import os
import io
import msoffcrypto
import openpyxl
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# --- Config ---
EXCEL_PATH = "/app/OldProjects/v2_0/main/server/all_pc.xlsx"
EXCEL_PASSWORD = os.getenv("EXCEL_PASS", "2583109")

POSTGRES_USER = os.getenv("POSTGRES_USER", "netadmin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "netadmin_secret")
POSTGRES_DB = os.getenv("POSTGRES_DB", "netadmin_db")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "db")

DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DB}"

# --- Helpers ---

def parse_bool(val):
    if not val:
        return False
    s = str(val).strip().lower()
    return s in ('да', 'yes', 'true', 'y', '+')

def parse_fio(full_name):
    if not full_name:
        return None, None, None
    parts = full_name.strip().split()
    if len(parts) == 0:
        return None, None, None
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], parts[1], None
    return parts[0], parts[1], " ".join(parts[2:])

def run_migration():
    print("🚀 Starting migration from v2.0 Excel to v3.0 Database...")
    
    # 1. Connect to DB
    try:
        engine = create_engine(DATABASE_URL)
        Session = sessionmaker(bind=engine)
        session = Session()
        print("✅ Connected to Database.")
    except Exception as e:
        print(f"❌ DB Connection failed: {e}")
        return

    # 2. Open Excel
    try:
        decrypted = io.BytesIO()
        with open(EXCEL_PATH, "rb") as f:
            office_file = msoffcrypto.OfficeFile(f)
            office_file.load_key(password=EXCEL_PASSWORD)
            office_file.decrypt(decrypted)
        
        decrypted.seek(0)
        # data_only=True to get formula results
        wb = openpyxl.load_workbook(decrypted, data_only=True, read_only=True)
        ws = wb.active
        print(f"✅ Excel loaded. Sheet: {ws.title}")
    except Exception as e:
        print(f"❌ Excel load failed: {e}")
        return

    # 3. Clear existing data
    print("🧹 Clearing existing employees table...")
    try:
        session.execute(text("TRUNCATE TABLE employees RESTART IDENTITY"))
        session.commit()
    except Exception as e:
        print(f"⚠️ Truncate failed (maybe table doesn't exist?): {e}")
        session.rollback()

    # 4. Iterate and Insert
    count = 0
    # Columns indices (0-based) based on previous inspection of Row 2
    # A: Company (0)
    # B: Full Name (1)
    # C: Dept/Loc (2)
    # D: Email (3)
    # F: TA/SIP (5)
    # G: Internal Phone (6)
    # H: WS (7)
    # I: Device Type (8)
    # J: CPU (9)
    # K: RAM (10)
    # L: GPU (11)
    # M: Monitor (12)
    # N: UPS (13)
    # O: AD (14)
    # P: Dr.Web (15)
    # Q: Zabbix (16)
    # R: Notes (17)
    
    # Skip first 2 rows (1 super-header, 1 header)
    rows_iter = ws.iter_rows(min_row=3, values_only=True)
    
    for row in rows_iter:
        if not row[1]: # Skip empty names
            continue
            
        full_name = str(row[1]).strip()
        last_name, first_name, middle_name = parse_fio(full_name)
        
        company = row[0]
        department = row[2] # Mixed location/dept, put in department for now
        email = row[3]
        # Clean email if it's a formula error or N/A
        if email and (str(email).startswith('=') or str(email) == 'N' or str(email) == '#VALUE!'):
            email = None
        
        phone_type = row[5]
        internal_phone = str(row[6]) if row[6] else None
        workstation = str(row[7]) if row[7] else None
        device_type = row[8]
        
        specs_cpu = str(row[9]) if row[9] else None
        specs_ram = str(row[10]) if row[10] else None
        specs_gpu = str(row[11]) if row[11] else None
        monitor = str(row[12]) if row[12] else None
        ups = str(row[13]) if row[13] else None
        
        has_ad = parse_bool(row[14])
        has_drweb = parse_bool(row[15])
        has_zabbix = parse_bool(row[16])
        notes = str(row[17]) if row[17] else None

        sql = text("""
            INSERT INTO employees (
                last_name, first_name, middle_name,
                company, department, email,
                phone_type, internal_phone,
                workstation, device_type,
                specs_cpu, specs_ram, specs_gpu, monitor, ups,
                has_ad, has_drweb, has_zabbix,
                notes, is_active
            ) VALUES (
                :last_name, :first_name, :middle_name,
                :company, :department, :email,
                :phone_type, :internal_phone,
                :workstation, :device_type,
                :specs_cpu, :specs_ram, :specs_gpu, :monitor, :ups,
                :has_ad, :has_drweb, :has_zabbix,
                :notes, :is_active
            )
        """)
        
        try:
            session.execute(sql, {
                "last_name": last_name,
                "first_name": first_name,
                "middle_name": middle_name,
                "company": company,
                "department": department,
                "email": email,
                "phone_type": phone_type,
                "internal_phone": internal_phone,
                "workstation": workstation,
                "device_type": device_type,
                "specs_cpu": specs_cpu,
                "specs_ram": specs_ram,
                "specs_gpu": specs_gpu,
                "monitor": monitor,
                "ups": ups,
                "has_ad": has_ad,
                "has_drweb": has_drweb,
                "has_zabbix": has_zabbix,
                "notes": notes,
                "is_active": True
            })
            count += 1
            if count % 50 == 0:
                print(f"Processed {count} records...")
        except Exception as e:
            print(f"❌ Error inserting {full_name}: {e}")
            session.rollback()

    session.commit()
    print(f"✅ Migration complete! Imported {count} employees.")
    session.close()

if __name__ == "__main__":
    run_migration()

