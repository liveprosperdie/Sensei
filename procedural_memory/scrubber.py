"""procedural_memory/scrubber.py — PII, credential, deictic, and scope exclusion scrubber.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional, Tuple

logger = logging.getLogger("akira.procedural_memory.scrubber")

# ── Deictic / Context-Dependent Utterance Veto ────────────────────────────────
DEICTIC_PATTERN = re.compile(
    r"\b(today|tomorrow|yesterday|tonight|latest|last|this|that|these|those|"
    r"it|its|them|current|selected|again|next|recent|here|there|now|earlier|previous)\b",
    re.IGNORECASE,
)

# ── Credential & Secret Patterns ─────────────────────────────────────────────
CREDENTIAL_PATTERNS = (
    re.compile(r"\b(?:bearer\s+[a-zA-Z0-9_\-\.]{16,})\b", re.IGNORECASE),
    re.compile(r"\b(?:sk-[a-zA-Z0-9]{20,})\b"),                         # OpenAI/Anthropic
    re.compile(r"\b(?:ghp_[a-zA-Z0-9]{36,})\b"),                        # GitHub Personal Token
    re.compile(r"\b(?:AKIA[0-9A-Z]{16})\b"),                            # AWS Access Key
    re.compile(r"\b(?:xox[baprs]-[0-9a-zA-Z]{10,})\b"),                 # Slack Token
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),            # Private key
    re.compile(r"(?:https?://[^:\s]+:[^@\s]+@[^\s]+)"),                 # Basic auth in URL
    re.compile(r"\b(?:password|passwd|api_key|apikey|secret)\s*[:=]\s*['\"]?[^\s'\"]+", re.IGNORECASE),
)

# ── PII Patterns (Email, Phone, SSN, Credit Cards) ───────────────────────────
PII_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # Email
    re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # Phone number
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                                 # US SSN
    re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),                           # 16-digit card
)

# ── Date-like literals in parameters ─────────────────────────────────────────
DATE_LITERAL_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})\b",
    re.IGNORECASE,
)


def contains_credentials(text: str) -> bool:
    """Return True if text matches known credential, secret, or token patterns."""
    if not text:
        return False
    return any(p.search(text) for p in CREDENTIAL_PATTERNS)


def contains_pii(text: str) -> bool:
    """Return True if text matches email, phone, SSN, or financial PII patterns."""
    if not text:
        return False
    return any(p.search(text) for p in PII_PATTERNS)


def is_deictic_or_relative(text: str) -> bool:
    """Return True if text contains deictic, relative, or context-dependent terms."""
    if not text:
        return False
    return bool(DEICTIC_PATTERN.search(text))


def normalize_and_check_path_exclusion(path_str: str) -> bool:
    """Normalize path via normcase and realpath, then check against IndexScopeConfig.
    Returns True if the path is excluded.
    """
    if not path_str or not isinstance(path_str, str):
        return False

    # Check if this looks like a filesystem path
    if not ((":\\" in path_str) or (":/" in path_str) or path_str.startswith("\\\\") or path_str.startswith("/")):
        return False

    try:
        from file_index.config import IndexScopeConfig
        scope = IndexScopeConfig()
        norm_path = os.path.normcase(os.path.realpath(path_str))
        folder_name = os.path.basename(norm_path)
        return scope.is_excluded(folder_name, norm_path)
    except Exception as e:
        logger.debug("[scrubber] Scope exclusion check error for %s: %s", path_str, e)
        return False


def validate_procedure_safety(
    trigger: str,
    actions: list[dict[str, Any]],
    response: str = ""
) -> Tuple[bool, Optional[str]]:
    """Comprehensive safety check before storing or replaying a procedure.
    
    Returns (is_safe, rejection_reason).
    """
    # 1. Trigger deictic veto
    if is_deictic_or_relative(trigger):
        return False, "trigger_contains_deictic_or_relative_terms"

    # 2. Trigger credentials check
    if contains_credentials(trigger):
        return False, "trigger_contains_credentials"

    # 3. Trigger PII check
    if contains_pii(trigger):
        return False, "trigger_contains_pii"

    # 4. Spoken response checks
    if contains_credentials(response):
        return False, "response_contains_credentials"
    if contains_pii(response):
        return False, "response_contains_pii"

    # 5. Parameter checks for each action step
    for idx, step in enumerate(actions):
        param = step.get("parameter")
        if param is None:
            continue
        param_str = str(param)

        # Parameter credentials check
        if contains_credentials(param_str):
            return False, f"parameter_step_{idx}_contains_credentials"

        # Parameter PII check
        if contains_pii(param_str):
            return False, f"parameter_step_{idx}_contains_pii"

        # Check for resolved dates that likely leaked from dynamic date block
        if DATE_LITERAL_PATTERN.search(param_str):
            # If the user did not explicitly mention that exact date in their trigger, veto it!
            date_match = DATE_LITERAL_PATTERN.search(param_str).group(0)
            if date_match.lower() not in trigger.lower():
                return False, f"parameter_step_{idx}_contains_resolved_date_leak"

        # Path exclusion check
        # Extract potential path parts from delimited parameter string (e.g. "path|name")
        parts = param_str.split("|")
        for p in parts:
            p_clean = p.strip().strip("'\"")
            if normalize_and_check_path_exclusion(p_clean):
                return False, f"parameter_step_{idx}_path_in_excluded_scope"

    return True, None
