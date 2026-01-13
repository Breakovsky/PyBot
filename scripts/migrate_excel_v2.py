#!/usr/bin/env python3
"""
Excel to PostgreSQL Migration Script V2.0 (Phase 8)
Complete migration with all business requirements:
- Smart parsing (phone types, RAM, booleans, company domains)
- Skip empty rows (if both Full Name AND WS are empty)
- Map all Excel columns to new schema
- Generate sequential IDs (not Excel row numbers)

Usage:
    python scripts/migrate_excel_v2.py --file path/to/all_pc.xlsx [--password <password>]
    
    If --password not provided, reads from EXCEL_PASS environment variable.
    
Environment Variables:
    POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST
    EXCEL_PASS - Excel file password (optional if --password provided)
"""

import argparse
import logging
import os
import sys
import re
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
        # data_only=True reads the cached values instead of formulas
        return openpyxl.load_workbook(decrypted, read_only=True, data_only=True)
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


def parse_fio(full_name: str):
    """
    Parse Russian FIO format: "Фамилия Имя Отчество"
    Returns tuple: (last_name, first_name, middle_name)
    """
    if not full_name or full_name == "None" or str(full_name).strip() == "":
        return (None, None, None)
    
    parts = str(full_name).strip().split()
    
    if len(parts) == 0:
        return (None, None, None)
    elif len(parts) == 1:
        return (parts[0], None, None)
    elif len(parts) == 2:
        return (parts[0], parts[1], None)
    else:
        # 3 or more parts: last_name, first_name, middle_name (rest)
        return (parts[0], parts[1], " ".join(parts[2:]))


def parse_phone_type(phone_data: str, notes: str = None):
    """
    Detect phone type based on keywords.
    Returns: 'TA', 'MicroSIP', or 'NONE'
    """
    if not phone_data or phone_data == "None" or str(phone_data).strip() == "":
        return 'NONE'
    
    phone_str = str(phone_data).lower()
    notes_str = str(notes).lower() if notes else ""
    combined = f"{phone_str} {notes_str}"
    
    if 'microsip' in combined or 'softphone' in combined or 'soft' in combined:
        return 'MicroSIP'
    elif 'ta' in combined or 'hardware' in combined or 'аппаратный' in combined:
        return 'TA'
    else:
        # Default to TA if phone number exists
        return 'TA'


def parse_boolean(value: str):
    """
    Convert various boolean representations to True/False.
    Accepts: 'Yes', 'No', '+', '-', '1', '0', 'True', 'False', 'Y', 'N'
    """
    if not value or value == "None":
        return False
    
    value_str = str(value).strip().upper()
    
    if value_str in ['YES', 'Y', '+', '1', 'TRUE', 'ДА', 'ЕСТЬ']:
        return True
    elif value_str in ['NO', 'N', '-', '0', 'FALSE', 'НЕТ', 'НЕТУ']:
        return False
    else:
        return False


def parse_ram(ram_str: str):
    """
    Parse RAM specification, remove 'GB' and normalize.
    Returns: Cleaned string (e.g., '16GB' -> '16GB', '32' -> '32GB')
    """
    if not ram_str or ram_str == "None":
        return None
    
    ram_clean = str(ram_str).strip().upper()
    
    # Remove common prefixes/suffixes
    ram_clean = re.sub(r'[^\dGB]', '', ram_clean)
    
    # If it's just a number, assume GB
    if ram_clean.isdigit():
        return f"{ram_clean}GB"
    
    # If it already has GB, return as is
    if 'GB' in ram_clean:
        return ram_clean
    
    return ram_clean if ram_clean else None


def parse_company_domain(company: str):
    """
    Map company name to email domain.
    Examples:
    - 'Company A' -> '@a.com'
    - 'Company B' -> '@b.com'
    - 'Corp' -> '@corp.com'
    """
    if not company or company == "None":
        return None
    
    company_clean = str(company).strip()
    
    # Simple mapping logic (can be extended)
    if 'a' in company_clean.lower() or 'первая' in company_clean.lower():
        return '@a.com'
    elif 'b' in company_clean.lower() or 'вторая' in company_clean.lower():
        return '@b.com'
    elif 'corp' in company_clean.lower() or 'корп' in company_clean.lower():
        return '@corp.com'
    else:
        # Default: extract first word and create domain
        first_word = company_clean.split()[0] if company_clean.split() else 'corp'
        return f"@{first_word.lower()}.com"


