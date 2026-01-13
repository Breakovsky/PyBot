"""
Конфигурация приложения.
Настройки загружаются из БД и Windows Credential Manager.
"""

from .settings import Settings, get_settings
from .security import SecurityManager, get_security_manager

__all__ = [
    'Settings',
    'get_settings',
    'SecurityManager',
    'get_security_manager',
]



