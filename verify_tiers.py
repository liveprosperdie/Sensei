"""verify_tiers.py — acceptance gate for the Free/Standard/Pro tier table.

    python verify_tiers.py

WHY THIS ONE RUNS ANYWHERE, UNLIKE verify_servant_tier.py
=========================================================
verify_servant_tier.py must hit live provider APIs, because the thing it proves
is that two third-party endpoints behave as claude_handler assumes. This gate
proves something entirely different: that the tier table's AVAILABILITY LOGIC
matches the specified table. That is pure local resolution — no key, no network,
no spend — so it runs in CI and in a sandbox.

The distinction matters when reading the results. A PASS here means the config
layer resolves correctly. It says NOTHING about whether Gemini, Kimi, Together
or Fireworks actually work, because no request is ever sent. Those need real
keys on the real machine.

WHAT IT PROVES
  1. TABLE       every cell of the specified 5x3 tier table resolves to the
                 availability the table states.
  2. INDEPENDENT each of the five layers is switchable on its own, and mixing
                 tiers across layers works without code changes.
  3. INERT       local model slots NEVER resolve to available, with or without
                 AKIRA_LOCAL_MODEL_PATH set. This is the non-negotiable one:
                 a fake success path here would surface as a failure far from
                 the config that caused it.
  4. NO-SPEND    Free/Standard servant calls refuse rather than escalating to
                 hosted inference. Guards the tier system's core promise.
  5. LEDGER      the reliability gate's semantics under both modes, including
                 that a failure resets a consecutive streak and that the gate is
                 tier-blind (no tier-name bypass).
  6. FAILSAFE    an unset or garbage tier string defaults to FREE, never PRO.

Exit code is 0 only if every check passed.
"""

from __future__ import annotations

import os
import sys
import json
import tempfile

RESULTS: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f" — {detail}" if detail else ""))


def check(name: str, condition: bool, detail: str = "") -> None:
    record("PASS" if condition else "FAIL", name, detail)


# Every test sets env vars, and both modules read env at call time (tiers) or
# import time (reliability). Isolating the ledger to a temp file BEFORE the first
# import keeps the gate from reading or corrupting a real user's history — a test
# that resets a live reliability ledger would silently re-gate every action the
# user had already earned.
_TMP = tempfile.mkdtemp(prefix="akira-verify-tiers-")
os.environ["LOCALAPPDATA"] = _TMP

import tiers          # noqa: E402
import reliability    # noqa: E402

reliability.LEDGER_FILE = os.path.join(_TMP, "action_reliability.json")

_LAYER_ENV = (
    list(tiers._ENV.values())
    + ["AKIRA_TIER"]
)


def set_tiers(**kw) -> None:
    """Set the five layer env vars from short names, clearing any not given.

    Clearing matters: a leaked variable from a previous check would make later
    assertions pass or fail for the wrong reason.
    """
    for var in _LAYER_ENV:
        os.environ.pop(var, None)
    alias_akira = {"head": "AKIRA_HEAD_TIER", "guard": "AKIRA_GUARD_TIER",
                   "servant": "AKIRA_SERVANT_TIER",
                   "gated": "AKIRA_SERVANT_GATED_TIER",
                   "mode": "AKIRA_GUARD_MODE_TIER", "all": "AKIRA_TIER"}
    for key, value in kw.items():
        os.environ[alias_akira[key]] = value


# ── 1. the specified table, cell by cell ─────────────────────────────────────

