"""
quiz_evaluator node — evaluates a user's sentence using the target word.

Flow:
  1. Receive transcribed (or typed) user_text
  2. Call MCP evaluate_word_usage → structured is_correct + feedback
  3. Update mastery immediately
  4. Return agent_text with positive/corrective feedback
"""

import time
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState
from tools.lexical import evaluate_word_usage
from rag.retriever import get_word_from_corpus
from memory.longterm import update_mastery
from observability.logger import log


async def quiz_evaluator(state: AgentState) -> AgentState:
    word = state.get("current_word") or "abate"
    user_text = state.get("user_text", "")

    if user_text.strip().lower() in {"start", "next", ""}:
        word_data = get_word_from_corpus(word)
        definition = word_data.get("definition", "")
        return {
            **state,
            "current_word": word,
            "agent_text": f"Use **{word}** in a sentence.\n\nDefinition: {definition}",
        }

    if not user_text.strip():
        return {
            **state,
            "agent_text": f"I didn't catch that. Use **{word}** in a sentence — spoken or typed.",
        }

    # Evaluate via MCP tool (calls OpenRouter LLM with structured output)
    start = time.time()
    evaluation = evaluate_word_usage(word=word, user_sentence=user_text)
    latency_ms = int((time.time() - start) * 1000)

    log("quiz_eval", word=word, is_correct=evaluation["is_correct"], latency_ms=latency_ms)

    is_correct: bool = evaluation["is_correct"]
    feedback: str = evaluation.get("feedback", "")
    corrected: str = evaluation.get("corrected_sentence") or evaluation.get("corrected_example") or ""

    # Update mastery in PostgreSQL
    mastery_record = update_mastery(
        user_id=state["user_id"],
        word=word,
        is_correct=is_correct,
    )

    mastery_updates = [{
        "word": word,
        "level": mastery_record["new_level"],
        "next_review": mastery_record["next_review"],
    }]

    # Build response text
    if is_correct:
        agent_text = (
            f"✅ **Correct!** Great use of *{word}*.\n\n"
            f"{feedback}\n\n"
            f"Mastery: {'⭐' * mastery_record['new_level']} (level {mastery_record['new_level']}/4)"
        )
    else:
        agent_text = (
            f"❌ **Not quite.** {feedback}\n\n"
        )
        if corrected:
            agent_text += f"Improved version: *{corrected}*\n\n"
        agent_text += f"Mastery: {'⭐' * mastery_record['new_level']} (level {mastery_record['new_level']}/4)"

    new_messages = list(state.get("messages", [])) + [
        HumanMessage(content=user_text),
        AIMessage(content=agent_text),
    ]

    return {
        **state,
        "is_correct": is_correct,
        "feedback": feedback,
        "mastery_updates": mastery_updates,
        "agent_text": agent_text,
        "messages": new_messages,
    }
