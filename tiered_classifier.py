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
import time
from dataclasses import dataclass, field
from typing import Any

from tiered_config import (
    ADAPTER_ALLOWED_INTENTS,
    CONVERSATION_COMPLEXITY_KEYWORDS,
    CONVERSATION_MULTI_PART_SIGNALS,
    DOC_COMPLEXITY_KEYWORDS,
    DOC_MAX_SIMPLE_WORDS,
    check_ambiguous_pattern,
    get_chain_sanity_ceiling,
    get_fan_out_threshold,
    get_min_confidence,
    has_backward_reference,
)

logger = logging.getLogger("akira.tiered_classifier")


@dataclass
class DecisionResult:
    mode: str = "conversation"  # "command" | "conversation" | "document_generation"
    complexity: str = "simple"  # "simple" | "complex" | "uncertain" | "n/a"
    intent: str = "NO_MATCH"
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    match: bool = True
    escalate: bool = False
    escalate_trigger: str | None = None  # "backward_reference" | "mixed_mode" | "weak_link" | "chain_ceiling" | "fan_out" | "ambiguous_flag" | "no_match" | "low_confidence" | "allowlist_reject"
    fan_out: int = 1  # count of distinct apps/tabs/sequential steps touched
    is_chain: bool = False
    sub_tasks: list[str] = field(default_factory=list)
    sub_decisions: list[Any] = field(default_factory=list)
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
            "escalate_trigger": self.escalate_trigger,
            "fan_out": self.fan_out,
            "is_chain": self.is_chain,
            "sub_tasks": self.sub_tasks,
            "title": self.title,
            "brief": self.brief,
            "error": self.error,
        }


# ── Step Boundary Decomposition & Independence Verification ───────────────────
_ACTION_VERB_PATTERN = (
    r"(?:open|launch|start|close|play|pause|resume|next|previous|skip|stop|"
    r"search|turn|increase|decrease|set|mute|unmute|switch)"
)

_QUESTION_STARTER_PATTERN = (
    r"(?:what|how|who|where|when|why|tell me)"
)

_SPLIT_PATTERN = re.compile(
    r"(?:"
    r"[;]\s*"
    r"|,\s*(?:and\s+then|then|after\s+that|next|afterwards)\s*"
    r"|\b(?:and\s+then|then|after\s+that|next|afterwards)\s*"
    r"|,\s*and\s+(?:(?=" + _ACTION_VERB_PATTERN + r"\b)|(?=" + _QUESTION_STARTER_PATTERN + r"\b))"
    r"|,\s*(?=" + _ACTION_VERB_PATTERN + r"\b)"
    r"|\s+and\s+(?:(?=" + _ACTION_VERB_PATTERN + r"\b)|(?=" + _QUESTION_STARTER_PATTERN + r"\b))"
    r")",
    re.IGNORECASE,
)


