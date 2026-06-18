"""
Standalone MCP server entrypoint.

    python -m tools.mcp_app

Exposes every registered Lexis tool over MCP stdio. With the old `backend/mcp/`
package removed, `mcp.server.fastmcp` now resolves to the real PyPI `mcp` library
instead of being shadowed by a local module.
"""

import os

from tools.registry import as_mcp_server

if __name__ == "__main__":
    # Fail fast if keys are missing when running the real server.
    os.environ.setdefault("SARVAM_API_KEY", os.environ.get("SARVAM_API_KEY", ""))
    os.environ.setdefault("OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY", ""))
    as_mcp_server().run(transport="stdio")
