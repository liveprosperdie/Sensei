"""verify_router.py — offline gate for action_router's tables and timing.

Runs without selenium, pywin32, pyaudio or a network, for the same reason
verify_guard_coverage.py does: a gate that needs the full Windows stack is a
gate nobody runs. executor's action names are read via AST, never by importing
it.

Three things checked:

  1. COVERAGE — every action in executor._ACTION_MAP has a ROLLBACK entry.
     A missing entry is UNKNOWN, which parallel_ok() treats as unsafe, so the
     failure is a silent latency regression rather than a safety hole. Still a
     failure: the whole point of the table is to force an explicit position.
  2. CONSISTENCY — A_ADJACENT names are real actions, and no action is both
     rollback-SAFE and in the not-rollback-safe commentary set.
  3. CONCURRENCY — the parallel path really overlaps. Asserted by timing a
     fake guard and a fake execute that each sleep, and requiring the total to
     look like max() and not sum(). This is the one property that cannot be
     proved by reading the code.

Run: python verify_router.py
"""

from __future__ import annotations

import ast
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


# ── executor's action names, via AST ────────────────────────────────────────

def _action_names() -> set[str]:
    """Keys of executor._ACTION_MAP, plus the ** spread from system_control.

    Same approach as verify_guard_coverage: parse, do not import. The ** spread
    of system_control.ACTIONS is resolved by parsing that module too, so an
    action added there is still covered.
    """
    names: set[str] = set()
    spreads: list[str] = []

    tree = ast.parse(_read("executor.py"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "_ACTION_MAP"
                   for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, _ in zip(node.value.keys, node.value.values):
            if key is None:                      # ** spread
                spreads.append("system_control")
            elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.add(key.value)

    if spreads:
        names |= _system_action_names()
    return names


def _system_action_names() -> set[str]:
    """Keys of system_control.ACTIONS, itself built from **TIER1/**TIER2."""
    tree = ast.parse(_read("system_control.py"))
    tables: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            keys = {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            refs = {n.id for k, v in zip(node.value.keys, node.value.values)
                    if k is None and isinstance(v, ast.Name) for n in [v]}
            tables[target.id] = keys | {r for r in refs}

    resolved: set[str] = set()
    for name in tables.get("ACTIONS", set()):
        resolved |= tables.get(name, {name}) if name in tables else {name}
    return {n for n in resolved if not n.isupper()}


def _read(name: str) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return fh.read()


# ── checks ─────────────────────────────────────────────────────────────────

def check_coverage(failures: list[str]) -> None:
    import action_router

    actions = _action_names()
    if not actions:
        failures.append("could not resolve executor._ACTION_MAP via AST")
        return

    missing = sorted(a for a in actions if a not in action_router.ROLLBACK)
    if missing:
        failures.append(
            "actions with no ROLLBACK entry (they default to UNKNOWN and will "
            f"run serially): {', '.join(missing)}")

    stale = sorted(a for a in action_router.ROLLBACK if a not in actions)
    if stale:
        failures.append(
            f"ROLLBACK entries for actions executor no longer has: {', '.join(stale)}")

    bad_adjacent = sorted(a for a in action_router.A_ADJACENT if a not in actions)
    if bad_adjacent:
        failures.append(
            f"A_ADJACENT names that are not real actions: {', '.join(bad_adjacent)}")

    print(f"[coverage] {len(actions)} actions, "
          f"{len(action_router.ROLLBACK)} rollback entries, "
          f"{len(action_router.A_ADJACENT)} a-adjacent")


def check_policy(failures: list[str]) -> None:
    """parallel_ok must refuse anything not provably rollback-safe."""
    import action_router
    from action_router import Rollback

    # Without a live sensei, tier() fails closed to GATED — which is itself the
    # behaviour to assert, and it means parallel_ok is False for everything.
    if "sensei" in sys.modules or "__main__" in sys.modules and \
            hasattr(sys.modules.get("__main__"), "_is_dangerous_step"):
        pass
    else:
        if action_router.tier({"action": "screenshot"}) is not action_router.Tier.GATED:
            failures.append(
                "tier() must fail closed to GATED when sensei's gate classifier "
                "is unreachable")
        if action_router.parallel_ok({"action": "screenshot"}):
            failures.append("parallel_ok must be False when tier fails closed")

    if action_router.rollback("no_such_action_xyz") is not Rollback.UNKNOWN:
        failures.append("unlisted actions must classify as UNKNOWN")

    # The entries most likely to be wrongly "optimised" into the parallel path.
    for action in ("click", "fill", "gmail_compose", "write_file",
                   "delete_files", "office_control", "calendar_control"):
        if action_router.rollback(action) is Rollback.SAFE:
            failures.append(f"{action} must NOT be rollback-SAFE")
    print("[policy] fail-closed and rollback positions as expected")


def check_concurrency(failures: list[str]) -> None:
    """Prove guard and execute actually overlap. Timing, not code reading.

    guard.review and the tier lookup are both monkeypatched: the point is to
    measure action_router's timing structure, not to reach a real endpoint.
    """
    import action_router
    from guard_rules import ALLOW, Verdict

    delay = 0.4
    real_review = action_router.guard.review
    real_tier = action_router.tier

    def slow_review(action, parameter=None, **kw):
        time.sleep(delay)
        return Verdict(ALLOW, (), source="model")

    def slow_execute():
        time.sleep(delay)
        return "done"

    try:
        action_router.guard.review = slow_review
        # Force the parallel branch: pretend the step is Tier A. rollback() is
        # left real, so screenshot must genuinely be SAFE for this to run.
        action_router.tier = lambda step: action_router.Tier.A

        step = {"action": "screenshot", "parameter": None}
        if not action_router.parallel_ok(step):
            failures.append("screenshot should be parallel-ok for this check")
            return

        started = time.monotonic()
        outcome = action_router.run_guarded(step, slow_execute)
        elapsed = time.monotonic() - started

        if not outcome.raced:
            failures.append("outcome.raced was False on the parallel path")
        if outcome.result != "done":
            failures.append(f"execute result lost: {outcome.result!r}")
        # Serial would be ~2*delay. Allow generous slack for a loaded CI box
        # while still failing a genuinely sequential implementation.
        if elapsed > delay * 1.6:
            failures.append(
                f"parallel path took {elapsed:.2f}s for two {delay}s halves — "
                "that is a sum, not a max: the guard is not overlapping execute")
        else:
            print(f"[concurrency] max() confirmed: {elapsed:.2f}s "
                  f"for 2x{delay}s halves")
    finally:
        action_router.guard.review = real_review
        action_router.tier = real_tier


def check_fail_closed_thread(failures: list[str]) -> None:
    """A crashing guard thread must still yield a non-allow verdict."""
    import action_router

    real_review = action_router.guard.review
    real_tier = action_router.tier
    try:
        def boom(action, parameter=None, **kw):
            raise RuntimeError("simulated guard crash")

        action_router.guard.review = boom
        action_router.tier = lambda step: action_router.Tier.A
        outcome = action_router.run_guarded(
            {"action": "screenshot", "parameter": None}, lambda: "ran")
        if outcome.verdict.allowed:
            failures.append("a crashed guard thread resolved to ALLOW")
        else:
            print(f"[fail-closed] guard crash -> {outcome.verdict.decision}")
    finally:
        action_router.guard.review = real_review
        action_router.tier = real_tier


def main() -> int:
    sys.path.insert(0, HERE)
    failures: list[str] = []
    for check in (check_coverage, check_policy, check_concurrency,
                  check_fail_closed_thread):
        try:
            check(failures)
        except Exception as e:
            failures.append(f"{check.__name__} errored: {e!r}")

    print()
    if failures:
        print(f"FAIL ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS — router tables covered, fail-closed, and genuinely concurrent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