def check_table() -> None:
    """Assert each cell's availability against the table as written."""
    # Head: Free inert (no Gemini adapter), Standard/Pro available.
    set_tiers(all="free")
    groq_key = os.environ.get("GROQ_API_KEY")
    os.environ["GROQ_API_KEY"] = ""
    try:
        check("table/head/free-without-key-unavailable", not tiers.head(),
              "Free Head must be Unavailable without GROQ_API_KEY")
    finally:
        if groq_key:
            os.environ["GROQ_API_KEY"] = groq_key
        else:
            os.environ.pop("GROQ_API_KEY", None)
    set_tiers(all="standard")
    spec = tiers.head()
    check("table/head/standard", bool(spec) and spec.priority is False,
          f"metered, non-priority: {spec}")
    set_tiers(all="pro")
    spec = tiers.head()
    check("table/head/pro-priority", bool(spec) and spec.priority is True,
          "Pro Head must be priority")

    pro_budget = spec.daily_budget_usd
    set_tiers(all="standard")
    std_budget = tiers.head().daily_budget_usd
    check("table/head/pro-higher-budget",
          (pro_budget or 0) > (std_budget or 0),
          f"pro={pro_budget} > standard={std_budget}")

    # Gated servant: unavailable on Free, available on Standard and Pro.
    set_tiers(all="free")
    check("table/gated/free-unavailable", not tiers.servant_gated(),
          "Gated must be off on Free")
    for plan in ("standard", "pro"):
        set_tiers(all=plan)
        # Availability of the Gated ROW is a tier question. On Standard/Pro the
        # table says "available, full confirmation flow", which is what
        # servant_gated() must not refuse on tier grounds.
        seat = tiers.servant_gated()
        refused_on_tier = isinstance(seat, tiers.Unavailable) and \
            "not available on the Free tier" in seat.reason
        check(f"table/gated/{plan}-available", not refused_on_tier,
              f"{plan} must not refuse Gated on tier grounds")

    # Guard mode: parallel-only on Free, +serial on Standard, +gate on Pro.
    set_tiers(all="free")
    mode = tiers.guard_mode()
    check("table/mode/free", mode.parallel and not mode.serial_gated
          and not mode.reliability_gate, str(mode))
    set_tiers(all="standard")
    mode = tiers.guard_mode()
    check("table/mode/standard", mode.parallel and mode.serial_gated
          and not mode.reliability_gate,
          "Standard: parallel + serial, NO reliability gate")
    set_tiers(all="pro")
    mode = tiers.guard_mode()
    check("table/mode/pro", mode.parallel and mode.serial_gated
          and mode.reliability_gate,
          "Pro: parallel + serial + reliability gate")

    # Guard model row: available on ALL three tiers. This is the row that must
    # never be inert, and it is also why making Free/Standard servants inert
    # cannot brick the guard — the guard does not read the servant row at all.
    for plan in ("free", "standard", "pro"):
        set_tiers(all=plan)
        os.environ["QWEN_API_KEY"] = "test-key-not-used-for-any-request"
        check(f"table/guard/{plan}-available", bool(tiers.guard()),
              f"Guard must be available on {plan} (hosted on all tiers)")
        os.environ.pop("QWEN_API_KEY", None)


# ── 2. independent layer toggling ────────────────────────────────────────────

def check_independence() -> None:
    """Each layer switchable alone; cross-tier mixes resolve per layer."""
    set_tiers(all="free")
    for layer in tiers.Layer:
        check(f"independent/default/{layer.value}",
              tiers.plan_for(layer) == tiers.FREE,
              "AKIRA_TIER must seed every unset layer")

    # The exact mix named in the brief: Standard Head + Free Guard.
    set_tiers(all="standard", guard="free")
    check("independent/mix/standard-head-free-guard",
          tiers.plan_for(tiers.Layer.HEAD) == tiers.STANDARD
          and tiers.plan_for(tiers.Layer.GUARD) == tiers.FREE,
          "per-layer override must beat AKIRA_TIER")

    # One layer at a time, with every other layer left at the default.
    for layer, env in tiers._ENV.items():
        set_tiers()
        os.environ[env] = "pro"
        others = [l for l in tiers.Layer if l is not layer]
        check(f"independent/solo/{layer.value}",
              tiers.plan_for(layer) == tiers.PRO
              and all(tiers.plan_for(o) == tiers.FREE for o in others),
              f"{env}=pro must move only {layer.value}")

    # Cross-tier combination warnings must be REPORTED, not enforced. The
    # config still has to resolve and run.
    set_tiers(all="pro", gated="free")
    warns = tiers.warnings()
    check("independent/warns-not-blocks", len(warns) > 0,
          f"contradictory mix must warn: {warns[0][:60] if warns else 'NONE'}")
    check("independent/still-resolves",
          tiers.guard_mode().plan == tiers.PRO,
          "a warned combination must still resolve, not raise")


