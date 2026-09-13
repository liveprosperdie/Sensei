"""local_adapter.py — Widened local adapter (SERVANT_MECH) and author-agnostic document sink.

Enforces ADAPTER_ALLOWED_INTENTS for command synthesis and packages pre-written
content into document creation actions without triggering re-generation.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from tiered_config import ADAPTER_ALLOWED_INTENTS

logger = logging.getLogger("akira.local_adapter")


def is_intent_allowed(intent: str) -> bool:
    """Check if the intent is permitted to execute via the local adapter."""
    return intent in ADAPTER_ALLOWED_INTENTS


def synthesize_command_envelope(
    intent: str,
    parameters: dict[str, Any] | None = None,
    context_delta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Synthesize a complete action or conversation envelope for allowed command intents.
    
    Returns None if the intent is not allowed or cannot be synthesized.
    """
    if not is_intent_allowed(intent):
        logger.info("[local_adapter] Intent %s not in ADAPTER_ALLOWED_INTENTS — refusing", intent)
        return None

    params = parameters or {}

    # Conversational intent
    if intent == "get_current_time":
        now = dt.datetime.now().strftime("%I:%M %p")
        return {
            "mode": "conversation",
            "response": f"It is currently {now}.",
            "end_session": False,
        }

    # Volume & Mute
    if intent == "adjust_volume":
        level = str(params.get("level", "+10")).strip()
        ack = "Adjusting the volume."
        if level in ("mute", "unmute"):
            ack = f"Audio {level}d."
        elif level.startswith("+"):
            ack = "Turning the volume up."
        elif level.startswith("-"):
            ack = "Turning the volume down."
        return _make_action_envelope("adjust_volume", level, ack)

    # App Management
    if intent == "open_application":
        app = str(params.get("app", "")).strip()
        if not app:
            return None
        return _make_action_envelope("open_application", app, f"Opening {app}.")

    if intent == "close_window":
        return _make_action_envelope("close_application", "", "Closing window.")

    if intent == "minimize_window":
        return _make_action_envelope("minimize_window", "", "Minimizing window.")

    if intent == "maximize_window":
        return _make_action_envelope("maximize_window", "", "Maximizing window.")

    if intent == "switch_application":
        target = str(params.get("app", "")).strip()
        return _make_action_envelope("switch_window", target, "Switching application.")

    # Tabs
    if intent == "list_tabs":
        return _make_action_envelope("list_tabs", "", "Checking open tabs.")

    if intent == "switch_tab":
        tab = str(params.get("tab", "")).strip()
        return _make_action_envelope("switch_tab", tab, "Switching tab.")

    if intent == "close_tab":
        return _make_action_envelope("close_tab", "", "Closing tab.")

    if intent == "open_new_tab":
        return _make_action_envelope("new_tab", "", "Opening a new tab.")

    # Clipboard
    if intent == "read_clipboard":
        return _make_action_envelope("read_clipboard", "", "Reading clipboard.")

    if intent == "write_clipboard":
        text = str(params.get("text", "")).strip()
        return _make_action_envelope("write_clipboard", text, "Copied to clipboard.")

    # Calendar
    if intent == "calendar_lookup":
        rng = str(params.get("range", "today")).strip()
        return _make_action_envelope("calendar_control", f"list|{rng}", f"Checking your calendar for {rng}.")

    # Spotify
    if intent == "spotify_play":
        return _make_action_envelope("spotify_control", "resume", "Resuming music on Spotify.")

    if intent == "spotify_pause":
        return _make_action_envelope("spotify_control", "pause", "Pausing music on Spotify.")

    if intent == "spotify_next":
        return _make_action_envelope("spotify_control", "next_track", "Skipping to the next track.")

    if intent == "spotify_previous":
        return _make_action_envelope("spotify_control", "previous_track", "Going back to the previous track.")

    if intent == "spotify_search_and_play":
        query = str(params.get("query", "")).strip()
        return _make_action_envelope("spotify_control", f"play|{query}", f"Playing {query} on Spotify.")

    # YouTube
    if intent == "youtube_play":
        query = str(params.get("query", "")).strip()
        return _make_action_envelope("youtube_control", f"play {query}".strip(), "Playing on YouTube.")

    if intent == "youtube_pause":
        return _make_action_envelope("youtube_control", "pause", "Pausing YouTube.")

    if intent == "youtube_seek":
        sec = str(params.get("seconds", "10")).strip()
        return _make_action_envelope("youtube_control", f"seek {sec}", "Seeking video.")

    if intent == "youtube_like":
        return _make_action_envelope("youtube_control", "like", "Liking video.")

    if intent == "youtube_subscribe":
        return _make_action_envelope("youtube_control", "subscribe", "Subscribing to channel.")

    if intent == "youtube_volume":
        vol = str(params.get("level", "50")).strip()
        return _make_action_envelope("youtube_control", f"volume {vol}", "Adjusting YouTube volume.")

    # Web Search
    if intent == "web_search_simple":
        query = str(params.get("query", "")).strip()
        if not query:
            return None
        return _make_action_envelope("web_search", query, f"Searching for {query}.")

    return None


def create_document_envelope(title: str, content: str, target: str = "google_doc") -> dict[str, Any]:
    """Author-agnostic document creation envelope.
    
    Accepts pre-written content (authored by either free speech head or Claude)
    and formats it into a docs_control|create action. Pure take-and-format,
    with zero internal AI regeneration or image search.
    """
    clean_title = (title or "Untitled Document").strip()
    clean_content = (content or "").strip()
    if not clean_content:
        clean_content = f"# {clean_title}\n\nDocument ready."

    # docs_control|create|Title|content takes prewritten content directly
    param = f"{clean_title}|{clean_content}"

    return {
        "mode": "action",
        "action": "docs_control",
        "parameter": param,
        "actions": [{"action": "docs_control", "parameter": param}],
        "response": f"I've created your document: {clean_title}.",
        "confirmation_required": False,
        "end_session": False,
    }


def _make_action_envelope(action: str, parameter: str, response_text: str) -> dict[str, Any]:
    return {
        "mode": "action",
        "action": action,
        "parameter": parameter,
        "actions": [{"action": action, "parameter": parameter}],
        "response": response_text,
        "confirmation_required": False,
        "end_session": False,
    }
