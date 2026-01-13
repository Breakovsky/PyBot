"""
Управление настройками из базы данных.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class Settings:
    """Класс для работы с настройками из БД."""
    
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._cache: Dict[str, Any] = {}
        self._cache_ttl: Dict[str, datetime] = {}
        self._cache_duration = 300  # 5 минут
    
    async def get(self, key: str, default: Any = None, category: str = "general") -> Any:
        """
        Получить значение настройки.
        
        Args:
            key: Ключ настройки
            default: Значение по умолчанию
            category: Категория настройки
            
        Returns:
            Значение настройки или default
        """
        # Проверяем кэш
        if key in self._cache:
            if key in self._cache_ttl:
                if (datetime.now() - self._cache_ttl[key]).total_seconds() < self._cache_duration:
                    return self._cache[key]
        
        # Читаем из БД
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT value, category, is_secret
                FROM core.settings
                WHERE key = $1
                """,
                key
            )
            
            if row:
                value = row['value']
                self._cache[key] = value
                self._cache_ttl[key] = datetime.now()
                return value
        
        return default
    
    async def set(
        self,
        key: str,
        value: Any,
        category: str = "general",
        is_secret: bool = False,
        description: Optional[str] = None,
        updated_by: str = "system"
    ):
        """
        Установить значение настройки.
        
        Args:
            key: Ключ настройки
            value: Значение
            category: Категория
            is_secret: Является ли секретом
            description: Описание
            updated_by: Кто обновил
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.settings (key, value, category, is_secret, description, updated_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    category = EXCLUDED.category,
                    is_secret = EXCLUDED.is_secret,
                    description = EXCLUDED.description,
                    updated_at = NOW(),
                    updated_by = EXCLUDED.updated_by
                """,
                key, str(value), category, is_secret, description, updated_by
            )
        
        # Обновляем кэш
        self._cache[key] = value
        self._cache_ttl[key] = datetime.now()
        logger.info(f"Setting updated: {key} by {updated_by}")
    
    async def get_all(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Получить все настройки (опционально по категории)."""
        async with self.db_pool.acquire() as conn:
            if category:
                rows = await conn.fetch(
                    """
                    SELECT key, value, category, is_secret, description
                    FROM core.settings
                    WHERE category = $1 AND is_secret = FALSE
                    ORDER BY key
                    """,
                    category
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT key, value, category, is_secret, description
                    FROM core.settings
                    WHERE is_secret = FALSE
                    ORDER BY category, key
                    """
                )
            
            return {row['key']: row['value'] for row in rows}
    
    async def reload_cache(self):
        """Перезагрузить кэш из БД."""
        self._cache.clear()
        self._cache_ttl.clear()
        logger.info("Settings cache reloaded")


# Глобальный экземпляр
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Получить глобальный экземпляр Settings."""
    global _settings
    if _settings is None:
        raise RuntimeError("Settings not initialized. Call init_settings() first.")
    return _settings


def init_settings(db_pool) -> Settings:
    """Инициализировать Settings."""
    global _settings
    _settings = Settings(db_pool)
    return _settings



