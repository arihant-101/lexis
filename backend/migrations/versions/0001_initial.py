"""initial schema: user_word_mastery + study_sessions

Mirrors the DDL that used to live in memory.longterm.init_db(). Uses IF NOT EXISTS
so it is safe to run against a database that was already bootstrapped by init_db().

Revision ID: 0001
Revises:
Create Date: 2026-06-15
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_word_mastery (
            user_id       TEXT NOT NULL,
            word          TEXT NOT NULL,
            mastery_level INTEGER NOT NULL DEFAULT 0,
            times_seen    INTEGER NOT NULL DEFAULT 0,
            times_correct INTEGER NOT NULL DEFAULT 0,
            last_seen     TIMESTAMPTZ,
            next_review   TIMESTAMPTZ,
            PRIMARY KEY (user_id, word)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS study_sessions (
            session_id    TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at      TIMESTAMPTZ,
            words_studied INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            mode          TEXT
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS study_sessions;")
    op.execute("DROP TABLE IF EXISTS user_word_mastery;")
