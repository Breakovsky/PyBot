-- NetAdmin v3.0 - Schema V2.0 (Phase 8)
-- Complete database schema with all business requirements
-- DROP and RECREATE tables for clean migration

-- ============================================
-- Table A: employees (The Source of Truth)
-- ============================================
DROP TABLE IF EXISTS onboarding_secrets CASCADE;
DROP TABLE IF EXISTS employees CASCADE;

-- Phone Type Enum
DO $$ BEGIN
    CREATE TYPE phone_type_enum AS ENUM ('TA', 'MicroSIP', 'NONE');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Device Type Enum
DO $$ BEGIN
    CREATE TYPE device_type_enum AS ENUM ('PC', 'Laptop', 'Monoblock', 'Server', 'Other');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    
    -- Identity & Organization
    company VARCHAR(100),                    -- Determines email domain (e.g., 'Company A' -> @a.com)
    last_name VARCHAR(100),
    first_name VARCHAR(100),
    middle_name VARCHAR(100),
    full_name VARCHAR(255) GENERATED ALWAYS AS (
        TRIM(
            COALESCE(last_name || ' ', '') ||
            COALESCE(first_name || ' ', '') ||
            COALESCE(middle_name, '')
        )
    ) STORED,
    department VARCHAR(255),                -- Functional Department
    location VARCHAR(255),                  -- Physical office/room
    
    -- Contact Information
    email VARCHAR(255),                     -- Parsed or Override
    phone_type phone_type_enum DEFAULT 'NONE', -- 'TA' (Hardware Phone) or 'MicroSIP' (Softphone)
    internal_phone VARCHAR(50),             -- Extension number
    
    -- Hardware Inventory
    workstation VARCHAR(100),              -- 'WS-101' (Inventory Tag)
    device_type device_type_enum,           -- PC / Laptop / Monoblock
    specs_cpu VARCHAR(255),                -- CPU specification
    specs_gpu VARCHAR(255),                 -- GPU specification
    specs_ram VARCHAR(50),                  -- RAM (e.g., '16GB', '32GB')
    monitor VARCHAR(255),                   -- Monitor model/specs
    ups VARCHAR(255),                       -- UPS model/power
    
    -- Software Status (Boolean flags)
    has_ad BOOLEAN DEFAULT FALSE,           -- Active Directory status
    has_drweb BOOLEAN DEFAULT FALSE,        -- Dr.Web Antivirus status
    has_zabbix BOOLEAN DEFAULT FALSE,       -- Zabbix Monitoring status
    
    -- Additional
    ad_login VARCHAR(100),                  -- AD username (for reference)
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast search
CREATE INDEX idx_employees_company ON employees(company);
CREATE INDEX idx_employees_last_name ON employees(last_name);
CREATE INDEX idx_employees_first_name ON employees(first_name);
CREATE INDEX idx_employees_full_name ON employees(full_name);
CREATE INDEX idx_employees_department ON employees(department);
CREATE INDEX idx_employees_location ON employees(location);
CREATE INDEX idx_employees_workstation ON employees(workstation);
CREATE INDEX idx_employees_internal_phone ON employees(internal_phone);
CREATE INDEX idx_employees_email ON employees(email);
CREATE INDEX idx_employees_ad_login ON employees(ad_login);
CREATE INDEX idx_employees_is_active ON employees(is_active);

-- Composite indexes for common queries
CREATE INDEX idx_employees_dept_location ON employees(department, location);
CREATE INDEX idx_employees_company_dept ON employees(company, department);

-- ============================================
-- Table B: onboarding_secrets (New!)
-- Stores initial credentials for new hires
-- ============================================
CREATE TABLE onboarding_secrets (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    service_type VARCHAR(50) NOT NULL,        -- 'AD', 'EMAIL', 'REDMINE', 'VPN', etc.
    login VARCHAR(255) NOT NULL,            -- e.g., 'DOMAIN\ivanov' or 'ivanov@corp.com'
    initial_password VARCHAR(255),        -- Encrypted or stored for initial printout
    is_issued BOOLEAN DEFAULT FALSE,       -- False = ready to print, True = given to user
    issued_at TIMESTAMP WITH TIME ZONE,     -- When credentials were given to user
    issued_by_telegram_id BIGINT,           -- Who issued the credentials
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_employee_service UNIQUE (employee_id, service_type)
);

