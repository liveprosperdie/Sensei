"""Deterministic adaptation rules. No model is called here.

The student's quiz result is judged locally. A model (the FREE tier, never the
HEAD) is only consulted when a threshold is breached, and only to WRITE a brief —
the decision itself is made here.
"""

from __future__ import annotations

from collections import Counter

from .schema import LEVELS

PROCEED_AT = 0.80
REVIEW_BAND = 0.60
UP_STREAK, UP_SCORE = 3, 0.95
DOWN_STREAK, DOWN_SCORE = 2, 0.60
MAX_REMEDIAL_TOTAL = 3


def grade(quiz: dict, answers: dict) -> dict:
    """Server-side grading. `answers` maps question id -> chosen option id."""
    graded, missed = [], Counter()
    right = 0
    for q in quiz["questions"]:
        chosen = answers.get(q["id"])
        ok = chosen == q["correct_option_id"]
        right += ok
        if not ok:
            missed[q["concept_tag"]] += 1
        graded.append({
            "id": q["id"], "selected": chosen, "correct_option_id": q["correct_option_id"],
            "is_correct": ok, "explanation": q.get("explanation", ""),
            "concept_tag": q["concept_tag"],
        })
    total = len(quiz["questions"])
    return {"score": round(right / total, 3) if total else 0.0, "right": right,
            "total": total, "graded": graded, "missed_tags": dict(missed)}


def _shift(level: str, step: int) -> str:
    i = max(0, min(len(LEVELS) - 1, LEVELS.index(level) + step))
    return LEVELS[i]


def decide(meta: dict, lesson: dict, result: dict) -> dict:
    """Return {"action": proceed|insert_remedial_lesson|adjust_depth, ...}."""
    score = result["score"]
    lessons = meta.get("lessons", [])
    remedial_total = sum(1 for l in lessons if l.get("type") == "remedial")
    prior = [l["quiz_score"] for l in lessons
             if l.get("id") != lesson["id"] and isinstance(l.get("quiz_score"), (int, float))
             and l.get("state") == "completed"]
    recent = prior + [score]
    depth = (meta.get("calibration") or {}).get("calibrated_depth", "intermediate")

    repeated = [t for t, n in result["missed_tags"].items() if n >= 2]
    breached = score < REVIEW_BAND or (repeated and score < PROCEED_AT)
    if breached and lesson.get("type") != "remedial" and remedial_total < MAX_REMEDIAL_TOTAL:
        worst = max(result["missed_tags"].items(), key=lambda kv: kv[1])[0] if result["missed_tags"] else None
        return {"action": "insert_remedial_lesson", "reason": "threshold_breached",
                "focus_tag": worst, "needs_model": True}

    if len(recent) >= DOWN_STREAK and all(s < DOWN_SCORE for s in recent[-DOWN_STREAK:]) and depth != LEVELS[0]:
        return {"action": "adjust_depth", "direction": "down", "new_depth": _shift(depth, -1),
                "reason": "two_low_scores", "needs_model": False}
    if len(recent) >= UP_STREAK and all(s >= UP_SCORE for s in recent[-UP_STREAK:]) and depth != LEVELS[-1]:
        return {"action": "adjust_depth", "direction": "up", "new_depth": _shift(depth, +1),
                "reason": "three_near_perfect", "needs_model": False}

    if score >= PROCEED_AT:
        return {"action": "proceed", "reason": "score_ok", "needs_model": False}
    return {"action": "proceed", "reason": "review_band", "needs_model": True, "review_notes": True}
