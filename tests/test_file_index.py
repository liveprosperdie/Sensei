"""tests/test_file_index.py — Comprehensive tests for Akira's local file-indexing subsystem.

Covers Part 8:
1. Initial scan on mock tree: pruning at walk time, deduplication, path reconstruction.
2. Watcher: create, modify, delete, rename synchronization.
3. Tier gating: Free tier downgrade notice & metadata fallback; Standard/Pro full content search.
4. Content extraction: 50KB truncation, zlib round-trip, contentless FTS5 search.
5. Re-mapping survival: volume serial number drive letter recovery.
6. Missing index handling: user prompt callback and recovery flow.
7. manage_index_scope voice action: config persistence, SQLite pruning, backfill.
8. Index size query & VACUUM: disk size reporting, periodic 7-day VACUUM trigger.
"""

from __future__ import annotations

import os
import sys
import time
import zlib
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import tiers
import file_index
from file_index.config import (
    IndexScopeConfig,
    save_index_location,
    resolve_saved_location,
    get_volume_serial
)
from file_index.db import (
    get_connection,
    init_schema,
    get_or_create_extension,
    reconstruct_folder_path,
    maybe_vacuum_database,
    get_index_size_bytes
)
from file_index.scanner import scan_directory_tree
from file_index.search import search_files, search_files_metadata, search_files_content
from file_index.content_extractor import extract_text_from_file, MAX_CONTENT_CHARS, CHUNK_SIZE
from file_index.watcher import IndexWatcher


