"""
Конфигурация бота.
Загружает настройки из переменных окружения или .env файла.
"""
import os
import logging
from pathlib import Path
from typing import List
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Часовой пояс UTC+3 (Москва)
MSK_TIMEZONE = timezone(timedelta(hours=3))


def now_msk() -> datetime:
    """Возвращает текущее время в часовом поясе MSK (UTC+3)."""
    return datetime.now(MSK_TIMEZONE)

logger = logging.getLogger(__name__)


def load_env_file():
    """Загружает .env файл из возможных местоположений."""
    env_paths = [
        Path(__file__).parent.parent.parent / ".env",  # TelegramBot/.env
        Path(__file__).parent.parent / ".env",  # TelegramBot/main/.env
        Path(__file__).parent / ".env",  # TelegramBot/main/assets/.env
        Path("/app/.env"),  # Docker контейнер
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(f"Loaded .env from: {env_path}")
            return
    
    logger.warning("No .env file found, using environment variables or defaults")


def get_env_str(key: str, default: str = "") -> str:
    """Получает строковую переменную окружения."""
    value = os.getenv(key, default)
    if not value and not default:
        logger.warning(f"Environment variable {key} is not set")
    return value


def get_env_int(key: str, default: int = 0) -> int:
    """Получает целочисленную переменную окружения."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.error(f"Invalid integer value for {key}: {value}, using default: {default}")
        return default


def get_env_list_int(key: str, default: List[int]) -> List[int]:
    """Получает список целых чисел из переменной окружения (через запятую)."""
    value = os.getenv(key)
    if not value:
        return default
    try:
        return [int(x.strip()) for x in value.split(",") if x.strip()]
    except ValueError as e:
        logger.error(f"Invalid list format for {key}: {e}, using default: {default}")
        return default


# Загружаем .env файл
load_env_file()

# Токены и пароли (обязательные)
TOKEN = get_env_str("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable is required!")

SUPERCHAT_TOKEN = get_env_str("SUPERCHAT_TOKEN")
if not SUPERCHAT_TOKEN:
    raise ValueError("SUPERCHAT_TOKEN environment variable is required!")

EXCEL_PASSWORD = get_env_str("EXCEL_PASSWORD", "")

# ID топиков (темы в форуме)
EXCEL_TOPIC_ID = get_env_int("EXCEL_TOPIC_ID", 38)
PING_TOPIC_ID = get_env_int("PING_TOPIC_ID", 40)
BOT_TOPIC_ID = get_env_int("BOT_TOPIC_ID", 42)
METRICS_TOPIC_ID = get_env_int("METRICS_TOPIC_ID", 0)  # Топик для метрик мониторинга
TASKS_TOPIC_ID = get_env_int("TASKS_TOPIC_ID", 145)  # Топик для заявок OTRS

# OTRS Configuration
OTRS_URL = get_env_str("OTRS_URL", "")  # URL OTRS сервера (например: https://otrs.company.ru)
OTRS_USERNAME = get_env_str("OTRS_USERNAME", "")  # Логин для API
OTRS_PASSWORD = get_env_str("OTRS_PASSWORD", "")  # Пароль для API
OTRS_WEBSERVICE = get_env_str("OTRS_WEBSERVICE", "TelegramBot")  # Имя Web Service

# SMTP Configuration (для отправки кодов верификации)
SMTP_HOST = get_env_str("SMTP_HOST", "")  # Сервер SMTP (например: smtp.company.ru)
SMTP_PORT = get_env_int("SMTP_PORT", 587)  # Порт (587 для TLS, 465 для SSL)
SMTP_USER = get_env_str("SMTP_USER", "")  # Email отправителя
SMTP_PASSWORD = get_env_str("SMTP_PASSWORD", "")  # Пароль
SMTP_FROM_NAME = get_env_str("SMTP_FROM_NAME", "OTRS Bot")  # Имя отправителя
SMTP_USE_TLS = get_env_str("SMTP_USE_TLS", "true").lower() == "true"  # Использовать TLS

# Active Directory Configuration
DOMAIN_SERVER = get_env_str("DOMAIN_SERVER", "")  # IP или FQDN контроллера домена
DOMAIN_PORT = get_env_int("DOMAIN_PORT", 389)  # 389 для LDAP, 636 для LDAPS
DOMAIN_BASE_DN = get_env_str("DOMAIN_BASE_DN", "")  # Например: dc=meb52,dc=local
DOMAIN_BIND_DN = get_env_str("DOMAIN_BIND_DN", "")  # Может быть пустым для анонимного подключения
DOMAIN_BIND_PASSWORD = get_env_str("DOMAIN_BIND_PASSWORD", "")  # Может быть пустым

# Пути к файлам
EXCEL_FILE_PATH = get_env_str(
    "EXCEL_FILE_PATH",
    r"\\fs\it$\6. Наша\1. Общая\3. Общая документация ИТ\ВсеПК.xlsx"
)

# В Docker используем относительный путь, если не указан абсолютный
_ip_default = r"main\assets\ip_addresses.xml"
if os.path.exists("/app"):  # Docker контейнер
    _ip_default = "/app/main/assets/ip_addresses.xml"

IP_ADDRESSES_PATH = get_env_str("IP_ADDRESSES_PATH", _ip_default)

# Сообщения
BOT_STARTUP_MESSAGE = get_env_str(
    "BOT_STARTUP_MESSAGE",
    "🤖 Бот включился и готов к работе\\!"
)

# Разрешенные топики
ALLOWED_THREADS = get_env_list_int("ALLOWED_THREADS", [38, 40, 42, 164])

# PostgreSQL Configuration
DB_HOST = get_env_str("DB_HOST", "localhost")
DB_PORT = get_env_int("DB_PORT", 5432)
DB_NAME = get_env_str("DB_NAME", "tbot")
DB_USER = get_env_str("DB_USER", "tbot")
DB_PASSWORD = get_env_str("DB_PASSWORD", "")
DB_POOL_MIN_SIZE = get_env_int("DB_POOL_MIN_SIZE", 5)
DB_POOL_MAX_SIZE = get_env_int("DB_POOL_MAX_SIZE", 20)

# Формируем DSN для PostgreSQL
if DB_PASSWORD:
    DB_DSN = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
else:
    DB_DSN = f"postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Валидация конфигурации
def validate_config():
    """Проверяет корректность конфигурации."""
    errors = []
    
    if not TOKEN:
        errors.append("TOKEN is not set")
    
    if not SUPERCHAT_TOKEN:
        errors.append("SUPERCHAT_TOKEN is not set")
    
    try:
        chat_id = int(SUPERCHAT_TOKEN)
        if chat_id >= 0:
            errors.append("SUPERCHAT_TOKEN should be negative (chat ID)")
    except ValueError:
        errors.append("SUPERCHAT_TOKEN must be a valid integer")
    
    if errors:
        error_msg = "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    logger.info("Configuration validated successfully")


# Выполняем валидацию при импорте
try:
    validate_config()
except Exception as e:
    logger.error(f"Configuration validation failed: {e}")
    # В production можно поднять исключение, но для совместимости оставляем warning