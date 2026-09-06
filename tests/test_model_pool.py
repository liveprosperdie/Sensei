"""Unit and simulation tests for Akira's multi-provider, multi-model rotation & chain throttling."""

import collections
import os
import unittest
from unittest.mock import MagicMock, patch

import model_pool
from model_pool import (
    ModelEndpoint,
    ModelPoolManager,
    PoolExhaustedError,
    parse_reset_seconds,
    throttle_chain_step,
)


class TestModelPoolRotationAndThrottling(unittest.TestCase):
    """Test suite covering Groq-only rotation, quality tiering, session pinning, and throttling."""

    def setUp(self):
        # Create an isolated test pool with 5 verified Groq models
        self.endpoints = [
            ModelEndpoint("groq", "openai/gpt-oss-120b", "120B", 30, 1000, "TEST_GROQ_KEY", "https://api.groq.com/openai/v1", quality_tier="high"),
            ModelEndpoint("groq", "qwen/qwen3.8-27b", "27B", 30, 1000, "TEST_GROQ_KEY", "https://api.groq.com/openai/v1", quality_tier="high"),
            ModelEndpoint("groq", "qwen/qwen3.6-27b", "27B", 30, 1000, "TEST_GROQ_KEY", "https://api.groq.com/openai/v1", quality_tier="high"),
            ModelEndpoint("groq", "groq/compound", "compound", 30, 1000, "TEST_GROQ_KEY", "https://api.groq.com/openai/v1", quality_tier="standard"),
            ModelEndpoint("groq", "groq/compound-mini", "compound", 30, 1000, "TEST_GROQ_KEY", "https://api.groq.com/openai/v1", quality_tier="standard"),
        ]
        os.environ["TEST_GROQ_KEY"] = "mock_groq_key"
        self.pool = ModelPoolManager(self.endpoints)

    def tearDown(self):
        os.environ.pop("TEST_GROQ_KEY", None)

    # ── Test Header & Reset Parsing ──────────────────────────────────────────

    def test_parse_reset_seconds(self):
        self.assertEqual(parse_reset_seconds("4m19.2s"), 259.2)
        self.assertEqual(parse_reset_seconds("52.86s"), 52.86)
        self.assertEqual(parse_reset_seconds("10m4.8s"), 604.8)
        self.assertEqual(parse_reset_seconds("15"), 15.0)
        self.assertEqual(parse_reset_seconds(15), 15.0)
        self.assertEqual(parse_reset_seconds("1h30m"), 5400.0)
        self.assertEqual(parse_reset_seconds("250ms"), 0.25)
        self.assertIsNone(parse_reset_seconds(""))
        self.assertIsNone(parse_reset_seconds(None))

    # ── Test Groq-Only Models Registration ───────────────────────────────────

    def test_groq_only_models_registered(self):
        """Confirm DEFAULT_MODELS contains ONLY Groq models, no other providers."""
        default_endpoints = model_pool.DEFAULT_MODELS
        self.assertGreater(len(default_endpoints), 0)

        excluded_providers = {"cerebras", "nvidia", "cloudflare", "openrouter"}
        for ep in default_endpoints:
            self.assertEqual(ep.provider, "groq", f"Non-Groq provider found in pool: {ep.provider}")
            self.assertNotIn(ep.provider, excluded_providers)

        model_ids = [ep.model_id for ep in default_endpoints]
        self.assertNotIn("llama-3.3-70b-versatile", model_ids)
        self.assertNotIn("deepseek-r1-distill-llama-70b", model_ids)
        self.assertIn("openai/gpt-oss-120b", model_ids)
        self.assertIn("qwen/qwen3.8-27b", model_ids)

    # ── Test Quality Tier Prioritization ─────────────────────────────────────

    def test_quality_tier_prioritization(self):
        """Confirm high quality tier models are prioritized over standard models."""
        high_ep = ModelEndpoint("groq", "openai/gpt-oss-120b", "120B", 30, 1000, "TEST_GROQ_KEY", "https://api.groq.com/openai/v1", quality_tier="high")
        std_ep = ModelEndpoint("groq", "groq/compound-mini", "compound", 30, 1000, "TEST_GROQ_KEY", "https://api.groq.com/openai/v1", quality_tier="standard")

        test_pool = ModelPoolManager([std_ep, high_ep])
        # Both available and idle -> high tier should win due to quality_bonus (+20.0)
        selected = test_pool.select_next_model()
        self.assertIsNotNone(selected)
        self.assertEqual(selected.quality_tier, "high")
        self.assertEqual(selected.model_id, "openai/gpt-oss-120b")

    # ── Test 5-Task Session Batch Pinning ─────────────────────────────────────

    def test_session_batch_pinning(self):
        """Confirm a session pins to one model for up to 5 calls, then rotates."""
        session_id = "test_session_batch"
        used_models = []

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"mode": "conversation", "response": "ok"}'}}]
            }
            mock_post.return_value.headers = {"x-ratelimit-remaining-requests": "999"}

            # Calls 1 to 5 should stay pinned to the exact same model
            for i in range(5):
                res = self.pool.call_model(
                    messages=[{"role": "user", "content": f"turn {i}"}],
                    session_id=session_id,
                )
                used_models.append(res.model)

            self.assertEqual(len(set(used_models)), 1, f"Session did not stay pinned: {used_models}")
            pinned_model = used_models[0]

            # 6th call should rotate away / re-evaluate since turns_used reached 5
            res_6 = self.pool.call_model(
                messages=[{"role": "user", "content": "turn 5"}],
                session_id=session_id,
            )
            # The pin was rotated
            pin_info = self.pool.get_session_pin(session_id)
            self.assertIsNotNone(pin_info)
            self.assertEqual(pin_info["turns_used"], 1)

    # ── Test Session Pin 429 Failover ─────────────────────────────────────────

    def test_session_pin_429_failover(self):
        """Confirm 429 mid-batch immediately unpins and selects next model."""
        session_id = "test_session_429"

        with patch("requests.post") as mock_post:
            # First call succeeds
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"mode": "conversation", "response": "first"}'}}]
            }
            mock_post.return_value.headers = {"x-ratelimit-remaining-requests": "999"}

            res1 = self.pool.call_model(
                messages=[{"role": "user", "content": "hello"}],
                session_id=session_id,
            )
            first_model = res1.model

            # Second call: the pinned model returns 429, but next model succeeds
            call_count = 0
            def mock_post_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                mock_resp = MagicMock()
                if call_count == 1:
                    mock_resp.status_code = 429
                    mock_resp.text = '{"error": {"message": "Rate limit reached. Try in 10s"}}'
                    mock_resp.headers = {"retry-after": "10"}
                else:
                    mock_resp.status_code = 200
                    mock_resp.json.return_value = {
                        "choices": [{"message": {"content": '{"mode": "conversation", "response": "fallback"}'}}]
                    }
                    mock_resp.headers = {"x-ratelimit-remaining-requests": "998"}
                return mock_resp

            mock_post.side_effect = mock_post_side_effect

            res2 = self.pool.call_model(
                messages=[{"role": "user", "content": "second turn"}],
                session_id=session_id,
            )
            self.assertNotEqual(res2.model, first_model, "Failed model should not have handled the request")
            self.assertEqual(res2.status_code, 200)

            # Confirm session is now pinned to the new model
            pin = self.pool.get_session_pin(session_id)
            self.assertIsNotNone(pin)
            self.assertEqual(pin["endpoint"].model_id, res2.model)

    # ── Test Session Reset ───────────────────────────────────────────────────

    def test_session_reset(self):
        """Confirm reset_session_pin cleanly removes the session pin."""
        session_id = "test_reset_session"

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"response": "hi"}'}}]
            }
            mock_post.return_value.headers = {"x-ratelimit-remaining-requests": "999"}

            self.pool.call_model(messages=[{"role": "user", "content": "hi"}], session_id=session_id)
            self.assertIsNotNone(self.pool.get_session_pin(session_id))

            self.pool.reset_session_pin(session_id)
            self.assertIsNone(self.pool.get_session_pin(session_id))

    # ── Verification Item 1: Multi-Action Chain Distribution ─────────────────

    def test_multi_action_chain_distribution(self):
        """Simulate a long multi-action chain (10 sub-actions) with stagger

        and confirm backend calls are distributed across multiple models in the pool.
        """
        chain_steps = 10
        stagger_s = 0.3  # 300ms mandatory stagger between chain steps
        current_time = 1000.0
        used_models = []

        with patch("requests.post") as mock_post, patch("time.monotonic") as mock_time:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"decision": "allow", "reasons": []}'}}]
            }
            mock_post.return_value.headers = {
                "x-ratelimit-remaining-requests": "990",
                "x-ratelimit-reset-requests": "1m0s",
            }

            for step_idx in range(chain_steps):
                mock_time.return_value = current_time
                res = self.pool.call_model(
                    messages=[{"role": "user", "content": f"subaction {step_idx}"}],
                    system="You are a safety guard.",
                )
                used_models.append(f"{res.provider}/{res.model}")
                current_time += stagger_s

        distinct_models = set(used_models)
        counts = collections.Counter(used_models)
        print(f"[test_chain_dist] 10 calls distributed across {len(distinct_models)} models: {counts}")

        # Assert distributed across at least 4 distinct models
        self.assertGreaterEqual(
            len(distinct_models), 4,
            f"Expected at least 4 distinct models in 10-step chain, got {len(distinct_models)}: {counts}"
        )
        max_handled = max(counts.values())
        self.assertLessEqual(
            max_handled, 4,
            f"Single model took too many calls ({max_handled}/10): {counts}"
        )

    # ── Verification Item 2: Rapid-Fire Commands (60s simulation) ────────────

    def test_rapid_fire_burst_rpm_ceiling(self):
        """Simulate rapid-fire commands (one every 1-2 seconds) for 60 seconds

        and confirm no single model in the pool exceeds ~50% of its per-minute limit.
        """
        simulated_duration = 60  # seconds
        request_interval = 1.0   # 1 request per second = 60 total rapid requests
        total_requests = int(simulated_duration / request_interval)

        current_time = 2000.0

        with patch("requests.post") as mock_post, patch("time.monotonic") as mock_time:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"mode": "command", "action": "adjust_volume", "parameter": "50"}'}}]
            }
            mock_post.return_value.headers = {"x-ratelimit-remaining-requests": "950"}

            for _ in range(total_requests):
                mock_time.return_value = current_time
                self.pool.call_model(messages=[{"role": "user", "content": "fast command"}])
                current_time += request_interval

            mock_time.return_value = current_time

            # Verify RPM load per model in sliding window
            for ep in self.pool.get_available_endpoints():
                state = self.pool.get_state(ep)
                load = state.current_rpm_load
                utilization = state.rpm_utilization_ratio
                print(f"[test_rapid_burst] {ep.full_name}: load={load}/{ep.rpm_limit} ({utilization*100:.1f}%)")
                # Assert no single model exceeds 50% of its 30 RPM limit (i.e. <= 15 calls)
                self.assertLessEqual(
                    utilization, 0.50,
                    f"Model {ep.full_name} exceeded 50% RPM limit during rapid burst: {load}/{ep.rpm_limit}"
                )

    # ── Verification Item 3: Full Pool Exhaustion & Recovery ─────────────────

    def test_full_pool_exhaustion_and_recovery(self):
        """Simulate a full pool exhaustion scenario (force 429s across all models)

        and confirm graceful degradation: a clear wait response, with automatic recovery.
        """
        current_time = 5000.0

        with patch("requests.post") as mock_post, patch("time.monotonic") as mock_time:
            mock_time.return_value = current_time
            mock_post.return_value.status_code = 429
            mock_post.return_value.text = '{"error": {"message": "Rate limit reached. Please try again in 15s"}}'
            mock_post.return_value.headers = {"retry-after": "15"}

            with self.assertRaises(PoolExhaustedError) as ctx:
                self.pool.call_model(messages=[{"role": "user", "content": "hello"}])

            self.assertIn("temporarily busy", str(ctx.exception))
            self.assertGreaterEqual(ctx.exception.retry_after, 10.0)

            current_time += 16.0
            mock_time.return_value = current_time

            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"mode": "conversation", "response": "I am back online!"}'}}]
            }
            mock_post.return_value.headers = {"x-ratelimit-remaining-requests": "999"}

            recovered_res = self.pool.call_model(messages=[{"role": "user", "content": "are you back?"}])
            self.assertIsNotNone(recovered_res)
            self.assertEqual(recovered_res.status_code, 200)
            self.assertIn("online", recovered_res.text)

    # ── Verification Item 4: Conversational Pacing Utilization ────────────────

    def test_conversational_pacing_utilization(self):
        """Confirm normal conversational pacing (one request per 15-20 seconds)

        shows negligible (<10%) utilization of any single model's per-minute capacity.
        """
        interval = 20.0  # seconds between conversational turns (1 turn per 20s)
        total_turns = 15 # over 5 minutes
        current_time = 2000.0

        with patch("requests.post") as mock_post, patch("time.monotonic") as mock_time:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"mode": "conversation", "response": "Sure thing!"}'}}]
            }
            mock_post.return_value.headers = {"x-ratelimit-remaining-requests": "999"}

            for _ in range(total_turns):
                mock_time.return_value = current_time
                self.pool.call_model(messages=[{"role": "user", "content": "chat turn"}])
                current_time += interval

            mock_time.return_value = current_time

            for ep in self.pool.get_available_endpoints():
                state = self.pool.get_state(ep)
                load = state.current_rpm_load
                utilization = state.rpm_utilization_ratio
                print(f"[test_chat_pacing] {ep.full_name}: load={load}/{ep.rpm_limit} ({utilization*100:.1f}%)")
                self.assertLessEqual(
                    utilization, 0.10,
                    f"Model {ep.full_name} had {utilization*100:.1f}% utilization, expected <= 10%"
                )

    # ── Verification Part 3: Chain-Level Throttling & Safety Check ───────────

    def test_chain_throttling_stagger_and_safety_logging(self):
        """Verify chain throttling safety check, mandatory stagger, and pacing pauses."""
        logs = []
        slept_durations = []

        def mock_log(msg: str):
            logs.append(msg)

        total_steps = 10
        stagger_ms = 300
        pacing_interval = 5
        pacing_pause_s = 1.0

        with patch("time.sleep") as mock_sleep:
            for step_idx in range(total_steps):
                d = throttle_chain_step(
                    step_idx=step_idx,
                    total_steps=total_steps,
                    stagger_ms=stagger_ms,
                    max_safe_length=8,
                    pacing_interval=pacing_interval,
                    pacing_pause_s=pacing_pause_s,
                    on_log=mock_log,
                )
                slept_durations.append(d)

        self.assertTrue(
            any("Long multi-action chain detected (10 sub-actions)" in m for m in logs),
            "Expected long multi-action chain warning log"
        )
        self.assertTrue(
            any("Periodic pacing pause (1.0s) at step 5/10" in m for m in logs),
            "Expected periodic pacing pause log at step 5"
        )
        self.assertEqual(slept_durations[0], 0.0)
        for i in [1, 2, 3, 4, 6, 7, 8, 9]:
            self.assertAlmostEqual(slept_durations[i], 0.3, places=2)
        self.assertAlmostEqual(slept_durations[5], 1.0, places=2)
        self.assertEqual(mock_sleep.call_count, 9)

    # ── Verification Part 3: Guard Fast-Path Skipping in Chains ──────────────

    def test_guard_fast_path_skipping_in_chains(self):
        """Verify that in multi-action chains, fast-path eligible actions skip

        model calls entirely, conserving backend rate limit budget.
        """
        import sys, types
        orig_akira = sys.modules.get("akira")
        sys.modules["akira"] = types.SimpleNamespace(_is_dangerous_step=lambda step: False)
        try:
            import guard
            from guard_rules import ALLOW

            fast_path_actions = [
                ("switch_tab", "1"),
                ("adjust_volume", "50"),
                ("web_search", "python docs"),
                ("screenshot", ""),
                ("adjust_brightness", "80"),
            ]

            with patch("servant_clients.call_json") as mock_servant, patch("model_pool.ModelPoolManager.call_json") as mock_pool:
                for action, param in fast_path_actions:
                    verdict = guard.review(action, param)
                    self.assertEqual(verdict.decision, ALLOW)
                    self.assertEqual(verdict.source, "static")

                mock_servant.assert_not_called()
                mock_pool.assert_not_called()
        finally:
            if orig_akira is not None:
                sys.modules["akira"] = orig_akira
            else:
                sys.modules.pop("akira", None)


if __name__ == "__main__":
    unittest.main()
