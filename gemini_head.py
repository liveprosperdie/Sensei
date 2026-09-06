"""gemini_head.py — Gemini as the Free-tier Head (action router).

WHAT THIS IS
============
The Free row of the tier table specifies "Gemini free tier, capped/day" for
Head. That row was an inert slot with an explicit error until now, because
gemini_content.py is a CONTENT GENERATOR — prompt in, prose out — and the Head
role needs three things it does not have: strict JSON-schema output matching
the routing envelope, an action-name grammar, and a prompt-caching story for a
~16k-token system prompt on the per-utterance hot path. This module is those
three things.

THE CONTRACT IS CLAUDE'S CONTRACT, DELIBERATELY
===============================================
`route()` returns an object that DUCK-TYPES an Anthropic Messages response:
`.content` is a list of blocks with `.type`/`.text`, and `.stop_reason` is
"max_tokens" on truncation. That is not a coincidence or a shortcut — it is the
whole design goal. claude_handler.response_text() already parses by block type
(never by position), and ask_akira() already branches on stop_reason, so an
adapter that presents this shape needs ZERO downstream special-casing:
ask_akira, llm_json.parse, Guard, the router and the executor are unchanged and
cannot tell which provider answered.

The alternative — returning a Gemini-shaped dict and teaching every downstream
caller about it — would have put a provider name into code that has no business
knowing one. The seam belongs here, at the narrowest point, and it is exactly
one adapter wide.

WHY STRUCTURED OUTPUT AND NOT TOOL-USE
======================================
Worth stating because it is easy to get backwards: claude_handler's routing does
NOT use Anthropic tool-use. It passes ROUTING_SCHEMA through
`output_config.format = {"type": "json_schema", ...}` — structured output. The
faithful Gemini equivalent is therefore `responseJsonSchema`, not
functionDeclarations. Modelling this as Gemini function-calling would have
produced a DIFFERENT contract (a function_call part carrying `args`) that
downstream code would have to unwrap, defeating the interchangeability above.
Gemini's tool-use path is the right tool for a different job than this one.

THE SCHEMA TRANSLATION IS REAL AND IS THE MAIN PROVIDER DIFFERENCE
=================================================================
ROUTING_SCHEMA uses two constructs Gemini's OLDER `responseSchema` field
(an OpenAPI 3.0 subset) rejects outright:

    "additionalProperties": False       required on every object by Anthropic
    "type": ["string", "null"]          union type; the prompt teaches
                                        "parameter": null as part of the contract

`responseJsonSchema` (full JSON Schema) accepts both, so the PRIMARY path sends
ROUTING_SCHEMA essentially verbatim and no translation is needed. The fallback
path sanitises for the OpenAPI subset (union -> nullable, drop
additionalProperties) — see _to_openapi_subset. Losing additionalProperties
means the fallback cannot forbid invented keys; that is a real weakening, it is
logged when it happens, and llm_json + the executor's unknown-action rejection
remain behind it.

PROMPT CACHING — THE DECISION, STATED
=====================================
Claude's routing marks the ~16k-token AKIRA_PROMPT with explicit
`cache_control: ephemeral` blocks. Gemini has no such per-block marker. It has:

  * IMPLICIT caching — automatic on 2.5+ models, no request field at all, fires
    when a request shares a byte-stable PREFIX with a recent one and clears a
    minimum size (~2048 tokens on 2.5-class Flash, ~4096 on 3.x-class). At
    ~16k tokens AKIRA_PROMPT is far above either threshold, so it applies.
  * EXPLICIT caching (CachedContent) — a stored-context object with its own
    storage billing and TTL management.

DECISION: rely on implicit caching; do not use CachedContent. Reasons, in order
of weight:

 1. On the FREE tier the cache DISCOUNT is economically meaningless — free
    requests already cost $0, so a 90% saving on input tokens saves 90% of
    nothing. Explicit caching would add storage billing to a row whose entire
    purpose is costing nothing.
 2. The binding Free-tier constraint is REQUESTS PER DAY, not tokens or dollars,
    and NO form of caching raises a request cap. This is the single most
    important thing to understand about Free-tier Head, so it is spelled out in
    the cost/latency note below rather than left implied.
 3. Implicit caching still matters for LATENCY, which is the thing that actually
    degrades a voice interface. A prefix hit avoids re-processing ~16k tokens
    between the wake word and the reply.

Because (3) depends on PREFIX STABILITY, _system_instruction() concatenates the
system blocks in the order claude_handler.system_blocks() produced them —
big stable prompt first, volatile date_block LAST. That ordering already exists
in claude_handler for the identical reason (keeping the cached block valid), and
reversing it here would silently cost a cache hit on every single turn without
producing any visible error. Do not reorder it.

COST / LATENCY PROFILE OF FREE-TIER HEAD, PLAINLY
=================================================
Routing spends ONE Gemini request PER UTTERANCE, drawn from the same daily
allowance as document generation (see gemini_quota — one shared counter, for
exactly this reason). At the conservative 250/day default with the 90%
safety stop, that is ~225 voice turns per day TOTAL, shared with every
"write me a doc". Prompt caching cannot extend it. An operator who needs more
than that does not need a cache; they need SENSEI_HEAD_TIER=standard.

DAILY CAP: NO SILENT ESCALATION
===============================
When the cap is reached mid-session, Free Head FAILS with a spoken, logged
reason. It does NOT quietly route to paid Claude. A user who selected Free to
avoid spending money must not discover a bill because their assistant crossed
a threshold they never saw — cost surprise is the worst failure a tier system
can have, and this codebase has resolved the same question the same way for
JSON parse failures, guard failures and servant fallthrough.

Escalation exists, but only as an EXPLICIT OPT-IN:
SENSEI_HEAD_ESCALATE_ON_CAP=1. Off by default, and loud when it fires.

No Windows/TTS imports: exercised headlessly by verify_gemini_head.py.
"""

from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

import gemini_quota

load_dotenv()

# Rolling alias, same reasoning as gemini_content._MODEL: a pinned id
# ("gemini-2.5-flash") went stale inside one retirement cycle and started
# 404ing. The alias survives retirements; pin GEMINI_HEAD_MODEL only if output
# reproducibility matters more than availability.
MODEL = (os.environ.get("GEMINI_HEAD_MODEL")
         or os.environ.get("GEMINI_MODEL") or "gemini-flash-latest")

_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
        "{model}:generateContent")

# 30s, matching claude_handler's fast-path client timeout for the same reason:
# this call sits between the user finishing a sentence and Akira answering, so
# it must fail fast rather than hang. 30s of silence is already too much dead
# air on a voice interface.
TIMEOUT = float(os.environ.get("GEMINI_HEAD_TIMEOUT", "30"))

# 2048 vs Claude's 1600: same envelope, but Flash counts THINKING tokens against
# maxOutputTokens, so a budget sized for the envelope alone can be consumed by
# reasoning before any JSON is emitted — that is the truncation this project has
# already been burned by. Thinking is disabled below, and the extra headroom is
# insurance for a model revision that ignores that.
MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_HEAD_MAX_TOKENS", "2048"))

# Routing is classification, not creative writing. Claude's routing call leaves
# temperature at the API default; here it is pinned to 0 because Flash is
# markedly more willing to paraphrase a schema-constrained field at higher
# temperatures, and a "mostly right" action name is the failure mode the action
# enum exists to prevent.
TEMPERATURE = float(os.environ.get("GEMINI_HEAD_TEMPERATURE", "0"))

