"""
Long-term memory: per-word mastery tracking in PostgreSQL.

Spaced repetition schedule:
    Level 0 (unseen)    → never reviewed
    Level 1 (introduced) → review after 1 day
    Level 2 (learning)   → review after 3 days
    Level 3 (familiar)   → review after 7 days
    Level 4 (mastered)   → review after 14 days

Wrong answer → drop 1 level (min 0).
"""

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime, timedelta
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv(override=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://lexis:lexis@localhost:5432/lexis")

REVIEW_INTERVALS = {0: 0, 1: 1, 2: 3, 3: 7, 4: 14}   # days


def _conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Create tables if they don't exist."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
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

            CREATE TABLE IF NOT EXISTS study_sessions (
                session_id    TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL,
                started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ended_at      TIMESTAMPTZ,
                words_studied INTEGER DEFAULT 0,
                correct_count INTEGER DEFAULT 0,
                mode          TEXT
            );

            -- Phase 1: practice-item bank + raw attempt signal. Kept in sync with
            -- Alembic migration 0002 for the no-alembic fallback path.
            CREATE TABLE IF NOT EXISTS items (
                id           TEXT PRIMARY KEY,
                type         TEXT NOT NULL,
                target_words TEXT[] NOT NULL DEFAULT '{}',
                stem         TEXT NOT NULL,
                options      JSONB NOT NULL DEFAULT '[]',
                answer       JSONB NOT NULL,
                explanation  TEXT NOT NULL DEFAULT '',
                difficulty   INTEGER NOT NULL DEFAULT 3,
                status       TEXT NOT NULL DEFAULT 'approved',
                source       TEXT NOT NULL DEFAULT 'seed',
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_items_type_diff ON items (type, difficulty);

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
            CREATE INDEX IF NOT EXISTS idx_attempts_user_ts ON attempts (user_id, ts DESC);

            -- Phase 2: per-user model the planner agent reasons over.
            CREATE TABLE IF NOT EXISTS learner_profile (
                user_id         TEXT PRIMARY KEY,
                ability         JSONB NOT NULL DEFAULT '{}',
                confusion_pairs JSONB NOT NULL DEFAULT '[]',
                notes           JSONB NOT NULL DEFAULT '[]',
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            -- Simple username/password auth (kept in sync with migrations 0004/0005).
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT PRIMARY KEY,
                username      TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                exam_date     DATE,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            ALTER TABLE users ADD COLUMN IF NOT EXISTS exam_date DATE;
        """)
        conn.commit()


def get_mastery(user_id: str, word: str) -> dict:
    """Get mastery record for a single word."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM user_word_mastery WHERE user_id = %s AND word = %s",
            (user_id, word)
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        return {"user_id": user_id, "word": word, "mastery_level": 0,
                "times_seen": 0, "times_correct": 0}


def get_all_mastery(user_id: str) -> dict:
    """Return {word: mastery_level} for all words seen by this user."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT word, mastery_level FROM user_word_mastery WHERE user_id = %s",
            (user_id,)
        )
        return {row["word"]: row["mastery_level"] for row in cur.fetchall()}


def get_words_due_today(user_id: str) -> list[str]:
    """Return words whose next_review date is today or earlier."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT word FROM user_word_mastery
            WHERE user_id = %s
              AND next_review <= NOW()
              AND mastery_level < 4
            ORDER BY next_review ASC
        """, (user_id,))
        return [row["word"] for row in cur.fetchall()]


def update_mastery(user_id: str, word: str, is_correct: bool) -> dict:
    """
    Update mastery level after a quiz answer.
    Returns {"new_level": int, "next_review": str | None}.
    """
    current = get_mastery(user_id, word)
    level = current["mastery_level"]

    new_level = min(level + 1, 4) if is_correct else max(level - 1, 0)
    days = REVIEW_INTERVALS[new_level]
    next_review = datetime.utcnow() + timedelta(days=days) if days > 0 else None

    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO user_word_mastery
                (user_id, word, mastery_level, times_seen, times_correct, last_seen, next_review)
            VALUES (%s, %s, %s, 1, %s, NOW(), %s)
            ON CONFLICT (user_id, word) DO UPDATE SET
                mastery_level  = EXCLUDED.mastery_level,
                times_seen     = user_word_mastery.times_seen + 1,
                times_correct  = user_word_mastery.times_correct + %s,
                last_seen      = NOW(),
                next_review    = EXCLUDED.next_review
        """, (
            user_id, word, new_level, 1 if is_correct else 0, next_review,
            1 if is_correct else 0
        ))
        conn.commit()

    return {
        "new_level": new_level,
        "next_review": next_review.isoformat() if next_review else None,
    }


def record_word_seen(user_id: str, word: str) -> None:
    """
    Record that the user saw a word during a learn turn (no mastery change).
    Upserts the row so the word appears in stats even before the first quiz.
    """
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO user_word_mastery
                (user_id, word, mastery_level, times_seen, last_seen, next_review)
            VALUES (%s, %s, 1, 1, NOW(), NOW() + INTERVAL '1 day')
            ON CONFLICT (user_id, word) DO UPDATE SET
                times_seen = user_word_mastery.times_seen + 1,
                last_seen  = NOW()
        """, (user_id, word))
        conn.commit()


def bulk_set_mastery(user_id: str, mastery_map: dict) -> None:
    """
    Set initial mastery levels from diagnostic results.
    mastery_map: {word: level (0-4)}
    """
    with _conn() as conn, conn.cursor() as cur:
        for word, level in mastery_map.items():
            level = max(0, min(int(level), 4))
            days = REVIEW_INTERVALS[level]
            next_review = datetime.utcnow() + timedelta(days=days) if days > 0 else None
            cur.execute("""
                INSERT INTO user_word_mastery
                    (user_id, word, mastery_level, times_seen, times_correct, last_seen, next_review)
                VALUES (%s, %s, %s, 0, 0, NOW(), %s)
                ON CONFLICT (user_id, word) DO UPDATE SET
                    mastery_level = EXCLUDED.mastery_level,
                    next_review = EXCLUDED.next_review
            """, (user_id, word, level, next_review))
        conn.commit()


def get_study_stats(user_id: str) -> dict:
    """Return aggregate study stats for the dashboard."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT
                COUNT(*) AS words_seen,
                COALESCE(SUM(times_seen), 0) AS total_reviews,
                COALESCE(SUM(times_correct), 0) AS total_correct,
                COALESCE(AVG(mastery_level), 0) AS avg_mastery,
                COUNT(*) FILTER (WHERE mastery_level >= 4) AS mastered,
                COUNT(*) FILTER (WHERE mastery_level = 3) AS familiar,
                COUNT(*) FILTER (WHERE mastery_level BETWEEN 1 AND 2) AS learning
            FROM user_word_mastery
            WHERE user_id = %s
        """, (user_id,))
        row = dict(cur.fetchone() or {})

    total_reviews = int(row.get("total_reviews") or 0)
    total_correct = int(row.get("total_correct") or 0)
    accuracy = round(total_correct / total_reviews, 3) if total_reviews else 0
    words_seen = int(row.get("words_seen") or 0)
    return {
        "words_seen": words_seen,
        "total_words_seen": words_seen,
        "total_reviews": total_reviews,
        "total_correct": total_correct,
        "accuracy": accuracy,
        "avg_accuracy": accuracy,
        "avg_mastery": round(float(row.get("avg_mastery") or 0), 2),
        "mastered": int(row.get("mastered") or 0),
        "familiar": int(row.get("familiar") or 0),
        "learning": int(row.get("learning") or 0),
    }


# ── Item bank + attempts (Phase 1) ───────────────────────────────────────────

def insert_item(item: dict) -> None:
    """Upsert a practice item. `options`/`answer` are JSON-serializable structures."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO items
                (id, type, target_words, stem, options, answer, explanation,
                 difficulty, status, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                type = EXCLUDED.type, target_words = EXCLUDED.target_words,
                stem = EXCLUDED.stem, options = EXCLUDED.options,
                answer = EXCLUDED.answer, explanation = EXCLUDED.explanation,
                difficulty = EXCLUDED.difficulty, status = EXCLUDED.status,
                source = EXCLUDED.source
            """,
            (
                item["id"], item["type"], item.get("target_words", []),
                item["stem"], Json(item.get("options", [])), Json(item["answer"]),
                item.get("explanation", ""), int(item.get("difficulty", 3)),
                item.get("status", "approved"), item.get("source", "seed"),
            ),
        )
        conn.commit()


def get_item(item_id: str) -> Optional[dict]:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def next_item_for(
    user_id: str,
    item_type: str,
    min_difficulty: int = 1,
    max_difficulty: int = 5,
) -> Optional[dict]:
    """
    Serve the next approved item of `item_type` the user hasn't answered correctly
    yet, within [min_difficulty, max_difficulty] (easiest first). The difficulty
    window lets the planner drop difficulty after a miss or step up after a win.
    Falls back to the full range if nothing matches the window.
    """
    lo, hi = max(1, int(min_difficulty)), min(5, int(max_difficulty))

    def _query(low: int, high: int) -> Optional[dict]:
        with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT i.* FROM items i
                WHERE i.type = %s AND i.status = 'approved'
                  AND i.difficulty BETWEEN %s AND %s
                  AND NOT EXISTS (
                      SELECT 1 FROM attempts a
                      WHERE a.user_id = %s AND a.item_id = i.id AND a.is_correct = TRUE
                  )
                ORDER BY i.difficulty ASC, random()
                LIMIT 1
                """,
                (item_type, low, high, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    return _query(lo, hi) or _query(1, 5)


def get_item_stems(item_type: str) -> list[str]:
    """All stems for a type — used by the generator to avoid producing duplicates."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT stem FROM items WHERE type = %s", (item_type,))
        return [r[0] for r in cur.fetchall()]


def count_items(item_type: str = None) -> int:
    with _conn() as conn, conn.cursor() as cur:
        if item_type:
            cur.execute("SELECT COUNT(*) FROM items WHERE type = %s", (item_type,))
        else:
            cur.execute("SELECT COUNT(*) FROM items")
        return int(cur.fetchone()[0])


def record_attempt(
    user_id: str,
    item_type: str,
    *,
    item_id: Optional[str] = None,
    word: Optional[str] = None,
    user_answer=None,
    is_correct: Optional[bool] = None,
    error_tags: Optional[list[str]] = None,
    latency_ms: Optional[int] = None,
) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO attempts
                (user_id, item_id, word, item_type, user_answer, is_correct,
                 error_tags, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id, item_id, word, item_type,
                Json(user_answer) if user_answer is not None else None,
                is_correct, error_tags or [], latency_ms,
            ),
        )
        conn.commit()


def get_recent_attempts(user_id: str, n: int = 20) -> list[dict]:
    """Most recent attempts (newest first) — basis for Phase 2 error-pattern diagnosis."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM attempts WHERE user_id = %s ORDER BY ts DESC LIMIT %s",
            (user_id, n),
        )
        return [dict(r) for r in cur.fetchall()]