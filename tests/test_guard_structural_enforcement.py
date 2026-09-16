"""test_guard_structural_enforcement.py — Verification of structural GUARD enforcement.

Tests that:
1. Direct execution calls without a GuardToken are structurally blocked.
2. Forged, expired, or tampered tokens are rejected.
3. Action/parameter cross-token smuggling is rejected.
4. Blocked actions produce no execution token.
5. Lawful execution via action_router.run_guarded successfully obtains and verifies tokens.
6. AKIRA_SKIP_GUARD environment variable bypass has been completely eliminated.
"""

import os
import time
import unittest
from unittest.mock import patch, MagicMock

import guard
import guard_rules
from guard_rules import (
    ALLOW,
    BLOCK,
    FLAG,
    GuardBypassError,
    GuardToken,
    Verdict,
    _hash_param,
)
import executor
import action_router


class TestGuardStructuralEnforcement(unittest.TestCase):

    def test_direct_execution_without_token_raises(self):
        """Calling executor.execute without a GuardToken must raise GuardBypassError."""
        with self.assertRaises(GuardBypassError) as ctx:
            executor.execute("adjust_volume", "50")
        self.assertIn("missing required GuardToken", str(ctx.exception))

    def test_direct_execution_with_none_token_raises(self):
        """Passing guard_token=None must raise GuardBypassError."""
        with self.assertRaises(GuardBypassError) as ctx:
            executor.execute("adjust_volume", "50", guard_token=None)
        self.assertIn("missing required GuardToken", str(ctx.exception))

    def test_forged_token_rejected(self):
        """Passing an un-signed or forged GuardToken must raise GuardBypassError."""
        fake_token = GuardToken(
            action="adjust_volume",
            parameter_hash=_hash_param("50"),
            decision=ALLOW,
            created_at=time.time(),
            signature="bad_signature_00000000000000000000000000000000000000000000000000",
        )
        with self.assertRaises(GuardBypassError) as ctx:
            executor.execute("adjust_volume", "50", guard_token=fake_token)
        self.assertIn("invalid, forged, or mismatched GuardToken", str(ctx.exception))

    def test_mismatched_action_token_rejected(self):
        """Token generated for action A cannot be used to execute action B."""
        verdict = guard_rules.validate("adjust_volume", "50")
        self.assertIsNotNone(verdict.token)

        # Attempt to use adjust_volume's token to execute delete_files
        with self.assertRaises(GuardBypassError) as ctx:
            executor.execute("delete_files", "dummy.txt", guard_token=verdict.token)
        self.assertIn("invalid, forged, or mismatched GuardToken", str(ctx.exception))

    def test_mismatched_parameter_token_rejected(self):
        """Token generated for parameter X cannot be used to execute with parameter Y."""
        verdict = guard_rules.validate("adjust_volume", "50")
        self.assertIsNotNone(verdict.token)

        # Attempt to use 50 volume token with 100
        with self.assertRaises(GuardBypassError) as ctx:
            executor.execute("adjust_volume", "100", guard_token=verdict.token)
        self.assertIn("invalid, forged, or mismatched GuardToken", str(ctx.exception))

    def test_expired_token_rejected(self):
        """Token older than expiry window (120s) must fail validation."""
        old_time = time.time() - 300.0
        p_hash = _hash_param("50")
        sig = guard_rules._compute_token_signature("adjust_volume", p_hash, ALLOW, old_time)
        expired_token = GuardToken(
            action="adjust_volume",
            parameter_hash=p_hash,
            decision=ALLOW,
            created_at=old_time,
            signature=sig,
        )
        with self.assertRaises(GuardBypassError) as ctx:
            executor.execute("adjust_volume", "50", guard_token=expired_token)
        self.assertIn("invalid, forged, or mismatched GuardToken", str(ctx.exception))

    def test_blocked_action_produces_no_token(self):
        """guard_rules.validate produces no token for blocked actions."""
        # Self-modification target
        akira_py = os.path.abspath("akira.py")
        verdict = guard_rules.validate("delete_files", akira_py)
        self.assertEqual(verdict.decision, BLOCK)
        self.assertIsNone(verdict.token)

        # Destructive OS command
        verdict_cmd = guard_rules.validate("create_file", "format c: /fs:ntfs")
        self.assertEqual(verdict_cmd.decision, BLOCK)
        self.assertIsNone(verdict_cmd.token)

    def test_lawful_action_router_dispatch_provides_token(self):
        """action_router.run_guarded mints token and successfully passes it to execution."""
        mock_handler = MagicMock(return_value="Volume adjusted.")
        with patch.dict(executor._ACTION_MAP, {"adjust_volume": mock_handler}):
            step = {"action": "adjust_volume", "parameter": "50"}
            outcome = action_router.run_guarded(
                step,
                lambda tok=None: executor.execute("adjust_volume", "50", guard_token=tok),
                confirmed=True,
            )
            self.assertTrue(outcome.executed)
            self.assertEqual(outcome.result, "Volume adjusted.")
            mock_handler.assert_called_once_with("50")

    def test_tier_a_lawful_dispatch_without_confirmation(self):
        """Tier A actions execute lawfully through run_guarded without confirmation."""
        mock_app_handler = MagicMock(return_value="Notepad opened.")
        with patch("action_router._dangerous_classifier", return_value=lambda s: False):
            with patch.dict(executor._ACTION_MAP, {"open_application": mock_app_handler}):
                step = {"action": "open_application", "parameter": "notepad"}
                outcome = action_router.run_guarded(
                    step,
                    lambda tok=None: executor.execute("open_application", "notepad", guard_token=tok),
                )
                self.assertTrue(outcome.executed)
                self.assertEqual(outcome.result, "Notepad opened.")
                mock_app_handler.assert_called_once_with("notepad")

    def test_akira_skip_guard_flag_eliminated(self):
        """Setting AKIRA_SKIP_GUARD=true does NOT bypass guard review."""
        os.environ["AKIRA_SKIP_GUARD"] = "true"
        try:
            # Action that is NOT in FAST_PATH_ALLOWED_ACTIONS (e.g. shutdown_pc)
            # Must proceed to review / fail-closed, not be approved by fast-path
            with patch("guard.servant_clients.call_json", side_effect=Exception("Mock network unavailable")):
                verdict = guard.review("shutdown_pc", None)
                # Should NOT be ALLOW from fast path:
                self.assertNotEqual(verdict.decision, ALLOW)
        finally:
            os.environ.pop("AKIRA_SKIP_GUARD", None)


if __name__ == "__main__":
    unittest.main()
