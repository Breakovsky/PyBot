-- Fix Employee IDs: Reindex to sequential numbers starting from 1
-- This script renumbers all employees to have sequential IDs
-- WARNING: This will break any foreign key references to employees.id
-- Use only if you understand the implications!

-- Step 1: Disable foreign key constraints temporarily
ALTER TABLE onboarding_secrets DROP CONSTRAINT IF EXISTS onboarding_secrets_employee_id_fkey;

-- Step 2: Create mapping table
CREATE TEMP TABLE id_mapping AS
SELECT 
    id as old_id,
    ROW_NUMBER() OVER (ORDER BY id) as new_id
FROM employees
ORDER BY id;

-- Step 3: Update onboarding_secrets with new IDs
UPDATE onboarding_secrets os
SET employee_id = im.new_id
FROM id_mapping im
WHERE os.employee_id = im.old_id;

-- Step 4: Update employees with new sequential IDs
-- We need to do this carefully to avoid conflicts
-- First, add a temporary column
ALTER TABLE employees ADD COLUMN IF NOT EXISTS new_id_temp INTEGER;

-- Map new IDs
UPDATE employees e
SET new_id_temp = im.new_id
FROM id_mapping im
WHERE e.id = im.old_id;

-- Clear old IDs (set to negative to avoid conflicts)
UPDATE employees SET id = -id WHERE new_id_temp IS NOT NULL;

-- Set new IDs
UPDATE employees SET id = new_id_temp WHERE new_id_temp IS NOT NULL;

-- Drop temp column
ALTER TABLE employees DROP COLUMN IF EXISTS new_id_temp;

-- Step 5: Reset sequence
SELECT setval('employees_id_seq', (SELECT COALESCE(MAX(id), 1) FROM employees), true);

-- Step 6: Re-enable foreign key constraints
ALTER TABLE onboarding_secrets 
ADD CONSTRAINT onboarding_secrets_employee_id_fkey 
FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE;

-- Verify
SELECT 
    MIN(id) as min_id,
    MAX(id) as max_id,
    COUNT(*) as total,
    MAX(id) - MIN(id) + 1 as expected_range,
    CASE 
        WHEN MAX(id) - MIN(id) + 1 = COUNT(*) THEN '✅ IDs are sequential'
        ELSE '⚠️ IDs have gaps'
    END as status
FROM employees;

