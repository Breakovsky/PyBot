"""
Скрипт для создания пользователя веб-интерфейса
"""

import asyncio
import sys
import os
import bcrypt
from pathlib import Path

# Добавляем путь к main
sys.path.insert(0, str(Path(__file__).parent.parent / "main"))

from dotenv import load_dotenv
from database.connection import init_db_pool, close_db_pool
from config.security import get_security_manager

# Настройка кодировки для Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


async def create_user():
    """Создаёт пользователя в БД."""
    # Загружаем .env
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded .env from: {env_path}")
    else:
        print("⚠️  .env file not found, using environment variables")
    
    print("=" * 60)
    print("Создание пользователя для веб-интерфейса TBot v2.1")
    print("=" * 60)
    
    # Получаем данные для подключения к БД
    security = get_security_manager()
    db_password = security.get_secret("DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    from urllib.parse import quote_plus
    db_user_escaped = quote_plus(db_user)
    if db_password:
        db_password_escaped = quote_plus(db_password)
        dsn = f"postgresql://{db_user_escaped}:{db_password_escaped}@{db_host}:{db_port}/{db_name}"
    else:
        dsn = f"postgresql://{db_user_escaped}@{db_host}:{db_port}/{db_name}"
    
    # Инициализируем пул БД
    db_pool = init_db_pool(dsn, min_size=1, max_size=5)
    await db_pool.initialize()
    
    try:
        # Запрашиваем данные пользователя
        print("\nВведите данные нового пользователя:")
        email = input("Email: ").strip().lower()
        if not email:
            print("❌ Email не может быть пустым")
            return
        
        # Проверяем, существует ли пользователь
        async with db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT id, email FROM core.users WHERE email = $1
            """, email)
            
            if existing:
                print(f"\n⚠️  Пользователь с email {email} уже существует!")
                update = input("Обновить пароль? (y/n): ").strip().lower()
                if update != 'y':
                    print("Отменено")
                    return
                user_id = existing['id']
            else:
                full_name = input("ФИО (опционально): ").strip()
                is_admin_input = input("Сделать администратором? (y/n) [y]: ").strip().lower()
                is_admin = is_admin_input != 'n'
                user_id = None
        
        # Запрашиваем пароль
        password = input("Пароль: ").strip()
        if not password:
            print("❌ Пароль не может быть пустым")
            return
        
        # Хешируем пароль
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Создаём или обновляем пользователя
        async with db_pool.acquire() as conn:
            if user_id:
                # Обновляем существующего
                await conn.execute("""
                    UPDATE core.users
                    SET password_hash = $1, password_set_at = NOW()
                    WHERE id = $2
                """, password_hash, user_id)
                print(f"\n✅ Пароль пользователя {email} обновлён")
            else:
                # Создаём нового
                user_id = await conn.fetchval("""
                    INSERT INTO core.users (email, password_hash, full_name, is_active, is_admin, password_set_at)
                    VALUES ($1, $2, $3, TRUE, $4, NOW())
                    RETURNING id
                """, email, password_hash, full_name or None, is_admin)
                role = "администратор" if is_admin else "пользователь"
                print(f"\n✅ Пользователь {email} создан ({role})")
        
        print(f"   ID: {user_id}")
        print(f"   Email: {email}")
        if not user_id:  # Если это новый пользователь
            print(f"   Роль: {'Администратор' if is_admin else 'Пользователь'}")
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await close_db_pool()


if __name__ == "__main__":
    try:
        asyncio.run(create_user())
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

