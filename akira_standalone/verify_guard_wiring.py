"""verify_guard_wiring.py — proves the guard is actually REACHED, not just present.

WHY THIS GATE EXISTS
====================
verify_guard_coverage.py proves every action has a rule and that the guard fails
closed. verify_router.py proves the tier tables are complete and the parallel
path really overlaps. Neither proves the thing that matters most: that a real
execution path cannot reach an executor closure without a verdict.

That gap was not hypothetical. guard.py's docstring claimed "NOT WIRED YET" long
after the wiring landed, and in the opposite direction akira's post-confirmation
branch called `pending_execute()` directly — so the single most dangerous path in
the app (a resolved, approved file deletion) was the one path the guard never
saw. Both are the same class of bug: a safety layer whose reachability is
asserted in prose instead of in a test.

So this file asserts reachability two ways, because neither alone is enough:

  BEHAVIOURAL  drive action_router.run_guarded down all four of its timing paths
               with a counting stub in place of guard.review, and require a call
               on every one. Catches a path that stops consulting the guard.
  STATIC (AST) scan akira.py for closure calls that bypass the router. Catches a
               NEW path that never goes through run_guarded at all — which a
               behavioural test of run_guarded structurally cannot see.

Runs offline: no selenium, pyaudio, pywin32, network or API key. akira is never
imported (it opens audio devices at import); its gate classifier is stubbed and
its source is read by AST, the same approach verify_router and
verify_guard_coverage already use.

Run: python verify_guard_wiring.py
"""

from __future__ import annotations

import ast
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_PASS: list[str] = []
_FAIL: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    (_PASS if ok else _FAIL).append(f"{name} — {detail}")
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")


def _read(fname: str) -> str:
    with open(os.path.join(HERE, fname), encoding="utf-8") as fh:
        return fh.read()


# ── akira stub ──────────────────────────────────────────────────────────────
# action_router.tier() asks akira._is_dangerous_step whether a step is gated,
# resolving it lazily out of sys.modules. Installing a stub lets this gate drive
# GATED and non-GATED deliberately instead of accepting tier()'s offline
# fail-closed answer (always GATED), which would leave the parallel and serial
# paths untested — the two that a bypass is most likely to hide in.

DANGEROUS = {"delete_files"}


def _install_akira_stub() -> None:
    mod = types.ModuleType("akira")
    mod._is_dangerous_step = lambda step: (
        (step.get("action") or "").strip() in DANGEROUS)
    sys.modules["akira"] = mod


_install_akira_stub()

import action_router  # noqa: E402
import guard  # noqa: E402
from guard_rules import ALLOW, BLOCK, Verdict  # noqa: E402


class _CountingGuard:
    """Stands in for guard.review and records that it was consulted.

    Returns a caller-chosen verdict so refusal handling is exercised too, and
    records the label so each path can be told apart in the assertions.
    """

    def __init__(self, decision: str = ALLOW):
        self.decision = decision
        self.calls: list[tuple[str, object, str]] = []

    def __call__(self, action, parameter, *, label="", **kw):
        self.calls.append((action, parameter, label))
        return Verdict(self.decision, ("stubbed",), "model")


def _drive(step: dict, *, confirmed: bool = False, decision: str = ALLOW):
    """Run one step through the router with the guard stubbed out.

    Returns (outcome, stub, executed_flag). execute() records its own invocation
    separately from Outcome.executed so a path that reports executed=True
    without calling the closure (or vice versa) is detectable.
    """
    stub = _CountingGuard(decision)
    ran: list[bool] = []
    original = guard.review
    guard.review = stub
    try:
        outcome = action_router.run_guarded(
            step, lambda: ran.append(True) or "done", confirmed=confirmed)
    finally:
        guard.review = original
    return outcome, stub, bool(ran)


# ── 1. BEHAVIOURAL: every timing path consults the guard ────────────────────

def check_every_path_consults_guard() -> None:
    """No timing path may reach execution without a verdict.

    Four paths, matching run_guarded's branches. The assertion is deliberately
    "review was called", not "review returned ALLOW": a path that consults the
    guard and ignores it is covered by the refusal checks below.
    """
    cases = [
        ("gated-unconfirmed", {"action": "delete_files", "parameter": "x"},
         False, False),
        ("gated-confirmed", {"action": "delete_files", "parameter": "x"},
         True, True),
        # screenshot is Tier A and ROLLBACK.SAFE -> the parallel path.
        ("parallel", {"action": "screenshot", "parameter": ""}, False, True),
        # no ROLLBACK entry -> UNKNOWN -> forced serial.
        ("serial-unknown-rollback", {"action": "not_a_real_action",
                                     "parameter": "x"}, False, True),
    ]
    for name, step, confirmed, should_run in cases:
        outcome, stub, ran = _drive(step, confirmed=confirmed)
        check(f"reached/{name}", len(stub.calls) == 1,
              f"guard consulted exactly once (calls={len(stub.calls)}, "
              f"label={stub.calls[0][2] if stub.calls else 'none'})")
        check(f"executed/{name}", ran is should_run,
              f"closure {'ran' if ran else 'did not run'} as required")


