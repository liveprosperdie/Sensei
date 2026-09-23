"""session_crypto_logger.py — Encrypted local session logging for Akira.

Records high-level, generalized summaries of user interactions and actions across
sessions, encrypted at rest using AES-128-CBC / HMAC-SHA256 (Fernet).

Zero sensitive text, credentials, private document contents, or personal email
bodies are stored in session logs.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet

logger = logging.getLogger("akira.session_crypto")

_MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")
_KEY_FILE = os.path.join(_MEMORY_DIR, ".session_vault.key")
_VAULT_FILE = os.path.join(_MEMORY_DIR, "session_history.vault")


def _get_or_create_cipher() -> Fernet:
    """Load or generate the local symmetric encryption key."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
    if os.path.exists(_KEY_FILE):
        try:
            with open(_KEY_FILE, "rb") as f:
                key = f.read().strip()
                if key:
                    return Fernet(key)
        except Exception as e:
            logger.warning("[session_crypto] Could not read vault key: %s — generating new", e)

    key = Fernet.generate_key()
    try:
        with open(_KEY_FILE, "wb") as f:
            f.write(key)
    except Exception as e:
        logger.error("[session_crypto] Failed to save vault key: %s", e)

    return Fernet(key)


def log_session_encrypted(
    session_id: str,
    action_history: list[dict[str, Any]],
    turn_count: int = 0
) -> str | None:
    """Write an encrypted, generalized summary of completed session actions.
    
    Returns the path to the vault file on success, or None on failure.
    """
    if not action_history and turn_count <= 0:
        return None

    # Generalize action intents into high-level privacy-safe descriptions
    generalized_intents = []
    apps_touched = set()

    for item in action_history:
        act = item.get("action", "")
        param = item.get("parameter", "")

        if act == "gmail_control":
            apps_touched.add("Gmail")
            if "search" in param:
                generalized_intents.append("Searched emails in Gmail")
            else:
                generalized_intents.append("Checked unread messages in Gmail")
        elif act == "calendar_control":
            apps_touched.add("Google Calendar")
            if "create" in param:
                generalized_intents.append("Scheduled calendar appointment")
            else:
                generalized_intents.append("Checked calendar schedule")
        elif act == "docs_control":
            apps_touched.add("Google Docs")
            title = param.split("|")[1] if "|" in param else "document"
            generalized_intents.append(f"Generated Google Doc on {title[:30]}")
        elif act == "office_control":
            if "excel" in param:
                apps_touched.add("Microsoft Excel")
                generalized_intents.append("Manipulated Excel spreadsheet")
            elif "word" in param:
                apps_touched.add("Microsoft Word")
                generalized_intents.append("Drafted Word document")
            elif "powerpoint" in param:
                apps_touched.add("PowerPoint")
                generalized_intents.append("Controlled PowerPoint presentation")
        elif act == "spotify_control":
            apps_touched.add("Spotify")
            generalized_intents.append("Controlled Spotify music playback")
        elif act == "youtube_control":
            apps_touched.add("YouTube")
            generalized_intents.append("Searched/played video on YouTube")
        elif act in ("search_file", "open_file", "summarize_file", "organize_folder"):
            apps_touched.add("File System")
            generalized_intents.append(f"Executed file operation ({act.replace('_', ' ')})")
        elif act:
            generalized_intents.append(f"System operation: {act}")

    session_record = {
        "session_id": session_id or f"session_{int(time.time())}",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_turns": turn_count,
        "generalized_intents": generalized_intents[:10],
        "applications_interacted": sorted(list(apps_touched)),
    }

    try:
        cipher = _get_or_create_cipher()
        serialized = json.dumps(session_record, ensure_ascii=False).encode("utf-8")
        encrypted_token = cipher.encrypt(serialized)

        with open(_VAULT_FILE, "ab") as f:
            f.write(encrypted_token + b"\n")

        print(f"[session_crypto] Encrypted session summary recorded ({len(generalized_intents)} intents)")
        return _VAULT_FILE
    except Exception as e:
        logger.error("[session_crypto] Failed to write encrypted session log: %s", e)
        return None


def read_decrypted_session_history(max_sessions: int = 5) -> list[dict[str, Any]]:
    """Decrypt and read recent generalized session records."""
    if not os.path.exists(_VAULT_FILE):
        return []

    records = []
    try:
        cipher = _get_or_create_cipher()
        with open(_VAULT_FILE, "rb") as f:
            lines = f.readlines()

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                decrypted_bytes = cipher.decrypt(line)
                record = json.loads(decrypted_bytes.decode("utf-8"))
                records.append(record)
                if len(records) >= max_sessions:
                    break
            except Exception as dec_err:
                logger.warning("[session_crypto] Error decrypting session line: %s", dec_err)

    except Exception as e:
        logger.error("[session_crypto] Error reading vault: %s", e)

    return records


def get_generalized_previous_sessions_summary(max_sessions: int = 3) -> str:
    """Decrypt and summarize recent sessions into high-level, privacy-safe text.
    
    Zero sensitive parameters, credentials, or file paths are included.
    """
    records = read_decrypted_session_history(max_sessions=max_sessions)
    if not records:
        return ""

    lines = []
    for r in records:
        ts = r.get("timestamp", "")
        apps = ", ".join(r.get("applications_interacted", [])) or "General"
        intents = ", ".join(r.get("generalized_intents", [])) or "Conversational query"
        lines.append(f"- Session ({ts}): Interacted with {apps} | Tasks: {intents}")

    return "\n".join(lines)
