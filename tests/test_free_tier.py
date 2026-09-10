"""tests/test_free_tier.py — Free Tier Complete Server-Independence Tests.

Verifies:
1. Free tier is intentionally excluded from the gateway — no caps, no server round-trip, no auth required.
2. Free tier head model routes directly and locally via Groq without touching gateway_client.
3. Gateway server endpoint POST /v1/route explicitly rejects any Free-tier token with HTTP 403.
4. Standard and Pro tiers route through the gateway server by default.
5. AKIRA_DEV_DIRECT_KEYS=true emits loud warning and falls back to raw keys locally.
"""

from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from gateway_server.main import app
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    TestClient = None
    app = None

os.environ["AKIRA_JWT_SECRET"] = "super-secret-test-jwt-key-32-chars-minimum!!"
os.environ["AKIRA_ENV"] = "test"

try:
    from gateway_server import auth
    HAS_AUTH = True
except ImportError:
    HAS_AUTH = False
    auth = None

import claude_handler
import gateway_client
import tiers


class TestFreeTier(unittest.TestCase):

    def setUp(self):
        if HAS_FASTAPI and app is not None and HAS_AUTH:
            self.client = TestClient(app)
        else:
            self.client = None

    def test_free_tier_head_dispatch_is_local_groq(self):
        """Free tier resolves directly to local Groq head, never gateway."""
        os.environ["AKIRA_TIER"] = "free"
        os.environ["GROQ_API_KEY"] = "test-mock-groq-key"

        provider, payload = claude_handler._head_dispatch()
        self.assertEqual(provider, "groq", "Free tier head dispatch must resolve to local 'groq'")
        self.assertIsNone(payload)

    @patch("gemini_head._try_fast_pattern_route")
    @patch("gemini_head._route_via_groq")
    @patch("gateway_client.call_route")
    def test_free_tier_execution_never_calls_gateway(self, mock_gw, mock_groq, mock_fast):
        """Executing a routing call on Free tier must NEVER call the gateway server."""
        os.environ["AKIRA_TIER"] = "free"
        os.environ["GROQ_API_KEY"] = "test-mock-groq-key"

        mock_fast.return_value = None
        fake_reply = claude_handler._RefusalReply(
            [claude_handler._TextBlockShim('{"mode": "conversation", "response": "Hello"}')]
        )
        mock_groq.return_value = fake_reply

        messages = [{"role": "user", "content": "hello"}]
        reply = claude_handler._routing_call(messages, "2026-09-06")

        self.assertIsNotNone(reply)
        mock_groq.assert_called_once()
        # Non-negotiable check: gateway_client must NOT have been called
        mock_gw.assert_not_called()

    def test_free_fallback_servant_gated_is_unblocked(self):
        """Free/fallback tier now has access to full gated capability seat (zero cost-gate refusal)."""
        seat = tiers.servant_gated("free")
        self.assertTrue(bool(seat), "servant_gated('free') must return truthy GatedSeat, not Unavailable")
        self.assertEqual(seat.plan, "free")
        # fine-tuned LoRA task adapters remain Pro-exclusive
        self.assertFalse(seat.adapters, "Adapters must remain Pro-exclusive")

    def test_free_fallback_guard_mode_enforces_serial_gated(self):
        """Free/fallback tier must enforce serial_gated=True for identical safety to Standard."""
        mode = tiers.guard_mode("free")
        self.assertTrue(mode.serial_gated, "serial_gated must be True on free/fallback tier")
        self.assertTrue(mode.parallel, "parallel speculative guard must be True on free/fallback tier")
        self.assertFalse(mode.reliability_gate, "reliability_gate bypass is Pro-exclusive")

    @unittest.skipUnless(HAS_FASTAPI and HAS_AUTH, "fastapi and jwt required for server gateway test")
    def test_server_v1_route_rejects_free_tier_with_403(self):
        """Server gateway must return HTTP 403 Forbidden if a Free-tier token hits /v1/route."""
        free_token = auth.issue_jwt("free_user_123", "free")
        headers = {"Authorization": f"Bearer {free_token}"}
        payload = {"messages": [{"role": "user", "content": "hi"}]}

        resp = self.client.post("/v1/route", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertIn("Free tier does not use the server gateway", data["detail"])
        self.assertIn("100% locally and uncapped", data["detail"])

    @patch("gateway_client.call_route")
    def test_standard_tier_calls_gateway(self, mock_gw):
        """Standard tier must route through gateway_client when direct keys are off."""
        os.environ["AKIRA_TIER"] = "standard"
        os.environ["AKIRA_DEV_DIRECT_KEYS"] = "false"

        mock_gw.return_value = claude_handler._RefusalReply(
            [claude_handler._TextBlockShim('{"mode": "conversation", "response": "Standard hi"}')]
        )

        messages = [{"role": "user", "content": "test"}]
        reply = claude_handler._routing_call(messages, "2026-09-06")
        self.assertIsNotNone(reply)
        mock_gw.assert_called_once()

    def test_dev_direct_keys_warning(self):
        """AKIRA_DEV_DIRECT_KEYS=true must print a loud startup warning."""
        os.environ["AKIRA_DEV_DIRECT_KEYS"] = "true"
        # Reset the printed flag to re-trigger warning
        gateway_client._dev_warning_shown = False

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            is_dev = gateway_client.is_dev_direct_keys()
            self.assertTrue(is_dev)
            output = fake_out.getvalue()
            self.assertIn("[DEV MODE] Using local API keys directly", output)
            self.assertIn("must be disabled before any real distribution", output)

        os.environ["AKIRA_DEV_DIRECT_KEYS"] = "false"


if __name__ == "__main__":
    unittest.main()
