"""
reading_coach node — contextual vocabulary learning through GRE-style passages.

Flow:
  1. Retrieve a passage from ChromaDB matching user's current difficulty level
  2. Identify 3-5 target GRE words in the passage
  3. Ask comprehension + vocabulary question
  4. On user answer: evaluate and explain
"""

import json
import time
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState
from llm.router import get_llm, Task
from rag.retriever import retriever
from memory.longterm import get_study_stats
from tools.config import OPENROUTER_API_KEY, _has_real_key
from observability.logger import log, log_llm_call

_llm = get_llm(Task.GENERATE, temperature=0.3)

READING_SYSTEM = """You are a GRE reading comprehension coach.
Given a passage, do two things:
1. Identify the 3 most advanced vocabulary words (GRE-level) in it.
2. Ask ONE vocabulary-in-context question about the most important word.

Format:
{
  "passage_summary": "<1-sentence summary>",
  "target_words": ["word1", "word2", "word3"],
  "question": "<question about word usage in context>",
  "target_word": "<the word the question is about>"
}"""

EVAL_SYSTEM = """You are evaluating a GRE student's answer to a vocabulary-in-context question.
Return JSON: {"is_correct": bool, "explanation": "<2-3 sentences explaining the correct answer>"}"""


async def run_reading_coach(state: AgentState) -> AgentState:
    user_id = state["user_id"]
    messages = state.get("messages", [])
    user_text = state.get("user_text", "")
    current_question = state.get("current_question")
    current_passage = state.get("current_passage")

    # ── Turn 1: present passage ────────────────────────────────────────────
    if not current_passage or not current_question:
        # Get user difficulty from stats
        stats = get_study_stats(user_id)
        mastered = stats.get("mastered", 0)
        total = max(stats.get("total_words_seen", 1), 1)
        mastery_ratio = mastered / total
        difficulty = 1 + int(mastery_ratio * 4)  # 1-5

        # Retrieve passage from ChromaDB
        seen_ids = state.get("_seen_passage_ids", [])
        results = retriever.gre_passages.query(
            query_texts=["GRE reading comprehension vocabulary"],
            n_results=3,
            where={"difficulty": {"$lte": difficulty}},
        )

        passage = None
        passage_id = None
        for i, doc in enumerate(results["documents"][0]):
            pid = results["ids"][0][i]
            if pid not in seen_ids:
                passage = doc
                passage_id = pid
                break

        if not passage:
            return {
                **state,
                "agent_text": "I've run out of new passages at your level. Try the quiz mode to reinforce what you've learned!",
            }

        if _has_real_key(OPENROUTER_API_KEY):
            # LLM: identify vocab + form question
            start = time.time()
            response = await _llm.ainvoke([
                HumanMessage(content=f"{READING_SYSTEM}\n\nPassage:\n{passage}")
            ])
            latency_ms = int((time.time() - start) * 1000)
            usage = getattr(response, "response_metadata", {}).get("token_usage", {})
            log_llm_call("openai/gpt-4o-mini", usage.get("prompt_tokens", 0),
                         usage.get("completion_tokens", 0), latency_ms)

            try:
                data = json.loads(response.content)
            except Exception:
                data = {"passage_summary": "", "target_words": [], "question": response.content, "target_word": ""}
        else:
            data = {
                "passage_summary": "",
                "target_words": [],
                "question": "Dev mode: add an OpenRouter key to generate reading questions.",
                "target_word": "",
            }

        agent_text = (
            f"📄 **Reading passage:**\n\n{passage}\n\n"
            f"---\n"
            f"🔑 Key words to notice: {', '.join(data.get('target_words', []))}\n\n"
            f"**Question:** {data['question']}"
        )

        return {
            **state,
            "current_passage": passage,
            "current_question": data["question"],
            "current_word": data.get("target_word"),
            "_seen_passage_ids": seen_ids + [passage_id],
            "agent_text": agent_text,
            "messages": messages + [
                HumanMessage(content="[reading_start]"),
                AIMessage(content=agent_text),
            ],
        }

    # ── Turn 2: evaluate answer ────────────────────────────────────────────
    if user_text:
        if not _has_real_key(OPENROUTER_API_KEY):
            agent_text = "Dev mode: I received your answer. Add an OpenRouter key for real reading-comprehension evaluation."
            return {
                **state,
                "is_correct": None,
                "feedback": agent_text,
                "agent_text": agent_text,
                "current_passage": None,
                "current_question": None,
                "messages": messages + [
                    HumanMessage(content=user_text),
                    AIMessage(content=agent_text),
                ],
            }

        start = time.time()
        eval_prompt = (
            f"{EVAL_SYSTEM}\n\n"
            f"Passage: {current_passage[:300]}...\n"
            f"Question: {current_question}\n"
            f"Student answer: {user_text}"
        )
        response = await _llm.ainvoke([HumanMessage(content=eval_prompt)])
        latency_ms = int((time.time() - start) * 1000)
        usage = getattr(response, "response_metadata", {}).get("token_usage", {})
        log_llm_call("openai/gpt-4o-mini", usage.get("prompt_tokens", 0),
                     usage.get("completion_tokens", 0), latency_ms)

        try:
            result = json.loads(response.content)
        except Exception:
            result = {"is_correct": False, "explanation": response.content}

        icon = "✅" if result["is_correct"] else "❌"
        agent_text = (
            f"{icon} {result['explanation']}\n\n"
            "Ready for another passage? Just say 'next'."
        )

        return {
            **state,
            "is_correct": result["is_correct"],
            "feedback": result["explanation"],
            "agent_text": agent_text,
            "current_passage": None,   # clear for next passage
            "current_question": None,
            "messages": messages + [
                HumanMessage(content=user_text),
                AIMessage(content=agent_text),
            ],
        }

    return state
