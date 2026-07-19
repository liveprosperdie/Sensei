"""Google Slides dispatcher. Create/generate/read/edit/delete — no sharing wired.

Action format:
  create|Name|Slide 1 title::slide 1 content;;Slide 2 title::content...
  generate|Name|topic brief|[slide count]        (Gemini writes the slides)
  read|<presentationId>|[slide number]
  update|<presentationId>|Slide 1 title::content;;...   (replaces slide set)
  delete|<presentationId or name>       (moves to Drive trash — gated in sensei.py)
"""

import google_mcp


def _slides(text: str) -> list[dict]:
    """'T1::body;;T2::body' -> [{"title":"T1","content":"body"}, ...]
    (matches the server's slides array item schema: {title, content})"""
    out = []
    for chunk in text.split(";;"):
        chunk = chunk.strip()
        if not chunk:
            continue
        title, _, content = chunk.partition("::")
        out.append({"title": title.strip(), "content": content.strip()})
    return out


def _resolve_presentation_id(ref: str) -> tuple[str | None, str | None]:
    """Accept a raw presentation id or a name (searched via Drive by name).
    Same shape as docs_control._resolve_doc_id."""
    ref = ref.strip()
    if len(ref) > 25 and " " not in ref:
        return ref, None
    res = google_mcp.call("workspace", "search",
                          {"query": ref, "searchType": "name", "pageSize": 3})
    if not res["success"]:
        return None, res["message"]
    import re
    ids = re.findall(r"[-\w]{25,}", res["message"])
    if not ids:
        return None, f"No presentation found matching '{ref}'."
    return ids[0], None


def slides_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    parts = (parameter or "").split("|", 1)
    # Log the raw parameter, not `parts`: the split-once view falsely makes a
    # trailing "|count" (generate format) look absorbed into the brief.
    print(f"[slides_control] action={action!r} parameter={parameter!r}")

    if action == "create":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "What should the presentation be called?"}
        slides = _slides(parts[1]) if len(parts) > 1 else []
        if not slides:
            slides = [{"title": parts[0].strip(), "content": ""}]
        return google_mcp.call("workspace", "create_google_slides",
                               {"name": parts[0].strip(), "slides": slides})

    if action == "generate":
        # Name|brief|[slide count] — content from Gemini in a separate call,
        # returned in the exact T::body;;T::body format _slides() parses.
        sub = (parameter or "").split("|")
        if len(sub) < 2 or not sub[0].strip() or not sub[1].strip():
            return {"success": False,
                    "message": "Generate needs a presentation name and a topic brief."}
        # 5 slides default, 15 cap — voice-requested decks are outlines, not
        # keynotes; anything bigger should be asked for explicitly per slide.
        count = int(sub[2]) if len(sub) > 2 and sub[2].strip().isdigit() else 5
        count = max(1, min(count, 15))
        import gemini_content
        gen = gemini_content.generate(
            sub[1].strip(),
            f"Produce exactly {count} presentation slides in this exact plain-text "
            "format and nothing else:\n"
            "Slide title::2-4 short sentences of slide body;;next title::body\n"
            "Separate slides with ;; and title from body with ::. "
            "No markdown, no numbering, no extra commentary.",
            "short" if count <= 6 else "detailed")
        if not gen["success"]:
            return gen
        slides = _slides(gen["text"])
        if not slides:
            return {"success": False,
                    "message": "The generated slide content came back in an unusable format."}
        return google_mcp.call("workspace", "create_google_slides",
                               {"name": sub[0].strip(), "slides": slides})

    if action == "read":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "Which presentation? I need its id."}
        sub = parts[1].strip() if len(parts) > 1 else ""
        args = {"presentationId": parts[0].strip()}
        if sub.isdigit():
            args["slideIndex"] = int(sub)
        return google_mcp.call("workspace", "get_google_slides_content", args,
                               speak_summary=True)

    if action == "update":
        if len(parts) < 2:
            return {"success": False, "message": "Update needs a presentation id and slide content."}
        slides = _slides(parts[1])
        if not slides:
            return {"success": False, "message": "No slide content given."}
        return google_mcp.call("workspace", "update_google_slides",
                               {"presentationId": parts[0].strip(), "slides": slides})

    if action == "delete":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "Which presentation should I delete?"}
        pres_id, err = _resolve_presentation_id(parts[0])
        if err:
            return {"success": False, "message": err}
        # The Slides API has no delete — presentations are Drive files, and
        # the server's only per-file delete is delete_item, which moves the
        # file to the Drive TRASH (recoverable), not a permanent wipe.
        res = google_mcp.call("workspace", "delete_item", {"itemId": pres_id})
        if res["success"]:
            res["detail"] = res["message"]  # full server output for the LLM
            res["message"] = ("Presentation moved to the Drive trash. "
                              "It can be restored from there if needed.")
        return res

    return {"success": False, "message": f"Unknown slides action: {action}"}