def decompose_utterance(text: str) -> list[str]:
    """Decompose a multi-step utterance into an ordered list of individual sub-tasks.
    
    Reuses structural boundary detection, handling sequential connectives and shared initial verbs.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    cleaned = re.sub(r"^akira[\s,:]+", "", cleaned, flags=re.IGNORECASE).strip()

    raw_steps = [s.strip() for s in _SPLIT_PATTERN.split(cleaned) if s.strip()]
    if not raw_steps:
        return [cleaned]

    # Handle inherited initial verb (e.g. "open notepad, then chrome, then spotify")
    first_step = raw_steps[0]
    first_verb_match = re.match(r"^(" + _ACTION_VERB_PATTERN + r")\s+(.*)$", first_step, re.IGNORECASE)
    if first_verb_match and len(raw_steps) > 1:
        inherited_verb = first_verb_match.group(1)
        expanded_steps = [first_step]
        for s in raw_steps[1:]:
            has_clause_start = re.match(
                r"^(" + _ACTION_VERB_PATTERN + r"|" + _QUESTION_STARTER_PATTERN + r"|write|create|draft|make)\b",
                s,
                re.IGNORECASE,
            )
            if not has_clause_start:
                expanded_steps.append(f"{inherited_verb} {s}")
            else:
                expanded_steps.append(s)
        return expanded_steps

    return raw_steps


def estimate_command_fan_out(text: str) -> int:
    """Structurally estimate the fan-out count of steps in a command utterance."""
    steps = decompose_utterance(text)
    return max(len(steps), 1)


@dataclass
class ChainIndependenceResult:
    is_independent: bool
    sub_tasks: list[str]
    sub_decisions: list[DecisionResult]
    interdependent_reason: str | None = None  # "backward_reference" | "mixed_mode" | "weak_link" | "chain_ceiling"


def check_chain_independence(sub_tasks: list[str]) -> ChainIndependenceResult:
    """Run independence checks across the decomposed sub-task list.
    
    A chain is INTERDEPENDENT if:
    a) Any step (after step 0) contains a backward reference pronoun/term to a prior step's result
    b) Steps span more than one mode (e.g. command mixed with conversation or doc generation)
    c) Any individual sub-task is ambiguous-flagged, low confidence, NO_MATCH, or not in ADAPTER_ALLOWED_INTENTS
    d) Total steps exceed the sanity ceiling (6+ steps)
    """
    if not sub_tasks:
        return ChainIndependenceResult(is_independent=True, sub_tasks=[], sub_decisions=[])

    # Check d: Sanity ceiling
    ceiling = get_chain_sanity_ceiling()
    if len(sub_tasks) >= ceiling:
        return ChainIndependenceResult(
            is_independent=False,
            sub_tasks=sub_tasks,
            sub_decisions=[],
            interdependent_reason="chain_ceiling",
        )

    # Classify each sub-task individually as a standalone utterance
    sub_decisions: list[DecisionResult] = [classify(task, _is_subtask=True) for task in sub_tasks]

    # Check a: Backward reference in any subsequent step (i >= 1)
    for i in range(1, len(sub_tasks)):
        if has_backward_reference(sub_tasks[i]):
            return ChainIndependenceResult(
                is_independent=False,
                sub_tasks=sub_tasks,
                sub_decisions=sub_decisions,
                interdependent_reason="backward_reference",
            )

    # Check b: Mixed modes (commands mixed with conversation or doc gen)
    modes = {d.mode for d in sub_decisions}
    if len(modes) > 1 or any(m != "command" for m in modes):
        return ChainIndependenceResult(
            is_independent=False,
            sub_tasks=sub_tasks,
            sub_decisions=sub_decisions,
            interdependent_reason="mixed_mode",
        )

    # Check c: Weak link (any step ambiguous, low confidence, NO_MATCH, or unallowed)
    min_conf = get_min_confidence()
    for i, dec in enumerate(sub_decisions):
        step_text = sub_tasks[i]
        # Ambiguous pattern check
        if check_ambiguous_pattern(dec.intent, step_text) is not None:
            return ChainIndependenceResult(
                is_independent=False,
                sub_tasks=sub_tasks,
                sub_decisions=sub_decisions,
                interdependent_reason="weak_link",
            )
        # Low confidence or unrecognized
        if dec.confidence < min_conf or dec.intent == "NO_MATCH":
            return ChainIndependenceResult(
                is_independent=False,
                sub_tasks=sub_tasks,
                sub_decisions=sub_decisions,
                interdependent_reason="weak_link",
            )
        # Not allowed in adapter
        if dec.intent not in ADAPTER_ALLOWED_INTENTS:
            return ChainIndependenceResult(
                is_independent=False,
                sub_tasks=sub_tasks,
                sub_decisions=sub_decisions,
                interdependent_reason="weak_link",
            )

    # All checks passed cleanly -> Independent chain
    return ChainIndependenceResult(
        is_independent=True,
        sub_tasks=sub_tasks,
        sub_decisions=sub_decisions,
        interdependent_reason=None,
    )


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
        app_words = set(app_name.lower().split())
        excluded = {"doc", "document", "tab", "file", "note", "notes", "http", "youtube", "netflix"}
        if not app_words.intersection(excluded):
            return DecisionResult(mode="command", intent="open_application", parameters={"app": app_name}, confidence=0.95)

    # 3. Spotify transport
    if t in ("spotify pause", "pause spotify", "pause music", "pause song", "stop music"):
        return DecisionResult(mode="command", intent="spotify_pause", parameters={}, confidence=0.98)
    if t in ("spotify resume", "resume spotify", "resume music", "play spotify", "resume playback"):
        return DecisionResult(mode="command", intent="spotify_play", parameters={}, confidence=0.98)
    if t in ("spotify next", "next song", "next track", "skip song", "skip track", "change the song", "change song", "different song", "skip", "skip this song") or re.search(r"\b(?:change\s+(?:the\s+)?song|skip\s+(?:the\s+|this\s+)?(?:song|track)|next\s+(?:song|track))\b", t):
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
    if t in ("copy this", "copy that to clipboard", "put this on the clipboard", "copy to clipboard", "copy this to clipboard"):
        return DecisionResult(mode="command", intent="write_clipboard", parameters={}, confidence=0.98)

    copy_clipboard_patterns = (
        r"\bcopy\b.*?\b(?:this|that|the|your)?\s*(?:information|info|text|response|reply|answer|what you (?:just )?said)\b.*?\b(?:clipboard|clip board)\b",
        r"\bcopy\b.*?\b(?:last|previous)\s+response\b.*?\b(?:clipboard|clip board)\b",
        r"\bcopy\b.*?\b(?:clipboard|clip board)\b.*?\b(?:last|previous)\s+response\b",
        r"\bput\b.*?\b(?:this|that|what you (?:just )?said|the information)\b.*?\b(?:clipboard|clip board)\b",
    )
    if any(re.search(pat, t, re.IGNORECASE) for pat in copy_clipboard_patterns):
        import session_context_cache
        last_resp = session_context_cache.get_last_assistant_response()
        return DecisionResult(mode="command", intent="write_clipboard", parameters={"text": last_resp}, confidence=0.98)

    # 7. Calendar Read
    if t in ("check calendar", "what's on my calendar", "what is on my calendar today", "my agenda today", "calendar today"):
        return DecisionResult(mode="command", intent="calendar_lookup", parameters={"range": "today"}, confidence=0.95)

    # 8. Time check
    if t in ("what time is it", "what's the time", "current time", "tell me the time") or re.search(r"\b(?:what(?:\s*is|\s*'s)?\s*(?:the\s*)?time|what\s*time\s*is\s*it|check\s*(?:the\s*)?time|tell\s*me\s*the\s*time)\b", t):
        return DecisionResult(mode="command", intent="get_current_time", parameters={}, confidence=0.98)

    # 9. Colloquial Volume adjustment (e.g. crank the volume down)
    if re.search(r"\b(?:crank|turn|put)\s*(?:the\s*)?(?:volume|sound)\s*(?:down|up)\b", t):
        direction = "down" if "down" in t else "up"
        return DecisionResult(mode="command", intent="adjust_volume", parameters={"direction": direction}, confidence=0.98)

    # 10. Netflix commands (confident pattern match; ambiguity registry forces escalation)
    if "netflix" in t:
        return DecisionResult(
            mode="command",
            intent="netflix_control",
            parameters={"query": t},
            confidence=0.95,
            match=True,
        )

    return None


def classify(user_text: str, timeout: float = 3.0, _is_subtask: bool = False) -> DecisionResult:
    """Classify user utterance into (mode, complexity/intent) with fail-safe escalation.
    
    Decomposes multi-step chains and verifies independence before deciding route.
    """
    cleaned = (user_text or "").strip()
    if not cleaned:
        return DecisionResult(mode="conversation", complexity="simple", intent="NO_MATCH", confidence=1.0)

    try:
        # Step 0: Multi-step chain decomposition (when not already evaluating an isolated sub-task)
        if not _is_subtask:
            cmd_verbs = ("open ", "close ", "turn ", "set ", "play ", "pause ", "search ", "find ", "delete ", "copy ", "move ", "mute", "unmute", "spotify", "youtube", "launch ", "start ", "run ", "pull ", "hop ", "check ", "crank ", "minimize", "maximize", "list ", "show ")
            has_cmd_verb = any(cleaned.lower().startswith(v) or f" {v}" in cleaned.lower() for v in cmd_verbs)
            if has_cmd_verb:
                sub_tasks = decompose_utterance(cleaned)
                if len(sub_tasks) > 1:
                    chain_info = check_chain_independence(sub_tasks)
                    if chain_info.is_independent:
                        return DecisionResult(
                            mode="command",
                            complexity="n/a",
                            intent="command_chain",
                            confidence=0.95,
                            match=True,
                            escalate=False,
                            fan_out=len(sub_tasks),
                            is_chain=True,
                            sub_tasks=sub_tasks,
                            sub_decisions=chain_info.sub_decisions,
                        )
                    else:
                        return DecisionResult(
                            mode="command",
                            complexity="n/a",
                            intent="command_chain",
                            confidence=0.5,
                            match=False,
                            escalate=True,
                            escalate_trigger=chain_info.interdependent_reason,
                            fan_out=len(sub_tasks),
                            is_chain=True,
                            sub_tasks=sub_tasks,
                            sub_decisions=chain_info.sub_decisions,
                        )

        # Step 1: Check document generation triggers & complexity
        is_doc, doc_title, doc_brief, doc_complexity = _detect_doc_generation(cleaned)
        if is_doc:
            escalate = (doc_complexity in ("complex", "uncertain"))
            trigger = f"complex_doc" if doc_complexity == "complex" else (f"uncertain_doc" if doc_complexity == "uncertain" else None)
            return DecisionResult(
                mode="document_generation",
                complexity=doc_complexity,
                title=doc_title,
                brief=doc_brief,
                confidence=0.95,
                match=True,
                escalate=escalate,
                escalate_trigger=trigger,
                fan_out=1,
            )

        # Step 2: Check quick pattern matches for routine commands
        quick = _quick_pattern_match(cleaned)
        if quick is not None:
            quick.complexity = "n/a"
            quick.fan_out = 1
            min_conf = get_min_confidence()

            # Escalation checks ahead of dispatch
            if check_ambiguous_pattern(quick.intent, cleaned) is not None:
                quick.escalate = True
                quick.escalate_trigger = "ambiguous_flag"
            elif quick.confidence < min_conf:
                quick.escalate = True
                quick.escalate_trigger = "low_confidence"
            elif quick.intent not in ADAPTER_ALLOWED_INTENTS:
                quick.escalate = True
                quick.escalate_trigger = "allowlist_reject"
            return quick

        # Step 3: Fast check for conversational utterances
        conv_complexity = _detect_conversation_complexity(cleaned)
        
        # Check if the text contains obvious command verbs
        cmd_verbs = ("open ", "close ", "turn ", "set ", "play ", "pause ", "search ", "find ", "delete ", "copy ", "move ", "mute", "unmute", "spotify", "youtube", "launch ", "start ", "run ", "pull ", "hop ", "check ", "crank ", "minimize", "maximize", "list ", "show ")
        has_cmd_verb = any(cleaned.lower().startswith(v) or f" {v}" in cleaned.lower() for v in cmd_verbs)

        if not has_cmd_verb:
            # It's a conversational utterance
            escalate = (conv_complexity in ("complex", "uncertain"))
            trigger = f"complex_conversation" if conv_complexity == "complex" else (f"uncertain_conversation" if conv_complexity == "uncertain" else None)
            return DecisionResult(
                mode="conversation",
                complexity=conv_complexity,
                confidence=0.90,
                match=True,
                escalate=escalate,
                escalate_trigger=trigger,
                fan_out=1,
            )

        # Step 4: Unknown / ambiguous single command -> comfortably escalate to Claude
        return DecisionResult(
            mode="command",
            complexity="n/a",
            intent="NO_MATCH",
            parameters={},
            confidence=0.5,
            match=False,
            escalate=True,
            escalate_trigger="no_match",
            fan_out=1,
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


# ═══════════════════════════════════════════════════════════════════════════════
# ── COMBINED ROUTER & SYNTHESIZER (Option A: Direct Groq Envelope Emission) ──
# ═══════════════════════════════════════════════════════════════════════════════

def _synthesize_regex_envelope(decision: DecisionResult) -> dict[str, Any] | None:
    """Build an action envelope directly from a deterministic regex match (0 tokens, no Groq)."""
    intent = decision.intent
    params = decision.parameters or {}

    import datetime as dt

    if intent == "get_current_time":
        now = dt.datetime.now().strftime("%I:%M %p")
        return {
            "mode": "conversation",
            "response": f"It is currently {now}.",
            "end_session": False,
        }

    if intent == "adjust_volume":
        level = str(params.get("level", "+10")).strip()
        ack = "Adjusting the volume."
        if level in ("mute", "unmute"):
            ack = f"Audio {level}d."
        elif level.startswith("+"):
            ack = "Turning the volume up."
        elif level.startswith("-"):
            ack = "Turning the volume down."
        return {
            "mode": "command",
            "action": "adjust_volume",
            "parameter": level,
            "actions": [{"action": "adjust_volume", "parameter": level}],
            "response": ack,
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "open_application":
        app = str(params.get("app", "")).strip()
        if not app:
            return None
        return {
            "mode": "command",
            "action": "open_application",
            "parameter": app,
            "actions": [{"action": "open_application", "parameter": app}],
            "response": f"Opening {app}.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "close_window":
        return {
            "mode": "command",
            "action": "close_application",
            "parameter": "",
            "actions": [{"action": "close_application", "parameter": ""}],
            "response": "Closing window.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "minimize_window":
        return {
            "mode": "command",
            "action": "minimize_window",
            "parameter": "",
            "actions": [{"action": "minimize_window", "parameter": ""}],
            "response": "Minimizing window.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "maximize_window":
        return {
            "mode": "command",
            "action": "maximize_window",
            "parameter": "",
            "actions": [{"action": "maximize_window", "parameter": ""}],
            "response": "Maximizing window.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "list_tabs":
        return {
            "mode": "command",
            "action": "list_tabs",
            "parameter": "",
            "actions": [{"action": "list_tabs", "parameter": ""}],
            "response": "Checking open tabs.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "close_tab":
        return {
            "mode": "command",
            "action": "close_tab",
            "parameter": "",
            "actions": [{"action": "close_tab", "parameter": ""}],
            "response": "Closing tab.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "open_new_tab":
        return {
            "mode": "command",
            "action": "new_tab",
            "parameter": "",
            "actions": [{"action": "new_tab", "parameter": ""}],
            "response": "Opening a new tab.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "read_clipboard":
        return {
            "mode": "command",
            "action": "read_clipboard",
            "parameter": "",
            "actions": [{"action": "read_clipboard", "parameter": ""}],
            "response": "Reading clipboard.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "write_clipboard":
        text = str(params.get("text", "")).strip()
        if not text:
            try:
                import session_context_cache
                text = session_context_cache.get_last_assistant_response()
            except Exception:
                pass
        return {
            "mode": "command",
            "action": "write_clipboard",
            "parameter": text,
            "actions": [{"action": "write_clipboard", "parameter": text}],
            "response": "Copied that to your clipboard.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "calendar_lookup":
        rng = str(params.get("range", "today")).strip()
        return {
            "mode": "command",
            "action": "calendar_control",
            "parameter": f"list|{rng}",
            "actions": [{"action": "calendar_control", "parameter": f"list|{rng}"}],
            "response": f"Checking your calendar for {rng}.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "spotify_play":
        return {
            "mode": "command",
            "action": "spotify_control",
            "parameter": "resume",
            "actions": [{"action": "spotify_control", "parameter": "resume"}],
            "response": "Resuming music on Spotify.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "spotify_pause":
        return {
            "mode": "command",
            "action": "spotify_control",
            "parameter": "pause",
            "actions": [{"action": "spotify_control", "parameter": "pause"}],
            "response": "Pausing music on Spotify.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "spotify_next":
        return {
            "mode": "command",
            "action": "spotify_control",
            "parameter": "next_track",
            "actions": [{"action": "spotify_control", "parameter": "next_track"}],
            "response": "Skipping to the next track.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "spotify_previous":
        return {
            "mode": "command",
            "action": "spotify_control",
            "parameter": "previous_track",
            "actions": [{"action": "spotify_control", "parameter": "previous_track"}],
            "response": "Going back to the previous track.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "youtube_play":
        query = str(params.get("query", "")).strip()
        param = f"play {query}".strip()
        return {
            "mode": "command",
            "action": "youtube_control",
            "parameter": param,
            "actions": [{"action": "youtube_control", "parameter": param}],
            "response": "Playing on YouTube.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "youtube_pause":
        return {
            "mode": "command",
            "action": "youtube_control",
            "parameter": "pause",
            "actions": [{"action": "youtube_control", "parameter": "pause"}],
            "response": "Pausing YouTube.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "youtube_like":
        return {
            "mode": "command",
            "action": "youtube_control",
            "parameter": "like",
            "actions": [{"action": "youtube_control", "parameter": "like"}],
            "response": "Liking video.",
            "confirmation_required": False,
            "end_session": False,
        }

    if intent == "youtube_subscribe":
        return {
            "mode": "command",
            "action": "youtube_control",
            "parameter": "subscribe",
            "actions": [{"action": "youtube_control", "parameter": "subscribe"}],
            "response": "Subscribing to channel.",
            "confirmation_required": False,
            "end_session": False,
        }

    return None


def _combine_regex_envelopes(envelopes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Combine multiple regex action envelopes into a single sequential multi-action envelope."""
    if not envelopes:
        return None

    combined_actions: list[dict[str, Any]] = []
    responses: list[str] = []

    for env in envelopes:
        if not env:
            continue
        for a in env.get("actions", []):
            combined_actions.append(a)
        resp = env.get("response")
        if resp:
            responses.append(resp.rstrip("."))

    if not combined_actions:
        return None

    if len(responses) == 1:
        spoken = f"{responses[0]}."
    elif len(responses) == 2:
        spoken = f"{responses[0]}, and {responses[1].lower()}."
    else:
        spoken = f"{', '.join(responses[:-1])}, and {responses[-1].lower()}."

    return {
        "mode": "command",
        "action": combined_actions[0].get("action", ""),
        "parameter": combined_actions[0].get("parameter", ""),
        "actions": combined_actions,
        "response": spoken,
        "confirmation_required": False,
        "end_session": False,
    }


