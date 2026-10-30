"""procedural_memory/matcher.py — Matcher interface and ExactNormalizedMatcher.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .schema import StoredProcedure, normalize_trigger


@dataclass
class MatchResult:
    procedure: StoredProcedure
    confidence: float
    match_type: str  # "exact" | "bm25" | "semantic"


class Matcher(ABC):
    """Abstract interface for matching an incoming utterance against stored procedures."""

    @abstractmethod
    def match(self, utterance: str) -> Optional[MatchResult]:
        """Attempt to match the user utterance to a stored procedure."""
        raise NotImplementedError


class ExactNormalizedMatcher(Matcher):
    """v1 Matcher: Strict exact normalized string match only.
    
    Zero fuzzy confusion; fast O(1) hash lookup.
    """

    def __init__(self, store: Any):
        self.store = store

    def match(self, utterance: str) -> Optional[MatchResult]:
        norm = normalize_trigger(utterance)
        if not norm:
            return None

        proc = self.store.find_by_normalized_trigger(norm)
        if not proc:
            return None

        # Exact normalized match has confidence 1.0
        return MatchResult(
            procedure=proc,
            confidence=1.0,
            match_type="exact",
        )
