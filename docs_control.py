"""Google Docs dispatcher. Create/generate/read/append — no sharing tools wired.

Action format:
  create|Title|content...            (user-dictated content only)
  generate|Title|content brief|[short or detailed]   (Gemini writes the content)
  read|<documentId or name>
  append|<documentId>|text...
"""

import google_mcp


def _resolve_doc_id(ref: str) -> tuple[str | None, str | None]:
    """Accept either a raw Docs id or a document name (searched via Drive).
    Returns (doc_id, error_message)."""
    ref = ref.strip()
    # Docs ids are long and have no spaces; names usually don't look like ids
    if len(ref) > 25 and " " not in ref:
        return ref, None
    # searchType enum is fulltext|name|name_exact (verified in v3.4.4 source
    # — the previous "documents" value was invalid and failed server-side
    # validation). "name" matches how users refer to docs aloud.
    res = google_mcp.call("workspace", "search",
                          {"query": ref, "searchType": "name", "pageSize": 3})
    if not res["success"]:
        return None, res["message"]
    import re
    ids = re.findall(r"[-\w]{25,}", res["message"])
    if not ids:
        return None, f"No document found matching '{ref}'."
    return ids[0], None


def docs_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    parts = (parameter or "").split("|", 1)
    print(f"[docs_control] action={action!r} params={parts!r}")

    if action == "create":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "What should the document be called?"}
        content = parts[1] if len(parts) > 1 else ""
        # The server unconditionally builds an insertText request from
        # content (required field, verified in v3.4.4 source) and the Docs
        # API rejects an empty insertText. A single newline is the smallest
        # valid insert and yields a visually blank doc.
        if not content.strip():
            content = "\n"
        return google_mcp.call("workspace", "create_google_doc", {
            "name": parts[0].strip(), "content": content})

    if action == "generate":
        # Pro-only: AI-authored content generation is a premium capability.
        # Interactive create/read/append stay on Standard.
        import tiers
        if tiers.plan_for(tiers.Layer.SERVANT) != tiers.PRO:
            return {"success": False, "speak": True,
                    "message": "AI-generated document drafting is a Pro tier feature. "
                               "You can still create documents with your own content using 'create'."}
        # Title|brief|[short or detailed] — content comes from Gemini in a
        # separate completion, never inline in the routing JSON (that's what
        # used to truncate long docs mid-string).
        sub = (parameter or "").split("|")
        if len(sub) < 2 or not sub[0].strip() or not sub[1].strip():
            return {"success": False,
                    "message": "Generate needs a document title and a brief of what to write."}
        length = sub[2].strip().lower() if len(sub) > 2 and sub[2].strip() else "short"
        import gemini_content
        gen = gemini_content.generate(
            sub[1].strip(),
            "Write plain text suitable for a Google Doc. No markdown syntax, "
            "no # headers, no asterisks.",
            length)
        if not gen["success"]:
            return gen
        return google_mcp.call("workspace", "create_google_doc", {
            "name": sub[0].strip(), "content": gen["text"]})

    if action == "read":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "Which document?"}
        doc_id, err = _resolve_doc_id(parts[0])
        if err:
            return {"success": False, "message": err}
        return google_mcp.call("workspace", "get_google_doc_content",
                               {"documentId": doc_id}, speak_summary=True)

    if action == "append":
        if len(parts) < 2 or not parts[0].strip():
            return {"success": False, "message": "Append needs a document and the text to add."}
        doc_id, err = _resolve_doc_id(parts[0])
        if err:
            return {"success": False, "message": err}
        return google_mcp.call("workspace", "append_to_doc",
                               {"documentId": doc_id, "text": parts[1],
                                "insertNewline": True})

    return {"success": False, "message": f"Unknown docs action: {action}"}
