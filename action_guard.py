"""
action_guard.py — hard, code-level rules for action chains.

The AKIRA_PROMPT states these rules, but prompts are conventions — this
module is the enforcement. sensei.run_actions() sanitizes every chain
through here BEFORE anything executes, so no LLM output can violate:

  1. download_image NEVER runs in the same chain as search_image.
     Searching returns candidates; nothing downloads until the user names
     one in a LATER turn. (Live failure: "download me a picture of X"
     chained search + six downloads with zero user input.)
  2. At most ONE download_image per chain. Batch-downloading result
     indices 1..N from a single instruction is never allowed.

Pure module — no imports beyond typing, testable anywhere.
"""

from __future__ import annotations


def sanitize_actions(steps: list[dict]) -> tuple[list[dict], list[str]]:
    """Drop chain steps that violate the image-download rules.
    Returns (allowed_steps, spoken_notes). Dependent steps of a dropped
    download are skipped naturally by run_actions' failed_ids handling,
    because a dropped step's id never lands in step_results."""
    if not steps:
        return steps, []

    notes: list[str] = []
    has_search = any(s.get("action") == "search_image" for s in steps)
    allowed: list[dict] = []
    dropped_ids: set[str] = set()
    downloads_kept = 0

    for step in steps:
        action = step.get("action")

        # Cascade: anything depending on a dropped download is dropped too.
        dep = step.get("depends_on")
        if dep and dep in dropped_ids:
            print(f"[action_guard] dropped {action} (depends on dropped step '{dep}')")
            if step.get("id"):
                dropped_ids.add(step["id"])
            continue

        if action == "download_image":
            if has_search:
                print("[action_guard] BLOCKED download_image chained with "
                      "search_image — user must pick first")
                notes.append("I've pulled up the candidates — tell me which "
                             "one you want and I'll download just that one.")
                if step.get("id"):
                    dropped_ids.add(step["id"])
                continue
            if downloads_kept >= 1:
                print("[action_guard] BLOCKED extra download_image — "
                      "one download per turn")
                if step.get("id"):
                    dropped_ids.add(step["id"])
                continue
            downloads_kept += 1

        allowed.append(step)

    return allowed, notes
