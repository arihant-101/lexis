"""
Structured observability for Lexis.

Every LLM call and tool call is logged as a JSON line with:
  - request_id, user_id, timestamp
  - event type (llm_call, tool_call, agent_run)
  - latency_ms, token counts, cost estimate
  - success/error

Output: stdout (pipe to any log aggregator) + optional file.
"""

import json
import time
import uuid
import logging
import os
from typing import Optional
from contextvars import ContextVar

# Per-request context
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")

LOG_FILE = os.environ.get("LOG_FILE")

# Token cost estimates (USD per 1k tokens) — update as pricing changes
COST_PER_1K = {
    "openai/gpt-4o-mini":    {"input": 0.000150, "output": 0.000600},
    "openai/gpt-4o":         {"input": 0.005000, "output": 0.015000},
    "anthropic/claude-haiku": {"input": 0.000250, "output": 0.001250},
}

_logger = logging.getLogger("lexis")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# In-process per-session cost accumulator. Good enough for single-worker dev;
# a multi-worker deployment should push these to Redis/StatsD instead.
_session_costs: dict[str, float] = {}


def add_session_cost(session_id: Optional[str], cost_usd: float):
    if not session_id:
        return
    _session_costs[session_id] = _session_costs.get(session_id, 0.0) + cost_usd


def get_session_cost(session_id: str) -> float:
    return round(_session_costs.get(session_id, 0.0), 6)


def reset_session_cost(session_id: str):
    _session_costs.pop(session_id, None)


def set_request_context(request_id: Optional[str] = None, user_id: Optional[str] = None):
    _request_id.set(request_id or str(uuid.uuid4()))
    _user_id.set(user_id or "")


def log(event: str, **kwargs):
    """Emit a structured log line."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_id": _request_id.get(),
        "user_id": _user_id.get(),
        "event": event,
        **kwargs
    }
    line = json.dumps(entry)
    _logger.info(line)
    if LOG_FILE:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")


def log_llm_call(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    success: bool = True,
    error: Optional[str] = None,
    session_id: Optional[str] = None,
):
    costs = COST_PER_1K.get(model, {"input": 0, "output": 0})
    cost_usd = (
        prompt_tokens / 1000 * costs["input"] +
        completion_tokens / 1000 * costs["output"]
    )
    add_session_cost(session_id, cost_usd)
    log(
        "llm_call",
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cost_usd=round(cost_usd, 6),
        latency_ms=latency_ms,
        success=success,
        error=error,
        session_id=session_id,
    )


def log_tool_call(
    tool: str,
    latency_ms: int,
    success: bool = True,
    error: Optional[str] = None,
    **kwargs,
):
    """Trace a tool invocation (Sarvam API, dictionary, RAG, etc.)."""
    log(
        "tool_call",
        tool=tool,
        latency_ms=latency_ms,
        success=success,
        error=error,
        **kwargs,
    )


def log_plan_decision(action: str, reason: str = "", **kwargs):
    """Trace an agent planning decision (which action the planner chose and why)."""
    log("plan_decision", action=action, reason=reason, **kwargs)


def log_agent_run(
    mode: str,
    word: Optional[str],
    total_latency_ms: int,
    nodes_executed: list[str],
    success: bool = True
):
    log(
        "agent_run",
        mode=mode,
        word=word,
        total_latency_ms=total_latency_ms,
        nodes_executed=nodes_executed,
        success=success
    )
