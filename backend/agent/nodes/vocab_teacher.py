"""
vocab_teacher node — teaches a single GRE word.

Picks the next word due for review (spaced repetition), fetches its data via
the MCP tool, then asks the LLM to produce a structured teaching turn:
  - definition in plain English
  - memorable mnemonic
  - two example sentences (one formal, one conversational)
  - Hindi translation of the definition
"""

import json
import os
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState
from llm.router import acomplete_json, Task
from memory.longterm import get_all_mastery, get_words_due_today
from memory.working import get_cached_word, cache_word
from tools.config import OPENROUTER_API_KEY, _has_real_key
from tools.lexical import get_word_data
from tools.speech import translate_to_hindi
from observability.logger import log

TEACH_SYSTEM = """You are Lexis, an expert GRE vocabulary tutor.
When given a word and its dictionary data, produce a teaching turn in this exact JSON:
{
  "definition": "<plain-English definition, ≤2 sentences>",
  "mnemonic": "<memorable tip to remember the word>",
  "examples": ["<formal sentence>", "<conversational sentence>"],
  "usage_tip": "<one sentence on when/how to use it in GRE writing>"
}
Be concise. The student is short on time. Avoid filler."""


def _seed_words() -> list[str]:
    data_path = os.path.join(os.path.dirname(__file__), "..", "..", "rag", "data", "gre_words.json")
    try:
        with open(os.path.abspath(data_path)) as f:
            words = json.load(f)
        return [w["word"] for w in words if w.get("word")]
    except Exception as exc:
        log("seed_word_load_error", error=str(exc))
        return []


def _next_seed_word(user_id: str, current_word: str | None = None) -> str | None:
    words = _seed_words()
    if not words:
        return None

    mastery = get_all_mastery(user_id)
    for word in words:
        if word != current_word and word not in mastery:
            return word

    if current_word in words:
        return words[(words.index(current_word) + 1) % len(words)]
    return words[0]


def _fallback_teaching_content(word: str, word_data: dict) -> dict:
    examples = word_data.get("example_sentences") or word_data.get("examples") or []
    synonyms = word_data.get("synonyms") or []
    return {
        "definition": word_data.get("definition") or "Definition not found in the local corpus.",
        "mnemonic": (
            f"Connect {word} with similar words like {', '.join(synonyms[:2])}."
            if synonyms
            else f"Say {word} aloud and pair it with one concrete example."
        ),
        "examples": examples[:2],
        "usage_tip": "Dev mode: add an OpenRouter key for a richer generated explanation.",
    }


async def vocab_teacher(state: AgentState) -> AgentState:
    user_id = state["user_id"]

    # Pick the next word: prefer due words, else any learning word
    due = get_words_due_today(user_id)
    user_text = (state.get("user_text") or "").strip().lower()
    wants_new_word = user_text in {"next", "next word", "another", "another word", "new word"}
    current_word = state.get("current_word")
    word = due[0] if due else (_next_seed_word(user_id, current_word) if wants_new_word else current_word or _next_seed_word(user_id))

    if not word:
        return {
            **state,
            "agent_text": "You're all caught up! No words due today. Come back tomorrow.",
            "current_word": None,
        }

    # Fetch word data (cached in Redis)
    cached = get_cached_word(word)
    if cached:
        word_data = cached
        log("word_cache_hit", word=word)
    else:
        word_data = get_word_data(word)
        cache_word(word, word_data)
        log("word_cache_miss", word=word)

    if _has_real_key(OPENROUTER_API_KEY):
        # JSON-mode completion: avoids markdown ```json fences (which broke the old
        # json.loads path) and retries once on malformed output before we fall back.
        try:
            content = await acomplete_json(
                Task.GENERATE,
                system=TEACH_SYSTEM,
                user=f"Word: {word}\nData: {json.dumps(word_data)}",
                session_id=state.get("session_id"),
            )
        except Exception as exc:
            log("vocab_teacher_llm_error", word=word, error=str(exc))
            content = _fallback_teaching_content(word, word_data)
    else:
        content = _fallback_teaching_content(word, word_data)

    # Normalize so missing keys never crash the formatting below.
    content = {
        "definition": content.get("definition") or word_data.get("definition", ""),
        "mnemonic": content.get("mnemonic", ""),
        "examples": content.get("examples") or [],
        "usage_tip": content.get("usage_tip", ""),
    }

    # Hindi translation of definition
    hindi = translate_to_hindi(content["definition"])

    # Build human-readable agent text
    agent_text = (
        f"**{word.upper()}**\n\n"
        f"📖 {content['definition']}\n\n"
        f"🧠 Mnemonic: {content['mnemonic']}\n\n"
        f"Examples:\n"
        + "\n".join(f"  • {ex}" for ex in content.get("examples", []))
        + f"\n\n✏️ GRE tip: {content.get('usage_tip', '')}"
        + (f"\n\n🇮🇳 {hindi}" if hindi else "")
    )

    new_messages = list(state.get("messages", [])) + [
        HumanMessage(content=f"[teach] {word}"),
        AIMessage(content=agent_text),
    ]

    return {
        **state,
        "current_word": word,
        "agent_text": agent_text,
        "hindi_translation": hindi,
        "messages": new_messages,
    }
