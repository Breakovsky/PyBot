"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем схемы
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS telegram")
    op.execute("CREATE SCHEMA IF NOT EXISTS employees")
    op.execute("CREATE SCHEMA IF NOT EXISTS monitoring")
    op.execute("CREATE SCHEMA IF NOT EXISTS otrs")
    op.execute("CREATE SCHEMA IF NOT EXISTS cluster")
    
    # ============================================
    # CORE SCHEMA
    # ============================================
    
    # Settings
    op.create_table(
        'settings',
        sa.Column('key', sa.String(255), primary_key=True),
        sa.Column('value', sa.Text),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('is_secret', sa.Boolean, default=False),
        sa.Column('description', sa.Text),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('updated_by', sa.String(255)),
        schema='core'
    )
    op.create_index('idx_settings_category', 'settings', ['category'], schema='core')
    
    # Users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255)),
        sa.Column('full_name', sa.String(255)),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('is_admin', sa.Boolean, default=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('last_login', sa.DateTime),
        sa.Column('password_set_at', sa.DateTime),
        schema='core'
    )
    op.create_index('idx_users_email', 'users', ['email'], schema='core')
    
    # Audit Log
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('core.users.id')),
        sa.Column('user_email', sa.String(255)),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('resource_type', sa.String(50)),
        sa.Column('resource_id', sa.String(255)),
        sa.Column('details', postgresql.JSON),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('user_agent', sa.Text),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        schema='core'
    )
    op.create_index('idx_audit_user_id', 'audit_log', ['user_id'], schema='core')
    op.create_index('idx_audit_action_type', 'audit_log', ['action_type'], schema='core')
    op.create_index('idx_audit_created_at', 'audit_log', ['created_at'], schema='core')
    op.create_index('idx_audit_user_time', 'audit_log', ['user_id', 'created_at'], schema='core')
    
    # ============================================
    # TELEGRAM SCHEMA
    # ============================================
    
    # Telegram Users
    op.create_table(
        'telegram_users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('telegram_id', sa.Integer, unique=True, nullable=False),
        sa.Column('telegram_username', sa.String(255)),
        sa.Column('full_name', sa.String(255)),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('core.users.id')),
        sa.Column('otrs_email', sa.String(255)),
        sa.Column('verified_at', sa.DateTime),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        schema='telegram'
    )
    op.create_index('idx_telegram_users_telegram_id', 'telegram_users', ['telegram_id'], schema='telegram')
    
    # Telegram Chats
    op.create_table(
        'telegram_chats',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('chat_id', sa.Integer, nullable=False),
        sa.Column('topic_id', sa.Integer),
        sa.Column('chat_title', sa.String(255)),
        sa.Column('topic_title', sa.String(255)),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        schema='telegram'
    )
    op.create_index('idx_telegram_chats_chat_id', 'telegram_chats', ['chat_id'], schema='telegram')
    op.create_index('idx_telegram_chats_chat_topic', 'telegram_chats', ['chat_id', 'topic_id'], schema='telegram')
    
    # Telegram Messages
    op.create_table(
        'telegram_messages',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('chat_id', sa.Integer, nullable=False),
        sa.Column('topic_id', sa.Integer),
        sa.Column('message_type', sa.String(50), nullable=False),
        sa.Column('message_id', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        schema='telegram'
    )
    op.create_index('idx_telegram_messages_chat_topic_type', 'telegram_messages', 
                   ['chat_id', 'topic_id', 'message_type'], unique=True, schema='telegram')
    
    # Verification Codes (для авторизации через email)
    op.create_table(
        'verification_codes',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('telegram_id', sa.Integer, unique=True, nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('code', sa.String(6), nullable=False),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        schema='telegram'
    )
    op.create_index('idx_verification_codes_telegram_id', 'verification_codes', ['telegram_id'], schema='telegram')
    op.create_index('idx_verification_codes_expires_at', 'verification_codes', ['expires_at'], schema='telegram')
    
    # ============================================
    # EMPLOYEES SCHEMA
    # ============================================
    
    # Departments
    op.create_table(
        'departments',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(255), unique=True, nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        schema='employees'
    )
    
    # Workstations
    op.create_table(
        'workstations',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(255), unique=True, nullable=False),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('description', sa.Text),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        schema='employees'
    )
    op.create_index('idx_workstations_name', 'workstations', ['name'], schema='employees')
    op.create_index('idx_workstations_ip', 'workstations', ['ip_address'], schema='employees')
    
    # Employees
    op.create_table(
        'employees',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('department_id', sa.Integer, sa.ForeignKey('employees.departments.id')),
        sa.Column('workstation_id', sa.Integer, sa.ForeignKey('employees.workstations.id')),
        sa.Column('phone', sa.String(50)),
        sa.Column('ad_account', sa.String(255)),
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('updated_by', sa.String(255)),
        schema='employees'
    )
    op.create_index('idx_employees_name', 'employees', ['full_name'], schema='employees')
    op.create_index('idx_employees_phone', 'employees', ['phone'], schema='employees')
    op.create_index('idx_employees_department', 'employees', ['department_id'], schema='employees')
    
    # ============================================
    # MONITORING SCHEMA
    # ============================================
    
    # Server Groups
    op.create_table(
        'server_groups',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(255), unique=True, nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        schema='monitoring'
    )
    
    # Servers
    op.create_table(
        'servers',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=False),
        sa.Column('server_group_id', sa.Integer, sa.ForeignKey('monitoring.server_groups.id'), nullable=False),
        sa.Column('first_seen', sa.DateTime, server_default=sa.func.now()),
        sa.Column('last_seen', sa.DateTime, server_default=sa.func.now()),
        schema='monitoring'
    )
    op.create_index('idx_servers_name', 'servers', ['name'], schema='monitoring')
    op.create_index('idx_servers_ip', 'servers', ['ip_address'], schema='monitoring')
    op.create_index('idx_servers_group', 'servers', ['server_group_id'], schema='monitoring')
    op.create_index('idx_servers_group_name', 'servers', ['server_group_id', 'name'], unique=True, schema='monitoring')
    
    # Server Events
    op.create_table(
        'server_events',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('server_id', sa.Integer, sa.ForeignKey('monitoring.servers.id'), nullable=False),
        sa.Column('event_type', sa.String(10), nullable=False),
        sa.Column('event_time', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('duration_seconds', sa.Integer),
        schema='monitoring'
    )
    op.create_index('idx_server_events_server_id', 'server_events', ['server_id'], schema='monitoring')
    op.create_index('idx_server_events_time', 'server_events', ['event_time'], schema='monitoring')
    op.create_index('idx_server_events_server_time', 'server_events', ['server_id', 'event_time'], schema='monitoring')
    
    # Server Metrics
    op.create_table(
        'server_metrics',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('server_id', sa.Integer, sa.ForeignKey('monitoring.servers.id'), unique=True, nullable=False),
        sa.Column('total_uptime_seconds', sa.Integer, default=0),
        sa.Column('total_downtime_seconds', sa.Integer, default=0),
        sa.Column('downtime_count', sa.Integer, default=0),
        sa.Column('longest_downtime_seconds', sa.Integer, default=0),
        sa.Column('last_status', sa.String(10), default='UNKNOWN'),
        sa.Column('last_status_change', sa.DateTime),
        schema='monitoring'
    )
    
    # ============================================
    # OTRS SCHEMA
    # ============================================
    
    # OTRS Users
    op.create_table(
        'otrs_users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('telegram_user_id', sa.Integer, sa.ForeignKey('telegram.telegram_users.id'), unique=True),
        sa.Column('otrs_email', sa.String(255), nullable=False),
        sa.Column('otrs_username', sa.String(255)),
        sa.Column('verified_at', sa.DateTime, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        schema='otrs'
    )
    op.create_index('idx_otrs_users_email', 'otrs_users', ['otrs_email'], schema='otrs')
    
    # OTRS Tickets
    op.create_table(
        'otrs_tickets',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('ticket_id', sa.Integer, unique=True, nullable=False),
        sa.Column('ticket_number', sa.String(50), unique=True, nullable=False),
        sa.Column('title', sa.String(500)),
        sa.Column('state', sa.String(50)),
        sa.Column('priority', sa.Integer),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('last_seen_at', sa.DateTime, server_default=sa.func.now()),
        schema='otrs'
    )
    op.create_index('idx_otrs_tickets_id', 'otrs_tickets', ['ticket_id'], schema='otrs')
    op.create_index('idx_otrs_tickets_number', 'otrs_tickets', ['ticket_number'], schema='otrs')
    
    # OTRS Metrics
    op.create_table(
        'otrs_metrics',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('telegram_user_id', sa.Integer, sa.ForeignKey('telegram.telegram_users.id'), nullable=False),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('ticket_id', sa.Integer, sa.ForeignKey('otrs.otrs_tickets.id'), nullable=False),
        sa.Column('ticket_number', sa.String(50)),
        sa.Column('ticket_title', sa.String(500)),
        sa.Column('details', postgresql.JSON),
        sa.Column('action_time', sa.DateTime, nullable=False, server_default=sa.func.now()),
        schema='otrs'
    )
    op.create_index('idx_otrs_metrics_user_id', 'otrs_metrics', ['telegram_user_id'], schema='otrs')
    op.create_index('idx_otrs_metrics_action_time', 'otrs_metrics', ['action_time'], schema='otrs')
    op.create_index('idx_otrs_metrics_user_action_time', 'otrs_metrics', 
                   ['telegram_user_id', 'action_type', 'action_time'], schema='otrs')
    
    # ============================================
    # CLUSTER SCHEMA
    # ============================================
    
    # Cluster Nodes
    op.create_table(
        'cluster_nodes',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('node_id', sa.String(100), unique=True, nullable=False),
        sa.Column('node_type', sa.String(50)),
        sa.Column('hostname', sa.String(255)),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('is_leader', sa.Boolean, default=False),
        sa.Column('last_heartbeat', sa.DateTime, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        schema='cluster'
    )
    op.create_index('idx_cluster_nodes_node_id', 'cluster_nodes', ['node_id'], schema='cluster')
    op.create_index('idx_cluster_nodes_active', 'cluster_nodes', ['is_active'], schema='cluster')
    
    # Cluster Locks
    op.create_table(
        'cluster_locks',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('lock_name', sa.String(255), unique=True, nullable=False),
        sa.Column('node_id', sa.String(100), nullable=False),
        sa.Column('acquired_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        schema='cluster'
    )
    op.create_index('idx_cluster_locks_name', 'cluster_locks', ['lock_name'], schema='cluster')
    op.create_index('idx_cluster_locks_expires', 'cluster_locks', ['expires_at'], schema='cluster')


def downgrade() -> None:
    # Удаляем таблицы в обратном порядке
    op.drop_table('cluster_locks', schema='cluster')
    op.drop_table('cluster_nodes', schema='cluster')
    op.drop_table('otrs_metrics', schema='otrs')
    op.drop_table('otrs_tickets', schema='otrs')
    op.drop_table('otrs_users', schema='otrs')
    op.drop_table('server_metrics', schema='monitoring')
    op.drop_table('server_events', schema='monitoring')
    op.drop_table('servers', schema='monitoring')
    op.drop_table('server_groups', schema='monitoring')
    op.drop_table('employees', schema='employees')
    op.drop_table('workstations', schema='employees')
    op.drop_table('departments', schema='employees')
    op.drop_table('verification_codes', schema='telegram')
    op.drop_table('telegram_messages', schema='telegram')
    op.drop_table('telegram_chats', schema='telegram')
    op.drop_table('telegram_users', schema='telegram')
    op.drop_table('audit_log', schema='core')
    op.drop_table('users', schema='core')
    op.drop_table('settings', schema='core')
    
    # Удаляем схемы
    op.execute("DROP SCHEMA IF EXISTS cluster")
    op.execute("DROP SCHEMA IF EXISTS otrs")
    op.execute("DROP SCHEMA IF EXISTS monitoring")
    op.execute("DROP SCHEMA IF EXISTS employees")
    op.execute("DROP SCHEMA IF EXISTS telegram")
    op.execute("DROP SCHEMA IF EXISTS core")



