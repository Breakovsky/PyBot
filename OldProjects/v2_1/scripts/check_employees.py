"""
Скрипт для проверки данных сотрудников в БД.
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


async def check_employees():
    """Проверяет данные сотрудников в БД."""
    
    # Загружаем .env если есть
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded .env from: {env_path}")
    else:
        print("⚠️  .env file not found, using environment variables and defaults")
    
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
    print("Проверка данных сотрудников")
    print("=" * 60 + "\n")
    
    # Проверяем настройки
    excel_topic_id = await settings.get("EXCEL_TOPIC_ID", "0")
    chat_id = await settings.get("TELEGRAM_CHAT_ID", "-1")
    
    print(f"📋 Настройки:")
    print(f"   TELEGRAM_CHAT_ID: {chat_id}")
    print(f"   EXCEL_TOPIC_ID: {excel_topic_id}")
    print()
    
    # Проверяем количество сотрудников
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM employees.employees")
        print(f"👥 Сотрудников в БД: {count}")
        
        if count == 0:
            print("\n⚠️  ВНИМАНИЕ: В таблице employees.employees нет данных!")
            print("   Для работы поиска нужно импортировать данные из Excel.")
            print("   Используйте веб-интерфейс или скрипт импорта.")
        else:
            # Показываем несколько примеров
            print(f"\n📊 Примеры сотрудников (первые 5):")
            rows = await conn.fetch("""
                SELECT 
                    e.id,
                    e.full_name,
                    d.name as department,
                    w.name as workstation,
                    e.phone
                FROM employees.employees e
                LEFT JOIN employees.departments d ON e.department_id = d.id
                LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                ORDER BY e.id
                LIMIT 5
            """)
            
            for row in rows:
                print(f"   • {row['full_name']} | {row['department'] or 'N/A'} | {row['workstation'] or 'N/A'} | {row['phone'] or 'N/A'}")
    
    await db_pool.close()
    print("\n✅ Проверка завершена!")


if __name__ == "__main__":
    try:
        asyncio.run(check_employees())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

