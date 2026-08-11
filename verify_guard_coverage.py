"""verify_guard_coverage.py — acceptance gate for the Guard's rule coverage.

Run this before calling the Guard work done. Everything here is STATIC: it
parses source with ast and imports only guard_rules (which pulls nothing heavier
than re). No API key, no provider call, no Windows, no spend — so it runs in CI
and on any dev box, unlike verify_servant_tier.py's live checks.

    python verify_guard_coverage.py

WHAT IT PROVES
  1. COVERAGE    every action executor can dispatch has a rule in
                 guard_rules.ACTION_RULES, and ACTION_RULES contains no rule for
                 an action that no longer exists. This is the check that stops an
                 action from silently dispatching unvalidated — the guard's
                 equivalent of the mistiered-call-site drift that
                 verify_servant_tier.py Check 1 was written for.
  2. RULE SHAPES every ACTION_RULES value is one of the named Rule constants, so
                 a typo is a gate failure rather than an AttributeError at the
                 first dangerous action.
  3. FAIL-CLOSED validate() actually refuses: unknown actions and arity
                 violations return BLOCK, and with no risk classifier reachable
                 (the situation in any offline run) nothing returns ALLOW.

WHY IT IS SEPARATE FROM verify_servant_tier.py
  Different preconditions and different audiences. That gate needs live keys and
  answers "do the servant providers behave as assumed"; this one needs nothing
  and answers "is any action unguarded". Merging them would make the free,
  always-runnable check inherit the other's SKIP-means-not-met semantics, and the
  coverage check would stop being run on machines without provider keys —
  exactly the machines where a coverage regression gets written.

WHY THE ACTION LIST IS PARSED, NOT IMPORTED
  executor.py imports selenium, pyautogui and Windows-only modules at import
  time. Parsing is also strictly more honest for this check: _ACTION_MAP ends
  with **_system_control.ACTIONS, and the resolver below follows that spread
  through to system_control.py's own **TIER1_ACTIONS/**TIER2_ACTIONS, so actions
  contributed by another module are covered rather than invisible.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import guard_rules

_ROOT = pathlib.Path(__file__).resolve().parent

RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f" — {detail}" if detail else ""))


# ── AST helpers: resolve a dict literal's keys across ** spreads ─────────────

def _parse_module(name: str) -> ast.Module | None:
    path = _ROOT / f"{name}.py"
    if not path.exists():
        return None
    return ast.parse(path.read_text(encoding="utf-8"))


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """{local_name: module_name} for plain imports, so `_system_control.ACTIONS`
    can be traced back to system_control.py."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = \
                    alias.name.split(".")[0]
    return aliases


def _find_dict(tree: ast.Module, dict_name: str) -> ast.Dict | None:
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == dict_name
                and isinstance(node.value, ast.Dict)):
            return node.value
    return None


def dict_keys(module: str, dict_name: str,
              _seen: frozenset[tuple[str, str]] = frozenset()) -> set[str]:
    """String keys of `module.dict_name`, following ** spreads recursively.

    Unresolvable spreads raise rather than returning a short list: silently
    under-reporting the action set would make the coverage check pass by
    knowing about fewer actions, which is the one failure this gate must not
    have.
    """
    if (module, dict_name) in _seen:
        raise SystemExit(f"cyclic dict spread at {module}.{dict_name}")
    tree = _parse_module(module)
    if tree is None:
        raise SystemExit(f"cannot read {module}.py")
    node = _find_dict(tree, dict_name)
    if node is None:
        raise SystemExit(f"cannot find {dict_name} in {module}.py")

    aliases = _import_aliases(tree)
    seen = _seen | {(module, dict_name)}
    keys: set[str] = set()

    for key, value in zip(node.keys, node.values):
        if key is None:  # ** spread
            if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                target = aliases.get(value.value.id, value.value.id)
                keys |= dict_keys(target, value.attr, seen)
            elif isinstance(value, ast.Name):
                keys |= dict_keys(module, value.id, seen)
            else:
                raise SystemExit(
                    f"{module}.{dict_name}: unresolvable ** spread at line "
                    f"{getattr(value, 'lineno', '?')}")
        elif isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
        else:
            raise SystemExit(
                f"{module}.{dict_name}: non-string key at line "
                f"{getattr(key, 'lineno', '?')}")
    return keys


# ── 1. coverage ──────────────────────────────────────────────────────────────

