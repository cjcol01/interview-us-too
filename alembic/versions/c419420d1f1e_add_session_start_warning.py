"""add session_start_warning to users

Revision ID: c419420d1f1e
Revises: c1a770f1636e
Create Date: 2026-08-16 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c419420d1f1e'
down_revision: Union[str, Sequence[str], None] = 'c1a770f1636e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default='1' works for both SQLite and PostgreSQL (Postgres also accepts '1' for boolean).
    op.add_column(
        'users',
        sa.Column(
            'session_start_warning',
            sa.Boolean(),
            nullable=False,
            server_default='1',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'session_start_warning')
