"""Add missing tables from v2_0

Revision ID: 007
Revises: 006
Create Date: 2024-01-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаём схему backups если её нет
    op.execute("CREATE SCHEMA IF NOT EXISTS backups")
    
    # Daily Stats - дневная статистика серверов
    op.create_table(
        'daily_stats',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('server_id', sa.Integer, sa.ForeignKey('monitoring.servers.id'), nullable=False),
        sa.Column('date', sa.Date, nullable=False),
        sa.Column('uptime_seconds', sa.Integer, default=0),
        sa.Column('downtime_seconds', sa.Integer, default=0),
        sa.Column('downtime_count', sa.Integer, default=0),
        schema='monitoring'
    )
    op.create_index('idx_daily_stat_server_id', 'daily_stats', ['server_id'], schema='monitoring')
    op.create_index('idx_daily_stat_date', 'daily_stats', ['date'], schema='monitoring')
    op.create_unique_constraint(
        'uq_daily_stat_server_date',
        'daily_stats',
        ['server_id', 'date'],
        schema='monitoring'
    )
    
    # User Private Tickets - личные сообщения с тикетами
    # Проверяем, существует ли таблица (может быть создана в миграции 004)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names(schema='otrs')
    
    if 'user_private_tickets' not in tables:
        op.create_table(
            'user_private_tickets',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('telegram_user_id', sa.Integer, 
                     sa.ForeignKey('telegram.telegram_users.id'), nullable=False),
            sa.Column('ticket_id', sa.Integer, 
                     sa.ForeignKey('otrs.otrs_tickets.id'), nullable=False),
            sa.Column('ticket_number', sa.String(50), nullable=False),
            sa.Column('message_id', sa.Integer, nullable=False),
            sa.Column('assigned_at', sa.DateTime, server_default=sa.func.now()),
            schema='otrs'
        )
        op.create_index('idx_private_ticket_user', 'user_private_tickets', 
                       ['telegram_user_id'], schema='otrs')
        op.create_index('idx_private_ticket_ticket', 'user_private_tickets', 
                       ['ticket_id'], schema='otrs')
        op.create_unique_constraint(
            'uq_user_private_ticket',
            'user_private_tickets',
            ['telegram_user_id', 'ticket_id'],
            schema='otrs'
        )
    
    # AD Users - пользователи Active Directory (опционально)
    tables_core = inspector.get_table_names(schema='core')
    if 'ad_users' not in tables_core:
        op.create_table(
            'ad_users',
            sa.Column('email', sa.String(255), primary_key=True),
            sa.Column('full_name', sa.String(255)),
            sa.Column('first_name', sa.String(255)),
            sa.Column('last_name', sa.String(255)),
            sa.Column('is_active', sa.Boolean, default=True),
            sa.Column('synced_at', sa.DateTime, server_default=sa.func.now()),
            schema='core'
        )
    
    # Исправляем OTRS Ticket Messages - должна быть в схеме otrs, а не telegram
    # Проверяем, где находится таблица
    if 'ticket_messages' in inspector.get_table_names(schema='telegram'):
        # Миграция: переносим из telegram в otrs
        op.execute("""
            CREATE TABLE IF NOT EXISTS otrs.otrs_ticket_messages (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES otrs.otrs_tickets(id),
                ticket_number VARCHAR(50) NOT NULL,
                message_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                topic_id INTEGER,
                ticket_state VARCHAR(50),
                sent_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        op.execute("""
            INSERT INTO otrs.otrs_ticket_messages 
            (ticket_id, ticket_number, message_id, chat_id, topic_id, ticket_state, sent_at, updated_at)
            SELECT 
                tm.ticket_id,
                tm.ticket_number,
                tm.message_id,
                tm.chat_id,
                tm.topic_id,
                tm.ticket_state,
                tm.created_at,
                tm.updated_at
            FROM telegram.ticket_messages tm
            ON CONFLICT DO NOTHING
        """)
        op.drop_table('ticket_messages', schema='telegram')
        op.drop_table('private_ticket_messages', schema='telegram')
        
        # Создаём индексы и ограничения
        op.create_index('idx_ticket_message_ticket_id', 'otrs_ticket_messages', 
                       ['ticket_id'], schema='otrs')
        op.create_index('idx_ticket_message_chat_topic', 'otrs_ticket_messages', 
                       ['chat_id', 'topic_id'], schema='otrs')
        op.create_unique_constraint(
            'uq_ticket_chat_topic',
            'otrs_ticket_messages',
            ['ticket_id', 'chat_id', 'topic_id'],
            schema='otrs'
        )


def downgrade() -> None:
    op.drop_table('daily_stats', schema='monitoring')
    op.drop_table('user_private_tickets', schema='otrs')
    op.drop_table('ad_users', schema='core')

