"""Add notes column to employee_snapshots

Revision ID: 006
Revises: 005
Create Date: 2024-12-21
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем колонку notes для хранения описания версии
    op.add_column(
        'employee_snapshots',
        sa.Column('notes', sa.Text, nullable=True),
        schema='backups'
    )


def downgrade() -> None:
    op.drop_column('employee_snapshots', 'notes', schema='backups')

