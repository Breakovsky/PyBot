"""Add employee snapshots table

Revision ID: 005
Revises: 004
Create Date: 2024-12-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаём схему для snapshots если её нет
    op.execute("CREATE SCHEMA IF NOT EXISTS backups")
    
    # Таблица снапшотов сотрудников
    op.create_table(
        'employee_snapshots',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('snapshot_name', sa.String(255), nullable=False),
        sa.Column('snapshot_type', sa.String(50), nullable=False),  # 'daily', 'auto', 'manual'
        sa.Column('created_by', sa.String(255)),  # Кто создал снапшот
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('employees_data', postgresql.JSONB, nullable=False),  # JSON с данными всех сотрудников
        schema='backups'
    )
    op.create_index('idx_snapshots_type', 'employee_snapshots', ['snapshot_type'], schema='backups')
    op.create_index('idx_snapshots_created_at', 'employee_snapshots', ['created_at'], schema='backups')
    op.create_index('idx_snapshots_name', 'employee_snapshots', ['snapshot_name'], schema='backups')


def downgrade() -> None:
    op.drop_table('employee_snapshots', schema='backups')
    op.execute("DROP SCHEMA IF EXISTS backups")

