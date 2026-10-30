"""procedural_memory/schema.py — Data models and normalization for procedures.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


def compute_plan_hash(actions: list[dict[str, Any]]) -> str:
    """Compute a canonical SHA-256 hash of the normalized action list."""
    canonical = []
    for a in actions:
        canonical.append({
            "action": str(a.get("action", "")).strip().lower(),
            "parameter": str(a.get("parameter", "")).strip() if a.get("parameter") is not None else None,
        })
    blob = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def normalize_trigger(text: str) -> str:
    """Normalize user trigger text: lowercase, strip punctuation, remove wake words and fillers."""
    t = (text or "").lower().strip()
    # Strip wake word if present
    t = re.sub(r"^(?:akira|sensei)[\s,:]+", "", t, flags=re.IGNORECASE).strip()
    # Strip non-alphanumeric except spaces
    t = re.sub(r"[^\w\s]", "", t)
    # Collapse multiple whitespaces
    return " ".join(t.split())


@dataclass
class StoredProcedure:
    id: str
    trigger: str
    normalized_trigger: str
    actions: list[dict[str, Any]]
    plan_hash: str
    response: str
    origin_brain: str  # "free" | "claude"
    tag: str = "recall-eligible"
    success_count: int = 1
    failure_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StoredProcedure:
        return cls(
            id=d["id"],
            trigger=d["trigger"],
            normalized_trigger=d["normalized_trigger"],
            actions=d["actions"],
            plan_hash=d.get("plan_hash") or compute_plan_hash(d["actions"]),
            response=d.get("response", ""),
            origin_brain=d.get("origin_brain", "unknown"),
            tag=d.get("tag", "recall-eligible"),
            success_count=int(d.get("success_count", 1)),
            failure_count=int(d.get("failure_count", 0)),
            created_at=float(d.get("created_at", time.time())),
            last_used_at=float(d.get("last_used_at", time.time())),
        )

    def is_replay_eligible(self, threshold: int = 2) -> bool:
        return self.success_count >= threshold and self.tag == "recall-eligible"


def normalize_incoming_envelope(envelope: dict[str, Any], origin_brain: str) -> Optional[dict[str, Any]]:
    """Normalize an incoming envelope from either Free brain or Claude brain.
    
    Enforces:
    - mode == "command"
    - no pending_actions
    - confirmation_required is False
    - no depends_on in any step
    
    Returns standard shape:
    {
        "mode": "command",
        "action": str,
        "parameter": str | None,
        "actions": list[dict],
        "response": str,
        "origin_brain": origin_brain,
    }
    or None if ineligible.
    """
    if not isinstance(envelope, dict):
        return None

    mode = str(envelope.get("mode", "")).strip().lower()
    if mode != "command":
        return None

    # Veto any confirmation-required or pending actions
    if envelope.get("confirmation_required") is True:
        return None
    if envelope.get("pending_actions") or envelope.get("pending_action"):
        return None

    raw_actions = envelope.get("actions")
    if not raw_actions and envelope.get("action"):
        raw_actions = [{"action": envelope["action"], "parameter": envelope.get("parameter")}]

    if not isinstance(raw_actions, list) or not raw_actions:
        return None

    normalized_steps = []
    for step in raw_actions:
        if not isinstance(step, dict):
            return None
        act = str(step.get("action", "")).strip()
        if not act:
            return None
        # Veto if depends_on is present
        if step.get("depends_on"):
            return None
        param = step.get("parameter")
        if param is not None:
            param = str(param).strip()
        normalized_steps.append({"action": act, "parameter": param})

    first_act = normalized_steps[0]["action"]
    first_param = normalized_steps[0]["parameter"]
    resp = str(envelope.get("response", "")).strip()

    return {
        "mode": "command",
        "action": first_act,
        "parameter": first_param,
        "actions": normalized_steps,
        "response": resp,
        "origin_brain": origin_brain.strip().lower(),
    }
