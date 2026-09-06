"""tests/test_live_bug_fixes.py — Dedicated reproduction tests for the 6 live testing bugs.

Tests:
- Bug 1: Guard keyword false-positives on content parameters (tab titles, searches).
- Bug 2: "Do it" / confirmation phrases recognized after an action block.
- Bug 3: switch_tab handling tab titles containing '|' and delimiter characters.
- Bug 4: open_application honest status reporting and VS Code path resolution.
- Bug 5: llm_json tolerant repair of malformed guard JSON ('[...]"}' pattern).
- Bug 6: Ambiguous tab reference prioritized from recent session action history.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import guard_rules
import executor
import llm_json
import akira
import gemini_head


class TestLiveBugFixes(unittest.TestCase):

    # ── BUG 1: Keyword screening on user-content parameters ────────────────
    def test_bug1_keyword_false_positives(self):
        """Content parameters (tab titles, search queries, video names) must NOT

        trigger risky-keyword flags for harmless words like 'report', 'delete', 'urgent'.
        """
        # 1. switch_tab with 'report' in title
        v1 = guard_rules.validate("switch_tab", "threats report issues")
        self.assertNotIn("risky keyword(s): report", "; ".join(v1.reasons))
        self.assertFalse(any("risky keyword" in r for r in v1.reasons))

        # 2. open_site_tab with 'report' in title
        v2 = guard_rules.validate("open_site_tab", "quarterly report")
        self.assertFalse(any("risky keyword" in r for r in v2.reasons))

        # 3. web_search with 'delete' in search query
        v3 = guard_rules.validate("web_search", "how to delete files")
        self.assertFalse(any("risky keyword" in r for r in v3.reasons))

        # 4. youtube_control with 'report' or 'urgent' in song/video query
        v4 = guard_rules.validate("youtube_control", "play threats report video")
        self.assertFalse(any("risky keyword" in r for r in v4.reasons))

        # 5. CONTRAST: genuine destructive command actions MUST still flag on risky keywords
        v5 = guard_rules.validate("delete_files", "report.txt")
        self.assertTrue(any("risky keyword(s): report" in r for r in v5.reasons))

        v6 = guard_rules.validate("gmail_compose", "delete|test@example.com|urgent|body")
        self.assertTrue(any("risky keyword(s): delete" in r for r in v6.reasons))

    # ── BUG 2: Confirmation phrases recognized after a block ───────────────
    def test_bug2_confirmation_after_block(self):
        """Saying 'Do it' after an action was blocked must re-attempt the exact

        blocked action and parameter, rather than routing as a new command.
        """
        # Set up a pending blocked action
        blocked_action = {"action": "switch_tab", "parameter": "Momentum Labs | Supabase"}
        akira._pending_blocked_action = dict(blocked_action)

        with patch.object(akira, "run_actions", return_value=["Switched to Momentum Labs."]) as mock_run, \
             patch.object(akira, "speak_and_wait") as mock_speak:
            # User says "Do it"
            res = akira.get_akira_response("Do it")

            # Must handle inline and return None
            self.assertIsNone(res)
            # Must have called run_actions with the EXACT blocked action
            mock_run.assert_called_once_with({"actions": [blocked_action]}, confirmed=True)
            mock_speak.assert_called_once_with("Switched to Momentum Labs.")
            # Pending blocked action must be cleared after confirmation
            self.assertIsNone(akira._pending_blocked_action)

    def test_bug2_other_confirmation_phrases(self):
        """Various natural confirmation utterances must also confirm the blocked action."""
        for phrase in ("yes", "confirm", "go ahead", "yeah do that", "proceed"):
            blocked = {"action": "open_application", "parameter": "vscode"}
            akira._pending_blocked_action = dict(blocked)

            with patch.object(akira, "run_actions", return_value=["Opening vscode."]) as mock_run, \
                 patch.object(akira, "speak_and_wait"):
                akira.get_akira_response(phrase)
                mock_run.assert_called_once_with({"actions": [blocked]}, confirmed=True)
                self.assertIsNone(akira._pending_blocked_action)

    # ── BUG 3: Pipe characters in tab titles ────────────────────────────────
    def test_bug3_pipe_in_tab_title(self):
        """switch_tab must treat titles with '|' as a single opaque parameter

        and NOT fail with 'accepts at most 1 parameter field(s), got 2'.
        """
        v = guard_rules.validate("switch_tab", "Momentum Labs | Supabase")
        # Must NOT be BLOCK (excess fields produces BLOCK)
        self.assertNotEqual(v.decision, guard_rules.BLOCK)
        self.assertFalse(any("accepts at most 1 parameter field(s)" in r for r in v.reasons))

        v_multi_pipe = guard_rules.validate("switch_tab", "App | Project | Branch | Section")
        self.assertNotEqual(v_multi_pipe.decision, guard_rules.BLOCK)
        self.assertFalse(any("parameter field" in r for r in v_multi_pipe.reasons))

    # ── BUG 4: Honest open_application status & VS Code resolution ──────────
    def test_bug4_open_application_honest_failure(self):
        """open_application must return an honest failure message when the app

        cannot be found, NEVER a false 'Done.'.
        """
        result = executor.open_application("nonexistent_app_12345")
        self.assertTrue(result.startswith("Couldn't find nonexistent_app_12345"),
                        f"Expected honest failure, got: {result!r}")
        self.assertNotEqual(result, "Done.")

    def test_bug4_vscode_resolution(self):
        """VS Code aliases ('vscode', 'vs code', 'code') must resolve to the executable

        path if installed, or be present in MANUAL_MAP.
        """
        self.assertIn("vscode", executor.MANUAL_MAP)
        self.assertIn("code", executor.MANUAL_MAP)
        self.assertEqual(executor.APP_ALIASES.get("vs code"), "vscode")
        self.assertEqual(executor.APP_ALIASES.get("visual studio code"), "vscode")
        exe = executor._find_exe("vscode")
        self.assertIsNotNone(exe)
        self.assertTrue(exe.endswith("Code.exe") or "code" in exe.lower())

    def test_bug4_common_apps_honest(self):
        """Common apps (calculator, notepad) must resolve aliases and report honestly."""
        self.assertEqual(executor.APP_ALIASES.get("calculator"), "calc")
        self.assertEqual(executor.APP_ALIASES.get("calc"), "calc")
        self.assertIn("calc", executor.MANUAL_MAP)
        self.assertIn("notepad", executor.MANUAL_MAP)

        # Nonexistent close app must report honest failure, not 'Done.'
        close_res = executor.close_application("completely_fake_running_app")
        self.assertTrue("Couldn't find" in close_res or "Couldn't close" in close_res,
                        f"Expected honest failure, got: {close_res!r}")
        self.assertNotEqual(close_res, "Done.")

    # ── BUG 5: Guard model malformed JSON repair ────────────────────────────
    def test_bug5_malformed_guard_json_repair(self):
        """llm_json must repair trailing-quote / delimiter anomalies in guard output

        such as '{"decision": "allow", "reasons": [...]"}'.
        """
        # 1. Exact observed live pattern: array closing bracket followed by stray quote before closing brace
        raw1 = '{"decision": "allow", "reasons": ["safe"]"}'
        obj1, info1 = llm_json.parse(raw1)
        self.assertIsNotNone(obj1)
        self.assertEqual(obj1.get("decision"), "allow")
        self.assertEqual(obj1.get("reasons"), ["safe"])
        self.assertTrue(info1.get("repaired"))

        # 2. Empty reasons with stray quote
        raw2 = '{"decision": "allow", "reasons": []"}'
        obj2, info2 = llm_json.parse(raw2)
        self.assertIsNotNone(obj2)
        self.assertEqual(obj2.get("decision"), "allow")
        self.assertEqual(obj2.get("reasons"), [])
        self.assertTrue(info2.get("repaired"))

        # 3. Flag decision with multiple reasons and stray quote
        raw3 = '{"decision": "flag", "reasons": ["destructive action", "power state change"]"}'
        obj3, info3 = llm_json.parse(raw3)
        self.assertIsNotNone(obj3)
        self.assertEqual(obj3.get("decision"), "flag")
        self.assertEqual(len(obj3.get("reasons")), 2)

    # ── BUG 6: Ambiguous tab reference resolution from recent history ───────
    def test_bug6_ambiguous_tab_pre_router_bypass(self):
        """Conversational tab references like 'the tab that was open before' must

        bypass the fast pre-router so the LLM receives session context.
        """
        messages = [{
            "role": "user",
            "content": (
                "[RECENT ACTIONS THIS SESSION]\n"
                "1. open_site_tab | youtube -> Playing 'Starboy' on YouTube\n\n"
                "[CURRENT BROWSER TABS]\n"
                "- Cerebras Cloud\n"
                "- YouTube - Starboy\n"
                "- Settings\n\n"
                "open the tab where it was opened before"
            )
        }]
        fast_reply = gemini_head._try_fast_pattern_route(messages)
        # Fast pre-router must return None to let full router with session context resolve it
        self.assertIsNone(fast_reply)

    def test_bug6_system_prompt_instructs_recent_tab_prioritization(self):
        """groq_sys prompt must contain explicit instructions to prioritize the tab

        most recently opened/acted upon in [RECENT ACTIONS THIS SESSION].
        """
        sys_prompt = gemini_head._route_via_groq.__doc__ or ""
        # Inspect groq_sys definition in module
        import inspect
        source = inspect.getsource(gemini_head._route_via_groq)
        self.assertIn("RECENT ACTIONS THIS SESSION", source)
        self.assertIn("Prioritize the tab most recently opened or acted upon", source)
        self.assertIn("switch_tab", source)


if __name__ == "__main__":
    unittest.main()
