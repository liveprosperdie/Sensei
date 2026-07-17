"""Long-form content generation via the Gemini API free tier.

Why this exists (design decision, 2026-07): the Claude action-routing call
used to carry entire documents inside one JSON string field of the action
envelope. Long docs hit max_tokens mid-string and crashed the turn with an
unterminated-JSON error, and every "write me a doc" burned paid Claude
tokens. Content generation is now a SEPARATE call to Gemini's free tier;
the resulting text is handed to the Docs/Slides/Sheets MCP tools as plain
content and NEVER travels inside the routing JSON.

Requires GEMINI_API_KEY — a Google AI Studio key from
https://aistudio.google.com/apikey. This is a different product and key
type from the Workspace OAuth client id/secret; the two are unrelated.
"""

import datetime
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

# Stable model id confirmed live on ai.google.dev (2026-07). Overridable
# because Google retires model ids on ~yearly cycles.
_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Google no longer publishes fixed free-tier RPD in the docs — limits are
# per-project and shown only in the AI Studio dashboard. 250/day is the most
# conservative figure the 2.5-flash free tier has carried, so it's the safe
# default; set GEMINI_DAILY_LIMIT to your project's real number from AI
# Studio. We hard-stop at 90% of the limit to leave a safety margin.
_DAILY_LIMIT = int(os.environ.get("GEMINI_DAILY_LIMIT", "250"))
_STOP_AT = max(1, (_DAILY_LIMIT * 9) // 10)

_QUOTA_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Sensei", "gemini_quota.json")

# "short" is the default everywhere so a plain "make me a doc about X"
# never triggers a 20-page generation nobody asked for.
_LENGTH_WORDS = {"short": 400, "detailed": 2500}


def _quota_used_today() -> int:
    try:
        with open(_QUOTA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == datetime.date.today().isoformat():
            return int(data.get("count", 0))
    except (OSError, ValueError):
        pass
    return 0


def _bump_quota() -> None:
    os.makedirs(os.path.dirname(_QUOTA_FILE), exist_ok=True)
    data = {"date": datetime.date.today().isoformat(),
            "count": _quota_used_today() + 1}
    with open(_QUOTA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def generate(brief: str, format_instructions: str = "",
             length: str = "short") -> dict:
    """One Gemini completion. Returns {"success": True, "text": ...} or an
    honest {"success": False, "message": ...} — quota exhaustion, missing
    key, HTTP errors, and mid-generation truncation all surface as failures,
    never as silently shortened content."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"success": False,
                "message": "GEMINI_API_KEY isn't set. Get a free key at "
                           "aistudio.google.com/apikey and add it to the .env file."}

    used = _quota_used_today()
    if used >= _STOP_AT:
        return {"success": False,
                "message": "Free content-generation quota reached for today, "
                           "try again tomorrow or ask for something shorter."}

    words = _LENGTH_WORDS.get(length, _LENGTH_WORDS["short"])
    prompt = (f"Write the following content in roughly {words} words or fewer. "
              f"{format_instructions}\n\n{brief}")

    try:
        # 120s: a detailed multi-page generation on the free tier can take
        # over a minute; a short one returns in seconds either way.
        resp = requests.post(
            _URL.format(model=_MODEL),
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  # 8192 covers ~2500 words plus the model's internal
                  # thinking tokens (2.5-flash thinks by default and thinking
                  # counts against maxOutputTokens).
                  "generationConfig": {"maxOutputTokens": 8192}},
            timeout=120)
    except requests.RequestException as e:
        return {"success": False, "message": f"Gemini request failed: {e}"}

    _bump_quota()  # count every attempt that reached Google, including errors

    if resp.status_code == 429:
        return {"success": False,
                "message": "Gemini says the free quota is exhausted. "
                           "Try again tomorrow or ask for something shorter."}
    if resp.status_code != 200:
        detail = resp.text[:300]
        return {"success": False,
                "message": f"Gemini returned HTTP {resp.status_code}: {detail}"}

    try:
        body = resp.json()
        candidate = body["candidates"][0]
        text = "".join(p.get("text", "")
                       for p in candidate["content"]["parts"]).strip()
    except (KeyError, IndexError, ValueError) as e:
        return {"success": False,
                "message": f"Gemini returned an unexpected response shape: {e}"}

    if not text:
        return {"success": False, "message": "Gemini returned no text."}
    if candidate.get("finishReason") == "MAX_TOKENS":
        # truncated mid-content — the exact failure mode this module was
        # built to eliminate; refuse rather than save a cut-off document
        return {"success": False,
                "message": "The generated content was too long and got cut off. "
                           "Ask for something shorter."}

    print(f"[gemini_content] generated {len(text)} chars "
          f"(quota {used + 1}/{_STOP_AT})")
    return {"success": True, "text": text}
