"""tests/test_procedural_memory.py — Comprehensive test suite for procedural memory foundation.
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

import procedural_memory as pm
from procedural_memory.store import ProceduralStore
from procedural_memory.schema import StoredProcedure, compute_plan_hash, normalize_trigger, normalize_incoming_envelope
from procedural_memory.tags import (
    get_step_tag,
    get_plan_tag,
    TAG_RECALL_ELIGIBLE,
    TAG_ALWAYS_FRESH,
    TAG_CONTENT_GENERATED,
)
from procedural_memory.scrubber import (
    validate_procedure_safety,
    is_deictic_or_relative,
    contains_credentials,
    contains_pii,
)


class TestProceduralMemoryFoundation(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_procedures.db")
        self.key_path = os.path.join(self.temp_dir, "test_procedures.key")
        self.cipher = Fernet(Fernet.generate_key())
        self.store = ProceduralStore(db_path=self.db_path, key_path=self.key_path, cipher=self.cipher)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_dpapi_key_generation_and_load(self):
        """Verify DPAPI key creation, encryption, and unwrapping."""
        cipher1 = pm.get_or_create_cipher(self.key_path)
        self.assertTrue(os.path.exists(self.key_path))
        # Loading again should unwrap the exact same key
        cipher2 = pm.get_or_create_cipher(self.key_path)
        token = cipher1.encrypt(b"secret payload")
        self.assertEqual(cipher2.decrypt(token), b"secret payload")

    def test_store_crud_and_persistence(self):
        """Verify procedures can be saved, loaded, and retrieved across instances."""
        proc = StoredProcedure(
            id="test-1",
            trigger="open downloads folder",
            normalized_trigger="open downloads folder",
            actions=[{"action": "open_folder", "parameter": "Downloads"}],
            plan_hash=compute_plan_hash([{"action": "open_folder", "parameter": "Downloads"}]),
            response="Opening your Downloads folder.",
            origin_brain="free",
            tag=TAG_RECALL_ELIGIBLE,
            success_count=1,
        )
        self.store.upsert(proc)
        self.assertEqual(self.store.count(), 1)

        # Reload store from disk
        store2 = ProceduralStore(db_path=self.db_path, key_path=self.key_path, cipher=self.cipher)
        self.assertEqual(store2.count(), 1)
        retrieved = store2.find_by_normalized_trigger("open downloads folder")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, "test-1")
        self.assertEqual(retrieved.origin_brain, "free")

    def test_corrupted_store_fails_open(self):
        """A corrupted or undecryptable store must never crash; it rotates aside and starts empty."""
        with open(self.db_path, "wb") as f:
            f.write(b"NOT_A_VALID_ENCRYPTED_BLOB_GARBAGE")

        fallback_store = ProceduralStore(db_path=self.db_path, key_path=self.key_path, cipher=self.cipher)
        self.assertEqual(fallback_store.count(), 0)
        # Verify corrupt file was rotated aside
        rotated = [f for f in os.listdir(self.temp_dir) if "corrupted" in f]
        self.assertTrue(len(rotated) >= 1)

    def test_poisoned_store_rejection(self):
        """Tampered ciphertext fails HMAC authenticated decryption and triggers safe fallback."""
        proc = StoredProcedure(
            id="poison-1",
            trigger="test trigger",
            normalized_trigger="test trigger",
            actions=[{"action": "open_settings", "parameter": ""}],
            plan_hash="hash1",
            response="done",
            origin_brain="claude",
        )
        self.store.upsert(proc)

        # Tamper with encrypted bytes
        with open(self.db_path, "rb") as f:
            data = bytearray(f.read())
        # Flip bytes in the ciphertext payload
        data[-10] ^= 0xFF
        with open(self.db_path, "wb") as f:
            f.write(data)

        # Reloading must catch HMAC failure and fall open cleanly
        poisoned_store = ProceduralStore(db_path=self.db_path, key_path=self.key_path, cipher=self.cipher)
        self.assertEqual(poisoned_store.count(), 0)

    def test_default_deny_all_action_map_entries(self):
        """Every action in executor._ACTION_MAP must have a deterministic tag under default-deny."""
        from executor import _ACTION_MAP

        self.assertGreater(len(_ACTION_MAP), 30)
        valid_tags = {TAG_RECALL_ELIGIBLE, TAG_ALWAYS_FRESH, TAG_CONTENT_GENERATED}

        for act_name in _ACTION_MAP.keys():
            tag = get_step_tag(act_name, None)
            self.assertIn(tag, valid_tags, f"Action {act_name} produced invalid tag {tag}")

    def test_section_3_corrections_tagging(self):
        """Verify actions moved in Section 3 are strictly always-fresh or content-generated."""
        # Dictated payloads
        self.assertEqual(get_step_tag("write_clipboard", "text"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("write_text", "text"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("type_text", "text"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("insert_text", "text"), TAG_ALWAYS_FRESH)

        # File operations
        self.assertEqual(get_step_tag("copy_files", "*.pdf|D:\\dest"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("compress_files", "*.txt|test.zip"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("extract_files", "test.zip"), TAG_ALWAYS_FRESH)

        # Network / Cloud / Privacy config
        self.assertEqual(get_step_tag("download_image", "url"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("file_to_doc", "file"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("manage_index_scope", "path"), TAG_ALWAYS_FRESH)

        # Shopping cart
        self.assertEqual(get_step_tag("amazon_control", "add to cart|item"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("flipkart_control", "add to cart|item"), TAG_ALWAYS_FRESH)

        # Calendar sub-actions
        self.assertEqual(get_step_tag("calendar_control", "create|event"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("calendar_control", "update|event"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("calendar_control", "delete|event"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("calendar_control", "list|today"), TAG_RECALL_ELIGIBLE)

        # State-dependent toggles & media
        self.assertEqual(get_step_tag("toggle_wifi", ""), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("toggle_bluetooth", ""), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("spotify_control", "play"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("spotify_control", "pause"), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("close_tab", ""), TAG_ALWAYS_FRESH)
        self.assertEqual(get_step_tag("switch_window", ""), TAG_ALWAYS_FRESH)

        # Content generated
        self.assertEqual(get_step_tag("summarize_file", "path.pdf"), TAG_CONTENT_GENERATED)

    def test_compound_plan_most_restrictive_wins(self):
        """If any step in a compound plan is always-fresh, entire plan is always-fresh."""
        plan_safe = [
            {"action": "open_settings", "parameter": "sound"},
            {"action": "open_folder", "parameter": "Documents"},
        ]
        self.assertEqual(get_plan_tag(plan_safe), TAG_RECALL_ELIGIBLE)

        plan_poisoned = [
            {"action": "open_settings", "parameter": "sound"},
            {"action": "write_clipboard", "parameter": "confidential notes"},
        ]
        self.assertEqual(get_plan_tag(plan_poisoned), TAG_ALWAYS_FRESH)

    def test_credential_and_token_scrubbing(self):
        """Bearer tokens, API keys, and credentials drop the procedure."""
        self.assertTrue(contains_credentials("Authorization: Bearer sk-ant-api03-1234567890abcdef"))
        self.assertTrue(contains_credentials("ghp_123456789012345678901234567890123456"))
        self.assertTrue(contains_credentials("AKIAIOSFODNN7EXAMPLE"))

        safe, reason = validate_procedure_safety(
            trigger="search for api key sk-12345678901234567890",
            actions=[{"action": "open_url", "parameter": "https://example.com"}],
        )
        self.assertFalse(safe)
        self.assertEqual(reason, "trigger_contains_credentials")

    def test_pii_scrubbing_and_drop(self):
        """Email, phone, and SSN parameters trigger procedure drop."""
        self.assertTrue(contains_pii("Contact user at john.doe@example.com"))
        self.assertTrue(contains_pii("Call 555-123-4567 now"))
        self.assertTrue(contains_pii("SSN 123-45-6789"))

        safe, reason = validate_procedure_safety(
            trigger="search user john.doe@example.com",
            actions=[{"action": "open_url", "parameter": "https://example.com"}],
        )
        self.assertFalse(safe)
        self.assertEqual(reason, "trigger_contains_pii")

    def test_deictic_and_relative_utterance_veto(self):
        """Triggers with relative words (today, tomorrow, this, that, it, etc.) are vetoed."""
        self.assertTrue(is_deictic_or_relative("what is on my calendar today"))
        self.assertTrue(is_deictic_or_relative("open the latest report"))
        self.assertTrue(is_deictic_or_relative("close this tab"))
        self.assertTrue(is_deictic_or_relative("do it again"))

        safe, reason = validate_procedure_safety(
            trigger="check calendar tomorrow",
            actions=[{"action": "calendar_control", "parameter": "list|2026-09-22"}],
        )
        self.assertFalse(safe)
        self.assertEqual(reason, "trigger_contains_deictic_or_relative_terms")

    def test_q1_success_agreement_and_divergence(self):
        """Q1: count increments only when fresh derivation matches plan; resets to 1 on divergence."""
        proc1 = StoredProcedure(
            id="q1-test",
            trigger="open system settings",
            normalized_trigger="open system settings",
            actions=[{"action": "open_settings", "parameter": "display"}],
            plan_hash=compute_plan_hash([{"action": "open_settings", "parameter": "display"}]),
            response="Opening display settings.",
            origin_brain="claude",
            success_count=1,
        )
        self.store.record_derivation(proc1)
        self.assertEqual(self.store.find_by_id("q1-test").success_count, 1)

        # Agreeing derivation -> count becomes 2 (replay eligible!)
        proc1_agree = StoredProcedure(
            id="q1-test-2",
            trigger="open system settings",
            normalized_trigger="open system settings",
            actions=[{"action": "open_settings", "parameter": "display"}],
            plan_hash=compute_plan_hash([{"action": "open_settings", "parameter": "display"}]),
            response="Opening display settings.",
            origin_brain="free",
        )
        updated = self.store.record_derivation(proc1_agree)
        self.assertEqual(updated.success_count, 2)
        self.assertTrue(updated.is_replay_eligible())

        # Divergent derivation -> replaces stored plan, resets count to 1
        proc1_diverge = StoredProcedure(
            id="q1-test-diverge",
            trigger="open system settings",
            normalized_trigger="open system settings",
            actions=[{"action": "open_settings", "parameter": "sound"}],
            plan_hash=compute_plan_hash([{"action": "open_settings", "parameter": "sound"}]),
            response="Opening sound settings.",
            origin_brain="claude",
        )
        diverged = self.store.record_derivation(proc1_diverge)
        self.assertEqual(diverged.success_count, 1)
        self.assertEqual(diverged.actions[0]["parameter"], "sound")
        self.assertFalse(diverged.is_replay_eligible())

    def test_user_correction_reversal(self):
        """User correction decrements success_count and purges on repeated error."""
        proc = StoredProcedure(
            id="corr-test",
            trigger="open tools",
            normalized_trigger="open tools",
            actions=[{"action": "open_system_tool", "parameter": "calc"}],
            plan_hash="hash_calc",
            response="Opening calculator.",
            origin_brain="free",
            success_count=2,
        )
        self.store.upsert(proc)
        self.assertTrue(self.store.find_by_id("corr-test").is_replay_eligible())

        # First correction -> demoted
        self.store.record_correction("corr-test")
        p = self.store.find_by_id("corr-test")
        self.assertEqual(p.success_count, 1)
        self.assertFalse(p.is_replay_eligible())

        # Second correction -> purged from store
        self.store.record_correction("corr-test")
        self.assertIsNone(self.store.find_by_id("corr-test"))

    def test_purge_by_path_on_new_exclusion(self):
        """When an exclusion path is added, procedures touching that path are purged."""
        proc = StoredProcedure(
            id="path-test",
            trigger="open secret financial report",
            normalized_trigger="open secret financial report",
            actions=[{"action": "open_file", "parameter": "C:\\SecretDocs\\finance.xlsx"}],
            plan_hash="hash_fin",
            response="Opening financial report.",
            origin_brain="claude",
        )
        self.store.upsert(proc)
        self.assertEqual(self.store.count(), 1)

        purged_count = self.store.purge_by_path("C:\\SecretDocs")
        self.assertEqual(purged_count, 1)
        self.assertEqual(self.store.count(), 0)

    def test_exact_matcher_interface(self):
        """ExactNormalizedMatcher performs O(1) matching with wake-word and punctuation stripping."""
        proc = StoredProcedure(
            id="match-1",
            trigger="open system task manager",
            normalized_trigger="open system task manager",
            actions=[{"action": "open_system_tool", "parameter": "taskmgr"}],
            plan_hash="hash_taskmgr",
            response="Opening Task Manager.",
            origin_brain="free",
            success_count=2,
        )
        self.store.upsert(proc)

        matcher = pm.ExactNormalizedMatcher(self.store)
        res = matcher.match("Akira, open system task manager!")
        self.assertIsNotNone(res)
        self.assertEqual(res.procedure.id, "match-1")
        self.assertEqual(res.confidence, 1.0)
        self.assertEqual(res.match_type, "exact")

        # Mismatched query returns None
        self.assertIsNone(matcher.match("open task manager please"))

    def test_envelope_normalization_parity(self):
        """Verify Free brain and Claude envelope shapes normalize to identical standard."""
        # Claude shape
        claude_env = {
            "mode": "command",
            "action": "open_folder",
            "parameter": "Downloads",
            "actions": [{"action": "open_folder", "parameter": "Downloads"}],
            "response": "Opening Downloads.",
            "confirmation_required": False,
        }
        # Free brain shape (Groq)
        free_env = {
            "mode": "command",
            "action": "open_folder",
            "parameter": "Downloads",
            "actions": [{"action": "open_folder", "parameter": "Downloads"}],
            "response": "Opening Downloads.",
            "confirmation_required": False,
        }

        norm_claude = normalize_incoming_envelope(claude_env, origin_brain="claude")
        norm_free = normalize_incoming_envelope(free_env, origin_brain="free")

        self.assertIsNotNone(norm_claude)
        self.assertIsNotNone(norm_free)
        self.assertEqual(norm_claude["actions"], norm_free["actions"])
        self.assertEqual(norm_claude["mode"], norm_free["mode"])
        self.assertEqual(norm_claude["origin_brain"], "claude")
        self.assertEqual(norm_free["origin_brain"], "free")

    def test_shadow_mode_suppresses_replay_and_logs_metrics(self):
        """In shadow mode (default), would-be hits increment telemetry counters and return None."""
        from procedural_memory.shadow import ShadowTelemetry
        stats_file = os.path.join(self.temp_dir, "shadow_stats.json")
        telemetry = ShadowTelemetry(stats_path=stats_file)

        proc = StoredProcedure(
            id="shadow-test-1",
            trigger="open network settings",
            normalized_trigger="open network settings",
            actions=[{"action": "open_settings", "parameter": "network"}],
            plan_hash="hash_net",
            response="Opening network settings.",
            origin_brain="claude",
            success_count=2,
        )
        self.store.upsert(proc)

        with patch("procedural_memory.pipeline.get_store", return_value=self.store):
            with patch("procedural_memory.pipeline.get_shadow_telemetry", return_value=telemetry):
                with patch.dict(os.environ, {"AKIRA_PROCEDURAL_MEMORY_MODE": "shadow"}):
                    # Check recall in shadow mode
                    res = pm.check_procedural_recall("open network settings")
                    # Must suppress replay
                    self.assertIsNone(res)

                    # Telemetry must record would-be hit and token/latency savings
                    summary = telemetry.get_summary()
                    self.assertEqual(summary["would_be_hits"], 1)
                    self.assertGreater(summary["estimated_tokens_saved"], 0)
                    self.assertGreater(summary["estimated_latency_saved_ms"], 0.0)
                    self.assertEqual(summary["brain_counts"]["claude"], 1)

    def test_deferred_turn_accounting_and_correction_cancellation(self):
        """Turn N stages plan; Turn N+1 commits if no correction, or cancels if user corrects."""
        from procedural_memory.shadow import ShadowTelemetry
        telemetry = ShadowTelemetry(stats_path=os.path.join(self.temp_dir, "shadow_stats.json"))

        with patch("procedural_memory.pipeline.get_store", return_value=self.store):
            with patch("procedural_memory.pipeline.get_shadow_telemetry", return_value=telemetry):
                # Turn N: stage a successful derivation
                fresh_env = {
                    "mode": "command",
                    "action": "open_settings",
                    "parameter": "sound",
                    "actions": [{"action": "open_settings", "parameter": "sound"}],
                    "response": "Opening sound settings.",
                    "confirmation_required": False,
                }
                pm.stage_pending_derivation(
                    user_text="open sound settings",
                    envelope=fresh_env,
                    origin_brain="claude",
                )

                # Case A: User issues a correction on Turn N+1 -> staged plan cancelled!
                pm.resolve_deferred_accounting("no, not that")
                self.assertEqual(self.store.count(), 0)

                # Turn N again: stage fresh derivation
                pm.stage_pending_derivation(
                    user_text="open sound settings",
                    envelope=fresh_env,
                    origin_brain="claude",
                )

                # Case B: User speaks regular next turn -> staged plan committed!
                pm.resolve_deferred_accounting("what is the weather today")
                self.assertEqual(self.store.count(), 1)
                stored = self.store.find_by_normalized_trigger("open sound settings")
                self.assertIsNotNone(stored)
                self.assertEqual(stored.success_count, 1)


if __name__ == "__main__":
    unittest.main()
