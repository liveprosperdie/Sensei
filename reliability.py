"""Per-action-type reliability ledger — the 20-run gate.

WHAT THIS IS AND WHY IT EXISTS HERE
===================================
Pro-tier Gated actions unlock per action TYPE once that type has cleared the
20-run reliability protocol. This module is that ledger.

HONEST PROVENANCE — read before trusting the semantics
-----------------------------------------------------
The brief describes the 20-run protocol as "existing" and referenced in the
project's architecture bible. I searched the repo for it before writing this:

    grep -rn "20-run|reliability|consecutive|success_count|promot|graduat" *.py
    -> 0 matches.

There is no implementation, and no architecture bible is committed to this
repository, so the protocol's exact rule could not be read. That leaves one
genuine ambiguity I cannot resolve from the code: whether "cleared 20 runs"
means 20 CONSECUTIVE successes or 20 cumulative runs at some success rate.

Rather than silently pick one and present it as "the existing protocol", both
are implemented and selectable, defaulting to consecutive:

    RELIABILITY_MODE=consecutive   (default) 20 successes in a row; any
                                   failure resets the streak to 0.
    RELIABILITY_MODE=cumulative    >=20 runs AND success rate >= threshold.

Consecutive is the default because it is the stricter reading and this gate
guards destructive actions. If the bible says otherwise, RELIABILITY_MODE is the
one-line correction and no logic changes.

WHY A LEDGER RATHER THAN A COUNTER
----------------------------------
Per action TYPE, not global: "delete_files has proven itself" says nothing about
shutdown_pc. A single global counter would let a hundred safe screenshots unlock
a file deletion that has never once run correctly, which inverts the point.

WHY THIS IS NOT COUPLED TO TIERS
--------------------------------
Nothing here knows what a tier is. tiers.py asks `cleared(action)`; this answers
from recorded history alone. That is what stops the Pro unlock from being a
hardcoded tier-name bypass — Pro does not skip the bar, it only becomes eligible
to consult it, and the bar itself is tier-blind. Keeping the two modules
separate is what makes that structurally true rather than merely intended.
"""

from __future__ import annotations

import datetime
import json
import os
import threading

# 20 is the specified bar. Env-overridable because the number is policy, not
# mechanism — and because a test that needed 20 real runs to exercise the unlock
# would never be written.
THRESHOLD = max(1, int(os.environ.get("RELIABILITY_RUNS", "20")))

MODE = (os.environ.get("RELIABILITY_MODE", "consecutive") or "").strip().lower()

# Only consulted in cumulative mode. 0.95 of 20 runs allows a single failure.
MIN_RATE = float(os.environ.get("RELIABILITY_MIN_RATE", "0.95"))

# Same LOCALAPPDATA\Sensei convention as gemini_content._QUOTA_FILE, so all
# persistent assistant state lands in one directory the user can inspect or
# delete, rather than a second scheme invented here.
LEDGER_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Sensei", "action_reliability.json")

# run_actions executes on the calling thread, but background_tasks runs its own
# threads and both can record. The lock covers the read-modify-write; the atomic
# replace below covers a crash mid-write.
_LOCK = threading.Lock()


def _load() -> dict:
    """Read the ledger. A corrupt or absent file is an empty history, never an
    error: losing the ledger must make actions MORE gated, not crash the
    assistant. An empty history means nothing has cleared, which is the safe
    direction to fail in."""
    try:
        with open(LEDGER_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    """Atomic write. A half-written ledger would read as corrupt on next load
    and silently reset every streak, so the temp-file-and-replace is not
    ceremony — os.replace is atomic on Windows for same-directory paths."""
    os.makedirs(os.path.dirname(LEDGER_FILE), exist_ok=True)
    tmp = LEDGER_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, LEDGER_FILE)


def _entry(data: dict, action: str) -> dict:
    return data.setdefault(action, {"runs": 0, "successes": 0, "streak": 0,
                                    "last_result": None, "last_run": None})


def record(action: str, success: bool) -> None:
    """Record one real execution outcome for an action type.

    Call this ONLY for attempts that actually ran. Recording a step that was
    refused before dispatch would let guard refusals look like action
    unreliability, and recording a success that never executed would inflate a
    streak toward unlocking a destructive action — the exact failure this gate
    exists to prevent.
    """
    if not action:
        return
    with _LOCK:
        data = _load()
        e = _entry(data, action)
        e["runs"] += 1
        if success:
            e["successes"] += 1
            e["streak"] += 1
        else:
            # Reset, not decrement: a streak is a claim of uninterrupted
            # correctness, and one failure falsifies it outright.
            e["streak"] = 0
        e["last_result"] = "success" if success else "failure"
        e["last_run"] = datetime.datetime.now().isoformat(timespec="seconds")
        _save(data)


def cleared(action: str) -> bool:
    """Has this action type cleared the reliability bar?

    Unknown action -> False. An action with no history has not proven anything,
    and defaulting to True would make the gate a no-op on a fresh install,
    which is precisely when it matters most.
    """
    e = _load().get(action)
    if not e:
        return False
    if MODE == "cumulative":
        runs = int(e.get("runs", 0))
        if runs < THRESHOLD:
            return False
        return (int(e.get("successes", 0)) / runs) >= MIN_RATE
    return int(e.get("streak", 0)) >= THRESHOLD


def remaining(action: str) -> int:
    """How many more clean runs are needed. Drives the spoken explanation, so
    the user hears "3 more successful runs" instead of a bare refusal."""
    e = _load().get(action) or {}
    if MODE == "cumulative":
        return max(0, THRESHOLD - int(e.get("runs", 0)))
    return max(0, THRESHOLD - int(e.get("streak", 0)))


def status(action: str) -> dict:
    """Full record for one action. Diagnostics and the verification gate."""
    e = dict(_load().get(action) or
             {"runs": 0, "successes": 0, "streak": 0,
              "last_result": None, "last_run": None})
    e.update(action=action, mode=MODE, threshold=THRESHOLD,
             cleared=cleared(action), remaining=remaining(action))
    return e


def all_status() -> dict:
    """Every action with recorded history, for a 'what's unlocked' report."""
    return {a: status(a) for a in sorted(_load())}


def reset(action: str | None = None) -> None:
    """Clear history for one action, or all of it. Test/maintenance only.

    Deliberately explicit and never called from the normal flow: automatic
    resets are how a gate quietly stops gating.
    """
    with _LOCK:
        if action is None:
            _save({})
            return
        data = _load()
        data.pop(action, None)
        _save(data)
