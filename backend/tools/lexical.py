"""
Lexical + RAG tools: dictionary lookup, LLM usage evaluation, passage retrieval.

Moved out of the old `mcp/server.py`. These call external services directly (they
ARE the tool boundary), so they keep their own httpx calls rather than going
through llm.router.
"""

import json
import time
from typing import Literal, Optional

import httpx
from pydantic import BaseModel

from observability.logger import log, log_tool_call
from tools.config import OPENROUTER_API_KEY, _has_real_key
from tools.registry import register


# ── Schemas ──────────────────────────────────────────────────────────────────

class WordData(BaseModel):
    word: str
    definition: str
    part_of_speech: str
    example_sentences: list[str]
    synonyms: list[str]
    antonyms: list[str]
    etymology: Optional[str] = None


class UsageEvaluation(BaseModel):
    word: str
    user_sentence: str
    is_correct: bool
    score: float            # 0.0 – 1.0
    feedback: str
    corrected_example: Optional[str] = None


class Passage(BaseModel):
    passage_id: str
    text: str
    difficulty: str
    topic: str
    questions: list[dict]


# ── Tools ────────────────────────────────────────────────────────────────────

@register(description="Fetch definition, examples, synonyms for a GRE word.")
def get_word_data(word: str) -> dict:
    """
    Fetch definition, examples, synonyms, antonyms for a GRE word.
    Uses Free Dictionary API with local corpus fallback.
    """
    start = time.time()
    try:
        resp = httpx.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()[0]

        meanings = data.get("meanings", [])
        definition = ""
        pos = ""
        examples: list[str] = []
        synonyms: list[str] = []
        antonyms: list[str] = []

        for meaning in meanings:
            pos = meaning.get("partOfSpeech", pos)
            for defn in meaning.get("definitions", []):
                if not definition:
                    definition = defn.get("definition", "")
                if ex := defn.get("example"):
                    examples.append(ex)
            synonyms.extend(meaning.get("synonyms", []))
            antonyms.extend(meaning.get("antonyms", []))

        result = WordData(
            word=word,
            definition=definition,
            part_of_speech=pos,
            example_sentences=examples[:3],
            synonyms=synonyms[:5],
            antonyms=antonyms[:5],
            etymology=data.get("origin"),
        ).model_dump()

        log_tool_call("get_word_data", int((time.time() - start) * 1000), word=word, cache_hit=False)
        return result

    except httpx.HTTPStatusError:
        from rag.retriever import get_word_from_corpus
        log_tool_call("get_word_data", int((time.time() - start) * 1000),
                      word=word, fallback="corpus")
        return get_word_from_corpus(word)


@register(description="Evaluate whether a GRE word is used correctly in a sentence.")
def evaluate_word_usage(word: str, user_sentence: str) -> dict:
    """
    Evaluate whether the user correctly used a GRE word in a sentence.
    Uses LLM judgment with structured output, with a dev-mode fallback.
    """
    start = time.time()
    if not _has_real_key(OPENROUTER_API_KEY):
        log("evaluate_word_usage_skipped", reason="missing_api_key", word=word)
        normalized_word = word.lower()
        contains_word = normalized_word in user_sentence.lower()
        return UsageEvaluation(
            word=word,
            user_sentence=user_sentence,
            is_correct=contains_word,
            score=0.6 if contains_word else 0.0,
            feedback=(
                "Dev fallback: I can see the target word in your sentence, but add an "
                "OpenRouter key for real usage evaluation."
                if contains_word
                else "Dev fallback: try writing a complete sentence that includes the target "
                "word. Add an OpenRouter key for real scoring."
            ),
            corrected_example=None,
        ).model_dump()

    prompt = f"""You are a GRE verbal expert. Evaluate whether the word "{word}" is used correctly in the following sentence.

Sentence: "{user_sentence}"

Respond in JSON:
{{
  "is_correct": true/false,
  "score": 0.0-1.0,
  "feedback": "brief explanation",
  "corrected_example": "better sentence if incorrect, else null"
}}"""

    try:
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        result = json.loads(resp.json()["choices"][0]["message"]["content"])
        log_tool_call("evaluate_word_usage", int((time.time() - start) * 1000),
                      word=word, is_correct=result.get("is_correct"))
        return UsageEvaluation(word=word, user_sentence=user_sentence, **result).model_dump()
    except Exception as e:
        log_tool_call("evaluate_word_usage", int((time.time() - start) * 1000),
                      success=False, error=str(e), word=word)
        raise


@register(description="Retrieve a GRE reading passage from the RAG corpus.")
def get_reading_passage(
    difficulty: Literal["easy", "medium", "hard"] = "medium",
    topic: Optional[str] = None,
    exclude_ids: Optional[list[str]] = None,
) -> dict:
    """Retrieve a GRE reading comprehension passage from the RAG corpus."""
    from rag.retriever import retrieve_passage

    # The retriever takes an int difficulty; map the coarse label onto the 1-5 scale.
    difficulty_map = {"easy": 2, "medium": 3, "hard": 5}
    passage = retrieve_passage(
        difficulty=difficulty_map.get(difficulty, 3),
        topic=topic,
        exclude_ids=exclude_ids or [],
    )
    log_tool_call("get_reading_passage", 0, difficulty=difficulty, topic=topic,
                  passage_id=passage.get("passage_id"))
    return passage
