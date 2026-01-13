"""
Кастомные исключения.
"""


class ConfigurationError(Exception):
    """Ошибка конфигурации."""
    pass


class DatabaseError(Exception):
    """Ошибка базы данных."""
    pass
