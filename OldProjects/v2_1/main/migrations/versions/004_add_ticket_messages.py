"""Add ticket messages table

Revision ID: 004
Revises: 003
Create Date: 2024-01-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ticket Messages - для хранения связи между тикетами OTRS и сообщениями в Telegram
    op.create_table(
        'ticket_messages',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('ticket_id', sa.Integer, sa.ForeignKey('otrs.otrs_tickets.id'), nullable=False),
        sa.Column('ticket_number', sa.String(50), nullable=False),
        sa.Column('chat_id', sa.BigInteger, nullable=False),
        sa.Column('topic_id', sa.Integer, nullable=False),
        sa.Column('message_id', sa.Integer, nullable=False),
        sa.Column('ticket_state', sa.String(50)),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        schema='telegram'
    )
    op.create_index('idx_ticket_messages_ticket_id', 'ticket_messages', ['ticket_id'], schema='telegram')
    op.create_index('idx_ticket_messages_chat_topic', 'ticket_messages', ['chat_id', 'topic_id'], schema='telegram')
    op.create_unique_constraint('uq_ticket_messages_ticket_chat_topic', 
                               'ticket_messages', 
                               ['ticket_id', 'chat_id', 'topic_id'], 
                               schema='telegram')
    
    # Private Ticket Messages - для хранения личных сообщений о тикетах
    op.create_table(
        'private_ticket_messages',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('telegram_id', sa.Integer, nullable=False),
        sa.Column('ticket_id', sa.Integer, nullable=False),
        sa.Column('ticket_number', sa.String(50), nullable=False),
        sa.Column('message_id', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        schema='telegram'
    )
    op.create_index('idx_private_ticket_messages_telegram_id', 'private_ticket_messages', ['telegram_id'], schema='telegram')
    op.create_index('idx_private_ticket_messages_ticket_id', 'private_ticket_messages', ['ticket_id'], schema='telegram')
    op.create_unique_constraint('uq_private_ticket_messages_telegram_ticket', 
                               'private_ticket_messages', 
                               ['telegram_id', 'ticket_id'], 
                               schema='telegram')


def downgrade() -> None:
    op.drop_table('private_ticket_messages', schema='telegram')
    op.drop_table('ticket_messages', schema='telegram')

