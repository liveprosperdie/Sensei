"""gateway_server/upstream.py — Upstream LLM Dispatch (Anthropic & Groq) with Zero Content Logging."""

from __future__ import annotations

import logging
import time
import requests
from gateway_server import config

try:
    import anthropic
except ImportError:
    anthropic = None

logger = logging.getLogger("akira.upstream")


def call_upstream_claude(
    messages: list[dict],
    system: str | list | None = None,
    model: str | None = None,
    max_tokens: int = 1600,
    temperature: float = 0.0,
    output_config: dict | None = None
) -> tuple[int, dict]:
    """Relay call to Anthropic Claude using server-held ANTHROPIC_API_KEY.

    Zero Content Logging: Prompts, message contents, and response contents
    are NEVER logged or persisted. Only timestamp, latency, and status are recorded.
    """
    api_key = config.ANTHROPIC_API_KEY
    if not api_key:
        logger.error("[upstream.claude] ANTHROPIC_API_KEY not configured on server.")
        return 500, {"error": "Upstream Anthropic API key is not configured on server."}

    client = anthropic.Anthropic(api_key=api_key, timeout=30.0) if anthropic else None
    if not client:
        return 500, {"error": "anthropic SDK is not installed on server."}

    start_t = time.time()
    model_to_use = model or config.CLAUDE_MODEL
    try:
        kwargs = dict(
            model=model_to_use,
            max_tokens=max_tokens,
            messages=messages,
            system=system if system else "",
        )
        if output_config:
            kwargs["extra_body"] = {"output_config": output_config}

        resp = client.messages.create(**kwargs)
        elapsed = (time.time() - start_t) * 1000
        logger.info("[upstream.claude] Completed in %.1fms (status 200)", elapsed)

        # Serialize response blocks for client
        content_blocks = []
        for b in resp.content:
            b_type = getattr(b, "type", "text")
            b_text = getattr(b, "text", "")
            content_blocks.append({"type": b_type, "text": b_text})

        return 200, {
            "content": content_blocks,
            "stop_reason": getattr(resp, "stop_reason", "end_turn"),
            "model": model_to_use,
            "provider": "anthropic"
        }
    except Exception as e:
        elapsed = (time.time() - start_t) * 1000
        logger.error("[upstream.claude] Call failed in %.1fms: %s", elapsed, str(e))
        return 502, {"error": f"Upstream Claude error: {str(e)}"}


def call_upstream_groq(
    messages: list[dict],
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 1600,
    temperature: float = 0.0,
    response_format: dict | None = None
) -> tuple[int, dict]:
    """Relay call to Groq free API using server-held GROQ_API_KEY.

    Zero Content Logging: Prompts, message contents, and response contents
    are NEVER logged or persisted. Only timestamp, latency, and status are recorded.
    """
    api_key = config.GROQ_API_KEY
    if not api_key:
        logger.error("[upstream.groq] GROQ_API_KEY not configured on server.")
        return 500, {"error": "Upstream GROQ_API_KEY is not configured on server."}

    start_t = time.time()
    model_to_use = model or config.GROQ_MODEL

    turns = []
    if system:
        turns.append({"role": "system", "content": system})
    for m in messages:
        turns.append({"role": m.get("role", "user"), "content": m.get("content", "")})

    payload = {
        "model": model_to_use,
        "messages": turns,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=15.0
        )
        elapsed = (time.time() - start_t) * 1000

        if resp.status_code == 200:
            logger.info("[upstream.groq] Completed in %.1fms (status 200)", elapsed)
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"] or ""
            # Strip reasoning tags
            import re
            clean_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
            return 200, {
                "content": [{"type": "text", "text": clean_text}],
                "stop_reason": data["choices"][0].get("finish_reason", "end_turn"),
                "model": model_to_use,
                "provider": "groq_fallback"
            }
        elif resp.status_code == 429:
            logger.warning("[upstream.groq] Groq rate limited (HTTP 429) in %.1fms", elapsed)
            return 429, {"error": "Upstream Groq rate limit reached. Please wait a moment."}
        else:
            logger.error("[upstream.groq] Groq returned HTTP %d in %.1fms: %s",
                         resp.status_code, elapsed, resp.text[:200])
            return 502, {"error": f"Upstream Groq error: HTTP {resp.status_code}"}
    except Exception as e:
        elapsed = (time.time() - start_t) * 1000
        logger.error("[upstream.groq] Transport failed in %.1fms: %s", elapsed, str(e))
        return 502, {"error": f"Upstream Groq connection failed: {str(e)}"}
