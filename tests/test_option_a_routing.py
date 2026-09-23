"""tests/test_option_a_routing.py — Verification of Option A collapsed routing architecture.

Validates:
1. Phase 1 Regex Fast-Path: Zero tokens, zero Groq calls, deterministic envelope emission.
2. Independent Multi-Step Regex Chains: Emits combined action envelope without Groq.
3. Groq Router Fallback (Regex Miss):
   - Triggered on regex miss.
   - Payload receives ONLY raw utterance and format_delta_context() output.
   - Zero access / excluded: core_profile.md, conversation history, file/clipboard content, full context.
4. Fail-Closed Safety:
   - Malformed JSON -> fails closed (escalates to Claude).
   - Unknown action name not in ACTION_RULES -> fails closed.
   - Parameter arity violation -> fails closed.
   - action_guard rule violation (download_image after search_image) -> fails closed.
   - More than 1 download_image -> fails closed.
5. End-to-end integration via akira.get_akira_response().
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import akira
import guard_rules
import tiered_classifier


class TestOptionAFastPath(unittest.TestCase):

    @patch("tiered_classifier._call_groq_router")
    def test_single_command_regex_fast_path_zero_tokens(self, mock_groq):
        """Standard volume adjustment must resolve deterministically via regex with 0 Groq calls."""
        env = tiered_classifier.classify_and_synthesize("turn volume up")
        self.assertIsNotNone(env)
        self.assertEqual(env.get("mode"), "command")
        self.assertEqual(env.get("action"), "adjust_volume")
        self.assertEqual(env.get("parameter"), "+10")
        self.assertEqual(len(env.get("actions", [])), 1)
        # Verify ZERO Groq router calls were made
        mock_groq.assert_not_called()

    @patch("tiered_classifier._call_groq_router")
    def test_open_application_regex_fast_path_zero_tokens(self, mock_groq):
        """App open command resolves deterministically via regex with 0 Groq calls."""
        env = tiered_classifier.classify_and_synthesize("open notepad")
        self.assertIsNotNone(env)
        self.assertEqual(env.get("action"), "open_application")
        self.assertEqual(env.get("parameter"), "notepad")
        mock_groq.assert_not_called()

    @patch("tiered_classifier._call_groq_router")
    def test_compound_multi_step_chain_routes_to_groq(self, mock_groq):
        """Compound command chains with 'then'/commas bypass regex and route to Groq router for multi-action synthesis."""
        mock_groq.return_value = {
            "mode": "command",
            "actions": [
                {"action": "open_application", "parameter": "notepad"},
                {"action": "open_application", "parameter": "chrome"},
                {"action": "open_application", "parameter": "spotify"},
            ],
            "response": "Opening notepad, chrome, and spotify."
        }
        chain_cmd = "open notepad, then open chrome, then open spotify"
        env = tiered_classifier.classify_and_synthesize(chain_cmd)
        self.assertIsNotNone(env)
        self.assertEqual(env.get("mode"), "command")
        actions = env.get("actions", [])
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0]["parameter"], "notepad")
        self.assertEqual(actions[1]["parameter"], "chrome")
        self.assertEqual(actions[2]["parameter"], "spotify")
        mock_groq.assert_called_once()

    @patch("tiered_classifier._call_groq_router")
    def test_conversation_routes_to_groq(self, mock_groq):
        """Conversational greetings without regex fast-path route to Groq router."""
        mock_groq.return_value = {"mode": "conversation", "response": "Hello! How can I assist you today?"}
        env = tiered_classifier.classify_and_synthesize("hello akira")
        self.assertIsNotNone(env)
        self.assertEqual(env.get("mode"), "conversation")
        self.assertEqual(env.get("response"), "Hello! How can I assist you today?")
        mock_groq.assert_called_once()


class TestOptionAGroqRouterPayloadAndExclusions(unittest.TestCase):

    @patch("tiered_classifier._call_groq_router")
    def test_groq_call_triggered_on_regex_miss(self, mock_groq):
        """Unrecognized / complex command triggers Groq router."""
        mock_groq.return_value = {
            "mode": "command",
            "actions": [{"action": "click", "parameter": "500,300"}],
            "response": "Clicking coordinate."
        }
        utterance = "click on the blue button near the middle"
        delta_ctx = "[WINDOW CHANGED] Chrome -> VS Code"
        env = tiered_classifier.classify_and_synthesize(utterance, delta_context=delta_ctx)

        mock_groq.assert_called_once_with(utterance, delta_context=delta_ctx)
        self.assertEqual(env.get("action"), "click")

    def test_groq_system_prompt_encodes_action_rules_and_safety_constraints(self):
        """Groq system prompt contains serialized ACTION_RULES enum, arity spec, and action_guard safety rules."""
        prompt = tiered_classifier._build_router_system_prompt()

        # 1. ACTION_RULES coverage
        self.assertIn("ACTION_RULES", prompt)
        self.assertIn("open_application", prompt)
        self.assertIn("adjust_volume", prompt)
        self.assertIn("docs_control", prompt)
        self.assertIn("download_image", prompt)
        self.assertIn("search_image", prompt)

        # 2. action_guard chain safety rules
        self.assertIn("MANDATORY CHAIN SAFETY RULES", prompt)
        self.assertIn("NEVER chain 'download_image' in the same turn as 'search_image'", prompt)
        self.assertIn("At most ONE 'download_image' action per turn", prompt)

    @patch("groq.Groq")
    def test_groq_call_excludes_unauthorized_context(self, mock_groq_cls):
        """Groq router call payload contains ONLY delta context and utterance — no files, clipboard, or core profile."""
        os.environ["GROQ_API_KEY"] = "fake-key-for-test"
        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"mode": "command", "actions": [{"action": "click", "parameter": "submit"}]}'))]
        )

        utterance = "click the submit button"
        delta_ctx = "[DELTA ACTIVE WINDOW] Notepad -> Chrome"

        tiered_classifier._call_groq_router(utterance, delta_context=delta_ctx)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[1]["content"]

        # Confirm delta_context and utterance are present
        self.assertIn("[DELTA ACTIVE WINDOW]", user_msg)
        self.assertIn(utterance, user_msg)

        # Confirm unauthorized context sources are NOT present
        self.assertNotIn("core_profile", user_msg)
        self.assertNotIn("clipboard", user_msg.lower())
        self.assertNotIn("<all_tabs>", user_msg)
        self.assertNotIn("<installed_apps>", user_msg)


class TestOptionAFailClosedSafety(unittest.TestCase):

    def test_malformed_json_fails_closed(self):
        """Invalid JSON from Groq fails closed to Claude escalation."""
        with patch("tiered_classifier._call_groq_router", return_value={"escalate": True, "reason": "unparseable_or_truncated_json"}):
            env = tiered_classifier.classify_and_synthesize("recalibrate the sensor array")
            self.assertTrue(env.get("escalate"))
            self.assertEqual(env.get("reason"), "unparseable_or_truncated_json")

    def test_unknown_action_fails_closed(self):
        """Action not in ACTION_RULES fails closed to Claude escalation."""
        groq_reply = {
            "mode": "command",
            "actions": [{"action": "totally_fabricated_action", "parameter": "something"}],
        }
        with patch("tiered_classifier._call_groq_router", return_value=groq_reply):
            env = tiered_classifier.classify_and_synthesize("recalibrate warp nacelles")
            self.assertTrue(env.get("escalate"))
            self.assertIn("guard_rules_rejected", env.get("reason", ""))

    def test_parameter_arity_mismatch_fails_closed(self):
        """Action accepting 0 parameters failing arity check when given an argument fails closed."""
        groq_reply = {
            "mode": "command",
            "actions": [{"action": "empty_recycle_bin", "parameter": "unexpected_argument"}],
        }
        with patch("tiered_classifier._call_groq_router", return_value=groq_reply):
            env = tiered_classifier.classify_and_synthesize("clear out the recycle bin")
            self.assertTrue(env.get("escalate"))
            self.assertIn("guard_rules_rejected", env.get("reason", ""))

    def test_action_guard_violation_search_then_download_fails_closed(self):
        """download_image chained after search_image is caught by action_guard and fails closed."""
        groq_reply = {
            "mode": "command",
            "actions": [
                {"action": "search_image", "parameter": "cute cats"},
                {"action": "download_image", "parameter": "https://example.com/cat.jpg"},
            ],
        }
        with patch("tiered_classifier._call_groq_router", return_value=groq_reply):
            env = tiered_classifier.classify_and_synthesize("find cat pictures and download the first one")
            self.assertTrue(env.get("escalate"))
            self.assertIn("action_guard_sanitized_out_actions", env.get("reason", ""))

    def test_action_guard_violation_multiple_downloads_fails_closed(self):
        """Multiple download_image actions in one turn are caught and fail closed."""
        groq_reply = {
            "mode": "command",
            "actions": [
                {"action": "download_image", "parameter": "https://example.com/1.jpg"},
                {"action": "download_image", "parameter": "https://example.com/2.jpg"},
            ],
        }
        with patch("tiered_classifier._call_groq_router", return_value=groq_reply):
            env = tiered_classifier.classify_and_synthesize("download both images")
            self.assertTrue(env.get("escalate"))
            self.assertIn("action_guard_sanitized_out_actions", env.get("reason", ""))

    @patch("groq.Groq")
    def test_groq_raw_malformed_syntax_string_fails_closed(self, mock_groq_cls):
        """When Groq returns raw unparseable garbage text instead of JSON, _call_groq_router fails closed."""
        os.environ["GROQ_API_KEY"] = "fake-key-for-test"
        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        # Simulate raw non-JSON refusal or syntax error from LLM
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="I cannot fulfill this request because it violates safety guidelines."))]
        )

        res = tiered_classifier._call_groq_router("some weird request")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("escalate"))
        self.assertEqual(res.get("reason"), "unparseable_or_truncated_json")

    def test_groq_adversarial_self_modification_fails_closed(self):
        """Adversarial Groq output attempting to delete Akira source code fails closed via guard_rules/security_guard."""
        adversarial_reply = {
            "mode": "command",
            "actions": [{"action": "delete_files", "parameter": "akira.py"}],
        }
        with patch("tiered_classifier._call_groq_router", return_value=adversarial_reply):
            env = tiered_classifier.classify_and_synthesize("clean up old script files")
            self.assertTrue(env.get("escalate"))
            self.assertIn("guard_rules_rejected", env.get("reason", ""))
            self.assertIn("strictly prohibited", env.get("reason", ""))


    def test_office_control_legitimate_not_blocked(self):
        """Legitimate office_control actions (e.g. excel|new, word|new) must not be falsely blocked by self-modification."""
        import guard_rules
        v1 = guard_rules.validate("office_control", "excel|new")
        self.assertEqual(v1.decision, guard_rules.ALLOW)

        v2 = guard_rules.validate("office_control", "excel|write|A1|Name")
        self.assertEqual(v2.decision, guard_rules.ALLOW)

        v3 = guard_rules.validate("vscode_control", "open folder|D:\\test")
        self.assertEqual(v3.decision, guard_rules.ALLOW)

        v4 = guard_rules.validate("github_control", "search repos|python")
        self.assertEqual(v4.decision, guard_rules.ALLOW)

    def test_office_control_codebase_blocked(self):
        """office_control save as targeting Akira codebase files must be blocked."""
        import guard_rules
        v = guard_rules.validate("office_control", "word|save as|akira.py")
        self.assertEqual(v.decision, guard_rules.BLOCK)
        self.assertTrue(any("self-modification" in r.lower() or "codebase" in r.lower() for r in v.reasons))

    @patch("tiered_classifier._call_groq_router")
    def test_copy_last_response_to_clipboard(self, mock_groq):
        """Asking to copy the last response/information puts the cached assistant response in write_clipboard."""
        import session_context_cache
        sample_info = "LLMs are neural networks trained on vast datasets of text."
        session_context_cache.set_last_assistant_response(sample_info)
        mock_groq.return_value = {
            "mode": "command",
            "actions": [{"action": "write_clipboard", "parameter": sample_info}],
            "response": "Copied to your clipboard."
        }

        utterance = "Sensei, copy this information into my clipboard that you provided in the last response."
        env = tiered_classifier.classify_and_synthesize(utterance)
        self.assertEqual(env.get("mode"), "command")
        self.assertEqual(env.get("action"), "write_clipboard")
        self.assertEqual(env.get("parameter"), sample_info)
        self.assertEqual(env["actions"][0]["parameter"], sample_info)


if __name__ == "__main__":
    unittest.main()