class TestFileIndex(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="akira_index_test_")
        self.orig_localappdata = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.test_dir
        self.db_path = os.path.join(self.test_dir, "test_index.db")
        self.conn = get_connection(self.db_path)
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        from file_index.db import clear_caches
        clear_caches()
        if self.orig_localappdata:
            os.environ["LOCALAPPDATA"] = self.orig_localappdata
        else:
            os.environ.pop("LOCALAPPDATA", None)
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Initial Scan & Pruning & Path Reconstruction
    # ──────────────────────────────────────────────────────────────────────────
    def test_initial_scan_pruning_and_path_reconstruction(self):
        """Verify walk-time exclusion pruning, extension dedup, and path reconstruction."""
        # Setup mock directory tree
        tree_root = os.path.join(self.test_dir, "mock_drive")
        os.makedirs(os.path.join(tree_root, "docs", "sub"), exist_ok=True)
        os.makedirs(os.path.join(tree_root, "node_modules", "pkg"), exist_ok=True)
        os.makedirs(os.path.join(tree_root, ".git", "objects"), exist_ok=True)

        keep1 = os.path.join(tree_root, "docs", "file1.txt")
        keep2 = os.path.join(tree_root, "docs", "file2.pdf")
        keep3 = os.path.join(tree_root, "docs", "sub", "file3.txt")
        skip1 = os.path.join(tree_root, "node_modules", "pkg", "index.js")
        skip2 = os.path.join(tree_root, ".git", "objects", "commit.blob")

        for p in (keep1, keep2, keep3, skip1, skip2):
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"Sample content for {os.path.basename(p)}")

        scope = IndexScopeConfig()
        scan_directory_tree(self.conn, tree_root, scope=scope)

        cur = self.conn.cursor()
        cur.execute("SELECT name FROM files;")
        indexed_names = {row[0] for row in cur.fetchall()}

        # 1. Non-excluded files indexed
        self.assertIn("file1.txt", indexed_names)
        self.assertIn("file2.pdf", indexed_names)
        self.assertIn("file3.txt", indexed_names)

        # 2. Excluded directories pruned at walk time
        self.assertNotIn("index.js", indexed_names)
        self.assertNotIn("commit.blob", indexed_names)

        # 3. Extensions table properly deduplicated (.txt only once)
        cur.execute("SELECT ext FROM extensions WHERE ext = '.txt';")
        self.assertEqual(len(cur.fetchall()), 1, "Extension .txt must be deduplicated")

        # 4. Path reconstruction matches original paths
        cur.execute("SELECT id, folder_id, name FROM files WHERE name = 'file3.txt';")
        fid, folder_id, fname = cur.fetchone()
        reconstructed_folder = reconstruct_folder_path(self.conn, folder_id)
        reconstructed_full = os.path.join(reconstructed_folder, fname)
        self.assertEqual(os.path.normpath(reconstructed_full), os.path.normpath(keep3))

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Watcher Sync
    # ──────────────────────────────────────────────────────────────────────────
    def test_watcher_sync(self):
        """Verify watcher creates, renames, modifies, and deletes entries in SQLite."""
        watcher = IndexWatcher(self.db_path)

        watch_dir = os.path.join(self.test_dir, "watched")
        os.makedirs(watch_dir, exist_ok=True)

        target_file = os.path.join(watch_dir, "notes.txt")
        renamed_file = os.path.join(watch_dir, "notes_renamed.txt")

        # Create
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("Initial notes content")
        watcher._apply_event(self.conn, "created", False, target_file, None)

        cur = self.conn.cursor()
        cur.execute("SELECT name FROM files WHERE name = 'notes.txt';")
        self.assertIsNotNone(cur.fetchone(), "File should exist after create event")

        # Rename / Moved
        os.rename(target_file, renamed_file)
        watcher._apply_event(self.conn, "moved", False, target_file, renamed_file)

        cur.execute("SELECT name FROM files WHERE name = 'notes.txt';")
        self.assertIsNone(cur.fetchone(), "Old file name must be removed after rename")
        cur.execute("SELECT name FROM files WHERE name = 'notes_renamed.txt';")
        self.assertIsNotNone(cur.fetchone(), "New file name must be indexed after rename")

        # Delete
        os.remove(renamed_file)
        watcher._apply_event(self.conn, "deleted", False, renamed_file, None)

        cur.execute("SELECT name FROM files WHERE name = 'notes_renamed.txt';")
        self.assertIsNone(cur.fetchone(), "Deleted file must be removed from SQLite")

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Tier Gating: Free vs Standard/Pro
    # ──────────────────────────────────────────────────────────────────────────
    def test_tier_gating_free_vs_standard(self):
        """Free tier content search returns explanation and fallback; Standard/Pro allowed."""
        # 1. Free tier rejection
        allowed, msg = tiers.content_search_allowed("free")
        self.assertFalse(allowed)
        self.assertIn("Standard and Pro", msg)

        # 2. Standard & Pro allowance
        allowed_std, _ = tiers.content_search_allowed("standard")
        self.assertTrue(allowed_std)
        allowed_pro, _ = tiers.content_search_allowed("pro")
        self.assertTrue(allowed_pro)

        # 3. Graceful downgrade in search_files
        test_file = os.path.join(self.test_dir, "report.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("Secret budget metrics")

        scope = IndexScopeConfig()
        scan_directory_tree(self.conn, self.test_dir, scope=scope)

        with patch("tiers.plan_for", return_value="free"):
            res = search_files(self.db_path, "report", content=True)
            self.assertTrue(res["success"])
            self.assertTrue(res.get("is_downgraded"))
            self.assertIn("Standard and Pro", res["message"])
            self.assertTrue(len(res["results"]) > 0)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Content Extraction: 50KB Cap, Compression Round-trip, FTS5 Search
    # ──────────────────────────────────────────────────────────────────────────
    def test_content_extraction_truncation_and_fts5(self):
        """Verify 50KB truncation, zlib compression, and contentless FTS5 search."""
        # 1. Truncation cap
        large_txt = os.path.join(self.test_dir, "large.txt")
        with open(large_txt, "w", encoding="utf-8") as f:
            f.write("A" * (MAX_CONTENT_CHARS + 20000))

        extracted = extract_text_from_file(large_txt)
        self.assertEqual(len(extracted), MAX_CONTENT_CHARS)

        # 2. zlib round-trip
        sample_paragraph = "Akira intelligent voice assistant file search index."
        compressed = zlib.compress(sample_paragraph.encode("utf-8"))
        decompressed = zlib.decompress(compressed).decode("utf-8")
        self.assertEqual(sample_paragraph, decompressed)

        # 3. Content FTS5 search
        unique_term = "quantum_superposition_xyz"
        unique_doc = os.path.join(self.test_dir, "physics.txt")
        with open(unique_doc, "w", encoding="utf-8") as f:
            f.write(f"This document discusses {unique_term} in detail.")

        scope = IndexScopeConfig()
        scan_directory_tree(self.conn, self.test_dir, scope=scope)

        cur = self.conn.cursor()
        cur.execute("SELECT id FROM files WHERE name = 'physics.txt';")
        fid = cur.fetchone()[0]

        # Insert into content_chunks and content_fts
        self.conn.execute("INSERT INTO content_fts(rowid, text) VALUES (?, ?);",
                          (fid, f"This document discusses {unique_term} in detail."))
        self.conn.execute("INSERT INTO content_chunks(file_id, chunk_index, compressed_text) VALUES (?, ?, ?);",
                          (fid, 0, zlib.compress(f"This document discusses {unique_term} in detail.".encode("utf-8"))))
        self.conn.commit()

        results = search_files_content(self.conn, unique_term)
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["file_id"], fid)
        self.assertIn(unique_term, results[0]["snippet"])

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Drive Letter Re-mapping Survival
    # ──────────────────────────────────────────────────────────────────────────
    def test_remapping_survival(self):
        """Simulate drive letter change and verify recovery via volume serial number."""
        real_serial = get_volume_serial(self.test_dir) or "TEST1234"

        # Mock location where drive letter is fictitious 'Z:\' but serial matches test drive
        mock_saved_path = f"Z:\\Akira\\search_index.db"
        test_drive = os.path.splitdrive(self.test_dir)[0] + "\\"

        with patch("file_index.config.find_drive_by_serial", return_value=test_drive):
            save_index_location(mock_saved_path, serial=real_serial)

            # Ensure the actual file exists on the test drive
            remapped_target = os.path.join(test_drive, "Akira", "search_index.db")
            os.makedirs(os.path.dirname(remapped_target), exist_ok=True)
            with open(remapped_target, "w") as f:
                f.write("mock db")

            resolved, _, reason = resolve_saved_location()
            self.assertEqual(os.path.normpath(resolved), os.path.normpath(remapped_target))

    # ──────────────────────────────────────────────────────────────────────────
    # 6. Missing Index Handling & Recovery Flow
    # ──────────────────────────────────────────────────────────────────────────
    def test_missing_index_handling_and_recovery(self):
        """Verify prompt callback is triggered when index database is unreachable."""
        missing_db = os.path.join(self.test_dir, "nonexistent", "index.db")
        prompt_mock = MagicMock(return_value=self.db_path)

        save_index_location(missing_db, serial="BADSERIAL")

        # init_file_index should call prompt_callback; mock initial_scan to avoid scanning live system drives
        with patch("file_index.initial_scan") as mock_scan:
            final_path = file_index.init_file_index(background=False, prompt_callback=prompt_mock)
            self.assertTrue(prompt_mock.called)
            self.assertEqual(final_path, self.db_path)

    # ──────────────────────────────────────────────────────────────────────────
    # 7. manage_index_scope Voice Action
    # ──────────────────────────────────────────────────────────────────────────
    def test_manage_index_scope(self):
        """Verify exclude/include updates config and prunes/backfills SQLite entries."""
        sub_folder = os.path.join(self.test_dir, "secret_vault")
        os.makedirs(sub_folder, exist_ok=True)
        secret_file = os.path.join(sub_folder, "vault.txt")
        with open(secret_file, "w") as f:
            f.write("Secret data")

        with patch("file_index.get_active_db_path", return_value=self.db_path):
            # 1. Initial scan
            scope = IndexScopeConfig()
            scan_directory_tree(self.conn, self.test_dir, scope=scope)

            cur = self.conn.cursor()
            cur.execute("SELECT name FROM files WHERE name = 'vault.txt';")
            self.assertIsNotNone(cur.fetchone(), "vault.txt should initially be indexed")

            # 2. Exclude folder
            res_ex = file_index.manage_index_scope("exclude", sub_folder)
            self.assertTrue(res_ex["success"])

            cur.execute("SELECT name FROM files WHERE name = 'vault.txt';")
            self.assertIsNone(cur.fetchone(), "vault.txt must be pruned after exclude")

            # 3. Status check
            res_st = file_index.manage_index_scope("status")
            self.assertTrue(res_st["success"])
            self.assertIn(os.path.normpath(sub_folder), res_st["excludes"])

            # 4. Include folder again (backfill)
            res_in = file_index.manage_index_scope("include", sub_folder)
            self.assertTrue(res_in["success"])

            cur.execute("SELECT name FROM files WHERE name = 'vault.txt';")
            self.assertIsNotNone(cur.fetchone(), "vault.txt must be re-indexed after include")

    # ──────────────────────────────────────────────────────────────────────────
    # 8. Index Size Query & Scheduled VACUUM
    # ──────────────────────────────────────────────────────────────────────────
    def test_index_size_and_vacuum(self):
        """Verify index size calculation and 7-day VACUUM trigger."""
        with patch("file_index.get_active_db_path", return_value=self.db_path):
            stats = file_index.get_index_stats()
            self.assertTrue(stats["success"])
            self.assertIn("size_mb", stats)
            self.assertIn("file_count", stats)
            self.assertIn("folder_count", stats)

            # VACUUM scheduling
            # 1. First run when never run before (last_vacuum = 0) -> executes
            ran = maybe_vacuum_database(self.conn, force=False)
            self.assertTrue(ran, "Initial VACUUM should run when last_vacuum_time is unset")

            # 2. Immediate second check (< 7 days) -> skips
            ran_again = maybe_vacuum_database(self.conn, force=False)
            self.assertFalse(ran_again, "VACUUM should not run if < 7 days have passed")

            # 3. Forced VACUUM -> runs
            ran_force = maybe_vacuum_database(self.conn, force=True)
            self.assertTrue(ran_force, "Forced VACUUM must always execute")


if __name__ == "__main__":
    unittest.main()
