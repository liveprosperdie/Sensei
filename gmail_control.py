"""Gmail dispatcher — STRICTLY READ ONLY.

Runs against the dedicated read-only MCP instance (gmail.readonly scope
only; the server hides all write tools in that mode) AND every outbound
tool name sits on google_mcp.DENYLIST as a second wall. There is no send,
draft, delete, or modify path through this module by design — do not add
one without clearing the project's confirmation-protocol requirements.

Action format:
  search|<gmail query, e.g. from:boss after:2026/07/01>
  read|<messageId>
  unread|[max results]
  labels
"""

import google_mcp


def gmail_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    param = (parameter or "").strip()
    print(f"[gmail_control] action={action!r} param={param!r}")

    # Every gmail action is a read whose result is a raw API dump —
    # speak_summary=True gets it synthesized into a spoken digest in the
    # SAME turn instead of requiring a "you didn't answer" follow-up.
    if action == "search":
        if not param:
            return {"success": False, "message": "Search your mail for what?"}
        return google_mcp.call("gmail", "search_emails",
                               {"query": param, "maxResults": 10},
                               speak_summary=True)

    if action == "read":
        if not param:
            return {"success": False, "message": "Which email? I need the message id."}
        return google_mcp.call("gmail", "read_email",
                               {"id": param, "contentFormat": "text"},
                               speak_summary=True)

    if action == "unread":
        n = int(param) if param.isdigit() else 5
        return google_mcp.call("gmail", "search_emails",
                               {"query": "is:unread", "maxResults": n},
                               speak_summary=True)

    if action == "labels":
        return google_mcp.call("gmail", "list_labels", {}, speak_summary=True)

    return {"success": False,
            "message": f"Unknown or disabled gmail action: {action}. Gmail is read-only in Akira."}
