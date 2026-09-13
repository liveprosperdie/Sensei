"""tiered_config.py — Configuration and complexity signals for Akira's tiered routing layer.

Easily editable, named constants for complexity classification, allowlists, and thresholds.
"""

from __future__ import annotations

import os

# ── Claude API Kill Switch ───────────────────────────────────────────────────
CLAUDE_DISABLED_MESSAGE: str = (
    "This needs Claude, which is temporarily turned off. "
    "Try again in a bit or ask me something simpler."
)


def is_claude_disabled() -> bool:
    """Return True if Claude API calls are disabled for cost control (default: True)."""
    val = os.environ.get("AKIRA_DISABLE_CLAUDE", "true").strip().lower()
    return val not in ("0", "false", "no", "off")


# ── Confidence Gate ──────────────────────────────────────────────────────────
# Any match below this confidence threshold is treated as escalate: True -> Claude
DEFAULT_MIN_CONFIDENCE: float = 0.85


def get_min_confidence() -> float:
    try:
        return float(os.environ.get("AKIRA_CLASSIFIER_MIN_CONFIDENCE", str(DEFAULT_MIN_CONFIDENCE)))
    except (ValueError, TypeError):
        return DEFAULT_MIN_CONFIDENCE


# ── Allowed Command Intents for Local Adapter ────────────────────────────────
ADAPTER_ALLOWED_INTENTS = frozenset({
    # Volume / mute (adjust_volume handles both scalar volume and mute/unmute)
    "adjust_volume",

    # Spotify-specific (routed to executor.spotify_control)
    "spotify_play",
    "spotify_pause",
    "spotify_next",
    "spotify_previous",
    "spotify_search_and_play",

    # YouTube-specific (routine single-video actions via executor.youtube_control)
    "youtube_play",
    "youtube_pause",
    "youtube_seek",
    "youtube_like",
    "youtube_subscribe",
    "youtube_volume",

    # App / window management
    "open_application",
    "close_window",
    "minimize_window",
    "maximize_window",
    "switch_application",

    # Browser tabs
    "list_tabs",
    "switch_tab",
    "close_tab",
    "open_new_tab",

    # Clipboard
    "read_clipboard",
    "write_clipboard",

    # Calendar — READ only (calendar_control list|...; create/delete escalate to Claude)
    "calendar_lookup",

    # Search
    "web_search_simple",

    # Simple info/status reads
    "get_current_time",
})


# ── Document Generation Complexity Signals ───────────────────────────────────
# Threshold: documents requesting more than ~1 page (450 words) are complex
DOC_MAX_SIMPLE_WORDS: int = 450

DOC_COMPLEXITY_KEYWORDS = (
    "compare",
    "comparison",
    "analyze",
    "analysis",
    "evaluate",
    "evaluation",
    "explain how",
    "technical breakdown",
    "architecture",
    "architectural",
    "in-depth",
    "comprehensive",
    "exhaustive",
    "detailed",
    "full report",
    "multi-page",
    "several pages",
    "extensive",
    "thorough",
    "deep dive",
)


# ── Conversation Complexity Signals ──────────────────────────────────────────
CONVERSATION_COMPLEXITY_KEYWORDS = (
    "pros and cons",
    "tradeoffs",
    "trade-offs",
    "analyze",
    "analysis",
    "compare",
    "comparison",
    "difference between",
    "explain the difference",
    "explain why",
    "how does",
    "why did",
    "how come",
    "synthesize",
    "weigh the options",
    "what happened earlier",
    "as we discussed",
    "earlier you said",
    "multi-part",
    "compare and contrast",
    "in detail",
    "step by step",
    "elaborate on",
    "technical breakdown",
)

CONVERSATION_MULTI_PART_SIGNALS = (
    " and also ",
    " furthermore ",
    " additionally ",
    " on top of that ",
    " secondly ",
)