# ── 3. local slots are structurally present and permanently inert ────────────

def check_inert() -> None:
    """The non-negotiable: no local slot may ever report available."""
    for plan in ("free", "standard", "pro"):
        set_tiers(all=plan)
        slot = tiers.servant(plan).local
        # Structurally present: the slot exists and names its env vars.
        check(f"inert/{plan}/slot-exists",
              slot.path_env == "AKIRA_LOCAL_MODEL_PATH",
              "config slot must exist structurally")

        os.environ.pop("AKIRA_LOCAL_MODEL_PATH", None)
        unset = slot.resolve()
        check(f"inert/{plan}/unset", isinstance(unset, tiers.Unavailable)
              and not unset, "must be Unavailable and falsy")

        # The critical case: a path IS set. A slot that flips to available
        # because a string was set is the fake success path this forbids.
        os.environ["AKIRA_LOCAL_MODEL_PATH"] = "C:\\models\\qwen-7b.gguf"
        with_path = slot.resolve()
        check(f"inert/{plan}/path-set-still-inert",
              isinstance(with_path, tiers.Unavailable) and not with_path,
              "setting a path must NOT make the slot available")
        check(f"inert/{plan}/reason-distinguishes",
              "no local inference runtime" in with_path.reason,
              "reason must blame the missing runtime, not the path")
        os.environ.pop("AKIRA_LOCAL_MODEL_PATH", None)

    # Free/Standard have no hosted row at all, so the whole spec is falsy.
    for plan in ("free", "standard"):
        set_tiers(all=plan)
        check(f"inert/{plan}/no-hosted", not tiers.servant(plan),
              f"{plan} servant must have no server")

    # Pro's hosted fallback appears only with a provider key.
    set_tiers(all="pro")
    for key in ("TOGETHER_API_KEY", "FIREWORKS_API_KEY"):
        os.environ.pop(key, None)
    check("inert/pro/no-key-no-server", not tiers.servant("pro"),
          "Pro without a provider key must not claim a server")
    os.environ["TOGETHER_API_KEY"] = "test-key-not-used-for-any-request"
    check("inert/pro/hosted-with-key", bool(tiers.servant("pro")),
          "Pro WITH a provider key must resolve a hosted fallback")
    os.environ.pop("TOGETHER_API_KEY", None)


# ── 4. no silent cloud fallthrough ──────────────────────────────────────────

def check_no_spend() -> None:
    """Free/Standard servant work must refuse, never escalate to paid.

    This is the check that distinguishes "inert" from "quietly expensive". The
    pre-existing servant_clients policy is fail-OPEN to the brain tier, which
    would route a Free-tier call to paid Claude; servant_allowed() overrides it
    for tier decisions specifically.
    """
    for key in ("TOGETHER_API_KEY", "FIREWORKS_API_KEY"):
        os.environ.pop(key, None)

    for plan in ("free", "standard"):
        set_tiers(all=plan)
        refusal = tiers.servant_allowed()
        check(f"no-spend/{plan}/refuses", refusal is not None,
              f"{plan} servant call must be refused")
        check(f"no-spend/{plan}/explains-why",
              refusal is not None and "not permitted to spend" in refusal.reason,
              "refusal must name the cost reason, not just 'unavailable'")

    set_tiers(all="pro")
    refusal = tiers.servant_allowed()
    check("no-spend/pro/no-key-distinct-reason",
          refusal is not None and "nothing to fall back to" in refusal.reason,
          "Pro's missing-key reason must differ from a tier prohibition")

    os.environ["TOGETHER_API_KEY"] = "test-key-not-used-for-any-request"
    check("no-spend/pro/allowed-with-key", tiers.servant_allowed() is None,
          "Pro with a hosted key may proceed")
    os.environ.pop("TOGETHER_API_KEY", None)


