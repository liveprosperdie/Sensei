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
allowance as document generation (see akira_quota — one shared counter, for
exactly this reason). At the conservative 250/day default with the 90%
safety stop, that is ~225 voice turns per day TOTAL, shared with every
"write me a doc". Prompt caching cannot extend it. An operator who needs more
than that does not need a cache; they need AKIRA_HEAD_TIER=standard.

DAILY CAP: NO SILENT ESCALATION
===============================
When the cap is reached mid-session, Free Head FAILS with a spoken, logged
reason. It does NOT quietly route to paid Claude. A user who selected Free to
avoid spending money must not discover a bill because their assistant crossed
a threshold they never saw — cost surprise is the worst failure a tier system
can have, and this codebase has resolved the same question the same way for
JSON parse failures, guard failures and servant fallthrough.

Escalation exists, but only as an EXPLICIT OPT-IN:
AKIRA_HEAD_ESCALATE_ON_CAP=1. Off by default, and loud when it fires.

No Windows/TTS imports: exercised headlessly by verify_akira_head.py.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

import akira_quota

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

KEY_ENV = "GROQ_API_KEY"
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
    model: str = "default"
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
    caller (akira.get_akira_response) wraps ask_akira in a bare
    `except Exception` that speaks "Something went wrong. Try again." So raising
    would convert every specific, actionable reason — cap reached, key missing,
    Gemini 500 — into the same generic sentence, discarding the diagnosis at the
    last step. Returning a spoken envelope routes the REAL reason to the user's
    ears and the log, through a path that already works, with no change to
    akira.py.
    """
    print(f"[gemini_head] refusing: {spoken}")
    return _reply({"mode": "conversation", "response": spoken,
                   "end_session": False},
                  quota=akira_quota.snapshot())


# ── Readiness (consumed by tiers.head) ───────────────────────────────────────

def readiness() -> tuple[bool, str]:
    """(ok, reason). Reason is human-facing and only meaningful when not ok.

    Checks CONFIGURATION only, never the network: tiers.head() is called from a
    startup banner and a status command, and a layer-resolution function that
    makes an HTTP request would turn config display into a network dependency.
    """
    if not (os.environ.get(KEY_ENV) or "").strip():
        return False, (
            f"the Free Head is Groq, but {KEY_ENV} is not set in .env. Get a key "
            f"at console.groq.com/keys and add it to .env, or set "
            f"AKIRA_HEAD_TIER=standard to use paid Claude. Not falling back to "
            f"paid Claude automatically, because that would spend money you did "
            f"not agree to.")
    return True, ""


def escalation_opted_in() -> bool:
    """True only if the user EXPLICITLY allowed paid escalation on cap."""
    raw = (os.environ.get("AKIRA_HEAD_ESCALATE_ON_CAP") or "").strip().lower()
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


ACTION_ALIASES: dict[str, str] = {
    # Brightness
    "set_system_brightness": "adjust_brightness",
    "set_brightness": "adjust_brightness",
    "change_brightness": "adjust_brightness",
    "change_system_brightness": "adjust_brightness",
    "screen_brightness": "adjust_brightness",
    "system_brightness": "adjust_brightness",

    # Volume
    "set_system_volume": "adjust_volume",
    "set_volume": "adjust_volume",
    "change_volume": "adjust_volume",
    "change_system_volume": "adjust_volume",
    "adjust_sound": "adjust_volume",
    "system_volume": "adjust_volume",

    # Text & Clipboard
    "write_text": "write_clipboard",
    "type_text": "write_clipboard",
    "insert_text": "write_clipboard",
    "enter_text": "write_clipboard",
    "paste_text": "write_clipboard",

    # Files & Search
    "file_search": "search_file",
    "folder_search": "search_file",
    "find_file": "search_file",
    "find_folder": "search_file",
    "search_files": "search_file",
    "index_size": "index_stats",
    "search_index_size": "index_stats",
    "file_index_size": "index_stats",
    "manage_index": "manage_index_scope",
    "google_search": "web_search",
    "google": "web_search",
    "search": "web_search",
    "search_web": "web_search",

    # Screenshot
    "take_screenshot": "screenshot",
    "capture_screenshot": "screenshot",
    "grab_screenshot": "screenshot",

    # Applications
    "launch_app": "open_application",
    "launch_application": "open_application",
    "start_app": "open_application",
    "start_application": "open_application",
    "kill_app": "close_application",
    "kill_application": "close_application",
    "exit_app": "close_application",
    "quit_app": "close_application",
}


def _normalize_payload(obj: dict) -> dict:
    """Normalize LLM-hallucinated action names and ensure valid tone."""
    if not isinstance(obj, dict):
        return obj
    if "action" in obj and isinstance(obj["action"], str):
        obj["action"] = ACTION_ALIASES.get(obj["action"], obj["action"])
    if "actions" in obj and isinstance(obj["actions"], list):
        for a in obj["actions"]:
            if isinstance(a, dict) and "action" in a:
                a["action"] = ACTION_ALIASES.get(a["action"], a["action"])

    valid_tones = {"neutral", "happy", "calm", "excited", "focused"}
    tone = obj.get("tone")
    if not isinstance(tone, str) or tone.lower() not in valid_tones:
        obj["tone"] = "focused" if obj.get("mode") == "command" else "neutral"
    else:
        obj["tone"] = tone.lower()
    return obj


def _route_via_groq(groq_key: str, messages: list[dict], system_blocks: list,
                    schema: dict | None = None,
                    session_id: str | None = None) -> HeadReply | None:
    """Route intent using Groq multi-model rotation pool with 5-task session pinning.

    Rotates across verified >=27B and compound class models on Groq with quality tiering,
    automatic 429 failover, sliding-window RPM smoothing, and 5-task session pinning.
    """
    groq_sys = (
        "You are Akira AI system assistant. Analyze user intent and respond strictly with a single JSON object.\n"
        "Canonical action names and pipe syntax:\n"
        "- System: adjust_volume (0..100|mute), adjust_brightness (0..100), lock_pc, sleep_pc, shutdown_pc, restart_pc, "
        "empty_recycle_bin, clear_temp_files, run_disk_cleanup, toggle_wifi (on|off), battery_status, performance_stats\n"
        "- Apps: open_application (app), close_application (app), switch_window (app), maximize_window, minimize_window, open_settings\n"
        "- Browser: web_search (query|browser:chrome), open_url (url), site_search (site|query), open_site_tab (site), "
        "switch_tab (tab_title), close_tab (tab_title), new_tab (query), list_tabs, browser_control (back|forward|reload), "
        "click (text), fill (field|text), scroll (up|down|pixels)\n"
        "- Media: youtube_control (play [song]|pause|resume|next|like|volume 80), spotify_control (play [song]|pause|resume|next|previous), "
        "netflix_control (search|query; play title|title; pause; resume; volume|70)\n"
        "- Clipboard: screenshot, read_clipboard, write_clipboard (exact text), generate_to_clipboard (brief), speak_clipboard, stop_reading, read_more\n"
        "- Files: search_file (name|folder), open_file (path), open_folder (path), list_folder (path), summarize_file (path), "
        "file_to_doc (file|Doc Title|extract), copy_files (pattern|dest), compress_files (pattern|zip), extract_files (zip|dest), "
        "create_file (path|content), write_file (path|content), edit_file (path|find|replace), move_files (pattern|dest), delete_files (pattern|folder), "
        "organize_folder (folder), bulk_rename_files (pattern|new_name), index_stats, manage_index_scope (include|path / exclude|path)\n"
        "- Images: search_image (query), download_image (pick/url|path), set_wallpaper (path)\n"
        "- Google Workspace: calendar_control (list|days; create|Title|YYYY-MM-DD HH:MM|YYYY-MM-DD HH:MM|desc; get|id; delete|id), "
        "docs_control (create|Title|content; generate|Title|brief|short; read|id; append|id|text), "
        "sheets_control (create|Title|cells; generate|Title|brief; read|id; write|id|range|values), "
        "slides_control (create|Title|slides; generate|Title|brief|count; read|id; update|id|slides; delete|id), "
        "gmail_control (search|query; read|id; unread|count; labels), gmail_compose (draft|to|sub|body; generate|to|sub|brief)\n"
        "- Notes: obsidian_control (progress|note|summary; append|note|section|text; create|title|content; read|note; search|term; "
        "moc|title|notes; link|note|targets; diagram|note|mermaid; focus|on/off; organize|content)\n"
        "- Office: office_control (word|generate|Title|brief; word|open; word|insert|text; excel|generate|Title|brief; excel|open; powerpoint|open; teams|focus), "
        "meet_control (join|url; mute; camera off; leave), "
        "vscode_control (action|param), github_control (search repos|q; open repo|name; star repo; clone repo|dest; repo notes|repo), "
        "amazon_control (search|q; select result|item; add to cart; proceed to checkout), flipkart_control (search|q; select result|item; add to cart; proceed to checkout)\n"
        "\nCore Generation & Anti-Echo Rules (P0 Correctness):\n"
        "1. NEVER echo the literal user prompt into content parameters (e.g. user says 'write an email to marcus about the budget meeting, mention it's moved to Thursday' -> parameter must be 'generate|marcus|Budget Meeting|meeting moved to Thursday', NEVER literal body text).\n"
        "2. CONTENT GENERATION PATTERNS:\n"
        "   - TWO-STAGE ACTIONS (Google Workspace & Office): Routing models emit 'generate|...' with a brief. Downstream content engines author the long-form text:\n"
        "     * Email: gmail_compose with 'generate|recipient|Subject|topic brief'.\n"
        "     * Word Doc: office_control with 'word|generate|Title|topic brief'.\n"
        "     * Google Doc: docs_control with 'generate|Title|topic brief|short'.\n"
        "     * Notepad / Clipboard: generate_to_clipboard with '1-line topic brief'.\n"
        "   - SINGLE-STAGE ACTIONS (Obsidian Notes): obsidian_control writes the content parameter DIRECTLY to disk/vault. There is NO second-stage generator. You MUST author the actual note markdown directly in the parameter (e.g. actual bullet points, actual markdown tables, or wikilinks like [[Note]]), NEVER a placeholder summary or literal prompt echo.\n"
        "3. Literal write_clipboard or draft is ONLY for short phrases literally dictated word-for-word by the user (e.g. 'type hello world').\n"
        "\nAction Chaining & Sequential Rules:\n"
        "1. When user requests multiple steps joined by 'then', 'and then', 'after that', or multiple verbs, ALWAYS emit {\"mode\": \"command\", \"actions\": [...]}.\n"
        "2. EVERY requested step must be present in 'actions' in strict chronological order — NEVER drop or omit trailing steps.\n"
        "\nContextual Tab & History Rules:\n"
        "1. Check [RECENT ACTIONS THIS SESSION] and [CURRENT BROWSER TABS] before choosing actions.\n"
        "2. When resolving ambiguous tab references, prioritize recently acted tabs and emit 'switch_tab'.\n"
        "3. Do NOT emit 'new_tab', 'open_site_tab', or 'web_search' when referring to an already-open tab.\n"
        "4. Ambiguous command phrasing:\n"
        "   - 'search netflix for [X]' -> netflix_control: 'search|[X]'\n"
        "   - 'look up [X] on youtube' -> site_search: 'youtube|[X]'\n"
        "   - 'stop, open spotify instead' -> open_site_tab: 'spotify'\n"
        "   - 'write me a note on [topic]' -> obsidian_control: 'create|[Topic]|- Core principle 1\n- Core principle 2\n- Core principle 3'\n"
        "   - Calendar relative dates: compute real ISO datetime strings (e.g. 'next Tuesday at 3pm' -> YYYY-MM-DD 15:00).\n"
        "\nOutput format:\n"
        "Tone must be one of: 'neutral', 'happy', 'calm', 'excited', 'focused'.\n"
        "Single command: {\"mode\": \"command\", \"action\": \"canonical_action_name\", \"parameter\": \"value\", \"tone\": \"focused\"}\n"
        "Chained/multi command: {\"mode\": \"command\", \"actions\": [{\"action\": \"action_1\", \"parameter\": \"param_1\"}, {\"action\": \"action_2\", \"parameter\": \"param_2\"}], \"tone\": \"focused\"}\n"
        "Chat: {\"mode\": \"conversation\", \"response\": \"reply\", \"tone\": \"neutral\", \"end_session\": false}\n"
        "\nChaining examples:\n"
        "User: \"open notepad, write a short paragraph about climate change, then open spotify and play lo-fi music\" -> {\"mode\": \"command\", \"actions\": [{\"action\": \"open_application\", \"parameter\": \"notepad\"}, {\"action\": \"generate_to_clipboard\", \"parameter\": \"short paragraph about climate change\"}, {\"action\": \"spotify_control\", \"parameter\": \"play lofi music\"}], \"tone\": \"focused\"}\n"
        "User: \"search reddit for r/programming, then open notepad and write down 3 things I should look into there\" -> {\"mode\": \"command\", \"actions\": [{\"action\": \"site_search\", \"parameter\": \"reddit|r/programming\"}, {\"action\": \"open_application\", \"parameter\": \"notepad\"}, {\"action\": \"generate_to_clipboard\", \"parameter\": \"3 things to look into from r/programming\"}], \"tone\": \"focused\"}\n"
        "User: \"write a note in obsidian about today's meeting, then send an email to sarah summarizing it\" -> {\"mode\": \"command\", \"actions\": [{\"action\": \"obsidian_control\", \"parameter\": \"create|Today's Meeting|### Discussion\n- Reviewed Q3 deliverables\n- Finalized budget reallocation\n\n### Action Items\n- Sarah to follow up with vendor\"}, {\"action\": \"gmail_compose\", \"parameter\": \"generate|sarah|Meeting Summary|summarizing key decisions and next steps from today's meeting\"}], \"tone\": \"focused\"}\n"
        "User: \"Create a note in obsidian titled 'Project Ideas' and write three bullet points of ideas about a mobile app\" -> {\"mode\": \"command\", \"action\": \"obsidian_control\", \"parameter\": \"create|Project Ideas|- Local micro-events discovery app\n- AI pantry scanner and meal planner\n- Peer-to-peer neighborhood tool sharing\", \"tone\": \"focused\"}\n"
        "User: \"Create an obsidian note that links to my 'Project Ideas' note and explains why I'm revisiting it\" -> {\"mode\": \"command\", \"action\": \"obsidian_control\", \"parameter\": \"create|Revisiting Project Ideas|[[Project Ideas]]\n\nRevisiting these concepts to prioritize mobile app ideas that can be built and launched as MVPs this quarter.\", \"tone\": \"focused\"}\n"
        "User: \"Create a note in obsidian with a markdown table comparing three phone models\" -> {\"mode\": \"command\", \"action\": \"obsidian_control\", \"parameter\": \"create|Phone Model Comparison|| Model | Display | Camera | Price |\n|---|---|---|---|\n| iPhone 15 | 6.1 OLED | 48MP | $799 |\n| Galaxy S24 | 6.2 AMOLED | 50MP | $799 |\n| Pixel 8 | 6.2 OLED | 50MP | $699 |\", \"tone\": \"focused\"}\n"
        "User: \"open word, write a one-paragraph report on renewable energy, then copy the report to the clipboard as well\" -> {\"mode\": \"command\", \"actions\": [{\"action\": \"office_control\", \"parameter\": \"word|generate|Renewable Energy|one-paragraph report on renewable energy\"}, {\"action\": \"generate_to_clipboard\", \"parameter\": \"one-paragraph report on renewable energy\"}], \"tone\": \"focused\"}\n"
        "User: \"close spotify, open chrome, search netflix for stranger things, then pause\" -> {\"mode\": \"command\", \"actions\": [{\"action\": \"close_application\", \"parameter\": \"spotify\"}, {\"action\": \"open_application\", \"parameter\": \"chrome\"}, {\"action\": \"netflix_control\", \"parameter\": \"search|stranger things\"}, {\"action\": \"netflix_control\", \"parameter\": \"pause\"}], \"tone\": \"focused\"}"
    )

    import model_pool
    pool = model_pool.get_pool()

    try:
        route_messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages]
        try:
            import prompt_dump
            prompt_dump.capture_payload("Groq Head Routing (gemini_head._route_via_groq)", groq_sys, route_messages, {"provider": "groq", "json_mode": True})
        except Exception:
            pass
        result = pool.call_model(
            messages=route_messages,
            system=groq_sys,
            json_mode=True,
            timeout=10.0,
            session_id=session_id,
        )

        raw_text = result.text
        import llm_json
        obj = result.parsed
        if not obj:
            obj, _ = llm_json.parse(raw_text)
        if not obj and raw_text:
            m_json = re.search(r'(\{[\s\S]*\})', raw_text)
            if m_json:
                obj, _ = llm_json.parse(m_json.group(1))

        if obj and isinstance(obj, dict) and "mode" in obj:
            # If a reasoning model wrapped a valid command inside conversation response:
            if obj.get("mode") == "conversation" and isinstance(obj.get("response"), str):
                m_inner = re.search(r'(\{\s*"mode"\s*:\s*"command"[\s\S]*?\})', obj["response"])
                if m_inner:
                    inner_obj, _ = llm_json.parse(m_inner.group(1))
                    if inner_obj and isinstance(inner_obj, dict) and inner_obj.get("mode") == "command":
                        obj = inner_obj
            obj = _normalize_payload(obj)
            raw_text = json.dumps(obj)
        elif raw_text:
            raw_text = json.dumps({"mode": "conversation", "response": raw_text, "tone": "neutral", "end_session": False})
        else:
            raw_text = json.dumps({"mode": "conversation", "response": "How can I help with that?", "tone": "neutral", "end_session": False})

        print(f"[gemini_head] routed via {result.provider} ({result.model}) in {result.elapsed_ms:.1f}ms (retries={result.retries_made})")
        return HeadReply([_TextBlock(raw_text)], "end_turn", provider="groq", model=result.model)


    except model_pool.PoolExhaustedError as e:
        # Bug-5 fix: for short waits (≤5s), sleep and retry once instead
        # of surfacing "rate-limited" as a raw refusal mid-session.  A
        # live demo with rapid back-to-back voice commands can exhaust
        # all 4 pool slots simultaneously for 1-3 seconds.
        if e.retry_after <= 5.0:
            print(f"[gemini_head] Pool exhausted, waiting {e.retry_after:.1f}s and retrying once…")
            time.sleep(e.retry_after)
            try:
                result = pool.call_model(
                    messages=route_messages,
                    system=groq_sys,
                    json_mode=True,
                    timeout=10.0,
                    session_id=session_id,
                )
                raw_text = result.text
                import llm_json
                obj = result.parsed
                if not obj:
                    obj, _ = llm_json.parse(raw_text)
                if not obj and raw_text:
                    m_json = re.search(r'(\{[\s\S]*\})', raw_text)
                    if m_json:
                        obj, _ = llm_json.parse(m_json.group(1))
                if obj and isinstance(obj, dict) and "mode" in obj:
                    if obj.get("mode") == "conversation" and isinstance(obj.get("response"), str):
                        m_inner = re.search(r'(\{\s*"mode"\s*:\s*"command"[\s\S]*?\})', obj["response"])
                        if m_inner:
                            inner_obj, _ = llm_json.parse(m_inner.group(1))
                            if inner_obj and isinstance(inner_obj, dict) and inner_obj.get("mode") == "command":
                                obj = inner_obj
                    obj = _normalize_payload(obj)
                    raw_text = json.dumps(obj)
                elif raw_text:
                    raw_text = json.dumps({"mode": "conversation", "response": raw_text, "tone": "neutral", "end_session": False})
                else:
                    raw_text = json.dumps({"mode": "conversation", "response": "How can I help with that?", "tone": "neutral", "end_session": False})
                print(f"[gemini_head] retry succeeded via {result.provider} ({result.model}) in {result.elapsed_ms:.1f}ms")
                return HeadReply([_TextBlock(raw_text)], "end_turn", provider="groq", model=result.model)
            except Exception as retry_err:
                print(f"[gemini_head] retry after wait also failed: {retry_err!r}")
                return _refuse(
                    "Voice routing is momentarily busy. Try again in a few seconds."
                )
        else:
            print(f"[gemini_head] Model pool exhausted (wait={e.retry_after:.1f}s too long to block): {e}")
            return _refuse(
                f"All free routing models are temporarily rate-limited. "
                f"Please wait {int(e.retry_after)} seconds."
            )
    except Exception as e:
        print(f"[gemini_head] Multi-model route failed: {e!r}")
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
                obj = _normalize_payload(obj)
                raw_text = json.dumps(obj)
            elif clean_text:
                raw_text = json.dumps({"mode": "conversation", "response": clean_text, "tone": "neutral", "end_session": False})
            else:
                raw_text = json.dumps({"mode": "conversation", "response": "How can I help with that?", "tone": "neutral", "end_session": False})

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

    # Strip external context wrappers (session context, PC state, untrusted tags)
    # so regex targets the user's actual spoken command rather than injected metadata
    raw = (last_user_msg or "").strip()
    raw = re.sub(r"^\[session start\].*?</untrusted_external_context>\s*", "", raw, flags=re.I | re.DOTALL)
    raw = re.sub(r"<untrusted_external_context>.*?</untrusted_external_context>\s*", "", raw, flags=re.I | re.DOTALL)
    raw = re.sub(r"^\[pc state\].*?\n\n", "", raw, flags=re.I | re.DOTALL)
    raw = re.sub(r"\[recent actions this session\].*?\n\n", "", raw, flags=re.I | re.DOTALL)
    raw = re.sub(r"\[current browser tabs\].*?\n\n", "", raw, flags=re.I | re.DOTALL)
    raw = re.sub(r"\[session context\].*?\[/session context\]\s*", "", raw, flags=re.I | re.DOTALL)
    text_clean = raw.strip().lower()
    if not text_clean:
        return None

    # Conversational correction & context-referencing cues:
    # When user says "no I meant...", "where it was opened before", "already open", "switch back", etc.,
    # they are correcting or referencing prior actions/tabs. The fast pre-router must NOT hijack
    # this (e.g. treating "open the tab where it was opened before" as new_tab or web_search).
    # Return None so the full LLM with session action history & tab context resolves it cleanly.
    _CORRECTION_PATTERNS = (
        r'\b(?:no|wait|actually|sorry)\b.*?\b(?:i\s+meant|not\s+that|wanted|mean)\b',
        r'\b(?:where\s+it\s+was\s+(?:opened|open)\s+before)\b',
        r'\b(?:opened|open)\s+before\b',
        r'\balready\s+open(?:ed)?\b',
        r'\bthe\s+(?:other|previous|prior)\s+tab\b',
        r'\bswitch\s+back\b',
        r'\bbut\s+i\s+(?:wanted|meant)\b',
        r'\binstead\s+of\b',
    )
    if any(re.search(p, text_clean) for p in _CORRECTION_PATTERNS):
        return None

    # Compound conjunction guard: when user utterance contains chained/compound commands
    # (e.g. "open notepad and write hello", "turn volume to 50 then play lofi", "after that close excel"),
    # do NOT greedily match the first action via regex. Fall through to LLM to emit the full actions[] chain.
    _COMPOUND_CONJUNCTIONS = (
        r'\b(?:and|then|after\s+that|also|plus|afterwards)\b',
    )
    if any(re.search(p, text_clean) for p in _COMPOUND_CONJUNCTIONS):
        return None

    def _emit(action: str, parameter: str = "") -> HeadReply:
        envelope = json.dumps({"mode": "command", "action": action, "parameter": parameter, "tone": "focused"})
        print(f"[gemini_head] routed via Fast Pre-Router in 0.1ms -> {action}")
        return HeadReply([_TextBlock(envelope)], "end_turn", provider="fast_pattern")


    # ── 1. Volume ─────────────────────────────────────────────────────────
    m = re.search(r'(?:increase|decrease|set|change|turn|put|make|adjust)\s+(?:the\s+)?(?:system\s+|pc\s+|speaker\s+|audio\s+)?volume\s+(?:to\s+)?(\d+)', text_clean)
    if m:
        return _emit("adjust_volume", m.group(1))
    if re.search(r'(?:mute|unmute)\s+(?:the\s+)?(?:system\s+|pc\s+|speaker\s+|audio\s+)?(?:volume|sound|audio)', text_clean):
        return _emit("adjust_volume", "0" if "unmute" not in text_clean else "50")
    if re.search(r'(?:max|full|maximum)\s+(?:the\s+)?(?:system\s+|pc\s+|speaker\s+|audio\s+)?volume', text_clean):
        return _emit("adjust_volume", "100")

    # ── 2. Brightness ────────────────────────────────────────────────────
    m = re.search(r'(?:increase|decrease|set|change|turn|put|adjust)\s+(?:the\s+)?(?:screen\s+|system\s+|display\s+|monitor\s+)?brightness\s+(?:to\s+)?(\d+)', text_clean)
    if m:
        return _emit("adjust_brightness", m.group(1))
    if re.search(r'(?:max|full|maximum|high|low|min|minimum|half)\s+(?:the\s+)?(?:screen\s+|system\s+|display\s+|monitor\s+)?brightness', text_clean):
        val = "100" if re.search(r'max|full|high', text_clean) else ("50" if "half" in text_clean else "20")
        return _emit("adjust_brightness", val)

    # ── 3. Web Search (browser-specific) ─────────────────────────────────
    m = re.search(r'(?:search|google|look\s+up|find)\s+(.+?)\s+(?:on|in|using)\s+(chrome|brave|edge|firefox)', text_clean)
    if m:
        return _emit("web_search", f"{m.group(1).strip()}|browser:{m.group(2).strip()}")

    # ── 3b. Site Search (specific platform: netflix, reddit, youtube, amazon, etc.) ──
    _KNOWN_SITES = (
        r"netflix|reddit|youtube|spotify|amazon|flipkart|github|twitter|x\.com|"
        r"instagram|pinterest|stackoverflow|wikipedia|makemytrip|ixigo|imdb"
    )
    m_site = re.search(rf'(?:search|look\s+up|find)\s+({_KNOWN_SITES})\s+(?:for\s+)?(.+)', text_clean)
    if m_site:
        site = m_site.group(1).strip()
        query = m_site.group(2).strip()
        return _emit("site_search", f"{site}|{query}")

    m_site2 = re.search(rf'(?:search|look\s+up|find)\s+(.+?)\s+(?:on|in)\s+({_KNOWN_SITES})', text_clean)
    if m_site2:
        query = m_site2.group(1).strip()
        site = m_site2.group(2).strip()
        return _emit("site_search", f"{site}|{query}")

    # ── 4. Web Search (generic — default to chrome) ──────────────────────
    m = re.search(r'(?:^|\b(?:please\s+)?)(?:search|google|look\s+up)\s+(?:for\s+)?(?:on\s+(?:the\s+)?(?:web|internet|google)\s+)?(.+)', text_clean)
    if m and not re.search(r'(?:file|folder|image|index|doc|sheet|slide|drive|calendar|on\s+(?:amazon|flipkart|github|youtube|netflix|spotify))', text_clean):
        query = m.group(1).strip()
        if len(query) > 3 and not query.startswith(("on ", "in ")):
            return _emit("web_search", f"{query}|browser:chrome")

    # ── 5. Open Site Tab ─────────────────────────────────────────────────
    m = re.search(r'open\s+(youtube|netflix|spotify|github|reddit|amazon|flipkart|twitter|x\.com|instagram|linkedin|whatsapp\s*web|facebook|google\s*maps|google\s*drive|google\s*docs|stackoverflow)(?:\s+in\s+\w+)?', text_clean)
    if m and not re.search(r'\band\s+(?:play|search|listen)\b', text_clean):
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

    # ── 7. Open Desktop App ──────────────────────────────────────────────
    _APPS = (
        "chrome|brave|firefox|edge|notepad|calculator|calc|vscode|code|"
        "spotify|vlc|cmd|powershell|terminal|explorer|files|discord|"
        "steam|whatsapp|teams|obsidian|notion|paint|camera|clock|"
        "excel|word|powerpoint|outlook|onenote|winrar|gitbash|capcut|"
        "adobe|acrobat|protonvpn|vpn|copilot|chatgpt|store|xbox|settings"
    )
    m = re.search(rf'\b(?:open|launch|start|run)\s+({_APPS})\b', text_clean)
    if m:
        app = m.group(1).strip()
        if app == "code":
            app = "vscode"
        if app in ("settings",):
            return _emit("open_settings", "")
        return _emit("open_application", app)

    # ── 8. Close Application ─────────────────────────────────────────────
    _NON_APP_TARGETS = (
        "tab", "window", "all tabs", "this tab", "the tab", "browser",
        "talking", "reading", "speaking", "it", "that", "this", "me",
        "now", "here", "the door", "door", "down", "up", "off", "playing"
    )
    m = re.search(r'\b(?:close|quit|exit|kill)\s+(?:the\s+app(?:lication)?\s+)?(\w+(?:\s+\w+)?)\b', text_clean)
    if not m:
        m = re.search(r'\bstop\s+(?:running\s+(?:the\s+app(?:lication)?\s+)?|(?:the\s+app(?:lication)?\s+))(\w+(?:\s+\w+)?)\b', text_clean)
    if m:
        target = m.group(1).strip()
        if target not in _NON_APP_TARGETS and not target.endswith(("ing", "ed")):
            return _emit("close_application", target)

    # ── 9. Switch Window ─────────────────────────────────────────────────
    if not re.search(r'\bswitch\s+(?:on|off)\b', text_clean):
        m = re.search(r'\b(?:switch\s+(?:window\s+)?to\s+|switch\s+window\s+(?:to\s+)?|alt\s*tab\s+(?:to\s+)?)(\w+(?:\s+\w+)?)\b', text_clean)
        if m:
            target = m.group(1).strip()
            if target not in ("tab", "the tab", "user", "account", "accounts", "off", "on"):
                return _emit("switch_window", target)

    # ── 10. Maximize / Minimize Window ───────────────────────────────────
    if re.search(r'maximize\s+(?:the\s+)?(?:current\s+)?window', text_clean):
        return _emit("maximize_window", "")
    if re.search(r'minimize\s+(?:the\s+)?(?:current\s+)?window', text_clean):
        return _emit("minimize_window", "")

    # ── 11. Scroll ───────────────────────────────────────────────────────
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
    if re.search(r'\b(?:put\s+(?:the\s+)?(?:pc|computer|system)\s+to\s+sleep|sleep\s+(?:the\s+)?(?:pc|computer|mode))\b', text_clean) or re.match(r'^(?:please\s+)?(?:go\s+to\s+)?sleep\s+(?:the\s+)?(?:pc|computer)$', text_clean):
        return _emit("sleep_pc", "")

    # ── 17. Shutdown ─────────────────────────────────────────────────────
    if re.search(r'(?:shut\s*down|power\s+off|turn\s+off)\s+(?:the\s+)?(?:pc|computer|system|laptop|machine)\b', text_clean) or re.match(r'^(?:please\s+)?(?:shut\s*down|power\s+off)$', text_clean):
        return _emit("shutdown_pc", "")

    # ── 18. Restart ──────────────────────────────────────────────────────
    if re.search(r'(?:restart|reboot)\s+(?:the\s+)?(?:pc|computer|system|laptop|machine)\b', text_clean) or re.match(r'^(?:please\s+)?(?:restart|reboot)$', text_clean):
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

    # ── 23. YouTube Search & Play / Control ──────────────────────────────
    # A. Search & Auto-Play on YouTube
    m = re.search(r'(?:open|go\s+to)\s+youtube\s+(?:and\s+)?(?:play|search\s+(?:for\s+)?)\s+(.+)', text_clean)
    if m:
        query = m.group(1).strip().rstrip("?.!")
        return _emit("youtube_control", f"play {query}")

    m = re.search(r'(?:can\s+you\s+)?(?:please\s+)?play\s+(.+?)\s+on\s+youtube\s+by\s+(.+)', text_clean)
    if m:
        song = m.group(1).strip().rstrip("?.!")
        artist = m.group(2).strip().rstrip("?.!")
        return _emit("youtube_control", f"play {song} {artist}")

    m = re.search(r'(?:can\s+you\s+)?(?:please\s+)?play\s+(.+?)\s+by\s+(.+?)\s+on\s+youtube', text_clean)
    if m:
        song = m.group(1).strip().rstrip("?.!")
        artist = m.group(2).strip().rstrip("?.!")
        return _emit("youtube_control", f"play {song} {artist}")

    m = re.search(r'(?:can\s+you\s+)?(?:please\s+)?play\s+(.+?)\s+on\s+youtube', text_clean)
    if m:
        song = m.group(1).strip().rstrip("?.!")
        return _emit("youtube_control", f"play {song}")

    m = re.search(r'on\s+youtube\s+(?:play|search\s+(?:for\s+)?)\s+(.+)', text_clean)
    if m:
        query = m.group(1).strip().rstrip("?.!")
        return _emit("youtube_control", f"play {query}")

    m = re.search(r'search\s+(?:for\s+)?(.+?)\s+on\s+youtube', text_clean)
    if m:
        query = m.group(1).strip().rstrip("?.!")
        return _emit("youtube_control", f"play {query}")

    # B. Interactive Controls & Actions
    if re.search(r'\b(?:skip|next)\s+(?:this\s+|the\s+)?(?:video|song|track)\b', text_clean):
        return _emit("youtube_control", "next")
    if re.match(r'^(?:please\s+)?(?:skip|next)(?:\s+(?:this|it))?$', text_clean):
        return _emit("youtube_control", "next")

    # Thumbs up / down
    if re.search(r'\b(?:give\s+(?:this\s+)?a\s+)?thumbs\s+(up|down)\b', text_clean):
        return _emit("youtube_control", "like" if "up" in text_clean else "dislike")
    # Explicit like / dislike of video/song/track
    if re.search(r'\b(like|dislike)\s+(?:this\s+|the\s+)?(?:video|song|track)\b', text_clean) and not re.search(r'\b(?:would|i|you|we|looks?|feels?|sounds?|seems?)\s+like\b', text_clean):
        return _emit("youtube_control", "like" if ("like" in text_clean and "dislike" not in text_clean) else "dislike")
    # Standalone like/dislike command: "like this", "like it", "dislike this", "dislike it"
    if re.match(r'^(?:please\s+)?(like|dislike)\s+(?:this|it)$', text_clean):
        m = re.match(r'^(?:please\s+)?(like|dislike)', text_clean)
        return _emit("youtube_control", m.group(1))
    if re.search(r'(?:open|show|go\s+to)\s+(?:the\s+)?comments?\s*(?:section)?', text_clean):
        return _emit("youtube_control", "comments")
    if re.search(r'(?:sign\s+in|log\s+in)\s+(?:to\s+)?youtube', text_clean):
        return _emit("youtube_control", "sign_in")
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
    if re.search(r'^(?:please\s+)?(?:open|create|start)\s+(?:a\s+)?(?:new\s+)?tab\b|\b(?:open|create)\s+(?:a\s+)?new\s+tab\b', text_clean):
        if not re.search(r'\b(?:youtube|spotify|netflix|play|video|song|why|what|how|where|which|in|on)\b', text_clean):
            m_search = re.search(r'\b(?:open|create|start)\s+(?:a\s+)?(?:new\s+)?tab\s+(?:and\s+)?(?:search\s+(?:for\s+)?|with\s+)?(.+)', text_clean)
            param = m_search.group(1).strip().rstrip("?.!") if m_search else ""
            return _emit("new_tab", param)

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
    _home_dir = os.path.expanduser("~")
    _FOLDERS = {
        "downloads": os.path.join(_home_dir, "Downloads"),
        "desktop": os.path.join(_home_dir, "Desktop"),
        "documents": os.path.join(_home_dir, "Documents"),
        "pictures": os.path.join(_home_dir, "Pictures"),
        "music": os.path.join(_home_dir, "Music"),
        "videos": os.path.join(_home_dir, "Videos"),
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
        return _emit("gmail_compose", f"generate|{to_person}|{subject}|{brief}")

    # ── 36. Background Status ────────────────────────────────────────────
    if re.search(r'(?:check|show|get|what\'?s?)\s+(?:the\s+)?(?:background|pending)\s+(?:tasks?|status|jobs?)', text_clean):
        return _emit("background_status", "")

    # ── 36b. Reminders / Notes (map to calendar_control, obsidian_control, or create_file) ──
    # "write a note in obsidian about X" → obsidian_control
    m_obs = re.search(r'(?:take\s+(?:a\s+)?note|note\s+(?:down|this)|write\s+(?:a\s+)?note|make\s+a\s+note|add\s+(?:a\s+)?note)\s+(?:in|into|to|on)?\s*(?:my\s+)?obsidian(?:\s+vault)?\s*(?:about|that|:|-)?\s*(.*)', text_clean)
    if m_obs:
        content = m_obs.group(1).strip()
        return _emit("obsidian_control", f"progress|Daily Note|{content}")

    # "take notes / note down / create a note" → create_file (generic text file only when obsidian is not mentioned)
    if "obsidian" not in text_clean and "vault" not in text_clean:
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
    if re.search(r'\b(?:put\s+(?:the\s+)?(?:pc|computer|system)\s+to\s+sleep|sleep\s+(?:the\s+)?(?:pc|computer|mode))\b', text_clean) or re.match(r'^(?:please\s+)?(?:go\s+to\s+)?sleep\s+(?:the\s+)?(?:pc|computer)$', text_clean):
        return _emit("sleep_pc", "")
    if re.search(r'\bhibernate\s+(?:the\s+)?(?:pc|computer|system|laptop)\b', text_clean) or re.match(r'^(?:please\s+)?hibernate$', text_clean):
        return _emit("hibernate", "")
    if re.search(r'(?:shutdown|turn\s+off)\s+(?:the\s+)?(?:pc|computer|system)\b', text_clean) or re.match(r'^(?:please\s+)?(?:shutdown|turn\s+off)$', text_clean):
        return _emit("shutdown", "")
    if re.search(r'(?:restart|reboot)\s+(?:the\s+)?(?:pc|computer|system)\b', text_clean) or re.match(r'^(?:please\s+)?(?:restart|reboot)$', text_clean):
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
    if re.match(r'^(?:please\s+)?(?:continue|read\s+more|continue\s+reading)$', text_clean):
        return _emit("read_more", "")

    # ── 39b. Web Form Field Input ─────────────────────────────────────────
    m_fill = re.search(r'(?:enter|type|input|fill)\s+(.+?)\s+(?:in|into|on)\s+(?:the\s+)?(placeholder|field|input|box|search\s+bar|email\s+field|password\s+field)', text_clean)
    if m_fill:
        val = m_fill.group(1).strip()
        target_field = m_fill.group(2).strip()
        if val.lower() in ("my email", "my email address", "my gmail", "my gmail address", "email"):
            val = os.environ.get("AKIRA_USER_EMAIL") or os.environ.get("USER_EMAIL") or "user@example.com"
        return _emit("fill", f"{target_field}|{val}")

    # ── 39c. Type / Write text in active window ───────────────────────────
    # Intercepts Groq hallucinations like 'write_text', 'type_text', 'insert_text'.
    # Strategy: copy content to clipboard so user can paste it wherever needed.
    #
    # BUG FIX (2026-09): distinguish COMPOSE requests ("write an essay on
    # llms in notepad") from LITERAL DICTATION ("type this: hello world").
    # Compose requests are routed to generate_to_clipboard which invokes
    # gemini_content.generate() to produce actual content, then writes the
    # result to the clipboard. Literal dictation keeps the fast path.
    m = re.search(r'(?:write|type|insert|enter|put)\s+(?:the\s+)?(?:text|content|following)?\s*(?:in|into|on)?\s*(?:notepad|word|the\s+editor|the\s+app)?\s*[:\-]?\s*(.{5,})', text_clean)
    if m:
        content = m.group(1).strip().rstrip('".,')

        # Literal-dictation markers: "type this:", "write exactly:", etc.
        # These mean the user IS dictating verbatim text — keep the fast path.
        _is_literal = bool(re.search(
            r'(?:this|exactly|the\s+following|verbatim|these\s+words)\s*[:\-]',
            content, re.I))

        # Compose-type trigger words: the captured text describes WHAT to
        # generate, not the literal characters to type.
        _COMPOSE_KEYWORDS = re.compile(
            r'\b(?:essay|story|poem|email|letter|report|summary|paragraph[s]?|'
            r'article|blog\s*post|speech|code|script|note|notes|document|paper|'
            r'review|description|explanation|tutorial|guide|outline|draft|memo|'
            r'proposal|message|list|plan|response|reply|haiku|sonnet)\b', re.I)
        _COMPOSE_PHRASES = re.compile(
            r'\b(?:about|on\s+the\s+topic\s+of|regarding|on\s+(?:the\s+)?'
            r'(?:subject|theme)\s+of)\b', re.I)

        is_compose = (not _is_literal
                      and (_COMPOSE_KEYWORDS.search(content)
                           or _COMPOSE_PHRASES.search(content)))

        if is_compose:
            # Strip target-app suffixes so the brief is clean:
            # "an essay on llms in notepad" → "an essay on llms"
            brief = re.sub(
                r'\s+(?:in|into|on|to)\s+(?:notepad|word|the\s+editor|the\s+app)\s*$',
                '', content, flags=re.I).strip()
            if not brief:
                brief = content
            return _emit("generate_to_clipboard", brief)

        return _emit("write_clipboard", content)

    # ── 39d. Index Stats & Scope Management ───────────────────────────────
    # 'how big is my search index', 'index size'
    m = re.search(r'(?:how\s+(?:big|large)|what\s+is\s+the\s+size\s+of)\s+(?:is\s+)?(?:my\s+|the\s+)?(?:search\s+index|file\s+index|index)', text_clean)
    if not m:
        m = re.search(r'\b(?:search\s+index|file\s+index)\s+(?:size|stats|status)\b', text_clean)
    if m:
        return _emit("index_stats", "")

    # 'don't index my Downloads', 'exclude folder X from search'
    m = re.search(r"(?:don'?t\s+index|stop\s+indexing|exclude\s+(?:folder\s+|directory\s+|path\s+)?)(.+?)(?:\s+from\s+(?:the\s+)?(?:index|search))?$", text_clean)
    if m and any(k in text_clean for k in ("don't index", "dont index", "stop indexing", "exclude")):
        target = m.group(1).strip().strip('"\'')
        target = re.sub(r"\s+from\s+(?:the\s+)?(?:index|search)$", "", target, flags=re.I).strip()
        if target:
            return _emit("manage_index_scope", f"exclude|{target}")

    # 'include folder X in index', 'start indexing Y'
    m = re.search(r"(?:include\s+(?:folder\s+|directory\s+|path\s+)?|start\s+indexing\s+)(.+?)(?:\s+in\s+(?:the\s+)?(?:index|search))?$", text_clean)
    if m and any(k in text_clean for k in ("include", "start indexing")):
        target = m.group(1).strip().strip('"\'')
        target = re.sub(r"\s+in\s+(?:the\s+)?(?:index|search)$", "", target, flags=re.I).strip()
        if target:
            return _emit("manage_index_scope", f"include|{target}")

    if re.search(r"\b(?:what\s+folders\s+are\s+indexed|show\s+(?:indexed\s+folders|index\s+scope)|index\s+scope)\b", text_clean):
        return _emit("manage_index_scope", "status")

    # ── 39e. Content & Scoped File Search ─────────────────────────────────
    # 'search for files containing keyword', 'find documents with text XYZ'
    m = re.search(r'(?:search|find|look)\s+(?:for\s+)?(?:files?|documents?|notes?)\s+(?:containing|with\s+text|inside)\s+["\']?(.+?)["\']?$', text_clean)
    if m:
        return _emit("search_file", f"{m.group(1).strip()}||content")

    # 'search for file X under/in folder Y'
    m = re.search(r'(?:search\s+for|find|locate)\s+(?:a\s+)?(?:file|folder|document)\s+(?:named|called\s+)?(.+?)\s+(?:in|under)\s+(.+)', text_clean)
    if m:
        return _emit("search_file", f"{m.group(1).strip()}|{m.group(2).strip()}")

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

    m = re.search(r'(?:search|find|buy|look\s+up)\s+(?:for\s+)?(.+?)\s+(?:on|in|through|via)\s+(?:this\s+)?amazon(?:\s+window|\s+tab|\s+page)?', text_clean)
    if m:
        return _emit("amazon_control", f"search|{m.group(1).strip()}")
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

    m = re.match(r'^(?:please\s+)?click\s+(?:on\s+)?(.+)', text_clean)
    if m:
        target = m.group(1).strip()
        if not target.startswith(("sound", "noise")):
            return _emit("click", target)

    m = re.search(r'\bfill\s+(?:out\s+)?(?:the\s+)?form\s*(?:with\s+)?(.*)', text_clean)
    if m:
        return _emit("fill", m.group(1).strip())

    m = re.search(r'send\s+message\s+(.+)', text_clean)
    if m:
        return _emit("message", m.group(1).strip())

    # No pattern matched — fall through to LLM
    return None


def route(messages: list[dict], system_blocks: list[dict],
          schema: dict | None = None, session_id: str | None = None) -> HeadReply:
    fast_reply = _try_fast_pattern_route(messages)
    if fast_reply is not None:
        try:
            import prompt_dump
            prompt_dump.capture_payload("Fast Pre-Router Match", "(Deterministic Regex Pattern Matcher — No LLM Prompt)", messages, {"result": fast_reply.text if hasattr(fast_reply, "text") else str(fast_reply)})
        except Exception:
            pass
        return fast_reply

    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if groq_key:
        groq_reply = _route_via_groq(groq_key, messages, system_blocks, schema, session_id=session_id)
        if groq_reply is not None:
            return groq_reply

    openrouter_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if openrouter_key:
        or_reply = _route_via_openrouter(openrouter_key, messages, system_blocks, schema)
        if or_reply is not None:
            return or_reply

    if not groq_key:
        return _refuse(readiness()[1])

    return _refuse(
        "Groq routing service is temporarily busy or rate-limited. "
        "Please try again in a moment.")



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
    # akira refuses to execute it, which is the established path for this.
    if finish == "MAX_TOKENS":
        print(f"[gemini_head] hit maxOutputTokens ({MAX_OUTPUT_TOKENS}) — "
              f"envelope is truncated")
        if not text:
            return _refuse("That answer came back cut off before it started, "
                           "so I didn't run anything.")
        return HeadReply([_TextBlock(text)], "max_tokens",
                         quota=akira_quota.snapshot())

    if finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT",
                  "SPII"):
        print(f"[gemini_head] candidate blocked: {finish}")
        return _refuse("Gemini declined to answer that one, so I didn't run "
                       "anything.")

    if not text:
        print(f"[gemini_head] empty text, finishReason={finish}")
        return _refuse("Gemini returned an empty answer, so I didn't run "
                       "anything.")

    snap = akira_quota.snapshot()
    print(f"[gemini_head] routed on {MODEL} "
          f"(quota {used}/{snap['stop_at']}, finish={finish})")
    return HeadReply([_TextBlock(text)], "end_turn", quota=snap)


def summary() -> dict:
    """Diagnostics for the startup banner."""
    ok, reason = readiness()
    return {"model": MODEL, "ready": ok, "reason": reason,
            "quota": akira_quota.snapshot(),
            "escalate_on_cap": escalation_opted_in(),
            "capabilities": dict(_supports)}