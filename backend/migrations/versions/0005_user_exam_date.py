"""per-user GRE exam date

A nullable target date each tester can set, used to show a countdown on the
dashboard. Per-user (not a global env var) now that accounts exist.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-17
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS exam_date DATE;")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS exam_date;")
