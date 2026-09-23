"""procedural_memory/pipeline.py — Integration pipeline coordinator for Akira.

Supports:
- AKIRA_PROCEDURAL_MEMORY_MODE: "shadow" (default) | "replay" | "off"
- Deferred derivation accounting on Turn N+1
- Universal correction handling
- Strict safety vetoes before matching or staging
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Optional

from .config import REPLAY_ANNOUNCEMENT_CUE
from .matcher import ExactNormalizedMatcher
from .schema import (
    StoredProcedure,
    compute_plan_hash,
    normalize_incoming_envelope,
    normalize_trigger,
)
from .scrubber import (
    contains_credentials,
    contains_pii,
    is_deictic_or_relative,
    normalize_and_check_path_exclusion,
    validate_procedure_safety,
)
from .shadow import get_shadow_telemetry
from .store import ProceduralStore
from .tags import TAG_RECALL_ELIGIBLE, get_plan_tag

logger = logging.getLogger("akira.procedural_memory.pipeline")

# Correction pattern
CORRECTION_PATTERN = re.compile(
    r"\b(no|nope|nah|not that|undo|wrong|cancel that|stop that|wait no|don't do that|that was wrong)\b",
    re.IGNORECASE,
)

# Global store and pipeline state
_STORE: Optional[ProceduralStore] = None
_PENDING_DERIVATION: Optional[Dict[str, Any]] = None
_LAST_RECALLED_ID: Optional[str] = None


def get_store() -> ProceduralStore:
    global _STORE
    if _STORE is None:
        _STORE = ProceduralStore()
    return _STORE


def get_mode() -> str:
    """Return active mode: 'shadow' (default), 'replay', or 'off'."""
    mode = os.environ.get("AKIRA_PROCEDURAL_MEMORY_MODE", "shadow").strip().lower()
    if mode in ("replay", "shadow", "off"):
        return mode
    return "shadow"


def resolve_deferred_accounting(incoming_text: str) -> None:
    """Evaluate Turn N+1 text against Turn N staged derivation.
    
    If user utterance is a correction, discard staged derivation.
    If no correction, commit derivation to store.
    """
    global _PENDING_DERIVATION, _LAST_RECALLED_ID
    if not _PENDING_DERIVATION and not _LAST_RECALLED_ID:
        return

    is_correction = bool(CORRECTION_PATTERN.search(incoming_text or ""))

    if is_correction:
        if _PENDING_DERIVATION:
            logger.info("[procedural_memory] Deferred derivation cancelled by user correction")
            _PENDING_DERIVATION = None

        if _LAST_RECALLED_ID:
            store = get_store()
            store.record_correction(_LAST_RECALLED_ID)
            logger.info("[procedural_memory] Replay %s penalized by user correction", _LAST_RECALLED_ID)
            _LAST_RECALLED_ID = None
        return

    # No correction detected -> commit staged derivation
    if _PENDING_DERIVATION:
        proc: StoredProcedure = _PENDING_DERIVATION["procedure"]
        try:
            store = get_store()
            updated = store.record_derivation(proc)
            telemetry = get_shadow_telemetry()
            telemetry.record_procedure_stored()
            logger.info(
                "[procedural_memory] Committed derivation %s (success_count=%d)",
                updated.id,
                updated.success_count,
            )
        except Exception as e:
            logger.warning("[procedural_memory] Failed to commit derivation: %s", e)
        finally:
            _PENDING_DERIVATION = None


def check_procedural_recall(user_text: str) -> Optional[dict[str, Any]]:
    """Check procedural memory for a match.
    
    In 'shadow' mode (default): logs would-be hits or fallbacks, returns None.
    In 'replay' mode: returns validated executable envelope.
    In 'off' mode: returns None immediately.
    """
    global _LAST_RECALLED_ID
    mode = get_mode()
    if mode == "off":
        return None

    # Resolve deferred turn accounting first
    resolve_deferred_accounting(user_text)

    telemetry = get_shadow_telemetry()
    store = get_store()
    if not store.learning_enabled:
        return None

    matcher = ExactNormalizedMatcher(store)
    match = matcher.match(user_text)

    if not match:
        telemetry.record_fallback("no_match")
        return None

    proc = match.procedure
    if not proc.is_replay_eligible():
        telemetry.record_fallback("under_threshold")
        return None

    # Validate replay safety (exclusions, credentials, PII)
    is_safe, reason = validate_procedure_safety(user_text, proc.actions, proc.response)
    if not is_safe:
        # Map rejection reason to high-level category
        cat = "other"
        if "deictic" in str(reason):
            cat = "deictic"
        elif "pii" in str(reason):
            cat = "pii"
        elif "credential" in str(reason):
            cat = "pii"
        elif "excluded_scope" in str(reason):
            cat = "exclusion"
        elif "date_leak" in str(reason):
            cat = "context_leak"
        telemetry.record_fallback(cat)
        return None

    # Match passed all safety criteria!
    if mode == "shadow":
        telemetry.record_would_be_hit(proc.origin_brain)
        logger.info(
            "[procedural_memory.shadow] Would-be hit: id=%s brain=%s actions=%d (replay suppressed in shadow mode)",
            proc.id,
            proc.origin_brain,
            len(proc.actions),
        )
        return None

    if mode == "replay":
        _LAST_RECALLED_ID = proc.id
        telemetry.record_would_be_hit(proc.origin_brain)

        # Prepend transparency cue
        clean_resp = proc.response.strip() if proc.response else f"Running {proc.actions[0]['action']}."
        spoken_response = f"{REPLAY_ANNOUNCEMENT_CUE} {clean_resp}"

        first_act = proc.actions[0]["action"]
        first_param = proc.actions[0].get("parameter")

        return {
            "mode": "command",
            "action": first_act,
            "parameter": first_param,
            "actions": proc.actions,
            "response": spoken_response,
            "confirmation_required": False,
            "origin_brain": proc.origin_brain,
            "is_replayed": True,
            "procedure_id": proc.id,
        }

    return None


def stage_pending_derivation(
    user_text: str,
    envelope: dict[str, Any],
    origin_brain: str,
    pc_context: Optional[dict[str, Any]] = None,
) -> None:
    """Stage a completed, guard-passed Tier-2 plan for deferred registration on Turn N+1."""
    global _PENDING_DERIVATION
    mode = get_mode()
    if mode == "off":
        return

    telemetry = get_shadow_telemetry()
    norm_env = normalize_incoming_envelope(envelope, origin_brain=origin_brain)
    if not norm_env:
        telemetry.record_fallback("confirmation_or_pending")
        return

    # 1. Tagging check (default-deny)
    actions = norm_env["actions"]
    plan_tag = get_plan_tag(actions)
    if plan_tag != TAG_RECALL_ELIGIBLE:
        telemetry.record_fallback("tag")
        return

    # 2. Safety scrubber validation (credentials, PII, deictic, path exclusions)
    is_safe, reason = validate_procedure_safety(user_text, actions, norm_env.get("response", ""))
    if not is_safe:
        cat = "other"
        if "deictic" in str(reason):
            cat = "deictic"
        elif "pii" in str(reason) or "credential" in str(reason):
            cat = "pii"
        elif "excluded_scope" in str(reason):
            cat = "exclusion"
        elif "date_leak" in str(reason):
            cat = "context_leak"
        telemetry.record_fallback(cat)
        return

    # 3. Context-leak veto (focused app, page title, URL)
    if pc_context and isinstance(pc_context, dict):
        fg_app = str(pc_context.get("foreground_app") or "").strip().lower()
        curr_url = str(pc_context.get("current_url") or "").strip().lower()
        curr_title = str(pc_context.get("current_page_title") or "").strip().lower()
        u_lower = user_text.lower()

        for step in actions:
            p_str = str(step.get("parameter") or "").lower()
            if fg_app and fg_app not in ("unknown", "") and fg_app in p_str and fg_app not in u_lower:
                telemetry.record_fallback("context_leak")
                return
            if curr_url and curr_url not in ("about:blank", "chrome://newtab/", "") and curr_url in p_str and curr_url not in u_lower:
                telemetry.record_fallback("context_leak")
                return
            if curr_title and len(curr_title) > 5 and curr_title in p_str and curr_title not in u_lower:
                telemetry.record_fallback("context_leak")
                return

    # Construct StoredProcedure candidate
    norm_trigger = normalize_trigger(user_text)
    if not norm_trigger:
        return

    plan_hash = compute_plan_hash(actions)
    proc_id = f"proc_{plan_hash}"

    candidate = StoredProcedure(
        id=proc_id,
        trigger=user_text.strip(),
        normalized_trigger=norm_trigger,
        actions=actions,
        plan_hash=plan_hash,
        response=norm_env.get("response", ""),
        origin_brain=origin_brain.strip().lower(),
        tag=TAG_RECALL_ELIGIBLE,
        success_count=1,
    )

    _PENDING_DERIVATION = {
        "user_text": user_text,
        "procedure": candidate,
        "staged_at": time.time(),
    }
    logger.debug("[procedural_memory] Staged pending derivation for %s", proc_id)
