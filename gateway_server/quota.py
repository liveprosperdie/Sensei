"""gateway_server/quota.py — Atomic Quota Tracking and Outage-Resilient Groq Fallback."""

from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import NamedTuple

try:
    import redis
except ImportError:
    redis = None

from gateway_server import config

logger = logging.getLogger("akira.quota")

_LUA_ATOMIC_INCR = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local current = tonumber(redis.call('get', key) or "0")
if current < limit then
    local new_val = redis.call('incr', key)
    if new_val == 1 then
        redis.call('expire', key, 86400)
    end
    return new_val
else
    return -1
end
"""

_lock = threading.Lock()
_in_memory_counters: dict[str, int] = {}
_redis_client: redis.Redis | None = None
_redis_was_down: bool = False


class QuotaVerdict(NamedTuple):
    allowed: bool
    use_fallback: bool
    used_today: int
    cap: int
    remaining: int
    reason: str | None
    redis_outage: bool = False


def _get_redis() -> redis.Redis | None:
    global _redis_client, _redis_was_down
    if redis is None:
        return None
    try:
        if _redis_client is None:
            _redis_client = redis.Redis.from_url(config.REDIS_URL, socket_timeout=1.5)
        _redis_client.ping()
        if _redis_was_down:
            logger.info("[QUOTA] Redis connectivity restored. Resuming normal quota-gated Claude routing.")
            _redis_was_down = False
        return _redis_client
    except Exception as e:
        if not _redis_was_down:
            logger.error("[QUOTA] Redis unreachable (%s). Standard/Pro routing degraded to Groq free fallback.", e)
            _redis_was_down = True
        return None


def set_redis_client(client) -> None:
    """Explicitly set or clear the Redis client instance (e.g. for testing or custom pool)."""
    global _redis_client
    _redis_client = client


def get_today_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def log_fallback_event(user_id: str, tier: str, reason: str) -> None:
    """Internal telemetry: logs fallback transitions for analytics/capacity (Requirement #13)."""
    telemetry_logger = logging.getLogger("akira.telemetry.fallback")
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    telemetry_logger.info(
        json.dumps({
            "event": "fallback_routing",
            "user_id": user_id,
            "timestamp": now_iso,
            "tier_from": tier,
            "reason": reason
        })
    )


def check_and_increment_turn(user_id: str, tier: str) -> QuotaVerdict:
    """Atomic quota check and increment for Standard, Pro, and Fallback tiers.

    - Free tier does not call this function (Free is 100% local and unmetered).
    - Checks Claude cap (Standard=30, Pro=53, Fallback=0).
    - If Claude cap reached OR user is on fallback tier OR Redis is down, automatically shifts to Groq free API fallback.
    - If Groq fallback is also exhausted, returns allowed=False (HTTP 429).
    """
    valid_tiers = ("standard", "pro", "fallback_permanent", "fallback_tier", "fallback")
    if tier not in valid_tiers:
        return QuotaVerdict(
            allowed=False, use_fallback=False, used_today=0, cap=0, remaining=0,
            reason=f"Unknown tier '{tier}'."
        )

    claude_cap = config.TIER_CAPS.get(tier, 0 if "fallback" in tier else 30)
    fallback_cap = config.TIER_CAPS.get("fallback_groq", 250)
    today = get_today_str()

    claude_key = f"akira:user:{user_id}:quota_claude:{today}"
    fallback_key = f"akira:user:{user_id}:quota_fallback_groq:{today}"

    r = _get_redis()

    # Case 1: Redis is DOWN -> E.3 Revised: Gracefully degrade to Groq free fallback!
    if r is None:
        # In dev or prod: use in-memory fallback counter for Groq during outage
        with _lock:
            current_fb = _in_memory_counters.get(fallback_key, 0)
            if current_fb < fallback_cap:
                _in_memory_counters[fallback_key] = current_fb + 1
                return QuotaVerdict(
                    allowed=True,
                    use_fallback=True,
                    used_today=current_fb + 1,
                    cap=fallback_cap,
                    remaining=fallback_cap - (current_fb + 1),
                    reason="Redis outage: routed to Groq free fallback.",
                    redis_outage=True
                )
            else:
                return QuotaVerdict(
                    allowed=False,
                    use_fallback=True,
                    used_today=current_fb,
                    cap=fallback_cap,
                    remaining=0,
                    reason=f"Daily limit reached on both Claude and fallback models. Resets at {config.RESET_TIME_UTC}.",
                    redis_outage=True
                )

    # Case 2: Redis is UP -> Perform atomic Lua script check
    try:
        res = r.eval(_LUA_ATOMIC_INCR, 1, claude_key, claude_cap)
        if res != -1:
            # Successfully incremented Claude turn within cap!
            used = int(res)
            return QuotaVerdict(
                allowed=True,
                use_fallback=False,
                used_today=used,
                cap=claude_cap,
                remaining=max(0, claude_cap - used),
                reason=None
            )

        # Claude cap was reached! Check and increment Groq fallback atomically:
        fb_res = r.eval(_LUA_ATOMIC_INCR, 1, fallback_key, fallback_cap)
        if fb_res != -1:
            fb_used = int(fb_res)
            fallback_reason = "trial_expired" if "fallback" in tier else "quota_exhausted"
            log_fallback_event(user_id, tier, fallback_reason)
            logger.info("[QUOTA] User %s exceeded Claude cap (%d/%d). Auto-shifted to Groq fallback (%d/%d).",
                        user_id, claude_cap, claude_cap, fb_used, fallback_cap)
            return QuotaVerdict(
                allowed=True,
                use_fallback=True,
                used_today=fb_used,
                cap=fallback_cap,
                remaining=max(0, fallback_cap - fb_used),
                reason="Claude daily cap reached. Using Groq free fallback."
            )

        # Both Claude and Groq fallback exhausted!
        return QuotaVerdict(
            allowed=False,
            use_fallback=True,
            used_today=fallback_cap,
            cap=fallback_cap,
            remaining=0,
            reason=f"Daily limit reached on both Claude and fallback models. Resets at {config.RESET_TIME_UTC}."
        )
    except Exception as e:
        logger.error("[QUOTA] Redis eval failed (%s) — falling back to Groq outage path.", e)
        # Fall back to Groq free fallback
        with _lock:
            current_fb = _in_memory_counters.get(fallback_key, 0)
            if current_fb < fallback_cap:
                _in_memory_counters[fallback_key] = current_fb + 1
                return QuotaVerdict(
                    allowed=True,
                    use_fallback=True,
                    used_today=current_fb + 1,
                    cap=fallback_cap,
                    remaining=fallback_cap - (current_fb + 1),
                    reason="Redis execution failure: routed to Groq free fallback.",
                    redis_outage=True
                )
            return QuotaVerdict(
                allowed=False,
                use_fallback=True,
                used_today=fallback_cap,
                cap=fallback_cap,
                remaining=0,
                reason=f"Daily limit reached on both Claude and fallback models. Resets at {config.RESET_TIME_UTC}.",
                redis_outage=True
            )


def get_user_quota_summary(user_id: str, tier: str) -> dict:
    """Return status summary for GET /v1/quota."""
    claude_cap = config.TIER_CAPS.get(tier, 30)
    fallback_cap = config.TIER_CAPS.get("fallback_groq", 250)
    today = get_today_str()

    claude_key = f"akira:user:{user_id}:quota_claude:{today}"
    fallback_key = f"akira:user:{user_id}:quota_fallback_groq:{today}"

    r = _get_redis()
    claude_used = 0
    fallback_used = 0
    if r is not None:
        try:
            claude_used = int(r.get(claude_key) or 0)
            fallback_used = int(r.get(fallback_key) or 0)
        except Exception:
            pass
    else:
        with _lock:
            claude_used = _in_memory_counters.get(claude_key, 0)
            fallback_used = _in_memory_counters.get(fallback_key, 0)

    claude_rem = max(0, claude_cap - claude_used)
    fallback_rem = max(0, fallback_cap - fallback_used)

    return {
        "user_id": user_id,
        "tier": tier,
        "primary_model": "claude",
        "primary_used": claude_used,
        "primary_cap": claude_cap,
        "primary_remaining": claude_rem,
        "fallback_model": "groq",
        "fallback_active": claude_rem == 0,
        "fallback_used": fallback_used,
        "fallback_cap": fallback_cap,
        "fallback_remaining": fallback_rem,
        "reset_time": config.RESET_TIME_UTC
    }


def reset_counters_for_testing():
    """Clear in-memory and test Redis counters (used by test suites)."""
    global _in_memory_counters, _redis_was_down, _redis_client
    with _lock:
        _in_memory_counters.clear()
        _redis_was_down = False
    if _redis_client is not None:
        try:
            keys = _redis_client.keys("akira:user:*")
            if keys:
                _redis_client.delete(*keys)
        except Exception:
            pass
