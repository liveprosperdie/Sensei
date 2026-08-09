"""verify_servant_tier.py — acceptance gate for the servant-tier routing.

Run this, against LIVE provider APIs, before calling the servant-tier work
done. Nothing here is mocked: the whole point of the tier split is that two
third-party endpoints behave the way claude_handler assumes they do, and a mock
would assert our assumptions against themselves.

    python verify_servant_tier.py            # all checks
    python verify_servant_tier.py --offline   # registry checks only, no spend

WHAT IT PROVES
  1. REGISTRY   every MODEL_TIER key is actually passed to servant_or_none()
                (or is BRAIN), and no servant_or_none() call site is missing
                from MODEL_TIER. Static, free, catches the exact drift that
                shipped synthesize_action_reply mistiered.
  2. REACHABLE  each configured tier answers a trivial prompt over its real
                base_url with its real model string.
  3. JSON       each tier's json_mode reply survives llm_json.parse.
  4. TRUNCATION a deliberately under-budgeted call raises ServantUnavailable
                instead of returning half a sentence. This is the guarantee the
                plain-text callers (summarize_text, ask_confirmation,
                synthesize_action_reply, match_element) depend on.

Exit code is 0 only if every executed check passed. A tier whose key is unset
is reported as SKIP, not PASS — an unset key means the gate did not test it.
"""

from __future__ import annotations

import re
import sys
import pathlib

import servant_clients
from servant_clients import ServantUnavailable, ServantJSONError

RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f" — {detail}" if detail else ""))


# ── 1. registry ↔ call-site drift ────────────────────────────────────────────

_ROOT = pathlib.Path(__file__).resolve().parent
_CALL_RE = re.compile(r"servant_or_none\(\s*[\"']([^\"']+)[\"']\s*\)")


def _parse_model_tier() -> dict[str, str]:
    """MODEL_TIER as {call_site: tier_name}, read out of the source with ast.

    The dict's values are the literal "SERVANT_*" strings plus the BRAIN alias,
    so the alias is resolved here rather than assuming its value.
    """
    import ast

    tree = ast.parse((_ROOT / "claude_handler.py").read_text(encoding="utf-8"))
    consts: dict[str, str] = {}
    tiers: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str):
            consts[target.id] = node.value.value
        elif target.id == "MODEL_TIER" and isinstance(node.value, ast.Dict):
            for key, value in zip(node.value.keys, node.value.values):
                name = value.value if isinstance(value, ast.Constant) else \
                    consts.get(getattr(value, "id", ""), "?")
                tiers[key.value] = name
    if not tiers:
        raise SystemExit("could not find MODEL_TIER in claude_handler.py")
    return tiers


