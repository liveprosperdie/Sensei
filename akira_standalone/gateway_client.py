"""gateway_client.py — Central Client for Akira Gateway and Dev Fallback Isolation."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("akira.gateway_client")

GATEWAY_URL = (os.environ.get("AKIRA_GATEWAY_URL") or "http://127.0.0.1:8000").rstrip("/")
_TOKEN_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Akira", "session.json"
)

_dev_warning_shown = False
_lock = threading.Lock()


@dataclass(frozen=True)
class _TextBlockShim:
    text: str
    type: str = "text"


@dataclass(frozen=True)
class GatewayReply:
    content: list[_TextBlockShim]
    stop_reason: str = "end_turn"
    provider: str = "gateway"


def is_dev_direct_keys() -> bool:
    """Check if the developer explicitly opted into using local .env keys directly."""
    global _dev_warning_shown
    val = (os.environ.get("AKIRA_DEV_DIRECT_KEYS") or "").strip().lower()
    active = val in ("1", "true", "yes", "on")
    if active and not _dev_warning_shown:
        with _lock:
            if not _dev_warning_shown:
                print("=" * 80)
                print("[DEV MODE] Using local API keys directly — this must be disabled "
                      "before any real distribution/release build.")
                print("=" * 80)
                _dev_warning_shown = True
    return active


def get_stored_tokens() -> dict:
    """Retrieve cached JWT and refresh token from secure local app storage."""
    try:
        if os.path.exists(_TOKEN_FILE):
            with open(_TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_tokens(data: dict) -> None:
    """Persist session JWT and refresh token."""
    try:
        os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
        with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning("Could not persist session tokens: %s", e)


def get_valid_jwt() -> str | None:
    """Return an active JWT, silently refreshing if near expiry."""
    tokens = get_stored_tokens()
    jwt_token = tokens.get("access_token")
    if not jwt_token:
        return None

    # Check if expired or refresh needed
    try:
        import jwt as pyjwt
        # Decode without verification just to check exp timestamp
        payload = pyjwt.decode(jwt_token, options={"verify_signature": False})
        exp = payload.get("exp", 0)
        # If expiring in less than 5 minutes, refresh
        if time.time() > (exp - 300):
            refresh_token = tokens.get("refresh_token")
            if refresh_token:
                refreshed = refresh_jwt(refresh_token)
                if refreshed:
                    return refreshed
    except Exception:
        pass

    return jwt_token


def refresh_jwt(refresh_token: str) -> str | None:
    """Silently refresh session token against /v1/auth/refresh."""
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/v1/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=10.0
        )
        if resp.status_code == 200:
            data = resp.json()
            tokens = get_stored_tokens()
            tokens["access_token"] = data["access_token"]
            if "refresh_token" in data:
                tokens["refresh_token"] = data["refresh_token"]
            save_tokens(tokens)
            return data["access_token"]
    except Exception as e:
        logger.warning("[gateway_client] Token refresh failed: %s", e)
    return None


def call_route(
    messages: list[dict],
    system: str | list | None = None,
    model: str | None = None,
    action: str | None = None,
    parameters: str | None = None,
    max_tokens: int = 1600,
    temperature: float = 0.0,
    output_config: dict | None = None
) -> GatewayReply | None:
    """Route LLM call through POST /v1/route for Standard and Pro tiers.

    Zero Content Logging: Server proxies call and counts usage without storing prompts.
    """
    jwt_token = get_valid_jwt()
    # Fallback to dev key in local dev if token not set
    headers = {"Content-Type": "application/json"}
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"

    payload = {
        "messages": messages,
        "system": system if isinstance(system, str) else None,
        "model": model,
        "action": action,
        "parameters": parameters,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "output_config": output_config
    }

    try:
        resp = requests.post(
            f"{GATEWAY_URL}/v1/route",
            headers=headers,
            json=payload,
            timeout=35.0
        )
        if resp.status_code == 200:
            data = resp.json()
            content_blocks = [
                _TextBlockShim(b.get("text", "")) for b in data.get("content", [])
            ]
            return GatewayReply(
                content=content_blocks,
                stop_reason=data.get("stop_reason", "end_turn"),
                provider=data.get("provider", "gateway")
            )
        elif resp.status_code == 429:
            body = resp.json()
            detail = body.get("detail", "Daily quota exceeded.")
            err_json = json.dumps({"mode": "conversation", "response": detail, "end_session": False})
            return GatewayReply(content=[_TextBlockShim(err_json)], stop_reason="end_turn")
        else:
            logger.error("[gateway_client] Gateway returned HTTP %d: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("[gateway_client] Failed to connect to gateway: %s", e)

    return None


def validate_indirect_command(command: str) -> tuple[bool, str]:
    """Check command string against server validation endpoint POST /v1/validate-command."""
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/v1/validate-command",
            json={"command": command},
            timeout=5.0
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("valid", False), data.get("message", "")
    except Exception as e:
        logger.warning("[gateway_client] Command validation endpoint unreachable (%s) — using local check", e)
        # Fallback to local check if gateway is unreachable
        from gateway_server import command_validator
        return command_validator.validate_command_string(command)

    return False, "Validation failed."