-- Indexes for onboarding_secrets
CREATE INDEX idx_onboarding_employee_id ON onboarding_secrets(employee_id);
CREATE INDEX idx_onboarding_service_type ON onboarding_secrets(service_type);
CREATE INDEX idx_onboarding_is_issued ON onboarding_secrets(is_issued);
CREATE INDEX idx_onboarding_created_at ON onboarding_secrets(created_at DESC);

-- ============================================
-- Audit Log (if not exists)
-- ============================================
CREATE TABLE IF NOT EXISTS inventory_audit (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(50) NOT NULL,
    record_id INT NOT NULL,
    action VARCHAR(20) NOT NULL,            -- INSERT, UPDATE, DELETE, DISABLE
    changed_by_telegram_id BIGINT,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    old_data JSONB,
    new_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_table_record ON inventory_audit(table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON inventory_audit(changed_at DESC);

-- ============================================
-- Helper Functions
-- ============================================

-- Function to get employee full details (for API)
CREATE OR REPLACE FUNCTION get_employee_details(emp_id INTEGER)
RETURNS TABLE (
    id INTEGER,
    company VARCHAR,
    full_name VARCHAR,
    department VARCHAR,
    location VARCHAR,
    email VARCHAR,
    phone_type phone_type_enum,
    internal_phone VARCHAR,
    workstation VARCHAR,
    device_type device_type_enum,
    specs_cpu VARCHAR,
    specs_gpu VARCHAR,
    specs_ram VARCHAR,
    monitor VARCHAR,
    ups VARCHAR,
    has_ad BOOLEAN,
    has_drweb BOOLEAN,
    has_zabbix BOOLEAN,
    notes TEXT,
    is_active BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        e.id, e.company, e.full_name, e.department, e.location,
        e.email, e.phone_type, e.internal_phone, e.workstation,
        e.device_type, e.specs_cpu, e.specs_gpu, e.specs_ram,
        e.monitor, e.ups, e.has_ad, e.has_drweb, e.has_zabbix,
        e.notes, e.is_active
    FROM employees e
    WHERE e.id = emp_id;
END;
$$ LANGUAGE plpgsql;

-- Function to count employees by status
CREATE OR REPLACE FUNCTION get_employee_stats()
RETURNS TABLE (
    total INTEGER,
    active INTEGER,
    with_ad INTEGER,
    with_drweb INTEGER,
    with_zabbix INTEGER,
    by_company JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*)::INTEGER as total,
        COUNT(*) FILTER (WHERE is_active = TRUE)::INTEGER as active,
        COUNT(*) FILTER (WHERE has_ad = TRUE)::INTEGER as with_ad,
        COUNT(*) FILTER (WHERE has_drweb = TRUE)::INTEGER as with_drweb,
        COUNT(*) FILTER (WHERE has_zabbix = TRUE)::INTEGER as with_zabbix,
        jsonb_object_agg(company, cnt) FILTER (WHERE company IS NOT NULL) as by_company
    FROM (
        SELECT company, COUNT(*) as cnt
        FROM employees
        GROUP BY company
    ) subq
    CROSS JOIN employees;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- Comments for Documentation
-- ============================================
COMMENT ON TABLE employees IS 'Main inventory table - source of truth for all employee assets';
COMMENT ON TABLE onboarding_secrets IS 'Stores initial credentials for new hires (AD, Email, Redmine, etc.)';
COMMENT ON COLUMN employees.phone_type IS 'TA = Hardware Phone, MicroSIP = Softphone, NONE = No phone';
COMMENT ON COLUMN employees.device_type IS 'PC, Laptop, Monoblock, Server, or Other';
COMMENT ON COLUMN employees.specs_ram IS 'RAM specification (e.g., "16GB", "32GB")';
COMMENT ON COLUMN onboarding_secrets.is_issued IS 'FALSE = ready to print credentials, TRUE = already given to user';

