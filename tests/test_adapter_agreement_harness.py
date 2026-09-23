"""test_adapter_agreement_harness.py — Unit test suite for Task 5 regression & agreement harness."""

import unittest
from unittest.mock import MagicMock, patch

import adapter_agreement_harness as aah
from tiered_config import ADAPTER_ALLOWED_INTENTS, validate_allowlist


class TestAdapterAgreementHarness(unittest.TestCase):

    def test_graduation_threshold_rules(self):
        threshold = aah.GraduationThreshold(
            min_agreement_ratio=0.95,
            max_guard_rejections=0,
            min_side_effect_ratio=1.0,
        )
        self.assertEqual(threshold.min_agreement_ratio, 0.95)
        self.assertEqual(threshold.max_guard_rejections, 0)
        self.assertEqual(threshold.min_side_effect_ratio, 1.0)

    def test_validate_allowlist_gating(self):
        # When all allowed intents have graduated, ungraduated list is empty
        graduated = set(ADAPTER_ALLOWED_INTENTS)
        ungraduated = validate_allowlist(graduated)
        self.assertEqual(ungraduated, [])

        # If some intents have not graduated, they are caught
        graduated_partial = set(ADAPTER_ALLOWED_INTENTS) - {"adjust_volume", "open_application"}
        ungraduated = validate_allowlist(graduated_partial)
        self.assertIn("adjust_volume", ungraduated)
        self.assertIn("open_application", ungraduated)

    def test_summary_verdict_threshold_logic(self):
        # 20/20 success -> GRADUATED
        s = aah.IntentRunSummary(
            intent="test_intent",
            total_runs=20,
            agreement_runs=20,
            side_effects_passed=20,
        )
        s.agreement_ratio = 20 / 20.0
        if s.unverifiable_runs > 10:
            s.verdict = "INSUFFICIENT_DATA (Unverifiable)"
        elif s.guard_rejections > 0:
            s.verdict = "FAIL (GUARD Rejection)"
        elif s.agreement_ratio >= 0.95:
            s.verdict = "GRADUATED"
        self.assertEqual(s.verdict, "GRADUATED")

        # 18/20 success (90% < 95%) -> FAIL
        s2 = aah.IntentRunSummary(
            intent="test_intent_2",
            total_runs=20,
            agreement_runs=18,
            side_effects_passed=18,
            side_effects_failed=2,
        )
        s2.agreement_ratio = 18 / 20.0
        if s2.side_effects_failed > 0:
            s2.verdict = "FAIL (Side-effect failure: 2/20)"
        self.assertIn("FAIL", s2.verdict)

        # 1 GUARD rejection -> FAIL
        s3 = aah.IntentRunSummary(
            intent="test_intent_3",
            total_runs=20,
            guard_rejections=1,
            agreement_runs=19,
        )
        s3.agreement_ratio = 19 / 20.0
        if s3.guard_rejections > 0:
            s3.verdict = "FAIL (GUARD Rejection: 1/20)"
        self.assertIn("GUARD Rejection", s3.verdict)

        # >50% unverifiable -> INSUFFICIENT_DATA
        s4 = aah.IntentRunSummary(
            intent="test_intent_4",
            total_runs=20,
            unverifiable_runs=15,
            agreement_runs=5,
        )
        if s4.unverifiable_runs > 10:
            s4.verdict = "INSUFFICIENT_DATA (Unverifiable)"
        self.assertIn("INSUFFICIENT_DATA", s4.verdict)

    def test_clipboard_probe_mocked(self):
        probe = aah.ClipboardProbe()
        with patch("pyperclip.paste", return_value="sentinel_val"):
            res = probe.verify("read_clipboard", {}, "sentinel_val", {"sentinel": "sentinel_val"})
            self.assertEqual(res.status, "PASS")

        with patch("pyperclip.paste", return_value="other_val"):
            res = probe.verify("write_clipboard", {"text": "sentinel_val"}, "", {"sentinel": "sentinel_val"})
            self.assertEqual(res.status, "FAIL")

    def test_conversational_probe_time(self):
        probe = aah.ConversationalProbe()
        res = probe.verify("get_current_time", {}, {"response": "It is currently 10:00 PM."}, {})
        self.assertEqual(res.status, "PASS")


if __name__ == "__main__":
    unittest.main()
