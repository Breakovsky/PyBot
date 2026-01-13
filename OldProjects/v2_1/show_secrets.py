"""
Utility script to view secrets stored in Windows Credential Manager.
Shows which secrets are set (without revealing full values for security).
"""

import sys
from pathlib import Path

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

try:
    import keyring
except ImportError:
    print("ERROR: keyring is not installed!")
    print("Install: pip install keyring")
    sys.exit(1)

SERVICE_NAME = "TBot"

# Known secret keys
KNOWN_SECRETS = [
    'TOKEN',                    # Токен Telegram бота (обязательно)
    'DB_PASSWORD',              # Пароль базы данных (обязательно)
    'JWT_SECRET',               # Секрет для JWT токенов веб-интерфейса (обязательно)
    'OTRS_PASSWORD',            # Пароль OTRS (опционально)
    'SMTP_PASSWORD',            # Пароль SMTP (опционально)
    'EXCEL_PASSWORD',           # Пароль Excel файла (опционально)
    'DOMAIN_BIND_PASSWORD',    # Пароль Active Directory (опционально)
    # Устаревшие ключи (для совместимости, можно удалить из Windows Credential Manager)
    'TELEGRAM_BOT_TOKEN',       # Устаревший: используйте TOKEN
    'SUPERCHAT_TOKEN',          # Устаревший: используйте TELEGRAM_CHAT_ID в БД
    'WEB_SECRET_KEY',           # Устаревший: не используется
    'JWT_SECRET_KEY',           # Устаревший: используйте JWT_SECRET
    'SMTP_USER',                # Устаревший: теперь в БД (настройка SMTP_USER)
]


def mask_secret(value: str, show_chars: int = 4) -> str:
    """
    Mask secret value, showing only first and last characters.
    
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


def check_secret(key: str) -> tuple[bool, str]:
    """
    Check if secret exists and return masked value.
    
    Args:
        key: Secret key to check
        
    Returns:
        Tuple of (exists: bool, masked_value: str)
    """
    try:
        value = keyring.get_password(SERVICE_NAME, key)
        if value is None:
            return False, "(not set)"
        return True, mask_secret(value)
    except Exception as e:
        return False, f"(error: {str(e)[:30]})"


def list_all_secrets():
    """List all known secrets with their status."""
    print("=" * 70)
    print(f"Secrets stored in Windows Credential Manager")
    print(f"Service: {SERVICE_NAME}")
    print("=" * 70)
    print()
    
    print(f"{'Secret Key':<25} {'Status':<10} {'Preview':<30}")
    print("-" * 70)
    
    found_count = 0
    for key in KNOWN_SECRETS:
        exists, preview = check_secret(key)
        status = "SET" if exists else "NOT SET"
        status_color = "\033[92m" if exists else "\033[91m"  # Green or Red
        reset_color = "\033[0m"
        
        print(f"{key:<25} {status_color}{status:<10}{reset_color} {preview}")
        
        if exists:
            found_count += 1
    
    print("-" * 70)
    print(f"Total: {found_count}/{len(KNOWN_SECRETS)} secrets configured")
    print()
    
    if found_count == 0:
        print("WARNING: No secrets found!")
        print()
        print("To set secrets, use:")
        print('  python -c "import keyring; keyring.set_password(\'TBot\', \'KEY_NAME\', \'value\')"')
    else:
        print("Note: Full values are hidden for security.")
        print("To view full value, use get_secret() function in your code.")
    print()


def show_full_secret(key: str):
    """Show full secret value (use with caution!)."""
    try:
        value = keyring.get_password(SERVICE_NAME, key)
        if value is None:
            print(f"Secret '{key}' is not set.")
        else:
            print(f"Secret '{key}': {value}")
    except Exception as e:
        print(f"Error getting secret '{key}': {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Show full secret if key provided
        key = sys.argv[1].upper()
        if key in KNOWN_SECRETS:
            response = input(f"WARNING: This will show the FULL value of '{key}'. Continue? (yes/no): ")
            if response.lower() == 'yes':
                show_full_secret(key)
            else:
                print("Cancelled.")
        else:
            print(f"Unknown secret key: {key}")
            print(f"Known keys: {', '.join(KNOWN_SECRETS)}")
    else:
        # List all secrets
        list_all_secrets()

