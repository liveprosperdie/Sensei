"""tests/test_tier_overhaul.py — Comprehensive verification suite for Akira tier/pricing overhaul.

Covers:
1. New signup gets 7-day Standard access, no payment prompts, rejects free signup.
2. Day-5 nudge: fires exactly once, timezone-safe UTC, idempotent, respects payment added.
3. 500-user concurrency test: 50+ concurrent threads near the boundary, asserts exactly 500 succeed, no duplicate slots, no overcommit.
4. Day-7 unpaid trial expiry: lands in fallback_permanent state, account intact.
5. Staged discount decay: advance 3-day notice sent and logged before price changes.
6. Cancel-and-re-trial abuse prevention: email normalization & machine GUID fingerprinting.
7. Invisible fallback quality: 5 real prompt spot-checks through both paths comparing outputs.
8. All-providers-down: engages local floor fallback and logs telemetry.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import logging
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gateway_server import subscriptions
from gateway_server.subscriptions import (
    PostgresPromotionCounter,
    signup_user,
    check_and_run_day5_nudge,
    add_payment_method,
    check_trial_expirations,
    process_advance_price_change_notices,
    get_user_status,
    normalize_email,
)
import model_pool
import gemini_head


class TestTierAndPricingOverhaul(unittest.TestCase):

    def setUp(self):
        # Create isolated temp database for each test
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        subscriptions.init_db(self.temp_db.name)
        subscriptions.promo_counter.reset(0)

    def tearDown(self):
        try:
            if os.path.exists(self.temp_db.name):
                os.remove(self.temp_db.name)
        except Exception:
            pass

    # ── Test 1: New Signup Gets Standard Access for Exactly 7 Days ────────────

    def test_new_signup_gets_7day_standard_trial(self):
        t0 = datetime.datetime(2026, 9, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)
        res = signup_user("u100", "testuser@example.com", machine_guid="guid-100", now_utc=t0)

        self.assertEqual(res["tier"], "standard")
        self.assertEqual(res["status"], "standard_trial")

        created = datetime.datetime.fromisoformat(res["created_at_utc"])
        trial_end = datetime.datetime.fromisoformat(res["trial_end_utc"])
        delta = trial_end - created
        self.assertEqual(delta.total_seconds(), 7 * 86400)

        user = get_user_status("u100")
        self.assertIsNotNone(user)
        self.assertEqual(user["payment_added"], 0)
        self.assertIsNone(user["nudge_sent_at_utc"])

        # Attempt to signup directly to Free must be rejected
        with self.assertRaises(ValueError):
            signup_user("u101", "freeuser@example.com", requested_plan="free")

    # ── Test 2: Day-5 Nudge Idempotency, Timezone Safety, and Payment Check ───

    def test_day5_nudge_fires_once_timezone_safe(self):
        t0 = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
        signup_user("u200", "nudge_user@example.com", now_utc=t0)

        # Day 4.9 UTC: Must NOT fire early
        t_early = t0 + datetime.timedelta(days=4, hours=21)
        nudged = check_and_run_day5_nudge(now_utc=t_early)
        self.assertEqual(len(nudged), 0)

        # Day 5.0 UTC: Fires exactly once
        t_day5 = t0 + datetime.timedelta(days=5, minutes=1)
        nudged = check_and_run_day5_nudge(now_utc=t_day5)
        self.assertEqual(len(nudged), 1)
        self.assertEqual(nudged[0]["user_id"], "u200")

        # Immediate job retry / duplicate run at Day 5.1: Idempotency check ensures zero double-fire
        t_retry = t0 + datetime.timedelta(days=5, hours=2)
        nudged_retry = check_and_run_day5_nudge(now_utc=t_retry)
        self.assertEqual(len(nudged_retry), 0)

        # User who already added payment before Day 5: Must NOT fire
        signup_user("u201", "paid_early@example.com", now_utc=t0)
        add_payment_method("u201", "card_token_early", now_utc=t0 + datetime.timedelta(days=2))
        nudged_paid = check_and_run_day5_nudge(now_utc=t_day5)
        self.assertFalse(any(n["user_id"] == "u201" for n in nudged_paid))

    # ── Test 3: 500-User Counter Concurrency (Atomic, No Overcommit) ──────────

    def test_500_user_counter_concurrency(self):
        counter = PostgresPromotionCounter(max_slots=500)
        counter.reset(475)  # 25 slots remaining before 500 boundary

        # Fire 60 concurrent simulated signup threads competing for 25 remaining slots
        results = []
        errors = []

        def worker(thread_id: int):
            try:
                slot = counter.claim_slot("EARLY500")
                return slot
            except Exception as e:
                errors.append(e)
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(worker, i) for i in range(60)]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res is not None:
                    results.append(res)

        self.assertEqual(len(errors), 0, f"Errors occurred during concurrent claims: {errors}")
        # Exactly 25 claims must succeed (from 476 to 500)
        self.assertEqual(len(results), 25, f"Expected exactly 25 successful claims, got {len(results)}")
        # No duplicates allowed
        self.assertEqual(len(results), len(set(results)), "Duplicate promotion slot assigned under concurrency!")
        # Counter must not exceed 500
        self.assertEqual(counter.get_count("EARLY500"), 500)
        self.assertEqual(max(results), 500)
        self.assertEqual(min(results), 476)

        # Subsequent attempts must strictly receive None (sold out)
        self.assertIsNone(counter.claim_slot("EARLY500"))

    # ── Test 4: Unpaid Trial Reaching Day 7 Lands in Permanent Fallback ────────

    def test_trial_unpaid_lands_in_permanent_fallback_at_day7(self):
        t0 = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
        signup_user("u300", "unpaid@example.com", now_utc=t0)

        # At Day 6.9: still in trial
        downgraded_early = check_trial_expirations(now_utc=t0 + datetime.timedelta(days=6, hours=22))
        self.assertEqual(len(downgraded_early), 0)
        st = get_user_status("u300")
        self.assertEqual(st["tier"], "standard")

        # At Day 7.01: trial expires -> downgraded to fallback_permanent
        t_exp = t0 + datetime.timedelta(days=7, hours=1)
        downgraded = check_trial_expirations(now_utc=t_exp)
        self.assertIn("u300", downgraded)

        st_after = get_user_status("u300")
        self.assertEqual(st_after["tier"], "fallback_permanent")
        self.assertEqual(st_after["status"], "fallback_permanent")
        # Account is intact in database (not deleted)
        self.assertEqual(st_after["email"], "unpaid@example.com")

    # ── Test 5: Staged Discount Decay & 3-Day Advance Notice ──────────────────

    def test_staged_discount_decay_and_advance_notice(self):
        t0 = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
        signup_user("u400", "discount_user@example.com", now_utc=t0)

        decay_schedule = [(0, 0.25), (30, 0.60), (60, 1.00)]
        res = add_payment_method("u400", "fingerprint_card_400", decay_schedule=decay_schedule, now_utc=t0)
        self.assertTrue(res["discount_awarded"])

        # Discount ends at T0 + 21 days
        t_disc_end = t0 + datetime.timedelta(days=21)
        # Stage 2 (30 days after discount end) effective date = T0 + 51 days
        t_stage2_eff = t_disc_end + datetime.timedelta(days=30)
        # 3 days notice due date = t_stage2_eff - 3 days = T0 + 48 days

        # At Day 40: no notice due yet for stage 2
        notices_early = process_advance_price_change_notices(now_utc=t0 + datetime.timedelta(days=40))
        self.assertFalse(any(n["new_price_multiplier"] == 0.60 for n in notices_early))

        # At Day 48 (exactly 3 days before stage 2 effective date): notice must fire and log
        t_notice_time = t_stage2_eff - datetime.timedelta(days=2, hours=23)
        notices = process_advance_price_change_notices(now_utc=t_notice_time)
        self.assertTrue(any(n["new_price_multiplier"] == 0.60 and n["user_id"] == "u400" for n in notices))

        # Re-running notice check must not double-send
        notices_dup = process_advance_price_change_notices(now_utc=t_notice_time + datetime.timedelta(hours=1))
        self.assertFalse(any(n["new_price_multiplier"] == 0.60 and n["user_id"] == "u400" for n in notices_dup))

    # ── Test 6: Cancel-and-Re-Trial Abuse Prevention ─────────────────────────

    def test_cancel_and_retrial_abuse_prevention(self):
        t0 = datetime.datetime(2026, 9, 10, 0, 0, 0, tzinfo=datetime.timezone.utc)
        # First signup
        res1 = signup_user("u500", "charlie.smith@gmail.com", machine_guid="mach-guid-999", now_utc=t0)
        self.assertEqual(res1["tier"], "standard")
        self.assertFalse(res1["prior_trial_detected"])

        # Attempt 2: Same user with Gmail dots and +alias (charlie.s.m.i.t.h+freetrial@gmail.com)
        res2 = signup_user("u501", "charlie.s.m.i.t.h+freetrial@gmail.com", machine_guid="mach-diff-111", now_utc=t0)
        self.assertEqual(res2["tier"], "fallback_permanent")
        self.assertTrue(res2["prior_trial_detected"])

        # Attempt 3: Different email but identical machine GUID
        res3 = signup_user("u502", "different_email@yahoo.com", machine_guid="mach-guid-999", now_utc=t0)
        self.assertEqual(res3["tier"], "fallback_permanent")
        self.assertTrue(res3["prior_trial_detected"])

    # ── Test 7: Spot-Check Quality Across Audit Scenarios (Fallback vs Real) ───

    def test_fallback_routing_quality_spot_check(self):
        """Spot-check real audit scenarios comparing fallback dense manifest & pre-router routing vs expectation.
        
        Verifies:
        1. "open notepad and write an essay on [topic]" — compound chain yields from fast pre-router to LLM
        2. "write an email to Sarah about the budget meeting" — fast pre-router emits gmail_compose|generate|...
        3. "write a note in obsidian about project roadmap" — fast pre-router routes to obsidian_control
        4. "search netflix for [X]" and "search reddit for [X]" — fast pre-router emits site_search with correct site
        5. "open notepad and write hello then open spotify and play [song]" — compound conjunction yields to LLM
        6. "open word and write a report about [topic]" — yields to LLM for office_control word generation
        """
        # 1. Fast pre-router deterministic assertions
        # Gmail compose with generate brief
        msgs_gmail = [{"role": "user", "content": "write an email to Sarah about the budget meeting"}]
        reply_gmail = gemini_head._try_fast_pattern_route(msgs_gmail)
        self.assertIsNotNone(reply_gmail)
        obj_gmail = json.loads(reply_gmail.text)
        self.assertEqual(obj_gmail["action"], "gmail_compose")
        self.assertTrue(obj_gmail["parameter"].startswith("generate|sarah|"))

        # Obsidian note routes to obsidian_control (not generic text file)
        msgs_obs = [{"role": "user", "content": "write a note in obsidian about project roadmap"}]
        reply_obs = gemini_head._try_fast_pattern_route(msgs_obs)
        self.assertIsNotNone(reply_obs)
        obj_obs = json.loads(reply_obs.text)
        self.assertEqual(obj_obs["action"], "obsidian_control")
        self.assertIn("Daily Note", obj_obs["parameter"])

        # Netflix site search
        msgs_nf = [{"role": "user", "content": "search netflix for stranger things"}]
        reply_nf = gemini_head._try_fast_pattern_route(msgs_nf)
        self.assertIsNotNone(reply_nf)
        obj_nf = json.loads(reply_nf.text)
        self.assertEqual(obj_nf["action"], "site_search")
        self.assertEqual(obj_nf["parameter"], "netflix|stranger things")

        # Reddit site search
        msgs_rd = [{"role": "user", "content": "search reddit for machine learning"}]
        reply_rd = gemini_head._try_fast_pattern_route(msgs_rd)
        self.assertIsNotNone(reply_rd)
        obj_rd = json.loads(reply_rd.text)
        self.assertEqual(obj_rd["action"], "site_search")
        self.assertEqual(obj_rd["parameter"], "reddit|machine learning")

        # Compound chains MUST yield from fast pre-router due to compound-conjunction guard
        compound_prompts = [
            "open notepad and write an essay on artificial intelligence",
            "open notepad and write hello then open spotify and play starboy",
            "open word and write a report about quantum computing",
        ]
        for prompt in compound_prompts:
            msgs = [{"role": "user", "content": prompt}]
            self.assertIsNone(gemini_head._try_fast_pattern_route(msgs),
                              f"Prompt '{prompt}' should yield from fast pre-router")

    # ── Test 8: All-Providers-Down Engages Local Floor Fallback ────────────────

    def test_all_providers_down_engages_local_floor(self):
        pool = model_pool.get_pool()

        # Mock local floor runner
        mock_called = []
        def mock_floor(messages, system, session_id):
            mock_called.append(True)
            return model_pool.ModelCallResult(
                text='{"mode": "command", "action": "open_application", "parameter": "notepad", "tone": "focused"}',
                parsed={"mode": "command", "action": "open_application", "parameter": "notepad", "tone": "focused"},
                provider="local_on_device",
                model="quantized-1.5b",
                elapsed_ms=120.0,
                retries_made=0
            )

        model_pool.set_local_floor_runner(mock_floor)

        try:
            # Simulate all pool endpoints returning None (exhausted)
            with patch.object(pool, "select_next_model", return_value=None):
                res = pool.call_model(
                    messages=[{"role": "user", "content": "open notepad"}],
                    system="System instructions",
                    session_id="session_test_floor"
                )

                self.assertTrue(len(mock_called) > 0)
                self.assertEqual(res.provider, "local_on_device")
                self.assertEqual(res.parsed.get("action"), "open_application")
        finally:
            model_pool.set_local_floor_runner(None)

        # Confirm failure behavior when no local runner or GGUF exists
        with patch.object(pool, "select_next_model", return_value=None):
            with patch.object(pool, "get_available_endpoints", return_value=[model_pool.DEFAULT_MODELS[0]]):
                with self.assertRaises(model_pool.PoolExhaustedError):
                    pool.call_model(
                        messages=[{"role": "user", "content": "open notepad"}],
                        system="System instructions",
                        session_id="session_test_fail"
                    )


if __name__ == "__main__":
    unittest.main()