# ── 5. the reliability ledger ───────────────────────────────────────────────

def check_ledger() -> None:
    """Ledger semantics. NOTE: these assert the semantics CHOSEN in
    reliability.py, not a spec read from an architecture bible — no bible is
    committed to this repo. If the intended protocol differs, these
    expectations change with it."""
    reliability.reset()
    reliability.MODE = "consecutive"
    reliability.THRESHOLD = 5   # 20 real runs per assertion is unreasonable

    check("ledger/unknown-not-cleared", not reliability.cleared("delete_files"),
          "an action with no history must NOT be cleared")
    check("ledger/unknown-remaining",
          reliability.remaining("delete_files") == 5,
          "full threshold remaining with no history")

    for _ in range(4):
        reliability.record("delete_files", True)
    check("ledger/below-threshold", not reliability.cleared("delete_files"),
          "4 of 5 must not clear")
    reliability.record("delete_files", True)
    check("ledger/clears-at-threshold", reliability.cleared("delete_files"),
          "5 of 5 must clear")

    # A failure resets the streak — the documented choice, since a streak is a
    # claim of uninterrupted correctness.
    reliability.record("delete_files", False)
    check("ledger/failure-resets", not reliability.cleared("delete_files"),
          "one failure must revoke a cleared action")
    check("ledger/failure-resets-fully",
          reliability.remaining("delete_files") == 5,
          "reset must be to zero, not a decrement")

    # Per action TYPE, not global.
    reliability.reset()
    for _ in range(5):
        reliability.record("screenshot", True)
    check("ledger/per-action-scope",
          reliability.cleared("screenshot")
          and not reliability.cleared("shutdown_pc"),
          "clearing one action must not clear another")

    # Cumulative mode tolerates a failure rate instead of requiring a streak.
    reliability.reset()
    reliability.MODE = "cumulative"
    reliability.MIN_RATE = 0.8
    for i in range(5):
        reliability.record("move_files", success=(i != 0))   # 4/5 = 0.8
    check("ledger/cumulative-mode", reliability.cleared("move_files"),
          "cumulative mode must clear on rate, despite a broken streak")
    reliability.MODE = "consecutive"

    # Corruption is an empty history, never a crash, and fails toward MORE
    # gating rather than less.
    with open(reliability.LEDGER_FILE, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    check("ledger/corrupt-fails-safe", not reliability.cleared("screenshot"),
          "a corrupt ledger must gate, not crash or open")

    reliability.reset()
    reliability.record("delete_files", True)
    with open(reliability.LEDGER_FILE, encoding="utf-8") as f:
        check("ledger/persists", "delete_files" in json.load(f),
              "records must survive on disk")


# ── 5b. the closure / self-gating path actually records ─────────────────────

# The self-gating file actions. These execute through the stored-closure path in
# get_akira_response, NOT through the bottom of run_actions' loop, so they are the
# exact set that accumulated zero ledger history before this gate existed.
SELF_GATING = ("delete_files", "move_files", "organize_files",
               "organize_folder", "bulk_rename_files")


def _closure_path_source() -> str:
    """The REAL post-confirmation closure branch, lifted out of akira.py.

    Why AST extraction instead of importing akira or hand-rolling an equivalent:

      * akira cannot be imported here — it opens audio devices at import, which
        is why verify_guard_wiring reads its source by AST too. Same approach.
      * a hand-written "equivalent" of the branch is the failure mode this gate
        exists to prevent. It would pass while the shipped code recorded nothing,
        which is precisely the bug being fixed. Executing the real statements is
        the only version of this test that can actually fail correctly.

    So the branch's own statements are extracted verbatim and executed against
    stubs. If someone deletes the reliability.record call from akira.py, the
    extracted source no longer contains it and these checks fail.
    """
    import ast
    target = "akira.py"
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           target), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef)
                and node.name in ("get_akira_response",)):
            continue
        # The branch guarded by `pending_action == "click_confirmed" and
        # pending_execute is not None` — the closure path.
        for inner in ast.walk(node):
            if not isinstance(inner, ast.If):
                continue
            src = ast.unparse(inner.test)
            if "click_confirmed" in src and "pending_execute" in src:
                return "\n".join(ast.unparse(s) for s in inner.body)
    return ""


