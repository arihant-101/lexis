"""
Central LLM router for Lexis.

One place builds chat models, so every node uses the right model for the job and
emits consistent cost/latency telemetry. Replaces the duplicated `ChatOpenAI(...)`
construction that used to live in each agent node.

Routing principle:
  - cheap/fast model  → routing, evaluation, parsing, validation
  - stronger model    → planning, content generation, diagnosis synthesis
"""

import os
import json
import time
from enum import Enum
from typing import Optional, Type, TypeVar

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from observability.logger import log, log_llm_call

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

T = TypeVar("T", bound=BaseModel)


class Task(str, Enum):
    ROUTE = "route"
    EVALUATE = "evaluate"
    PARSE = "parse"
    VALIDATE = "validate"
    PLAN = "plan"
    GENERATE = "generate"
    DIAGNOSE = "diagnose"


MODEL_BY_TASK: dict[Task, str] = {
    Task.ROUTE: "openai/gpt-4o-mini",
    Task.EVALUATE: "openai/gpt-4o-mini",
    Task.PARSE: "openai/gpt-4o-mini",
    Task.VALIDATE: "openai/gpt-4o-mini",
    Task.PLAN: "openai/gpt-4o",
    Task.GENERATE: "openai/gpt-4o",
    Task.DIAGNOSE: "openai/gpt-4o",
}

DEFAULT_TEMPERATURE: dict[Task, float] = {
    Task.ROUTE: 0.0,
    Task.EVALUATE: 0.1,
    Task.PARSE: 0.0,
    Task.VALIDATE: 0.0,
    Task.PLAN: 0.3,
    Task.GENERATE: 0.6,
    Task.DIAGNOSE: 0.2,
}


def _api_key() -> str:
    # `local-dev-placeholder` keeps construction from crashing when no key is set;
    # nodes gate real calls behind tools.config._has_real_key().
    return OPENROUTER_API_KEY or os.environ.get("OPENAI_API_KEY") or "local-dev-placeholder"


def get_llm(
    task: Task,
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    **kwargs,
) -> ChatOpenAI:
    """Build a chat model configured for the given task."""
    return ChatOpenAI(
        model=model or MODEL_BY_TASK[task],
        base_url=OPENROUTER_BASE_URL,
        api_key=_api_key(),
        temperature=DEFAULT_TEMPERATURE[task] if temperature is None else temperature,
        **kwargs,
    )


async def acomplete_json(
    task: Task,
    system: str,
    user: str,
    schema: Optional[Type[T]] = None,
    *,
    session_id: Optional[str] = None,
    max_retries: int = 1,
):
    """
    Run a JSON-mode completion and parse the result.

    Returns a `schema` instance if provided, else a plain dict. Retries once on
    malformed JSON / schema-validation failure with a corrective nudge.
    """
    llm = get_llm(task, model_kwargs={"response_format": {"type": "json_object"}})
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    last_error: Optional[Exception] = None

    for _attempt in range(max_retries + 1):
        start = time.time()
        response = await llm.ainvoke(messages)
        latency_ms = int((time.time() - start) * 1000)
        usage = getattr(response, "response_metadata", {}).get("token_usage", {})
        log_llm_call(
            MODEL_BY_TASK[task],
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            latency_ms,
            session_id=session_id,
        )
        try:
            data = json.loads(response.content)
            return schema.model_validate(data) if schema is not None else data
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            messages.append(
                HumanMessage(
                    content="Your previous reply was not valid JSON matching the schema. "
                    "Return ONLY the JSON object, no prose."
                )
            )

    log("acomplete_json_failed", task=task.value, error=str(last_error))
    raise ValueError(f"acomplete_json failed after {max_retries} retries: {last_error}")
