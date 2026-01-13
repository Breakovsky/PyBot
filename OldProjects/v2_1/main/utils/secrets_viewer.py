"""
Utility functions to view secrets (for development/debugging).
"""

import keyring
from typing import Optional
from .logger import get_logger

logger = get_logger(__name__)

SERVICE_NAME = "TBot"


def mask_secret(value: str, show_chars: int = 4) -> str:
    """
    Mask secret value for safe display.
    
    Args:
        value: Secret value to mask
        show_chars: Number of characters to show at start and end
        
    Returns:
        Masked secret (e.g., "abcd...xyz")
    """
    if not value:
        return "(empty)"
    
    if len(value) <= show_chars * 2:
        return "*" * len(value)
    
    return value[:show_chars] + "..." + "*" * (len(value) - show_chars * 2 - 3) + value[-show_chars:]


def check_secret_status(key: str) -> tuple[bool, Optional[str]]:
    """
    Check if secret exists and return masked value.
    
    Args:
        key: Secret key to check
        
    Returns:
        Tuple of (exists: bool, masked_value: Optional[str])
    """
    try:
        value = keyring.get_password(SERVICE_NAME, key)
        if value is None:
            return False, None
        return True, mask_secret(value)
    except Exception as e:
        logger.error(f"Error checking secret '{key}': {e}")
        return False, None


def list_secrets_status(keys: list[str]) -> dict[str, tuple[bool, Optional[str]]]:
    """
    Check status of multiple secrets.
    
    Args:
        keys: List of secret keys to check
        
    Returns:
        Dictionary mapping key -> (exists: bool, masked_value: Optional[str])
    """
    result = {}
    for key in keys:
        result[key] = check_secret_status(key)
    return result