def _build_action_rules_spec() -> str:
    """Generate compact serialized ACTION_RULES specification for the Groq system prompt."""
    try:
        import guard_rules
        rules = guard_rules.ACTION_RULES
    except Exception:
        return ""

    items = []
    for name in sorted(rules.keys()):
        r = rules[name]
        if r.max_fields == 0:
            desc = "no param"
        elif r.min_fields == 0 and r.max_fields == 1:
            desc = "[opt]"
        elif r.max_fields == 1:
            desc = "<arg>"
        elif r.max_fields == 2:
            desc = "<sub|arg>"
        else:
            desc = "<pipe_args>"
        items.append(f"{name}: {desc}")

    # Pack into compact 3-column rows
    rows = []
    for i in range(0, len(items), 3):
        rows.append("  " + " | ".join(items[i:i+3]))
    return "\n".join(rows)


_CONVERSATION_PATTERNS: tuple[str, ...] = (
    r"^(?:hello|hi|hey|greetings|howdy)(?:\s+akira)?[\s.!?]*$",
    r"^(?:good\s+(?:morning|afternoon|evening|night|day))(?:\s+akira)?[\s.!?]*$",
    r"^how\s+are\s+you(?:.*)?$",
    r"^what(?:\'s|\s+is)\s+up(?:.*)?$",
    r"^who\s+are\s+you(?:.*)?$",
    r"^what\s+can\s+you\s+do(?:.*)?$",
    r"^tell\s+me\s+a\s+joke(?:.*)?$",
    r"^thanks?(?:\s+you)?(?:\s+very\s+much|\s+a\s+lot)?(?:.*)?$",
    r"^thank\s+you(?:\s+akira)?[\s.!?]*$",
    r"^you(?:'re|\s+are)\s+(?:awesome|great|cool|the\s+best)[\s.!?]*$",
    r"^(?:what|how)(?:\'s|\s+is)\s+the\s+weather(?:.*)?$",
)