# ── 2. BEHAVIOURAL: a refusal actually withholds execution ──────────────────

def check_refusal_withholds() -> None:
    """A BLOCK must stop the closure on every serial path.

    The parallel path is exempt by construction — it starts execution before the
    verdict exists, which is why parallel_ok() restricts it to rollback-safe
    actions. Asserting it here would encode the wrong requirement.
    """
    for name, step, confirmed in [
        ("gated-confirmed", {"action": "delete_files", "parameter": "x"}, True),
        ("serial", {"action": "not_a_real_action", "parameter": "x"}, False),
    ]:
        outcome, _stub, ran = _drive(step, confirmed=confirmed, decision=BLOCK)
        check(f"refusal/{name}", (not ran) and (not outcome.executed),
              "BLOCK withheld execution and reported executed=False")


def check_confirmed_gated_can_run() -> None:
    """The mirror of the above: approval must not be silently discarded.

    Regression guard for the failure where a confirmed gated step still hit the
    pre-approval branch, so the user said yes to a deletion and was told it had
    not run. A safety layer that never lets anything through gets removed.
    """
    outcome, _stub, ran = _drive({"action": "delete_files", "parameter": "x"},
                                 confirmed=True)
    check("confirmed/gated-executes", ran and outcome.executed,
          "an approved gated step with a clear verdict does run")


# ── 3. BEHAVIOURAL: the tier policy switch is load-bearing ──────────────────

def check_parallel_switch() -> None:
    """guard_mode().parallel=False must actually force serial.

    A declared policy flag that nothing reads is worse than no flag: it reports a
    guarantee it cannot deliver. This asserts the flag is wired, not merely
    declared.
    """
    import tiers
    safe = {"action": "screenshot", "parameter": ""}
    original = tiers.guard_mode

    check("policy/parallel-default", action_router.parallel_ok(safe),
          "a rollback-safe Tier A step races by default")

    tiers.guard_mode = lambda plan=None: types.SimpleNamespace(
        plan="test", parallel=False, serial_gated=True, reliability_gate=False)
    try:
        check("policy/parallel-off", not action_router.parallel_ok(safe),
              "parallel=False forces the serial path")
    finally:
        tiers.guard_mode = original

    def _boom(plan=None):
        raise RuntimeError("simulated tier config failure")

    tiers.guard_mode = _boom
    try:
        check("policy/fail-closed", not action_router.parallel_ok(safe),
              "a raising policy lookup falls back to serial, never parallel")
    finally:
        tiers.guard_mode = original


# ── 4. STATIC: no path bypasses the router ──────────────────────────────────

def _akira_tree() -> ast.Module:
    return ast.parse(_read("akira.py"))


def check_navigation_waits_for_verdict() -> None:
    """URL navigation must not start before the guard verdict resolves.

    Regression gate for the audit's critical finding: open_url was ROLLBACK.SAFE
    on the reasoning that "a page load is undoable". The tab is; the remote effect
    is not. A one-click unsubscribe, a "confirm delete" link or a webhook URL has
    already fired against a third party by the time a raced verdict is read, and
    _handle_open_url screens nothing beyond the http(s) prefix.

    Asserted by ORDERING rather than wall-clock timing, which is the stronger
    claim available here: the guard stub records the moment it is consulted and
    the closure records the moment it runs, so "execution began before a verdict
    existed" is detectable directly instead of being inferred from elapsed time.
    A BLOCK is used so the requirement is the one that actually matters — the
    navigation must be WITHHELD, not merely sequenced after the call.
    """
    for action in ("open_url", "open_site_tab", "web_search"):
        step = {"action": action, "parameter": "https://example.com/unsubscribe"}

        # 1. Not racing: the parallel path is what allowed the request to leave
        #    the machine before review returned.
        check(f"nav/{action}-serial", not action_router.parallel_ok(step),
              f"{action} is not eligible for the parallel path "
              f"(rollback={action_router.rollback(action).value})")

        # 2. A refusal withholds the navigation entirely.
        outcome, stub, ran = _drive(step, decision=BLOCK)
        label = stub.calls[0][2] if stub.calls else "none"
        check(f"nav/{action}-blocked", (not ran) and (not outcome.executed),
              f"BLOCK withheld navigation (label={label}, raced={outcome.raced})")

        # 3. The verdict was reached serially, not concurrently. raced=False is
        #    the router's own report that execute did not overlap review.
        check(f"nav/{action}-not-raced", outcome.raced is False,
              "router reports the verdict was resolved before execution")

        # 4. The mirror: a clear verdict must still let navigation through, so
        #    this fix cannot be "passing" because it broke open_url outright.
        outcome_ok, _stub_ok, ran_ok = _drive(step, decision=ALLOW)
        check(f"nav/{action}-allowed", ran_ok and outcome_ok.executed,
              "an allowed navigation still runs after the guard clears")


