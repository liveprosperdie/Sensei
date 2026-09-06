"""gateway_server/config.py — Gateway Server Configuration and Environment Settings."""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

AKIRA_ENV = (os.environ.get("AKIRA_ENV") or "dev").strip().lower()

# JWT Secret: must be set on server and at least 32 characters long
AKIRA_JWT_SECRET = os.environ.get("AKIRA_JWT_SECRET", "")

# Default Redis connection URL
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

# Authoritative Daily Caps
# Free tier has NO server involvement (0 turns on server, unlimited local).
# Standard & Pro tiers are server-gated.
TIER_CAPS = {
    "standard": 30,         # 30 turns/day Claude
    "pro": 53,              # 53 turns/day Claude (priority)
    "fallback_groq": 250,   # ceiling for Groq free fallback when cap reached or during outage
}

RESET_TIME_UTC = "00:00 UTC"

# Upstream API Keys (held exclusively server-side in production)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-3-7-sonnet-20250219")

# Rate Limiting (calls, window_seconds)
RATE_LIMIT_AUTH = (10, 60)    # 10 calls / min per IP
RATE_LIMIT_ROUTE = (60, 60)   # 60 calls / min per user/IP


def validate_config() -> None:
    """Validate critical server settings on startup. Refuse to start if secret is weak."""
    if not AKIRA_JWT_SECRET or len(AKIRA_JWT_SECRET.strip()) < 32:
        raise RuntimeError(
            "AKIRA_JWT_SECRET environment variable is missing or shorter than 32 characters. "
            "The server refuses to start with an insecure signing key. "
            "Please configure AKIRA_JWT_SECRET in server environment."
        )