def _build_router_system_prompt() -> str:
    """Construct the system prompt for direct action-envelope generation with Akira personality."""
    rules_spec = _build_action_rules_spec()
    return f"""### IDENTITY & PERSONALITY
You are Akira (also called Sensei), an intelligent, highly responsive, voice-first desktop companion for Windows.
- Tone: Direct, confident, helpful, articulate, and sharp. Never sound robotic, preachy, or overly formal.
- Audio-First Voice: Your 'response' string is directly spoken aloud to the user via Text-to-Speech (TTS). Keep spoken acknowledgments clean, natural, and punchy (1 to 2 sentences).
- ZERO MARKDOWN in Spoken Voice: NEVER include markdown asterisks (**bold**), bullet points, numbered lists, backticks, emojis, or code blocks in the 'response' field.
- Multi-Action Synthesis: When the user requests compound, chained, or multi-step tasks (e.g. "Turn the volume up and check my calendar", "Mute audio, open Spotify, and play lofi beats"), you MUST synthesize ALL actions in sequence into the "actions" array. NEVER drop subsequent actions!
- Context-Aware Clipboard & Apps: Use [LAST ASSISTANT RESPONSE] to copy what was previously said to clipboard. Use [CONTEXT DELTA] to resolve active windows, open tabs, or relative references like "this tab" or "that file".

### MANDATORY CHAIN SAFETY RULES (GENERATION-TIME CONSTRAINTS)
1. NEVER chain 'download_image' in the same turn as 'search_image'. 'search_image' shows candidate images to the user; downloading must only happen in a subsequent turn after the user picks one.
2. At most ONE 'download_image' action per turn.
3. Every action name MUST be chosen from the ALLOWED ACTIONS list below.
4. Parameter formats MUST match the required pipe-separated shape.
5. ACTION PRIMACY: When the user asks to perform an actionable task (create, open, write, search, play, minimize, or adjust something on the PC), you MUST output mode: "command" with the real action(s). NEVER output mode: "conversation" saying you will do it — emit the concrete command actions.
6. DANGEROUS & GATED ACTIONS (CONFIRMATION):
   - Destructive actions (such as 'close_application', 'shutdown_pc', 'restart_pc', 'hibernate_pc', 'clear_temp_files', 'empty_recycle_bin', 'delete_files', 'move_files') require confirmation.
   - When confirmation is needed, put those dangerous steps in the "pending_actions" array, set "confirmation_required": true, and provide a clear "confirmation_message".
   - Safe actions preceding a dangerous step remain in the "actions" array so they run immediately.
8. LONG CONTENT GENERATION & SPREADSHEETS:
   - Google Drive / Google Docs: When the user asks to write/draft/create a document in Google Drive ("in my drive", "on drive", "google doc", "doc in drive", "create a drive doc"):
     use 'docs_control' with parameter 'generate|<Title>|<brief>|detailed'. Google Docs automatically creates, edits, and saves the document directly in Google Drive.
   - Google Sheets / Spreadsheets on Drive: When the user asks to create a spreadsheet, budget planner, expense sheet, or data table in Google Sheets or save spreadsheet to Drive:
     use 'sheets_control' with parameter 'generate|<Title>|<brief>'.
   - Excel Workbook / Local Spreadsheets: When the user asks to create an Excel spreadsheet, budget planner, or tracker locally in Excel:
     use 'office_control' with parameter 'excel|generate|<Title>|<brief>'.
   - Word Document / Downloads / Local: When the user asks for a Word document, local docx, or downloads file ("in my download", "word doc", "docx", "detailed write-up", "two pages on", "save it in my downloads"):
     use 'office_control' with parameter 'word|generate|<Title>|<brief>|detailed'.
   - NEVER try to inline long text in 'word|insert', 'docs_control|create', or in the 'response' field — that will exceed your token limit.
   - For SHORT inline text (a sentence or two, e.g. "write a quick summary"), use 'word|insert|<text>'.
7. BROWSER & TAB CONTROL (STRICT RULES):
   - NEVER open a new tab unless the user explicitly says "new tab" or "different tab".
   - TAB REUSE: If YouTube, Amazon, Spotify, Netflix, or any requested website is ALREADY open (check [CONTEXT DELTA] or open windows/tabs), DO NOT emit 'open_site_tab' or 'new_tab'!
     * If user says "Open YouTube" and YouTube is open: emit 'switch_tab' with parameter "youtube".
     * If user says "Play X on YouTube" or "Search X on YouTube": emit direct site action ONLY ('youtube_control|play X' or 'youtube_control|search X'). NEVER emit 'open_site_tab' or 'new_tab'!
     * For Amazon: emit 'switch_tab|amazon' or 'site_search|amazon|<query>'.

### COMMON ACTION PATTERNS:
- Office ('office_control'): 'excel|generate|<title>|<brief>', 'excel|new', 'excel|write|<cell>|<val>', 'word|generate|<title>|<brief>|detailed', 'word|new', 'word|insert|<text>', 'powerpoint|new', 'powerpoint|next slide'
- Google Workspace: 'docs_control|generate|<title>|<brief>|detailed', 'sheets_control|generate|<name>|<brief>', 'calendar_control|today', 'calendar_control|create|<title>|<start>|<end>', 'gmail_control|unread'
- Media & Audio: 'spotify_control|play|<query>', 'spotify_control|next', 'spotify_control|pause', 'youtube_control|search <q>', 'youtube_control|play <q>', 'adjust_volume|+10', 'adjust_volume|mute'
- Files & Storage: 'search_file|<query>', 'summarize_file|<path>', 'organize_folder|<folder_path>', 'open_file|<path>', 'open_folder|<path>', 'create_file|<path>|<content>'
- System & Apps: 'performance_stats' (""), 'open_application|<app>', 'close_application|<app>', 'write_clipboard|<text>', 'open_site_tab|<url>', 'switch_tab|<site>'

### CRITICAL SPOKEN VOICE & RESPONSE RULES:
- The "response" field is spoken aloud to the user via Text-to-Speech (TTS).
- KEEP IT CONCISE: 1 short, natural sentence acknowledging the action (e.g. "Creating your weekly budget planner in Google Sheets.").
- NEVER explain or read out tutorials, recipes, or steps on HOW to create a spreadsheet or file (e.g. NEVER recite "Step 1: Open Excel, Step 2: set column headers..."). Always emit the action directly and keep response short.
- For reading files or folders, summarize what was found in 1-2 sentences and ask if the user wants details. Never monologue raw listings or files.

### OUTPUT JSON FORMAT (STRICT REQUIREMENT)
You MUST ALWAYS emit a single valid JSON object starting with '{{' and ending with '}}'.
NEVER emit plain conversational text, markdown code blocks, preamble, or commentary outside JSON.
If the user asks a question, conversational chit-chat, or a request that you answer with words:
{{"mode": "conversation", "response": "<your complete conversational reply text here>"}}

For safe desktop actions (no confirmation required):
{{"mode": "command", "actions": [{{"action": "<action_name>", "parameter": "<parameter_string>"}}], "response": "<short spoken acknowledgement>"}}

For actions requiring user confirmation (e.g. closing applications, system power, clearing files):
{{"mode": "command", "actions": [...safe actions...], "pending_actions": [{{"action": "<dangerous_action>", "parameter": "<parameter_string>"}}], "confirmation_required": true, "confirmation_message": "<warm direct confirmation question>", "response": "<spoken message asking confirmation>"}}

For requests that are ambiguous, need human clarification, or cannot be determined:
{{"escalate": true, "reason": "<short explanation>"}}

### FEW-SHOT EXAMPLES:
User: "Why is my PC lagging? Check what's slowing it down"
{{"mode": "command", "actions": [{{"action": "performance_stats", "parameter": ""}}], "response": "Checking your CPU and memory to find what's causing the lag."}}

User: "Turn the volume up, then check my calendar for today"
{{"mode": "command", "actions": [{{"action": "adjust_volume", "parameter": "+10"}}, {{"action": "calendar_control", "parameter": "today"}}], "response": "Turning the volume up and checking your calendar."}}

User: "Mute the audio right now, pull up Spotify, and play lofi beats"
{{"mode": "command", "actions": [{{"action": "adjust_volume", "parameter": "mute"}}, {{"action": "open_application", "parameter": "spotify"}}, {{"action": "spotify_control", "parameter": "play|lofi beats"}}], "response": "Muting audio and playing lofi beats on Spotify."}}

User: "Sensei, copy this information into my clipboard that you provided in the last response."
(Context contains: [LAST ASSISTANT RESPONSE] Solar energy is rapidly expanding worldwide.)
{{"mode": "command", "actions": [{{"action": "write_clipboard", "parameter": "Solar energy is rapidly expanding worldwide."}}], "response": "Copied that to your clipboard."}}

User: "Create a budget planner in Excel for next week with formulas"
{{"mode": "command", "actions": [{{"action": "office_control", "parameter": "excel|generate|Weekly_Budget_Planner|Create a structured weekly budget planner with categories for income, expenses, and total formulas"}}], "response": "Generating a weekly budget planner with formulas in Excel."}}

User: "Write a detailed document on quantum computing in my Google Drive"
{{"mode": "command", "actions": [{{"action": "docs_control", "parameter": "generate|Quantum Computing|Write a comprehensive overview of quantum computing, qubits, and applications|detailed"}}], "response": "Generating a detailed document on quantum computing in your Google Drive."}}

User: "Write a detailed Word document on reinforcement learning in Downloads"
{{"mode": "command", "actions": [{{"action": "office_control", "parameter": "word|generate|Reinforcement Learning|Write a comprehensive overview of reinforcement learning|detailed"}}], "response": "Creating a detailed Word document on reinforcement learning in your Downloads folder."}}

User: "Close Excel and open Spotify"
{{"mode": "command", "actions": [{{"action": "open_application", "parameter": "spotify"}}], "pending_actions": [{{"action": "close_application", "parameter": "excel"}}], "confirmation_required": true, "confirmation_message": "Opening Spotify. Would you like me to close Excel as well?", "response": "Opening Spotify. Should I close Excel too?"}}

User: "Organize my Downloads folder"
{{"mode": "command", "actions": [], "pending_actions": [{{"action": "organize_folder", "parameter": "%USERPROFILE%\\Downloads"}}], "confirmation_required": true, "confirmation_message": "Would you like me to sort loose files in your Downloads folder into categorized subfolders?", "response": "I can organize your Downloads folder. Would you like me to proceed?"}}

User: "What time is it right now?"
{{"mode": "conversation", "response": "It is currently 2:15 AM."}}

User: "Who are you and what can you do?"
{{"mode": "conversation", "response": "I'm Akira, your desktop companion. I can control your media, manage applications, create spreadsheets, organize files, and answer questions."}}

### ALLOWED ACTIONS & PARAMETER SHAPES (ACTION_RULES spec):
{rules_spec}
"""


