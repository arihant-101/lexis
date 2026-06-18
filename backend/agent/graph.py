"""
Lexis — LangGraph agent graph.

Flow:
    START
      → [conditional entry: route_by_mode]   (mode comes from the session start request)
            "learn"        → vocab_teacher   → generate_audio  → update_mastery
            "learn_answer" → transcribe_audio → quiz_evaluator → generate_audio
            "quiz"         → transcribe_audio → quiz_evaluator → generate_audio
            "reading"      → reading_coach   → generate_audio
            "diagnostic"   → diagnostic      → generate_audio
      → END

NOTE: routing here is deterministic on the client-supplied mode. Phase 2 replaces
this with an LLM-driven planner loop (see TRANSFORMATION_PLAN.md).
"""

from langgraph.graph import StateGraph, END
from agent.state import AgentState
from agent.nodes.diagnostic import run_diagnostic
from agent.nodes.vocab_teacher import vocab_teacher
from agent.nodes.quiz_evaluator import quiz_evaluator
from agent.nodes.reading_coach import run_reading_coach
from agent.nodes.audio import generate_audio, transcribe_audio
from agent.nodes.mastery import update_mastery


def route_by_mode(state: AgentState) -> str:
    if (
        state["mode"] == "learn"
        and state.get("current_word")
        and (state.get("user_text") or state.get("user_audio_b64"))
    ):
        return "learn_answer"
    return state["mode"]


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    # ── Nodes ──────────────────────────────────────────────────────────────
    g.add_node("diagnostic",       run_diagnostic)
    g.add_node("vocab_teacher",    vocab_teacher)
    g.add_node("transcribe_audio", transcribe_audio)   # STT if user sent audio
    g.add_node("quiz_evaluator",   quiz_evaluator)
    g.add_node("reading_coach",    run_reading_coach)
    g.add_node("generate_audio",   generate_audio)     # TTS for agent response
    g.add_node("update_mastery",   update_mastery)

    # ── Conditional entry: route straight to the mode's node ────────────────
    g.set_conditional_entry_point(
        route_by_mode,
        {
            "diagnostic": "diagnostic",
            "learn":      "vocab_teacher",
            "learn_answer": "transcribe_audio",
            "quiz":       "transcribe_audio",   # always try STT first
            "reading":    "reading_coach",
        }
    )

    # ── Learn path ─────────────────────────────────────────────────────────
    g.add_edge("vocab_teacher",    "generate_audio")
    g.add_edge("generate_audio",   "update_mastery")
    g.add_edge("update_mastery",   END)

    # ── Quiz path ──────────────────────────────────────────────────────────
    g.add_edge("transcribe_audio", "quiz_evaluator")
    g.add_edge("quiz_evaluator",   "generate_audio")

    # ── Reading path ───────────────────────────────────────────────────────
    g.add_edge("reading_coach",    "generate_audio")

    # ── Diagnostic path ────────────────────────────────────────────────────
    g.add_edge("diagnostic",       "generate_audio")

    return g.compile()


# Singleton compiled graph
graph = build_graph()
