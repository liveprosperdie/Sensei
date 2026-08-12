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


def route(messages: list[dict], system_blocks: list[dict],
          schema: dict | None = None) -> HeadReply:
    """One routing turn on Gemini. Returns a Claude-shaped reply, always.

    Never raises for a provider-side problem: every failure becomes a spoken
    conversation-mode refusal (see _refuse) so the user hears the real reason
    and no action can execute. `schema` is ROUTING_SCHEMA, passed in by the
    caller rather than imported, so this module never imports claude_handler
    (which pulls in pyttsx3/anthropic and would make routing untestable
    headlessly, and would create an import cycle).
    """
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
