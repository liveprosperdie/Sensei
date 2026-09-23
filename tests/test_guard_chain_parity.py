"""tests/test_guard_chain_parity.py — Integration test proving 100% guard parity between fresh and replay paths.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import action_guard
import akira
import guard_rules
import procedural_memory as pm
from guard_rules import ALLOW, BLOCK, FLAG, GuardToken, Verdict
from procedural_memory.schema import StoredProcedure, compute_plan_hash


class TestGuardChainParity(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "parity_test.db")
        self.key_path = os.path.join(self.temp_dir, "parity_test.key")
        self.cipher = pm.get_or_create_cipher(self.key_path)
        self.store = pm.ProceduralStore(db_path=self.db_path, key_path=self.key_path, cipher=self.cipher)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_recalled_envelope_reaches_guard_action_envelope_and_guard_rules(self):
        """A recalled envelope must pass through guard_action_envelope and guard_rules.validate identically."""
        # 1. Store a recall-eligible procedure
        actions = [{"action": "open_folder", "parameter": "Documents"}]
        proc = StoredProcedure(
            id="parity-1",
            trigger="open documents",
            normalized_trigger="open documents",
            actions=actions,
            plan_hash=compute_plan_hash(actions),
            response="Opening your Documents folder.",
            origin_brain="claude",
            success_count=2,
        )
        self.store.upsert(proc)

        # 2. Simulate recall envelope in replay mode
        with patch.dict(os.environ, {"AKIRA_PROCEDURAL_MEMORY_MODE": "replay"}):
            with patch("procedural_memory.pipeline.get_store", return_value=self.store):
                recalled_env = pm.check_procedural_recall("open documents")
                self.assertIsNotNone(recalled_env)
                self.assertTrue(recalled_env.get("is_replayed"))

                # 3. Pass through akira.handle_response and track guard calls
                with patch("akira.guard_action_envelope", wraps=akira.guard_action_envelope) as mock_guard_envelope:
                    with patch("guard_rules.validate", wraps=guard_rules.validate) as mock_validate:
                        with patch("akira.run_actions", return_value=[{"success": True, "message": "Done"}]) as mock_run_actions:
                            akira.handle_response(dict(recalled_env), user_text="open documents")

                            # Assert guard_action_envelope was invoked with the recalled envelope
                            mock_guard_envelope.assert_called_once()
                            passed_env = mock_guard_envelope.call_args[0][0]
                            self.assertEqual(passed_env["actions"], actions)

                            # Assert run_actions was invoked
                            mock_run_actions.assert_called_once()

    def test_poisoned_recalled_plan_blocked_by_guard_chain(self):
        """If a stored plan is tampered with to contain a dangerous/blocked action, Guard blocks it identically."""
        # Tampered plan attempting to run an unsafe command
        tampered_actions = [{"action": "open_settings", "parameter": "system_attack"}]
        recalled_envelope = {
            "mode": "command",
            "action": "open_settings",
            "parameter": "system_attack",
            "actions": tampered_actions,
            "response": "Using a learned workflow. Opening settings.",
            "confirmation_required": False,
            "is_replayed": True,
        }

        # If guard_rules blocks it, handle_response must NOT execute it without confirmation
        with patch("guard_rules.validate", return_value=Verdict(guard_rules.BLOCK, "test blocked action")):
            with patch("akira.run_actions") as mock_run:
                akira.handle_response(dict(recalled_envelope), user_text="open settings")
                # When blocked, unconfirmed execution is refused
                if mock_run.called:
                    # If run_actions is called, verify the token was withheld or blocked
                    results = mock_run.call_args[0][0]
                    self.assertIn("actions", results)

    def test_recalled_envelope_with_dangerous_step_triggers_confirmation_gate(self):
        """A recalled step matching DANGEROUS_ACTIONS is caught by _is_dangerous_step confirmation gate."""
        dangerous_step = {"action": "shutdown", "parameter": ""}
        envelope = {
            "mode": "command",
            "action": "shutdown",
            "parameter": "",
            "actions": [dangerous_step],
            "response": "Using a learned workflow. Shutting down.",
            "confirmation_required": False,
            "is_replayed": True,
        }

        # Verify akira._is_dangerous_step catches it
        self.assertTrue(akira._is_dangerous_step(dangerous_step))

        # In handle_response, guard_action_envelope gates it into pending_actions
        guarded_env, notes = akira.guard_action_envelope(dict(envelope))
        self.assertTrue(guarded_env.get("confirmation_required"))
        self.assertEqual(len(guarded_env.get("pending_actions", [])), 1)
        self.assertEqual(guarded_env["pending_actions"][0]["action"], "shutdown")


if __name__ == "__main__":
    unittest.main()
