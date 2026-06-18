"""learner_profile table (Phase 2: the model the planner reasons over)

Holds a per-skill ability estimate (deterministic Elo) plus LLM-curated confusion
pairs and notes. One row per user.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-17
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learner_profile (
            user_id         TEXT PRIMARY KEY,
            ability         JSONB NOT NULL DEFAULT '{}',   -- {"TC": 1234.5, "SE": ..., ...}
            confusion_pairs JSONB NOT NULL DEFAULT '[]',   -- [["prodigal","prodigious"], ...]
            notes           JSONB NOT NULL DEFAULT '[]',   -- LLM-curated observations
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS learner_profile;")
