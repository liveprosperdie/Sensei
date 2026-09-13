"""tests/test_tiered_routing.py — Automated test suite for Akira's tiered routing layer.

Validates:
1. Decision API three-way mode classification (command, conversation, document_generation)
2. Complexity classification (simple, complex, uncertain) with cheap named signals
3. Local adapter allowlist enforcement (ADAPTER_ALLOWED_INTENTS)
4. Author-agnostic document creation sink
5. Routing coordinator in get_akira_response (speech head vs Claude fallback)
6. Fail-safe fail-open on speech head exception or timeout
7. Feature flag revert via AKIRA_ROUTING_MODE=legacy
8. Unified GUARD validation seam
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import akira
import local_adapter
import speech_head
import tiered_classifier
from tiered_config import ADAPTER_ALLOWED_INTENTS, DOC_MAX_SIMPLE_WORDS


class TestDecisionAPIClassification(unittest.TestCase):

    def test_classify_simple_conversation(self):
        """Simple greetings and chit-chat classify as conversation / simple."""
        res = tiered_classifier.classify("Hello Akira, how are you?")
        self.assertEqual(res.mode, "conversation")
        self.assertEqual(res.complexity, "simple")
        self.assertFalse(res.escalate)

    def test_classify_complex_conversation_multi_part(self):
        """Multi-part question or comparative language classifies as conversation / complex."""
        query = "Can you explain how Redis replication works and also what are the pros and cons?"
        res = tiered_classifier.classify(query)
        self.assertEqual(res.mode, "conversation")
        self.assertEqual(res.complexity, "complex")
        self.assertTrue(res.escalate)

    def test_classify_simple_document(self):
        """Short document or quick note classifies as document_generation / simple."""
        query = "Write a doc with my quick grocery list: milk, eggs, bread"
        res = tiered_classifier.classify(query)
        self.assertEqual(res.mode, "document_generation")
        self.assertEqual(res.complexity, "simple")
        self.assertFalse(res.escalate)

    def test_classify_complex_document_keywords(self):
        """Document with analytical/comparative keywords classifies as complex."""
        query = "Draft a document comparing Redis and Memcached with a technical breakdown"
        res = tiered_classifier.classify(query)
        self.assertEqual(res.mode, "document_generation")
        self.assertEqual(res.complexity, "complex")
        self.assertTrue(res.escalate)

    def test_classify_complex_document_pages(self):
        """Document explicitly requesting >1 page classifies as complex."""
        query = "Create a document that is 3 pages long about system architecture"
        res = tiered_classifier.classify(query)
        self.assertEqual(res.mode, "document_generation")
        self.assertEqual(res.complexity, "complex")
        self.assertTrue(res.escalate)

    def test_classify_command_allowed(self):
        """Routine command classifies as command with allowed intent."""
        res = tiered_classifier.classify("Turn volume up")
        self.assertEqual(res.mode, "command")
        self.assertEqual(res.intent, "adjust_volume")
        self.assertFalse(res.escalate)
        self.assertIn(res.intent, ADAPTER_ALLOWED_INTENTS)


class TestLocalAdapter(unittest.TestCase):

    def test_adapter_allows_listed_intents(self):
        """Permitted intents synthesize valid action envelopes."""
        env = local_adapter.synthesize_command_envelope("adjust_volume", {"level": "+10"})
        self.assertIsNotNone(env)
        self.assertEqual(env["action"], "adjust_volume")
        self.assertEqual(env["parameter"], "+10")

    def test_adapter_refuses_unlisted_intents(self):
        """Dangerous or complex intents outside ADAPTER_ALLOWED_INTENTS are refused."""
        for intent in ("netflix_play", "calendar_delete", "repo_notes", "send_email", "write_file"):
            env = local_adapter.synthesize_command_envelope(intent, {})
            self.assertIsNone(env, f"Intent {intent} should be refused by local adapter")

    def test_author_agnostic_document_sink(self):
        """create_document_envelope produces pure take-and-format docs_control|create action."""
        title = "Grocery List"
        content = "1. Milk\n2. Eggs\n3. Bread"
        env = local_adapter.create_document_envelope(title, content)
        self.assertEqual(env["action"], "docs_control")
        self.assertIn(title, env["parameter"])
        self.assertIn(content, env["parameter"])
        self.assertTrue(env["parameter"].startswith("Grocery List|"))


class TestTieredRoutingIntegration(unittest.TestCase):

    def setUp(self):
        os.environ["AKIRA_ROUTING_MODE"] = "tiered"
        os.environ["AKIRA_DISABLE_CLAUDE"] = "false"

    def test_simple_conversation_routes_to_speech_head(self):
        """Simple conversation queries are answered directly by free speech head."""
        with patch("speech_head.generate_conversation_reply", return_value="Good morning! I am ready to help.") as mock_head:
            with patch("claude_handler.ask_akira") as mock_claude:
                resp = akira.get_akira_response("Hello Akira", raw_text="Hello Akira")
                self.assertIsNotNone(resp)
                self.assertEqual(resp.get("mode"), "conversation")
                self.assertEqual(resp.get("response"), "Good morning! I am ready to help.")
                mock_head.assert_called_once()
                mock_claude.assert_not_called()

    def test_complex_conversation_escalates_to_claude(self):
        """Complex conversation queries bypass speech head and escalate to Claude."""
        with patch("speech_head.generate_conversation_reply") as mock_head:
            with patch("claude_handler.ask_akira", return_value='{"mode": "conversation", "response": "TCP provides reliable, ordered stream delivery."}') as mock_claude:
                query = "Can you analyze the pros and cons of TCP vs UDP and explain why?"
                resp = akira.get_akira_response(query, raw_text=query)
                self.assertIsNotNone(resp)
                self.assertEqual(resp.get("mode"), "conversation")
                mock_head.assert_not_called()
                mock_claude.assert_called_once()

    def test_simple_document_routes_to_speech_head_then_adapter_sink(self):
        """Simple document drafts content with speech head and creates doc via adapter sink."""
        drafted = "Meeting Notes:\nDiscussed project roadmap and sprint velocity."
        with patch("speech_head.generate_document_content", return_value=drafted) as mock_head:
            with patch("claude_handler.ask_akira") as mock_claude:
                query = "Make a doc with quick meeting notes"
                resp = akira.get_akira_response(query, raw_text=query)
                self.assertIsNotNone(resp)
                self.assertEqual(resp.get("action"), "docs_control")
                self.assertIn(drafted, resp.get("parameter"))
                mock_head.assert_called_once()
                mock_claude.assert_not_called()

    def test_speech_head_failure_fails_open_to_claude(self):
        """If free speech head fails or times out, it falls back cleanly to Claude."""
        with patch("speech_head.generate_conversation_reply", return_value=None):
            with patch("claude_handler.ask_akira", return_value='{"mode": "conversation", "response": "Fallback answer from Claude."}') as mock_claude:
                resp = akira.get_akira_response("What is the weather?", raw_text="What is the weather?")
                self.assertIsNotNone(resp)
                self.assertEqual(resp.get("response"), "Fallback answer from Claude.")
                mock_claude.assert_called_once()

    def test_legacy_feature_flag_bypasses_tiered_routing(self):
        """When AKIRA_ROUTING_MODE=legacy, classifier is bypassed entirely."""
        os.environ["AKIRA_ROUTING_MODE"] = "legacy"
        try:
            with patch("tiered_classifier.classify") as mock_cls:
                with patch("claude_handler.ask_akira", return_value='{"mode": "conversation", "response": "Direct legacy response."}'):
                    resp = akira.get_akira_response("Volume up", raw_text="Volume up")
                    self.assertIsNotNone(resp)
                    mock_cls.assert_not_called()
        finally:
            os.environ["AKIRA_ROUTING_MODE"] = "tiered"

    def test_unified_guard_seam_applied(self):
        """Both adapter and Claude action plans pass through guard_action_envelope."""
        safe_plan = {"actions": [{"action": "adjust_volume", "parameter": "+10"}]}
        guarded, notes = akira.guard_action_envelope(safe_plan)
        self.assertFalse(guarded.get("confirmation_required", False))

        # Risky shopping/power action is caught by safety net
        risky_plan = {"actions": [{"action": "shutdown_pc", "parameter": ""}]}
        guarded_risky, notes_risky = akira.guard_action_envelope(risky_plan)
        self.assertTrue(guarded_risky.get("confirmation_required"))
        self.assertEqual(len(guarded_risky.get("pending_actions", [])), 1)

    def test_claude_kill_switch_blocks_complex_turns(self):
        """When AKIRA_DISABLE_CLAUDE=true, all complex escalations return honest off message."""
        os.environ["AKIRA_DISABLE_CLAUDE"] = "true"
        try:
            from tiered_config import CLAUDE_DISABLED_MESSAGE
            with patch("claude_handler.ask_akira") as mock_claude:
                # 1. Complex conversation
                q_conv = "Explain TCP vs UDP in technical detail with tradeoffs"
                r_conv = akira.get_akira_response(q_conv, raw_text=q_conv)
                self.assertEqual(r_conv.get("response"), CLAUDE_DISABLED_MESSAGE)

                # 2. Complex document
                q_doc = "Draft a comprehensive technical analysis comparing Redis and Memcached"
                r_doc = akira.get_akira_response(q_doc, raw_text=q_doc)
                self.assertEqual(r_doc.get("response"), CLAUDE_DISABLED_MESSAGE)

                # Zero calls to real Claude API
                mock_claude.assert_not_called()
        finally:
            os.environ["AKIRA_DISABLE_CLAUDE"] = "false"


if __name__ == "__main__":
    unittest.main()
