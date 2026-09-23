"""tests/test_session_context_cache.py — Unit tests for SessionContextCache and context diffing."""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session_context_cache import DesktopState, SessionContextCache


class TestSessionContextCache(unittest.TestCase):

    def setUp(self):
        self.cache = SessionContextCache()
        self.session_id = "test_session_123"
        self.cache.start_session(self.session_id)

    def test_turn1_returns_full_context(self):
        """Turn 1 must always format and return the full desktop state."""
        mock_ctx = {
            "foreground_app": "Google Chrome",
            "open_windows": ["Chrome", "VS Code"],
            "current_url": "https://www.youtube.com",
            "current_page_title": "YouTube",
        }
        mock_tabs = [
            {"title": "YouTube - Starboy", "url": "https://www.youtube.com/watch?v=123"},
            {"title": "GitHub - Sensei", "url": "https://github.com/liveprosperdie/Sensei"},
        ]

        ctx_str = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=1,
            get_pc_context_fn=lambda: mock_ctx,
            get_all_tabs_fn=lambda: mock_tabs,
            action_lines=["1. open_application | chrome"],
        )

        self.assertIn("[SESSION START]", ctx_str)
        self.assertIn("[DESKTOP ENVIRONMENT]", ctx_str)
        self.assertIn("Running Applications:", ctx_str)
        self.assertIn("Active Browser Tabs:", ctx_str)
        self.assertIn("[RECENT ACTIONS THIS SESSION]", ctx_str)

    def test_turn2_returns_minimal_delta_on_window_change(self):
        """Turn 2 must compute and return only the changed fields (e.g. active window switch)."""
        # Turn 1 baseline
        mock_ctx_1 = {
            "foreground_app": "Google Chrome",
            "open_windows": ["Chrome", "VS Code"],
            "current_url": "https://www.google.com",
        }
        mock_tabs_1 = [{"title": "Google", "url": "https://www.google.com"}]

        _ = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=1,
            get_pc_context_fn=lambda: mock_ctx_1,
            get_all_tabs_fn=lambda: mock_tabs_1,
        )

        # Turn 2: User switches to Spotify (foreground app and active window changed)
        mock_ctx_2 = {
            "foreground_app": "Spotify",
            "open_windows": ["Spotify", "Chrome", "VS Code"],
            "current_url": "https://www.google.com",
        }

        turn2_str = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=2,
            get_pc_context_fn=lambda: mock_ctx_2,
            get_all_tabs_fn=lambda: mock_tabs_1,
        )

        # Full context headers must NOT be present
        self.assertNotIn("[SESSION START]", turn2_str)
        self.assertNotIn("[CURRENT BROWSER TABS]", turn2_str)
        self.assertNotIn("[PC STATE]", turn2_str)

        # Delta must be present inside <untrusted_external_context>
        self.assertIn("<untrusted_external_context>", turn2_str)
        self.assertIn("[CONTEXT DELTA]", turn2_str)

        # Parse the JSON delta
        lines = turn2_str.splitlines()
        delta_line = [l for l in lines if l.strip().startswith("{")][0]
        delta_obj = json.loads(delta_line)

        self.assertTrue(delta_obj.get("changed"))
        self.assertTrue(delta_obj.get("foreground_app_changed"))
        self.assertEqual(delta_obj.get("new_foreground_app"), "Spotify")
        self.assertTrue(delta_obj.get("active_window_changed"))
        self.assertEqual(delta_obj.get("new_window"), "Spotify")
        self.assertIn("Spotify", delta_obj.get("opened_windows", []))
        # Tabs did not change
        self.assertNotIn("tabs_changed", delta_obj)

    def test_turn_with_no_changes_returns_changed_false(self):
        """When desktop state is identical between turns, delta reports changed: false."""
        mock_ctx = {"foreground_app": "Chrome", "open_windows": ["Chrome"]}
        mock_tabs = [{"title": "Docs", "url": "https://docs.google.com"}]

        _ = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=1,
            get_pc_context_fn=lambda: mock_ctx,
            get_all_tabs_fn=lambda: mock_tabs,
        )

        turn2_str = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=2,
            get_pc_context_fn=lambda: mock_ctx,
            get_all_tabs_fn=lambda: mock_tabs,
        )

        self.assertIn("[CONTEXT DELTA]", turn2_str)
        lines = turn2_str.splitlines()
        delta_line = [l for l in lines if l.strip().startswith("{")][0]
        delta_obj = json.loads(delta_line)
        self.assertEqual(delta_obj, {"changed": False})

    def test_tab_delta_opened_and_closed(self):
        """Detects newly opened and closed tabs correctly in delta."""
        tabs_turn1 = [
            {"title": "Tab A", "url": "http://a.com"},
            {"title": "Tab B", "url": "http://b.com"},
        ]
        tabs_turn2 = [
            {"title": "Tab B", "url": "http://b.com"},
            {"title": "Tab C", "url": "http://c.com"},
        ]
        mock_ctx = {"foreground_app": "Chrome", "open_windows": ["Chrome"]}

        _ = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=1,
            get_pc_context_fn=lambda: mock_ctx,
            get_all_tabs_fn=lambda: tabs_turn1,
        )

        turn2_str = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=2,
            get_pc_context_fn=lambda: mock_ctx,
            get_all_tabs_fn=lambda: tabs_turn2,
        )

        lines = turn2_str.splitlines()
        delta_line = [l for l in lines if l.strip().startswith("{")][0]
        delta_obj = json.loads(delta_line)

        self.assertTrue(delta_obj.get("tabs_changed"))
        self.assertEqual(delta_obj.get("opened_tabs"), ["Tab C"])
        self.assertEqual(delta_obj.get("closed_tabs"), ["Tab A"])

    def test_corruption_fallback_to_full_context(self):
        """Hard cap: If diff computation fails or state is corrupted, fall back to full context and reset cache."""
        mock_ctx = {"foreground_app": "Chrome", "open_windows": ["Chrome"]}
        mock_tabs = [{"title": "Tab A", "url": "http://a.com"}]

        _ = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=1,
            get_pc_context_fn=lambda: mock_ctx,
            get_all_tabs_fn=lambda: mock_tabs,
        )

        # Force compute_delta to raise an exception simulating corrupted state
        with patch.object(self.cache, "compute_delta", side_effect=ValueError("Corrupted delta state")):
            fallback_str = self.cache.get_context_for_turn(
                session_id=self.session_id,
                turn_index=2,
                get_pc_context_fn=lambda: mock_ctx,
                get_all_tabs_fn=lambda: mock_tabs,
            )

        # Must fall back to sending full context
        self.assertIn("[SESSION START]", fallback_str)
        self.assertIn("[DESKTOP ENVIRONMENT]", fallback_str)
        self.assertNotIn("[CONTEXT DELTA]", fallback_str)

    def test_session_reset(self):
        """Starting a new session resets turn index and previous cache."""
        mock_ctx = {"foreground_app": "Chrome", "open_windows": ["Chrome"]}
        mock_tabs = [{"title": "Tab A", "url": "http://a.com"}]

        _ = self.cache.get_context_for_turn(
            session_id="session_1",
            turn_index=1,
            get_pc_context_fn=lambda: mock_ctx,
            get_all_tabs_fn=lambda: mock_tabs,
        )
        self.assertEqual(self.cache.turn_index, 1)

        # Start session 2
        self.cache.start_session("session_2")
        self.assertEqual(self.cache.turn_index, 0)
        self.assertIsNone(self.cache._cached_state)
        self.assertEqual(self.cache.session_id, "session_2")

    def test_reorder_does_not_produce_opened_or_closed_delta(self):
        """Reordering tabs or background windows must NEVER produce opened_tabs or closed_tabs."""
        tabs_turn1 = [
            {"title": "Tab A", "url": "http://a.com"},
            {"title": "Tab B", "url": "http://b.com"},
            {"title": "Tab C", "url": "http://c.com"},
        ]
        # Same tabs, reordered
        tabs_turn2 = [
            {"title": "Tab B", "url": "http://b.com"},
            {"title": "Tab C", "url": "http://c.com"},
            {"title": "Tab A", "url": "http://a.com"},
        ]
        ctx_turn1 = {"foreground_app": "Chrome", "open_windows": ["Chrome", "Window 2", "Window 3"]}
        # Background windows reordered, foreground stays Chrome
        ctx_turn2 = {"foreground_app": "Chrome", "open_windows": ["Chrome", "Window 3", "Window 2"]}

        _ = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=1,
            get_pc_context_fn=lambda: ctx_turn1,
            get_all_tabs_fn=lambda: tabs_turn1,
        )

        turn2_str = self.cache.get_context_for_turn(
            session_id=self.session_id,
            turn_index=2,
            get_pc_context_fn=lambda: ctx_turn2,
            get_all_tabs_fn=lambda: tabs_turn2,
        )

        lines = turn2_str.splitlines()
        delta_line = [l for l in lines if l.strip().startswith("{")][0]
        delta_obj = json.loads(delta_line)

        # Must not report tabs_changed, opened_tabs, or closed_tabs
        self.assertNotIn("tabs_changed", delta_obj)
        self.assertNotIn("opened_tabs", delta_obj)
        self.assertNotIn("closed_tabs", delta_obj)
        # Must not report opened_windows or closed_windows or active_window_changed
        self.assertNotIn("opened_windows", delta_obj)
        self.assertNotIn("closed_windows", delta_obj)
        self.assertNotIn("active_window_changed", delta_obj)
        # Active tab was Tab A, now Tab B
        self.assertEqual(delta_obj.get("active_tab"), "Tab B")


if __name__ == "__main__":
    unittest.main()
