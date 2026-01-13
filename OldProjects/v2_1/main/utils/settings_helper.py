"""
Вспомогательные функции для работы с настройками.
Читает из БД с fallback на .env для обратной совместимости.
"""

import os
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


async def get_setting_or_env(settings, key: str, default: Any = None, env_key: Optional[str] = None) -> Any:
    """
    Получает настройку из БД, если settings доступен, иначе из .env.
    
    Args:
        settings: Экземпляр Settings или None
        key: Ключ настройки в БД
        default: Значение по умолчанию
        env_key: Ключ в .env (если отличается от key)
        
    Returns:
        Значение настройки
    """
    env_key = env_key or key
    
    # Пытаемся прочитать из БД
    if settings is not None:
        try:
            value = await settings.get(key, None)
            if value is not None:
                return value
        except Exception as e:
            logger.debug(f"Failed to read {key} from DB: {e}, falling back to .env")
    
    # Fallback на .env
    return os.getenv(env_key, default)


async def get_setting_int_or_env(settings, key: str, default: int = 0, env_key: Optional[str] = None) -> int:
    """Получает целочисленную настройку из БД или .env."""
    value = await get_setting_or_env(settings, key, default, env_key)
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid integer value for {key}: {value}, using default: {default}")
        return default


async def get_setting_bool_or_env(settings, key: str, default: bool = False, env_key: Optional[str] = None) -> bool:
    """Получает булеву настройку из БД или .env."""
    value = await get_setting_or_env(settings, key, default, env_key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    return bool(value)