def check_registry() -> None:
    """MODEL_TIER keys and servant_or_none() call sites must match 1:1.

    Read from SOURCE, not by importing claude_handler, for two reasons: a call
    site is only observable at runtime if that code path is actually taken —
    which is precisely how the mistiered site hid — and claude_handler
    initialises pyttsx3 at import time, so importing it would make this gate
    unrunnable anywhere but the Windows box.
    """
    tiers = _parse_model_tier()
    servant_keys = {k for k, v in tiers.items() if v != "BRAIN"}
    brain_keys = set(tiers) - servant_keys

    found: set[str] = set()
    for path in sorted(_ROOT.glob("*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        found |= set(_CALL_RE.findall(path.read_text(encoding="utf-8")))

    missing = sorted(servant_keys - found)
    unknown = sorted(found - set(tiers))
    brain_routed = sorted(found & brain_keys)

    if missing:
        record("FAIL", "registry/no-call-site",
               f"tiered as servant but never passed to servant_or_none(): "
               f"{missing}")
    if unknown:
        record("FAIL", "registry/unregistered",
               f"servant_or_none() called with keys absent from MODEL_TIER: "
               f"{unknown}")
    if brain_routed:
        record("WARN", "registry/brain-routed",
               f"BRAIN keys passed to servant_or_none() (always returns None): "
               f"{brain_routed}")
    if not missing and not unknown:
        record("PASS", "registry",
               f"{len(servant_keys)} servant sites matched, "
               f"{len(brain_keys)} brain sites")

    # Every tier name in the registry must name a real Tier in servant_clients
    # — resolve_tier() does getattr(servant_clients, tier_name), so a typo
    # there is an AttributeError at the first live call, not at import.
    for site in sorted(servant_keys):
        tier = getattr(servant_clients, tiers[site], None)
        if not isinstance(tier, servant_clients.Tier):
            record("FAIL", f"resolve_tier/{site}",
                   f"MODEL_TIER names {tiers[site]!r}, which is not a Tier")

    # No model string may be hardcoded outside claude_handler. Scanned as AST
    # string constants, minus docstrings, so prose that merely NAMES a model
    # (comments, module docs, this file) does not read as a call site — a
    # line-grep version of this check fired on its own explanatory comment.
    for path in sorted(_ROOT.glob("*.py")):
        if path.name in {"claude_handler.py", pathlib.Path(__file__).name}:
            continue
        for lineno, value in _model_literals(path):
            record("FAIL", "hardcoded-model", f"{path.name}:{lineno} {value}")


_MODEL_LITERAL_RE = re.compile(r"^claude-(haiku|sonnet|opus)\b")


def _model_literals(path: pathlib.Path):
    """Yield (lineno, value) for Anthropic model strings used as VALUES.

    Docstrings are excluded because a module explaining which model serves
    which tier is documentation, not drift.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings
                and _MODEL_LITERAL_RE.match(node.value.strip())):
            yield node.lineno, node.value


# ── 2-4. live tier checks ────────────────────────────────────────────────────

def check_tier(tier: servant_clients.Tier) -> None:
    if not tier.available:
        record("SKIP", f"{tier.name}/live",
               f"{tier.key_env} not set — tier UNVERIFIED")
        return

    try:
        text = servant_clients.call_openai_compatible(
            tier, system="Reply with the single word OK.", user="ping",
            max_tokens=16, label="verify/reachable")
    except ServantUnavailable as e:
        record("FAIL", f"{tier.name}/reachable", str(e))
        return
    record("PASS", f"{tier.name}/reachable", repr(text.strip()[:40]))

    try:
        parsed, info = servant_clients.call_json(
            tier,
            system='Reply with JSON only: {"ok": true, "tier": "<model name>"}',
            user="respond", max_tokens=120, label="verify/json")
    except (ServantUnavailable, ServantJSONError) as e:
        record("FAIL", f"{tier.name}/json", str(e))
    else:
        record("PASS" if isinstance(parsed, dict) else "FAIL",
               f"{tier.name}/json", f"{parsed} info={info}")

    # Under-budget on purpose: a long answer capped at a handful of tokens is
    # the reproducible way to get finish_reason=length out of a live provider.
    try:
        leaked = servant_clients.call_openai_compatible(
            tier,
            system="Answer in at least 200 words of continuous prose.",
            user="Explain how a hard disk works.",
            max_tokens=12, label="verify/truncation")
    except ServantUnavailable as e:
        ok = "truncated" in str(e)
        record("PASS" if ok else "WARN", f"{tier.name}/truncation",
               str(e)[:140])
    except ServantJSONError as e:
        record("FAIL", f"{tier.name}/truncation",
               f"truncation misreported as a JSON bug: {e}")
    else:
        record("FAIL", f"{tier.name}/truncation",
               f"truncated reply returned as success: {leaked[:80]!r}")


def main() -> int:
    offline = "--offline" in sys.argv
    check_registry()
    if offline:
        record("SKIP", "live", "--offline: no provider calls made")
    else:
        for tier in (servant_clients.SERVANT_GEN, servant_clients.SERVANT_MECH):
            check_tier(tier)

    failed = [r for r in RESULTS if r[0] == "FAIL"]
    skipped = [r for r in RESULTS if r[0] == "SKIP"]
    print(f"\n{len(RESULTS) - len(failed) - len(skipped)} passed, "
          f"{len(failed)} failed, {len(skipped)} skipped")
    if skipped:
        print("GATE NOT MET: skipped checks are unverified, not passing.")
    return 1 if failed or skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
