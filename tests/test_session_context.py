"""End-to-end and unit tests reproducing the tab-correction scenario and verifying session context."""

import os
import unittest
from unittest.mock import MagicMock, patch

import akira
import gemini_head
import model_pool


class TestSessionContextAndCorrection(unittest.TestCase):
    """Verifies that session action history and browser tab context resolve conversational corrections."""

    def setUp(self):
        akira._reset_session_action_history()
        akira._active_session_id = "test_session_ctx_001"

    def tearDown(self):
        akira._end_session()

    # ── Test 1: Action History Recording & Ring Buffer ────────────────────────

    def test_session_action_history_recording_and_ring_buffer(self):
        """Confirm actions are stored up to 8 maxlen in FIFO order."""
        akira._reset_session_action_history()
        self.assertEqual(len(akira._session_action_history), 0)

        # Record 10 actions; only the last 8 should be kept
        for i in range(10):
            akira._record_session_action(
                action=f"action_{i}",
                parameter=f"param_{i}",
                result=f"result_{i}",
            )

        self.assertEqual(len(akira._session_action_history), 8)
        # Oldest kept action should be action_2 (0 and 1 dropped)
        self.assertEqual(akira._session_action_history[0]["action"], "action_2")
        self.assertEqual(akira._session_action_history[-1]["action"], "action_9")

        # Test reset
        akira._reset_session_action_history()
        self.assertEqual(len(akira._session_action_history), 0)

    # ── Test 2: Build Session Context with Tabs and Action History ────────────

    def test_build_session_context_injection(self):
        """Confirm _build_session_context formats tabs, actions, and PC state."""
        akira._record_session_action(
            action="open_site_tab",
            parameter="https://www.youtube.com",
            result="opened YouTube in tab",
        )

        mock_tabs = [
            {"title": "YouTube - Starboy", "url": "https://www.youtube.com/watch?v=123"},
            {"title": "GitHub - Sensei", "url": "https://github.com/liveprosperdie/Sensei"},
        ]
        mock_ctx = {
            "open_windows": ["Chrome", "VS Code"],
            "foreground_app": "Google Chrome",
            "current_url": "https://www.youtube.com",
        }

        with patch("akira.get_all_tabs", return_value=mock_tabs), \
             patch("akira.get_pc_context", return_value=mock_ctx):
            ctx_str = akira._build_session_context()

        self.assertIn("[RECENT ACTIONS THIS SESSION]", ctx_str)
        self.assertIn("1. open_site_tab | https://www.youtube.com -> opened YouTube in tab", ctx_str)
        self.assertIn("[CURRENT BROWSER TABS]", ctx_str)
        self.assertIn("YouTube - Starboy, GitHub - Sensei", ctx_str)
        self.assertIn("[PC STATE]", ctx_str)
        self.assertIn("Focused app: Google Chrome", ctx_str)

    # ── Test 3: Fast Pre-Router Correction Bypass ─────────────────────────────

    def test_fast_pre_router_bypasses_on_correction_phrases(self):
        """Confirm fast pre-router does NOT hijack natural corrections."""
        correction_phrases = [
            "but I wanted to open the tab where it was opened before",
            "no I meant the one that's already open",
            "switch back to youtube",
            "the tab that was open before",
            "the other tab",
            "open the tab that's already open",
            "actually I meant the previous tab",
            "no i wanted youtube instead of search",
        ]

        for phrase in correction_phrases:
            # Without context prefix
            messages = [{"role": "user", "content": phrase}]
            reply = gemini_head._try_fast_pattern_route(messages)
            self.assertIsNone(
                reply,
                f"Fast pre-router falsely hijacked correction phrase: {phrase!r} -> {reply}"
            )

            # With session context block prepended
            full_msg = (
                "[RECENT ACTIONS THIS SESSION]\n1. open_site_tab | youtube\n\n"
                "[CURRENT BROWSER TABS]\nYouTube - Starboy\n\n"
                "[PC STATE]\nWindows: Chrome\n\n" + phrase
            )
            reply_with_ctx = gemini_head._try_fast_pattern_route([{"role": "user", "content": full_msg}])
            self.assertIsNone(
                reply_with_ctx,
                f"Fast pre-router falsely hijacked correction with context: {phrase!r} -> {reply_with_ctx}"
            )

        # Sanity check: non-correction standard fast patterns STILL work
        normal_reply = gemini_head._try_fast_pattern_route([{"role": "user", "content": "set volume to 50"}])
        self.assertIsNotNone(normal_reply)
        self.assertIn("adjust_volume", normal_reply.text)

    # ── Test 4: End-to-End Tab Correction Scenario ───────────────────────────

    def test_end_to_end_tab_correction_resolves_to_switch_tab(self):
        """Reproduce original failure scenario end-to-end:

        Turn 1: User opens YouTube tab.
        Turn 2: User says "but I wanted to open the tab where it was opened before".
        With action history and active tabs injected, confirm router resolves to switch_tab.
        """
        # Turn 1: open YouTube tab
        akira._record_session_action(
            action="open_site_tab",
            parameter="https://www.youtube.com",
            result="opened YouTube in tab",
        )

        # User's correction turn
        user_utterance = "but I wanted to open the tab where it was opened before"

        mock_tabs = [{"title": "YouTube - Starboy", "url": "https://www.youtube.com/watch?v=Starboy"}]
        mock_ctx = {"open_windows": ["Google Chrome"], "foreground_app": "Google Chrome", "current_url": "https://www.google.com"}

        with patch("akira.get_all_tabs", return_value=mock_tabs), \
             patch("akira.get_pc_context", return_value=mock_ctx):
            full_context = akira._build_session_context()
            turn_input = full_context + user_utterance

        # Step A: Confirm fast pattern router is bypassed
        fast_res = gemini_head._try_fast_pattern_route([{"role": "user", "content": turn_input}])
        self.assertIsNone(fast_res, "Fast pre-router should return None for conversational correction")

        # Step B: LLM receives full prompt instructing switch_tab on existing tabs
        # Mock pool.call_model to verify prompt content and test routing result
        with patch.object(model_pool.ModelPoolManager, "call_model") as mock_call:
            mock_call.return_value = model_pool.ModelCallResult(
                text='{"mode": "command", "action": "switch_tab", "parameter": "YouTube", "tone": "focused"}',
                parsed={"mode": "command", "action": "switch_tab", "parameter": "YouTube", "tone": "focused"},
                provider="groq",
                model="openai/gpt-oss-120b",
                elapsed_ms=120.0,
                status_code=200,
            )

            route_reply = gemini_head._route_via_groq(
                groq_key="mock_key",
                messages=[{"role": "user", "content": turn_input}],
                system_blocks=[],
                session_id=akira._active_session_id,
            )

            self.assertIsNotNone(route_reply)
            self.assertIn("switch_tab", route_reply.text)
            self.assertIn("YouTube", route_reply.text)

            # Confirm session_id was forwarded to model pool
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args.kwargs
            self.assertEqual(call_kwargs.get("session_id"), akira._active_session_id)
            # Confirm prompt instructed switch_tab
            system_prompt = call_kwargs.get("system", "")
            self.assertIn("[CURRENT BROWSER TABS]", system_prompt)
            self.assertIn("switch_tab", system_prompt)

    # ── Test 5: Session Batch Pinning Within Groq Pool ────────────────────────

    def test_session_batch_pinning_within_groq_pool(self):
        """Confirm 5-task batch pinning retains model across turns and unpins on reset."""
        session_id = "test_akira_batch_pin"

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "choices": [{"message": {"content": '{"mode": "conversation", "response": "ok"}'}}]
            }
            mock_post.return_value.headers = {"x-ratelimit-remaining-requests": "999"}

            pool = model_pool.get_pool()

            # Run 5 turns under same session_id
            used_models = []
            for i in range(5):
                res = pool.call_model(
                    messages=[{"role": "user", "content": f"turn {i}"}],
                    session_id=session_id,
                )
                used_models.append(res.model)

            # All 5 turns must use the exact same model
            self.assertEqual(len(set(used_models)), 1)

            # Reset clears the pin
            pool.reset_session_pin(session_id)
            self.assertIsNone(pool.get_session_pin(session_id))


if __name__ == "__main__":
    unittest.main()
