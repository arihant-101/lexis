"""
Grading for practice items.

  score_item  — DETERMINISTIC correctness (no LLM). Right/wrong is never an LLM call.
  tag_errors  — only on wrong answers: one cheap LLM call returns error-taxonomy
                tags + a short explanation, with a dev-mode/key-less fallback.
"""

from typing import Optional

from content.taxonomy import ALL_TAGS
from llm.router import acomplete_json, Task
from observability.logger import log
from tools.config import OPENROUTER_API_KEY, _has_real_key


def score_item(item: dict, user_answer: list) -> bool:
    """`user_answer` is the list of selected option strings (one per blank, or the
    two chosen synonyms for SE). Comparison is case-insensitive and trimmed."""
    answer = [str(a).strip().lower() for a in (item.get("answer") or [])]
    ua = [str(a).strip().lower() for a in (user_answer or [])]

    if item.get("type") == "SE":
        # single blank, exactly two correct synonyms — order-independent
        return len(ua) == 2 and set(ua) == set(answer)

    # TC / RC: per-blank exact match, in order
    return len(ua) == len(answer) and all(a == b for a, b in zip(ua, answer))


ERROR_TAG_SYSTEM = f"""You are a GRE Verbal item analyst. A student answered a question incorrectly.
Identify WHY they likely erred, choosing one or more tags from this FIXED list:
{', '.join(ALL_TAGS)}.
Prefer the single most explanatory tag. Return JSON:
{{"error_tags": ["<tag from the list>", ...], "explanation": "<= 2 sentences, specific and encouraging"}}"""


async def tag_errors(item: dict, user_answer: list, session_id: Optional[str] = None) -> dict:
    """Return {error_tags, explanation} for a wrong answer. Falls back to the item's
    own explanation (and no tags) when no LLM key is configured."""
    if not _has_real_key(OPENROUTER_API_KEY):
        return {"error_tags": [], "explanation": item.get("explanation", "")}

    user = (
        f"Question (each '____' is a blank): {item.get('stem')}\n"
        f"Options per blank: {item.get('options')}\n"
        f"Correct answer: {item.get('answer')}\n"
        f"Student answer: {user_answer}\n"
        f"Reference explanation: {item.get('explanation', '')}"
    )
    try:
        data = await acomplete_json(Task.EVALUATE, ERROR_TAG_SYSTEM, user, session_id=session_id)
        tags = [t for t in (data.get("error_tags") or []) if t in ALL_TAGS]
        return {
            "error_tags": tags,
            "explanation": data.get("explanation") or item.get("explanation", ""),
        }
    except Exception as exc:  # noqa: BLE001
        log("tag_errors_failed", item_id=item.get("id"), error=str(exc))
        return {"error_tags": [], "explanation": item.get("explanation", "")}