def clean_string(value):
    """Clean string value, return None if empty."""
    if not value or value == "None":
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def parse_excel_data_v2(wb):
    """
    Parse Excel workbook with complete column mapping.
    
    Expected Excel columns (0-indexed):
    - A (0): Row number / ID (ignore, we use SERIAL)
    - B (1): ФИО (Full Name) -> last_name, first_name, middle_name
    - C (2): Подразделение (Department) -> department
    - D (3): Компания (Company) -> company
    - E (4): Локация (Location) -> location
    - F (5): Email -> email
    - G (6): Телефон (Phone) -> internal_phone, phone_type
    - H (7): WorkStation -> workstation
    - I (8): Тип устройства (Device Type) -> device_type
    - J (9): CPU -> specs_cpu
    - K (10): GPU -> specs_gpu
    - L (11): RAM -> specs_ram
    - M (12): Монитор (Monitor) -> monitor
    - N (13): UPS -> ups
    - O (14): AD Login -> ad_login, has_ad
    - P (15): Dr.Web -> has_drweb
    - Q (16): Zabbix -> has_zabbix
    - R (17): Примечание (Notes) -> notes
    
    IMPORTANT: Skip rows where BOTH full_name AND workstation are empty.
    """
    sheet = wb.active
    employees = []
    
    logger.info("Parsing Excel data (V2.0)...")
    
    # Start from row 2 (skip header row 1)
    # Parse exactly 621 rows (rows 2-622 inclusive)
    max_rows = 621
    skipped_empty = 0
    
    for idx, row in enumerate(sheet.iter_rows(min_row=2, max_row=622, values_only=True), start=2):
        try:
            # Extract all columns with safe indexing based on debug analysis
            # Col 0 (A): Company
            # Col 1 (B): Full Name
            # Col 2 (C): Location / Department
            # Col 3 (D): Email
            # Col 5 (F): Phone Type
            # Col 6 (G): Internal Phone
            # Col 7 (H): WS
            # Col 8 (I): Device Type
            # ...
            
            company = clean_string(row[0]) if len(row) > 0 and row[0] else None
            full_name_raw = clean_string(row[1]) if len(row) > 1 and row[1] else None
            # Use Col 2 for both Department and Location as they are mixed
            location_raw = clean_string(row[2]) if len(row) > 2 and row[2] else None
            department = location_raw # Assumed same for now
            location = location_raw
            
            email = clean_string(row[3]) if len(row) > 3 and row[3] else None
            # Skip Col 4 (E) - Alternative Email/Formula
            
            phone_type_raw = clean_string(row[5]) if len(row) > 5 and row[5] else None
            phone_raw = clean_string(row[6]) if len(row) > 6 and row[6] else None
            workstation = clean_string(row[7]) if len(row) > 7 and row[7] else None
            device_type_raw = clean_string(row[8]) if len(row) > 8 and row[8] else None
            cpu = clean_string(row[9]) if len(row) > 9 and row[9] else None
            gpu = clean_string(row[11]) if len(row) > 11 and row[11] else None # GPU is L (11)
            ram_raw = clean_string(row[10]) if len(row) > 10 and row[10] else None # RAM is K (10)
            monitor = clean_string(row[12]) if len(row) > 12 and row[12] else None
            ups = clean_string(row[13]) if len(row) > 13 and row[13] else None
            ad_login = clean_string(row[14]) if len(row) > 14 and row[14] else None
            drweb_raw = clean_string(row[15]) if len(row) > 15 and row[15] else None
            zabbix_raw = clean_string(row[16]) if len(row) > 16 and row[16] else None
            notes = clean_string(row[17]) if len(row) > 17 and row[17] else None
            
            # CRITICAL: Skip if BOTH full_name AND workstation are empty
            if not full_name_raw and not workstation:
                skipped_empty += 1
                logger.debug(f"Row {idx}: Skipped (both name and WS empty)")
                continue
            
            # Parse FIO
            last_name, first_name, middle_name = parse_fio(full_name_raw)
            
            # Parse phone type and clean phone number
            # Pass phone_type_raw (Col F) to helper if needed, or use logic
            phone_type = parse_phone_type(phone_type_raw, notes) # Prefer explicit column
            if phone_type == 'NONE' and phone_raw:
                 # Fallback to detection if Col F is empty but phone exists
                 phone_type = parse_phone_type(phone_raw, notes)

            internal_phone = None
            if phone_raw:
                # Clean phone: remove non-digits except + at start
                phone_clean = phone_raw.replace(" ", "").replace("-", "").replace("(", "").replace(")")
                internal_phone = phone_clean if phone_clean else None
            
            # Parse device type
            device_type = None
            if device_type_raw:
                device_lower = device_type_raw.lower()
                if 'laptop' in device_lower or 'ноутбук' in device_lower:
                    device_type = 'Laptop'
                elif 'monoblock' in device_lower or 'моноблок' in device_lower:
                    device_type = 'Monoblock'
                elif 'server' in device_lower or 'сервер' in device_lower:
                    device_type = 'Server'
                elif 'pc' in device_lower or 'пк' in device_lower or 'сб' in device_lower:
                    device_type = 'PC'
                else:
                    device_type = 'Other'
            
            # Parse RAM
            specs_ram = parse_ram(ram_raw)
            
            # Parse booleans
            has_ad = bool(ad_login) or parse_boolean(ad_login)  # Has AD if login exists
            has_drweb = parse_boolean(drweb_raw)
            has_zabbix = parse_boolean(zabbix_raw)
            
            # Generate email if not provided but company exists
            if not email and company:
                domain = parse_company_domain(company)
                if ad_login and domain:
                    # Extract username from AD login
                    username = ad_login.split('@')[0] if '@' in ad_login else ad_login
                    email = f"{username}{domain}"
            
            employees.append({
                "company": company,
                "last_name": last_name,
                "first_name": first_name,
                "middle_name": middle_name,
                "department": department,
                "location": location,
                "email": email,
                "phone_type": phone_type,
                "internal_phone": internal_phone,
                "workstation": workstation,
                "device_type": device_type,
                "specs_cpu": cpu,
                "specs_gpu": gpu,
                "specs_ram": specs_ram,
                "monitor": monitor,
                "ups": ups,
                "has_ad": has_ad,
                "has_drweb": has_drweb,
                "has_zabbix": has_zabbix,
                "ad_login": ad_login,
                "notes": notes
            })
            
        except Exception as e:
            logger.warning(f"Failed to parse row {idx}: {e}")
            skipped_empty += 1
            continue
    
    logger.info(f"Parsed {len(employees)} employees from Excel (skipped {skipped_empty} empty rows)")
    return employees