def check_no_direct_closure_call() -> None:
    """`pending_execute()` must never be invoked directly in akira.

    This is the exact bypass that existed: the post-confirmation branch called
    the closure itself, so the resolved targets the executor had just computed
    were never reviewed. The guard had only ever seen the UNRESOLVED request, and
    the parameter a human cannot evaluate from a spoken summary is precisely the
    one it is there to catch.
    """
    offenders = [
        node.lineno for node in ast.walk(_akira_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "pending_execute"
    ]
    check("bypass/no-direct-closure-call", not offenders,
          "no direct pending_execute() call"
          if not offenders else f"direct call at line(s) {offenders}")


def check_router_is_the_only_seam() -> None:
    """The guard-bearing entry points must all call action_router.run_guarded.

    Named explicitly so that deleting the call from any one of them fails here
    rather than being noticed in production. run_actions is every chain step;
    _guard_gated is the pre-confirmation review; get_akira_response is both
    post-confirmation shapes.
    """
    wanted = {"run_actions", "_guard_gated", "get_akira_response"}
    found: set[str] = set()
    for node in ast.walk(_akira_tree()):
        if not isinstance(node, ast.FunctionDef) or node.name not in wanted:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "run_guarded"):
                found.add(node.name)
                break
    missing = sorted(wanted - found)
    check("seam/run_guarded-in-every-entrypoint", not missing,
          f"all of {sorted(wanted)} route through run_guarded"
          if not missing else f"missing run_guarded in {missing}")


def check_origin_is_recorded() -> None:
    """Wherever a closure is stored for later, its action name is stored too.

    pending_action is the literal "click_confirmed" for both self-gating shapes,
    which erases the action about to run — and without a name the guard cannot
    select a rule, so it would fail closed on a legitimate action and the feature
    would be switched off. Checked structurally: any statement block that assigns
    a real closure to pending_execute must also assign pending_origin.
    """
    bad: list[int] = []
    for node in ast.walk(_akira_tree()):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            names = {
                t.id
                for stmt in block if isinstance(stmt, ast.Assign)
                for t in stmt.targets if isinstance(t, ast.Name)
            }
            for stmt in block:
                if not isinstance(stmt, ast.Assign):
                    continue
                stores_closure = any(
                    isinstance(t, ast.Name) and t.id == "pending_execute"
                    for t in stmt.targets)
                # `pending_execute = None` is a RESET, not a store; requiring an
                # origin next to it would be noise.
                is_reset = isinstance(stmt.value, ast.Constant) \
                    and stmt.value.value is None
                if stores_closure and not is_reset \
                        and "pending_origin" not in names:
                    bad.append(stmt.lineno)
    check("origin/recorded-beside-closure", not bad,
          "every stored closure records its originating action"
          if not bad else f"pending_origin missing near line(s) {sorted(bad)}")


def check_docstring_not_stale() -> None:
    """guard.py must not still claim it is unwired.

    Cheap, and it is the specific rot that sent a later reader chasing work that
    was already done. Documentation that contradicts the code is a defect.
    """
    doc = ast.get_docstring(ast.parse(_read("guard.py"))) or ""
    stale = "NOT WIRED" in doc.upper()
    check("docs/not-stale", not stale,
          "guard.py's docstring reflects the wiring that exists" if not stale
          else "guard.py still claims to be unwired; review() has four live "
               "call sites in action_router")


def main() -> int:
    check_every_path_consults_guard()
    check_refusal_withholds()
    check_confirmed_gated_can_run()
    check_parallel_switch()
    check_navigation_waits_for_verdict()
    check_no_direct_closure_call()
    check_router_is_the_only_seam()
    check_origin_is_recorded()
    check_docstring_not_stale()

    print(f"\n{len(_PASS)} passed, {len(_FAIL)} failed")
    if _FAIL:
        print("\nFAIL")
        for f in _FAIL:
            print(f"  - {f}")
        return 1
    print("Guard reachability verified: no execution path bypasses review(). "
          "NOTE: guard.review itself is STUBBED here — this gate proves it is "
          "CALLED, not that a real endpoint agrees. Model-side behaviour still "
          "needs a funded key (see verify_guard_coverage).")
    return 0


if __name__ == "__main__":
    sys.exit(main())