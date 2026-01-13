"""
Управление секретами через Windows Credential Manager.
"""

import logging
import keyring
from typing import Optional

logger = logging.getLogger(__name__)

# Имя сервиса для keyring
SERVICE_NAME = "TBot"


class SecurityManager:
    """Класс для работы с секретами через Windows Credential Manager."""
    
    def __init__(self, service_name: str = SERVICE_NAME):
        self.service_name = service_name
    
    def get_secret(self, key: str) -> Optional[str]:
        """
        Получить секрет из Windows Credential Manager.
        
        Args:
            key: Ключ секрета
            
        Returns:
            Значение секрета или None
        """
        try:
            value = keyring.get_password(self.service_name, key)
            if value:
                logger.debug(f"Secret retrieved: {key}")
            return value
        except Exception as e:
            logger.error(f"Error getting secret {key}: {e}")
            return None
    
    def set_secret(self, key: str, value: str):
        """
        Сохранить секрет в Windows Credential Manager.
        
        Args:
            key: Ключ секрета
            value: Значение секрета
        """
        try:
            keyring.set_password(self.service_name, key, value)
            logger.info(f"Secret saved: {key}")
        except Exception as e:
            logger.error(f"Error saving secret {key}: {e}")
            raise
    
    def delete_secret(self, key: str):
        """
        Удалить секрет из Windows Credential Manager.
        
        Args:
            key: Ключ секрета
        """
        try:
            keyring.delete_password(self.service_name, key)
            logger.info(f"Secret deleted: {key}")
        except keyring.errors.PasswordDeleteError:
            logger.warning(f"Secret {key} not found for deletion")
        except Exception as e:
            logger.error(f"Error deleting secret {key}: {e}")
            raise
    
    def list_secrets(self) -> list:
        """Получить список всех ключей секретов (если поддерживается)."""
        # Windows Credential Manager не поддерживает список напрямую
        # Можно хранить список в БД или файле
        return []
    
    def check_secret_exists(self, key: str) -> bool:
        """
        Проверить, существует ли секрет.
        
        Args:
            key: Ключ секрета
            
        Returns:
            True если секрет существует, False иначе
        """
        try:
            value = keyring.get_password(self.service_name, key)
            return value is not None
        except Exception:
            return False
    
    def get_secret_masked(self, key: str, show_chars: int = 4) -> Optional[str]:
        """
        Получить замаскированное значение секрета (для отображения).
        
        Args:
            key: Ключ секрета
            show_chars: Количество символов для отображения в начале и конце
            
        Returns:
            Замаскированное значение или None
        """
        try:
            value = keyring.get_password(self.service_name, key)
            if value is None:
                return None
            
            if len(value) <= show_chars * 2:
                return "*" * len(value)
            
            return value[:show_chars] + "..." + "*" * (len(value) - show_chars * 2 - 3) + value[-show_chars:]
        except Exception as e:
            logger.error(f"Error getting masked secret {key}: {e}")
            return None


# Глобальный экземпляр
_security_manager: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    """Получить глобальный экземпляр SecurityManager."""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecurityManager()
    return _security_manager


