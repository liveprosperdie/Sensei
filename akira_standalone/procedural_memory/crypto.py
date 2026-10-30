"""procedural_memory/crypto.py — DPAPI-wrapped Fernet key handling.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet

from .config import get_key_path, get_procedures_dir

logger = logging.getLogger("akira.procedural_memory.crypto")

try:
    import win32crypt
    _DPAPI_AVAILABLE = True
except ImportError:
    _DPAPI_AVAILABLE = False
    logger.warning("[procedural_memory.crypto] win32crypt not available — DPAPI disabled")


def get_or_create_cipher(key_path: Optional[str] = None) -> Fernet:
    """Load or generate a Fernet cipher, wrapping the key on disk with Windows DPAPI (user scope).
    
    If the key cannot be unwrapped, or if DPAPI fails, raises RuntimeError to let the caller
    fail open to an in-memory ephemeral store or empty cache.
    """
    path = key_path or get_key_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                blob = f.read()
            if not blob:
                raise ValueError("Key file is empty")

            if _DPAPI_AVAILABLE:
                # win32crypt.CryptUnprotectData returns (description, plaintext_bytes)
                _, raw_key = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
            else:
                raw_key = blob

            return Fernet(raw_key.strip())
        except Exception as e:
            logger.warning("[procedural_memory.crypto] Failed to unwrap DPAPI key at %s: %s", path, e)
            raise RuntimeError(f"Could not unwrap procedural memory DPAPI key: {e}") from e

    # Generate fresh key and wrap with DPAPI
    raw_key = Fernet.generate_key()
    try:
        if _DPAPI_AVAILABLE:
            blob = win32crypt.CryptProtectData(raw_key, "Akira Procedural Memory Key", None, None, None, 0)
        else:
            blob = raw_key

        # Write wrapped blob atomically via temp file
        tmp_path = path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(blob)
        os.replace(tmp_path, path)
        return Fernet(raw_key)
    except Exception as e:
        logger.error("[procedural_memory.crypto] Failed to protect/save DPAPI key at %s: %s", path, e)
        raise RuntimeError(f"Could not create and protect procedural memory DPAPI key: {e}") from e