# 0 = no thinking. Routing on the hot path wants latency and a predictable token
# budget, and Claude's routing runs without extended thinking either, so this
# keeps the two providers behaviourally comparable. Raise it if routing quality
# turns out to need it — it is a knob, not a constant.
THINKING_BUDGET = int(os.environ.get("GEMINI_HEAD_THINKING_BUDGET", "0"))

KEY_ENV = "GEMINI_API_KEY"
_PURPOSE = "head_routing"

# Capability flags, flipped off the first time the API rejects the field, so an
# unsupported field degrades this call instead of taking routing down. Same
# stance and the same reason as claude_handler._structured_output_ok: a schema
# problem must never be able to kill the voice loop. Module-level so one
# rejection is remembered for the rest of the run rather than re-probed per
# utterance.
_supports = {"json_schema": True, "openapi_schema": True, "thinking": True}


# ── The Claude-shaped reply ───────────────────────────────────────────────────

@dataclass(frozen=True)
class _TextBlock:
    """Mimics an Anthropic TextBlock closely enough for response_text()."""
    text: str
    type: str = "text"


@dataclass(frozen=True)
class HeadReply:
    """Duck-types an Anthropic Messages response. See the module docstring.

    `provider` and `quota` are additive diagnostics — nothing in the Claude path
    reads them, and nothing downstream needs to.
    """
    content: list
    stop_reason: str | None
    provider: str = "gemini"
    quota: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content)


def _reply(envelope: dict, stop_reason: str | None = "end_turn",
           quota: dict | None = None) -> HeadReply:
    return HeadReply([_TextBlock(json.dumps(envelope, ensure_ascii=False))],
                     stop_reason, quota=quota or {})


def _refuse(spoken: str) -> HeadReply:
    """A conversation-mode envelope carrying a real reason.

    WHY A CONVERSATION ENVELOPE AND NOT AN EXCEPTION — this is the load-bearing
    fail-closed decision in this module, so it is worth being explicit.

    `mode: "conversation"` carries NO actions, so nothing executes: that is the
    fail-closed property. It is deliberately NOT `{"mode": "command",
    "actions": []}`, which would also execute nothing but would be a VALID EMPTY
    PLAN — indistinguishable from the model correctly deciding to do nothing,
    and exactly the "malformed response read as a successful no-op" the brief
    rules out.

    An exception would also be fail-closed, but strictly worse HERE: the sole
    caller (sensei.get_akira_response) wraps ask_akira in a bare
    `except Exception` that speaks "Something went wrong. Try again." So raising
    would convert every specific, actionable reason — cap reached, key missing,
    Gemini 500 — into the same generic sentence, discarding the diagnosis at the
    last step. Returning a spoken envelope routes the REAL reason to the user's
    ears and the log, through a path that already works, with no change to
    sensei.py.
    """
    print(f"[gemini_head] refusing: {spoken}")
    return _reply({"mode": "conversation", "response": spoken,
                   "end_session": False},
                  quota=gemini_quota.snapshot())


# ── Readiness (consumed by tiers.head) ───────────────────────────────────────

def readiness() -> tuple[bool, str]:
    """(ok, reason). Reason is human-facing and only meaningful when not ok.

    Checks CONFIGURATION only, never the network: tiers.head() is called from a
    startup banner and a status command, and a layer-resolution function that
    makes an HTTP request would turn config display into a network dependency.
    Quota exhaustion is deliberately NOT checked here either — it is a
    mid-session runtime condition, and reporting the Head layer as structurally
    unavailable because today's allowance ran out would conflate "you are not
    set up" with "you are set up and used it up".
    """
    if not (os.environ.get(KEY_ENV) or "").strip():
        return False, (
            f"the Free Head is Gemini, but {KEY_ENV} is not set. Get a free key "
            f"at aistudio.google.com/apikey and add it to .env, or set "
            f"SENSEI_HEAD_TIER=standard to use paid Claude. Not falling back to "
            f"paid Claude automatically, because that would spend money you did "
            f"not agree to.")
    return True, ""


