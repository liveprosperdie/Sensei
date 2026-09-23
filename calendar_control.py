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


import re

_MONTHS = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3, 'apr': 4, 'april': 4,
    'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7, 'aug': 8, 'august': 8, 'sep': 9, 'september': 9,
    'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12
}


def _parse_dt(text: str) -> datetime:
    """Parse strict ISO, YYYY-MM-DD HH:MM, or natural relative strings ('tomorrow 7pm', 'Sep 19 7pm')."""
    t = (text or "").strip()
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %I:%M %p', '%Y-%m-%d %I%p', '%Y-%m-%d'):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            pass

    now = datetime.now()
    t_lower = t.lower()
    target_year = now.year
    target_month = now.month
    target_day = now.day

    if 'tomorrow' in t_lower:
        d = now.date() + timedelta(days=1)
        target_year, target_month, target_day = d.year, d.month, d.day
        t_lower = t_lower.replace('tomorrow', '')
    elif 'today' in t_lower:
        d = now.date()
        target_year, target_month, target_day = d.year, d.month, d.day
        t_lower = t_lower.replace('today', '')
    else:
        m_month = None
        for m_name, m_num in _MONTHS.items():
            if re.search(r'\b' + m_name + r'\b', t_lower):
                m_month = m_num
                t_lower = re.sub(r'\b' + m_name + r'\b', '', t_lower)
                break
        if m_month:
            target_month = m_month
            m_day = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\b', t_lower)
            if m_day:
                target_day = int(m_day.group(1))
                t_lower = re.sub(r'\b' + m_day.group(0) + r'\b', '', t_lower)

    t_lower = re.sub(r'\b(at|on|for)\b', '', t_lower).strip()
    m_time = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', t_lower)
    if m_time:
        hour = int(m_time.group(1))
        minute = int(m_time.group(2)) if m_time.group(2) else 0
        meridiem = m_time.group(3)
        if meridiem == 'pm' and hour < 12:
            hour += 12
        elif meridiem == 'am' and hour == 12:
            hour = 0
        elif not meridiem and hour <= 7:
            hour += 12
        return datetime(target_year, target_month, target_day, hour, minute)

    # Fallback to direct strptime
    return datetime.strptime(t, "%Y-%m-%d %H:%M")


def _iso(text: str) -> str:
    """Convert any date string to RFC3339 with local timezone offset."""
    dt = _parse_dt(text)
    return dt.astimezone().isoformat()


def calendar_control(action: str, parameter: str | None = None) -> dict:
    action = (action or "").strip().lower()
    if action in ("today", "tomorrow", "agenda"):
        parameter = action if not parameter else f"{action}|{parameter}"
        action = "list"
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
            try:
                dt_start = _parse_dt(start_str)
            except Exception as e:
                return {"success": False, "message": f"Couldn't understand start time '{start_str}': {e}"}

            if len(parts) >= 3 and parts[2]:
                try:
                    dt_end = _parse_dt(parts[2])
                except Exception:
                    dt_end = dt_start + timedelta(hours=1)
            else:
                dt_end = dt_start + timedelta(hours=1)

            args = {"summary": title,
                    "start": {"dateTime": dt_start.astimezone().isoformat()},
                    "end": {"dateTime": dt_end.astimezone().isoformat()}}
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