_LAST_ROUTER_TELEMETRY: dict[str, Any] = {}
_ROUTING_METRICS: dict[str, int] = {
    "total_turns": 0,
    "phase_1_regex_hits": 0,
    "phase_2_groq_calls": 0,
    "phase_2_failovers_429": 0,
}

def get_last_router_telemetry() -> dict[str, Any]:
    return dict(_LAST_ROUTER_TELEMETRY)


def reset_routing_metrics() -> None:
    """Reset the routing telemetry metrics counter."""
    _ROUTING_METRICS["total_turns"] = 0
    _ROUTING_METRICS["phase_1_regex_hits"] = 0
    _ROUTING_METRICS["phase_2_groq_calls"] = 0
    _ROUTING_METRICS["phase_2_failovers_429"] = 0


def get_routing_metrics() -> dict[str, Any]:
    """Return live counts and percentage ratio of Phase 1 regex vs Phase 2 Groq calls."""
    total = _ROUTING_METRICS["total_turns"]
    p1 = _ROUTING_METRICS["phase_1_regex_hits"]
    p2 = _ROUTING_METRICS["phase_2_groq_calls"]
    p1_pct = round((p1 / total * 100), 1) if total > 0 else 0.0
    p2_pct = round((p2 / total * 100), 1) if total > 0 else 0.0
    return {
        "total_turns": total,
        "phase_1_regex_hits": p1,
        "phase_1_regex_pct": f"{p1_pct}%",
        "phase_2_groq_calls": p2,
        "phase_2_groq_pct": f"{p2_pct}%",
        "regex_hit_ratio_pct": p1_pct,
        "phase_2_failovers_429": _ROUTING_METRICS["phase_2_failovers_429"],
    }


_ACTION_CLAIM_PATTERNS = re.compile(
    r"\b(?:i(?:'ve| have)? (?:saved|created|written|downloaded|deleted|moved|opened|closed|set|updated|generated)\b.*?\b(?:file|folder|document|spreadsheet|downloads?|desktop|window)\b)|"
    r"\b(?:saved (?:it|this|the file|the document) (?:as|to|in)\b)|"
    r"\b(?:file (?:has been|is) saved\b)|"
    r"\b(?:i(?:'ve| have) saved (?:it|this)\b)",
    re.IGNORECASE
)

def _enforce_no_action_hallucinations(text: str) -> str:
    """Hard post-validation constraint: conversational responses CANNOT assert file or system state changes.
    
    If actions list is empty, conversational text claiming files were saved or created is intercepted
    and converted to a truthful, non-hallucinated response.
    """
    if _ACTION_CLAIM_PATTERNS.search(text):
        logger.warning("[tiered_classifier] Intercepted action-completion hallucination in conversational mode: %r", text[:100])
        return "I cannot save files or perform system changes while in conversational mode without an action. Would you like me to create this file for you?"
    return text


_COMMAND_VERBS = ("open", "launch", "start", "close", "turn", "set", "play", "pause", "resume", "skip", "mute", "unmute", "search", "find", "delete", "copy", "move", "save", "create", "write", "check")

def _is_compound_utterance(text: str) -> bool:
    """Detect compound/chained commands that must bypass single-action regex and route to Groq.
    
    Checks for conjunctions ('and', 'then', 'also', commas, semicolons).
    Special-cases media queries (e.g. 'play Simon and Garfunkel'): 'and' in media titles
    is NOT treated as a compound conjunction unless followed by another command verb.
    """
    t = text.lower().strip()
    t = re.sub(r"^(?:akira|sensei)[\s,:]+", "", t).strip()

    # Comma or semicolon separating clauses
    if re.search(r"[,;]\s*(?:then\s+|and\s+)?[a-z]", t):
        return True

    # Check for conjunctions followed by command verbs
    for conj in (r"\bthen\b", r"\bafter that\b", r"\bfollowed by\b", r"\balso\b"):
        if re.search(conj, t):
            return True

    # For 'and': check all occurrences
    and_matches = list(re.finditer(r"\band\s+([a-z]+)", t))
    if and_matches:
        # If ANY 'and' is followed by a command verb (e.g. '... and turn volume up'), it is compound
        if any(m.group(1) in _COMMAND_VERBS for m in and_matches):
            return True
        # If utterance doesn't start with media/play, 'and' indicates a compound sentence
        if not re.match(r"^(?:play|put on|stream|listen to)\b", t):
            return True

    return False