def check_coverage() -> set[str]:
    dispatchable = dict_keys("executor", "_ACTION_MAP")
    ruled = set(guard_rules.ACTION_RULES)

    unguarded = sorted(dispatchable - ruled)
    orphaned = sorted(ruled - dispatchable)

    if unguarded:
        record("FAIL", "coverage/unguarded",
               f"dispatchable by executor with no guard rule: {unguarded}")
    if orphaned:
        # Not merely untidy: an orphan means the table was written against an
        # action name that does not exist, so the rule someone believes is
        # protecting them is dead code.
        record("FAIL", "coverage/orphaned",
               f"guard rules for actions executor cannot dispatch: {orphaned}")
    if not unguarded and not orphaned:
        record("PASS", "coverage",
               f"{len(dispatchable)} dispatchable actions, all ruled")
    return dispatchable


# ── 2. rule shapes ───────────────────────────────────────────────────────────

def check_rule_shapes() -> None:
    """Every ACTION_RULES value must be a real Rule.

    Read from the live module rather than the AST because guard_rules is cheap
    to import, and the imported object is the thing validate() will actually
    consult.
    """
    known = {name: obj for name, obj in vars(guard_rules).items()
             if isinstance(obj, guard_rules.Rule)}
    bad = [action for action, rule in guard_rules.ACTION_RULES.items()
           if not isinstance(rule, guard_rules.Rule)]
    if bad:
        record("FAIL", "rules/not-a-rule", f"{bad}")
        return
    incoherent = [
        action for action, rule in guard_rules.ACTION_RULES.items()
        if rule.min_fields > rule.max_fields or rule.min_fields < 0]
    if incoherent:
        record("FAIL", "rules/incoherent-arity", f"{incoherent}")
        return
    record("PASS", "rules",
           f"{len(guard_rules.ACTION_RULES)} rules over "
           f"{len(known)} named shapes")


# ── 3. fail-closed behaviour ─────────────────────────────────────────────────

def check_fail_closed(dispatchable: set[str]) -> None:
    """validate() must refuse, not shrug.

    Runs offline, which means guard_rules cannot reach sensei's classifier — so
    this also proves the "classifier unavailable" path does not degrade to ALLOW.
    """
    unknown = guard_rules.validate("definitely_not_an_action", "x")
    record("PASS" if unknown.decision == guard_rules.BLOCK else "FAIL",
           "fail-closed/unknown-action", str(unknown))

    # Arity: feed every rule with a required field an empty parameter, and every
    # rule a parameter with more fields than it accepts. Both must BLOCK.
    missing_ok, excess_ok = [], []
    for action, rule in guard_rules.ACTION_RULES.items():
        if rule.min_fields >= 1:
            v = guard_rules.validate(action, "")
            if v.decision != guard_rules.BLOCK:
                missing_ok.append(f"{action}={v.decision}")
        v = guard_rules.validate(action, "|".join(["x"] * (rule.max_fields + 1)))
        if v.decision != guard_rules.BLOCK:
            excess_ok.append(f"{action}={v.decision}")

    record("FAIL" if missing_ok else "PASS", "fail-closed/missing-parameter",
           f"accepted empty parameter: {missing_ok}" if missing_ok
           else "empty parameter blocked for every required-field action")
    record("FAIL" if excess_ok else "PASS", "fail-closed/excess-fields",
           f"accepted over-long parameter: {excess_ok}" if excess_ok
           else "over-long parameter blocked for every action")

    # With no classifier reachable, nothing may come back ALLOW.
    if guard_rules._sensei_classifier() is None:
        allowed = [a for a in sorted(dispatchable & set(guard_rules.ACTION_RULES))
                   if guard_rules.validate(a, "x").decision == guard_rules.ALLOW]
        record("FAIL" if allowed else "PASS", "fail-closed/no-classifier",
               f"allowed without a risk classifier: {allowed}" if allowed
               else "no ALLOW verdicts while the classifier is unreachable")
    else:
        record("SKIP", "fail-closed/no-classifier",
               "a live classifier is importable here — check not meaningful")


def main() -> int:
    dispatchable = check_coverage()
    check_rule_shapes()
    check_fail_closed(dispatchable)

    failed = [r for r in RESULTS if r[0] == "FAIL"]
    skipped = [r for r in RESULTS if r[0] == "SKIP"]
    print(f"\n{len(RESULTS) - len(failed) - len(skipped)} passed, "
          f"{len(failed)} failed, {len(skipped)} skipped")
    # Unlike verify_servant_tier.py, a SKIP here is not a gate failure: the only
    # skippable check is one that becomes meaningless when a classifier happens
    # to be importable, and every check that proves coverage always runs.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
