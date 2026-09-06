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

import akira_quota

load_dotenv()

# "gemini-flash-latest" is Google's ROLLING alias for the current Flash
# model (it appears in /v1beta/models itself). A pinned id was tried first
# ("gemini-2.5-flash") and went stale within one retirement cycle — the API
# started 404ing when Google retired the model. The alias survives
# retirements by design; pin a specific id via GEMINI_MODEL only if
# output reproducibility matters more than availability.
_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# QUOTA MOVED TO akira_quota. The limit, the 90% safety stop and the
# counter file all live there now, unchanged in format and path, because ROUTING
# (gemini_head) draws on the SAME per-project daily allowance as this module.
# Two private counters would each have believed they owned the whole allowance
# and together sailed through roughly twice the real cap — see that module's
# docstring. Names kept as aliases so the call sites below read the same.
_STOP_AT = akira_quota.STOP_AT
_PURPOSE = "content_generation"

# "short" is the default everywhere so a plain "make me a doc about X"
# never triggers a 20-page generation nobody asked for.
_LENGTH_WORDS = {"short": 400, "detailed": 2500}


def generate(brief: str, format_instructions: str = "",
             length: str = "short") -> dict:
    """Content generator powered by Groq (model from GROQ_MODEL in .env).
    Gemini free API has been decommissioned.
    Returns {"success": True, "text": ...} or {"success": False, "message": ...}."""
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not groq_key:
        return {
            "success": False,
            "message": "GROQ_API_KEY isn't set in .env. Gemini has been removed from use, so Groq is required."
        }

    groq_model = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")
    words = _LENGTH_WORDS.get(length, _LENGTH_WORDS["short"])
    prompt = (f"Write the following content in roughly {words} words or fewer. "
              f"{format_instructions}\n\n{brief}")

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": groq_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a professional content writer. Produce high-quality, clean, well-formatted prose matching the requested length and format. Do not include conversational preambles or meta commentary."
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5,
                "max_tokens": 4096
            },
            timeout=60
        )
    except requests.RequestException as e:
        return {"success": False, "message": f"Groq request failed: {e}"}

    # Record usage
    akira_quota.record(_PURPOSE)

    if resp.status_code == 429:
        return {
            "success": False,
            "message": "Groq API rate limit reached. Please wait a moment and try again."
        }
    if resp.status_code != 200:
        detail = resp.text[:300]
        return {
            "success": False,
            "message": f"Groq returned HTTP {resp.status_code}: {detail}"
        }

    try:
        body = resp.json()
        raw_text = (body["choices"][0]["message"]["content"] or "").strip()
        import re
        text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    except (KeyError, IndexError, ValueError) as e:
        return {"success": False,
                "message": f"Groq returned an unexpected response shape: {e}"}

    if not text:
        return {"success": False, "message": "Groq returned empty text."}

    print(f"[content_generator] generated {len(text)} chars via Groq ({groq_model})")
    return {"success": True, "text": text}