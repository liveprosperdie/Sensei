"""Guard model — a second opinion on a planned action, before it is dispatched.

WHAT THIS IS
============
A fourth model ROLE alongside BRAIN / SERVANT_GEN / SERVANT_MECH. The brain
decides what the user meant; the guard decides whether the resulting action is
safe to run. Separate role because those two jobs disagree about what a failure
should do, and one model cannot hold both policies at once.

It reuses servant_clients.call_openai_compatible verbatim — the wire format is
the same OpenAI /chat/completions shape, so a second HTTP implementation would
buy nothing and drift. What is NOT reused is the failure policy.

WHY FAIL-CLOSED HERE, WHEN THE SERVANT TIER IS FAIL-OPEN
========================================================
servant_clients treats truncation (finish_reason=length) as UNAVAILABILITY: it
raises ServantUnavailable and every caller falls back to its brain-tier model.
That is fail-open in the only sense that matters there — the fallback still
tries to complete the task, so the user's request succeeds, just pricier. The
worst case is a bigger bill.

For the guard the same policy inverts into a hole. The guard's output is not a
deliverable, it is a permission. If a truncated or unreachable guard were
treated the way a truncated servant is, the caller would receive "no objection
available" and the natural, quiet reading of that is "no objection" — a
destructive action would sail through precisely when the safety layer was
broken. Absence of evidence is not evidence of safety, and there is no
equivalent brain-tier fallback that restores the property cheaply: escalating to
the brain to re-approve its own plan is not a check, it is the same opinion
twice.

So every path that does not produce a complete, parseable, recognised verdict
returns FLAG or BLOCK, never ALLOW:

  * missing key / transport / HTTP error   -> FLAG (fail-closed)
  * truncated reply (finish_reason=length) -> FLAG (fail-closed)
  * unparseable JSON                       -> FLAG (fail-closed)
  * unrecognised decision string           -> FLAG (fail-closed)
  * static shape violation                 -> BLOCK, without spending a call

FLAG rather than BLOCK for guard failures is the deliberate line. BLOCK on an
unreachable guard would brick the assistant the moment a key expired, and a
safety layer whose failure mode is "nothing works" gets switched off within a
day — at which point it protects nothing. FLAG routes the action to the
confirmation machinery that already exists, so a broken guard degrades to "the
human decides", which is the pre-guard status quo and strictly safer than a
silent pass.

RELATION TO action_guard.py (three guard modules, three different jobs)
----------------------------------------------------------------------
Read this before adding a rule, so it lands in the right file:

  action_guard.py  BETWEEN steps. Chain-level relationships — no
                   download_image in the same chain as search_image, at most one
                   download per chain. Pure, deterministic, no model. ALREADY
                   WIRED, at akira.py:462.
  guard_rules.py   WITHIN one step. Is this action known, does its parameter
                   have the right shape, and does the existing risk taxonomy
                   object to it. Deterministic, no model.
  guard.py         judgement about one step that no rule can express, from a
                   model, on top of guard_rules' verdict.

So a rule about how steps combine belongs in action_guard; a rule about whether
a single step is well-formed belongs in guard_rules. The two do not currently
overlap — action_guard names search_image/download_image only to relate them,
guard_rules only to type their parameters.

HOW THIS IS WIRED (an earlier "unwired" note here outlived the work it described)
--------------------------------------------------------------------------------
review() is never called from here by the execution flow directly. action_router
owns every call, because "should the guard run before dispatch or alongside it"
is a timing question and the router is what holds the tier table that answers
it. This module still has no import of, and no effect on, executor's dispatch —
the seam is akira, exactly as originally predicted, not executor's ~83 call
sites.

There are four call sites, all in action_router, and they differ only in timing:

  guard:gated    action_router.run_guarded, gated + not yet confirmed. Blocking,
                 execute never invoked. Reached from akira._guard_gated, which
                 runs BEFORE the spoken confirmation is offered, so a malformed
                 gated step is dropped instead of being read out for approval.
                 An ALLOW here grants nothing: confirmation still happens.
  guard:serial   run_guarded for anything not rollback-safe, AND for gated steps
                 that the human has now approved (confirmed=True). Blocking;
                 execute runs only if the verdict cleared.
  guard:parallel run_guarded for Tier A / A-adjacent rollback-safe steps. Guard
                 goes to a worker thread, execute stays on the caller's thread.
  the same, via akira.get_akira_response's confirmed branch, which routes the
                 post-approval CLOSURE (the resolved targets, which no earlier
                 guard call has seen) back through run_guarded(confirmed=True).

Entry points into that machinery, for anyone tracing coverage:
akira.run_actions (every chain step) and akira.get_akira_response (both
post-confirmation shapes). verify_guard_wiring.py asserts there is no fifth
path that reaches an executor closure without passing one of these.

NOTES CHANNEL: guard refusals are appended to the same spoken-notes list that
action_guard.sanitize_actions returns — chain-level notes first, then per-step
guard notes in execution order. Concatenation, not merge: nothing is dropped or
overwritten, and Verdict.merge already tightened static-vs-model disagreement
within a single step before it got here.

VERIFICATION STATUS
-------------------
Written, not live-verified: reaching a real Qwen/Kimi endpoint needs a funded
QWEN_API_KEY, which is not available in the environment this was authored in.
The static half (guard_rules.validate and the coverage gate) IS verified and
runs offline. Every model-call path here is exercised only by its failure
branches until someone runs it against a real key.
"""

