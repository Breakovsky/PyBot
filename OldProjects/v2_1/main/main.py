"""
Точка входа для TBot v2.1
Production-ready версия с поддержкой кластеризации.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from dotenv import load_dotenv

# Настройка путей
sys.path.insert(0, str(Path(__file__).parent))

from utils.logger import setup_logger
from utils.errors import ConfigurationError, DatabaseError
from utils.config_validator import validate_all_config, get_config_summary
from utils.health_check import get_health_checker
from database.connection import init_db_pool, close_db_pool, get_db_pool
from config.settings import init_settings
from config.security import get_security_manager
from services.cluster_coordinator import ClusterCoordinator
try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None


def load_environment():
    """Загружает переменные окружения."""
    env_paths = [
        Path(__file__).parent.parent / ".env",
        Path(__file__).parent / ".env",
        Path("/app/.env"),  # Docker
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            logging.info(f"Loaded environment from: {env_path}")
            return
    
    # Если .env не найден, используем значения по умолчанию
    import os
    if not os.getenv("DB_HOST"):
        os.environ.setdefault("DB_HOST", "localhost")
    if not os.getenv("DB_PORT"):
        os.environ.setdefault("DB_PORT", "5432")


# Глобальные переменные для graceful shutdown
_shutdown_event = asyncio.Event()
_services = {}


def check_single_instance():
    """Проверяет, что запущен только один экземпляр бота."""
    lock_file = Path(__file__).parent.parent / "bot.lock"
    
    if sys.platform == "win32":
        # Windows: используем файл блокировки
        try:
            if lock_file.exists():
                # Проверяем, жив ли процесс
                try:
                    pid = int(lock_file.read_text().strip())
                    # Проверяем существование процесса
                    try:
                        import psutil
                        if psutil.pid_exists(pid):
                            # Проверяем, что это действительно наш процесс
                            proc = psutil.Process(pid)
                            if "main.py" in " ".join(proc.cmdline()):
                                logger.error(f"Another bot instance is already running (PID: {pid})")
                                logger.error("Please stop it first: .\\bot.ps1 stop")
                                sys.exit(1)
                    except ImportError:
                        # psutil не установлен - пропускаем проверку процесса
                        logger.debug("psutil not installed, skipping process check")
                    except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
                        # Процесс не существует или нет доступа - удаляем старый lock файл
                        lock_file.unlink(missing_ok=True)
                except (ValueError, FileNotFoundError):
                    # Не удалось прочитать PID - удаляем файл
                    lock_file.unlink(missing_ok=True)
            
            # Создаем новый lock файл
            lock_file.write_text(str(os.getpid()))
            logger.debug(f"Lock file created: {lock_file} (PID: {os.getpid()})")
        except Exception as e:
            logger.warning(f"Could not create lock file: {e}")
    else:
        # Unix: используем fcntl
        try:
            import fcntl
            lock_fd = open(lock_file, 'w')
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()
            logger.debug(f"Lock file created: {lock_file} (PID: {os.getpid()})")
        except (IOError, OSError) as e:
            logger.error(f"Another bot instance is already running: {e}")
            logger.error("Please stop it first")
            sys.exit(1)


def cleanup_lock_file():
    """Удаляет файл блокировки."""
    lock_file = Path(__file__).parent.parent / "bot.lock"
    try:
        if lock_file.exists():
            lock_file.unlink()
            logger.debug("Lock file removed")
    except Exception as e:
        logger.warning(f"Could not remove lock file: {e}")


def setup_signal_handlers():
    """Настраивает обработчики сигналов для graceful shutdown."""
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        _shutdown_event.set()
    
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    else:
        # Windows
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def init_services():
    """Инициализирует все сервисы."""
    logger.info("Initializing services...")
    
    # Валидация конфигурации
    try:
        validate_all_config()
    except ConfigurationError as e:
        error_msg = f"Configuration validation failed:\n  {str(e)}"
        logger.error(error_msg)
        raise ConfigurationError(error_msg)
    
    # Инициализация базы данных
    security = get_security_manager()
    db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    from urllib.parse import quote_plus
    db_user_escaped = quote_plus(db_user)
    if db_password:
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
    else:
        dsn = f"postgresql://{db_user_escaped}@{db_host}:{db_port}/{db_name}"
    
    db_pool = init_db_pool(dsn, min_size=5, max_size=20)
    await db_pool.initialize()
    logger.info("Database pool initialized")
    
    # Инициализация Settings
    settings = init_settings(db_pool)
    logger.info("Settings initialized")
    
    # Инициализация кластера (если включен)
    cluster_enabled = os.getenv("CLUSTER_ENABLED", "false").lower() == "true"
    redis_client = None
    cluster_coordinator = None
    
    if cluster_enabled:
        if aioredis is None:
            logger.warning("Redis not installed. Cluster features disabled. Install with: pip install redis")
            cluster_enabled = False
        else:
            try:
                redis_host = os.getenv("REDIS_HOST", "localhost")
                redis_port = int(os.getenv("REDIS_PORT", "6379"))
                redis_db = int(os.getenv("REDIS_DB", "0"))
                
                redis_client = aioredis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    decode_responses=True
                )
                
                # Проверяем подключение к Redis
                await redis_client.ping()
                logger.info("Redis connection established")
                
                # Инициализируем координатор кластера
                node_id = os.getenv("CLUSTER_NODE_ID", f"node-{os.getpid()}")
                node_type = os.getenv("CLUSTER_NODE_TYPE", "bot")
                
                cluster_coordinator = ClusterCoordinator(
                    node_id=node_id,
                    node_type=node_type,
                    redis_client=redis_client,
                    db_pool=db_pool,
                    heartbeat_interval=int(os.getenv("CLUSTER_HEARTBEAT_INTERVAL", "30")),
                    leader_ttl=int(os.getenv("CLUSTER_LEADER_TTL", "60"))
                )
                await cluster_coordinator.start()
                logger.info(f"Cluster coordinator started: {node_id} ({node_type})")
                
                # Регистрируем health check для Redis
                async def redis_check():
                    return await health_checker.check_redis(redis_client)
                health_checker.register_check('redis', redis_check)
                
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Cluster features disabled.")
                if redis_client:
                    try:
                        await redis_client.close()
                    except:
                        pass
                redis_client = None
                cluster_coordinator = None
    else:
        logger.info("Cluster features disabled (CLUSTER_ENABLED=false)")
    
    # Health checks
    health_checker = get_health_checker()
    health_checker.register_check('database', lambda: health_checker.check_database(db_pool))
    
    all_healthy = await health_checker.check_all()
    if not all_healthy:
        logger.warning("Some health checks failed, but continuing...")
    else:
        logger.info("All health checks passed")
    
    # Инициализация Telegram Bot
    from services.telegram_bot import TelegramBotService
    telegram_bot = TelegramBotService(db_pool)
    _services['telegram_bot'] = telegram_bot
    
    return {
        'db_pool': db_pool,
        'settings': settings,
        'telegram_bot': telegram_bot,
        'cluster_coordinator': cluster_coordinator,
        'redis_client': redis_client,
        'health_checker': health_checker
    }


async def cleanup_services(services):
    """Очищает ресурсы и останавливает сервисы."""
    logger.info("Cleaning up services...")
    
    # Останавливаем Telegram Bot
    if 'telegram_bot' in services:
        try:
            await services['telegram_bot'].stop()
        except Exception as e:
            logger.error(f"Error stopping Telegram Bot: {e}", exc_info=True)
    
    # Останавливаем координатор кластера
    if services.get('cluster_coordinator'):
        try:
            await services['cluster_coordinator'].stop()
        except Exception as e:
            logger.error(f"Error stopping cluster coordinator: {e}", exc_info=True)
    
    # Останавливаем сервис бэкапов
    if services.get('backup_service'):
        try:
            await services['backup_service'].stop()
        except Exception as e:
            logger.error(f"Error stopping backup service: {e}", exc_info=True)
    
    # Закрываем Redis
    if services.get('redis_client'):
        try:
            await services['redis_client'].close()
        except Exception as e:
            logger.error(f"Error closing Redis: {e}", exc_info=True)
    
    # Закрываем пул БД
    if services.get('db_pool'):
        try:
            await asyncio.wait_for(close_db_pool(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Database pool close timeout")
        except Exception as e:
            logger.error(f"Error closing database pool: {e}", exc_info=True)
    
    logger.info("Cleanup completed")


async def main():
    """Главная функция."""
    # Загружаем переменные окружения
    load_environment()
    
    # Настраиваем логирование
    setup_logger()
    global logger
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 50)
    logger.info("Starting TBot v2.1")
    logger.info("=" * 50)
    
    # Проверяем, что запущен только один экземпляр
    try:
        check_single_instance()
    except ImportError:
        # psutil не установлен - пропускаем проверку
        logger.warning("psutil not installed, skipping single instance check")
        logger.warning("Install with: pip install psutil")
    
    # Настраиваем обработчики сигналов
    setup_signal_handlers()
    
    # Выводим сводку конфигурации
    try:
        config_summary = get_config_summary()
        logger.info("Configuration summary:")
        for key, value in config_summary.items():
            logger.info(f"  {key}: {value}")
    except Exception as e:
        logger.warning(f"Could not get config summary: {e}")
    
    services = None
    try:
        # Инициализируем сервисы
        services = await init_services()
        logger.info("All services started. Starting Telegram Bot...")
        
        # Запускаем Telegram Bot в фоне
        telegram_bot = services['telegram_bot']
        bot_task = asyncio.create_task(telegram_bot.start())
        
        # Запускаем сервис бэкапов
        from services.backup_service import BackupService
        backup_service = BackupService(services['db_pool'])
        await backup_service.start()
        services['backup_service'] = backup_service
        
        # Запускаем веб-сервер (опционально)
        web_enabled = os.getenv("WEB_ENABLED", "true").lower() == "true"
        web_server_task = None
        web_server = None
        if web_enabled:
            try:
                import uvicorn
                
                web_host = os.getenv("WEB_HOST", "0.0.0.0")
                web_port = int(os.getenv("WEB_PORT", "8000"))
                
                # Создаём веб-приложение с уже инициализированными сервисами
                from api.app import create_app
                from config.security import get_security_manager
                web_app = create_app(
                    db_pool=services['db_pool'],
                    settings=services['settings'],
                    security_manager=get_security_manager()
                )
                
                # Запускаем веб-сервер в фоне
                config = uvicorn.Config(
                    app=web_app,
                    host=web_host,
                    port=web_port,
                    log_level="info"
                )
                web_server = uvicorn.Server(config)
                
                # Обёртка для логирования ошибок запуска
                async def run_web_server():
                    try:
                        logger.info(f"Starting web server on http://{web_host}:{web_port}...")
                        await web_server.serve()
                    except Exception as e:
                        logger.error(f"Web server error: {e}", exc_info=True)
                        raise
                
                web_server_task = asyncio.create_task(run_web_server())
                logger.info(f"Web server task created (starting on http://{web_host}:{web_port})")
            except Exception as e:
                logger.warning(f"Failed to start web server: {e}")
                logger.warning("Web interface will not be available")
        
        # Ждем сигнала завершения
        try:
            await _shutdown_event.wait()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            _shutdown_event.set()
        
        # Останавливаем веб-сервер
        if 'web_server_task' in locals() and web_server_task and not web_server_task.done():
            logger.info("Stopping web server...")
            try:
                if 'web_server' in locals() and web_server:
                    web_server.should_exit = True
                await asyncio.wait_for(web_server_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Web server stop timeout")
                web_server_task.cancel()
            except Exception as e:
                logger.warning(f"Error stopping web server: {e}")
        
        # Останавливаем бота
        logger.info("Stopping Telegram Bot...")
        await telegram_bot.stop()
        
        # Ждем завершения задачи
        try:
            await asyncio.wait_for(bot_task, timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Bot stop timeout")
            bot_task.cancel()
        
    except Exception as e:
        logger.error(f"Error in main: {e}", exc_info=True)
        raise
    finally:
        # Очищаем ресурсы
        if services:
            await cleanup_services(services)
        cleanup_lock_file()
        logger.info("TBot v2.1 stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
