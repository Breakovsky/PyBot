"""
Скрипт для просмотра текущих настроек из БД.
"""

import asyncio
import sys
import os
import io
from pathlib import Path
from urllib.parse import quote_plus

# Настройка кодировки для Windows
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except (AttributeError, ValueError):
        pass

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent.parent / "main"))

from dotenv import load_dotenv
from database.connection import init_db_pool, close_db_pool
from config.settings import init_settings
from config.security import get_security_manager


async def show_settings():
    """Показывает все настройки из БД."""
    
    # Загружаем .env если есть
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    
    # Подключаемся к БД
    security = get_security_manager()
    db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    db_user_escaped = quote_plus(db_user)
    if db_password:
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
    else:
        dsn = f"postgresql://{db_user_escaped}@{db_host}:{db_port}/{db_name}"
    
    db_pool = init_db_pool(dsn, min_size=2, max_size=5)
    await db_pool.initialize()
    
    settings = init_settings(db_pool)
    
    print("\n" + "=" * 60)
    print("Текущие настройки TBot v2.1")
    print("=" * 60 + "\n")
    
    # Получаем все настройки
    all_settings = await settings.get_all()
    
    if not all_settings:
        print("⚠️  Настроек в БД нет. Запустите: python scripts\\init_settings.py")
    else:
        # Группируем по категориям
        categories = {}
        for key, value in all_settings.items():
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT category, description FROM core.settings WHERE key = $1",
                    key
                )
                category = row['category'] if row else "general"
                description = row['description'] if row else ""
                
                if category not in categories:
                    categories[category] = []
                categories[category].append((key, value, description))
        
        # Выводим по категориям
        for category in sorted(categories.keys()):
            print(f"\n📁 {category.upper()}:")
            print("-" * 60)
            for key, value, description in sorted(categories[category]):
                desc_text = f" ({description})" if description else ""
                print(f"  {key:25} = {value}{desc_text}")
    
    print("\n" + "=" * 60)
    
    await db_pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(show_settings())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

