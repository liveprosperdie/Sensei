"""Focus-session state for Obsidian: what note is in play, what was mentioned.

Two jobs:

1. SESSION CONTEXT — one line appended to akira._build_session_context() at
   session start telling Akira which note is open in Obsidian. The original
   plan had no way to know this and proposed asking the user for their focus
   note up front; GET /active/ just answers it, so the question is unnecessary
   in the common case.

2. NOTE RESOLUTION — turning "add this to my notes" into a concrete vault path
   via the plan's decision tree (explicit -> implicit -> ambiguous), and
   reporting AMBIGUOUS rather than guessing, so akira can ask.

Deliberately cheap: /active/ is one localhost request and it is only made at
session start, never per-turn, so it cannot add latency to a rapid exchange.
Everything degrades to "no Obsidian context" silently — a user without the
plugin must never see an error just for starting a session.
"""

import re
import threading

# ── session state ────────────────────────────────────────────────────────────

_lock = threading.Lock()

# The note the user is working in, as a vault path. Seeded from /active/ at
# session start, overwritten whenever the user names a note explicitly.
focus_note: str | None = None

# Note titles the user has referenced aloud this session, most recent last.
mentioned_notes: list[str] = []

# Message timestamps, for the flow-rate heuristic that suppresses clarifying
# questions during a rapid back-and-forth.
_turn_times: list[float] = []

_MAX_MENTIONED = 8

# ── focus-mode switch ────────────────────────────────────────────────────────
# THE single source of truth for "is Akira in Focus Mode right now". Read by
# claude_handler.system_blocks() to decide whether the FOCUS MODE prompt block
# is sent at all, and by obsidian_control for focus-only sub-actions. Anything
# else that needs the mode must call is_focus_mode() — never keep its own flag.
_focus_mode = False


def is_focus_mode() -> bool:
    with _lock:
        return _focus_mode


def set_focus_mode(active: bool) -> bool:
    """Turn Focus Mode on/off. Returns the resulting state."""
    global _focus_mode
    with _lock:
        _focus_mode = bool(active)
        state = _focus_mode
    print(f"[obsidian_context] focus_mode={'on' if state else 'off'}")
    return state


def reset() -> None:
    """Clear all session state. Called when a focus session ends."""
    global focus_note, _focus_mode
    with _lock:
        focus_note = None
        _focus_mode = False
        mentioned_notes.clear()
        _turn_times.clear()


def set_focus_note(path: str | None) -> None:
    global focus_note
    with _lock:
        focus_note = path or None


def note_mentioned(title: str) -> None:
    """Record that a note was referenced, newest last, de-duplicated."""
    title = (title or "").strip()
    if not title:
        return
    with _lock:
        if title in mentioned_notes:
            mentioned_notes.remove(title)
        mentioned_notes.append(title)
        del mentioned_notes[:-_MAX_MENTIONED]


def record_turn(now: float) -> None:
    with _lock:
        _turn_times.append(now)
        del _turn_times[:-6]


def flow_rate() -> float:
    """Turns per minute over the recent window. 0.0 when there is no history.

    Used to decide whether interrupting with a clarifying question is worth it:
    a fast exchange means the user is in flow and a non-critical question costs
    more than a reasonable guess.
    """
    with _lock:
        times = list(_turn_times)
    if len(times) < 2:
        return 0.0
    span = times[-1] - times[0]
    if span <= 0:
        return 0.0
    return (len(times) - 1) / (span / 60.0)


# ── session-start context line ───────────────────────────────────────────────

