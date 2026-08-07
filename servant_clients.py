"""Servant-tier model clients — the cheap tiers below the Sonnet brain.

WHY THIS MODULE EXISTS
======================
Three tiers, by the shape of the thinking each job needs:

  BRAIN         claude-sonnet-5  — intent routing, deliberation, vault
                                   organisation. Judgement about the user.
  SERVANT_GEN   glm-5.2          — longer-form drafting from evidence already
                                   gathered (note outlines and note bodies).
  SERVANT_MECH  qwen2.5-max      — mechanical reductions: summarise this,
                                   yes or no, which element index.

WHY RAW REQUESTS AND NOT THE openai SDK
---------------------------------------
Both providers speak the OpenAI /chat/completions wire format, so the only
things that differ between them are base_url, model and key. That is a JSON
body and a Bearer header — the openai SDK's convenience layer buys nothing
here and adds a dependency to version-drift on. Same reasoning as
obsidian_api.py using REST directly instead of an SDK. requests is already in
requirements.txt.

This is deliberately NOT the anthropic client with a different model string:
that client speaks Anthropic's /v1/messages format (system as a top-level
param, content as typed blocks) and cannot talk to /chat/completions at all.

FAILURE POLICY — two different failures, two different answers
--------------------------------------------------------------
  * Tier UNAVAILABLE (no API key, transport error, HTTP error, empty reply)
    -> raise ServantUnavailable, and the CALLER falls back to its brain-tier
       model. A missing GLM_API_KEY must degrade to working-but-pricier, never
       to a broken feature.
  * Reply arrived but its JSON is UNUSABLE -> that is a servant-tier bug in
    our own prompt or schema injection for that provider. It is reported
    loudly at the call site and the call fails. It does NOT silently reroute
    to Sonnet, because rerouting would hide the bug permanently while quietly
    charging brain-tier prices for every affected call.
"""

import os
import json
import time

import requests


class ServantJSONError(RuntimeError):
    """A servant tier replied, but not with parseable JSON.

    Distinct from ServantUnavailable on purpose: this means OUR prompt or
    schema injection is wrong for that provider, so it must be visible and
    must NOT be retried on an expensive model.
    """


class ServantUnavailable(RuntimeError):
    """A servant tier could not be reached. Caller should fall back to BRAIN.

    Raised for a missing key, a transport failure, an HTTP error or an empty
    completion — never for a merely malformed reply body, which is our bug and
    must surface rather than be papered over.
    """


class Tier:
    """One servant tier: where to send it, what model, which key unlocks it.

    Model strings and base URLs are user-supplied (verified 2026-08) and
    env-overridable so a provider retiring a model is a .env edit, not a code
    change — the lesson gemini_content.py records about pinned model names
    going stale inside one retirement cycle.
    """

    __slots__ = ("name", "model", "base_url", "key_env")

    def __init__(self, name: str, model: str, base_url: str, key_env: str):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env

    @property
    def api_key(self) -> str | None:
        return (os.environ.get(self.key_env) or "").strip() or None

    @property
    def available(self) -> bool:
        return self.api_key is not None

    def __repr__(self) -> str:
        return f"<Tier {self.name} {self.model}>"


# NOTE ON COST: Qwen's free tier ended April 2026 — qwen2.5-max is paid, just
# very cheap, so SERVANT_MECH reduces spend rather than eliminating it.
# DashScope's maintained line has since moved to Qwen3.x (qwen3-flash and
# similar); qwen2.5-max still serves and is what was specified, but the
# QWEN_MODEL override below is the migration path when that changes.
SERVANT_GEN = Tier(
    "SERVANT_GEN",
    os.environ.get("GLM_MODEL", "glm-5.2"),
    os.environ.get("GLM_BASE_URL", "https://api.z.ai/api/paas/v4/"),
    "GLM_API_KEY",
)

