"""Add pending deletions table

Revision ID: 002
Revises: 001
Create Date: 2024-01-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Pending Deletions - для отслеживания сообщений, которые нужно удалить
    # Instruction Messages - для сохранения ID сообщений-инструкций
    op.create_table(
        'instruction_messages',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('chat_id', sa.BigInteger, nullable=False),
        sa.Column('topic_id', sa.Integer, nullable=False),
        sa.Column('message_type', sa.String(50), nullable=False),  # e.g., 'excel_instruction'
        sa.Column('message_id', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        schema='telegram'
    )
    op.create_unique_constraint('uq_instruction_message_type', 
                               'instruction_messages', 
                               ['chat_id', 'topic_id', 'message_type'], 
                               schema='telegram')
    op.create_index('idx_instruction_messages_chat_topic', 'instruction_messages', 
                   ['chat_id', 'topic_id'], schema='telegram')
    
    # Pending Deletions - для отслеживания сообщений, которые нужно удалить
    op.create_table(
        'pending_deletions',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('chat_id', sa.BigInteger, nullable=False),
        sa.Column('topic_id', sa.Integer, nullable=True),  # Может быть NULL для личных сообщений
        sa.Column('message_id', sa.Integer, nullable=False),
        sa.Column('delete_after', sa.DateTime, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        schema='telegram'
    )
    op.create_index('idx_pending_deletions_chat_topic', 'pending_deletions', 
                   ['chat_id', 'topic_id'], schema='telegram')
    op.create_index('idx_pending_deletions_topic', 'pending_deletions', 
                   ['topic_id'], schema='telegram')
    op.create_index('idx_pending_deletions_delete_after', 'pending_deletions', 
                   ['delete_after'], schema='telegram')
    op.create_unique_constraint('uq_pending_deletions_chat_message', 
                               'pending_deletions', 
                               ['chat_id', 'message_id'], 
                               schema='telegram')


def downgrade() -> None:
    op.drop_table('pending_deletions', schema='telegram')
    op.drop_table('instruction_messages', schema='telegram')

