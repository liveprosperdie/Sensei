"""Authentication and User Account Management for Teaching Mode Web App.

Provides secure SQLite-backed user storage, PBKDF2 password hashing,
and signed HMAC-SHA256 session tokens. Zero third-party dependencies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional

from . import config

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get_secret_key() -> bytes:
    env_secret = os.environ.get("TEACHING_SECRET_KEY")
    if env_secret:
        return env_secret.encode("utf-8")
    key_path = config.workspace_root() / ".secret_key"
    if key_path.exists():
        try:
            return key_path.read_bytes().strip()
        except Exception:
            pass
    secret = secrets.token_bytes(32)
    try:
        key_path.write_bytes(secret)
    except Exception:
        pass
    return secret


def _db_path() -> Path:
    return config.workspace_root() / "auth.db"


def _init_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        conn.commit()


_init_db()


def _hash_password(password: str, salt: str) -> str:
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    )
    return base64.b64encode(key).decode("ascii")


def create_token(user_id: str, email: str, expires_in_days: int = 30) -> str:
    exp = int(time.time()) + (expires_in_days * 86400)
    payload = json.dumps({"uid": user_id, "email": email, "exp": exp}, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(_get_secret_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def verify_token(token: str) -> Optional[dict]:
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(_get_secret_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode("ascii").rstrip("=")
        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None
        rem = len(payload_b64) % 4
        padded = payload_b64 + ("=" * (4 - rem) if rem else "")
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        if data.get("exp", 0) < int(time.time()):
            return None
        return {"id": data.get("uid"), "email": data.get("email")}
    except Exception:
        return None


def register_user(email: str, password: str) -> dict:
    email_clean = (email or "").strip().lower()
    if not EMAIL_RE.match(email_clean):
        raise ValueError("Invalid email address format.")
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    user_id = f"usr_{secrets.token_hex(8)}"
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    _init_db()
    try:
        with sqlite3.connect(str(_db_path())) as conn:
            conn.execute(
                "INSERT INTO users (id, email, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email_clean, pw_hash, salt, created_at),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError("An account with this email already exists.")

    token = create_token(user_id, email_clean)
    return {"id": user_id, "email": email_clean, "token": token}


def login_user(email: str, password: str) -> dict:
    email_clean = (email or "").strip().lower()
    _init_db()
    with sqlite3.connect(str(_db_path())) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, password_hash, salt FROM users WHERE email = ?", (email_clean,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Incorrect email or password.")
        uid, email_db, pw_hash, salt = row
        expected_hash = _hash_password(password, salt)
        if not hmac.compare_digest(pw_hash, expected_hash):
            raise ValueError("Incorrect email or password.")
        
    token = create_token(uid, email_db)
    return {"id": uid, "email": email_db, "token": token}


def get_user_by_id(user_id: str) -> Optional[dict]:
    _init_db()
    with sqlite3.connect(str(_db_path())) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {"id": row[0], "email": row[1], "created_at": row[2]}