def _run_closure_path(*, action: str, exec_result, executed: bool = True,
                      allowed: bool = True):
    """Execute the extracted branch with everything it touches stubbed.

    Returns the ledger entry recorded for `action`, or None if nothing was
    recorded — which is the pre-fix behaviour and the thing under test.
    """
    import types

    outcome = types.SimpleNamespace(
        executed=executed, result=exec_result,
        verdict=types.SimpleNamespace(allowed=allowed, reasons=("stubbed",)),
        blocked=not allowed, flagged=False, raced=False)

    ns = {
        "pending_action": "click_confirmed",
        "pending_parameter": "resolved enumeration of 3 files",
        "pending_execute": lambda: exec_result,
        "pending_origin": action,
        "action_router": types.SimpleNamespace(
            run_guarded=lambda step, ex, confirmed=False: outcome),
        "claude_handler": types.SimpleNamespace(
            record_action_results=lambda results: None),
        "reliability": reliability,
        "FAILURE_PREFIXES": ("Couldn't", "Failed", "Error", "I couldn't"),
        "_guard_refusal_text": lambda a, o: f"I didn't run {a}.",
        "_guard_flag_pending": lambda a, o: f"I ran {a}, but flagging.",
        "speak_text": None,
    }
    exec(_closure_path_source(), ns)          # noqa: S102 — real shipped source
    return reliability.status(action)


def check_closure_ledger() -> None:
    """FIX 1 GATE: the closure/self-gating path must record to the ledger.

    Before this fix, reliability.record had exactly ONE call site — the bottom of
    run_actions' loop, guarded by `if confirmed`. The self-gating file actions
    return a needs_confirmation PLAN and `break` out of that loop ABOVE the
    record line, then execute later through the stored closure, which recorded
    nothing. Net effect: these five action types accumulated zero history, ever.

    That was masked while they were classified A-adjacent, because nothing
    consulted their history. Once they are classified Gated (Fix 2) an
    permanently-empty ledger becomes a permanent Pro lockout with no unlock path.
    This gate is the reason Fix 2 is safe to ship.
    """
    reliability.MODE = "consecutive"
    reliability.THRESHOLD = 5

    src = _closure_path_source()
    check("closure/branch-located", bool(src),
          "the post-confirmation closure branch was found in akira.py")
    check("closure/records-in-source", "reliability.record" in src,
          "the shipped closure branch contains a reliability.record call")

    # Each self-gating type must accumulate history through the closure path.
    for action in SELF_GATING:
        reliability.reset()
        entry = _run_closure_path(
            action=action, exec_result={"success": True, "message": "Deleted 3 files."})
        check(f"closure/records/{action}",
              entry["runs"] == 1 and entry["successes"] == 1
              and entry["streak"] == 1,
              f"one closure execution recorded one success "
              f"(runs={entry['runs']}, streak={entry['streak']})")

    # A dict failure must record as a FAILURE, matching run_actions' semantics.
    reliability.reset()
    entry = _run_closure_path(
        action="delete_files",
        exec_result={"success": False, "message": "Couldn't delete."})
    check("closure/dict-failure-recorded",
          entry["runs"] == 1 and entry["successes"] == 0 and entry["streak"] == 0,
          f"a {{'success': False}} result records a failure "
          f"(successes={entry['successes']})")

    # A failure-prefixed string must also record as a failure.
    reliability.reset()
    entry = _run_closure_path(action="move_files",
                              exec_result="Couldn't move those files.")
    check("closure/string-failure-recorded",
          entry["runs"] == 1 and entry["successes"] == 0,
          "a FAILURE_PREFIXES string result records a failure")

    # A guard refusal must NOT record: nothing ran, so there is no evidence
    # either way, and recording it would let a strict guard permanently suppress
    # an action that never once misbehaved.
    reliability.reset()
    entry = _run_closure_path(action="delete_files", exec_result="irrelevant",
                              executed=False)
    check("closure/refusal-not-recorded", entry["runs"] == 0,
          "a guard refusal records nothing (nothing executed)")

    # The end-to-end claim: repeated closure executions actually clear the bar,
    # so a Pro user is not locked out forever.
    reliability.reset()
    for _ in range(5):
        _run_closure_path(action="delete_files",
                          exec_result={"success": True, "message": "ok"})
    check("closure/accumulates-to-unlock", reliability.cleared("delete_files"),
          "history from the closure path alone can clear the reliability bar")

    reliability.reset()


