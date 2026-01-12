CREATE TYPE user_role AS ENUM ('CREATOR', 'CTO', 'IT_HEAD', 'SENIOR_ADMIN', 'ADMIN', 'JUNIOR_ADMIN', 'USER');

CREATE TABLE IF NOT EXISTS telegram_users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    role user_role DEFAULT 'USER',
    karma_points INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telegram_topics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL, -- e.g., 'tickets', 'monitoring'
    thread_id INT NOT NULL,
    description VARCHAR(255)
);

-- Seed topics (IDs will need to be updated with real thread IDs via /setup command or DB edit)
INSERT INTO telegram_topics (name, thread_id, description) VALUES
('tickets', 0, 'Redmine Ticket Stream'),
('assets', 0, 'Asset Inventory Queries'),
('metrics', 0, 'Weekly Metrics & Leaderboard'),
('monitoring', 0, 'Infrastructure Alerts'),
('admin', 0, 'Bot Command Center')
ON CONFLICT (name) DO NOTHING;

