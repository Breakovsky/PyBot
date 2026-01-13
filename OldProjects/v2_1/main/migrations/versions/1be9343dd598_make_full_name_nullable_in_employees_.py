"""Make full_name nullable in employees table

Revision ID: 1be9343dd598
Revises: 007
Create Date: 2025-12-21 17:36:44.958172

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1be9343dd598'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Делаем full_name опциональным в таблице employees
    op.alter_column('employees', 'full_name',
                    existing_type=sa.String(255),
                    nullable=True,
                    schema='employees')


def downgrade() -> None:
    # Возвращаем обязательность full_name
    op.alter_column('employees', 'full_name',
                    existing_type=sa.String(255),
                    nullable=False,
                    schema='employees')



