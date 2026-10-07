"""Model access for Teaching Mode — FREE-TIER ONLY. Claude/Anthropic is never called.

Every role (head / worker / free) goes through the same resilient chain of free,
OpenAI-compatible endpoints, tried in order until one produces a usable reply:

    Groq gpt-oss-120b -> Cerebras gpt-oss-120b -> Groq qwen3.8-27b
      -> Cerebras qwen-3.8-27b -> Groq gpt-oss-20b

Override with TEACH_MODELS="groq:openai/gpt-oss-120b,cerebras:gpt-oss-120b".
An optional local model (TEACH_LOCAL_URL) is tried first for `worker()` and is the
ONLY option when a source was not cleared for cloud use (`local_only=True`).

Resilience: rate limits / 5xx / truncated / unparsable replies move on to the next
tier (with a short back-off), instead of failing the lesson.

Logging: every call appends one JSON line to <workspace>/_teaching.log with role,
provider, model, latency, token counts and a key-scrubbed error. Prompts and replies
are NEVER logged.

Errors surface as LLMUnavailable with key-scrubbed messages.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

import requests

from . import config  # noqa: F401  (loads .env)
import llm_json


class LLMUnavailable(RuntimeError):
    pass


PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "GEMINI_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
}
DEFAULT_CHAIN = [
    ("groq", "openai/gpt-oss-120b"),
    ("gemini", "gemini-3.5-flash-lite"),
    ("groq", "qwen/qwen3.8-27b"),
    ("gemini", "gemini-flash-latest"),
    ("cerebras", "gpt-oss-120b"),
    ("groq", "openai/gpt-oss-20b"),
]
FAST_CHAIN = [
    ("gemini", "gemini-3.5-flash-lite"),
    ("groq", "openai/gpt-oss-20b"),
    ("gemini", "gemini-flash-latest"),
    ("groq", "openai/gpt-oss-120b"),
    ("cerebras", "gpt-oss-120b"),
]
_KEY_RE = re.compile(r"(sk|gsk|csk|key)[-_][A-Za-z0-9_\-]{8,}")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_LOG_LOCK = threading.Lock()
_LOG_MAX = 1_000_000


def _scrub(msg: str) -> str:
    return _KEY_RE.sub("[key]", str(msg))[:300]


# ── persistent, privacy-safe log ────────────────────────────────────────────

def log_path():
    return config.workspace_root() / "_teaching.log"


def log(event: str, **kv) -> None:
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    rec.update({k: (_scrub(v) if isinstance(v, str) else v) for k, v in kv.items()})
    try:
        p = log_path()
        with _LOG_LOCK:
            if p.exists() and p.stat().st_size > _LOG_MAX:
                p.replace(p.with_suffix(".log.1"))
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ── chain construction ──────────────────────────────────────────────────────

def _chain(fast: bool = False) -> list[tuple[str, str]]:
    env = (os.environ.get("TEACH_MODELS") or "").strip()
    if env:
        out = []
        for part in env.split(","):
            if ":" in part:
                p, m = part.split(":", 1)
                if p.strip() in PROVIDERS and m.strip():
                    out.append((p.strip(), m.strip()))
        if out:
            return out
    chain = FAST_CHAIN if fast else DEFAULT_CHAIN
    return [(p, m) for p, m in chain if (os.environ.get(PROVIDERS[p][1]) or "").strip()]


def local_available() -> bool:
    """True only if a dedicated GENERAL local model is configured (TEACH_LOCAL_URL).

    The :8081 llama-server carries Akira's OS-action LoRAs, which answer
    'unsupported_intent' to tutoring prompts, so it is never used implicitly.
    """
    url = (os.environ.get("TEACH_LOCAL_URL") or "").strip()
    if not url:
        return False
    try:
        return requests.get(url.rstrip("/") + "/models", timeout=1.0).status_code == 200
    except Exception:
        return False


# ── one HTTP call ───────────────────────────────────────────────────────────

class _Retry(Exception):
    def __init__(self, why: str, wait: float = 0.0, skip_tier: bool = False):
        super().__init__(why)
        self.wait, self.skip_tier = wait, skip_tier


def _chat(base: str, key: str, model: str, system: str, user: str, max_tokens: int,
          json_mode: bool, timeout: float) -> tuple[str, dict]:
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = requests.post(base.rstrip("/") + "/chat/completions", json=body, timeout=timeout,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise _Retry(f"transport: {type(e).__name__}", 1.0)
    if r.status_code == 429:
        wait = 2.0
        try:
            wait = min(8.0, float(r.headers.get("retry-after", wait)))
        except ValueError:
            pass
        raise _Retry("rate limited", wait)
    if r.status_code in (404, 401, 403, 402):
        raise _Retry(f"HTTP {r.status_code}", skip_tier=True)
    if r.status_code >= 500:
        raise _Retry(f"HTTP {r.status_code}", 1.0)
    if r.status_code != 200:
        raise _Retry(f"HTTP {r.status_code}: {r.text[:160]}")
    try:
        payload = r.json()
        choice = payload["choices"][0]
        text = choice["message"].get("content") or ""
    except Exception:
        raise _Retry("unreadable envelope")
    finish = choice.get("finish_reason") or "?"
    usage = payload.get("usage") or {}
    text = _THINK_RE.sub("", text).strip()
    if not text:
        raise _Retry("empty completion")
    if finish == "length":
        raise _Retry("truncated")
    return text, {"finish": finish, "in": usage.get("prompt_tokens"), "out": usage.get("completion_tokens")}


def _chat_gemini(base: str, key: str, model: str, system: str, user: str, max_tokens: int,
                 json_mode: bool, timeout: float) -> tuple[str, dict]:
    url = f"{base.rstrip('/')}/{model}:generateContent?key={key}"
    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.2,
        }
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    try:
        r = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise _Retry(f"transport: {type(e).__name__}", 1.0)
    if r.status_code == 429:
        raise _Retry("rate limited", 2.0)
    if r.status_code in (404, 401, 403, 402):
        raise _Retry(f"HTTP {r.status_code}", skip_tier=True)
    if r.status_code >= 500:
        raise _Retry(f"HTTP {r.status_code}", 1.0)
    if r.status_code != 200:
        raise _Retry(f"HTTP {r.status_code}: {r.text[:160]}")
    try:
        data = r.json()
        cand = data["candidates"][0]
        text = cand["content"]["parts"][0]["text"]
        finish = cand.get("finishReason") or "STOP"
    except Exception:
        raise _Retry("unreadable envelope")
    usage = data.get("usageMetadata") or {}
    text = _THINK_RE.sub("", text).strip()
    if not text:
        raise _Retry("empty completion")
    if finish in ("MAX_TOKENS", "length"):
        raise _Retry("truncated")
    return text, {"finish": finish, "in": usage.get("promptTokenCount"), "out": usage.get("candidatesTokenCount")}


def _run(chain, role: str, system: str, user: str, max_tokens: int, json_mode: bool,
         timeout: float, label: str):
    """Walk the chain; return parsed JSON (json_mode) or text. Raise LLMUnavailable."""
    if not chain:
        raise LLMUnavailable("no free model is configured (set GROQ_API_KEY, GEMINI_API_KEY, or CEREBRAS_API_KEY)")
    last = "no attempt"
    for provider, model in chain:
        base, key_env = PROVIDERS[provider]
        key = (os.environ.get(key_env) or "").strip()
        for attempt in range(2):
            # 2nd attempt on the same tier: more headroom, no server-side JSON enforcer
            mt = max_tokens if attempt == 0 else int(max_tokens * 1.6)
            use_json = json_mode and attempt == 0
            t0 = time.monotonic()
            try:
                if provider == "gemini":
                    text, info = _chat_gemini(base, key, model, system, user, mt, use_json, timeout)
                else:
                    text, info = _chat(base, key, model, system, user, mt, use_json, timeout)
                if json_mode:
                    parsed, _ = llm_json.parse(text)
                    if not isinstance(parsed, dict):
                        raise _Retry("unparsable json")
                    result = parsed
                else:
                    result = text
                log("llm_ok", role=role, label=label, provider=provider, model=model,
                    ms=int((time.monotonic() - t0) * 1000), attempt=attempt, **info)
                return result
            except _Retry as e:
                last = f"{provider}/{model}: {e}"
                log("llm_retry", role=role, label=label, provider=provider, model=model,
                    attempt=attempt, why=str(e), ms=int((time.monotonic() - t0) * 1000))
                if e.skip_tier:
                    break
                if e.wait:
                    time.sleep(e.wait)
    log("llm_failed", role=role, label=label, last=last)
    raise LLMUnavailable(f"every free model failed (last: {last})")


# ── public roles ────────────────────────────────────────────────────────────

def free(system: str, user: str, *, max_tokens: int = 900, json_mode: bool = True,
         label: str = "teach-free"):
    """Small plan-check / feedback calls. Fast tiers first."""
    return _run(_chain(fast=True), "free", system, user, max_tokens, json_mode, 60.0, label)


def worker(system: str, user: str, *, max_tokens: int = 2400, json_mode: bool = False,
           local_only: bool = False, label: str = "teach-worker"):
    """Lessons, quizzes, diagrams. Returns (result, ran_locally)."""
    local_url = (os.environ.get("TEACH_LOCAL_URL") or "").strip()
    if local_available():
        try:
            text, _ = _chat(local_url, (os.environ.get("TEACH_LOCAL_KEY") or "local"),
                            os.environ.get("TEACH_LOCAL_MODEL", "default"),
                            system, user, max_tokens, json_mode, 120.0)
            if json_mode:
                parsed, _i = llm_json.parse(text)
                if isinstance(parsed, dict):
                    return parsed, True
            else:
                return text, True
        except _Retry as e:
            log("local_failed", label=label, why=str(e))
    if local_only:
        raise LLMUnavailable("a local model is required for private sources but none is available")
    return _run(_chain(), "worker", system, user, max_tokens, json_mode, 120.0, label), False


def head(system: str, user: str, *, max_tokens: int = 3000, label: str = "teach-head"):
    """Syllabus designer (runs once per course). Always JSON. Free models only."""
    return _run(_chain(), "head", system, user, max_tokens, True, 120.0, label)
