"""
Скрипт для добавления секретов в Windows Credential Manager
"""

import sys
import getpass
from pathlib import Path

# Добавляем путь к main
sys.path.insert(0, str(Path(__file__).parent.parent / "main"))

from config.security import get_security_manager

# Настройка кодировки для Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def add_secret():
    """Добавляет секрет в Windows Credential Manager."""
    print("=" * 60)
    print("Добавление секрета в Windows Credential Manager")
    print("=" * 60)
    print()
    
    security = get_security_manager()
    
    # Список известных секретов
    known_secrets = {
        'TOKEN': 'Токен Telegram бота (обязательно)',
        'DB_PASSWORD': 'Пароль базы данных (обязательно)',
        'JWT_SECRET': 'Секретный ключ для JWT токенов веб-интерфейса (обязательно)',
        'OTRS_PASSWORD': 'Пароль для OTRS API (опционально)',
        'SMTP_PASSWORD': 'Пароль SMTP (опционально)',
        'EXCEL_PASSWORD': 'Пароль для Excel файла (опционально)',
        'DOMAIN_BIND_PASSWORD': 'Пароль для Active Directory (опционально)',
    }
    
    print("Доступные секреты:")
    for i, (key, desc) in enumerate(known_secrets.items(), 1):
        exists = security.check_secret_exists(key)
        status = "✅ (установлен)" if exists else "❌ (не установлен)"
        print(f"  {i}. {key:<25} - {desc} {status}")
    print()
    
    # Выбор секрета
    key = input("Введите имя секрета (или номер): ").strip().upper()
    
    # Если ввели номер
    if key.isdigit():
        num = int(key)
        if 1 <= num <= len(known_secrets):
            key = list(known_secrets.keys())[num - 1]
        else:
            print(f"❌ Неверный номер. Выберите от 1 до {len(known_secrets)}")
            return
    
    if key not in known_secrets:
        print(f"❌ Неизвестный секрет: {key}")
        print(f"Доступные: {', '.join(known_secrets.keys())}")
        return
    
    # Проверяем, существует ли уже
    if security.check_secret_exists(key):
        update = input(f"⚠️  Секрет {key} уже существует. Обновить? (y/n): ").strip().lower()
        if update != 'y':
            print("Отменено")
            return
    
    # Получаем значение
    if key == 'JWT_SECRET':
        # Для JWT_SECRET можно сгенерировать автоматически
        generate = input("Сгенерировать случайный ключ? (y/n) [y]: ").strip().lower()
        if generate != 'n':
            import secrets
            value = secrets.token_hex(32)
            print(f"✅ Сгенерирован ключ: {value[:20]}...{value[-10:]}")
        else:
            value = getpass.getpass(f"Введите значение для {key}: ")
    else:
        value = getpass.getpass(f"Введите значение для {key}: ")
    
    if not value:
        print("❌ Значение не может быть пустым")
        return
    
    # Сохраняем
    try:
        security.set_secret(key, value)
        print(f"✅ Секрет {key} успешно сохранён!")
    except Exception as e:
        print(f"❌ Ошибка при сохранении: {e}")
        return


if __name__ == "__main__":
    try:
        add_secret()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

