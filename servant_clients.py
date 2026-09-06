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
  * Tier UNAVAILABLE (no API key, transport error, HTTP error, empty reply,
    reply truncated at max_tokens)
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

    __slots__ = ("name", "model", "base_url", "key_env", "lora_index")

    def __init__(self, name: str, model: str, base_url: str, key_env: str,
                 lora_index: int = -1):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env
        self.lora_index = lora_index  # -1 = no LoRA selection (remote API)

    @property
    def api_key(self) -> str | None:
        key = (os.environ.get(self.key_env) or "").strip()
        if key:
            return key
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            return "local"
        return None

    @property
    def available(self) -> bool:
        return self.api_key is not None

    @property
    def is_local(self) -> bool:
        """True when this tier points at a local llama-server."""
        return "localhost" in self.base_url or "127.0.0.1" in self.base_url

    def __repr__(self) -> str:
        return f"<Tier {self.name} {self.model}>"


# NOTE ON COST: Single local llama-server on :8081 with multi-LoRA.
# LoRA indices match the order passed to --lora in start_ai_engines.bat:
#   --lora akira_guard.gguf  → index 0
#   --lora akira_api.gguf    → index 1
#   --lora akira_mech.gguf   → index 2
SERVANT_GEN = Tier(
    "SERVANT_GEN",
    os.environ.get("GLM_MODEL", "akira-api"),
    os.environ.get("GLM_BASE_URL", os.environ.get("SENSEI_LOCAL_API_URL", "http://localhost:8081/v1")),
    "GLM_API_KEY",
    lora_index=1,
)

SERVANT_MECH = Tier(
    "SERVANT_MECH",
    os.environ.get("QWEN_MODEL", "akira-mech"),
    os.environ.get("QWEN_BASE_URL", os.environ.get("SENSEI_LOCAL_MECH_URL", "http://localhost:8081/v1")),
    "QWEN_API_KEY",
    lora_index=2,
)

GUARD = Tier(
    "GUARD",
    os.environ.get("GUARD_MODEL", "akira-guard"),
    os.environ.get("GUARD_BASE_URL", os.environ.get("SENSEI_LOCAL_GUARD_URL", "http://localhost:8081/v1")),
    os.environ.get("GUARD_API_KEY_ENV", "QWEN_API_KEY"),
    lora_index=0,
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

    # Per-request LoRA selection for the local multi-LoRA server.
    # --lora-init-without-apply means no adapter is applied by default;
    # each request must specify which one via the "lora" field.
    if tier.is_local and tier.lora_index >= 0:
        body["lora"] = [{"id": tier.lora_index, "scale": 1.0}]

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
    finish = (payload["choices"][0] or {}).get("finish_reason") or "?"
    print(f"[tier:{tag}] {tier.name} {tier.model} {elapsed:.2f}s "
          f"in={usage.get('prompt_tokens', '?')} "
          f"out={usage.get('completion_tokens', '?')} "
          f"finish={finish}")

    if not text.strip():
        raise ServantUnavailable(f"{tier.name} returned an empty completion")

    # TRUNCATION IS UNAVAILABILITY, NOT A REPLY.
    # finish_reason == "length" means the servant ran out of budget mid-sentence.
    # Returning that text would hand a half-finished summary straight to TTS
    # (summarize_text) or a half-finished verdict to a destructive-action gate
    # (ask_confirmation), with nothing in the logs pointing at why. Raising
    # ServantUnavailable reuses the one fallback path every caller already
    # implements — the brain tier retries the same job with more headroom —
    # rather than adding a second return channel that nine call sites would
    # have to remember to inspect. It is NOT ServantJSONError: a truncated
    # reply is a budget problem, not a bug in our prompt or schema injection.
    if finish == "length":
        raise ServantUnavailable(
            f"{tier.name} reply was truncated (finish_reason=length at "
            f"max_tokens={max_tokens}, label={tag}): {text[-120:]!r}")
    return text


def call_json(tier: Tier, *, system: str, user: str, max_tokens: int,
              timeout: float = DEFAULT_TIMEOUT, label: str = "") -> tuple:
    """Servant call whose reply must be JSON. Returns (parsed, info).

    Routed through llm_json.parse for the same reason brain-tier JSON calls
    are: replies arrive fenced or prefixed with prose, and tolerant repair
    recovers most of that. Neither provider can be grammar-constrained, so
    repair matters MORE here, not less. Truncated replies no longer reach the
    parser at all — call_openai_compatible raises ServantUnavailable on
    finish_reason=length, so a cut-off body is a fallback, not a parse failure
    that would otherwise be misreported as ServantJSONError.

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