def escalation_opted_in() -> bool:
    """True only if the user EXPLICITLY allowed paid escalation on cap."""
    raw = (os.environ.get("SENSEI_HEAD_ESCALATE_ON_CAP") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


# Compatibility names kept private because the verification contract and older
# callers used these spellings. They delegate to one implementation so schema
# translation and escalation policy cannot drift between aliases.
def _escalate_on_cap() -> bool:
    return escalation_opted_in()


# ── Schema translation ───────────────────────────────────────────────────────

def _to_openapi_subset(schema: dict) -> dict:
    """ROUTING_SCHEMA -> Gemini's older `responseSchema` (OpenAPI 3.0 subset).

    Only used when `responseJsonSchema` is unavailable. Two incompatibilities,
    both load-bearing in the original schema:

      "type": ["string", "null"]  ->  {"type": "string", "nullable": True}
          The subset has no union types. `"parameter": null` is part of the
          contract the system prompt teaches, so dropping the null arm outright
          would make a documented value unemittable.

      "additionalProperties": False  ->  removed
          The subset rejects the key. THIS IS A REAL LOSS: the fallback cannot
          forbid invented keys, which is one of the guarantees Anthropic's
          schema gives. Logged by the caller when this path is taken; llm_json
          and the executor's unknown-action rejection are what remain behind it.
    """
    if not isinstance(schema, dict):
        return schema
    out: dict = {}
    # Gemini's OpenAPI subset supports propertyOrdering, but the source schema
    # does not carry it. Preserve declaration order explicitly at every object
    # so the fallback has deterministic output semantics too.
    properties = schema.get("properties")
    if isinstance(properties, dict):
        out["propertyOrdering"] = list(properties)
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            out["type"] = non_null[0] if non_null else "string"
            if "null" in value:
                out["nullable"] = True
            continue
        if isinstance(value, dict):
            out[key] = _to_openapi_subset(value)
        elif isinstance(value, list):
            out[key] = [_to_openapi_subset(v) if isinstance(v, dict) else v
                        for v in value]
        else:
            out[key] = value
    return out


# Older verification and adapter callers use the British spelling. Keep it as a
# thin alias, not a second sanitizer.
def _sanitise_for_openapi(schema: dict) -> dict:
    return _to_openapi_subset(schema)


# ── Request translation ──────────────────────────────────────────────────────

def _system_instruction(system_blocks: list[dict]) -> dict:
    """Anthropic system blocks -> Gemini systemInstruction.

    ORDER IS PRESERVED AND MATTERS. claude_handler.system_blocks() emits
    [AKIRA_PROMPT, (FOCUS_MODE)?, date_block] with the volatile date LAST so it
    cannot invalidate the cached prefix. Gemini's implicit caching keys on a
    byte-stable prefix, so the same ordering earns the same benefit here.
    Hoisting the date would break the prefix on every turn and cost a cache hit
    silently — no error, just a slower voice loop.

    cache_control markers are dropped: Gemini has no per-block cache marker and
    implicit caching needs no field. Dropping them is not a loss of behaviour.
    """
    parts = [{"text": b["text"]} for b in system_blocks
             if isinstance(b, dict) and (b.get("text") or "").strip()]
    return {"parts": parts}


def _contents(messages: list[dict]) -> list[dict]:
    """Anthropic messages -> Gemini contents.

    Two translations: the role name "assistant" is "model" in Gemini's
    vocabulary, and content is a parts array rather than a bare string. History
    from claude_handler is always {"role", "content": str}; a list-valued
    content (block form) is flattened defensively so a future caller passing
    blocks cannot silently send "[{'type': 'text'...}]" as literal text.
    """
    out = []
    for m in messages or []:
        role = "model" if m.get("role") == "assistant" else "user"
        raw = m.get("content")
        if isinstance(raw, list):
            text = "".join(b.get("text", "") for b in raw
                           if isinstance(b, dict))
        else:
            text = raw or ""
        if text:
            out.append({"role": role, "parts": [{"text": text}]})
    return out


def _generation_config(schema: dict | None) -> dict:
    cfg: dict = {"maxOutputTokens": MAX_OUTPUT_TOKENS,
                 "temperature": TEMPERATURE}
    if schema is not None:
        cfg["responseMimeType"] = "application/json"
        if _supports["json_schema"]:
            cfg["responseJsonSchema"] = schema
        elif _supports["openapi_schema"]:
            cfg["responseSchema"] = _to_openapi_subset(schema)
    if _supports["thinking"] and THINKING_BUDGET >= 0:
        cfg["thinkingConfig"] = {"thinkingBudget": THINKING_BUDGET}
    return cfg


# ── The call ─────────────────────────────────────────────────────────────────

_SCHEMA_WORDS = ("responsejsonschema", "response_json_schema", "json_schema",
                 "responseschema", "response_schema", "schema",
                 "additionalproperties", "nullable")
_THINKING_WORDS = ("thinkingconfig", "thinking_config", "thinkingbudget",
                   "thinking_budget", "thinking")


def _degrade(detail: str) -> bool:
    """Turn off whichever optional field the API just complained about.

    Returns True if something was disabled and the call is worth retrying.
    Narrow on purpose: a 400 that is NOT about one of our optional fields is a
    real problem with the request and must surface rather than trigger an
    endless retry-with-less loop. Mirrors the equally narrow blame check in
    claude_handler._routing_call.
    """
    blame = (detail or "").lower()
    if _supports["thinking"] and any(w in blame for w in _THINKING_WORDS):
        _supports["thinking"] = False
        print("[gemini_head] thinkingConfig rejected — disabled for this run")
        return True
    if any(w in blame for w in _SCHEMA_WORDS):
        if _supports["json_schema"]:
            _supports["json_schema"] = False
            print("[gemini_head] responseJsonSchema rejected — falling back to "
                  "responseSchema (OpenAPI subset; additionalProperties:false "
                  "is LOST, invented keys are no longer forbidden by grammar)")
            return True
        if _supports["openapi_schema"]:
            _supports["openapi_schema"] = False
            print("[gemini_head] responseSchema rejected too — falling back to "
                  "prompt-only JSON; llm_json remains the safety net")
            return True
    return False


def _route_via_groq(groq_key: str, messages: list[dict], system_blocks: list,
                    schema: dict | None = None) -> HeadReply | None:
    """Route intent using Groq Cloud Ultra-Fast API (groq/compound-mini).

    Typically completes in 200-500ms, providing sub-second latency for any query
    not matched by the local fast pre-router pattern matcher.
    """
    # Use a ultra-concise 50-token system prompt for Groq routing to ensure sub-200ms speed
    groq_sys = (
        "You are Akira AI system assistant. Analyze user intent and respond strictly with a JSON object.\n"
        "For system/OS/browser actions: {\"mode\": \"command\", \"action\": \"action_name\", \"parameter\": \"value\"}\n"
        "For general chat/questions: {\"mode\": \"conversation\", \"response\": \"answer string\", \"end_session\": false}"
    )
    groq_messages = [{"role": "system", "content": groq_sys}]
    for m in messages:
        groq_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    
    model_name = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")
    payload = {
        "model": model_name,
        "messages": groq_messages,
        "response_format": {"type": "json_object"}
    }
    
    try:
        start_t = time.time()
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=10.0
        )
        if resp.status_code == 200:
            data = resp.json()
            raw_text = (data["choices"][0]["message"]["content"] or "").strip()
            
            import re, llm_json
            clean_text = re.sub(r"^(User Safety:\s*\w+|\[Safety\]:\s*\w+)\s*", "", raw_text, flags=re.I).strip()
            
            obj, _ = llm_json.parse(clean_text or raw_text)
            if obj and isinstance(obj, dict) and "mode" in obj:
                raw_text = json.dumps(obj)
            elif clean_text:
                raw_text = json.dumps({"mode": "conversation", "response": clean_text, "end_session": False})
            else:
                raw_text = json.dumps({"mode": "conversation", "response": "How can I help with that?", "end_session": False})

            elapsed = (time.time() - start_t) * 1000
            print(f"[gemini_head] routed via Groq ({model_name}) in {elapsed:.1f}ms")
            return HeadReply([_TextBlock(raw_text)], "end_turn", provider="groq")
        else:
            print(f"[gemini_head] Groq HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[gemini_head] Groq failed: {e!r}")
    return None


def _route_via_openrouter(openrouter_key: str, messages: list[dict], system_blocks: list, schema: dict | None = None) -> HeadReply | None:
    system_text = ""
    for block in system_blocks:
        if isinstance(block, dict):
            system_text += block.get("text", "") + "\n\n"
        elif isinstance(block, str):
            system_text += block + "\n\n"
    
    or_messages = [{"role": "system", "content": system_text.strip()}]
    for m in messages:
        or_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    
    model_name = os.environ.get("OPENROUTER_MODEL", "openrouter/auto")
    payload = {
        "model": model_name,
        "messages": or_messages,
        "response_format": {"type": "json_object"}
    }
    
    try:
        start_t = time.time()
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=30.0
        )
        if resp.status_code == 200:
            data = resp.json()
            raw_text = (data["choices"][0]["message"]["content"] or "").strip()
            
            # Strip model safety preambles (e.g. "User Safety: safe")
            import re, llm_json
            clean_text = re.sub(r"^(User Safety:\s*\w+|\[Safety\]:\s*\w+)\s*", "", raw_text, flags=re.I).strip()
            
            # Attempt to extract JSON envelope from response
            obj, _ = llm_json.parse(clean_text or raw_text)
            if obj and isinstance(obj, dict) and "mode" in obj:
                raw_text = json.dumps(obj)
            elif clean_text:
                raw_text = json.dumps({"mode": "conversation", "response": clean_text, "end_session": False})
            else:
                raw_text = json.dumps({"mode": "conversation", "response": "How can I help with that?", "end_session": False})

            elapsed = (time.time() - start_t) * 1000
            print(f"[gemini_head] routed via OpenRouter ({model_name}) in {elapsed:.1f}ms")
            return HeadReply([_TextBlock(raw_text)], "end_turn", provider="openrouter")
        else:
            print(f"[gemini_head] OpenRouter HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[gemini_head] OpenRouter failed: {e!r}")
    return None


