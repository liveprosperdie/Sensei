"""Google Docs dispatcher. Create/read/append — no sharing tools wired.

Action format:
  create|Title|content...
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
    res = google_mcp.call("workspace", "search",
                          {"query": ref, "searchType": "documents", "pageSize": 3})
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
        return google_mcp.call("workspace", "create_google_doc", {
            "name": parts[0].strip(),
            "content": parts[1] if len(parts) > 1 else ""})

    if action == "read":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "Which document?"}
        doc_id, err = _resolve_doc_id(parts[0])
        if err:
            return {"success": False, "message": err}
        return google_mcp.call("workspace", "get_google_doc_content",
                               {"documentId": doc_id})

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