def migrate_to_db_v2(employees, conn, mode="insert"):
    """
    Migrate employees to database using V2 schema.
    
    Args:
        employees: List of employee dictionaries
        conn: psycopg2 connection
        mode: "insert" (skip duplicates) or "upsert" (update existing)
    """
    cursor = conn.cursor()
    
    # Ensure V2 schema exists
    logger.info("Checking database schema (V2.0)...")
    sql_path = Path(__file__).parent.parent / "config" / "schema_v2.sql"
    if sql_path.exists():
        with open(sql_path, "r", encoding='utf-8') as f:
            # Execute schema creation
            cursor.execute(f.read())
        conn.commit()
        logger.info("✅ Database schema V2.0 verified")
    else:
        logger.warning(f"⚠️ Schema file not found: {sql_path}, assuming tables exist")
    
    inserted = 0
    updated = 0
    skipped = 0
    
    if mode == "upsert":
        # UPSERT: Check if exists by workstation or internal_phone, then UPDATE or INSERT
        for emp in employees:
            try:
                # Check if employee exists (by workstation or phone)
                check_query = """
                    SELECT id FROM employees 
                    WHERE (workstation = %(workstation)s AND %(workstation)s IS NOT NULL AND %(workstation)s != '')
                       OR (internal_phone = %(internal_phone)s AND %(internal_phone)s IS NOT NULL AND %(internal_phone)s != '')
                    LIMIT 1
                """
                cursor.execute(check_query, emp)
                existing = cursor.fetchone()
                
                if existing:
                    # UPDATE existing
                    update_query = """
                        UPDATE employees 
                        SET company = %(company)s,
                            last_name = %(last_name)s,
                            first_name = %(first_name)s,
                            middle_name = %(middle_name)s,
                            department = %(department)s,
                            location = %(location)s,
                            email = %(email)s,
                            phone_type = %(phone_type)s,
                            internal_phone = %(internal_phone)s,
                            workstation = %(workstation)s,
                            device_type = %(device_type)s,
                            specs_cpu = %(specs_cpu)s,
                            specs_gpu = %(specs_gpu)s,
                            specs_ram = %(specs_ram)s,
                            monitor = %(monitor)s,
                            ups = %(ups)s,
                            has_ad = %(has_ad)s,
                            has_drweb = %(has_drweb)s,
                            has_zabbix = %(has_zabbix)s,
                            ad_login = %(ad_login)s,
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
                        INSERT INTO employees (
                            company, last_name, first_name, middle_name,
                            department, location, email, phone_type, internal_phone,
                            workstation, device_type, specs_cpu, specs_gpu, specs_ram,
                            monitor, ups, has_ad, has_drweb, has_zabbix,
                            ad_login, notes, updated_at
                        )
                        VALUES (
                            %(company)s, %(last_name)s, %(first_name)s, %(middle_name)s,
                            %(department)s, %(location)s, %(email)s, %(phone_type)s, %(internal_phone)s,
                            %(workstation)s, %(device_type)s, %(specs_cpu)s, %(specs_gpu)s, %(specs_ram)s,
                            %(monitor)s, %(ups)s, %(has_ad)s, %(has_drweb)s, %(has_zabbix)s,
                            %(ad_login)s, %(notes)s, NOW()
                        )
                    """
                    cursor.execute(insert_query, emp)
                    inserted += 1
                
                conn.commit()
            except Exception as e:
                name_str = f"{emp.get('last_name', '')} {emp.get('first_name', '')} {emp.get('middle_name', '')}".strip() or "Unknown"
                logger.error(f"Failed to upsert employee {name_str}: {e}")
                skipped += 1
                conn.rollback()
                continue
    
    else:  # insert mode
        # Simple INSERT - import ALL valid records
        query = """
            INSERT INTO employees (
                company, last_name, first_name, middle_name,
                department, location, email, phone_type, internal_phone,
                workstation, device_type, specs_cpu, specs_gpu, specs_ram,
                monitor, ups, has_ad, has_drweb, has_zabbix,
                ad_login, notes
            )
            VALUES (
                %(company)s, %(last_name)s, %(first_name)s, %(middle_name)s,
                %(department)s, %(location)s, %(email)s, %(phone_type)s, %(internal_phone)s,
                %(workstation)s, %(device_type)s, %(specs_cpu)s, %(specs_gpu)s, %(specs_ram)s,
                %(monitor)s, %(ups)s, %(has_ad)s, %(has_drweb)s, %(has_zabbix)s,
                %(ad_login)s, %(notes)s
            )
        """
        
        for emp in employees:
            try:
                cursor.execute(query, emp)
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                name_str = f"{emp.get('last_name', '')} {emp.get('first_name', '')} {emp.get('middle_name', '')}".strip() or "Unknown"
                logger.error(f"Failed to insert employee {name_str}: {e}")
                skipped += 1
                conn.rollback()
                continue
        
        conn.commit()
    
    cursor.close()
    
    logger.info(f"Migration complete: inserted={inserted}, updated={updated}, skipped={skipped}")
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description="Migrate Excel data to PostgreSQL (V2.0)")
    parser.add_argument("--file", required=True, help="Path to Excel file")
    parser.add_argument("--password", help="Excel file password (or use EXCEL_PASS env var)")
    parser.add_argument("--mode", choices=["insert", "upsert"], default="insert",
                       help="Migration mode: insert (new records) or upsert (update existing)")
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
    employees = parse_excel_data_v2(wb)
    wb.close()
    
    if not employees:
        logger.error("No employees parsed from Excel")
        sys.exit(1)
    
    # Display sample
    if employees:
        sample = employees[0]
        logger.info(f"Sample employee: {sample.get('last_name')} {sample.get('first_name')}, WS={sample.get('workstation')}, Phone={sample.get('internal_phone')}, Type={sample.get('phone_type')}")
    
    if args.dry_run:
        logger.info("Dry run mode - skipping database write")
        logger.info(f"Total employees to migrate: {len(employees)}")
        return
    
    # Connect to DB
    logger.info("Connecting to PostgreSQL...")
    conn = get_db_connection()
    
    try:
        # Migrate
        result = migrate_to_db_v2(employees, conn, mode=args.mode)
        logger.info(f"✅ Migration successful: {result}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

