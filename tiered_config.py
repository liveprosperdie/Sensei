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


# ── Command Fan-Out & Chain Decomposition Thresholds ──────────────────────────
# Sanity ceiling: if decomposition produces >= this many steps, escalate regardless
# of independence (likely misheard or malformed utterance).
DEFAULT_CHAIN_SANITY_CEILING: int = 6


def get_chain_sanity_ceiling() -> int:
    try:
        val = os.environ.get("AKIRA_CHAIN_SANITY_CEILING") or os.environ.get("AKIRA_FAN_OUT_THRESHOLD")
        if val:
            parsed = int(val)
            return max(parsed, 6) if "CHAIN" in (os.environ.get("AKIRA_CHAIN_SANITY_CEILING") or "") else parsed
        return DEFAULT_CHAIN_SANITY_CEILING
    except (ValueError, TypeError):
        return DEFAULT_CHAIN_SANITY_CEILING


# Backward reference signals: pronouns and deictic terms referring to prior step results
BACKWARD_REFERENCE_PATTERNS: tuple[str, ...] = (
    r"\bit\b",
    r"\bthat\b",
    r"\bthis\b",
    r"\bthere\b",
    r"\bthe one\b",
    r"\bits\b",
    r"\bthem\b",
    r"\bthose\b",
    r"\bthe same\b",
    r"\bthe result\b",
    r"\bwhich it\b",
    r"\bwhat it\b",
)


def has_backward_reference(step_text: str) -> bool:
    """Check if a sub-task text contains pronouns or terms referencing earlier steps."""
    t = (step_text or "").lower().strip()
    for pattern in BACKWARD_REFERENCE_PATTERNS:
        if re.search(pattern, t):
            return True
    return False


# Legacy threshold accessor for compatibility
def get_fan_out_threshold() -> int:
    return get_chain_sanity_ceiling()


# ── Known-Ambiguous-Pattern Registry ──────────────────────────────────────────
# Plain, easily-editable list of tagged patterns that should always escalate
# to Claude regardless of classifier confidence or single-step structure.
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AmbiguousPattern:
    tag: str
    intent_regex: str | None = None
    text_regex: str | None = None
    reason: str = ""


KNOWN_AMBIGUOUS_PATTERNS: list[AmbiguousPattern] = [
    AmbiguousPattern(
        tag="netflix_title_request",
        intent_regex=r"^netflix_",
        text_regex=r"\bnetflix\b",
        reason="Netflix title requests are prone to fuzzy media matching and UI catalog ambiguity",
    ),
    AmbiguousPattern(
        tag="ambiguous_tab_reference",
        intent_regex=r"^(switch_tab|close_tab)$",
        text_regex=r"\b(that tab|the other tab|previous tab|last tab)\b",
        reason="Relative or vague tab reference requires session history disambiguation",
    ),
    AmbiguousPattern(
        tag="vague_media_query",
        intent_regex=r"^(spotify|youtube)_",
        text_regex=r"\b(play something|play that|put on that|play some music|play that song)\b",
        reason="Vague media playback query requires taste/history synthesis",
    ),
    AmbiguousPattern(
        tag="vague_note_target",
        intent_regex=r"^(obsidian|docs)_",
        text_regex=r"\b(add to (my )?notes|update the document|put this in the log)\b",
        reason="Target note or document is underspecified and requires multi-candidate resolution",
    ),
    AmbiguousPattern(
        tag="vague_deletion",
        intent_regex=r"delete",
        text_regex=r"\b(delete that|remove that|clean up|clear everything)\b",
        reason="Destructive deletion with vague target requires deliberate clarification",
    ),
]


def check_ambiguous_pattern(intent: str, text: str) -> AmbiguousPattern | None:
    """Check if intent or text matches any known ambiguous pattern in the registry."""
    cleaned_text = (text or "").strip()
    cleaned_intent = (intent or "").strip()
    for pat in KNOWN_AMBIGUOUS_PATTERNS:
        if pat.intent_regex and cleaned_intent and re.search(pat.intent_regex, cleaned_intent, re.IGNORECASE):
            return pat
        if pat.text_regex and cleaned_text and re.search(pat.text_regex, cleaned_text, re.IGNORECASE):
            return pat
    return None


# ── Speech Head Provider & Model Config ───────────────────────────────────────
DEFAULT_SPEECH_HEAD_PROVIDER: str = "groq"
DEFAULT_SPEECH_HEAD_MODEL: str = "openai/gpt-oss-120b"


def get_speech_head_provider() -> str:
    """Return the configured speech head provider (default: groq)."""
    return os.environ.get("AKIRA_SPEECH_HEAD_PROVIDER", DEFAULT_SPEECH_HEAD_PROVIDER).strip().lower()


def get_speech_head_model() -> str:
    """Return the configured speech head model (default: openai/gpt-oss-120b)."""
    return os.environ.get("AKIRA_SPEECH_HEAD_MODEL", DEFAULT_SPEECH_HEAD_MODEL).strip()

