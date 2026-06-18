"""
Learner model — the per-user state the Phase 2 planner reasons over.

Two halves, deliberately separated:
  - DETERMINISTIC: per-skill ability via an Elo update on every attempt. Fast,
    auditable, never an LLM call.
  - LLM-CURATED (later, P2-7): confusion_pairs + notes, refreshed once per session.

Skills are the item types: TC, SE, RC, vocab.
"""

from collections import Counter
from typing import Optional

from psycopg2.extras import Json, RealDictCursor

from llm.router import Task, acomplete_json
from memory.longterm import _conn, get_recent_attempts
from observability.logger import log
from tools.config import OPENROUTER_API_KEY, _has_real_key

START_RATING = 1200.0
K = 32.0
SKILLS = ["TC", "SE", "RC", "vocab"]


def _item_rating(difficulty: int) -> float:
    """Map item difficulty (1-5) to an Elo-style opponent rating."""
    d = max(1, min(int(difficulty), 5))
    return 1000.0 + d * 120.0


def _expected(player: float, opponent: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent - player) / 400.0))


def get_profile(user_id: str) -> dict:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM learner_profile WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    if row:
        return dict(row)
    return {"user_id": user_id, "ability": {}, "confusion_pairs": [], "notes": []}


def update_ability(user_id: str, skill: str, item_difficulty: int, correct: bool) -> float:
    """Elo update for one skill after one attempt. Returns the new rating."""
    profile = get_profile(user_id)
    ability = dict(profile.get("ability") or {})
    r = float(ability.get(skill, START_RATING))
    expected = _expected(r, _item_rating(item_difficulty))
    actual = 1.0 if correct else 0.0
    new_r = round(r + K * (actual - expected), 1)
    ability[skill] = new_r

    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO learner_profile (user_id, ability)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                ability = %s, updated_at = NOW()
            """,
            (user_id, Json(ability), Json(ability)),
        )
        conn.commit()
    log("ability_updated", user_id=user_id, skill=skill, rating=new_r, correct=correct)
    return new_r


def set_curation(user_id: str, confusion_pairs: list, notes: list) -> None:
    """Persist the LLM-curated half of the profile (P2-7)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO learner_profile (user_id, confusion_pairs, notes)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                confusion_pairs = %s, notes = %s, updated_at = NOW()
            """,
            (user_id, Json(confusion_pairs), Json(notes), Json(confusion_pairs), Json(notes)),
        )
        conn.commit()


def get_weak_skills(user_id: str, recent_n: int = 20) -> dict:
    """
    Summary the planner uses to decide what to work on:
      - ability per skill (weakest first)
      - the most common error tags in recent attempts
      - overall recent accuracy
    """
    profile = get_profile(user_id)
    ability = {s: float(profile.get("ability", {}).get(s, START_RATING)) for s in SKILLS}
    ranked = sorted(ability.items(), key=lambda kv: kv[1])

    attempts = get_recent_attempts(user_id, recent_n)
    tag_counts: Counter = Counter()
    correct = 0
    for a in attempts:
        for t in (a.get("error_tags") or []):
            if t != "none":
                tag_counts[t] += 1
        if a.get("is_correct"):
            correct += 1

    return {
        "ability": ability,
        "weakest_skill": ranked[0][0] if ranked else None,
        "skills_ranked": [s for s, _ in ranked],
        "top_error_tags": [t for t, _ in tag_counts.most_common(3)],
        "recent_accuracy": round(correct / len(attempts), 2) if attempts else None,
        "recent_count": len(attempts),
        "notes": profile.get("notes") or [],
        "confusion_pairs": profile.get("confusion_pairs") or [],
    }


# ── LLM-curated diagnosis (P2-7) ─────────────────────────────────────────────

DIAGNOSE_SYSTEM = """You are a GRE Verbal coach reviewing a student's recent attempts.
Find DURABLE patterns (recurring across attempts), not one-offs. Return JSON:
{
  "notes": ["<= 3 short, specific, actionable observations about their weaknesses>"],
  "confusion_pairs": [["wordA", "wordB"], ...]
}
Base notes on the recurring error tags and which skills they miss. If you see no clear
pattern or there is too little data, return empty lists. Be concrete and encouraging."""


async def curate_profile(user_id: str, recent_n: int = 30) -> dict:
    """End-of-session pass: synthesize recent attempts into notes + confusion pairs.
    Runs once per session (not per turn) — it's a strong-model call."""
    if not _has_real_key(OPENROUTER_API_KEY):
        return {"notes": [], "confusion_pairs": []}

    attempts = get_recent_attempts(user_id, recent_n)
    if len(attempts) < 3:
        return {"notes": [], "confusion_pairs": []}

    lines = [
        f"type={a['item_type']} correct={a['is_correct']} tags={a.get('error_tags')} word={a.get('word')}"
        for a in attempts
    ]
    user = "Recent attempts (newest first):\n" + "\n".join(lines)

    try:
        data = await acomplete_json(Task.DIAGNOSE, DIAGNOSE_SYSTEM, user)
        notes = [str(n) for n in (data.get("notes") or [])][:3]
        pairs = [p for p in (data.get("confusion_pairs") or []) if isinstance(p, list) and len(p) == 2]
        set_curation(user_id, pairs, notes)
        log("profile_curated", user_id=user_id, notes=len(notes), pairs=len(pairs))
        return {"notes": notes, "confusion_pairs": pairs}
    except Exception as exc:  # noqa: BLE001
        log("curate_profile_failed", user_id=user_id, error=str(exc))
        return {"notes": [], "confusion_pairs": []}
