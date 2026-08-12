"""Shared Gemini free-tier daily request counter.

WHY THIS IS ONE MODULE AND NOT TWO COUNTERS
===========================================
The Gemini free tier meters REQUESTS PER DAY per project, against the API key —
not per calling module. Sensei now makes Gemini calls from two places:

    gemini_content.generate()   long-form prose, one call per "write me a doc"
    gemini_head.route()         action routing, ONE CALL PER UTTERANCE

Before this module, gemini_content owned a private counter. Adding a second
private counter in gemini_head would have let each module believe it had the
full daily allowance, so the two together would have sailed through roughly
2x the real cap and then started taking hard 429s from Google — exactly the
"cheap tier silently fails" shape this project keeps rejecting. One counter,
one file, both callers.

The file format is unchanged from gemini_content's original
({"date": ..., "count": ...}) so an existing day's count carries over rather
than resetting to zero on upgrade. `by_purpose` is additive and optional; a
file written by the old code simply has no such key.

THE COUNTER IS ADVISORY, NOT AUTHORITATIVE. Google owns the real number. This
is a local pre-flight brake so the app can refuse with a clear message BEFORE
spending the request, instead of discovering the cap through a 429 mid-turn.
Google's 429 is still handled as the real signal by both callers.

No Windows/TTS/network imports: exercised headlessly by verify_gemini_head.py.
"""

from __future__ import annotations

import datetime
import json
import os
import threading

# Google no longer publishes a fixed free-tier RPD in the docs — it is
# per-project and visible only in the AI Studio dashboard. 250/day is the most
# conservative figure the Flash free tier has carried, so it is the safe
# default; set GEMINI_DAILY_LIMIT to the real number from AI Studio.
DAILY_LIMIT = int(os.environ.get("GEMINI_DAILY_LIMIT", "250"))

# Hard-stop at 90% to leave headroom, so a burst of routing calls cannot take
# the user all the way to a Google-side 429 with no margin left for the
# in-flight turn to finish.
STOP_AT = max(1, (DAILY_LIMIT * 9) // 10)

QUOTA_FILE = os.environ.get("SENSEI_GEMINI_QUOTA_FILE") or os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Sensei", "gemini_quota.json")

# Routing runs on the voice hot path from a background thread while a content
# generation may still be in flight. Two unsynchronised read-modify-writes lose
# counts, and an undercount here means overshooting a hard daily cap.
_lock = threading.Lock()


def _read() -> dict:
    """Today's record, or a fresh one. A missing/corrupt file reads as zero
    rather than raising: the counter must never be the reason a turn dies."""
    try:
        with open(QUOTA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == datetime.date.today().isoformat():
            return {"date": data["date"],
                    "count": int(data.get("count", 0)),
                    "by_purpose": dict(data.get("by_purpose") or {})}
    except (OSError, ValueError, TypeError):
        pass
    return {"date": datetime.date.today().isoformat(), "count": 0,
            "by_purpose": {}}


def used_today() -> int:
    with _lock:
        return _read()["count"]


def remaining() -> int:
    return max(0, STOP_AT - used_today())


def exhausted() -> bool:
    return remaining() <= 0


def record(purpose: str) -> int:
    """Count one request that REACHED Google. Returns the new total.

    Called after the HTTP round trip, including for error responses, because a
    request that reached Google counted against the project's quota whether or
    not it produced usable output. Only a local failure (no key, connection
    refused) is uncounted — that never touched the quota.
    """
    with _lock:
        data = _read()
        data["count"] += 1
        data["by_purpose"][purpose] = data["by_purpose"].get(purpose, 0) + 1
        try:
            os.makedirs(os.path.dirname(QUOTA_FILE), exist_ok=True)
            # Write-then-replace: a crash mid-write would otherwise leave
            # truncated JSON, which _read() would treat as zero and silently
            # hand back a full day's quota.
            tmp = QUOTA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, QUOTA_FILE)
        except OSError as e:
            print(f"[gemini_quota] could not persist count: {e}")
        return data["count"]


def snapshot() -> dict:
    """Diagnostics for a startup banner or status command."""
    with _lock:
        data = _read()
    return {"used": data["count"], "stop_at": STOP_AT, "limit": DAILY_LIMIT,
            "remaining": max(0, STOP_AT - data["count"]),
            "by_purpose": data["by_purpose"]}
