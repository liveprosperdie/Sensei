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

import os

import requests
from dotenv import load_dotenv

import gemini_quota

load_dotenv()

# "gemini-flash-latest" is Google's ROLLING alias for the current Flash
# model (it appears in /v1beta/models itself). A pinned id was tried first
# ("gemini-2.5-flash") and went stale within one retirement cycle — the API
# started 404ing when Google retired the model. The alias survives
# retirements by design; pin a specific id via GEMINI_MODEL only if
# output reproducibility matters more than availability.
_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# QUOTA MOVED TO gemini_quota (2026-08). The limit, the 90% safety stop and the
# counter file all live there now, unchanged in format and path, because ROUTING
# (gemini_head) draws on the SAME per-project daily allowance as this module.
# Two private counters would each have believed they owned the whole allowance
# and together sailed through roughly twice the real cap — see that module's
# docstring. Names kept as aliases so the call sites below read the same.
_STOP_AT = gemini_quota.STOP_AT
_PURPOSE = "content_generation"

# "short" is the default everywhere so a plain "make me a doc about X"
# never triggers a 20-page generation nobody asked for.
_LENGTH_WORDS = {"short": 400, "detailed": 2500}


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

    used = gemini_quota.used_today()
    if used >= _STOP_AT:
        # Wording now says "free Gemini quota" rather than
        # "content-generation quota": the allowance is shared with routing, so
        # naming only this module's use of it would misdescribe what ran out.
        return {"success": False,
                "message": "Free Gemini quota reached for today (shared with "
                           "voice routing), try again tomorrow or ask for "
                           "something shorter."}

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

    # Count every attempt that reached Google, including errors. purpose= is
    # recorded so the shared counter can say WHICH consumer spent the
    # allowance — "quota gone, no idea what used it" is not debuggable.
    gemini_quota.record(_PURPOSE)

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
