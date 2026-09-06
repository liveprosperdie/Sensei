"""tests/test_redis_outage.py — Redis Outage Resilience and Graceful Degradation Tests.

Verifies:
1. When Redis is down/unreachable, do NOT return 503; gracefully degrade to Groq free fallback.
2. The outage is logged at ERROR level.
3. Fallback turns are tracked in-memory during outage.
4. When Redis reconnects, the system automatically logs at INFO and resumes normal Claude routing.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ["AKIRA_JWT_SECRET"] = "super-secret-test-jwt-key-32-chars-minimum!!"
os.environ["AKIRA_ENV"] = "test"

from gateway_server import quota


class FailingRedis:
    def ping(self):
        raise ConnectionError("Target machine actively refused connection (simulated outage).")


class WorkingRedis:
    def __init__(self):
        self.data: dict[str, int] = {}

    def ping(self):
        return True

    def get(self, key: str):
        val = self.data.get(key)
        return str(val) if val is not None else None

    def eval(self, script: str, numkeys: int, key: str, limit: int | str):
        limit = int(limit)
        curr = int(self.data.get(key, 0))
        if curr < limit:
            curr += 1
            self.data[key] = curr
            return curr
        return -1


class TestRedisOutage(unittest.TestCase):

    def setUp(self):
        quota.reset_counters_for_testing()

    def tearDown(self):
        quota.set_redis_client(None)

    def test_outage_graceful_degradation_and_logging(self):
        """During Redis outage, degrade to Groq fallback and log at ERROR."""
        failing_redis = FailingRedis()
        quota.set_redis_client(failing_redis)

        user_id = "outage_user_1"
        tier = "pro"

        # Check that error is logged and request succeeds with use_fallback=True
        with self.assertLogs("akira.quota", level="ERROR") as cm:
            verdict = quota.check_and_increment_turn(user_id, tier)

        self.assertTrue(verdict.allowed, "Must remain allowed during Redis outage")
        self.assertTrue(verdict.use_fallback, "Must route to Groq fallback")
        self.assertTrue(verdict.redis_outage, "Must flag redis_outage=True")
        self.assertIn("Redis unreachable", cm.output[0])

        # Second call should still degrade without crashing
        verdict2 = quota.check_and_increment_turn(user_id, tier)
        self.assertTrue(verdict2.allowed)
        self.assertTrue(verdict2.use_fallback)
        self.assertEqual(verdict2.used_today, 2)

    def test_reconnection_resumes_claude(self):
        """When Redis reconnects, log at INFO and resume Claude quota routing."""
        # 1. Start in outage
        failing_redis = FailingRedis()
        quota.set_redis_client(failing_redis)
        user_id = "reconnect_user"
        tier = "standard"

        v_outage = quota.check_and_increment_turn(user_id, tier)
        self.assertTrue(v_outage.use_fallback)

        # 2. Redis is restored
        working_redis = WorkingRedis()
        quota.set_redis_client(working_redis)

        # 3. Next call should detect restoration and route to Claude
        with self.assertLogs("akira.quota", level="INFO") as cm:
            v_restored = quota.check_and_increment_turn(user_id, tier)

        self.assertTrue(v_restored.allowed)
        self.assertFalse(v_restored.use_fallback, "Must resume normal Claude routing")
        self.assertFalse(v_restored.redis_outage)
        self.assertEqual(v_restored.used_today, 1)
        self.assertTrue(any("connectivity restored" in line for line in cm.output))


if __name__ == "__main__":
    unittest.main()
