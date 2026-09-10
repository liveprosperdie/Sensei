"""gateway_server/auth.py — Authentication, JWT token management, and one-time code exchange."""

from __future__ import annotations

import datetime
import secrets
import time
import uuid
import jwt
from gateway_server import config

# In-memory stores for code exchange, refresh tokens, and live user tiers
# In production, these map to Redis or the website DB.
_AUTH_CODES: dict[str, dict] = {}           # code -> {"user_id": ..., "tier": ..., "nonce": ..., "exp": ...}
_REFRESH_TOKENS: dict[str, dict] = {}        # token -> {"user_id": ..., "exp": ...}
_REVOKED_USERS: set[str] = set()             # user_ids whose active sessions are revoked
_USER_TIERS: dict[str, str] = {              # Simulated live website Stripe/subscription database
    "user_pro": "pro",
    "user_std": "standard",
    "user_free": "free",
    "test_user": "pro",
}


def create_auth_code(user_id: str, nonce: str, tier: str | None = None) -> str:
    """Create a short-lived one-time code (5 min TTL) for browser login hand-off."""
    code = f"code_{secrets.token_urlsafe(32)}"
    # Live lookup of tier from subscription DB — never trust client
    live_tier = tier or _USER_TIERS.get(user_id, "standard")
    _AUTH_CODES[code] = {
        "user_id": user_id,
        "tier": live_tier,
        "nonce": nonce,
        "exp": time.time() + 300  # 5 minutes
    }
    return code


def exchange_auth_code(code: str, nonce: str) -> tuple[str, str, str] | None:
    """Exchange one-time code and matching nonce for (user_id, tier, refresh_token)."""
    entry = _AUTH_CODES.pop(code, None)
    if not entry:
        return None
    if time.time() > entry["exp"]:
        return None
    if entry["nonce"] != nonce:
        return None

    user_id = entry["user_id"]
    # Verify live tier once again against subscription database
    live_tier = entry["tier"]
    try:
        from gateway_server import subscriptions
        st = subscriptions.get_user_status(user_id)
        if st and st.get("tier"):
            live_tier = st["tier"]
        else:
            live_tier = _USER_TIERS.get(user_id, entry["tier"])
    except Exception:
        live_tier = _USER_TIERS.get(user_id, entry["tier"])

    refresh_token = secrets.token_urlsafe(48)
    _REFRESH_TOKENS[refresh_token] = {
        "user_id": user_id,
        "exp": time.time() + (30 * 86400)  # 30 days
    }
    _REVOKED_USERS.discard(user_id)
    return user_id, live_tier, refresh_token


def issue_jwt(user_id: str, tier: str, secret: str | None = None) -> str:
    """Issue a signed HS256 JWT with 30-minute expiry."""
    signing_secret = secret or config.AKIRA_JWT_SECRET
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "tier": tier,
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(minutes=30)).timestamp()),
        "iss": "akira-gateway"
    }
    return jwt.encode(payload, signing_secret, algorithm="HS256")


def decode_jwt(token: str, secret: str | None = None) -> dict:
    """Decode and verify JWT signature and expiry."""
    signing_secret = secret or config.AKIRA_JWT_SECRET
    return jwt.decode(
        token,
        signing_secret,
        algorithms=["HS256"],
        issuer="akira-gateway",
        options={"require": ["sub", "tier", "exp", "iat"]}
    )


def refresh_jwt(refresh_token: str, secret: str | None = None) -> tuple[str, str] | None:
    """Refresh JWT using a valid refresh token. Returns (new_jwt, tier) or None."""
    entry = _REFRESH_TOKENS.get(refresh_token)
    if not entry:
        return None
    if time.time() > entry["exp"]:
        _REFRESH_TOKENS.pop(refresh_token, None)
        return None

    user_id = entry["user_id"]
    if user_id in _REVOKED_USERS:
        return None

    # Re-fetch live tier from Stripe/website DB or subscriptions table
    live_tier = "standard"
    try:
        from gateway_server import subscriptions
        st = subscriptions.get_user_status(user_id)
        if st and st.get("tier"):
            live_tier = st["tier"]
        else:
            live_tier = _USER_TIERS.get(user_id, "standard")
    except Exception:
        live_tier = _USER_TIERS.get(user_id, "standard")

    new_jwt = issue_jwt(user_id, live_tier, secret=secret)
    return new_jwt, live_tier


def revoke_user_sessions(user_id: str) -> None:
    """Revoke all active sessions and refresh tokens for a user."""
    _REVOKED_USERS.add(user_id)
    tokens_to_remove = [k for k, v in _REFRESH_TOKENS.items() if v.get("user_id") == user_id]
    for k in tokens_to_remove:
        _REFRESH_TOKENS.pop(k, None)


def set_user_subscription(user_id: str, tier: str) -> None:
    """Helper to update user tier in database (e.g. from Stripe webhook)."""
    _USER_TIERS[user_id] = tier
