"""tests/test_gateway_quota.py — Standard & Pro Tier Daily Quota & Groq Fallback Tests.

Verifies:
1. Standard daily cap of 30 turns on Claude.
2. Pro daily cap of 53 turns on Claude.
3. Automatic shift to Groq free fallback upon reaching Claude cap.
4. Groq fallback quota tracking (ceiling: 250 turns).
5. HTTP 429 when both Claude and Groq fallback caps are exhausted.
6. Reset time message ("00:00 UTC").
7. GET /v1/quota returns accurate remaining count and fallback status.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

# Ensure JWT secret is set before importing gateway
os.environ["AKIRA_JWT_SECRET"] = "super-secret-test-jwt-key-32-chars-minimum!!"
os.environ["AKIRA_ENV"] = "test"

from gateway_server import auth, config, quota
from gateway_server.main import app


class FakeRedis:
    """Thread-safe in-memory Redis simulator implementing ping, get, and atomic eval."""
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

    def keys(self, pattern: str = "*"):
        return list(self.data.keys())

    def delete(self, *keys):
        for k in keys:
            self.data.pop(k, None)


class TestGatewayQuota(unittest.TestCase):

    def setUp(self):
        self.fake_redis = FakeRedis()
        quota.set_redis_client(self.fake_redis)
        self.client = TestClient(app)

    def tearDown(self):
        quota.set_redis_client(None)

    def test_standard_cap_and_fallback(self):
        """Standard tier: 30 Claude turns -> 31st shifts to Groq fallback."""
        user_id = "user_std_test"
        tier = "standard"

        # First 30 turns should be allowed on Claude (use_fallback=False)
        for i in range(1, 31):
            verdict = quota.check_and_increment_turn(user_id, tier)
            self.assertTrue(verdict.allowed, f"Turn {i} should be allowed")
            self.assertFalse(verdict.use_fallback, f"Turn {i} should use Claude")
            self.assertEqual(verdict.used_today, i)
            self.assertEqual(verdict.cap, 30)
            self.assertEqual(verdict.remaining, 30 - i)

        # 31st turn should auto-shift to Groq fallback
        verdict_31 = quota.check_and_increment_turn(user_id, tier)
        self.assertTrue(verdict_31.allowed, "31st turn should be allowed on Groq fallback")
        self.assertTrue(verdict_31.use_fallback, "31st turn must use fallback")
        self.assertEqual(verdict_31.used_today, 1, "Fallback used count starts at 1")
        self.assertEqual(verdict_31.cap, 250, "Fallback cap is 250")
        self.assertEqual(verdict_31.remaining, 249)

    def test_pro_cap_and_fallback(self):
        """Pro tier: 53 Claude turns -> 54th shifts to Groq fallback."""
        user_id = "user_pro_test"
        tier = "pro"

        # First 53 turns should be allowed on Claude
        for i in range(1, 54):
            verdict = quota.check_and_increment_turn(user_id, tier)
            self.assertTrue(verdict.allowed, f"Turn {i} should be allowed")
            self.assertFalse(verdict.use_fallback, f"Turn {i} should use Claude")
            self.assertEqual(verdict.used_today, i)
            self.assertEqual(verdict.cap, 53)
            self.assertEqual(verdict.remaining, 53 - i)

        # 54th turn should auto-shift to Groq fallback
        verdict_54 = quota.check_and_increment_turn(user_id, tier)
        self.assertTrue(verdict_54.allowed, "54th turn should be allowed on Groq fallback")
        self.assertTrue(verdict_54.use_fallback, "54th turn must use fallback")
        self.assertEqual(verdict_54.used_today, 1)
        self.assertEqual(verdict_54.cap, 250)

    def test_fallback_exhaustion_returns_429(self):
        """When both Claude and Groq fallback are exhausted, allowed=False with 00:00 UTC message."""
        user_id = "user_exhausted_test"
        tier = "standard"

        today = quota.get_today_str()
        claude_key = f"akira:user:{user_id}:quota_claude:{today}"
        fallback_key = f"akira:user:{user_id}:quota_fallback_groq:{today}"

        # Exhaust both keys in fake Redis
        self.fake_redis.data[claude_key] = 30
        self.fake_redis.data[fallback_key] = 250

        verdict = quota.check_and_increment_turn(user_id, tier)
        self.assertFalse(verdict.allowed, "Must not be allowed after exhausting fallback")
        self.assertTrue(verdict.use_fallback)
        self.assertEqual(verdict.remaining, 0)
        self.assertIn("00:00 UTC", verdict.reason)

    @patch("gateway_server.upstream.call_upstream_groq")
    @patch("gateway_server.upstream.call_upstream_claude")
    def test_route_endpoint_http_flow(self, mock_claude, mock_groq):
        """Test /v1/route endpoint end-to-end with TestClient."""
        mock_claude.return_value = (200, {"choices": [{"message": {"content": "Claude response"}}]})
        mock_groq.return_value = (200, {"choices": [{"message": {"content": "Groq response"}}]})

        user_id = "http_user_test"
        token = auth.issue_jwt(user_id, "standard")
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"messages": [{"role": "user", "content": "Hello Akira"}]}

        # Normal Claude call
        resp = self.client.post("/v1/route", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-akira-fallback"), "False")
        mock_claude.assert_called_once()

        # Simulate reaching cap
        today = quota.get_today_str()
        claude_key = f"akira:user:{user_id}:quota_claude:{today}"
        self.fake_redis.data[claude_key] = 30

        # Next call should hit Groq fallback
        resp2 = self.client.post("/v1/route", json=payload, headers=headers)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.headers.get("x-akira-fallback"), "True")
        mock_groq.assert_called_once()

        # Simulate exhausting fallback
        fallback_key = f"akira:user:{user_id}:quota_fallback_groq:{today}"
        self.fake_redis.data[fallback_key] = 250

        resp3 = self.client.post("/v1/route", json=payload, headers=headers)
        self.assertEqual(resp3.status_code, 429)
        self.assertIn("00:00 UTC", resp3.json()["detail"])

    def test_quota_summary_endpoint(self):
        """GET /v1/quota returns user quota state."""
        user_id = "quota_summary_user"
        token = auth.issue_jwt(user_id, "pro")
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.get("/v1/quota", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["tier"], "pro")
        self.assertEqual(data["primary_cap"], 53)
        self.assertEqual(data["primary_remaining"], 53)
        self.assertFalse(data["fallback_active"])
        self.assertEqual(data["reset_time"], "00:00 UTC")


if __name__ == "__main__":
    unittest.main()
