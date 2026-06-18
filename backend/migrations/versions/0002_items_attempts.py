"""items + attempts tables (Phase 1: real exam item types)

`items` is the practice-item bank (TC / SE / RC / vocab). `attempts` is the raw
per-answer signal — the data the spaced-repetition system and (later) the planner
agent reason over.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-16
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id           TEXT PRIMARY KEY,
            type         TEXT NOT NULL,                 -- TC | SE | RC | vocab
            target_words TEXT[] NOT NULL DEFAULT '{}',
            stem         TEXT NOT NULL,
            options      JSONB NOT NULL DEFAULT '[]',   -- shape varies by type
            answer       JSONB NOT NULL,                -- shape varies by type
            explanation  TEXT NOT NULL DEFAULT '',
            difficulty   INTEGER NOT NULL DEFAULT 3,
            status       TEXT NOT NULL DEFAULT 'approved',  -- pending|approved|retired
            source       TEXT NOT NULL DEFAULT 'seed',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_items_type_diff ON items (type, difficulty);")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            id          BIGSERIAL PRIMARY KEY,
            user_id     TEXT NOT NULL,
            item_id     TEXT,
            word        TEXT,
            item_type   TEXT NOT NULL,
            user_answer JSONB,
            is_correct  BOOLEAN,
            error_tags  TEXT[] NOT NULL DEFAULT '{}',
            latency_ms  INTEGER,
            ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_attempts_user_ts ON attempts (user_id, ts DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attempts;")
    op.execute("DROP TABLE IF EXISTS items;")
