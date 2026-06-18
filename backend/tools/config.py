"""Shared tool configuration: API keys and the dev-mode key check.

Centralized here so every tool and node imports the same source of truth instead
of pulling keys off the old `mcp.server` module.
"""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

_PLACEHOLDERS = {"placeholder", "your_sarvam_api_key", "your_openrouter_key"}


def _has_real_key(value: Optional[str]) -> bool:
    """True only when `value` looks like a real key (not empty / placeholder)."""
    return bool(value and value.strip() and value.strip().lower() not in _PLACEHOLDERS)
