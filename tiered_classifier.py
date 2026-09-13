"""tiered_classifier.py — Fast, free-tier Decision API for Akira.

Classifies incoming utterances across three modes:
1. "command" — Action execution (volume, apps, tabs, clipboard, media)
2. "conversation" — Pure conversational chit-chat / Q&A
3. "document_generation" — Requests to draft and create written documents

For conversation and document generation, classifies complexity:
- "simple" -> can be served by free speech head
- "complex" -> escalates to Claude Sonnet 5
- "uncertain" -> first-class comfortable opt-out that escalates to Claude Sonnet 5

Receives ONLY the raw transcribed utterance — no desktop state, no tabs, no system prompt.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from tiered_config import (
    ADAPTER_ALLOWED_INTENTS,
    CONVERSATION_COMPLEXITY_KEYWORDS,
    CONVERSATION_MULTI_PART_SIGNALS,
    DOC_COMPLEXITY_KEYWORDS,
    DOC_MAX_SIMPLE_WORDS,
    get_min_confidence,
)

logger = logging.getLogger("akira.tiered_classifier")


@dataclass
class DecisionResult:
    mode: str = "conversation"  # "command" | "conversation" | "document_generation"
    complexity: str = "simple"  # "simple" | "complex" | "uncertain"
    intent: str = "NO_MATCH"
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    match: bool = True
    escalate: bool = False
    title: str = ""
    brief: str = ""
    raw_response: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "complexity": self.complexity,
            "intent": self.intent,
            "parameters": self.parameters,
            "confidence": self.confidence,
            "match": self.match,
            "escalate": self.escalate,
            "title": self.title,
            "brief": self.brief,
            "error": self.error,
        }


def _detect_doc_generation(text: str) -> tuple[bool, str, str, str]:
    """Check if utterance is a document generation request.
    
    Returns (is_doc, title, brief, complexity).
    """
    t_lower = text.lower().strip()

    doc_triggers = [
        "create a doc", "create a document", "write a doc", "write a document",
        "make a doc", "make a document", "generate a doc", "generate a document",
        "draft a doc", "draft a document", "create a note", "write a note",
        "write up a document", "write an article", "draft an article",
        "write a summary document", "make a word doc", "create a google doc",
    ]

    is_doc = any(trigger in t_lower for trigger in doc_triggers)
    if not is_doc:
        if (t_lower.startswith("write ") or t_lower.startswith("draft ")) and any(
            w in t_lower for w in ("about", "on", "explaining", "describing", "comparing")
        ):
            # E.g. "write an essay on...", "draft a comparison between..."
            is_doc = True

    if not is_doc:
        return False, "", "", "simple"

    # Evaluate cheap complexity signals
    complexity = "simple"

    # 1. Keyword detection
    for kw in DOC_COMPLEXITY_KEYWORDS:
        if kw in t_lower:
            complexity = "complex"
            break

    # 2. Explicit length detection (pages or high word counts)
    if any(p in t_lower for p in ("pages", "page", "words", "word")):
        # Check for numbers > 1 page or > DOC_MAX_SIMPLE_WORDS words
        pages_match = re.search(r"(\d+)\s*pages?", t_lower)
        if pages_match and int(pages_match.group(1)) > 1:
            complexity = "complex"
        words_match = re.search(r"(\d+)\s*words?", t_lower)
        if words_match and int(words_match.group(1)) > DOC_MAX_SIMPLE_WORDS:
            complexity = "complex"

    # 3. Extract title/brief heuristic
    title = "Untitled Document"
    brief = text
    about_match = re.search(r"(?:about|on|titled|called)\s+['\"]?([^'\".,]+)['\"]?", text, re.IGNORECASE)
    if about_match:
        cand_title = about_match.group(1).strip().title()
        if len(cand_title) < 40:
            title = cand_title

    return True, title, brief, complexity


def _detect_conversation_complexity(text: str) -> str:
    """Evaluate cheap-to-compute complexity signals for conversational queries."""
    t_lower = text.lower().strip()

    # 1. Multiple question marks or compound query punctuation
    if text.count("?") > 1:
        return "complex"

    # 2. Multi-part connective signals
    for signal in CONVERSATION_MULTI_PART_SIGNALS:
        if signal in t_lower:
            return "complex"

    # 3. Known analytical/comparative conversation keywords
    for kw in CONVERSATION_COMPLEXITY_KEYWORDS:
        if kw in t_lower:
            return "complex"

    # 4. Synthesizing or deep context queries
    if any(k in t_lower for k in ("earlier you said", "last session", "previous conversation", "our discussion")):
        return "complex"

    return "simple"


def _quick_pattern_match(text: str) -> DecisionResult | None:
    """Sub-millisecond keyword pattern matching for obvious single-app commands."""
    t = text.lower().strip()
    # Strip wake word if present
    t = re.sub(r"^akira[\s,:]+", "", t).strip()

    # 1. Volume / Mute
    if t in ("volume up", "turn volume up", "increase volume", "louder", "boost volume"):
        return DecisionResult(mode="command", intent="adjust_volume", parameters={"level": "+10"}, confidence=0.98)
    if t in ("volume down", "turn volume down", "decrease volume", "lower volume", "softer"):
        return DecisionResult(mode="command", intent="adjust_volume", parameters={"level": "-10"}, confidence=0.98)
    vol_num = re.match(r"(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})%?$", t)
    if vol_num:
        return DecisionResult(mode="command", intent="adjust_volume", parameters={"level": vol_num.group(1)}, confidence=0.98)
    if t in ("mute", "mute audio", "silence audio", "unmute", "unmute audio"):
        param = "mute" if "unmute" not in t else "unmute"
        return DecisionResult(mode="command", intent="adjust_volume", parameters={"level": param}, confidence=0.98)

    # 2. App launch
    app_m = re.match(r"(?:open|launch|start)\s+([a-zA-Z0-9_\-\s]+)$", t)
    if app_m:
        app_name = app_m.group(1).strip()
        # Avoid matching document or search commands
        if not any(k in app_name for k in ("doc", "document", "tab", "file", "note", "http", "youtube", "spotify")):
            return DecisionResult(mode="command", intent="open_application", parameters={"app": app_name}, confidence=0.95)

    # 3. Spotify transport
    if t in ("spotify pause", "pause spotify", "pause music", "pause song", "stop music"):
        return DecisionResult(mode="command", intent="spotify_pause", parameters={}, confidence=0.98)
    if t in ("spotify resume", "resume spotify", "resume music", "play spotify", "resume playback"):
        return DecisionResult(mode="command", intent="spotify_play", parameters={}, confidence=0.98)
    if t in ("spotify next", "next song", "next track", "skip song", "skip track"):
        return DecisionResult(mode="command", intent="spotify_next", parameters={}, confidence=0.98)
    if t in ("spotify previous", "previous song", "previous track", "last song"):
        return DecisionResult(mode="command", intent="spotify_previous", parameters={}, confidence=0.98)

    # 4. YouTube transport
    if t in ("youtube pause", "pause youtube", "pause video"):
        return DecisionResult(mode="command", intent="youtube_pause", parameters={}, confidence=0.98)
    if t in ("youtube resume", "resume youtube", "resume video", "play video"):
        return DecisionResult(mode="command", intent="youtube_play", parameters={}, confidence=0.98)
    if t in ("like video", "like youtube video", "thumbs up video"):
        return DecisionResult(mode="command", intent="youtube_like", parameters={}, confidence=0.98)
    if t in ("subscribe", "subscribe to channel"):
        return DecisionResult(mode="command", intent="youtube_subscribe", parameters={}, confidence=0.98)

    # 5. Window / Tabs
    if t in ("minimize window", "minimize this window", "minimize"):
        return DecisionResult(mode="command", intent="minimize_window", parameters={}, confidence=0.98)
    if t in ("maximize window", "maximize this window", "maximize"):
        return DecisionResult(mode="command", intent="maximize_window", parameters={}, confidence=0.98)
    if t in ("close window", "close this window"):
        return DecisionResult(mode="command", intent="close_window", parameters={}, confidence=0.98)
    if t in ("list tabs", "show tabs", "what tabs are open", "list open tabs"):
        return DecisionResult(mode="command", intent="list_tabs", parameters={}, confidence=0.98)
    if t in ("close tab", "close current tab", "close this tab"):
        return DecisionResult(mode="command", intent="close_tab", parameters={}, confidence=0.98)
    if t in ("new tab", "open a new tab", "open tab"):
        return DecisionResult(mode="command", intent="open_new_tab", parameters={}, confidence=0.98)

    # 6. Clipboard
    if t in ("read clipboard", "what is on my clipboard", "what's on my clipboard", "read what i copied"):
        return DecisionResult(mode="command", intent="read_clipboard", parameters={}, confidence=0.98)

    # 7. Calendar Read
    if t in ("check calendar", "what's on my calendar", "what is on my calendar today", "my agenda today", "calendar today"):
        return DecisionResult(mode="command", intent="calendar_lookup", parameters={"range": "today"}, confidence=0.95)

    # 8. Time check
    if t in ("what time is it", "what's the time", "current time", "tell me the time"):
        return DecisionResult(mode="command", intent="get_current_time", parameters={}, confidence=0.98)

    return None


def classify(user_text: str, timeout: float = 3.0) -> DecisionResult:
    """Classify user utterance into (mode, complexity/intent) with fail-safe escalation.
    
    Receives strictly the raw user utterance text.
    """
    cleaned = (user_text or "").strip()
    if not cleaned:
        return DecisionResult(mode="conversation", complexity="simple", intent="NO_MATCH", confidence=1.0)

    try:
        # Step 1: Check document generation triggers & complexity
        is_doc, doc_title, doc_brief, doc_complexity = _detect_doc_generation(cleaned)
        if is_doc:
            escalate = (doc_complexity in ("complex", "uncertain"))
            return DecisionResult(
                mode="document_generation",
                complexity=doc_complexity,
                title=doc_title,
                brief=doc_brief,
                confidence=0.95,
                match=True,
                escalate=escalate,
            )

        # Step 2: Check quick pattern matches for routine commands
        quick = _quick_pattern_match(cleaned)
        if quick is not None:
            min_conf = get_min_confidence()
            if quick.confidence < min_conf or quick.intent not in ADAPTER_ALLOWED_INTENTS:
                quick.escalate = True
            return quick

        # Step 3: Fast check for conversational utterances
        # If it looks like chit-chat, a question, or discussion
        conv_complexity = _detect_conversation_complexity(cleaned)
        
        # Check if the text contains obvious command verbs
        cmd_verbs = ("open ", "close ", "turn ", "set ", "play ", "pause ", "search ", "find ", "delete ", "copy ", "move ")
        has_cmd_verb = any(cleaned.lower().startswith(v) or f" {v}" in cleaned.lower() for v in cmd_verbs)

        if not has_cmd_verb:
            # It's a conversational utterance
            escalate = (conv_complexity in ("complex", "uncertain"))
            return DecisionResult(
                mode="conversation",
                complexity=conv_complexity,
                confidence=0.90,
                match=True,
                escalate=escalate,
            )

        # Step 4: Unknown / ambiguous command -> comfortably escalate to Claude
        return DecisionResult(
            mode="command",
            complexity="uncertain",
            intent="NO_MATCH",
            parameters={},
            confidence=0.5,
            match=False,
            escalate=True,
        )

    except Exception as err:
        # Hard fail-safe: free-tier/classifier error never crashes and never drops silently.
        # It fails open comfortably to Claude Sonnet 5 as an uncertain conversation.
        logger.warning("[tiered_classifier] Classifier exception: %s — failing open to Claude", err)
        print(f"[tiered_classifier] WARNING: {err!r} — failing open to Claude")
        return DecisionResult(
            mode="conversation",
            complexity="uncertain",
            intent="NO_MATCH",
            confidence=0.0,
            match=False,
            escalate=True,
            error=str(err),
        )
