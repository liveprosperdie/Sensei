"""gateway_server/rate_limiter.py — Sliding Window Rate Limiting on Gateway Endpoints."""

from __future__ import annotations

import time
import threading
from collections import defaultdict
from gateway_server import config

try:
    import redis
except ImportError:
    redis = None

_lock = threading.Lock()
# In-memory sliding window fallback: key -> list of timestamps
_in_memory_windows: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
    """Check sliding-window rate limit. Returns (allowed, retry_after_seconds)."""
    now = time.time()
    cutoff = now - window_seconds

    with _lock:
        timestamps = _in_memory_windows[key]
        # Drop timestamps older than window
        valid = [ts for ts in timestamps if ts > cutoff]
        _in_memory_windows[key] = valid

        if len(valid) >= max_requests:
            earliest = valid[0]
            retry_after = max(1, int(earliest + window_seconds - now))
            return False, retry_after

        _in_memory_windows[key].append(now)
        return True, 0


def reset_rate_limits_for_testing():
    with _lock:
        _in_memory_windows.clear()
