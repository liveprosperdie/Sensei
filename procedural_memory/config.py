"""procedural_memory/config.py — Configuration constants for local procedural memory.
"""

from __future__ import annotations

import os

# Storage paths
def get_procedures_dir() -> str:
    """Return the directory where procedures.db and .procedures.key reside.
    Defaults to %LOCALAPPDATA%\\Akira, overrideable via AKIRA_PROCEDURES_DIR.
    """
    override = os.environ.get("AKIRA_PROCEDURES_DIR")
    if override:
        return os.path.abspath(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = os.path.expanduser("~\\AppData\\Local")
    return os.path.join(local_app_data, "Akira")


def get_db_path() -> str:
    return os.path.join(get_procedures_dir(), "procedures.db")


def get_key_path() -> str:
    return os.path.join(get_procedures_dir(), ".procedures.key")


# Store limits
MAX_STORE_ENTRIES: int = 500
EXPIRY_DAYS: int = 90
SUCCESS_THRESHOLD: int = 2  # Requires 2 agreeing derivations before replay becomes eligible

# Announcements
REPLAY_ANNOUNCEMENT_CUE: str = "Using a learned workflow."