from __future__ import annotations

import guard_rules
import servant_clients
from guard_rules import ALLOW, BLOCK, FLAG, Verdict
from servant_clients import GUARD, ServantJSONError, ServantUnavailable

# Verdicts are two words and a short list of reasons. The budget is generous for
# that on purpose — but note the guarantee does not rest on the budget being
# right: if a reply is truncated anyway, it fails closed below rather than
# arriving as a partial pass. Tuning this number changes cost and noise, never
# safety.
GUARD_MAX_TOKENS = 400

# Shorter than the servant default: this sits in front of a user-visible action,
# and a guard that takes 90s to approve "open notepad" will be removed by the
# user long before it ever blocks anything.
GUARD_TIMEOUT = 45.0

GUARD_SYSTEM = """You are a safety guard for a voice assistant that controls a \
Windows PC. You are given ONE planned action and its parameter. Decide whether \
executing it is safe.

Reply with JSON only, no prose:
{"decision": "allow" | "flag" | "block", "reasons": ["short reason", ...]}

  allow — routine and reversible; no confirmation needed.
  flag  — plausible but consequential: spends money, sends or publishes \
something, deletes or overwrites data, or changes system power state. The user \
will be asked to confirm.
  block — the action is malformed, contradicts its stated intent, or targets \
something it has no business touching.

Judge ONLY the action in front of you. Do not assume unstated context makes it \
safe. If you are unsure, answer flag — never allow. Keep each reason under 12 \
words."""

_DECISIONS = {ALLOW, FLAG, BLOCK}


def _failed_closed(detail: str) -> Verdict:
    """A verdict for 'the guard could not answer'. Never ALLOW — see module doc."""
    return Verdict(FLAG, (detail,), source="fail-closed")


def _parse(payload) -> Verdict:
    """Turn the model's JSON into a Verdict, or fail closed if it is not one."""
    if not isinstance(payload, dict):
        return _failed_closed(f"guard returned {type(payload).__name__}, not an object")

    decision = str(payload.get("decision", "")).strip().lower()
    if decision not in _DECISIONS:
        # Covers the empty string, a missing key, and inventive answers like
        # "safe" or "yes". Anything we cannot map exactly is not a verdict.
        return _failed_closed(f"guard returned unrecognised decision {decision!r}")

    raw = payload.get("reasons") or []
    if isinstance(raw, str):
        raw = [raw]
    reasons = tuple(str(r).strip() for r in raw if str(r).strip())
    if decision != ALLOW and not reasons:
        reasons = (f"guard said {decision} without giving a reason",)
    return Verdict(decision, reasons, source="model")


import logging

logger = logging.getLogger("akira.guard")

