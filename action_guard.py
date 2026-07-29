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

Both rules cover office_control's "insert image" sub-action too. It resolves
a spoken pick through image_flow.download_image internally, so treating it as
anything other than a download would have let "find a picture of X and put it
in my document" bypass the pick step entirely via a different action name.

Pure module — no imports beyond typing, testable anywhere.
"""

from __future__ import annotations


def _is_image_download(step: dict) -> bool:
    """True for any step that downloads a picked image, under any action name."""
    action = step.get("action")
    if action == "download_image":
        return True
    if action == "office_control":
        param = (step.get("parameter") or "").lower()
        # "word|insert image|third" — the sub-action is the second field.
        fields = [f.strip() for f in param.split("|")]
        return len(fields) > 1 and fields[1].replace("_", " ") == "insert image"
    return False


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

        if _is_image_download(step):
            if has_search:
                print(f"[action_guard] BLOCKED {action} chained with "
                      "search_image — user must pick first")
                notes.append("I've pulled up the candidates — tell me which "
                             "one you want and I'll download just that one.")
                if step.get("id"):
                    dropped_ids.add(step["id"])
                continue
            if downloads_kept >= 1:
                print(f"[action_guard] BLOCKED extra {action} — "
                      "one image download per turn")
                if step.get("id"):
                    dropped_ids.add(step["id"])
                continue
            downloads_kept += 1

        allowed.append(step)

    return allowed, notes
