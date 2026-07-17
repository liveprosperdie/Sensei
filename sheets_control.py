"""Google Sheets dispatcher. Create/read/write cells — no sharing wired.

Action format:
  create|Name|[row1col1,row1col2;row2col1,...]   (semicolon rows, comma cells)
  generate|Name|brief of the data wanted        (Gemini composes the rows)
  read|<spreadsheetId>|[range e.g. Sheet1!A1:C10]
  write|<spreadsheetId>|<range>|value1,value2;value3,...
"""

import google_mcp


def _grid(text: str) -> list[list[str]]:
    """'a,b;c,d' -> [["a","b"],["c","d"]]"""
    return [[cell.strip() for cell in row.split(",")]
            for row in text.split(";") if row.strip()]


def sheets_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    parts = (parameter or "").split("|")
    print(f"[sheets_control] action={action!r} params={parts!r}")

    if action == "create":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "What should the spreadsheet be called?"}
        data = _grid(parts[1]) if len(parts) > 1 and parts[1].strip() else [[""]]
        return google_mcp.call("workspace", "create_google_sheet",
                               {"name": parts[0].strip(), "data": data})

    if action == "generate":
        # Name|brief — data rows from Gemini in a separate call, returned in
        # the exact a,b;c,d format _grid() parses. Sheet data is inherently
        # short, so no length hint is exposed here.
        if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
            return {"success": False,
                    "message": "Generate needs a spreadsheet name and a brief of the data wanted."}
        import gemini_content
        gen = gemini_content.generate(
            parts[1].strip(),
            "Produce spreadsheet data in this exact plain-text format and "
            "nothing else: cells separated by commas, rows separated by "
            "semicolons, first row as headers. Example: Name,Age;Alice,30;Bob,25. "
            "No markdown, no commentary, and no commas or semicolons inside "
            "cell values.",
            "short")
        if not gen["success"]:
            return gen
        data = _grid(gen["text"])
        if not data:
            return {"success": False,
                    "message": "The generated sheet data came back in an unusable format."}
        return google_mcp.call("workspace", "create_google_sheet",
                               {"name": parts[0].strip(), "data": data})

    if action == "read":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "Which spreadsheet? I need its id."}
        args = {"spreadsheetId": parts[0].strip()}
        if len(parts) > 1 and parts[1].strip():
            args["range"] = parts[1].strip()
        return google_mcp.call("workspace", "get_google_sheet_content", args,
                               speak_summary=True)

    if action == "write":
        if len(parts) < 3:
            return {"success": False, "message": "Writing needs a spreadsheet id, a range, and values."}
        return google_mcp.call("workspace", "update_google_sheet", {
            "spreadsheetId": parts[0].strip(),
            "range": parts[1].strip(),
            "data": _grid("|".join(parts[2:]))})

    return {"success": False, "message": f"Unknown sheets action: {action}"}
