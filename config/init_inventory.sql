-- Inventory Schema for NetAdmin v3.0
-- Migrated from v2_0 Excel structure

-- Employees/Assets Inventory
CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    last_name VARCHAR(100),
    first_name VARCHAR(100),
    middle_name VARCHAR(100),
    full_name VARCHAR(255) GENERATED ALWAYS AS (
        TRIM(
            COALESCE(last_name || ' ', '') ||
            COALESCE(first_name || ' ', '') ||
            COALESCE(middle_name, '')
        )
    ) STORED,  -- Computed column for backward compatibility (can be empty if all parts are NULL)
    department VARCHAR(255),
    phone VARCHAR(50),
    workstation VARCHAR(100),  -- WS number
    ad_login VARCHAR(100),     -- Active Directory login
    email VARCHAR(255),
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    -- Note: No name constraint - allow empty records to maintain exact count (621 records)
);

-- Index for fast search
CREATE INDEX IF NOT EXISTS idx_employees_last_name ON employees(last_name);
CREATE INDEX IF NOT EXISTS idx_employees_first_name ON employees(first_name);
CREATE INDEX IF NOT EXISTS idx_employees_middle_name ON employees(middle_name);
CREATE INDEX IF NOT EXISTS idx_employees_full_name ON employees(full_name);
CREATE INDEX IF NOT EXISTS idx_employees_phone ON employees(phone);
CREATE INDEX IF NOT EXISTS idx_employees_workstation ON employees(workstation);
CREATE INDEX IF NOT EXISTS idx_employees_ad_login ON employees(ad_login);
CREATE INDEX IF NOT EXISTS idx_employees_email ON employees(email);

-- Monitored Targets (already exists from admin-panel, ensuring compatibility)
CREATE TABLE IF NOT EXISTS monitored_targets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    hostname VARCHAR(255) NOT NULL,
    interval_seconds INT DEFAULT 60,
    is_active BOOLEAN DEFAULT TRUE,
    last_status VARCHAR(50),
    last_check TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- AD Users (for MDaemon/LDAP sync)
CREATE TABLE IF NOT EXISTS ad_users (
    email VARCHAR(255) PRIMARY KEY,
    full_name VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Audit Log for changes
CREATE TABLE IF NOT EXISTS inventory_audit (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(50) NOT NULL,
    record_id INT NOT NULL,
    action VARCHAR(20) NOT NULL, -- INSERT, UPDATE, DELETE, DISABLE
    changed_by_telegram_id BIGINT,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    old_data JSONB,
    new_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_table_record ON inventory_audit(table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON inventory_audit(changed_at DESC);

