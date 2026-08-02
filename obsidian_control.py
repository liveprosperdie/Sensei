"""Obsidian dispatcher — voice-driven note updates in Focus Mode.

Action format (mirrors docs_control / office_control):
  search|<query>                      Find notes matching a term
  read|<note>                         Read a note's content
  read|<note>|<section>               Read just one heading's content
  active                              Which note is open in Obsidian right now
  append|<note>|<section>|<text>      Add text under a heading (creates it if absent)
  progress|<note>|<text>              Timestamped entry under "Progress Log"
  create|<title>|<content>            New note (REFUSES to overwrite an existing one)
  link|<note>|<target1>,<target2>     Add wikilinks under "Related"
  moc|<title>|<note1>,<note2>,...     Build a Map of Content index note
  diagram|<note>|<mermaid source>     Embed a mermaid code block
  tags                                List vault tags with counts
  open|<note>                         Open a note in the Obsidian UI

DELIBERATELY ABSENT — do not add without a code-level confirmation gate:
  delete / trash of any kind, whole-file overwrite of an existing note, and
  Obsidian command-palette execution. The plugin's API offers all three
  (DELETE /vault/, PUT over an existing path, POST /commands/{id}/). None are
  wired here. That is the same principle as google_mcp.DENYLIST: an action
  that is "just not wired" must instead hit a wall, so the reasoning lives
  here in code rather than in prompt text. `create` verifies absence before
  writing, and every other write is ADDITIVE via PATCH.

Writes go through the plugin's Markdown Patch engine (PATCH /vault/{path}),
never read-modify-write. One request, server-side heading resolution, no local
Markdown parsing, and no lost update if the user is editing the same note in
Obsidian at the same time.
"""

import datetime as dt

import obsidian_api

# Where a bare "track progress" lands when the caller names no section.
DEFAULT_SECTION = "Progress Log"

_MAX_SEARCH_RESULTS = 5


# ── helpers ──────────────────────────────────────────────────────────────────

def _heading_target(section: str) -> list[str]:
    """"Progress Log" -> ["Progress Log"]; "Work/Meetings" -> nested address.

    The plugin addresses a heading as the list of heading texts from the top
    level down, so a nested section is a multi-element array, not a string.
    """
    return [s.strip() for s in (section or "").split("/") if s.strip()]


def _note_title(path: str) -> str:
    """"folder/2026-08 Project Alpha.md" -> "2026-08 Project Alpha"."""
    name = (path or "").rsplit("/", 1)[-1]
    return name[:-3] if name.lower().endswith(".md") else name


def _wikilinks(raw: str) -> list[str]:
    """Parse a comma-separated list of note names into [[wikilink]] form."""
    out = []
    for item in (raw or "").split(","):
        item = item.strip().strip("[]").strip()
        if item:
            out.append(f"[[{_note_title(item)}]]")
    return out


def _timestamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _patch_append(note: str, section: str, content: str) -> dict:
    """Append `content` under `section`, creating the heading if it is missing.

    createTargetIfMissing is a JSON instruction FIELD (verified in the 5.0.3
    OpenAPI schema) — not the Create-Target-If-Missing header, which belongs to
    raw-content mode. Sending the header form alongside a JSON body is rejected.
    """
    return obsidian_api.request(
        "PATCH", obsidian_api.vault_path(note),
        json_body={
            "targetType": "heading",
            "target": _heading_target(section),
            "operation": "append",
            "content": content,
            "createTargetIfMissing": True,
        })


def _note_exists(note: str) -> bool:
    return obsidian_api.request("GET", obsidian_api.vault_path(note))["success"]


# ── sub-actions ──────────────────────────────────────────────────────────────

def search_notes(query: str, limit: int = _MAX_SEARCH_RESULTS) -> list[dict]:
    """Fuzzy vault search -> [{"title","path","score"}], best first.

    Uses POST /search/simple/?query= (Obsidian's own fuzzy search). The
    GET /vault/search?query= endpoint the original plan cited does not exist.
    """
    res = obsidian_api.request("POST", "/search/simple/",
                               params={"query": query, "contextLength": 100})
    if not res["success"]:
        return []
    rows = res.get("json") or []
    if not isinstance(rows, list):
        return []
    rows.sort(key=lambda r: r.get("score") or 0, reverse=True)
    return [{"title": _note_title(r.get("filename", "")),
             "path": r.get("filename", ""),
             "score": r.get("score")}
            for r in rows[:limit] if r.get("filename")]


