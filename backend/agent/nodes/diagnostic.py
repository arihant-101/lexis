"""
diagnostic node — runs on first session to estimate the user's vocabulary level.

Selects 10 words across difficulty 1-5 (2 per tier) and asks the user to
self-report familiarity (0 = never seen, 1 = seen, 2 = know it).
Sets initial mastery levels in PostgreSQL so the spaced repetition system
starts from a realistic baseline rather than treating everyone as a beginner.
"""

import json
import time
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState
from llm.router import get_llm, Task
from memory.longterm import bulk_set_mastery
from rag.retriever import retriever
from tools.config import OPENROUTER_API_KEY, _has_real_key
from observability.logger import log, log_llm_call

_llm = get_llm(Task.DIAGNOSE)

DIAGNOSTIC_SYSTEM = """You are administering a GRE vocabulary diagnostic.
Given a list of 10 words, ask the user to rate each one:
  0 = Never seen it
  1 = I've seen it but don't know the meaning
  2 = I know this word well

Format your message as a numbered list. Keep it friendly and brief.
After they respond, parse their ratings and return JSON:
{"ratings": {"word1": 0, "word2": 2, ...}}"""


async def run_diagnostic(state: AgentState) -> AgentState:
    user_id = state["user_id"]

    # Check if this is the first turn (no previous messages) or a response turn
    messages = state.get("messages", [])
    user_text = state.get("user_text", "")

    # First turn: present the diagnostic words
    if not messages:
        # Sample 2 words per difficulty tier from ChromaDB
        sample_words = []
        for difficulty in range(1, 6):
            results = retriever.gre_words.query(
                query_texts=["vocabulary"],
                n_results=2,
                where={"difficulty": difficulty},
            )
            for doc in results["documents"][0]:
                word = doc.split(":")[0].strip()
                sample_words.append(word)

        word_list = "\n".join(f"{i+1}. {w}" for i, w in enumerate(sample_words))
        if _has_real_key(OPENROUTER_API_KEY):
            start = time.time()
            response = await _llm.ainvoke([
                HumanMessage(content=f"{DIAGNOSTIC_SYSTEM}\n\nWords:\n{word_list}")
            ])
            latency_ms = int((time.time() - start) * 1000)

            usage = getattr(response, "response_metadata", {}).get("token_usage", {})
            log_llm_call("openai/gpt-4o-mini", usage.get("prompt_tokens", 0),
                         usage.get("completion_tokens", 0), latency_ms)
            agent_text = response.content
        else:
            agent_text = (
                "Dev mode diagnostic: rate these words from 0-2 when you add an OpenRouter key for full parsing.\n\n"
                f"{word_list}"
            )

        new_messages = [
            HumanMessage(content="[diagnostic_start]"),
            AIMessage(content=agent_text),
        ]
        # Store word list in message metadata for the second turn
        new_messages[0].additional_kwargs["diagnostic_words"] = sample_words

        return {
            **state,
            "agent_text": agent_text,
            "messages": new_messages,
            "mode": "diagnostic",
        }

    # Second turn: parse ratings and set initial mastery
    if user_text:
        # Get the original words from first message
        diagnostic_words = messages[0].additional_kwargs.get("diagnostic_words", [])

        parse_prompt = (
            f"Words presented: {diagnostic_words}\n"
            f"User response: {user_text}\n\n"
            "Return JSON: {\"ratings\": {\"word\": level}} where level is 0, 1, or 2. "
            "Infer from natural language if needed."
        )
        if _has_real_key(OPENROUTER_API_KEY):
            response = await _llm.ainvoke([HumanMessage(content=parse_prompt)])
            try:
                ratings = json.loads(response.content)["ratings"]
            except Exception:
                ratings = {w: 0 for w in diagnostic_words}
        else:
            ratings = {w: 0 for w in diagnostic_words}

        # Map self-reported familiarity to mastery levels
        # 0 → mastery 0, 1 → mastery 1, 2 → mastery 2
        mastery_map = {word: int(level) for word, level in ratings.items()}
        bulk_set_mastery(user_id, mastery_map)
        log("diagnostic_complete", user_id=user_id, levels=mastery_map)

        agent_text = (
            "✅ Diagnostic complete! I've calibrated your starting levels.\n\n"
            f"Based on your answers:\n"
            + "\n".join(f"  • {w}: level {l}/4" for w, l in mastery_map.items())
            + "\n\nYour first study session is ready. Ready to start?"
        )
        return {
            **state,
            "agent_text": agent_text,
            "mode": "learn",
            "messages": messages + [
                HumanMessage(content=user_text),
                AIMessage(content=agent_text),
            ],
        }

    return state
