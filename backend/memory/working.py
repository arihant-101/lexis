"""
Working memory: Redis-backed session state.

Stores:
  - Current session progress (words seen, score)
  - Study streak
  - Rate limiting state for Sarvam API calls
  - Word definition cache (avoid redundant API calls)
"""

import redis
import json
import time
import os
from typing import Optional

from langchain_core.messages import BaseMessage, messages_to_dict, messages_from_dict

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
CACHE_TTL = 86400           # 24h for word definitions
SESSION_TTL = 3600          # 1h for session state
RATE_LIMIT_WINDOW = 60      # 1 minute window
RATE_LIMIT_MAX = 30         # max 30 Sarvam API calls per minute

_redis: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


# ── Session state ──────────────────────────────────────────────────────────

def get_session(session_id: str) -> dict:
    r = get_redis()
    data = r.get(f"session:{session_id}")
    return json.loads(data) if data else {}


def set_session(session_id: str, state: dict):
    r = get_redis()
    r.setex(f"session:{session_id}", SESSION_TTL, json.dumps(state))


def update_session(session_id: str, updates: dict):
    current = get_session(session_id)
    current.update(updates)
    set_session(session_id, current)


def init_session(session_id: str, user_id: str, mode: str) -> dict:
    state = {
        "session_id": session_id,
        "user_id": user_id,
        "mode": mode,
        "words_seen": [],
        "correct_count": 0,
        "total_count": 0,
        "started_at": time.time()
    }
    set_session(session_id, state)
    return state


# ── Conversation history ───────────────────────────────────────────────────
# Stored separately from the session blob because LangChain messages need
# structured (de)serialization. Fixes the v1 bug where history was dropped each
# turn, which broke the multi-turn diagnostic and reading flows.

def get_messages(session_id: str) -> list:
    r = get_redis()
    data = r.get(f"messages:{session_id}")
    return messages_from_dict(json.loads(data)) if data else []


def set_messages(session_id: str, messages: list[BaseMessage]):
    r = get_redis()
    r.setex(f"messages:{session_id}", SESSION_TTL, json.dumps(messages_to_dict(messages)))


# ── Session plan (used by the Phase 2 planner) ─────────────────────────────

def get_plan(session_id: str) -> dict:
    r = get_redis()
    data = r.get(f"plan:{session_id}")
    return json.loads(data) if data else {}


def set_plan(session_id: str, plan: dict):
    r = get_redis()
    r.setex(f"plan:{session_id}", SESSION_TTL, json.dumps(plan))


# ── Word definition cache ──────────────────────────────────────────────────

def cache_word(word: str, data: dict):
    r = get_redis()
    r.setex(f"word_cache:{word.lower()}", CACHE_TTL, json.dumps(data))


def get_cached_word(word: str) -> Optional[dict]:
    r = get_redis()
    data = r.get(f"word_cache:{word.lower()}")
    return json.loads(data) if data else None


# ── Study streak ───────────────────────────────────────────────────────────

def get_streak(user_id: str) -> int:
    r = get_redis()
    return int(r.get(f"streak:{user_id}") or 0)


def update_streak(user_id: str):
    """Call once per day when user completes a study session."""
    r = get_redis()
    key = f"streak:{user_id}"
    last_key = f"streak_last:{user_id}"

    today = time.strftime("%Y-%m-%d")
    last_day = r.get(last_key)

    if last_day == today:
        return  # already updated today

    yesterday = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    if last_day == yesterday:
        r.incr(key)
    else:
        r.set(key, 1)   # streak broken, reset

    r.set(last_key, today)
    r.expire(key, 86400 * 30)
    r.expire(last_key, 86400 * 30)


# ── Sarvam API rate limiting ───────────────────────────────────────────────

def check_rate_limit(user_id: str, api: str = "sarvam") -> bool:
    """Returns True if request is allowed, False if rate limited."""
    r = get_redis()
    key = f"rate:{api}:{user_id}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, RATE_LIMIT_WINDOW)
    return count <= RATE_LIMIT_MAX