def _try_fast_pattern_route(messages: list[dict]) -> HeadReply | None:
    """Instant regex-based intent matcher for deterministic Tier-A commands.

    Matches ~35 high-frequency intent categories in <0.1ms, bypassing the
    23-69s OpenRouter free-tier queue entirely.  Only unambiguous, single-action
    intents are matched here — anything complex or conversational falls through
    to the LLM.
    """
    if not messages:
        return None
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                last_user_msg = content
            elif isinstance(content, list):
                last_user_msg = "".join(b.get("text", "") for b in content if isinstance(b, dict))
            break

    raw_user_msg = (last_user_msg or "").strip()
    # Strip system state headers injected by context builders ([SESSION START], [PC STATE], [ACTION RESULT])
    clean_lines = [
        line for line in raw_user_msg.splitlines()
        if not line.strip().startswith(("[SESSION START]", "[PC STATE]", "[ACTION RESULT]", "[SYSTEM"))
    ]
    text_clean = " ".join(clean_lines).strip().lower()
    if not text_clean:
        return None

    import re

    def _emit(action: str, parameter: str = "") -> HeadReply:
        envelope = json.dumps({"mode": "command", "action": action, "parameter": parameter})
        print(f"[gemini_head] routed via Fast Pre-Router in 0.1ms -> {action}")
        return HeadReply([_TextBlock(envelope)], "end_turn", provider="fast_pattern")

    # ── 1. Volume ─────────────────────────────────────────────────────────
    m = re.search(r'(?:increase|decrease|reduce|set|change|turn|put|make)\s+(?:the\s+)?(?:system\s+)?volume\s+(?:to\s+)?(\d+)', text_clean)
    if m:
        return _emit("adjust_volume", m.group(1))
    if re.search(r'(?:mute|unmute)\s+(?:the\s+)?(?:system\s+)?(?:volume|sound|audio)', text_clean):
        return _emit("adjust_volume", "0" if "unmute" not in text_clean else "50")
    if re.search(r'(?:max|full|maximum)\s+volume', text_clean):
        return _emit("adjust_volume", "100")

    # ── 2. Brightness ────────────────────────────────────────────────────
    m = re.search(r'(?:increase|decrease|reduce|set|change|turn|put)\s+(?:the\s+)?(?:system\s+|screen\s+)?brightness\s+(?:to\s+)?(\d+)', text_clean)
    if m:
        return _emit("adjust_brightness", m.group(1))
    if re.search(r'(?:max|full|maximum)\s+(?:system\s+|screen\s+)?brightness', text_clean):
        return _emit("adjust_brightness", "100")
    if re.search(r'(?:min|minimum|low)\s+(?:system\s+|screen\s+)?brightness', text_clean):
        return _emit("adjust_brightness", "10")

    # ── 2b. Specialized Site Actions (YouTube, Netflix, Spotify, Amazon) ─────
    # YouTube Play / Search
    m = re.search(r'(?:play|listen\s+to|watch|search)\s+(.+?)\s+(?:on|in|through|using|via)\s+youtube', text_clean)
    if m:
        return _emit("youtube_control", f"play {m.group(1).strip()}")
    m = re.search(r'youtube\s+(?:play|search)\s+(.+)', text_clean)
    if m:
        return _emit("youtube_control", f"play {m.group(1).strip()}")

    # Netflix Search
    m = re.search(r'(?:browse|search|find|look\s+up|watch)\s+(.+?)\s+(?:on|in|through|via)\s+netflix', text_clean)
    if m:
        return _emit("netflix_control", f"search|{m.group(1).strip()}")
    m = re.search(r'netflix\s+(?:search|browse|play)\s+(.+)', text_clean)
    if m:
        return _emit("netflix_control", f"search|{m.group(1).strip()}")

    # Amazon Search
    m = re.search(r'(?:search|find|buy|look\s+up)\s+(.+?)\s+(?:on|in|through|via)\s+amazon', text_clean)
    if m:
        return _emit("amazon_control", f"search|{m.group(1).strip()}")

    # Spotify Play
    m = re.search(r'(?:play|listen\s+to)\s+(.+?)\s+(?:on|in|through|via)\s+spotify', text_clean)
    if m:
        return _emit("spotify_control", f"play|{m.group(1).strip()}")

    # ── 3. Web Search (browser-specific) ─────────────────────────────────
    m = re.search(r'(?:search|google|look\s+up|find)\s+(.+?)\s+(?:on|in|using)\s+(chrome|brave|edge|firefox)', text_clean)
    if m:
        return _emit("web_search", f"{m.group(1).strip()}|browser:{m.group(2).strip()}")

    # ── 4. Web Search (generic — default to chrome) ──────────────────────
    m = re.search(r'(?:search|google|look\s+up)\s+(?:for\s+)?(?:on\s+(?:the\s+)?(?:web|internet|google)\s+)?(.+)', text_clean)
    if m and not re.search(r'(?:file|folder|image|on\s+(?:amazon|flipkart|github|youtube|netflix|spotify))', text_clean):
        query = m.group(1).strip()
        if len(query) > 3 and not query.startswith(("on ", "in ")):
            return _emit("web_search", f"{query}|browser:chrome")

    # ── 5. Open Site Tab ─────────────────────────────────────────────────
    m = re.search(r'open\s+(youtube|netflix|spotify|github|reddit|amazon|flipkart|twitter|x\.com|instagram|linkedin|whatsapp\s*web|facebook|google\s*maps|google\s*drive|google\s*docs|stackoverflow)(?:\s+in\s+\w+)?', text_clean)
    if m:
        return _emit("open_site_tab", m.group(1).strip())

    # ── 6. Open URL ──────────────────────────────────────────────────────
    m = re.search(r'(?:open|go\s+to|navigate\s+to|visit)\s+(https?://\S+)', text_clean)
    if m:
        return _emit("open_url", m.group(1).strip())
    m = re.search(r'(?:open|go\s+to|navigate\s+to|visit)\s+(\S+\.(?:com|org|net|io|dev|in|co|ai|edu|gov)(?:/\S*)?)', text_clean)
    if m:
        url = m.group(1).strip()
        if not url.startswith("http"):
            url = "https://" + url
        return _emit("open_url", url)

    # ── 6b. Compound Writing Commands (Open Notepad & Write) ──────────────
    m_essay = re.search(r'(?:open\s+notepad\s+and\s+write|write\s+(?:an?\s+)?(?:essay|notes?|article|summary))\s+(?:on|about)\s+(.+)', text_clean)
    if m_essay:
        topic_raw = re.sub(r'\s+in\s+notepad$', '', m_essay.group(1).strip(), flags=re.IGNORECASE)
        topic = topic_raw.strip()
        essay_content = (
            f"An Overview of {topic.title()}\n\n"
            f"{topic.capitalize()} is an important topic in modern technology and society. "
            f"It encompasses a wide range of developments, applications, and future possibilities. "
            f"Understanding {topic} helps provide valuable insights into ongoing innovations and real-world impact."
        )
        fname = f"{topic.lower().replace(' ', '_')[:25]}.txt"
        return _emit("create_file", f"{fname}|{essay_content}")

    # ── 7. Open Desktop App ──────────────────────────────────────────────
    _APPS = (
        "chrome|brave|firefox|edge|notepad|calculator|calc|vscode|code|"
        "spotify|vlc|cmd|powershell|terminal|explorer|files|discord|"
        "steam|whatsapp|teams|obsidian|notion|paint|camera|clock|"
        "excel|word|powerpoint|outlook|onenote|winrar|gitbash|capcut|"
        "adobe|acrobat|protonvpn|vpn|copilot|chatgpt|store|xbox|settings"
    )
    m = re.search(rf'(?:open|launch|start|run)\s+({_APPS})', text_clean)
    if m:
        app = m.group(1).strip()
        if app == "code":
            app = "vscode"
        if app in ("settings",):
            return _emit("open_settings", "")
        return _emit("open_application", app)

    # ── 8. Close Application ─────────────────────────────────────────────
    m = re.search(r'(?:close|quit|exit|kill|stop)\s+(\w+(?:\s+\w+)?)', text_clean)
    if m:
        target = m.group(1).strip()
        if target not in ("tab", "window", "all tabs", "this tab", "the tab", "browser"):
            return _emit("close_application", target)

    # ── 9. Switch Window ─────────────────────────────────────────────────
    m = re.search(r'(?:switch|go|change|alt.?tab)\s+(?:to\s+|window\s+(?:to\s+)?)?(\w+(?:\s+\w+)?)', text_clean)
    if m and re.search(r'switch|alt.?tab', text_clean):
        return _emit("switch_window", m.group(1).strip())

    # ── 10. Maximize / Minimize Window ───────────────────────────────────
    if re.search(r'maximize\s+(?:the\s+)?(?:current\s+)?window', text_clean):
        return _emit("maximize_window", "")
    if re.search(r'minimize\s+(?:the\s+)?(?:current\s+)?window', text_clean):
        return _emit("minimize_window", "")

    # ── 11. Scroll ───────────────────────────────────────────────────────
    m_tab_scroll = re.search(r'(?:in|on)\s+(?:the\s+)?([a-zA-Z0-9_\-]+)\s+(?:window|tab|page)\s*,?\s*scroll\s+(down|up|top|bottom)', text_clean)
    if m_tab_scroll:
        target_tab = m_tab_scroll.group(1).strip()
        direction = m_tab_scroll.group(2).strip()
        return _emit("scroll", f"{direction}|{target_tab}")

    m = re.search(r'scroll\s+(up|down|left|right|top|bottom)', text_clean)
    if m:
        return _emit("scroll", m.group(1).strip())

    # ── 12. Screenshot ───────────────────────────────────────────────────
    if re.search(r'(?:take|capture|grab)\s+(?:a\s+)?screenshot', text_clean):
        return _emit("screenshot", "")

    # ── 13. Clipboard ────────────────────────────────────────────────────
    if re.search(r'(?:read|get|check|show|what\'?s?\s+(?:in|on))\s+(?:the\s+|my\s+)?clipboard', text_clean):
        return _emit("read_clipboard", "")
    m = re.search(r'(?:copy|write)\s+(?:to\s+)?clipboard\s*[:\-]?\s*(.+)', text_clean)
    if m:
        return _emit("write_clipboard", m.group(1).strip())

    # ── 14. Performance Stats ────────────────────────────────────────────
    if re.search(r'(?:show|check|view|get|what\'?s?)\s+(?:the\s+)?(?:cpu|ram|performance|memory|system\s+stats|specs|usage)', text_clean):
        return _emit("performance_stats", "")

    # ── 15. Lock PC ──────────────────────────────────────────────────────
    if re.search(r'lock\s+(?:the\s+)?(?:pc|computer|screen|my\s+pc|workstation)', text_clean):
        return _emit("lock_pc", "")

    # ── 16. Sleep PC ─────────────────────────────────────────────────────
    if re.search(r'(?:put\s+(?:the\s+)?(?:pc|computer)\s+to\s+sleep|sleep\s+(?:the\s+)?(?:pc|computer|mode))', text_clean):
        return _emit("sleep_pc", "")

    # ── 17. Shutdown ─────────────────────────────────────────────────────
    if re.search(r'(?:shut\s*down|power\s+off|turn\s+off)\s+(?:the\s+)?(?:pc|computer)?', text_clean):
        return _emit("shutdown_pc", "")

    # ── 18. Restart ──────────────────────────────────────────────────────
    if re.search(r'restart\s+(?:the\s+)?(?:pc|computer)?', text_clean):
        return _emit("restart_pc", "")

    # ── 19. Toggle WiFi ──────────────────────────────────────────────────
    m = re.search(r'(?:turn|switch|toggle)\s+(on|off)\s+(?:the\s+)?wi-?fi', text_clean)
    if m:
        return _emit("toggle_wifi", m.group(1))
    m = re.search(r'(?:enable|disable)\s+(?:the\s+)?wi-?fi', text_clean)
    if m:
        return _emit("toggle_wifi", "on" if "enable" in text_clean else "off")

    # ── 20. Toggle Bluetooth ─────────────────────────────────────────────
    m = re.search(r'(?:turn|switch|toggle)\s+(on|off)\s+(?:the\s+)?bluetooth', text_clean)
    if m:
        return _emit("toggle_bluetooth", m.group(1))
    m = re.search(r'(?:enable|disable)\s+(?:the\s+)?bluetooth', text_clean)
    if m:
        return _emit("toggle_bluetooth", "on" if "enable" in text_clean else "off")

    # ── 21. Open Settings ────────────────────────────────────────────────
    m = re.search(r'open\s+(\w+)\s+settings', text_clean)
    if m:
        return _emit("open_settings", m.group(1).strip())
    if re.search(r'open\s+settings', text_clean):
        return _emit("open_settings", "")

    # ── 22. Open System Tool ─────────────────────────────────────────────
    m = re.search(r'open\s+(task\s*manager|device\s*manager|control\s*panel|disk\s*management|event\s*viewer|registry|regedit)', text_clean)
    if m:
        tool = m.group(1).strip().replace(" ", "")
        return _emit("open_system_tool", tool)

    # ── 23. YouTube Control ──────────────────────────────────────────────
    m = re.search(r'(?:on\s+)?youtube\s+(?:video\s+)?(pause|play|resume|stop|next|skip|previous|mute|unmute|fullscreen|full\s*screen)', text_clean)
    if m:
        return _emit("youtube_control", m.group(1).strip().replace(" ", ""))
    m = re.search(r'(pause|play|resume|stop|skip|next|previous)\s+(?:the\s+)?(?:youtube|video)', text_clean)
    if m:
        return _emit("youtube_control", m.group(1).strip())

    # ── 24. Spotify Control ──────────────────────────────────────────────
    m = re.search(r'(?:on\s+)?spotify\s+(pause|play|resume|next|skip|previous|shuffle|repeat|mute)', text_clean)
    if m:
        return _emit("spotify_control", m.group(1).strip())
    m = re.search(r'(pause|play|resume|next\s+(?:song|track)|previous\s+(?:song|track)|skip\s+(?:song|track))\s+(?:on\s+)?spotify', text_clean)
    if m:
        action = m.group(1).strip()
        if "next" in action or "skip" in action:
            return _emit("spotify_control", "next")
        elif "previous" in action:
            return _emit("spotify_control", "previous")
        else:
            return _emit("spotify_control", action.split()[0])

    # ── 25. Netflix Control ──────────────────────────────────────────────
    m = re.search(r'(?:on\s+)?netflix\s+(pause|play|resume|next\s*episode|skip|fullscreen|subtitles)', text_clean)
    if m:
        return _emit("netflix_control", m.group(1).strip().replace(" ", "_"))

    # ── 26. Browser Control (back/forward/refresh) ───────────────────────
    if re.search(r'(?:go\s+)?back\s+(?:in\s+)?(?:the\s+)?browser', text_clean):
        return _emit("browser_control", "back")
    if re.search(r'(?:go\s+)?forward\s+(?:in\s+)?(?:the\s+)?browser', text_clean):
        return _emit("browser_control", "forward")
    if re.search(r'(?:refresh|reload)\s+(?:the\s+)?(?:page|browser|tab)', text_clean):
        return _emit("browser_control", "refresh")

    # ── 27. New Tab ──────────────────────────────────────────────────────
    if re.search(r'\b(?:open|create)\s+(?:a\s+)?(?:new\s+)?tab\b', text_clean):
        return _emit("new_tab", "")

    # ── 28. Close Tab ────────────────────────────────────────────────────
    if re.search(r'close\s+(?:the\s+|this\s+|current\s+)?tab', text_clean):
        return _emit("close_tab", "")

    # ── 29. Switch Tab ───────────────────────────────────────────────────
    m = re.search(r'switch\s+(?:to\s+)?tab\s+(.+)', text_clean)
    if m:
        return _emit("switch_tab", m.group(1).strip())

    # ── 30. List Tabs ────────────────────────────────────────────────────
    if re.search(r'(?:list|show|get)\s+(?:all\s+)?(?:open\s+)?tabs', text_clean):
        return _emit("list_tabs", "")

    # ── 31. Bookmark Page ────────────────────────────────────────────────
    if re.search(r'bookmark\s+(?:this\s+)?(?:page|tab|site)', text_clean):
        return _emit("bookmark_page", "")

    # ── 32. Open Folder ──────────────────────────────────────────────────
    _FOLDERS = {
        "downloads": r"C:\Users\swast\Downloads",
        "desktop": r"C:\Users\swast\Desktop",
        "documents": r"C:\Users\swast\Documents",
        "pictures": r"C:\Users\swast\Pictures",
        "music": r"C:\Users\swast\Music",
        "videos": r"C:\Users\swast\Videos",
    }
    m = re.search(r'(?:open|show|go\s+to)\s+(?:the\s+|my\s+)?(downloads|desktop|documents|pictures|music|videos)\s*(?:folder)?', text_clean)
    if m:
        folder_key = m.group(1).strip()
        return _emit("open_folder", _FOLDERS.get(folder_key, folder_key))

    # ── 33. List Folder ──────────────────────────────────────────────────
    m = re.search(r'(?:list|show)\s+(?:all\s+)?(?:files|contents)\s+(?:in|of)\s+(?:the\s+|my\s+)?(downloads|desktop|documents|pictures)', text_clean)
    if m:
        folder_key = m.group(1).strip()
        return _emit("list_folder", _FOLDERS.get(folder_key, folder_key))

    # ── 34. Open File ────────────────────────────────────────────────────
    m = re.search(r'open\s+(?:the\s+)?(?:file\s+)?([a-zA-Z]:\\[^\s]+|~[\\/][^\s]+)', text_clean)
    if m:
        return _emit("open_file", m.group(1).strip())

    # ── 35. Email Compose ────────────────────────────────────────────────
    m = re.search(r'(?:write|draft|send|compose)\s+(?:an?\s+)?email\s+to\s+([a-zA-Z0-9\s]+?)\s+(?:telling|asking|about|regarding|saying)\s+(.+)', text_clean)
    if m:
        to_person = m.group(1).strip()
        brief = m.group(2).strip()
        subject = brief[:35].strip().capitalize()
        return _emit("gmail_compose", f"draft|{to_person}|{subject}|{brief}")

    # ── 36. Background Status ────────────────────────────────────────────
    if re.search(r'(?:check|show|get|what\'?s?)\s+(?:the\s+)?(?:background|pending)\s+(?:tasks?|status|jobs?)', text_clean):
        return _emit("background_status", "")

    # ── 36b. Reminders / Notes (map to calendar_control or create_file) ──
    # "take notes / note down / create a note" → create_file
    m = re.search(r'(?:take\s+(?:a\s+)?note|note\s+(?:down|this)|write\s+(?:a\s+)?note|make\s+a\s+note)\s*(?:about|that|:|-)?\s*(.*)', text_clean)
    if m:
        content = m.group(1).strip()
        return _emit("create_file", f"akira_notes.txt|{content}")

    # "remind me / set a reminder / create a reminder" → calendar_control
    m = re.search(r'(?:remind\s+me|set\s+(?:a\s+)?reminder|create\s+(?:a\s+)?reminder|add\s+(?:a\s+)?reminder)\s*(?:about|to|for|that)?\s*(.*)', text_clean)
    if m:
        content = m.group(1).strip()
        return _emit("calendar_control", f"remind|{content}")

    # "schedule / add to calendar" → calendar_control
    m = re.search(r'(?:schedule|add\s+to\s+(?:my\s+)?calendar|add\s+(?:an?\s+)?event)\s*(.*)', text_clean)
    if m:
        content = m.group(1).strip()
        return _emit("calendar_control", f"add|{content}")

    # ── 37. Power Management (sleep / hibernate / shutdown / restart) ───
    if re.search(r'(?:put\s+(?:the\s+)?(?:pc|computer)\s+to\s+)?sleep(?:\s+(?:mode|the\s+pc|the\s+computer))?', text_clean):
        return _emit("sleep_pc", "")
    if re.search(r'hibernate(?:\s+(?:the\s+)?(?:pc|computer))?', text_clean):
        return _emit("hibernate", "")
    if re.search(r'(?:shutdown|turn\s+off)\s+(?:the\s+)?(?:pc|computer|system)', text_clean):
        return _emit("shutdown", "")
    if re.search(r'(?:restart|reboot)\s+(?:the\s+)?(?:pc|computer|system)', text_clean):
        return _emit("restart", "")

    # ── 38. System Cleanup & Maintenance ────────────────────────────────
    if re.search(r'empty\s+(?:the\s+)?recycle\s+bin', text_clean):
        return _emit("empty_recycle_bin", "")
    if re.search(r'(?:clear|clean)\s+(?:temp|temporary)\s+files', text_clean):
        return _emit("clear_temp_files", "")
    if re.search(r'run\s+disk\s+cleanup', text_clean):
        return _emit("run_disk_cleanup", "")
    if re.search(r'(?:clear|clean)\s+browser\s+(?:cache|history|data)', text_clean):
        return _emit("clear_browser_cache", "")

    # ── 39. Speech & Clipboard Audio ────────────────────────────────────
    if re.search(r'(?:speak|read)\s+(?:the\s+)?clipboard\s*(?:aloud)?', text_clean):
        return _emit("speak_clipboard", "")
    if re.search(r'stop\s+(?:reading|speaking|talking)', text_clean):
        return _emit("stop_reading", "")
    if re.search(r'(?:continue|read)\s+more', text_clean):
        return _emit("read_more", "")

    # ── 39b. Type / Write text in active window / Notepad ─────────────────
    # Intercepts compound commands like 'open notepad and write an essay on AI'
    m_essay = re.search(r'(?:open\s+notepad\s+and\s+write|write\s+(?:an?\s+)?(?:essay|notes?|article|summary))\s+(?:on|about)\s+(.+)', text_clean)
    if m_essay:
        topic_raw = re.sub(r'\s+in\s+notepad$', '', m_essay.group(1).strip(), flags=re.IGNORECASE)
        topic = topic_raw.strip()
        essay_content = (
            f"An Overview of {topic.title()}\n\n"
            f"{topic.capitalize()} is an important topic in modern technology and society. "
            f"It encompasses a wide range of developments, applications, and future possibilities. "
            f"Understanding {topic} helps provide valuable insights into ongoing innovations and real-world impact."
        )
        fname = f"{topic.lower().replace(' ', '_')[:25]}.txt"
        return _emit("create_file", f"{fname}|{essay_content}")

    # ── 39b. Web Form Field Input ─────────────────────────────────────────
    m_fill = re.search(r'(?:enter|type|input|fill)\s+(.+?)\s+(?:in|into|on)\s+(?:the\s+)?(placeholder|field|input|box|search\s+bar|email\s+field|password\s+field)', text_clean)
    if m_fill:
        val = m_fill.group(1).strip()
        target_field = m_fill.group(2).strip()
        if val.lower() in ("my email", "my email address", "my gmail", "my gmail address", "email"):
            val = "shrivastasvastik90@gmail.com"
        return _emit("fill", f"{target_field}|{val}")

    # Intercepts Groq hallucinations like 'write_text', 'type_text', 'insert_text'.
    # Strategy: copy content to clipboard so user can paste it wherever needed.
    m = re.search(r'(?:write|type|insert|enter|put)\s+(?:the\s+)?(?:text|content|following)?\s*(?:in|into|on)?\s*(?:notepad|word|the\s+editor|the\s+app)?\s*[:\-]?\s*(.{5,})', text_clean)
    if m:
        content = m.group(1).strip().rstrip('".,')
        return _emit("write_clipboard", content)

    # ── 39c. File/Folder search alias ────────────────────────────────────
    # 'search for a folder', 'find a file' → search_file
    m = re.search(r'(?:search\s+for|find|locate)\s+(?:a\s+)?(?:file|folder|directory)\s+(?:named|called)?\s*(.+)', text_clean)
    if m:
        return _emit("search_file", m.group(1).strip())

    # ── 40. File Management (Search, Create, Read, Write, Edit, Delete) ───
    m = re.search(r'(?:search|find|look\s+for)\s+(?:file|document|folder)?\s*([a-zA-Z0-9_\-\.\s]+?\.[a-zA-Z0-9]+)', text_clean)
    if m:
        return _emit("search_file", m.group(1).strip())
    
    m = re.search(r'(?:create|make|new)\s+file\s+([a-zA-Z0-9_\-\.\s]+)', text_clean)
    if m:
        return _emit("create_file", m.group(1).strip())

    m = re.search(r'(?:read|view|show\s+content\s+of)\s+file\s+([a-zA-Z0-9_\-\.\s]+)', text_clean)
    if m:
        return _emit("read_file", m.group(1).strip())

    m = re.search(r'write\s+to\s+file\s+([a-zA-Z0-9_\-\.\s]+?)\s+(?:content|text|saying)?\s*(.+)', text_clean)
    if m:
        return _emit("write_file", f"{m.group(1).strip()}|{m.group(2).strip()}")

    m = re.search(r'edit\s+file\s+([a-zA-Z0-9_\-\.\s]+)', text_clean)
    if m:
        return _emit("edit_file", m.group(1).strip())

    m = re.search(r'(?:delete|remove)\s+(?:file|folder)\s+([a-zA-Z0-9_\-\.\s]+)', text_clean)
    if m:
        return _emit("delete_files", m.group(1).strip())

    # ── 41. File Operations (Copy, Move, Compress, Extract, Organize, Rename) ──
    m = re.search(r'copy\s+file\s+([^\s]+)\s+to\s+(.+)', text_clean)
    if m:
        return _emit("copy_files", f"{m.group(1).strip()}|{m.group(2).strip()}")

    m = re.search(r'move\s+file\s+([^\s]+)\s+to\s+(.+)', text_clean)
    if m:
        return _emit("move_files", f"{m.group(1).strip()}|{m.group(2).strip()}")

    m = re.search(r'(?:zip|compress)\s+(?:folder|file|directory)\s+(.+)', text_clean)
    if m:
        return _emit("compress_files", m.group(1).strip())

    m = re.search(r'(?:unzip|extract)\s+(?:folder|file|archive)\s+(.+)', text_clean)
    if m:
        return _emit("extract_files", m.group(1).strip())

    m = re.search(r'organize\s+(?:files\s+in\s+)?(downloads|desktop|documents)', text_clean)
    if m:
        return _emit("organize_files", m.group(1).strip())

    m = re.search(r'summarize\s+file\s+(.+)', text_clean)
    if m:
        return _emit("summarize_file", m.group(1).strip())

    # ── 42. Images & Personalization ────────────────────────────────────
    m = re.search(r'set\s+wallpaper\s+(?:to\s+)?(.+)', text_clean)
    if m:
        return _emit("set_wallpaper", m.group(1).strip())

    m = re.search(r'download\s+image\s+(?:of\s+)?(.+)', text_clean)
    if m:
        return _emit("download_image", m.group(1).strip())

    m = re.search(r'search\s+image\s+(?:of\s+)?(.+)', text_clean)
    if m:
        return _emit("search_image", m.group(1).strip())

    # ── 43. Google Workspace & Cloud Apps ────────────────────────────────
    m = re.search(r'(?:check|open)\s+(?:my\s+)?gmail\s*(?:inbox)?', text_clean)
    if m:
        return _emit("gmail_control", "inbox")

    m = re.search(r'(?:check|show|open)\s+(?:my\s+)?calendar', text_clean)
    if m:
        return _emit("calendar_control", "view")

    m = re.search(r'(?:open|create)\s+google\s+doc(?:s)?', text_clean)
    if m:
        return _emit("docs_control", "create")

    m = re.search(r'(?:open|create)\s+google\s+sheet(?:s)?', text_clean)
    if m:
        return _emit("sheets_control", "create")

    m = re.search(r'(?:open|create)\s+google\s+slide(?:s)?', text_clean)
    if m:
        return _emit("slides_control", "create")

    # ── 44. Specialized App Controls ─────────────────────────────────────
    m = re.search(r'github\s+(search|repo|star|issues)\s*(.*)', text_clean)
    if m:
        cmd = m.group(1).strip()
        arg = m.group(2).strip()
        return _emit("github_control", f"{cmd}|{arg}")

    m = re.search(r'vscode\s+(open|toggle|terminal|run)\s*(.*)', text_clean)
    if m:
        cmd = m.group(1).strip()
        arg = m.group(2).strip()
        return _emit("vscode_control", f"{cmd}|{arg}")

    m = re.search(r'obsidian\s+(open|note|create)\s*(.*)', text_clean)
    if m:
        cmd = m.group(1).strip()
        arg = m.group(2).strip()
        return _emit("obsidian_control", f"{cmd}|{arg}")

    m = re.search(r'amazon\s+(search|buy)\s+(.+)', text_clean)
    if m:
        cmd = m.group(1).strip()
        arg = m.group(2).strip()
        return _emit("amazon_control", f"{cmd}|{arg}")

    m = re.search(r'flipkart\s+(search|buy)\s+(.+)', text_clean)
    if m:
        cmd = m.group(1).strip()
        arg = m.group(2).strip()
        return _emit("flipkart_control", f"{cmd}|{arg}")

    m = re.search(r'(?:google\s+)?meet\s+(mute|unmute|camera|leave)', text_clean)
    if m:
        return _emit("meet_control", m.group(1).strip())

    # ── 45. Office & Additional Specialized Controls ─────────────────────
    m = re.search(r'(?:open|create)\s+(?:microsoft\s+|ms\s+)?(word|excel|powerpoint)\s*(?:doc|document|sheet|presentation)?', text_clean)
    if m:
        return _emit("office_control", m.group(1).strip())

    m = re.search(r'site\s+search\s+([a-zA-Z0-9_\-\.]+)\s+(?:for\s+)?(.+)', text_clean)
    if m:
        return _emit("site_search", f"{m.group(2).strip()}|site:{m.group(1).strip()}")

    m = re.search(r'(?:batch|bulk)\s+rename\s+(?:files\s+in\s+)?(.+)', text_clean)
    if m:
        return _emit("bulk_rename_files", m.group(1).strip())

    m = re.search(r'(?:convert|file\s+to\s+doc)\s+(?:file\s+)?(.+)\s+to\s+doc', text_clean)
    if m:
        return _emit("file_to_doc", m.group(1).strip())

    m = re.search(r'organize\s+folder\s+(.+)', text_clean)
    if m:
        return _emit("organize_folder", m.group(1).strip())

    m = re.search(r'click\s+(?:on\s+)?(.+)', text_clean)
    if m:
        return _emit("click", m.group(1).strip())

    m = re.search(r'fill\s+(?:form\s+)?(.+)', text_clean)
    if m:
        return _emit("fill", m.group(1).strip())

    m = re.search(r'send\s+message\s+(.+)', text_clean)
    if m:
        return _emit("message", m.group(1).strip())

    # No pattern matched — fall through to LLM
    return None


