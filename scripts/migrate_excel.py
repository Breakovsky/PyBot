#!/usr/bin/env python3
"""
Excel to PostgreSQL Migration Script
Migrates employee/asset data from legacy Excel file to NetAdmin v3.0 DB

Usage:
    python scripts/migrate_excel.py --file path/to/all_pc.xlsx [--password <password>]
    
    If --password not provided, reads from EXCEL_PASS environment variable.
    
Environment Variables:
    POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST
    EXCEL_PASS - Excel file password (optional if --password provided)
"""

import argparse
import logging
import os
import sys
from pathlib import Path
import io
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logger = logging.getLogger(__name__)
    logger.info(f"Loaded environment from: {env_path}")

import openpyxl
import msoffcrypto
import psycopg2
from psycopg2.extras import execute_batch
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_protected_excel(file_path: str, password: str):
    """Load password-protected Excel file."""
    try:
        decrypted = io.BytesIO()
        with open(file_path, "rb") as f:
            office_file = msoffcrypto.OfficeFile(f)
            office_file.load_key(password=password)
            office_file.decrypt(decrypted)
        decrypted.seek(0)
        return openpyxl.load_workbook(decrypted, read_only=True)
    except Exception as e:
        logger.error(f"Failed to load Excel file: {e}")
        return None