SERVANT_MECH = Tier(
    "SERVANT_MECH",
    os.environ.get("QWEN_MODEL", "qwen2.5-max"),
    os.environ.get("QWEN_BASE_URL",
                   "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "QWEN_API_KEY",
)

DEFAULT_TIMEOUT = 90.0


def call_openai_compatible(tier: Tier, *, system: str, user: str | None = None,
                           messages: list | None = None,
                           max_tokens: int, json_mode: bool = False,
                           timeout: float = DEFAULT_TIMEOUT,
                           label: str = "") -> str:
    """POST one completion to an OpenAI-compatible endpoint. Returns the text.

    Shared by both tiers because the wire format is identical between them —
    only tier.base_url/model/api_key differ. Raises ServantUnavailable on any
    failure to obtain a completion, so the caller can fall back to BRAIN.

    Pass either `user` (single-turn, the common case) or `messages` (a full
    role/content turn list, for the sites that summarise conversation history).
    In the OpenAI format the system prompt is just the leading message, unlike
    Anthropic's top-level `system` param — so it is prepended here rather than
    asking every call site to know that.

    json_mode asks for response_format json_object. Neither provider offers
    grammar-constrained schema output the way Anthropic's json_schema
    output_config does, so this is a request and not a guarantee — which is
    exactly why the callers parse through llm_json's tolerant repair.
    """
    key = tier.api_key
    tag = label or tier.name
    if not key:
        raise ServantUnavailable(
            f"{tier.key_env} is not set, cannot use {tier.name}")
    if (user is None) == (messages is None):
        raise ValueError("pass exactly one of user= or messages=")

    turns = [{"role": "user", "content": user}] if user is not None else [
        {"role": m["role"], "content": m["content"]} for m in messages]
    body: dict = {
        "model": tier.model,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, *turns],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    url = f"{tier.base_url}/chat/completions"
    started = time.monotonic()
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json=body,
            timeout=timeout,
        )
    except Exception as e:
        raise ServantUnavailable(f"{tier.name} transport failed: {e!r}") from e

    elapsed = time.monotonic() - started
    if resp.status_code != 200:
        # Body is truncated into the message: provider errors here are usually
        # a bad model string or an unfunded account, and both are unguessable
        # without the text.
        raise ServantUnavailable(
            f"{tier.name} HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        payload = resp.json()
        text = payload["choices"][0]["message"]["content"] or ""
    except Exception as e:
        raise ServantUnavailable(
            f"{tier.name} returned an unreadable envelope: {e!r} "
            f"{resp.text[:300]}") from e

    usage = payload.get("usage") or {}
    print(f"[tier:{tag}] {tier.name} {tier.model} {elapsed:.2f}s "
          f"in={usage.get('prompt_tokens', '?')} "
          f"out={usage.get('completion_tokens', '?')} "
          f"finish={(payload['choices'][0] or {}).get('finish_reason', '?')}")

    if not text.strip():
        raise ServantUnavailable(f"{tier.name} returned an empty completion")
    return text


def call_json(tier: Tier, *, system: str, user: str, max_tokens: int,
              timeout: float = DEFAULT_TIMEOUT, label: str = "") -> tuple:
    """Servant call whose reply must be JSON. Returns (parsed, info).

    Routed through llm_json.parse for the same reason brain-tier JSON calls
    are: replies arrive fenced, prefixed with prose, or truncated, and
    tolerant repair recovers most of that. Neither provider can be
    grammar-constrained, so repair matters MORE here, not less.

    A reply that survives transport but cannot be parsed raises
    ServantJSONError, which callers surface loudly. It is not a
    ServantUnavailable and must not trigger a brain-tier retry.
    """
    import llm_json

    raw = call_openai_compatible(tier, system=system, user=user,
                                 max_tokens=max_tokens, json_mode=True,
                                 timeout=timeout, label=label)
    parsed, info = llm_json.parse(raw)
    if parsed is None:
        raise ServantJSONError(
            f"{tier.name} reply was not usable JSON (label={label or '-'}, "
            f"info={info}): {raw[:300]}")
    return parsed, info