# ── 6. tier-blindness and the fail-safe default ─────────────────────────────

def check_gate_integration() -> None:
    """gated_available() composes both gates without a tier-name bypass."""
    reliability.reset()
    reliability.MODE = "consecutive"
    reliability.THRESHOLD = 5

    # Free: refused on the tier gate, before reliability is ever consulted.
    set_tiers(all="free")
    refusal = tiers.gated_available("delete_files")
    check("gate/free-refuses", refusal is not None
          and "Free tier" in refusal.reason, "Free must refuse Gated outright")

    # Standard: Gated available WITHOUT the reliability bar, per the table.
    set_tiers(all="standard")
    check("gate/standard-no-bar", tiers.gated_available("delete_files") is None,
          "Standard offers Gated with no per-action bar")

    # Pro: the bar applies, and it is NOT bypassed by the tier name.
    set_tiers(all="pro")
    refusal = tiers.gated_available("delete_files")
    check("gate/pro-enforces-bar", refusal is not None
          and "reliability protocol" in refusal.reason,
          "Pro must enforce the per-action bar, not skip it")

    # The documented inversion: a fresh Pro account has FEWER Gated actions
    # available than Standard. Asserted because it looks like a bug and is not.
    check("gate/pro-stricter-than-standard-when-fresh",
          tiers.gated_available("delete_files") is not None,
          "fresh Pro is intentionally stricter than Standard")

    for _ in range(5):
        reliability.record("delete_files", True)
    check("gate/pro-unlocks-after-runs",
          tiers.gated_available("delete_files") is None,
          "clearing the bar must unlock the action on Pro")
    check("gate/pro-unlock-is-per-action",
          tiers.gated_available("shutdown_pc") is not None,
          "unlocking one action must not unlock another")

    # Configurability: the same bar can be turned on for Standard without a
    # code change, as required.
    set_tiers(all="standard")
    os.environ["AKIRA_RELIABILITY_GATE"] = "1"
    check("gate/standard-bar-configurable",
          tiers.guard_mode().reliability_gate is True,
          "the gate must be enableable on Standard via env")
    os.environ.pop("AKIRA_RELIABILITY_GATE", None)


