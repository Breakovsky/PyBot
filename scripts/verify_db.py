#!/usr/bin/env python3
"""
Database Verification Script
Prints top rows from telegram_users and employees tables.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_connection():
    """Create PostgreSQL connection."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        database=os.getenv("POSTGRES_DB", "netadmin_db"),
        user=os.getenv("POSTGRES_USER", "netadmin"),
        password=os.getenv("POSTGRES_PASSWORD", "netadmin_secret")
    )


def print_table(conn, table_name: str, limit: int = 5):
    """Print top N rows from a table."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute(f"SELECT * FROM {table_name} ORDER BY id LIMIT %s", (limit,))
        rows = cursor.fetchall()
        
        print(f"\n{'='*60}")
        print(f"📊 Table: {table_name} (showing top {len(rows)} rows)")
        print(f"{'='*60}")
        
        if not rows:
            print("  (empty)")
            return
        
        # Print headers
        headers = list(rows[0].keys())
        print("  | ".join(f"{h:15}" for h in headers))
        print("-" * 60)
        
        # Print rows
        for row in rows:
            values = []
            for h in headers:
                val = row[h]
                if val is None:
                    val = "NULL"
                elif isinstance(val, str) and len(val) > 20:
                    val = val[:17] + "..."
                else:
                    val = str(val)
                values.append(f"{val:15}")
            print("  | ".join(values))
        
        # Get total count
        cursor.execute(f"SELECT COUNT(*) as total FROM {table_name}")
        total = cursor.fetchone()['total']
        print(f"\n  Total rows: {total}")
        
    except Exception as e:
        print(f"  ❌ Error reading {table_name}: {e}")
    finally:
        cursor.close()


def main():
    """Main function."""
    print("🔍 NetAdmin Database Verification")
    print("=" * 60)
    
    try:
        conn = get_db_connection()
        print("✅ Connected to PostgreSQL")
        
        # Print telegram_users
        print_table(conn, "telegram_users", limit=10)
        
        # Print employees
        print_table(conn, "employees", limit=10)
        
        # Print telegram_topics
        print_table(conn, "telegram_topics", limit=10)
        
        # Print monitored_targets
        print_table(conn, "monitored_targets", limit=10)
        
        conn.close()
        print(f"\n{'='*60}")
        print("✅ Verification complete")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

