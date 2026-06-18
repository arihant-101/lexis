"""
Tool registry — single source of truth for Lexis tools.

Each tool is defined once (in tools/speech.py, tools/lexical.py, ...) and decorated
with `@register`. The registry can then export the same set as:
  - LangChain StructuredTools (bound to the planner LLM so it *selects* them), and
  - an MCP server (for external reuse / inspection).

This replaces the v1 pattern where nodes imported tool functions directly and the
MCP server was a separate, unused copy.
"""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ToolSpec:
    name: str
    fn: Callable
    description: str
    args_schema: Optional[type] = None


REGISTRY: dict[str, ToolSpec] = {}


def register(name: Optional[str] = None, description: Optional[str] = None, args_schema: Optional[type] = None):
    """Decorator: register a function as a Lexis tool."""
    def decorator(fn: Callable) -> Callable:
        spec = ToolSpec(
            name=name or fn.__name__,
            fn=fn,
            description=(description or (fn.__doc__ or "")).strip(),
            args_schema=args_schema,
        )
        REGISTRY[spec.name] = spec
        return fn
    return decorator


def _ensure_loaded() -> None:
    """Import tool modules so their @register decorators populate the registry."""
    import tools.speech  # noqa: F401
    import tools.lexical  # noqa: F401


def as_langchain_tools(names: Optional[list[str]] = None) -> list:
    """Export registered tools as LangChain StructuredTools (for agent binding)."""
    from langchain_core.tools import StructuredTool

    _ensure_loaded()
    specs = [REGISTRY[n] for n in names] if names else list(REGISTRY.values())
    tools = []
    for spec in specs:
        kwargs = dict(func=spec.fn, name=spec.name, description=spec.description)
        if spec.args_schema is not None:
            kwargs["args_schema"] = spec.args_schema
        tools.append(StructuredTool.from_function(**kwargs))
    return tools


def as_mcp_server(name: str = "lexis"):
    """Export registered tools as a FastMCP server."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:  # mcp < 1.2 has no FastMCP
        raise RuntimeError(
            "FastMCP is unavailable — install mcp>=1.2.0 (see requirements.txt). "
            "The agent does not need this; it consumes tools via as_langchain_tools()."
        ) from exc

    _ensure_loaded()
    server = FastMCP(name)
    for spec in REGISTRY.values():
        server.tool(name=spec.name, description=spec.description)(spec.fn)
    return server