def route(messages: list[dict], system_blocks: list[dict],
          schema: dict | None = None) -> HeadReply:
    fast_reply = _try_fast_pattern_route(messages)
    if fast_reply is not None:
        return fast_reply

    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if groq_key:
        groq_reply = _route_via_groq(groq_key, messages, system_blocks, schema)
        if groq_reply is not None:
            return groq_reply

    openrouter_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if openrouter_key:
        or_reply = _route_via_openrouter(openrouter_key, messages, system_blocks, schema)
        if or_reply is not None:
            return or_reply

    api_key = (os.environ.get(KEY_ENV) or "").strip()
    if not api_key:
        return _refuse(readiness()[1])


    # PRE-FLIGHT CAP CHECK. Deliberately before the request: refusing with a
    # clear message costs nothing, whereas discovering the cap through Google's
    # 429 has already spent the request and delayed the turn.
    if gemini_quota.exhausted():
        snap = gemini_quota.snapshot()
        if escalation_opted_in():
            # Opt-in only, and loud. Returning None hands control back to
            # _routing_call, which proceeds to paid Claude.
            print(f"[gemini_head] DAILY CAP REACHED "
                  f"({snap['used']}/{snap['stop_at']}) and "
                  f"SENSEI_HEAD_ESCALATE_ON_CAP is on — escalating to PAID "
                  f"Claude. This will cost money.")
            raise CapReachedEscalate(snap)
        return _refuse(
            "I've used up today's free Gemini allowance, so I can't work out "
            "what to do right now. It resets tomorrow. If you want me to keep "
            "going today, switch to the paid tier — I won't do that on my own "
            "because it costs money.")

    body = {"contents": _contents(messages),
            "systemInstruction": _system_instruction(system_blocks),
            "generationConfig": _generation_config(schema)}

    # At most two attempts: one degrade step, then done. Not a loop over every
    # capability — an endless "try with less" would turn a broken request into
    # a multi-second stall on the voice path.
    for attempt in (1, 2):
        try:
            resp = requests.post(
                _URL.format(model=MODEL),
                # Header, not ?key=: query-string keys land in server logs and
                # proxy traces. gemini_content still uses params for historical
                # reasons; new code should not.
                headers={"x-goog-api-key": api_key,
                         "Content-Type": "application/json"},
                json=body, timeout=TIMEOUT)
        except requests.Timeout:
            return _refuse("Gemini took too long to answer, so I didn't run "
                           "anything. Say that again.")
        except requests.RequestException as e:
            # Never reached Google -> no quota consumed, so nothing is recorded.
            print(f"[gemini_head] transport error: {e!r}")
            return _refuse("I couldn't reach Gemini just now, so I didn't run "
                           "anything. Check the connection and try again.")

        used = gemini_quota.record(_PURPOSE)

        if resp.status_code == 400 and attempt == 1:
            detail = resp.text[:500]
            if _degrade(detail):
                body["generationConfig"] = _generation_config(schema)
                continue
            print(f"[gemini_head] 400 not attributable to an optional field: "
                  f"{detail}")
            return _refuse("Gemini rejected the request, so I didn't run "
                           "anything.")
        break

    if resp.status_code == 429:
        # Google's cap is the authoritative one; the local counter was only ever
        # advisory. Sync it up so the next turn refuses pre-flight instead of
        # spending another request to learn the same thing.
        print(f"[gemini_head] Google returned 429 at local count {used} — "
              f"the real cap is lower than GEMINI_DAILY_LIMIT suggests")
        return _refuse(
            "Gemini says I've hit the free daily limit, so I can't work out "
            "what to do right now. It resets tomorrow, or you can switch to "
            "the paid tier — I won't do that on my own because it costs money.")

    if resp.status_code != 200:
        print(f"[gemini_head] HTTP {resp.status_code}: {resp.text[:300]}")
        return _refuse("Gemini had an error, so I didn't run anything. "
                       "Try again in a moment.")

    return _parse(resp, used)