# ── EXPLICIT GUARD FAST-PATH ALLOWLIST ─────────────────────────────────────────
# Hand-reviewed, genuinely non-destructive, non-sensitive, low-blast-radius actions.
# An action qualifies for the fast-path (skipping the 6-16s model review) ONLY if:
#   1. action is in FAST_PATH_ALLOWED_ACTIONS
#   2. guard_rules.validate(action, parameter) returns ALLOW
#   3. static.reasons is empty (zero parameter-shape or keyword concerns)
#   4. parameter contains NO untrusted/indirect context markers
#
# Everything else (file modifications/deletions, communications, payments, system
# lifecycle, interactive browser actions, and compound multi-field actions)
# ALWAYS proceeds to full model review.
FAST_PATH_ALLOWED_ACTIONS: frozenset[str] = frozenset({
    # ── Display & Audio (Non-destructive Hardware) ─────────────────────────
    "adjust_volume",
    "adjust_brightness",

    # ── Read-Only System Diagnostics & Telemetry ───────────────────────────
    "performance_stats",
    "background_status",
    "screenshot",

    # ── Non-Destructive Window & Tab Navigation ────────────────────────────
    "switch_tab",
    "list_tabs",
    "scroll",
    "switch_window",
    "maximize_window",
    "minimize_window",
    "new_tab",

    # ── Safe Media & Settings ──────────────────────────────────────────────
    "spotify_control",
    "open_settings",

    # ── Safe Navigation & Search ───────────────────────────────────────────
    "web_search",
    "open_site_tab",
    "open_url",
    "search_image",

    # ── Read-Only File Exploration ─────────────────────────────────────────
    "list_folder",
    "search_file",
    "file_search",
    "folder_search",
    "read_more",
    "stop_reading",
})


def review(action: str, parameter=None, *, timeout: float = GUARD_TIMEOUT,
           label: str = "guard") -> Verdict:
    """Validate one action step statically, then with the guard model.

    Returns a Verdict; never raises. The static verdict is computed first and
    can only be tightened by the model, never loosened — see Verdict.merge.

    FAST PATH: when an action is in FAST_PATH_ALLOWED_ACTIONS, static validator
    returns a clean ALLOW (no reasons, parameter shape correct, no risky keywords),
    and no untrusted external context markers are present, the model call is skipped.
    All other actions (destructive, compound, communications, system controls)
    ALWAYS proceed through full model review.
    """
    static = guard_rules.validate(action, parameter)
    if static.decision == BLOCK:
        # Already refused on shape or an unknown action name. Spending a model
        # call to re-litigate a malformed step would cost money to reach the
        # same answer, and a model that disagreed could not be honoured anyway.
        return static

    # FAST PATH: strictly allowlist-based, low-blast-radius actions only.
    param_str = str(parameter or "")
    has_untrusted = "<untrusted_external_context>" in param_str or "untrusted" in param_str.lower()
    if (action in FAST_PATH_ALLOWED_ACTIONS
            and static.decision == ALLOW
            and not static.reasons
            and not has_untrusted):
        logger.info(f"[GUARD FAST-PATH] Approved low-blast-radius action: {action!r}")
        print(f"[guard] FAST-PATH approved {action!r} (<1ms)")
        return static

    user = f"action: {action}\nparameter: {parameter!r}"
    try:
        payload, _info = servant_clients.call_json(
            GUARD, system=GUARD_SYSTEM, user=user,
            max_tokens=GUARD_MAX_TOKENS, timeout=timeout, label=label)
    except ServantUnavailable as e:
        kind = "truncated" if "truncated" in str(e) else "unavailable"
        return static.merge(_failed_closed(f"guard {kind}: {e}"))
    except ServantJSONError as e:
        return static.merge(_failed_closed(f"guard reply unusable: {e}"))

    return static.merge(_parse(payload))


def available() -> bool:
    """Whether the guard model is configured. Diagnostics only.

    Callers must NOT use this to skip review(): review() already fails closed
    when the tier is unreachable, and branching on availability first is how a
    missing key turns back into a silent pass.
    """
    return GUARD.available
