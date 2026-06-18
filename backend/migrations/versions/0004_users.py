"""users table (simple username/password auth)

One row per tester. `user_id` is the normalized username and is what every other
table keys progress by — so logging in as the same username returns that user's
attempts, learner_profile, and mastery, while a new username starts fresh.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-17
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id       TEXT PRIMARY KEY,    -- normalized username; FK target for progress
            username      TEXT NOT NULL,       -- original display form
            password_hash TEXT NOT NULL,       -- pbkdf2: "<salt_hex>$<derived_hex>"
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS users;")