def check_probation_bootstrap() -> None:
    """The reliability bar must be EARNABLE, not a permanent lockout.

    THE DEADLOCK THIS GATES AGAINST
    -------------------------------
    gated_available() withholds an action with no history; _guard_gated drops a
    withheld step with `continue` before it can execute; reliability.record only
    fires on execution. So:

        no history -> withheld -> never runs -> no history -> ... forever

    Every Gated action on a fresh Pro install was withheld permanently with no
    reachable path to the runs being demanded. Confirmed live at
    RELIABILITY_RUNS=3 before the fix: delete_files, shutdown_pc and write_file
    all reported "3 more successful runs needed" and could never earn one.

    The resolution is that the bar governs AUTONOMY, not existence: an unproven
    action is offered on probation to a supervising human, and each confirmed
    outcome is recorded until the streak is genuinely earned. These checks pin
    both halves — that probation opens the path, and that it does not quietly
    become a bypass.
    """
    reliability.MODE = "consecutive"
    reliability.THRESHOLD = 5
    set_tiers(all="pro")
    reliability.reset()

    # The deadlock itself: unsupervised is strict, supervised is earnable.
    check("probation/unsupervised-still-strict",
          tiers.gated_available("delete_files") is not None,
          "an unproven action is still withheld from UNSUPERVISED execution")
    check("probation/supervised-offered",
          tiers.gated_available("delete_files", supervised=True) is None,
          "an unproven action IS offered when a human is confirming it")
    check("probation/flagged-as-probation", tiers.on_probation("delete_files"),
          "the action reports itself as on probation so the user can be told")

    # The bar must actually be reachable through the supervised path — this is
    # the check that would have caught the permanent lockout.
    for _ in range(5):
        reliability.record("delete_files", True)
    check("probation/earnable",
          tiers.gated_available("delete_files") is None
          and not tiers.on_probation("delete_files"),
          "runs earned under supervision must clear the bar for good")

    # Probation is per action type, exactly like the unlock it leads to.
    check("probation/per-action",
          tiers.gated_available("shutdown_pc") is not None
          and tiers.on_probation("shutdown_pc"),
          "one action clearing the bar must not graduate another")

    # A failure must send a cleared action back to probation, or the streak
    # reset in reliability.record would be cosmetic.
    reliability.record("delete_files", False)
    check("probation/failure-demotes",
          tiers.gated_available("delete_files") is not None
          and tiers.on_probation("delete_files"),
          "a failure returns a graduated action to probation")

    # Supervision relaxes the RELIABILITY bar only. It must never relax the
    # TIER gate — otherwise "supervised" becomes a Free-tier Gated bypass.
    set_tiers(all="free")
    refusal = tiers.gated_available("delete_files", supervised=True)
    check("probation/never-bypasses-tier",
          refusal is not None and "Free tier" in refusal.reason,
          "supervision must not grant Gated actions on a tier that lacks them")
    check("probation/no-probation-when-tier-forbids",
          not tiers.on_probation("delete_files"),
          "an action the tier forbids is not 'on probation', it is unavailable")

    # Standard has no bar at all, so nothing is ever on probation there.
    set_tiers(all="standard")
    check("probation/standard-has-no-probation",
          not tiers.on_probation("delete_files"),
          "Standard trades the per-action bar for confirmation alone")

    set_tiers(all="pro")
    reliability.reset()


def check_failsafe() -> None:
    """An unset or misspelled tier must default to FREE, never PRO."""
    for value, label in ((None, "unset"), ("", "empty"),
                         ("PRO_TIER_TYPO", "garbage"), ("enterprise", "unknown")):
        set_tiers()
        if value is not None:
            os.environ["AKIRA_TIER"] = value
        check(f"failsafe/{label}-defaults-free",
              tiers.plan_for(tiers.Layer.SERVANT_GATED) == tiers.FREE,
              "a config typo must reduce capability, never grant Pro")

    # Case and whitespace are normalised rather than falling through to FREE,
    # so "  Pro " is a working config and not a silent downgrade.
    set_tiers(all="  PRO  ")
    check("failsafe/normalises-case",
          tiers.plan_for(tiers.Layer.HEAD) == tiers.PRO,
          "case/whitespace must normalise, not silently downgrade")


def main() -> int:
    check_table()
    check_independence()
    check_inert()
    check_no_spend()
    check_ledger()
    check_closure_ledger()
    check_gate_integration()
    check_probation_bootstrap()
    check_failsafe()

    failed = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    if failed:
        for _, name, detail in failed:
            print(f"  FAIL {name} — {detail}")
        return 1
    print("Tier-table logic verified. NOTE: no provider request was made — "
          "Gemini/Kimi/Together/Fireworks remain unverified without real keys.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())