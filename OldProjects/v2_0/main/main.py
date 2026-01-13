# main/main.py

"""
Точка входа для Telegram бота.
Поддерживает запуск как в Docker, так и на Windows.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from dotenv import load_dotenv

from utils.logger import setup_logger
from modules.aiogram_bot import main as aiogram_main


def load_environment():
    """Загружает переменные окружения из .env файла."""
    env_paths = [
        Path(__file__).parent.parent / ".env",  # TelegramBot/.env
        Path(__file__).parent / ".env",  # TelegramBot/main/.env
        Path("/app/.env"),  # Docker контейнер
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            logging.info(f"Loaded environment from: {env_path}")
            return
    
    logging.warning("No .env file found, using environment variables")


def setup_signal_handlers():
    """Настраивает обработчики сигналов для корректного завершения."""
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down gracefully...")
        sys.exit(0)
    
    # Обработка SIGTERM (Docker stop)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)
    
    # Обработка SIGINT (Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)


def start_web_admin():
    """Запускает веб-панель администрирования в фоновом потоке."""
    try:
        from modules.web_admin import start_web_admin_thread
        start_web_admin_thread()
        logging.info("Web admin panel started on http://localhost:555")
    except Exception as e:
        logging.error(f"Failed to start web admin panel: {e}")


def main():
    """Главная функция запуска бота."""
    # Загружаем переменные окружения
    load_environment()
    
    # Настраиваем логирование
    log_file = os.getenv("LOG_FILE", "bot_log.log")
    log_level = os.getenv("LOG_LEVEL", "DEBUG")
    
    # Преобразуем строковый уровень в logging.LEVEL
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = level_map.get(log_level.upper(), logging.DEBUG)
    
    setup_logger(log_file=log_file, level=log_level)
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 50)
    logger.info("Starting Telegram Bot")
    logger.info("=" * 50)
    
    # Настраиваем обработчики сигналов
    setup_signal_handlers()
    
    # Запускаем веб-панель администрирования
    start_web_admin()
    
    try:
        # Запускаем бота
        asyncio.run(aiogram_main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