class CapReachedEscalate(Exception):
    """Raised ONLY when the cap is hit AND the user opted into paid escalation.

    An exception rather than a sentinel return so the escalation path cannot be
    reached by accident: a caller that does not explicitly catch this gets a
    loud failure, not a silent switch to a paid provider. _routing_call catches
    it and falls through to Claude.
    """

    def __init__(self, snapshot: dict):
        super().__init__(f"Gemini daily cap reached ({snapshot.get('used')}/"
                         f"{snapshot.get('stop_at')}); escalating by opt-in")
        self.snapshot = snapshot


def _parse(resp, used: int) -> HeadReply:
    """Gemini response -> Claude-shaped reply, or a refusal.

    Every unexpected shape is a REFUSAL, never an empty plan. A truncated or
    malformed routing envelope that reached the executor as
    {"mode": "command", "actions": []} would look exactly like a correct
    decision to do nothing.
    """
    try:
        body = resp.json()
    except ValueError as e:
        print(f"[gemini_head] non-JSON body: {e}")
        return _refuse("Gemini sent something I couldn't read, so I didn't run "
                       "anything.")

    # A prompt-level block has no candidates at all.
    feedback = (body.get("promptFeedback") or {}).get("blockReason")
    if feedback:
        print(f"[gemini_head] prompt blocked: {feedback}")
        return _refuse("Gemini wouldn't process that request, so I didn't run "
                       "anything.")

    candidates = body.get("candidates") or []
    if not candidates:
        print(f"[gemini_head] no candidates: {str(body)[:300]}")
        return _refuse("Gemini returned nothing usable, so I didn't run "
                       "anything.")

    cand = candidates[0]
    finish = cand.get("finishReason")
    text = "".join(
        p.get("text", "")
        for p in ((cand.get("content") or {}).get("parts") or [])
        if isinstance(p, dict)).strip()

    # MAX_TOKENS -> stop_reason "max_tokens", the exact string ask_akira already
    # warns on, so truncation reporting is identical across providers. The text
    # is still returned: llm_json.parse detects the cut-off string and
    # sensei refuses to execute it, which is the established path for this.
    if finish == "MAX_TOKENS":
        print(f"[gemini_head] hit maxOutputTokens ({MAX_OUTPUT_TOKENS}) — "
              f"envelope is truncated")
        if not text:
            return _refuse("That answer came back cut off before it started, "
                           "so I didn't run anything.")
        return HeadReply([_TextBlock(text)], "max_tokens",
                         quota=gemini_quota.snapshot())

    if finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT",
                  "SPII"):
        print(f"[gemini_head] candidate blocked: {finish}")
        return _refuse("Gemini declined to answer that one, so I didn't run "
                       "anything.")

    if not text:
        print(f"[gemini_head] empty text, finishReason={finish}")
        return _refuse("Gemini returned an empty answer, so I didn't run "
                       "anything.")

    snap = gemini_quota.snapshot()
    print(f"[gemini_head] routed on {MODEL} "
          f"(quota {used}/{snap['stop_at']}, finish={finish})")
    return HeadReply([_TextBlock(text)], "end_turn", quota=snap)


def summary() -> dict:
    """Diagnostics for the startup banner."""
    ok, reason = readiness()
    return {"model": MODEL, "ready": ok, "reason": reason,
            "quota": gemini_quota.snapshot(),
            "escalate_on_cap": escalation_opted_in(),
            "capabilities": dict(_supports)}