def _try_fast_path_regex(utterance: str) -> dict[str, Any] | None:
    """Safe, strictly anchored (<1ms, 0-token) local regex fast-path for atomic single commands."""
    t = utterance.lower().strip()
    t = re.sub(r"^(?:akira|sensei)[\s,:]+", "", t).strip()
    t = re.sub(r"[.?!]+$", "", t).strip()

    # 0. Active reading follow-up (chunked read / details)
    try:
        import chunked_read
        if chunked_read.active():
            if t in ("yes", "yeah", "yep", "sure", "keep reading", "continue", "more", "read more", "read in detail", "read it", "go ahead", "read", "details", "list them", "list in detail", "read them"):
                return {
                    "mode": "command",
                    "action": "read_more",
                    "parameter": "",
                    "actions": [{"action": "read_more", "parameter": ""}],
                    "response": "Reading next section.",
                    "confirmation_required": False,
                    "end_session": False
                }
            elif t in ("no", "stop", "stop reading", "that's enough", "thats enough", "pause", "never mind", "dont"):
                return {
                    "mode": "command",
                    "action": "stop_reading",
                    "parameter": "",
                    "actions": [{"action": "stop_reading", "parameter": ""}],
                    "response": "Stopped reading.",
                    "confirmation_required": False,
                    "end_session": False
                }
    except Exception:
        pass

    # 1. Volume / Mute
    if t in ("volume up", "turn volume up", "turn the volume up", "increase volume", "louder", "boost volume"):
        return {"mode": "command", "action": "adjust_volume", "parameter": "+10", "actions": [{"action": "adjust_volume", "parameter": "+10"}], "response": "Turning the volume up.", "confirmation_required": False, "end_session": False}
    if t in ("volume down", "turn volume down", "turn the volume down", "decrease volume", "lower volume", "softer"):
        return {"mode": "command", "action": "adjust_volume", "parameter": "-10", "actions": [{"action": "adjust_volume", "parameter": "-10"}], "response": "Turning the volume down.", "confirmation_required": False, "end_session": False}
    vol_num = re.match(r"^(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})%?$", t)
    if vol_num:
        val = vol_num.group(1)
        return {"mode": "command", "action": "adjust_volume", "parameter": val, "actions": [{"action": "adjust_volume", "parameter": val}], "response": f"Setting volume to {val} percent.", "confirmation_required": False, "end_session": False}
    if t in ("mute", "mute audio", "silence audio", "unmute", "unmute audio"):
        param = "unmute" if "unmute" in t else "mute"
        return {"mode": "command", "action": "adjust_volume", "parameter": param, "actions": [{"action": "adjust_volume", "parameter": param}], "response": f"Audio {param}d.", "confirmation_required": False, "end_session": False}

    # 2. Spotify / Media Transport
    if t in ("pause", "pause music", "pause playback", "pause spotify", "stop music", "pause video"):
        return {"mode": "command", "action": "spotify_control", "parameter": "pause", "actions": [{"action": "spotify_control", "parameter": "pause"}], "response": "Paused.", "confirmation_required": False, "end_session": False}
    if t in ("resume", "resume music", "resume playback", "resume spotify", "play music", "unpause"):
        return {"mode": "command", "action": "spotify_control", "parameter": "resume", "actions": [{"action": "spotify_control", "parameter": "resume"}], "response": "Resuming playback.", "confirmation_required": False, "end_session": False}
    if t in ("next", "next track", "next song", "skip", "skip track", "skip song"):
        return {"mode": "command", "action": "spotify_control", "parameter": "next", "actions": [{"action": "spotify_control", "parameter": "next"}], "response": "Skipping to next track.", "confirmation_required": False, "end_session": False}
    if t in ("previous", "previous track", "previous song", "last song", "go back a track"):
        return {"mode": "command", "action": "spotify_control", "parameter": "previous", "actions": [{"action": "spotify_control", "parameter": "previous"}], "response": "Going back to previous track.", "confirmation_required": False, "end_session": False}

    # 3. Window Management
    if t in ("minimize", "minimize window", "minimize this window"):
        return {"mode": "command", "action": "minimize_window", "parameter": "", "actions": [{"action": "minimize_window", "parameter": ""}], "response": "Minimizing window.", "confirmation_required": False, "end_session": False}
    if t in ("maximize", "maximize window", "maximize this window"):
        return {"mode": "command", "action": "maximize_window", "parameter": "", "actions": [{"action": "maximize_window", "parameter": ""}], "response": "Maximizing window.", "confirmation_required": False, "end_session": False}
    if t in ("close window", "close this window"):
        return {"mode": "command", "action": "close_application", "parameter": "", "actions": [{"action": "close_application", "parameter": ""}], "response": "Closing window.", "confirmation_required": False, "end_session": False}

    # 4. Browser Tabs
    if t in ("list tabs", "show tabs", "what tabs are open"):
        return {"mode": "command", "action": "list_tabs", "parameter": "", "actions": [{"action": "list_tabs", "parameter": ""}], "response": "Checking your open tabs.", "confirmation_required": False, "end_session": False}
    if t in ("close tab", "close this tab", "close current tab"):
        return {"mode": "command", "action": "close_tab", "parameter": "", "actions": [{"action": "close_tab", "parameter": ""}], "response": "Closing current tab.", "confirmation_required": False, "end_session": False}
    if t in ("new tab", "open a new tab", "open tab"):
        return {"mode": "command", "action": "new_tab", "parameter": "", "actions": [{"action": "new_tab", "parameter": ""}], "response": "Opening a new tab.", "confirmation_required": False, "end_session": False}

    # 5. System Utilities
    if t in ("lock", "lock pc", "lock the computer", "lock screen"):
        return {"mode": "command", "action": "lock_pc", "parameter": "", "actions": [{"action": "lock_pc", "parameter": ""}], "response": "Locking your PC.", "confirmation_required": False, "end_session": False}
    if t in ("what time is it", "what's the time", "current time", "tell me the time"):
        import datetime as dt
        now_str = dt.datetime.now().strftime("%I:%M %p")
        return {"mode": "conversation", "response": f"It is currently {now_str}.", "end_session": False}
    if t in ("performance stats", "check performance", "how is my pc doing"):
        return {"mode": "command", "action": "performance_stats", "parameter": "", "actions": [{"action": "performance_stats", "parameter": ""}], "response": "Checking hardware performance stats.", "confirmation_required": False, "end_session": False}
    if t in ("read clipboard", "what's on my clipboard", "what is on my clipboard"):
        return {"mode": "command", "action": "read_clipboard", "parameter": "", "actions": [{"action": "read_clipboard", "parameter": ""}], "response": "Reading your clipboard.", "confirmation_required": False, "end_session": False}

    # 6. Live Audience Demo: Folder Privacy Exclusion
    m_exc = re.match(r"^(?:exclude\s+(?:folder\s+|dir\s+|directory\s+)?|remove\s+(?:folder\s+|dir\s+)?)(.+?)(?:\s+from\s+(?:index|search|map))?$", t, re.IGNORECASE)
    if m_exc and not any(kw in t for kw in ("file", "history", "tab", "window", "app")):
        target_folder = m_exc.group(1).strip().strip("\"'")
        base_name = os.path.basename(target_folder) or target_folder
        return {
            "mode": "command",
            "action": "manage_index_scope",
            "parameter": f"exclude|{target_folder}",
            "actions": [{"action": "manage_index_scope", "parameter": f"exclude|{target_folder}"}],
            "response": f"Excluding {base_name} from indexing and updating the drive map.",
            "confirmation_required": False,
            "end_session": False
        }

    # 7. Folder Organization Fast-Path
    if re.search(r"\borganize\s+(?:my\s+)?(?:downloads(?:\s+folder)?|download)\b", t):
        return {
            "mode": "command",
            "action": "organize_folder",
            "parameter": "%USERPROFILE%\\Downloads",
            "actions": [{"action": "organize_folder", "parameter": "%USERPROFILE%\\Downloads"}],
            "response": "Checking files in Downloads to organize.",
            "confirmation_required": False,
            "end_session": False
        }

    # 8. Budget Planner & Spreadsheet Fast-Path
    if any(bp in t for bp in ("budget planner", "weekly budget", "expense tracker", "budget sheet")):
        if any(w in t for w in ("drive", "google sheet", "google sheets", "cloud")):
            return {
                "mode": "command",
                "action": "sheets_control",
                "parameter": "generate|Weekly Budget Planner|Weekly budget planner with categories, income, fixed and variable expenses, planned vs actual amounts, and formulas",
                "actions": [{"action": "sheets_control", "parameter": "generate|Weekly Budget Planner|Weekly budget planner with categories, income, fixed and variable expenses, planned vs actual amounts, and formulas"}],
                "response": "Creating a detailed weekly budget planner Google Sheet and saving it to your Drive.",
                "confirmation_required": False,
                "end_session": False
            }
        elif "excel" in t:
            return {
                "mode": "command",
                "action": "office_control",
                "parameter": "excel|generate|Weekly_Budget_Planner|Weekly budget planner with categories, income, fixed and variable expenses, planned vs actual, and formulas",
                "actions": [
                    {"action": "office_control", "parameter": "excel|generate|Weekly_Budget_Planner|Weekly budget planner with categories, income, fixed and variable expenses, planned vs actual, and formulas"}
                ],
                "response": "Creating a new Excel weekly budget planner with expense formulas.",
                "confirmation_required": False,
                "end_session": False
            }

    # 9. Clean Single App Launch (Strictly [a-zA-Z0-9_\-]+ only — excludes prepositions, URLs, clauses)
    orig_t = re.sub(r"^(?:akira|sensei)[\s,:]+", "", utterance, flags=re.IGNORECASE).strip().rstrip(".?!")
    app_m = re.match(r"^(?:open|launch|start)\s+([a-zA-Z0-9_\-]+)$", orig_t, re.IGNORECASE)
    if app_m:
        app_name = app_m.group(1).strip()
        # Exclude reserved words or ambiguous keywords
        if app_name.lower() not in ("tab", "file", "doc", "document", "note", "folder", "window", "url", "site", "to", "in"):
            return {"mode": "command", "action": "open_application", "parameter": app_name, "actions": [{"action": "open_application", "parameter": app_name}], "response": f"Opening {app_name}.", "confirmation_required": False, "end_session": False}

    return None