def session_line() -> str:
    """One-line Obsidian context for injection at session start, or "".

    Never raises and never blocks longer than the API timeout — a missing
    plugin, a closed Obsidian, or a missing key all yield "".
    """
    try:
        import obsidian_api
        if not obsidian_api.is_configured():
            return ""
        import obsidian_control
        res = obsidian_control.active_note()
    except Exception as e:
        print(f"[obsidian_context] session_line skipped: {e}")
        return ""

    if not res.get("success"):
        return ""
    path = res.get("path") or ""
    set_focus_note(path)
    title = path.rsplit("/", 1)[-1]
    if title.lower().endswith(".md"):
        title = title[:-3]
    note_mentioned(title)
    return f"Obsidian note open: {title}"


# ── note resolution ──────────────────────────────────────────────────────────

# "the X note", "my X note", "note called X", "in X"
_EXPLICIT_PATTERNS = (
    re.compile(r"note\s+(?:called|named|titled)\s+([\w \-']{2,60})", re.I),
    re.compile(r"(?:the|my)\s+([\w \-']{2,60}?)\s+note\b", re.I),
    re.compile(r"\[\[([^\]]{1,80})\]\]"),
)

# Phrases that mean "the note I'm already in" rather than naming one.
_IMPLICIT_PHRASES = (
    "my notes", "the note", "this note", "my note", "notes",
    "track progress", "progress", "the doc",
)

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
NONE = "none"


def extract_note_reference(text: str) -> str | None:
    """Pull an explicitly named note out of an utterance, or None."""
    for pat in _EXPLICIT_PATTERNS:
        m = pat.search(text or "")
        if m:
            name = m.group(1).strip()
            # "the note" / "my notes" match the second pattern with junk groups
            if name and name.lower() not in ("the", "my", "this", "that"):
                return name
    return None


def resolve_note(text: str) -> dict:
    """Resolve which note an utterance is about.

    Returns one of:
      {"status": RESOLVED,   "path": str,  "title": str}
      {"status": AMBIGUOUS,  "candidates": [{"title","path"}, ...]}
      {"status": NONE}

    Implements the plan's decision tree in order: an explicitly named note wins
    and is searched for; failing that, the session's focus note is used; only a
    genuine multi-way tie reports AMBIGUOUS so the caller can ask.
    """
    try:
        import obsidian_control
    except Exception:
        return {"status": NONE}

    named = extract_note_reference(text)

    if named:
        hits = obsidian_control.search_notes(named, limit=3)
        if len(hits) == 1:
            note_mentioned(hits[0]["title"])
            return {"status": RESOLVED, "path": hits[0]["path"],
                    "title": hits[0]["title"]}
        if len(hits) > 1:
            # a clear score leader is not really ambiguous
            top, second = hits[0], hits[1]
            if (top.get("score") or 0) >= 2 * (second.get("score") or 0):
                note_mentioned(top["title"])
                return {"status": RESOLVED, "path": top["path"],
                        "title": top["title"]}
            return {"status": AMBIGUOUS, "candidates": hits}
        return {"status": NONE}

    lowered = (text or "").lower()
    if any(p in lowered for p in _IMPLICIT_PHRASES):
        with _lock:
            current = focus_note
        if current:
            title = current.rsplit("/", 1)[-1]
            if title.lower().endswith(".md"):
                title = title[:-3]
            return {"status": RESOLVED, "path": current, "title": title}

    return {"status": NONE}


def clarifying_question(candidates: list[dict]) -> str:
    """Spoken question for an AMBIGUOUS resolution."""
    names = [c["title"] for c in candidates[:3]]
    if len(names) == 2:
        return f"Which note did you mean — {names[0]} or {names[1]}?"
    listed = ", ".join(names[:-1]) + f", or {names[-1]}"
    return f"Which note did you mean — {listed}?"


def should_ask_clarification(candidates: list[dict]) -> bool:
    """Ask only when it genuinely helps: real ambiguity, and not mid-flow.

    The flow-rate gate exists because Focus Mode's whole point is not breaking
    focus. Above ~4 turns/minute the user is mid-thought, and a question costs
    more than resolving to the best-scoring candidate.
    """
    if len(candidates) < 2:
        return False
    return flow_rate() < 4.0