def active_note() -> dict:
    """The note currently open in Obsidian: {"success","message","path"}.

    This is the single most useful thing the plan was missing — it answers
    "which note is the user looking at" directly instead of guessing from
    conversation or asking the user up front.
    """
    res = obsidian_api.request(
        "GET", "/active/",
        headers={"Accept": "application/vnd.olrapi.note+json"})
    if not res["success"]:
        return {"success": False,
                "message": "No note is open in Obsidian right now."}
    body = res.get("json") or {}
    path = body.get("path") or ""
    if not path:
        return {"success": False,
                "message": "No note is open in Obsidian right now."}
    return {"success": True, "path": path,
            "message": f"The open note is {_note_title(path)}.",
            "content": body.get("content", "")}


def _do_search(query: str) -> dict:
    if not query:
        return {"success": False, "message": "What should I search your notes for?"}
    hits = search_notes(query)
    if not hits:
        return {"success": True, "speak": True,
                "message": f"I couldn't find any notes matching '{query}'."}
    names = ", ".join(h["title"] for h in hits)
    return {"success": True, "speak": True,
            "message": f"Found {len(hits)} matching {'note' if len(hits) == 1 else 'notes'}: {names}."}


def _do_read(note: str, section: str | None) -> dict:
    if not note:
        return {"success": False, "message": "Which note should I read?"}
    if section:
        res = obsidian_api.request("GET", obsidian_api.heading_path(note, section))
    else:
        res = obsidian_api.request("GET", obsidian_api.vault_path(note))
    if not res["success"]:
        # a spoken note name rarely matches the exact filename — resolve it
        hits = search_notes(note, limit=1)
        if not hits:
            return res
        res = obsidian_api.request("GET", obsidian_api.vault_path(hits[0]["path"]))
        if not res["success"]:
            return res
    # raw markdown is not directly speakable — let the LLM synthesize it
    res["speak_summary"] = True
    return res


def _do_append(note: str, section: str, text: str, *, timestamped: bool) -> dict:
    if not note or not text:
        return {"success": False,
                "message": "I need both a note and the text to add."}
    section = section or DEFAULT_SECTION
    body = f"### {_timestamp()}\n\n{text}" if timestamped else text
    res = _patch_append(note, section, body)
    if not res["success"]:
        hits = search_notes(note, limit=1)
        if hits and hits[0]["path"]:
            res = _patch_append(hits[0]["path"], section, body)
            if res["success"]:
                note = hits[0]["title"]
        if not res["success"]:
            return res
    return {"success": True, "speak": True,
            "message": f"Added that under {section} in {_note_title(note)}."}


def _do_create(title: str, content: str) -> dict:
    if not title:
        return {"success": False, "message": "What should the note be called?"}
    if _note_exists(title):
        # PUT would silently replace the whole file. Never clobber notes.
        return {"success": False,
                "message": f"A note called {_note_title(title)} already exists. "
                           f"I can add to it instead if you want."}
    body = f"# {_note_title(title)}\n\n{content or ''}".rstrip() + "\n"
    res = obsidian_api.request("PUT", obsidian_api.vault_path(title), data=body)
    if not res["success"]:
        return res
    return {"success": True, "speak": True,
            "message": f"Created {_note_title(title)}."}


def _do_link(note: str, targets: str) -> dict:
    links = _wikilinks(targets)
    if not note or not links:
        return {"success": False,
                "message": "I need a note and at least one note to link to."}
    res = _patch_append(note, "Related", "\n".join(f"- {l}" for l in links))
    if not res["success"]:
        return res
    return {"success": True, "speak": True,
            "message": f"Linked {_note_title(note)} to {len(links)} "
                       f"{'note' if len(links) == 1 else 'notes'}."}


