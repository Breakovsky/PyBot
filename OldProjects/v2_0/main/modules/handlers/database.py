# main/modules/handlers/database.py

"""
Универсальный модуль для работы с базой данных.
Поддерживает PostgreSQL с connection pooling.
"""

import logging
import asyncpg
import asyncio
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from datetime import datetime

logger = logging.getLogger(__name__)


class DatabasePool:
    """Класс для управления пулом соединений PostgreSQL."""
    
    def __init__(self, dsn: str, min_size: int = 5, max_size: int = 20):
        """
        Инициализирует пул соединений.
        
        Args:
            dsn: Data Source Name для PostgreSQL (postgresql://user:pass@host:port/dbname)
            min_size: Минимальное количество соединений в пуле
            max_size: Максимальное количество соединений в пуле
        """
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None
    
    async def initialize(self):
        """Инициализирует пул соединений."""
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    self.dsn,
                    min_size=self.min_size,
                    max_size=self.max_size,
                    command_timeout=60,
                    server_settings={
                        'application_name': 'tbot',
                        'timezone': 'Europe/Moscow',
                    }
                )
                logger.info(f"Database pool initialized: min={self.min_size}, max={self.max_size}")
            except Exception as e:
                logger.error(f"Failed to initialize database pool: {e}")
                raise
    
    async def close(self):
        """Закрывает пул соединений."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Database pool closed")
    
    @asynccontextmanager
    async def acquire(self):
        """Контекстный менеджер для получения соединения из пула."""
        if self._pool is None:
            await self.initialize()
        
        async with self._pool.acquire() as connection:
            yield connection
    
    async def execute(self, query: str, *args) -> str:
        """
        Выполняет SQL-запрос (INSERT, UPDATE, DELETE) и возвращает результат.
        
        Args:
            query: SQL-запрос
            *args: Параметры запроса
            
        Returns:
            Результат выполнения (обычно количество затронутых строк)
        """
        async with self.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query: str, *args) -> List[asyncpg.Record]:
        """
        Выполняет SELECT-запрос и возвращает все строки.
        
        Args:
            query: SQL-запрос
            *args: Параметры запроса
            
        Returns:
            Список записей
        """
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        """
        Выполняет SELECT-запрос и возвращает одну строку.
        
        Args:
            query: SQL-запрос
            *args: Параметры запроса
            
        Returns:
            Одна запись или None
        """
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetchval(self, query: str, *args) -> Any:
        """
        Выполняет SELECT-запрос и возвращает одно значение.
        
        Args:
            query: SQL-запрос
            *args: Параметры запроса
            
        Returns:
            Одно значение или None
        """
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    async def execute_many(self, query: str, args_list: List[tuple]):
        """
        Выполняет запрос для множества наборов параметров.
        
        Args:
            query: SQL-запрос
            args_list: Список кортежей с параметрами
        """
        async with self.acquire() as conn:
            await conn.executemany(query, args_list)
    
    @property
    def pool(self) -> Optional[asyncpg.Pool]:
        """Возвращает пул соединений."""
        return self._pool


# Глобальный экземпляр пула
_db_pool: Optional[DatabasePool] = None


def get_db_pool() -> DatabasePool:
    """Возвращает глобальный экземпляр пула БД."""
    global _db_pool
    if _db_pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db_pool() first.")
    return _db_pool


def init_db_pool(dsn: str, min_size: int = 5, max_size: int = 20) -> DatabasePool:
    """
    Инициализирует глобальный пул БД.
    
    Args:
        dsn: Data Source Name для PostgreSQL
        min_size: Минимальное количество соединений
        max_size: Максимальное количество соединений
        
    Returns:
        Экземпляр DatabasePool
    """
    global _db_pool
    _db_pool = DatabasePool(dsn, min_size, max_size)
    return _db_pool


async def close_db_pool():
    """Закрывает глобальный пул БД."""
    global _db_pool
    if _db_pool:
        await _db_pool.close()
        _db_pool = None

