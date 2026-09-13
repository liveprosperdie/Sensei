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

    # 9. Netflix commands (confident pattern match; ambiguity registry forces escalation)
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
            cmd_verbs = ("open ", "close ", "turn ", "set ", "play ", "pause ", "search ", "find ", "delete ", "copy ", "move ", "mute", "unmute", "spotify", "youtube")
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
        cmd_verbs = ("open ", "close ", "turn ", "set ", "play ", "pause ", "search ", "find ", "delete ", "copy ", "move ")
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
