CREATE TABLE IF NOT EXISTS workstation_ranges (
    id SERIAL PRIMARY KEY,
    prefix VARCHAR(20) NOT NULL,
    range_start INTEGER NOT NULL,
    range_end INTEGER NOT NULL,
    description VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Initial Seed Data
INSERT INTO workstation_ranges (prefix, range_start, range_end, description) VALUES
    ('WS', 1, 100, 'Standard Workstations'),
    ('PWS', 1, 50, 'Power Workstations'),
    ('NIK', 1, 30, 'Nikolaev Office'),
    ('WSE', 1, 50, 'Engineering'),
    ('WSM', 1, 50, 'Manufacturing');

