"""
Скрипт для очистки таблицы сотрудников перед полным переимпортом.
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


async def clear_employees():
    """Очищает таблицу сотрудников."""
    
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
    
    print("\n" + "=" * 60)
    print("Очистка таблицы сотрудников")
    print("=" * 60 + "\n")
    
    async with db_pool.acquire() as conn:
        # Проверяем количество записей
        count = await conn.fetchval("SELECT COUNT(*) FROM employees.employees")
        print(f"📊 Текущее количество сотрудников: {count}")
        
        if count == 0:
            print("✅ Таблица уже пуста")
            await db_pool.close()
            return
        
        # Спрашиваем подтверждение
        print(f"\n⚠️  ВНИМАНИЕ: Будет удалено {count} записей!")
        response = input("❓ Продолжить? (yes/no): ").strip().lower()
        
        if response not in ['yes', 'y', 'да', 'д']:
            print("❌ Отменено")
            await db_pool.close()
            return
        
        # Удаляем все записи
        await conn.execute("DELETE FROM employees.employees")
        print(f"🗑️  Удалено {count} сотрудников")
        
        # Сбрасываем последовательность для employees
        await conn.execute("ALTER SEQUENCE employees.employees_id_seq RESTART WITH 1")
        print("🔄 Сброшена последовательность ID для сотрудников (начнется с 1)")
        
        # Также очищаем рабочие станции и отделы (опционально)
        clear_ws = input("\n❓ Очистить также рабочие станции? (yes/no, по умолчанию no): ").strip().lower()
        if clear_ws in ['yes', 'y', 'да', 'д']:
            ws_count = await conn.fetchval("SELECT COUNT(*) FROM employees.workstations")
            await conn.execute("DELETE FROM employees.workstations")
            await conn.execute("ALTER SEQUENCE employees.workstations_id_seq RESTART WITH 1")
            print(f"🗑️  Удалено {ws_count} рабочих станций")
            print("🔄 Сброшена последовательность ID для рабочих станций (начнется с 1)")
        
        clear_dept = input("❓ Очистить также отделы? (yes/no, по умолчанию no): ").strip().lower()
        if clear_dept in ['yes', 'y', 'да', 'д']:
            dept_count = await conn.fetchval("SELECT COUNT(*) FROM employees.departments")
            await conn.execute("DELETE FROM employees.departments")
            await conn.execute("ALTER SEQUENCE employees.departments_id_seq RESTART WITH 1")
            print(f"🗑️  Удалено {dept_count} отделов")
            print("🔄 Сброшена последовательность ID для отделов (начнется с 1)")
    
    await db_pool.close()
    print("\n✅ Очистка завершена!")


if __name__ == "__main__":
    try:
        asyncio.run(clear_employees())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

