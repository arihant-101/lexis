"""
update_mastery node — persists mastery changes to PostgreSQL after a learn turn.

In learn mode we give partial credit: seeing a word (without being quizzed)
advances mastery by 0 (no change). Mastery only moves on quiz evaluation.
This node records that the word was *seen* today (for streak tracking) and
updates Redis session state.
"""

from agent.state import AgentState
from memory.longterm import record_word_seen
from memory.working import update_streak
from observability.logger import log


def update_mastery(state: AgentState) -> AgentState:
    """
    Called at end of learn path.
    - Records that user_id saw current_word today (no mastery change)
    - Updates daily streak in Redis
    """
    user_id = state["user_id"]
    word = state.get("current_word")

    if word:
        record_word_seen(user_id, word)
        log("word_seen", user_id=user_id, word=word)

    streak = update_streak(user_id)
    log("streak_updated", user_id=user_id, streak=streak)

    return {
        **state,
        "mastery_updates": state.get("mastery_updates", []),
    }
