"""tests/test_audio_and_tab_fixes.py
Unit tests verifying:
1. Whisper hallucination filtering ('Clear speech only', 'clear response')
2. open_site_tab tab reuse (switches to existing tab instead of opening a new one)
3. synthesize_action_reply token suppression (refusing 'unsupported_intent')
"""

import unittest
from unittest.mock import MagicMock, patch
import audio_pipeline
import executor
import claude_handler


class TestAudioAndTabFixes(unittest.TestCase):

    def test_clean_transcription_filters_prompt_hallucinations(self):
        """Whisper prompt artifacts must be cleanly rejected."""
        self.assertEqual(audio_pipeline.clean_transcription_text("Clear speech only."), "")
        self.assertEqual(audio_pipeline.clean_transcription_text("Clear speech only"), "")
        self.assertEqual(audio_pipeline.clean_transcription_text("clear response"), "")
        self.assertEqual(audio_pipeline.clean_transcription_text("clear speech"), "")
        self.assertEqual(audio_pipeline.clean_transcription_text("Thank you for watching."), "")
        
        # Genuine user speech must pass intact
        self.assertEqual(audio_pipeline.clean_transcription_text("Close Brave and open YouTube"), "Close Brave and open YouTube")
        self.assertEqual(audio_pipeline.clean_transcription_text("Can you play some music"), "Can you play some music")

    @patch("executor.get_browser")
    def test_open_site_tab_reuses_existing_tab(self, mock_get_browser):
        """open_site_tab must switch to an already-open tab matching the site rather than creating a new one."""
        mock_browser = MagicMock()
        mock_get_browser.return_value = mock_browser

        # Simulate 2 tabs: 'h1' (Google) and 'h2' (YouTube)
        mock_browser.window_handles = ["h1", "h2"]
        mock_browser.current_window_handle = "h1"

        def switch_to_window(h):
            if h == "h1":
                mock_browser.current_url = "https://www.google.com"
                mock_browser.title = "Google Search"
            elif h == "h2":
                mock_browser.current_url = "https://www.youtube.com/watch?v=123"
                mock_browser.title = "(23) XYZ Studio - YouTube"

        mock_browser.switch_to.window.side_effect = switch_to_window

        res = executor.open_site_tab("youtube.com")
        self.assertIn("Switched to existing", res)
        # Verify it switched to h2 and did NOT call Target.createTarget
        mock_browser.switch_to.window.assert_called_with("h2")
        mock_browser.execute_cdp_cmd.assert_not_called()
        self.assertEqual(mock_browser._akira_tab, "h2")
        self.assertEqual(mock_browser._youtube_target_tab, "h2")

    @patch("executor.get_browser")
    def test_open_site_tab_creates_new_if_none_open(self, mock_get_browser):
        """open_site_tab creates a new tab only when no existing tab matches the requested domain."""
        mock_browser = MagicMock()
        mock_get_browser.return_value = mock_browser

        mock_browser.window_handles = ["h1"]
        mock_browser.current_window_handle = "h1"
        mock_browser.current_url = "https://www.google.com"
        mock_browser.title = "Google Search"

        # When Target.createTarget is called, simulate handle h2 appearing
        def create_target(cmd, args):
            mock_browser.window_handles = ["h1", "h2"]
            return {"targetId": "t2"}

        mock_browser.execute_cdp_cmd.side_effect = create_target

        res = executor.open_site_tab("netflix.com")
        self.assertIn("Opened netflix.com in a new tab", res)
        mock_browser.execute_cdp_cmd.assert_called_once()

    @patch("claude_handler.servant_or_none")
    @patch("claude_handler._synthesize_on_servant")
    def test_synthesize_action_reply_discards_unsupported_intent(self, mock_synth, mock_servant):
        """If a servant returns 'unsupported_intent' token, synthesize_action_reply must discard it."""
        mock_servant.return_value = "akira-mech"
        mock_synth.return_value = "unsupported_intent"

        with patch("claude_handler.conversation_history", [{"role": "user", "content": "open youtube"}]):
            res = claude_handler.synthesize_action_reply()
            # Must return None or fall back, NEVER return 'unsupported_intent'
            self.assertNotEqual(res, "unsupported_intent")


if __name__ == "__main__":
    unittest.main()
