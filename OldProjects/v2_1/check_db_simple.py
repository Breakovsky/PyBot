"""
Простой скрипт для проверки состояния базы данных после миграции.
Работает напрямую с psycopg2, который уже установлен для Alembic.
"""

import os
import sys
from pathlib import Path

# Устанавливаем UTF-8 для вывода
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Добавляем путь к проекту
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed, using environment variables")

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("ERROR: psycopg2 is not installed!")
    print("Install: pip install psycopg2-binary")
    sys.exit(1)


def get_db_password():
    """Получает пароль БД из keyring или переменных окружения."""
    if HAS_KEYRING:
        try:
            password = keyring.get_password("TBot", "DB_PASSWORD")
            if password:
                return password
        except Exception:
            pass
    
    return os.getenv("DB_PASSWORD", "")


def check_database():
    """Проверяет состояние базы данных."""
    # Получаем параметры подключения
    db_password = get_db_password()
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "tbot")
    db_user = os.getenv("DB_USER", "tbot")
    
    print("=" * 60)
    print("Database Status Check")
    print("=" * 60)
    print(f"Connecting to: {db_host}:{db_port}/{db_name} as {db_user}")
    print()
    
    if not db_password:
        print("WARNING: Password not found!")
        print("Save password to Windows Credential Manager:")
        print('  python -c "import keyring; keyring.set_password(\'TBot\', \'DB_PASSWORD\', \'your_password\')"')
        print("Or set environment variable DB_PASSWORD")
        print()
        response = input("Continue without password? (y/n): ")
        if response.lower() != 'y':
            return
    
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
        
        # 1. Check schemas
        print("1. Database schemas:")
        cur.execute("""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name
        """)
        schemas = cur.fetchall()
        for row in schemas:
            print(f"   [+] {row['schema_name']}")
        print()
        
        # 2. Check migration version
        print("2. Alembic migration version:")
        try:
            cur.execute("SELECT version_num FROM core.alembic_version")
            version = cur.fetchone()
            if version:
                print(f"   [+] Current version: {version['version_num']}")
            else:
                print("   [-] Version table is empty")
        except Exception as e:
            print(f"   [-] Error: {e}")
        print()
        
        # 3. Check tables in each schema
        print("3. Tables by schema:")
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
                print(f"   Schema '{schema_name}':")
                for table in tables:
                    table_name = table['table_name']
                    try:
                        cur.execute(f'SELECT COUNT(*) as cnt FROM "{schema_name}"."{table_name}"')
                        count = cur.fetchone()['cnt']
                        print(f"      [+] {table_name} ({count} rows)")
                    except Exception as e:
                        print(f"      [+] {table_name} (count error: {str(e)[:50]})")
        
        print()
        
        # 4. Check key tables
        print("4. Key tables check:")
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
                    print(f"   [+] {schema}.{table} ({count} rows)")
                else:
                    print(f"   [-] {schema}.{table} - not found")
            except Exception as e:
                print(f"   [-] {schema}.{table} - error: {str(e)[:50]}")
        
        cur.close()
        conn.close()
        
        print()
        print("=" * 60)
        print("Check completed successfully!")
        print("=" * 60)
        
    except psycopg2.OperationalError as e:
        print(f"Database connection error: {e}")
        print()
        print("Check:")
        print("  1. PostgreSQL is running")
        print("  2. Connection parameters are correct")
        print("  3. Password is saved in Windows Credential Manager (TBot/DB_PASSWORD)")
        print("     or DB_PASSWORD environment variable is set")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    check_database()

