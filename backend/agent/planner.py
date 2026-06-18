"""
The Phase 2 planner — an in-session, reactive coaching agent.

Unlike a next-item chooser, this loop REACTS to the learner's last attempt: it
re-teaches and drops difficulty after a miss, or steps up after a win — choosing a
variable set of tools per turn. The branch genuinely depends on observed state, so
the bind_tools -> ToolNode cycle is load-bearing, not decorative.

Entry point: `await plan_next(user_id)`.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from llm.router import Task, get_llm
from memory.learner_model import get_weak_skills
from memory.longterm import get_item, get_recent_attempts, next_item_for
from observability.logger import log_plan_decision
from tools.config import OPENROUTER_API_KEY, _has_real_key
from tools.lexical import get_word_data

MAX_STEPS = 6
SERVE_FIELDS = ("id", "type", "stem", "options", "target_words", "difficulty")

PLANNER_SYSTEM = """You are Lexis, an adaptive GRE Verbal coach running a live practice session.

Tools:
- get_session_context(): the learner's ability per skill, weakest skill, recent error tags,
  AND their most recent attempt (type, correct?, error tags, the target word, difficulty).
- look_up_word(word): dictionary data — use ONLY to ground a re-teach when the miss is a
  vocabulary/connotation error.
- serve_item(item_type, min_difficulty, max_difficulty): fetch the next item of a type
  ("TC", "SE", or "RC") within a 1-5 difficulty window.

Every turn:
1) Call get_session_context FIRST.
2) Decide from the LAST attempt:
   - WRONG: address the specific error in 1-2 sentences (if it's a vocabulary/connotation
     error, call look_up_word on that word first so your re-teach is accurate), then serve a
     SIMILAR item of the SAME skill at the SAME or LOWER difficulty
     (set max_difficulty to the missed item's difficulty).
   - CORRECT: brief encouragement, then serve the next item stepping UP
     (set min_difficulty to the last difficulty) and favor the weakest skill.
   - NO last attempt: serve an item in the weakest skill at moderate difficulty.
3) After serving, STOP and reply with the short coaching message for the learner
   (your re-teach / encouragement + a nudge). Do NOT call more tools after serving.
Keep it warm and concise — the learner has ~15 minutes."""


def _safe(item: dict) -> dict:
    return {k: item[k] for k in SERVE_FIELDS}


def _last_attempt(user_id: str):
    recent = get_recent_attempts(user_id, 1)
    if not recent:
        return None
    a = recent[0]
    item = get_item(a["item_id"]) if a.get("item_id") else None
    return {
        "type": a["item_type"],
        "is_correct": a["is_correct"],
        "error_tags": a.get("error_tags") or [],
        "word": a.get("word"),
        "stem": (item or {}).get("stem", "")[:160],
        "difficulty": (item or {}).get("difficulty"),
    }


class PlannerState(TypedDict):
    messages: Annotated[list, add_messages]
    step: int


def _build_tools(user_id: str):
    captured = {"item": None, "calls": []}

    def get_session_context() -> dict:
        """Learner ability per skill, weakest skill, recent error tags, and their most recent attempt."""
        captured["calls"].append("get_session_context")
        ctx = get_weak_skills(user_id)
        ctx["last_attempt"] = _last_attempt(user_id)
        return ctx

    def look_up_word(word: str) -> dict:
        """Dictionary data (definition, synonyms, antonyms) for a word — to ground a re-teach."""
        captured["calls"].append(f"look_up_word:{word}")
        return get_word_data(word)

    def serve_item(item_type: Literal["TC", "SE", "RC"], min_difficulty: int = 1, max_difficulty: int = 5) -> dict:
        """Fetch the next unseen item of a type within a 1-5 difficulty window."""
        captured["calls"].append(f"serve_item:{item_type}[{min_difficulty}-{max_difficulty}]")
        item = next_item_for(user_id, item_type, min_difficulty, max_difficulty)
        if not item:
            return {"served": False, "reason": f"no remaining {item_type} items"}
        captured["item"] = _safe(item)
        return {"served": True, "item_id": item["id"], "type": item["type"], "difficulty": item["difficulty"]}

    tools = [
        StructuredTool.from_function(get_session_context, name="get_session_context"),
        StructuredTool.from_function(look_up_word, name="look_up_word"),
        StructuredTool.from_function(serve_item, name="serve_item"),
    ]
    return tools, captured


def _build_graph(tools):
    llm = get_llm(Task.PLAN).bind_tools(tools)

    async def plan_node(state: PlannerState):
        ai = await llm.ainvoke(state["messages"])
        return {"messages": [ai], "step": state.get("step", 0) + 1}

    def should_continue(state: PlannerState):
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) and state["step"] < MAX_STEPS else "end"

    g = StateGraph(PlannerState)
    g.add_node("plan", plan_node)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", should_continue, {"tools": "tools", "end": END})
    g.add_edge("tools", "plan")
    return g.compile()


async def plan_next(user_id: str) -> dict:
    """Run the reactive planner. Returns {coaching_message, item, action, focus_skill, trace}."""
    profile = get_weak_skills(user_id)
    weakest = profile.get("weakest_skill") or "TC"
    last = _last_attempt(user_id)
    action = "reteach" if (last and not last["is_correct"]) else ("advance" if last else "start")

    if not _has_real_key(OPENROUTER_API_KEY):
        cap = (last["difficulty"] or 3) if action == "reteach" and last else 5
        item = next_item_for(user_id, weakest, 1, cap)
        return {
            "coaching_message": f"Dev mode: focusing on your weakest skill ({weakest}).",
            "item": _safe(item) if item else None,
            "action": action, "focus_skill": weakest, "trace": ["fallback"],
        }

    tools, captured = _build_tools(user_id)
    graph = _build_graph(tools)
    result = await graph.ainvoke({
        "messages": [
            SystemMessage(content=PLANNER_SYSTEM),
            HumanMessage(content=f"Coach learner '{user_id}' on their next step. Start with get_session_context."),
        ],
        "step": 0,
    })

    final = result["messages"][-1]
    message = final.content if isinstance(final, AIMessage) and not getattr(final, "tool_calls", None) else ""

    if not captured["item"]:  # safety net: always leave the learner with an item
        cap = (last["difficulty"] or 5) if action == "reteach" and last else 5
        item = next_item_for(user_id, weakest, 1, cap)
        captured["item"] = _safe(item) if item else None

    log_plan_decision(action=action, reason=message[:200], focus_skill=weakest, trace=captured["calls"])
    return {
        "coaching_message": message,
        "item": captured["item"],
        "action": action,
        "focus_skill": weakest,
        "trace": captured["calls"],
    }
