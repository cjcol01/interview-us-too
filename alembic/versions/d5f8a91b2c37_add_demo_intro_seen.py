"""add demo_intro_seen to users

Revision ID: d5f8a91b2c37
Revises: c419420d1f1e
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5f8a91b2c37'
down_revision: Union[str, Sequence[str], None] = 'a3f8b2d91c05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotency guard: skip if the column already exists (e.g. manual add, or
    # a previous run that timed out and left alembic_version un-updated).
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'users' AND column_name = 'demo_intro_seen'"
    )).fetchone()
    if exists:
        return

    op.add_column(
        'users',
        sa.Column(
            'demo_intro_seen',
            sa.Boolean(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'demo_intro_seen')