def get_db_connection():
    """Create PostgreSQL connection."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        database=os.getenv("POSTGRES_DB", "netadmin_db"),
        user=os.getenv("POSTGRES_USER", "netadmin"),
        password=os.getenv("POSTGRES_PASSWORD", "netadmin_secret")
    )


def parse_excel_data(wb):
    """
    Parse Excel workbook.
    
    Expected columns (based on v2_0 excel_handler.py):
    - B (1): ФИО (Full Name)
    - C (2): Подразделение (Department)
    - G (6): Телефон (Phone)
    - H (7): WorkStation (WS number)
    - O (14): AD логин (AD Login)
    - T (19): Примечание (Notes)
    """
    sheet = wb.active
    employees = []
    
    logger.info("Parsing Excel data...")
    
    for idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        try:
            # Extract data with safe indexing
            full_name = str(row[1]).strip() if len(row) > 1 and row[1] else None
            department = str(row[2]).strip() if len(row) > 2 and row[2] else None
            phone = str(row[6]).strip() if len(row) > 6 and row[6] else None
            workstation = str(row[7]).strip() if len(row) > 7 and row[7] else None
            ad_login = str(row[14]).strip() if len(row) > 14 and row[14] else None
            notes = str(row[19]).strip() if len(row) > 19 and row[19] else None
            
            # Skip empty rows
            if not full_name or full_name == "None":
                continue
            
            # Clean phone: remove non-digits except + at start
            if phone and phone != "None":
                phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            else:
                phone = None
            
            # Extract email from AD login if present (format: login or login@domain)
            email = None
            if ad_login and ad_login != "None" and "@" in ad_login:
                email = ad_login
            
            employees.append({
                "full_name": full_name,
                "department": department,
                "phone": phone,
                "workstation": workstation,
                "ad_login": ad_login,
                "email": email,
                "notes": notes
            })
            
        except Exception as e:
            logger.warning(f"Failed to parse row {idx}: {e}")
            continue
    
    logger.info(f"Parsed {len(employees)} employees from Excel")
    return employees


def migrate_to_db(employees, conn, mode="insert"):
    """
    Migrate employees to database.
    
    Args:
        employees: List of employee dictionaries
        conn: psycopg2 connection
        mode: "insert" (skip duplicates) or "upsert" (update existing)
    """
    cursor = conn.cursor()
    
    # Ensure inventory schema exists
    logger.info("Checking database schema...")
    sql_path = Path(__file__).parent.parent / "config" / "init_inventory.sql"
    if sql_path.exists():
        with open(sql_path, "r") as f:
            cursor.execute(f.read())
        conn.commit()
        logger.info("✅ Database schema verified")
    else:
        logger.warning(f"⚠️ Schema file not found: {sql_path}, assuming tables exist")
    
    inserted = 0
    updated = 0
    skipped = 0
    
    if mode == "upsert":
        # UPSERT: Check if exists by phone or workstation, then UPDATE or INSERT
        for emp in employees:
            try:
                # Check if employee exists (by phone or workstation)
                check_query = """
                    SELECT id FROM employees 
                    WHERE (phone = %(phone)s AND %(phone)s IS NOT NULL AND %(phone)s != '')
                       OR (workstation = %(workstation)s AND %(workstation)s IS NOT NULL AND %(workstation)s != '')
                    LIMIT 1
                """
                cursor.execute(check_query, emp)
                existing = cursor.fetchone()
                
                if existing:
                    # UPDATE existing
                    update_query = """
                        UPDATE employees 
                        SET full_name = %(full_name)s,
                            department = %(department)s,
                            phone = %(phone)s,
                            workstation = %(workstation)s,
                            ad_login = %(ad_login)s,
                            email = %(email)s,
                            notes = %(notes)s,
                            updated_at = NOW()
                        WHERE id = %(id)s
                    """
                    emp['id'] = existing[0]
                    cursor.execute(update_query, emp)
                    updated += 1
                else:
                    # INSERT new
                    insert_query = """
                        INSERT INTO employees (full_name, department, phone, workstation, ad_login, email, notes, updated_at)
                        VALUES (%(full_name)s, %(department)s, %(phone)s, %(workstation)s, %(ad_login)s, %(email)s, %(notes)s, NOW())
                    """
                    cursor.execute(insert_query, emp)
                    inserted += 1
                
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to upsert employee {emp.get('full_name', 'Unknown')}: {e}")
                skipped += 1
                conn.rollback()
                continue
    
    else:  # insert mode
        # Simple INSERT, skip duplicates
        query = """
            INSERT INTO employees (full_name, department, phone, workstation, ad_login, email, notes)
            VALUES (%(full_name)s, %(department)s, %(phone)s, %(workstation)s, %(ad_login)s, %(email)s, %(notes)s)
            ON CONFLICT DO NOTHING
        """
        
        for emp in employees:
            try:
                cursor.execute(query, emp)
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"Failed to insert employee {emp['full_name']}: {e}")
                skipped += 1
                conn.rollback()
                continue
        
        conn.commit()
    
    cursor.close()
    
    logger.info(f"Migration complete: inserted={inserted}, updated={updated}, skipped={skipped}")
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description="Migrate Excel data to PostgreSQL")
    parser.add_argument("--file", required=True, help="Path to Excel file")
    parser.add_argument("--password", help="Excel file password (or use EXCEL_PASS env var)")
    parser.add_argument("--mode", choices=["insert", "upsert"], default="upsert",
                       help="Migration mode: insert (skip duplicates) or upsert (update existing)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't write to DB")
    
    args = parser.parse_args()
    
    # Get password from args or env
    password = args.password or os.getenv("EXCEL_PASS")
    if not password:
        logger.error("❌ Excel password required! Provide --password or set EXCEL_PASS in .env")
        sys.exit(1)
    
    # Load Excel
    logger.info(f"Loading Excel file: {args.file}")
    wb = load_protected_excel(args.file, password)
    if not wb:
        logger.error("Failed to load Excel file")
        sys.exit(1)
    
    # Parse data
    employees = parse_excel_data(wb)
    wb.close()
    
    if not employees:
        logger.error("No employees parsed from Excel")
        sys.exit(1)
    
    # Display sample
    logger.info(f"Sample employee: {employees[0]}")
    
    if args.dry_run:
        logger.info("Dry run mode - skipping database write")
        logger.info(f"Total employees to migrate: {len(employees)}")
        return
    
    # Connect to DB
    logger.info("Connecting to PostgreSQL...")
    conn = get_db_connection()
    
    try:
        # Migrate
        result = migrate_to_db(employees, conn, mode=args.mode)
        logger.info(f"✅ Migration successful: {result}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

