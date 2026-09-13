"""Google Calendar dispatcher. Full read/write, routed through google_mcp.

Action format (pipe-separated, matching akira's existing convention):
  list|[days ahead, default 7]
  create|Title|2026-07-17 15:00|2026-07-17 16:00|[description]
  get|<eventId>
  update|<eventId>|field=value[|field=value...]   (title/start/end/description/location)
  delete|<eventId>
  free|2026-07-17 09:00|2026-07-17 18:00|[duration minutes, default 30]
"""

from datetime import datetime, timedelta

import google_mcp


def _iso(text: str) -> str:
    """'2026-07-17 15:00' -> RFC3339 with the machine's local UTC offset."""
    dt = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    return dt.astimezone().isoformat()


def calendar_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    parts = [p.strip() for p in (parameter or "").split("|")] if parameter else []
    print(f"[calendar_control] action={action!r} params={parts!r}")

    try:
        if action == "list":
            now = datetime.now().astimezone()
            p = (parts[0].lower() if parts else "")
            if p == "today":
                time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                time_max = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
            elif p == "tomorrow":
                tomorrow = now + timedelta(days=1)
                time_min = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                time_max = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
            else:
                days = int(parts[0]) if parts and parts[0].isdigit() else 7
                time_min = now.isoformat()
                time_max = (now + timedelta(days=days)).isoformat()
            # speak_summary: list results are raw event dumps — synthesized
            # into a spoken schedule in the same turn (see akira.handle_response)
            return google_mcp.call("workspace", "list_events", {
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": True, "orderBy": "startTime", "maxResults": 15},
                speak_summary=True)

        if action == "create":
            if len(parts) < 2:
                return {"success": False, "message": "Creating an event needs at least a title and start time."}
            title = parts[0]
            start_str = parts[1]
            if len(parts) >= 3 and parts[2]:
                end_str = parts[2]
            else:
                # Default end time to 1 hour after start
                dt_start = datetime.strptime(start_str.strip(), "%Y-%m-%d %H:%M")
                end_str = (dt_start + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
            args = {"summary": title,
                    "start": {"dateTime": _iso(start_str)},
                    "end": {"dateTime": _iso(end_str)}}
            if len(parts) > 3 and parts[3]:
                args["description"] = parts[3]
            return google_mcp.call("workspace", "create_event", args)

        if action == "get":
            if not parts:
                return {"success": False, "message": "Which event? I need the event id."}
            return google_mcp.call("workspace", "get_event", {"eventId": parts[0]})

        if action == "update":
            if len(parts) < 2:
                return {"success": False, "message": "Update needs an event id and at least one field=value."}
            args = {"eventId": parts[0]}
            for kv in parts[1:]:
                if "=" not in kv:
                    continue
                k, v = kv.split("=", 1)
                k = k.strip().lower()
                if k == "title":
                    args["summary"] = v
                elif k == "start":
                    args["start"] = {"dateTime": _iso(v)}
                elif k == "end":
                    args["end"] = {"dateTime": _iso(v)}
                elif k in ("description", "location"):
                    args[k] = v
            if len(args) == 1:
                return {"success": False, "message": "No valid fields to update."}
            return google_mcp.call("workspace", "update_event", args)

        if action == "delete":
            if not parts:
                return {"success": False, "message": "Which event? I need the event id."}
            return google_mcp.call("workspace", "delete_event", {"eventId": parts[0]})

        if action == "free":
            if len(parts) < 2:
                return {"success": False, "message": "Free-time check needs a start and end of the window."}
            duration = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30
            return google_mcp.call("workspace", "find_free_time", {
                "calendarIds": ["primary"],
                "timeMin": _iso(parts[0]), "timeMax": _iso(parts[1]),
                "duration": duration}, speak_summary=True)

        return {"success": False, "message": f"Unknown calendar action: {action}"}
    except ValueError as e:
        return {"success": False, "message": f"Bad date format — use YYYY-MM-DD HH:MM. ({e})"}
