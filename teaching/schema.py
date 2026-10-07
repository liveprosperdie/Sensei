"""The contract between the model layer and the UI layer.

Everything a model returns is passed through a validator here before it is
written to disk, and everything read back is shaped by these functions. Model
output is untrusted: it is clamped, normalised, and stripped of anything the
renderer could misinterpret.
"""

from __future__ import annotations

import re
import secrets
import unicodedata

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,63}$")
LESSON_ID_RE = re.compile(r"^lesson_\d{1,3}$")
SRC_ID_RE = re.compile(r"^src_\d{1,3}$")
TAG_RE = re.compile(r"[^a-z0-9]+")

LEVELS = ("beginner", "intermediate", "advanced")
FEEDBACK = ("too_basic", "about_right", "too_advanced")

# Only these relative paths may ever be read or written inside a topic dir.
ALLOWED_REL = (
    re.compile(r"^_topic_meta\.json$"),
    re.compile(r"^lesson_\d{1,3}\.md$"),
    re.compile(r"^lesson_\d{1,3}_quiz\.json$"),
    re.compile(r"^lesson_\d{1,3}_quiz_result\.json$"),
    re.compile(r"^lesson_\d{1,3}_feynman\.json$"),
    re.compile(r"^diagrams/lesson_\d{1,3}_fig\d{1,2}\.mmd$"),
    re.compile(r"^sources/src_\d{1,3}\.json$"),
)

_DIAGRAM_KINDS = (
    "graph", "flowchart", "sequencediagram", "classdiagram", "statediagram",
    "erdiagram", "mindmap", "timeline", "pie", "journey",
)
_DIAGRAM_BANNED = re.compile(
    r"(<\s*/?\s*(script|iframe|img|object|embed|style|link|svg|a)\b|javascript:|data:|"
    r"\bon\w+\s*=|%%\s*\{|^\s*click\b|\bhref\b|\bcallback\b|&#|\\u00)",
    re.IGNORECASE | re.MULTILINE,
)


def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s


def new_slug(topic: str) -> str:
    base = slugify(topic)[:40].strip("_") or "topic"
    return f"{base}_{secrets.token_hex(3)}"


def clean_text(value, maxlen: int) -> str:
    """Single-line, control-char-free, length-bounded string."""
    s = "" if value is None else str(value)
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen]


def norm_tag(value) -> str:
    t = TAG_RE.sub("-", str(value or "").lower()).strip("-")
    return t[:48] or "general"


def clamp_level(value, default="intermediate") -> str:
    v = str(value or "").lower().strip()
    return v if v in LEVELS else default


def is_allowed_rel(rel: str) -> bool:
    return any(p.match(rel) for p in ALLOWED_REL)


# ── Diagrams ────────────────────────────────────────────────────────────────

