"""Google Slides dispatcher. Create/read/edit — no sharing wired.

Action format:
  create|Name|Slide 1 title::slide 1 content;;Slide 2 title::content...
  read|<presentationId>|[slide number]
  update|<presentationId>|Slide 1 title::content;;...   (replaces slide set)
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


def slides_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    parts = (parameter or "").split("|", 1)
    print(f"[slides_control] action={action!r} params={parts!r}")

    if action == "create":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "What should the presentation be called?"}
        slides = _slides(parts[1]) if len(parts) > 1 else []
        if not slides:
            slides = [{"title": parts[0].strip(), "content": ""}]
        return google_mcp.call("workspace", "create_google_slides",
                               {"name": parts[0].strip(), "slides": slides})

    if action == "read":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "Which presentation? I need its id."}
        sub = parts[1].strip() if len(parts) > 1 else ""
        args = {"presentationId": parts[0].strip()}
        if sub.isdigit():
            args["slideIndex"] = int(sub)
        return google_mcp.call("workspace", "get_google_slides_content", args)

    if action == "update":
        if len(parts) < 2:
            return {"success": False, "message": "Update needs a presentation id and slide content."}
        slides = _slides(parts[1])
        if not slides:
            return {"success": False, "message": "No slide content given."}
        return google_mcp.call("workspace", "update_google_slides",
                               {"presentationId": parts[0].strip(), "slides": slides})

    return {"success": False, "message": f"Unknown slides action: {action}"}
