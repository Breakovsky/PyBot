"""Add verification codes table

Revision ID: 003
Revises: 002
Create Date: 2024-01-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table('verification_codes', schema='telegram')

