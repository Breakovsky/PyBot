"""
Скрипт для проверки и удаления дубликатов сотрудников.
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


async def check_and_fix_duplicates():
    """Проверяет и исправляет дубликаты сотрудников."""
    
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
    print("Проверка дубликатов сотрудников")
    print("=" * 60 + "\n")
    
    async with db_pool.acquire() as conn:
        # Ищем дубликаты по ФИО
        duplicates = await conn.fetch("""
            SELECT 
                LOWER(full_name) as name_lower,
                COUNT(*) as count,
                array_agg(id ORDER BY id) as ids,
                array_agg(full_name ORDER BY id) as names
            FROM employees.employees
            GROUP BY LOWER(full_name)
            HAVING COUNT(*) > 1
            ORDER BY count DESC
        """)
        
        if not duplicates:
            print("✅ Дубликатов не найдено!")
            await db_pool.close()
            return
        
        print(f"⚠️  Найдено {len(duplicates)} групп дубликатов:\n")
        
        total_duplicates = 0
        for dup in duplicates:
            count = dup['count']
            ids = dup['ids']
            names = dup['names']
            total_duplicates += count - 1  # Оставляем один, остальные - дубликаты
            
            print(f"📋 {names[0]} ({count} записей):")
            for i, (emp_id, emp_name) in enumerate(zip(ids, names)):
                # Получаем дополнительную информацию
                emp_info = await conn.fetchrow("""
                    SELECT 
                        d.name as department,
                        w.name as workstation,
                        e.phone,
                        e.ad_account
                    FROM employees.employees e
                    LEFT JOIN employees.departments d ON e.department_id = d.id
                    LEFT JOIN employees.workstations w ON e.workstation_id = w.id
                    WHERE e.id = $1
                """, emp_id)
                
                dept = emp_info['department'] or 'N/A'
                ws = emp_info['workstation'] or 'N/A'
                phone = emp_info['phone'] or 'N/A'
                
                marker = "✅ ОСТАВИТЬ" if i == 0 else "❌ УДАЛИТЬ"
                print(f"   {marker} ID {emp_id}: {emp_name} | {dept} | {ws} | {phone}")
        
        print(f"\n📊 Всего дубликатов для удаления: {total_duplicates}")
        
        # Спрашиваем подтверждение
        response = input("\n❓ Удалить дубликаты? (yes/no): ").strip().lower()
        
        if response not in ['yes', 'y', 'да', 'д']:
            print("❌ Отменено")
            await db_pool.close()
            return
        
        # Удаляем дубликаты, оставляя первую запись
        deleted = 0
        for dup in duplicates:
            ids = dup['ids']
            # Оставляем первый ID, удаляем остальные
            for dup_id in ids[1:]:
                await conn.execute("DELETE FROM employees.employees WHERE id = $1", dup_id)
                deleted += 1
                print(f"🗑️  Удален дубликат ID {dup_id}: {dup['names'][0]}")
        
        print(f"\n✅ Удалено {deleted} дубликатов")
    
    await db_pool.close()
    print("\n✅ Проверка завершена!")


if __name__ == "__main__":
    try:
        asyncio.run(check_and_fix_duplicates())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

