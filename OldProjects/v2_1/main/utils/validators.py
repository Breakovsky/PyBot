"""
Validation utilities for TBot v2.1
"""

import re
from typing import Optional, List
from email.utils import parseaddr


def is_valid_email(email: str) -> bool:
    """
    Validate email address.
    
    Args:
        email: Email address to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not email or not isinstance(email, str):
        return False
    
    # Basic email regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        return False
    
    # Additional check using parseaddr
    name, addr = parseaddr(email)
    return bool(addr and '@' in addr)


def is_valid_phone(phone: str) -> bool:
    """
    Validate phone number (basic validation).
    
    Args:
        phone: Phone number to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not phone or not isinstance(phone, str):
        return False
    
    # Remove common separators
    cleaned = re.sub(r'[\s\-\(\)\+]', '', phone)
    
    # Check if it's digits (with optional leading +)
    if cleaned.startswith('+'):
        cleaned = cleaned[1:]
    
    # Phone should be 7-15 digits
    return cleaned.isdigit() and 7 <= len(cleaned) <= 15


def is_valid_ip(ip: str) -> bool:
    """
    Validate IP address (IPv4).
    
    Args:
        ip: IP address to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not ip or not isinstance(ip, str):
        return False
    
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    
    parts = ip.split('.')
    return all(0 <= int(part) <= 255 for part in parts)


def is_valid_hostname(hostname: str) -> bool:
    """
    Validate hostname.
    
    Args:
        hostname: Hostname to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not hostname or not isinstance(hostname, str):
        return False
    
    if len(hostname) > 253:
        return False
    
    # Basic hostname validation
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
    return bool(re.match(pattern, hostname))


def sanitize_string(value: str, max_length: Optional[int] = None) -> str:
    """
    Sanitize string input.
    
    Args:
        value: String to sanitize
        max_length: Optional maximum length
        
    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Remove null bytes and control characters (except newline and tab)
    value = ''.join(c for c in value if ord(c) >= 32 or c in '\n\t')
    
    # Trim whitespace
    value = value.strip()
    
    # Limit length
    if max_length and len(value) > max_length:
        value = value[:max_length]
    
    return value


def validate_required_fields(data: dict, required_fields: List[str]) -> tuple[bool, Optional[str]]:
    """
    Validate that all required fields are present in data.
    
    Args:
        data: Data dictionary to validate
        required_fields: List of required field names
        
    Returns:
        Tuple of (is_valid: bool, error_message: Optional[str])
    """
    missing = [field for field in required_fields if field not in data or data[field] is None]
    
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    
    return True, None

