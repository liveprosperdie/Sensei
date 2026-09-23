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


CONTENT_SYSTEM_PROMPT = (
    "You are an elite research, technical, and analytical content creator. "
    "Produce thorough, well-structured, detailed, and substantive content matching the requested domain: "
    "- For Documents & Written Overviews: Produce clean, polished, comprehensive prose organized into clear sections with capitalized headings, in-depth explanations, and bullet points. Never include conversational chatter, preambles, or filler. "
    "- For Spreadsheets & Tabular Data: Output valid, structured tabular records with header rows and accurate formulas. "
    "Ensure output is complete, high-quality, and adheres strictly to formatting guidelines."
)


def generate(brief: str, format_instructions: str = "",
             length: str = "short") -> dict:
    """Content generator powered by Groq (model from GROQ_MODEL in .env).
    Gemini free API has been decommissioned.
    Returns {"success": True, "text": ...} or {"success": False, "message": ...}."""
    groq_key = (os.environ.get("GROQ_API_KEY") or os.environ.get("SPEECH_API_KEY") or "").strip()
    if not groq_key:
        return {
            "success": False,
            "message": "GROQ_API_KEY or SPEECH_API_KEY isn't set in .env. Groq is required."
        }

    groq_model = os.environ.get("GROQ_CONTENT_MODEL", os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"))
    words = _LENGTH_WORDS.get(length, _LENGTH_WORDS["short"])
    prompt = (f"Write the following content in roughly {words} words or fewer. "
              f"{format_instructions}\n\n{brief}")

    # Determine safe max_tokens under Qwen and Groq limits
    is_qwen = "qwen" in groq_model.lower()
    safe_max_tokens = min(words * 2, 450) if is_qwen else min(words * 2, 1800)

    # Optional Claude route (strictly disabled by default per user specification)
    use_claude = os.environ.get("AKIRA_ENABLE_CLAUDE_CONTENT", "").lower() in ("true", "1")
    if use_claude and os.environ.get("AKIRA_DISABLE_CLAUDE", "").lower() not in ("true", "1"):
        try:
            import claude_handler
            if getattr(claude_handler, "client", None) is not None:
                anthropic_client = claude_handler.client
                sonnet_sys = (
                    "You are a professional technical and analytical writer. Produce clean, "
                    "well-structured, detailed prose matching the requested format. "
                    "Do not include conversational preambles, meta-commentary, markdown tags, or filler."
                )
                init_prompt = (
                    f"{prompt}\n\n"
                    f"Please ensure the document is comprehensive, detailed, and substantive, "
                    f"aiming for at least 900 words (~2 full pages)."
                )
                long_client = anthropic_client.with_options(timeout=120.0, max_retries=1) if hasattr(anthropic_client, "with_options") else anthropic_client
                resp = long_client.messages.create(
                    model="claude-sonnet-5",
                    max_tokens=2048,
                    system=sonnet_sys,
                    messages=[{"role": "user", "content": init_prompt}],
                )
                text = claude_handler.response_text(resp).strip()
                if text:
                    return {"success": True, "text": text}
        except Exception as e:
            print(f"[content_generator] Claude generation skipped/failed ({e!r}), using Groq")

    # Primary: route through Groq with model_pool and fallback
    try:
        import model_pool
        pool = model_pool.get_pool()
        if pool.get_available_endpoints():
            result = pool.call_model(
                messages=[{"role": "user", "content": prompt}],
                system=CONTENT_SYSTEM_PROMPT,
                json_mode=False,
                timeout=45.0,
                max_tokens=safe_max_tokens,
            )
            text = (result.text or "").strip()
            import re
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            if text:
                akira_quota.record(_PURPOSE)
                print(f"[content_generator] generated {len(text)} chars via {result.provider} ({result.model})")
                return {"success": True, "text": text}
    except Exception as e:
        print(f"[content_generator] model_pool route failed ({e!r}), attempting direct Groq call")

    resp = None
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
                        "content": CONTENT_SYSTEM_PROMPT
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5,
                "max_tokens": safe_max_tokens
            },
            timeout=60
        )
    except requests.RequestException as e:
        print(f"[content_generator] Primary Groq call failed: {e}")

    text = ""
    if resp is not None and resp.status_code == 200:
        try:
            body = resp.json()
            raw_text = (body["choices"][0]["message"]["content"] or "").strip()
            import re
            text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
        except (KeyError, IndexError, ValueError):
            text = ""

    # If primary succeeded and returned text, record and return
    if text:
        akira_quota.record(_PURPOSE)
        print(f"[content_generator] generated {len(text)} chars via Groq ({groq_model})")
        return {"success": True, "text": text}

    # FAILOVER: If primary 429'd or returned empty text, failover to secondary model and key
    fallback_model = os.environ.get("GROQ_ROUTER_FALLBACK_MODEL", "qwen/qwen3.8-27b")
    fallback_key = (os.environ.get("SPEECH_API_KEY") or groq_key).strip()
    if fallback_key:
        print(f"[content_generator] Primary Groq call failed/empty — failing over to {fallback_model}")
        try:
            qwen_tokens = min(words * 2, 450)
            fb_resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {fallback_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": fallback_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": CONTENT_SYSTEM_PROMPT
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": qwen_tokens
                },
                timeout=45
            )
            if fb_resp.status_code == 200:
                fb_body = fb_resp.json()
                fb_raw = (fb_body["choices"][0]["message"]["content"] or "").strip()
                import re
                fb_text = re.sub(r"<think>.*?</think>", "", fb_raw, flags=re.DOTALL).strip()
                if fb_text:
                    akira_quota.record(_PURPOSE)
                    print(f"[content_generator] generated {len(fb_text)} chars via Groq fallback ({fallback_model})")
                    return {"success": True, "text": fb_text}
            else:
                print(f"[content_generator] Groq fallback status {fb_resp.status_code}: {fb_resp.text[:200]}")
        except Exception as fb_err:
            print(f"[content_generator] Groq fallback failed: {fb_err}")

    # ULTIMATE LAST-RESORT FALLBACK: If all free Groq models failed or rate-limited, call Claude as ultimate option
    try:
        import claude_handler
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key and getattr(claude_handler, "client", None) is not None:
            print("[content_generator] All free Groq models exhausted — falling back to Claude as ultimate last option")
            sonnet_sys = CONTENT_SYSTEM_PROMPT + "\nDo not include conversational preambles, meta-commentary, or markdown code fences."
            resp = claude_handler.client.messages.create(
                model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"),
                max_tokens=2048,
                system=sonnet_sys,
                messages=[{"role": "user", "content": prompt}],
            )
            c_text = claude_handler.response_text(resp).strip()
            if c_text:
                print(f"[content_generator] Generated {len(c_text)} chars via ultimate fallback Claude")
                return {"success": True, "text": c_text}
    except Exception as c_err:
        print(f"[content_generator] Ultimate Claude fallback failed: {c_err}")

    return {"success": False, "message": "All generation models (Groq and Claude fallback) were unavailable."}