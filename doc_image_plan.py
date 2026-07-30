"""
doc_image_plan.py — the batch image pass that runs after document generation.

WHY THIS EXISTS: generated documents used to come out as walls of text unless
the user thought to ask for pictures, and asking "want me to look for images?"
per section turned one request into a negotiation. So the image pass is now
MANDATORY and BATCHED: all text is generated first, then every section is
walked once, in order, with the SAME search_image -> local numbered picker ->
strict pick pipeline that image_flow already owns. Nothing here searches or
downloads anything itself — this module is only the ordered queue plus the
query derivation, so there is exactly one image pipeline in the codebase.

State is module-level and single-slot on purpose: a voice session has one user
and one active document, exactly like image_flow's candidate list.

Pure module — no COM, no network, no Windows imports. Testable anywhere.
"""

from __future__ import annotations

import re

# Words that carry no visual meaning in an image query.
_STOP = {
    "a", "an", "and", "the", "of", "to", "for", "in", "on", "with", "its",
    "their", "your", "our", "this", "that", "these", "those", "or", "as",
    "at", "by", "from", "into", "about", "overview", "introduction",
    "conclusion", "summary", "background", "section", "part", "chapter",
}

_plan: dict | None = None


# ── Query derivation ─────────────────────────────────────────────────────────

def clean_heading(heading: str) -> str:
    """A heading as a searchable phrase: no numbering, no trailing punctuation."""
    h = (heading or "").strip()
    h = re.sub(r"^\s*(?:\d+[.)]|[-•*])\s*", "", h)          # "1. ", "- "
    h = re.sub(r"\s+", " ", h).strip(" .:;,-–—")
    return h


def _significant(text: str, limit: int) -> str:
    words = [w for w in re.findall(r"[\w'-]+", text.lower()) if w not in _STOP]
    return " ".join(words[:limit])


def query_candidates(heading: str, doc_title: str = "") -> list[str]:
    """Progressively BROADER queries for one section.

    The live failure this fixes: an over-specific heading ("Comparative
    Anatomy Atlas Of The Human Forelimb") returns nothing usable, and the
    correct response is a broader query, never "I couldn't find anything".
    Callers try these in order and stop at the first search that succeeds.
    """
    out: list[str] = []
    head = clean_heading(heading)
    title = clean_heading(doc_title)
    for q in (head,
              _significant(head, 2),
              (f"{_significant(title, 2)} {_significant(head, 1)}".strip()
               if title else ""),
              _significant(title, 2)):
        q = (q or "").strip()
        if q and q.lower() not in {o.lower() for o in out}:
            out.append(q)
    return out


# ── Queue ────────────────────────────────────────────────────────────────────

def begin(app: str, doc_title: str, headings: list[str]) -> int:
    """Start a fresh image pass over `headings`. Returns the section count.
    Always replaces any previous plan — a new generate supersedes an old pass.
    """
    global _plan
    sections = [clean_heading(h) for h in (headings or []) if clean_heading(h)]
    if not sections:
        _plan = None
        return 0
    _plan = {"app": app, "doc_title": doc_title or "", "sections": sections,
             "index": 0}
    print(f"[doc_image_plan] started for {app}: {len(sections)} sections")
    return len(sections)


def is_active(app: str | None = None) -> bool:
    if _plan is None:
        return False
    return app is None or _plan["app"] == app


def current() -> dict | None:
    """{'heading', 'index' (1-based), 'total', 'doc_title'} or None."""
    if _plan is None:
        return None
    i = _plan["index"]
    if i >= len(_plan["sections"]):
        return None
    return {"heading": _plan["sections"][i], "index": i + 1,
            "total": len(_plan["sections"]), "doc_title": _plan["doc_title"]}


def advance() -> dict | None:
    """Move to the next section. Returns it, or None when the pass is done
    (which also clears the plan, so a later insert image is a plain insert)."""
    global _plan
    if _plan is None:
        return None
    _plan["index"] += 1
    nxt = current()
    if nxt is None:
        print("[doc_image_plan] pass complete")
        _plan = None
    return nxt


def clear() -> None:
    global _plan
    if _plan is not None:
        print("[doc_image_plan] cleared")
    _plan = None
