"""procedural_memory/shadow.py — Shadow mode telemetry and metrics tracking.

Logs ONLY aggregate counters:
- would-be hits
- fallbacks
- veto reasons by category (deictic, context_leak, pii, tag, exclusion, confirmation_or_pending)
- brain used (free vs claude)
- estimated tokens and latency saved

Zero raw user utterances are ever stored or logged in telemetry.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from .config import get_procedures_dir

logger = logging.getLogger("akira.procedural_memory.shadow")

# Default token and latency estimates per tier
_ESTIMATED_TOKENS_PER_HIT = {
    "claude": 1400,  # Prompt + response schema tokens
    "free": 800,
    "unknown": 1000,
}

_ESTIMATED_LATENCY_MS_PER_HIT = {
    "claude": 1200.0,
    "free": 450.0,
    "unknown": 800.0,
}


@dataclass
class ShadowStats:
    would_be_hits: int = 0
    fallbacks: int = 0
    vetoes_by_category: Dict[str, int] = field(default_factory=lambda: {
        "deictic": 0,
        "context_leak": 0,
        "pii": 0,
        "tag": 0,
        "exclusion": 0,
        "confirmation_or_pending": 0,
        "other": 0,
    })
    brain_counts: Dict[str, int] = field(default_factory=lambda: {
        "claude": 0,
        "free": 0,
        "unknown": 0,
    })
    estimated_tokens_saved: int = 0
    estimated_latency_saved_ms: float = 0.0
    recorded_procedures_count: int = 0
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ShadowStats:
        stats = cls(
            would_be_hits=int(d.get("would_be_hits", 0)),
            fallbacks=int(d.get("fallbacks", 0)),
            estimated_tokens_saved=int(d.get("estimated_tokens_saved", 0)),
            estimated_latency_saved_ms=float(d.get("estimated_latency_saved_ms", 0.0)),
            recorded_procedures_count=int(d.get("recorded_procedures_count", 0)),
            last_updated=float(d.get("last_updated", time.time())),
        )
        if "vetoes_by_category" in d and isinstance(d["vetoes_by_category"], dict):
            stats.vetoes_by_category.update(d["vetoes_by_category"])
        if "brain_counts" in d and isinstance(d["brain_counts"], dict):
            stats.brain_counts.update(d["brain_counts"])
        return stats


class ShadowTelemetry:
    """Thread-safe, privacy-preserving shadow mode telemetry manager."""

    def __init__(self, stats_path: Optional[str] = None):
        if stats_path:
            self.stats_path = stats_path
        else:
            self.stats_path = os.path.join(get_procedures_dir(), "shadow_stats.json")
        self.stats = ShadowStats()
        self.load()

    def load(self) -> None:
        """Load telemetry counters from disk."""
        if not os.path.exists(self.stats_path):
            return
        try:
            with open(self.stats_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.stats = ShadowStats.from_dict(data)
        except Exception as e:
            logger.warning("[shadow] Failed to load shadow stats: %s", e)

    def save(self) -> None:
        """Atomically persist telemetry counters to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(self.stats_path)), exist_ok=True)
        self.stats.last_updated = time.time()
        tmp_path = f"{self.stats_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.stats.to_dict(), f, indent=2)
            os.replace(tmp_path, self.stats_path)
        except Exception as e:
            logger.error("[shadow] Failed to save shadow stats: %s", e)

    def record_would_be_hit(self, origin_brain: str = "unknown") -> None:
        """Record a shadow match that would have been replayed."""
        brain = origin_brain.lower() if origin_brain in ("claude", "free") else "unknown"
        self.stats.would_be_hits += 1
        self.stats.brain_counts[brain] = self.stats.brain_counts.get(brain, 0) + 1
        self.stats.estimated_tokens_saved += _ESTIMATED_TOKENS_PER_HIT.get(brain, 1000)
        self.stats.estimated_latency_saved_ms += _ESTIMATED_LATENCY_MS_PER_HIT.get(brain, 800.0)
        self.save()

    def record_fallback(self, reason_category: Optional[str] = None) -> None:
        """Record a fallback to Tier 2."""
        self.stats.fallbacks += 1
        cat = (reason_category or "other").lower()
        if cat not in self.stats.vetoes_by_category:
            cat = "other"
        self.stats.vetoes_by_category[cat] = self.stats.vetoes_by_category.get(cat, 0) + 1
        self.save()

    def record_procedure_stored(self) -> None:
        """Increment count of stored procedures."""
        self.stats.recorded_procedures_count += 1
        self.save()

    def get_summary(self) -> dict[str, Any]:
        """Return aggregate metrics dictionary."""
        return self.stats.to_dict()


# Global singleton instance
_GLOBAL_TELEMETRY: Optional[ShadowTelemetry] = None


def get_shadow_telemetry() -> ShadowTelemetry:
    global _GLOBAL_TELEMETRY
    if _GLOBAL_TELEMETRY is None:
        _GLOBAL_TELEMETRY = ShadowTelemetry()
    return _GLOBAL_TELEMETRY
