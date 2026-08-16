"""add sub_lapsed_at to users

Revision ID: a3f8b2d91c05
Revises: c419420d1f1e
Create Date: 2026-08-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8b2d91c05'
down_revision: Union[str, Sequence[str], None] = 'c419420d1f1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('sub_lapsed_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'sub_lapsed_at')
