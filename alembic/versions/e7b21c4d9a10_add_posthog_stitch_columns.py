"""add users.ext_first_seen_at and leads.ph_distinct_id (PostHog activation + device-hop stitch)

Revision ID: e7b21c4d9a10
Revises: d5f8a91b2c37
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b21c4d9a10'
down_revision: Union[str, Sequence[str], None] = 'd5f8a91b2c37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).fetchone() is not None


def upgrade() -> None:
    # Idempotency guards: skip a column that already exists (manual add, or a previous run
    # that timed out and left alembic_version un-updated) — same pattern as d5f8a91b2c37.
    conn = op.get_bind()
    if not _column_exists(conn, 'users', 'ext_first_seen_at'):
        op.add_column('users', sa.Column('ext_first_seen_at', sa.DateTime(), nullable=True))
    if not _column_exists(conn, 'leads', 'ph_distinct_id'):
        op.add_column('leads', sa.Column('ph_distinct_id', sa.String(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, 'leads', 'ph_distinct_id'):
        op.drop_column('leads', 'ph_distinct_id')
    if _column_exists(conn, 'users', 'ext_first_seen_at'):
        op.drop_column('users', 'ext_first_seen_at')
