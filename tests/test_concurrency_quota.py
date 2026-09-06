"""tests/test_concurrency_quota.py — Concurrency and Race Condition Acceptance Tests.

Verifies:
1. 10 parallel threads at cap boundary (5 slots remaining -> exactly 5 get Claude, exactly 5 get Groq fallback).
2. 10 parallel threads at fallback ceiling boundary (5 slots remaining -> exactly 5 succeed, exactly 5 get 429).
3. Thread-safety: Atomic Lua execution guarantees zero over-allocation or lost updates.
"""

from __future__ import annotations

import concurrent.futures
import os
import threading
import unittest

os.environ["AKIRA_JWT_SECRET"] = "super-secret-test-jwt-key-32-chars-minimum!!"
os.environ["AKIRA_ENV"] = "test"

from gateway_server import quota


class ThreadSafeFakeRedis:
    """Thread-safe in-memory Redis simulator implementing atomic Lua eval with lock."""
    def __init__(self):
        self.data: dict[str, int] = {}
        self.lock = threading.Lock()

    def ping(self):
        return True

    def get(self, key: str):
        with self.lock:
            val = self.data.get(key)
            return str(val) if val is not None else None

    def eval(self, script: str, numkeys: int, key: str, limit: int | str):
        limit = int(limit)
        with self.lock:
            curr = int(self.data.get(key, 0))
            if curr < limit:
                curr += 1
                self.data[key] = curr
                return curr
            return -1

    def keys(self, pattern: str = "*"):
        with self.lock:
            return list(self.data.keys())

    def delete(self, *keys):
        with self.lock:
            for k in keys:
                self.data.pop(k, None)


class TestConcurrencyQuota(unittest.TestCase):

    def setUp(self):
        self.fake_redis = ThreadSafeFakeRedis()
        quota.set_redis_client(self.fake_redis)

    def tearDown(self):
        quota.set_redis_client(None)

    def test_concurrent_cap_boundary_race_condition(self):
        """10 threads compete with 5 Claude slots left: exactly 5 Claude, exactly 5 fallback."""
        user_id = "concurrent_user_boundary"
        tier = "standard"  # cap 30
        today = quota.get_today_str()
        claude_key = f"akira:user:{user_id}:quota_claude:{today}"

        # Pre-seed 25 turns used out of 30 (5 slots left)
        self.fake_redis.data[claude_key] = 25

        results = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()  # synchronize all 10 threads to fire at the exact same instant
            verdict = quota.check_and_increment_turn(user_id, tier)
            return verdict

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        # All 10 requests must be allowed
        self.assertEqual(len(results), 10)
        self.assertTrue(all(r.allowed for r in results), "All 10 turns must be allowed")

        claude_allocations = [r for r in results if not r.use_fallback]
        fallback_allocations = [r for r in results if r.use_fallback]

        # Exactly 5 got Claude, exactly 5 got Groq fallback
        self.assertEqual(len(claude_allocations), 5, "Exactly 5 threads must be granted Claude")
        self.assertEqual(len(fallback_allocations), 5, "Exactly 5 threads must be shifted to fallback")

        # Check final Redis state
        fallback_key = f"akira:user:{user_id}:quota_fallback_groq:{today}"
        self.assertEqual(self.fake_redis.data[claude_key], 30)
        self.assertEqual(self.fake_redis.data[fallback_key], 5)

    def test_concurrent_fallback_exhaustion_boundary(self):
        """10 threads compete with 5 fallback slots left: exactly 5 succeed, exactly 5 get 429."""
        user_id = "concurrent_fallback_boundary"
        tier = "pro"  # cap 53
        today = quota.get_today_str()
        claude_key = f"akira:user:{user_id}:quota_claude:{today}"
        fallback_key = f"akira:user:{user_id}:quota_fallback_groq:{today}"

        # Pre-seed Claude at cap (53) and fallback at 245 (5 slots left out of 250)
        self.fake_redis.data[claude_key] = 53
        self.fake_redis.data[fallback_key] = 245

        results = []
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            verdict = quota.check_and_increment_turn(user_id, tier)
            return verdict

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        allowed_results = [r for r in results if r.allowed]
        rejected_results = [r for r in results if not r.allowed]

        # Exactly 5 succeeded on fallback, exactly 5 were rejected with 429
        self.assertEqual(len(allowed_results), 5, "Exactly 5 threads must get remaining fallback slots")
        self.assertEqual(len(rejected_results), 5, "Exactly 5 threads must be rejected")
        self.assertEqual(self.fake_redis.data[fallback_key], 250, "Ceiling of 250 must never be exceeded")


if __name__ == "__main__":
    unittest.main()
