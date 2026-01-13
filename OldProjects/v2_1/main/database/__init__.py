"""
Модуль для работы с базой данных PostgreSQL.
"""

from .connection import DatabasePool, init_db_pool, get_db_pool, close_db_pool
from .models import Base, init_models

__all__ = [
    'DatabasePool',
    'init_db_pool',
    'get_db_pool',
    'close_db_pool',
    'Base',
    'init_models',
]