def _do_moc(title: str, targets: str) -> dict:
    """Create a Map of Content: an index note of wikilinks.

    Backlinks need no work of their own — Obsidian derives them from the
    wikilinks, so writing the links IS creating the graph edges.
    """
    links = _wikilinks(targets)
    if not title or not links:
        return {"success": False,
                "message": "I need a title and the notes to include in the map."}
    lines = [f"# {_note_title(title)}", "",
             f"Map of content. Built {_timestamp()}.", "", "## Notes", ""]
    lines += [f"- {l}" for l in links]
    body = "\n".join(lines) + "\n"

    if _note_exists(title):
        # additive: extend the existing map rather than replacing it
        res = _patch_append(title, "Notes", "\n".join(f"- {l}" for l in links))
        verb = "Updated"
    else:
        res = obsidian_api.request("PUT", obsidian_api.vault_path(title), data=body)
        verb = "Created"
    if not res["success"]:
        return res
    return {"success": True, "speak": True,
            "message": f"{verb} the map {_note_title(title)} with {len(links)} notes."}


def _do_diagram(note: str, source: str) -> dict:
    """Embed a mermaid block. Obsidian renders these natively — no plugin."""
    if not note or not source:
        return {"success": False,
                "message": "I need a note and the diagram content."}
    source = source.strip()
    if source.startswith("```"):
        source = source.strip("`").lstrip("mermaid").strip()
    block = "```mermaid\n" + source + "\n```"
    res = _patch_append(note, "Diagram", block)
    if not res["success"]:
        return res
    return {"success": True, "speak": True,
            "message": f"Added the diagram to {_note_title(note)}."}


def _do_tags() -> dict:
    res = obsidian_api.request("GET", "/tags/")
    if not res["success"]:
        return res
    tags = (res.get("json") or {}).get("tags") or []
    if not tags:
        return {"success": True, "speak": True,
                "message": "Your vault has no tags yet."}
    tags.sort(key=lambda t: t.get("count") or 0, reverse=True)
    top = ", ".join(f"{t['name']} ({t['count']})" for t in tags[:8])
    return {"success": True, "speak": True, "message": f"Your top tags: {top}."}


def _do_open(note: str) -> dict:
    if not note:
        return {"success": False, "message": "Which note should I open?"}
    path = note if note.lower().endswith(".md") else f"{note}.md"
    hits = search_notes(note, limit=1)
    if hits:
        path = hits[0]["path"]
    import urllib.parse
    encoded = "/".join(urllib.parse.quote(s, safe="") for s in path.split("/") if s)
    res = obsidian_api.request("POST", f"/open/{encoded}")
    if not res["success"]:
        return res
    return {"success": True, "speak": True,
            "message": f"Opened {_note_title(path)} in Obsidian."}


# ── dispatcher ───────────────────────────────────────────────────────────────

def obsidian_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    parts = [p.strip() for p in (parameter or "").split("|")]
    print(f"[obsidian_control] action={action!r} params={parts!r}")

    if not obsidian_api.is_configured():
        return {"success": False,
                "message": "I need an Obsidian API key first. Copy it from the "
                           "Local REST API plugin settings into OBSIDIAN_API_KEY."}

    def arg(i: int) -> str:
        return parts[i] if len(parts) > i else ""

    def rest(i: int) -> str:
        """Everything from field i onward, pipes intact — for free text."""
        return "|".join(parts[i:]) if len(parts) > i else ""

    if action == "search":
        return _do_search(rest(0))

    if action == "read":
        return _do_read(arg(0), arg(1) or None)

    if action == "active":
        res = active_note()
        res["speak"] = True
        return res

    if action == "append":
        # append|<note>|<section>|<text>
        return _do_append(arg(0), arg(1), rest(2), timestamped=False)

    if action == "progress":
        # progress|<note>|<text> — always timestamped, always the progress log
        return _do_append(arg(0), DEFAULT_SECTION, rest(1), timestamped=True)

    if action == "create":
        return _do_create(arg(0), rest(1))

    if action == "link":
        return _do_link(arg(0), rest(1))

    if action == "moc":
        return _do_moc(arg(0), rest(1))

    if action == "diagram":
        return _do_diagram(arg(0), rest(1))

    if action == "tags":
        return _do_tags()

    if action == "open":
        return _do_open(arg(0))

    if action == "status":
        res = obsidian_api.status()
        res["speak"] = True
        return res

    return {"success": False, "message": f"Unknown Obsidian action: {action}"}
