"""gateway_server/command_validator.py — Server-side validation for indirect commands."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger("akira.command_validator")

# Rejects shell metacharacters: & | ; < > ^ % ! " ` $ and newlines/carriage returns
_METACHUT_REGEX = re.compile(r'[&|;<>^%!"`$\r\n]')


def validate_command_string(candidate: str) -> tuple[bool, str]:
    """Validate a command/application string coming from untrusted or indirect channels.

    Direct voice commands are executed normally without this check.
    Indirect inputs (clipboard, scraped tabs, notes) must pass this validation.
    """
    if not candidate or not isinstance(candidate, str):
        return False, "Command or application string is empty."

    cleaned = candidate.strip()
    if len(cleaned) > 260:
        logger.warning("[validate-command] Rejected candidate exceeding MAX_PATH: %s", cleaned[:50])
        return False, "Application name or command string is too long (exceeds 260 characters)."

    match = _METACHUT_REGEX.search(cleaned)
    if match:
        logger.warning(
            "[validate-command] Blocked candidate containing shell metacharacter '%s': %s",
            match.group(0), cleaned
        )
        return False, "Invalid application name — blocked for safety."

    return True, "Valid application name."
