"""
Скрипт для проверки состояния базы данных после миграции.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import quote_plus
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db_password():
    """Получает пароль БД из keyring или переменных окружения."""
    try:
        import keyring
        password = keyring.get_password("TBot", "DB_PASSWORD")
        if password:
            return password
    except:
        pass
    
    return os.getenv("DB_PASSWORD", "")


def check_database():
    """Проверяет состояние базы данных."""
    load_dotenv()
    
    # Получаем параметры подключения
    db_password = get_db_password()
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    print("=" * 60)
    print("Проверка состояния базы данных")
    print("=" * 60)
    print(f"Подключение к: {db_host}:{db_port}/{db_name} как {db_user}")
    print()
    
    try:
        # Подключаемся через psycopg2
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            database=db_name,
            user=db_user,
            password=db_password
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Проверяем схемы
        print("1. Схемы в базе данных:")
        cur.execute("""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name
        """)
        schemas = cur.fetchall()
        for row in schemas:
            print(f"   ✓ {row['schema_name']}")
        print()
        
        # 2. Проверяем версию миграции
        print("2. Версия миграции Alembic:")
        try:
            cur.execute("SELECT version_num FROM core.alembic_version")
            version = cur.fetchone()
            if version:
                print(f"   ✓ Текущая версия: {version['version_num']}")
            else:
                print("   ✗ Таблица версий пуста")
        except Exception as e:
            print(f"   ✗ Ошибка: {e}")
        print()
        
        # 3. Проверяем таблицы в каждой схеме
        print("3. Таблицы по схемам:")
        for schema_row in schemas:
            schema_name = schema_row['schema_name']
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s
                ORDER BY table_name
            """, (schema_name,))
            tables = cur.fetchall()
            
            if tables:
                print(f"   Схема '{schema_name}':")
                for table in tables:
                    table_name = table['table_name']
                    try:
                        cur.execute(f'SELECT COUNT(*) as cnt FROM "{schema_name}"."{table_name}"')
                        count = cur.fetchone()['cnt']
                        print(f"      ✓ {table_name} ({count} строк)")
                    except Exception as e:
                        print(f"      ✓ {table_name} (ошибка подсчета: {e})")
        
        print()
        
        # 4. Проверяем основные таблицы
        print("4. Проверка ключевых таблиц:")
        key_tables = [
            ('core', 'settings'),
            ('core', 'users'),
            ('core', 'audit_log'),
            ('core', 'alembic_version'),
            ('telegram', 'telegram_users'),
            ('telegram', 'telegram_chats'),
            ('employees', 'employees'),
            ('employees', 'departments'),
            ('employees', 'workstations'),
            ('monitoring', 'servers'),
            ('monitoring', 'server_groups'),
            ('otrs', 'otrs_users'),
            ('cluster', 'cluster_nodes'),
        ]
        
        for schema, table in key_tables:
            try:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = %s
                    ) as exists
                """, (schema, table))
                exists = cur.fetchone()['exists']
                if exists:
                    cur.execute(f'SELECT COUNT(*) as cnt FROM "{schema}"."{table}"')
                    count = cur.fetchone()['cnt']
                    print(f"   ✓ {schema}.{table} ({count} строк)")
                else:
                    print(f"   ✗ {schema}.{table} - не найдена")
            except Exception as e:
                print(f"   ✗ {schema}.{table} - ошибка: {e}")
        
        cur.close()
        conn.close()
        
        print()
        print("=" * 60)
        print("Проверка завершена успешно!")
        print("=" * 60)
        
    except psycopg2.OperationalError as e:
        print(f"ОШИБКА подключения к базе данных: {e}")
        print()
        print("Проверьте:")
        print("  1. PostgreSQL запущен")
        print("  2. Параметры подключения правильные")
        print("  3. Пароль сохранен в Windows Credential Manager (TBot/DB_PASSWORD)")
        sys.exit(1)
    except Exception as e:
        print(f"ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    check_database()

