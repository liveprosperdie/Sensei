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

# LITERARY FRAMING, not subject matter. Generated headings are written to read
# well ("The Biological Engine", "The Framework of Life: The Skeletal System"),
# and searching those words is what returned museum photos and unrelated
# diagrams: no image is tagged "framework of life". These are dropped from
# QUERIES ONLY — the display heading in the document is never touched.
_FLOWERY = {
    "engine", "framework", "foundation", "foundations", "blueprint",
    "blueprints", "symphony", "journey", "gateway", "essence", "marvel",
    "marvels", "miracle", "miracles", "wonder", "wonders", "tapestry",
    "cornerstone", "machinery", "powerhouse", "orchestra", "dance",
    "story", "stories", "tale", "tales", "secret", "secrets", "mystery",
    "mysteries", "world", "life", "future", "power", "beauty", "role",
    "roles", "importance", "impact", "understanding", "exploring",
    "exploration", "unveiling", "unlocking", "guide", "basics",
    "fundamentals", "primer", "art", "science", "rise", "dawn", "age",
    "era", "key", "keys", "heart",   # "the heart of the matter", not the organ
    "machine", "machines", "engines", "intricate", "hidden", "silent",
    "great", "grand", "vital", "inner", "deeper", "beyond", "within",
}
# NOTE: adjectives like "green", "biological", or "natural" are deliberately
# NOT in _FLOWERY — they are real subject words elsewhere ("green sea turtle",
# "biological cell"). A heading made only of framing plus one such adjective is
# handled by the `thin` check in query_candidates instead, which falls back to
# the document subject rather than searching the adjective on its own.

# Words describing the WRITING TASK rather than its subject. Stripped when the
# brief ("write a detailed report about the human body") becomes the subject.
_TASK_WORDS = {
    "write", "writing", "written", "create", "creating", "make", "making",
    "draft", "generate", "report", "reports", "essay", "essays", "document",
    "documents", "doc", "paper", "papers", "article", "articles", "piece",
    "page", "pages", "word", "words", "brief", "detailed", "short", "long",
    "full", "quick", "covering", "cover", "covers", "including", "include",
    "includes", "explain", "explaining", "describe", "describing",
    "discuss", "discussing", "please", "me", "my", "it", "some", "few",
}

_SPLIT_RE = re.compile(r"\s*(?::|\u2014|\u2013|(?<=\s)-(?=\s))\s*")

_plan: dict | None = None


# ── Query derivation ─────────────────────────────────────────────────────────

def clean_heading(heading: str) -> str:
    """A heading as a searchable phrase: no numbering, no trailing punctuation."""
    h = (heading or "").strip()
    h = re.sub(r"^\s*(?:\d+[.)]|[-•*])\s*", "", h)          # "1. ", "- "
    h = re.sub(r"\s+", " ", h).strip(" .:;,-–—")
    return h


def _words(text: str, drop: set[str]) -> list[str]:
    return [w for w in re.findall(r"[a-z][\w'-]*", (text or "").lower())
            if w not in _STOP and w not in drop]


def derive_subject(brief: str, doc_title: str = "") -> str:
    """The real-world SUBJECT of the document, as image-search words.

    Taken from the brief the user actually spoke ("a report on the human
    body"), because the generated display title is written for prose, not for
    search. Falls back to the title only when the brief says nothing concrete.
    """
    words = _words(brief, _TASK_WORDS | _FLOWERY)
    if len(words) < 1:
        words = _words(doc_title, _TASK_WORDS | _FLOWERY)
    return " ".join(words[:3])


def section_keywords(heading: str) -> str:
    """The concrete topic inside a section heading, minus literary framing.

    'The Framework of Life: The Skeletal System' -> 'skeletal system'
    'The Biological Engine'                      -> 'biological' (thin, so the
    caller leans on the subject instead).
    """
    best: list[str] = []
    for segment in _SPLIT_RE.split(clean_heading(heading)):
        words = _words(segment, _FLOWERY)
        if len(words) >= len(best):          # ties favour the LATER segment,
            best = words                     # which is the concrete one
    return " ".join(best[:3])


def _join(*parts: str) -> str:
    """Join query fragments, dropping repeats — 'volcanoes' + 'types volcanoes'
    must not become 'volcanoes types volcanoes', which reads as a worse query
    to every provider's relevance ranking."""
    out: list[str] = []
    for word in " ".join(p for p in parts if p).split():
        if word not in out:
            out.append(word)
    return " ".join(out)


def query_candidates(heading: str, subject: str = "",
                     doc_title: str = "") -> list[str]:
    """Progressively broader queries for one section, ANCHORED ON THE SUBJECT.

    Ordering matters: the first query must already be a real-world phrase an
    image is plausibly tagged with, so a standard topic never has to broaden.
    Callers try these in order and stop at the first search that succeeds.
    """
    subject = (subject or "").strip() or derive_subject("", doc_title)
    keys = section_keywords(heading)
    thin = len(keys.split()) < 2          # heading was pure framing language

    out: list[str] = []
    for q in (_join(subject, keys) if not thin else "",
              keys if not thin else "",
              subject,
              _join(subject, keys),
              keys):
        q = " ".join((q or "").split())
        if q and q.lower() not in {o.lower() for o in out}:
            out.append(q)
    return out


# ── Queue ────────────────────────────────────────────────────────────────────

def begin(app: str, doc_title: str, headings: list[str], brief: str = "") -> int:
    """Start a fresh image pass over `headings`. Returns the section count.
    `brief` is the user's own description of the topic — the anchor for every
    search query. Always replaces any previous plan.
    """
    global _plan
    sections = [clean_heading(h) for h in (headings or []) if clean_heading(h)]
    if not sections:
        _plan = None
        return 0
    subject = derive_subject(brief, doc_title)
    _plan = {"app": app, "doc_title": doc_title or "", "sections": sections,
             "index": 0, "subject": subject}
    print(f"[doc_image_plan] started for {app}: {len(sections)} sections, "
          f"subject={subject!r}")
    return len(sections)


def is_active(app: str | None = None) -> bool:
    if _plan is None:
        return False
    return app is None or _plan["app"] == app


def current() -> dict | None:
    """{'heading', 'index' (1-based), 'total', 'doc_title', 'subject'} or None."""
    if _plan is None:
        return None
    i = _plan["index"]
    if i >= len(_plan["sections"]):
        return None
    return {"heading": _plan["sections"][i], "index": i + 1,
            "total": len(_plan["sections"]), "doc_title": _plan["doc_title"],
            "subject": _plan["subject"]}


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