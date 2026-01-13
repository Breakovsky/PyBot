"""
Скрипт для применения миграции: делает full_name опциональным
"""
import asyncio
import sys
from pathlib import Path
import asyncpg
from urllib.parse import quote_plus
import os
from dotenv import load_dotenv
import keyring

# Загружаем .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

async def migrate():
    """Применяет миграцию для full_name."""
    # Получаем пароль из keyring или .env
    db_password = keyring.get_password("tbot", "DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    # Подключаемся напрямую через asyncpg
    conn = await asyncpg.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=db_name
    )
    
    try:
        await conn.execute("ALTER TABLE employees.employees ALTER COLUMN full_name DROP NOT NULL")
        print("[OK] Migration applied: full_name is now optional")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())

