-- Migration: Split full_name into last_name, first_name, middle_name
-- Run this after init_inventory.sql

-- Step 1: Add new columns
ALTER TABLE employees 
ADD COLUMN IF NOT EXISTS last_name VARCHAR(100),
ADD COLUMN IF NOT EXISTS first_name VARCHAR(100),
ADD COLUMN IF NOT EXISTS middle_name VARCHAR(100);

-- Step 2: Migrate existing data (parse full_name)
-- Russian FIO format: "Фамилия Имя Отчество" (3 words)
-- We'll try to split by spaces
UPDATE employees
SET 
    last_name = CASE 
        WHEN full_name IS NOT NULL AND full_name != '' THEN
            SPLIT_PART(TRIM(full_name), ' ', 1)
        ELSE NULL
    END,
    first_name = CASE 
        WHEN full_name IS NOT NULL AND full_name != '' AND array_length(string_to_array(TRIM(full_name), ' '), 1) >= 2 THEN
            SPLIT_PART(TRIM(full_name), ' ', 2)
        ELSE NULL
    END,
    middle_name = CASE 
        WHEN full_name IS NOT NULL AND full_name != '' AND array_length(string_to_array(TRIM(full_name), ' '), 1) >= 3 THEN
            SPLIT_PART(TRIM(full_name), ' ', 3)
        ELSE NULL
    END
WHERE full_name IS NOT NULL;

-- Step 3: Create computed column for full_name (for backward compatibility)
-- Or we can keep full_name as a generated column
-- For now, we'll keep full_name but make it nullable and add a trigger to keep it in sync

-- Step 4: Add indexes for new columns
CREATE INDEX IF NOT EXISTS idx_employees_last_name ON employees(last_name);
CREATE INDEX IF NOT EXISTS idx_employees_first_name ON employees(first_name);
CREATE INDEX IF NOT EXISTS idx_employees_middle_name ON employees(middle_name);

-- Step 5: Create a function to generate full_name from parts
CREATE OR REPLACE FUNCTION employees_full_name(emp employees)
RETURNS TEXT AS $$
BEGIN
    RETURN TRIM(
        COALESCE(emp.last_name || ' ', '') ||
        COALESCE(emp.first_name || ' ', '') ||
        COALESCE(emp.middle_name, '')
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Note: We keep full_name column for now to maintain backward compatibility
-- But new inserts should use last_name, first_name, middle_name