def _call_groq_router(utterance: str, delta_context: str | None = None, timeout: float = 4.0) -> dict[str, Any] | None:
    """Send ONE Groq call to synthesize the action envelope directly.
    
    EXPLICIT CONTEXT BOUNDS:
    - Receives ONLY raw utterance and format_delta_context() output.
    - NEVER receives core_profile.md, conversation history, file/clipboard contents, or full context.
    """
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not groq_key:
        logger.warning("[tiered_classifier] GROQ_API_KEY unset — escalating to Claude")
        return {"escalate": True, "reason": "GROQ_API_KEY_unset"}

    model = os.environ.get("GROQ_ROUTER_MODEL", os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"))

    user_content = utterance.strip()
    if delta_context and delta_context.strip():
        user_content = f"{delta_context.strip()}\n\nUser utterance: {user_content}"

    messages = [
        {"role": "system", "content": _build_router_system_prompt()},
        {"role": "user", "content": user_content},
    ]

    router_max_tokens = min(int(os.environ.get("GROQ_ROUTER_MAX_TOKENS", "300")), 350)
    used_model = model
    t_call_start = time.perf_counter()
    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=min(router_max_tokens, 280) if "qwen" in str(model).lower() else router_max_tokens,
                timeout=timeout,
            )
        except Exception as e_primary:
            err_str = str(e_primary)
            if "rate_limit" in err_str.lower() or "429" in err_str:
                _ROUTING_METRICS["phase_2_failovers_429"] += 1
                fallback_model = os.environ.get("GROQ_ROUTER_FALLBACK_MODEL", "qwen/qwen3.8-27b")
                fallback_key = (os.environ.get("SPEECH_API_KEY") or groq_key).strip()
                fallback_client = Groq(api_key=fallback_key)
                used_model = fallback_model
                logger.warning("[tiered_classifier] Model %s rate limited (429) — failing over to %s with key %s...", model, fallback_model, fallback_key[:8])

                # Enforce strict < 1000 limit for Qwen on Groq (250 tokens is more than enough for router JSON)
                qwen_max_tokens = min(router_max_tokens, 280)
                resp = fallback_client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=qwen_max_tokens,
                    timeout=timeout,
                )
            else:
                raise e_primary

        call_latency_ms = round((time.perf_counter() - t_call_start) * 1000, 2)
        raw_reply = resp.choices[0].message.content or "{}"
        _LAST_ROUTER_TELEMETRY.clear()
        _LAST_ROUTER_TELEMETRY.update({
            "model": used_model,
            "param_class": "120B" if "120b" in used_model.lower() else "27B",
            "endpoint": "https://api.groq.com/openai/v1/chat/completions",
            "delta_context_sent": delta_context,
            "user_content_sent": user_content,
            "groq_latency_ms": call_latency_ms,
            "raw_reply": raw_reply,
            "is_escalation": False,
        })
    except Exception as e:
        err_str = str(e)
        # Recover conversational reply if Groq threw json_validate_failed with plain text in failed_generation
        if "failed_generation" in err_str:
            import re
            m = re.search(r"['\"]failed_generation['\"]:\s*['\"](.*?)['\"](?:\s*[,}])", err_str, re.DOTALL)
            if m:
                recovered = m.group(1).encode("utf-8").decode("unicode_escape", errors="replace").strip()
                if recovered and not recovered.startswith("{"):
                    logger.info("[tiered_classifier] Rescued conversational reply from Groq failed_generation: %s", recovered[:60])
                    return {"mode": "conversation", "response": recovered, "end_session": False}
        logger.warning("[tiered_classifier] Groq router call error (%s) — failing closed to Claude", e)
        return {"escalate": True, "reason": f"groq_call_failed: {e}"}

    import llm_json
    parsed, info = llm_json.parse(raw_reply)
    if not isinstance(parsed, dict) or info.get("truncated"):
        logger.warning("[tiered_classifier] Groq reply unusable or truncated: %r", raw_reply[:200])
        return {"escalate": True, "reason": "unparseable_or_truncated_json"}

    return parsed


def normalize_action_step(act: Any) -> dict[str, str] | None:
    """Normalize action dictionary/string from LLM output into exact executor contract.
    
    Resolves key variations ('name' -> 'action', 'parameters'/'arguments' -> 'parameter'),
    flattens dict parameters into pipe-separated strings, and maps known LLM action aliases.
    """
    if not act:
        return None
    if isinstance(act, str):
        act_str = act.strip()
        if "|" in act_str:
            act_name, param = act_str.split("|", 1)
        else:
            act_name, param = act_str, ""
    elif isinstance(act, dict):
        act_name = act.get("action") or act.get("name") or act.get("cmd") or act.get("tool") or ""
        param = act.get("parameter")
        if param is None:
            param = act.get("parameters") or act.get("arguments") or act.get("args") or act.get("param") or act.get("value") or ""
    else:
        return None

    act_name = str(act_name).strip()

    # Parameter normalization: convert dict/list to string
    if isinstance(param, dict):
        if "site" in param and "query" in param:
            param = f"{param['site']}|{param['query']}"
        elif "app" in param:
            param = str(param["app"])
        elif "path" in param:
            param = str(param["path"])
        elif "text" in param:
            param = str(param["text"])
        elif "query" in param:
            param = str(param["query"])
        elif len(param) == 1:
            param = str(next(iter(param.values())))
        else:
            param = "|".join(str(v) for v in param.values())
    elif isinstance(param, (list, tuple)):
        param = "|".join(str(v) for v in param)
    elif param is None:
        param = ""
    else:
        param = str(param).strip()

    act_lower = act_name.lower()

    # Canonical alias resolution
    if act_lower in ("pause", "resume", "unpause", "next", "previous", "skip"):
        return {"action": "spotify_control", "parameter": act_lower}
    if act_lower == "close_window":
        return {"action": "close_application", "parameter": param}
    if act_lower == "click_element":
        return {"action": "click", "parameter": param}
    if act_lower == "fill_input":
        return {"action": "fill", "parameter": param}
    if act_lower in ("file_search", "folder_search"):
        return {"action": "search_file", "parameter": param}
    if act_lower in ("write_text", "type_text", "insert_text"):
        return {"action": "write_clipboard", "parameter": param}
    if act_lower in ("delete_folder", "delete_directory", "delete_file", "remove_file", "remove_folder", "delete_item"):
        return {"action": "delete_files", "parameter": param}
    if act_lower in ("organize_directory", "sort_folder", "organize_downloads"):
        return {"action": "organize_folder", "parameter": param}

    # Fix youtube parameter if formatted as "search|..." or "play|..."
    if act_lower == "youtube_control":
        if param.lower().startswith("search|"):
            param = "search " + param[7:].strip()
        elif param.lower().startswith("play|"):
            param = "play " + param[5:].strip()

    # Fix docs_control parameter if missing subaction
    if act_lower == "docs_control" and param:
        sub = param.split("|")[0].lower().strip()
        if sub not in ("create", "generate", "read", "append"):
            param = f"create|{param}"

    # Fix sheets_control parameter if missing subaction
    if act_lower == "sheets_control" and param:
        sub = param.split("|")[0].lower().strip()
        if sub not in ("create", "generate", "read", "write"):
            param = f"create|{param}"

    return {"action": act_name, "parameter": param}


