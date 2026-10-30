"""Google Sheets dispatcher. Create/read/write cells — no sharing wired.

Action format:
  create|Name|[row1col1,row1col2;row2col1,...]   (semicolon rows, comma cells)
  generate|Name|brief of the data wanted        (Gemini composes the rows)
  read|<spreadsheetId>|[range e.g. Sheet1!A1:C10]
  write|<spreadsheetId>|<range>|value1,value2;value3,...
"""

import google_mcp


# Formula functions that can exfiltrate data or pull remote content — the MCP
# server's own USER_ENTERED security warning names these. LLM-generated cells
# containing them are force-texted (leading ') rather than evaluated.
_DANGEROUS_FORMULAS = ("IMPORTDATA", "IMPORTRANGE", "IMPORTXML", "IMPORTHTML",
                       "IMPORTFEED", "IMAGE", "HYPERLINK")


def _cell(raw: str) -> str:
    cell = raw.strip()
    # "'=" is Sheets' force-text marker — if the LLM emits it on a formula,
    # strip it so USER_ENTERED evaluates the formula instead of storing text.
    if cell.startswith("'="):
        cell = cell[1:]
    if cell.startswith("=") and any(f in cell.upper() for f in _DANGEROUS_FORMULAS):
        return "'" + cell  # neutralize: store as text, never evaluate
    return cell


def _grid(text: str) -> list[list[str]]:
    """Tolerantly parses 'a,b;c,d', newlines, and CSV rows into [["a","b"],["c","d"]]."""
    import re
    clean = text.strip()
    # Strip markdown fences
    if "```" in clean:
        clean = re.sub(r"^```(?:csv|plaintext)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
        clean = clean.strip()

    # If rows are separated by semicolons
    if ";" in clean and "\n" not in clean:
        raw_rows = [r.strip() for r in clean.split(";") if r.strip()]
    else:
        # Split on newlines, handling trailing semicolons if present
        raw_rows = [r.strip().rstrip(";") for r in clean.splitlines() if r.strip().rstrip(";")]

    grid = []
    for row in raw_rows:
        # Also split if multiple rows joined with semicolon in one line
        sub_rows = [sr.strip() for sr in row.split(";") if sr.strip()] if ";" in row else [row]
        for sub in sub_rows:
            cells = [_cell(c) for c in sub.split(",")]
            if cells:
                grid.append(cells)
    return grid


def sheets_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    parts = (parameter or "").split("|")
    print(f"[sheets_control] action={action!r} params={parts!r}")

    if action == "create":
        if not parts or not parts[0].strip():
            return {"success": False, "message": "What should the spreadsheet be called?"}
        data = _grid(parts[1]) if len(parts) > 1 and parts[1].strip() else [[""]]
        # USER_ENTERED so formulas evaluate (server default RAW stores "=SUM"
        # as text — the leading-apostrophe bug). Safe: _cell() neutralizes
        # dangerous IMPORT*/exfil formulas before anything reaches the API.
        return google_mcp.call("workspace", "create_google_sheet",
                               {"name": parts[0].strip(), "data": data,
                                "valueInputOption": "USER_ENTERED"})

    if action == "generate":
        # Pro-only: AI-generated dataset creation is a premium capability.
        # Interactive create/read/write stay on Standard.
        import tiers
        if tiers.plan_for(tiers.Layer.SERVANT) != tiers.PRO:
            return {"success": False, "speak": True,
                    "message": "AI-generated spreadsheet data is a Pro tier feature. "
                               "You can still create spreadsheets with your own data using 'create'."}
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
        name = parts[0].strip()
        res = google_mcp.call("workspace", "create_google_sheet",
                               {"name": name, "data": data,
                                "valueInputOption": "USER_ENTERED"})
        if not res.get("success") and "already exists" in str(res.get("message", "")).lower():
            import datetime
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            alt_name = f"{name} ({ts})"
            res = google_mcp.call("workspace", "create_google_sheet",
                                  {"name": alt_name, "data": data,
                                   "valueInputOption": "USER_ENTERED"})
        return res

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
            "data": _grid("|".join(parts[2:])),
            "valueInputOption": "USER_ENTERED"})

    return {"success": False, "message": f"Unknown sheets action: {action}"}