def sanitize_mermaid(code) -> str | None:
    """Return safe Mermaid source, or None if it must be rejected.

    The browser renders with securityLevel=strict as a second layer; this is the
    first. We reject rather than repair anything that could carry markup, links,
    callbacks or init directives.
    """
    if not isinstance(code, str):
        return None
    s = code.strip()
    s = re.sub(r"^```(?:mermaid)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s).strip()
    s = re.sub(r"<\s*br\s*/?\s*>", " ", s, flags=re.IGNORECASE)
    if not s or len(s) > 4000:
        return None
    first = s.splitlines()[0].strip().lower()
    if not any(first.startswith(k) for k in _DIAGRAM_KINDS):
        return None
    if _DIAGRAM_BANNED.search(s) or "<" in s.replace("<--", "").replace("<-", "").replace("<|", "").replace("<<", "").replace("<=", ""):
        return None
    return s


# ── Lesson markdown ─────────────────────────────────────────────────────────

_SRCREF_RE = re.compile(r"<!--\s*source-ref:\s*(\{.*?\})\s*-->", re.DOTALL)
_ANY_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_DIAGRAM_TOKEN_RE = re.compile(r"\{\{\s*diagram:\s*([^}|]*?)(?:\|([^}]*))?\}\}")


def extract_srcref_json(md: str) -> list[str]:
    return _SRCREF_RE.findall(md or "")


def strip_unknown_comments(md: str, keep_srcref: bool = True) -> str:
    def repl(m: re.Match) -> str:
        return m.group(0) if keep_srcref and _SRCREF_RE.fullmatch(m.group(0)) else ""
    return _ANY_COMMENT_RE.sub(repl, md or "")


_RAW_HTML_RE = re.compile(
    r"(`[^`\n]*`)|<\s*(script|style|iframe|object|embed)\b.*?<\s*/\s*\2\s*>|</?[a-zA-Z][^>\n]*>",
    re.DOTALL | re.IGNORECASE)


def strip_raw_html(md: str) -> str:
    """Remove raw HTML tags from lesson Markdown, leaving fenced/inline code alone.

    The UI never interprets HTML (it builds DOM nodes), so this is belt-and-braces:
    stored lesson files stay clean even if opened in some other viewer.
    """
    parts = re.split(r"(```.*?```)", md or "", flags=re.DOTALL)
    for i in range(0, len(parts), 2):
        parts[i] = _RAW_HTML_RE.sub(lambda m: m.group(1) or "", parts[i])
    return "".join(parts)


# ── Plan (syllabus) ─────────────────────────────────────────────────────────

def validate_plan(raw: dict, topic: str) -> dict:
    """Normalise the HEAD's roadmap into the shape the pipeline relies on."""
    if not isinstance(raw, dict):
        raise ValueError("plan is not an object")
    lessons_in = raw.get("lessons")
    if not isinstance(lessons_in, list) or len(lessons_in) < 3:
        raise ValueError("plan needs at least 3 lessons")
    lessons = []
    for item in lessons_in[:10]:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"), 90)
        if not title:
            continue
        concepts = [norm_tag(c) for c in (item.get("key_concepts") or [])[:6]]
        lessons.append({
            "title": title,
            "summary": clean_text(item.get("summary"), 320),
            "key_concepts": [c for c in concepts if c] or [norm_tag(title)],
        })
    if len(lessons) < 3:
        raise ValueError("plan has too few valid lessons")

    sources = []
    for s in (raw.get("reliable_sources") or [])[:8]:
        if not isinstance(s, dict):
            continue
        name = clean_text(s.get("name"), 120)
        if not name:
            continue
        sources.append({
            "name": name,
            "type": clean_text(s.get("type"), 24) or "reference",
            "url_or_ref": clean_text(s.get("url_or_ref"), 300),
            "why": clean_text(s.get("why"), 200),
        })
    return {
        "assumed_level": clamp_level(raw.get("assumed_level")),
        "audience_note": clean_text(raw.get("audience_note"), 240),
        "reliable_sources": sources,
        "lessons": lessons,
        "topic": clean_text(raw.get("topic") or topic, 100) or topic,
    }


# ── Quiz ────────────────────────────────────────────────────────────────────

def validate_quiz(raw: dict, key_concepts: list[str]) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("questions"), list):
        raise ValueError("quiz has no questions")
    out = []
    for i, q in enumerate(raw["questions"][:8], start=1):
        if not isinstance(q, dict):
            continue
        opts_in = q.get("options") or []
        if not isinstance(opts_in, list) or len(opts_in) < 3:
            continue
        opts, ids = [], []
        for j, o in enumerate(opts_in[:5]):
            text = o.get("text") if isinstance(o, dict) else o
            oid = "abcde"[j]
            opts.append({"id": oid, "text": clean_text(text, 240)})
            ids.append(oid)
        correct = q.get("correct_option_id")
        if isinstance(correct, str) and correct.lower() in ids:
            correct = correct.lower()
        elif isinstance(correct, int) and 0 <= correct < len(ids):
            correct = ids[correct]
        else:
            continue
        prompt = clean_text(q.get("prompt"), 320)
        if not prompt or any(not o["text"] for o in opts):
            continue
        tag = norm_tag(q.get("concept_tag") or (key_concepts[0] if key_concepts else "general"))
        out.append({
            "id": f"q{len(out) + 1}",
            "prompt": prompt,
            "options": opts,
            "correct_option_id": correct,
            "explanation": clean_text(q.get("explanation"), 500),
            "concept_tag": tag,
        })
    if len(out) < 3:
        raise ValueError("quiz had fewer than 3 valid questions")
    return {"questions": out}


def public_quiz(quiz: dict) -> dict:
    """Quiz as sent to the browser BEFORE submission: no answers, no explanations."""
    return {"questions": [
        {"id": q["id"], "prompt": q["prompt"], "options": q["options"],
         "concept_tag": q["concept_tag"]}
        for q in quiz.get("questions", [])
    ]}