def _validate_groq_envelope(parsed: dict[str, Any]) -> dict[str, Any]:
    """Validate Groq output against guard_rules.ACTION_RULES and action_guard rules.
    Fails closed (escalate=True) on any schema violation, arity mismatch, or safety failure.
    Preserves and normalizes both actions and pending_actions.
    """
    if parsed.get("escalate"):
        return parsed

    mode = parsed.get("mode", "command")
    if mode == "conversation":
        resp = str(parsed.get("response", "")).strip()
        if not resp:
            return {"escalate": True, "reason": "empty_conversation_response"}
        resp = _enforce_no_action_hallucinations(resp)
        return {"mode": "conversation", "response": resp, "end_session": bool(parsed.get("end_session", False))}

    # Check for conversational time request misclassified as command
    raw_single_act = parsed.get("action") or (parsed.get("actions", [{}])[0].get("action") if parsed.get("actions") and isinstance(parsed["actions"][0], dict) else "")
    if str(raw_single_act).strip().lower() == "get_current_time":
        import datetime as dt
        now_str = dt.datetime.now().strftime("%I:%M %p")
        return {"mode": "conversation", "response": f"It is currently {now_str}.", "end_session": False}

    # Extract and normalize actions
    raw_actions = parsed.get("actions", [])
    if not raw_actions and parsed.get("action"):
        raw_actions = [{"action": parsed["action"], "parameter": parsed.get("parameter", "")}]

    # Extract and normalize pending_actions
    raw_pending = parsed.get("pending_actions")
    if raw_pending is None and parsed.get("pending_action"):
        raw_pending = parsed["pending_action"]
    if raw_pending and not isinstance(raw_pending, list):
        raw_pending = [raw_pending]

    normalized_actions = []
    if isinstance(raw_actions, list):
        for a in raw_actions:
            norm = normalize_action_step(a)
            if norm:
                normalized_actions.append(norm)

    normalized_pending = []
    if isinstance(raw_pending, list):
        for a in raw_pending:
            norm = normalize_action_step(a)
            if norm:
                normalized_pending.append(norm)

    if not normalized_actions and not normalized_pending:
        return {"escalate": True, "reason": "no_actions_in_command_mode"}

    try:
        import guard_rules
        import action_guard
    except Exception as e:
        logger.error("[tiered_classifier] Guard modules unavailable: %s", e)
        return {"escalate": True, "reason": f"guard_import_failed: {e}"}

    validated_actions: list[dict[str, Any]] = []
    for idx, act in enumerate(normalized_actions):
        act_name = act["action"]
        param = act["parameter"]
        verdict = guard_rules.validate(act_name, param)
        if verdict.decision == guard_rules.BLOCK:
            logger.warning("[tiered_classifier] Action '%s' blocked by guard_rules: %s", act_name, verdict.reasons)
            return {"escalate": True, "reason": f"guard_rules_rejected_{act_name}: {verdict.reasons}"}
        validated_actions.append({"action": act_name, "parameter": param})

    validated_pending: list[dict[str, Any]] = []
    for idx, act in enumerate(normalized_pending):
        act_name = act["action"]
        param = act["parameter"]
        verdict = guard_rules.validate(act_name, param)
        if verdict.decision == guard_rules.BLOCK:
            logger.warning("[tiered_classifier] Pending action '%s' blocked by guard_rules: %s", act_name, verdict.reasons)
            return {"escalate": True, "reason": f"guard_rules_rejected_{act_name}: {verdict.reasons}"}
        validated_pending.append({"action": act_name, "parameter": param})

    # Generation-Time Chain Safety Enforcement
    if validated_actions:
        sanitized_steps, _ = action_guard.sanitize_actions(validated_actions)
        if len(sanitized_steps) != len(validated_actions):
            logger.warning("[tiered_classifier] Groq output violated action_guard chain rules — failing closed")
            return {"escalate": True, "reason": "action_guard_sanitized_out_actions: chain rule violation"}

    first_act = validated_actions[0]["action"] if validated_actions else (validated_pending[0]["action"] if validated_pending else "")
    first_param = validated_actions[0].get("parameter", "") if validated_actions else (validated_pending[0].get("parameter", "") if validated_pending else "")
    spoken = parsed.get("response") or f"Running {first_act}."

    result_env: dict[str, Any] = {
        "mode": "command",
        "action": first_act,
        "parameter": first_param,
        "actions": validated_actions,
        "response": spoken,
        "confirmation_required": bool(validated_pending or parsed.get("confirmation_required")),
        "end_session": bool(parsed.get("end_session", False)),
    }
    if validated_pending:
        result_env["pending_actions"] = validated_pending
        result_env["confirmation_message"] = parsed.get("confirmation_message") or spoken

    return result_env


def classify_and_synthesize(utterance: str, delta_context: str | None = None) -> dict[str, Any]:
    """Single direct routing and envelope synthesis function with safe compound-gated fast-path.
    
    1. Phase 1 (Local Regex Fast-Path):
       - If utterance is single-intent and non-compound (no 'and', 'then', commas, multiple verbs),
         matches atomic commands in <1ms with 0 Groq tokens.
    2. Phase 2 (Groq Direct Router):
       - Compound, chained, or ambiguous requests bypass regex completely to synthesize
         full multi-action envelopes via Groq (>=27B).
    """
    _ROUTING_METRICS["total_turns"] += 1
    cleaned = (utterance or "").strip()
    if not cleaned:
        return {"mode": "conversation", "response": "I didn't catch that. Could you repeat?", "end_session": False}

    # Phase 1: Safe Compound-Gated Local Fast-Path (Atomic only)
    if not _is_compound_utterance(cleaned):
        fast_env = _try_fast_path_regex(cleaned)
        if fast_env:
            _ROUTING_METRICS["phase_1_regex_hits"] += 1
            _LAST_ROUTER_TELEMETRY.clear()
            _LAST_ROUTER_TELEMETRY.update({
                "model": "local_regex_fast_path",
                "param_class": "0-token Reflex",
                "endpoint": "local_fast_path (<1ms)",
                "delta_context_sent": None,
                "user_content_sent": cleaned,
                "groq_latency_ms": 0.05,
                "raw_reply": json.dumps(fast_env),
                "is_escalation": False,
            })
            return _validate_groq_envelope(fast_env)

    # Phase 2: Groq Direct Router
    _ROUTING_METRICS["phase_2_groq_calls"] += 1
    groq_reply = _call_groq_router(cleaned, delta_context=delta_context)
    if not groq_reply:
        return {"escalate": True, "reason": "groq_router_empty_reply"}

    return _validate_groq_envelope(groq_reply)


def escalate_to_free_brain(utterance: str, delta_context: str | None = None, reason: str | None = None) -> dict[str, Any]:
    """Handles deep reasoning or escalated requests strictly using Groq's >= 27B free models.
    
    Ensures 100% free operation with $0 Anthropic costs when Claude escalation occurs.
    """
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not groq_key:
        return {
            "mode": "conversation",
            "response": "I couldn't process your request because GROQ_API_KEY is not configured.",
            "end_session": False,
        }

    # Primary high-parameter reasoning model (120B) or 27B fallback
    model = os.environ.get("GROQ_ESCALATION_MODEL", "openai/gpt-oss-120b")
    fallback_model = "qwen/qwen3.8-27b"

    sys_prompt = (
        "You are Akira, an intelligent desktop voice assistant on Windows. "
        "The user asked a question or conversational inquiry. "
        "Answer naturally, concisely, and helpfully in 1 to 2 spoken sentences. "
        "Do not use markdown, code blocks, bullet points, or asterisks. "
        "Respond STRICTLY in JSON format with keys: "
        '{"mode": "conversation", "response": "<natural spoken voice reply>", "end_session": false}.'
    )
    user_prompt = utterance.strip()
    if delta_context and delta_context.strip():
        user_prompt = f"{delta_context.strip()}\n\nUser request: {user_prompt}"

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    used_model = model
    t_call_start = time.perf_counter()
    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=min(300, 250 if "qwen" in str(model).lower() else 300),
                timeout=10.0,
            )
        except Exception as e_pri:
            if "rate_limit" in str(e_pri).lower() or "429" in str(e_pri):
                used_model = fallback_model
                fallback_key = (os.environ.get("SPEECH_API_KEY") or groq_key).strip()
                fallback_client = Groq(api_key=fallback_key)
                logger.warning("[tiered_classifier] Free escalation model %s rate limited, trying %s with secondary key", model, fallback_model)
                resp = fallback_client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.3,
                    max_tokens=250,
                    timeout=10.0,
                )
            else:
                raise e_pri

        call_latency_ms = round((time.perf_counter() - t_call_start) * 1000, 2)
        raw = resp.choices[0].message.content or "{}"
        _LAST_ROUTER_TELEMETRY.clear()
        _LAST_ROUTER_TELEMETRY.update({
            "model": used_model,
            "param_class": "120B" if "120b" in used_model.lower() else "27B",
            "endpoint": "https://api.groq.com/openai/v1/chat/completions",
            "delta_context_sent": delta_context,
            "user_content_sent": user_prompt,
            "groq_latency_ms": call_latency_ms,
            "raw_reply": raw,
            "is_escalation": True,
        })
        import llm_json
        parsed, _ = llm_json.parse(raw)
        if isinstance(parsed, dict) and "response" in parsed:
            parsed["response"] = _enforce_no_action_hallucinations(parsed["response"])
            return parsed
        return {"mode": "conversation", "response": _enforce_no_action_hallucinations(raw.strip()), "end_session": False}
    except Exception as e:
        logger.error("[tiered_classifier] Free brain escalation error: %s", e)
        return {
            "mode": "conversation",
            "response": "I'm having a brief issue reaching the free brain right now. Please try again.",
            "end_session": False,
        }



