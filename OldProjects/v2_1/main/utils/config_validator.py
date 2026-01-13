"""
Валидация конфигурации.
"""

import os
from typing import Tuple, List
from config.security import get_security_manager


def validate_all_config() -> Tuple[bool, List[str]]:
    """
    Валидирует всю конфигурацию.
    
    Returns:
        Tuple (is_valid, errors)
    """
    errors = []
    
    # Проверяем обязательные секреты
    security = get_security_manager()
    required_secrets = ["TOKEN"]  # SUPERCHAT_TOKEN устарел, используйте TELEGRAM_CHAT_ID в БД
    
    for secret in required_secrets:
        if not security.get_secret(secret) and not os.getenv(secret):
            errors.append(f"{secret} not found in Credential Manager or environment")
    
    # Настройки БД имеют значения по умолчанию, поэтому не требуем их обязательного наличия
    # Проверяем только если они явно указаны как пустые строки
    db_host = os.getenv("DB_HOST")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    
    if db_host == "":  # Явно указано как пустая строка
        errors.append("DB_HOST is explicitly set to empty string")
    if db_name == "":  # Явно указано как пустая строка
        errors.append("DB_NAME is explicitly set to empty string")
    if db_user == "":  # Явно указано как пустая строка
        errors.append("DB_USER is explicitly set to empty string")
    
    return len(errors) == 0, errors


def get_config_summary() -> dict:
    """Получает сводку конфигурации."""
    return {
        'database': {
            'host': os.getenv("DB_HOST", "localhost"),
            'port': os.getenv("DB_PORT", "5432"),
            'name': os.getenv("DB_NAME", "tbot"),
            'user': os.getenv("DB_USER", "tbot"),
        },
        'cluster': {
            'enabled': os.getenv("CLUSTER_ENABLED", "false").lower() == "true",
        },
        'logging': {
            'level': os.getenv("LOG_LEVEL", "INFO"),
            'file': os.getenv("LOG_FILE", "logs/tbot.log"),
        }
    }
