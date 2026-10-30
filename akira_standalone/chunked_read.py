"""Bounded read-aloud with an explicit continue/stop ask.

WHAT THIS IS FOR — read this before using it anywhere.

This module governs ONE thing: how much content gets SPOKEN to the user in a
single turn. Akira must never dump an entire file or note at the user in one
breath. She reads a bounded chunk, then asks whether to keep going.

WHAT THIS IS **NOT** FOR — do not wire it into these paths:
  - summarize_file / summarize_text        (needs the whole text to summarize)
  - file_to_doc                            (needs the whole text to transcribe)
  - plan_organization / _do_organize       (FM-1 must reason over the FULL dump)
  - _extract_document_text                 (the shared extraction primitive)
  - any search / index / context-building pass

Those are INTERNAL INGESTION. Akira is allowed — and required — to read as much
as she likes internally; a reading-aloud safeguard must never starve a
reasoning pass of its input. The two concerns are deliberately separate:

    INTERNAL INGESTION   unbounded (whatever the task needs)   silent
    SPOKEN OUTPUT        bounded by SPOKEN_CHUNK_CHARS         audible

If you find yourself importing this module into something that does not
directly produce speech, you are almost certainly in the wrong place.

State is process-global and single-session by design: Akira talks to one person
at a time, and a second read replaces the first rather than queueing.
"""

from __future__ import annotations

import threading

# One spoken chunk. Tuned for the ear, not the page: ~900 chars is roughly a
# 45-60 second read, which is about as long as a person tolerates before
# wanting a say. Raise this and Akira starts monologuing again.
SPOKEN_CHUNK_CHARS = 900

# Never break mid-word/mid-sentence if a natural boundary exists within this
# much of the target — a chunk that ends on a paragraph break sounds finished,
# a chunk that ends mid-clause sounds broken.
_BOUNDARY_WINDOW = 300

_lock = threading.Lock()
_state: dict | None = None   # {"label", "text", "cursor", "part"}


def _find_boundary(text: str, start: int, hard_end: int) -> int:
    """Best place to stop speaking, searching backwards from hard_end.

    Preference order: paragraph break, markdown heading, sentence end, word
    break. Returns hard_end unchanged if nothing better exists.
    """
    if hard_end >= len(text):
        return len(text)
    window_floor = max(start + 1, hard_end - _BOUNDARY_WINDOW)
    segment = text[window_floor:hard_end]

    para = segment.rfind("\n\n")
    if para != -1:
        return window_floor + para + 2

    heading = segment.rfind("\n#")
    if heading != -1:
        return window_floor + heading + 1

    best = -1
    for mark in (". ", ".\n", "! ", "? ", "; "):
        best = max(best, segment.rfind(mark))
    if best != -1:
        return window_floor + best + 1

    space = segment.rfind(" ")
    return window_floor + space + 1 if space != -1 else hard_end


def _emit() -> dict:
    """Cut the next chunk from the active read and describe it. Caller speaks."""
    assert _state is not None
    text, cursor = _state["text"], _state["cursor"]
    end = _find_boundary(text, cursor, cursor + SPOKEN_CHUNK_CHARS)
    chunk = text[cursor:end].strip()
    _state["cursor"] = end
    _state["part"] += 1

    remaining = len(text) - end
    has_more = remaining > 0
    part = _state["part"]
    label = _state["label"]

    if has_more:
        # An explicit ask, every single time. Never assume consent to continue.
        total_parts = max(2, -(-len(text) // SPOKEN_CHUNK_CHARS))
        header = (f"{label}, part {part} of about {total_parts}."
                  if part == 1 else f"Part {part}.")
        tail = "Want me to keep reading, or stop there?"
        message = f"{header} {chunk} ... {tail}"
    else:
        header = f"{label}." if part == 1 else f"Last part."
        message = f"{header} {chunk} That's the end of it."
        _clear_locked()

    print(f"[chunked_read] part={part} chars={len(chunk)} remaining={remaining}")
    return {"message": message, "has_more": has_more, "part": part}


def _clear_locked() -> None:
    global _state
    _state = None


def prime(label: str, full_text: str) -> None:
    """Stage `full_text` in chunked_read state at cursor 0 without emitting yet.

    Used when an action summarizes the content first and asks if the user wants
    to hear it in detail. When the user follows up with 'yes' / 'read in detail',
    the next call to more() will emit part 1.
    """
    global _state
    text = (full_text or "").strip()
    if not text:
        return
    with _lock:
        _state = {"label": label.strip() or "That", "text": text,
                  "cursor": 0, "part": 0}


def begin(label: str, full_text: str) -> dict:
    """Start reading `full_text` aloud in chunks. Returns the first chunk.

    `full_text` should be the COMPLETE content — this module does the bounding,
    so callers must not pre-truncate. That keeps "how much exists" accurate in
    the spoken progress count.
    """
    global _state
    text = (full_text or "").strip()
    if not text:
        return {"message": f"{label} is empty.", "has_more": False, "part": 0}
    with _lock:
        _state = {"label": label.strip() or "That", "text": text,
                  "cursor": 0, "part": 0}
        return _emit()


def more() -> dict | None:
    """Continue the active read. None means there is nothing in progress."""
    with _lock:
        if _state is None:
            return None
        return _emit()


def stop() -> bool:
    """Abandon the active read. True if one was actually in progress."""
    with _lock:
        was_active = _state is not None
        _clear_locked()
    return was_active


def active() -> bool:
    with _lock:
        return _state is not None


def status() -> str:
    """One line for the prompt/context so the model knows a read is paused."""
    with _lock:
        if _state is None:
            return ""
        done, total = _state["cursor"], len(_state["text"])
        return (f"paused part-way through reading {_state['label']} "
                f"({done} of {total} characters read)")
