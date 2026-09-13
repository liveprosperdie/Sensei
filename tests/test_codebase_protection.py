"""
Tests for Akira codebase protection guardrails.
Verifies that any tool or operation targeting Akira's own repository / source files is blocked.
"""

import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import security_guard
import executor

class TestCodebaseProtection(unittest.TestCase):
    def setUp(self):
        self.codebase_root = security_guard.get_codebase_root()

    def test_is_codebase_path_root_and_files(self):
        # Codebase root itself
        self.assertTrue(security_guard.is_codebase_path(self.codebase_root))
        
        # Files inside codebase
        akira_py = os.path.join(self.codebase_root, "akira.py")
        self.assertTrue(security_guard.is_codebase_path(akira_py))
        
        # Subdirectories inside codebase
        tests_dir = os.path.join(self.codebase_root, "tests")
        self.assertTrue(security_guard.is_codebase_path(tests_dir))
        
        # File inside subdirectory
        test_file = os.path.join(self.codebase_root, "tests", "test_app_open.py")
        self.assertTrue(security_guard.is_codebase_path(test_file))

    def test_is_codebase_path_traversal_and_case(self):
        # Path traversal
        traversal = os.path.join(self.codebase_root, "tests", "..", "akira.py")
        self.assertTrue(security_guard.is_codebase_path(traversal))
        
        # Case insensitivity (Windows)
        cased = self.codebase_root.lower()
        self.assertTrue(security_guard.is_codebase_path(cased))
        
        cased_file = os.path.join(self.codebase_root.upper(), "AKIRA.PY")
        self.assertTrue(security_guard.is_codebase_path(cased_file))

    def test_is_codebase_path_outside_files(self):
        # Temp dir outside codebase
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, "some_unrelated_file.txt")
        self.assertFalse(security_guard.is_codebase_path(temp_file))
        self.assertFalse(security_guard.is_codebase_path(""))
        self.assertFalse(security_guard.is_codebase_path(None))

    def test_assert_not_codebase_path_raises(self):
        akira_py = os.path.join(self.codebase_root, "akira.py")
        with self.assertRaises(ValueError) as ctx:
            security_guard.assert_not_codebase_path(akira_py, "modify")
        self.assertIn("strictly prohibited", str(ctx.exception).lower())

        # Outside path should not raise
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, "safe.txt")
        security_guard.assert_not_codebase_path(temp_file, "modify")

    def test_executor_file_functions_block_codebase(self):
        akira_py = os.path.join(self.codebase_root, "akira.py")
        
        # create_file targeting codebase
        res = executor.create_file(f"{akira_py}|malicious code")
        self.assertFalse(res.get("success", False))
        msg = res.get("message", "").lower()
        self.assertTrue("prohibited" in msg or "not permitted" in msg)
        
        # delete_files targeting codebase
        res = executor.delete_files(akira_py)
        self.assertFalse(res.get("success", False))
        msg = res.get("message", "").lower()
        self.assertTrue("prohibited" in msg or "not permitted" in msg)

        # organize_folder targeting codebase root
        res = executor.organize_folder(self.codebase_root)
        self.assertFalse(res.get("success", False))
        msg = res.get("message", "").lower()
        self.assertTrue("prohibited" in msg or "not permitted" in msg)

    def test_executor_execute_action_blocks_codebase(self):
        akira_py = os.path.join(self.codebase_root, "akira.py")

        # execute with create_file
        res = executor.execute("create_file", f"{akira_py}|overwrite")
        if isinstance(res, dict):
            self.assertFalse(res.get("success", False))
            msg = res.get("message", "").lower()
        else:
            msg = str(res).lower()
        self.assertTrue("prohibited" in msg or "not permitted" in msg)

        # execute with delete_files
        res = executor.execute("delete_files", akira_py)
        if isinstance(res, dict):
            self.assertFalse(res.get("success", False))
            msg = res.get("message", "").lower()
        else:
            msg = str(res).lower()
        self.assertTrue("prohibited" in msg or "not permitted" in msg)

        # execute with organize_folder
        res = executor.execute("organize_folder", self.codebase_root)
        if isinstance(res, dict):
            self.assertFalse(res.get("success", False))
            msg = res.get("message", "").lower()
        else:
            msg = str(res).lower()
        self.assertTrue("prohibited" in msg or "not permitted" in msg)

    def test_destructive_command_checks(self):
        akira_py = os.path.join(self.codebase_root, "akira.py")

        # check_destructive_command on delete_files
        blocked, reason = security_guard.check_destructive_command("delete_files", akira_py)
        self.assertTrue(blocked)
        self.assertIn("prohibited", reason.lower())

        # check_self_modification
        blocked, reason = security_guard.check_self_modification(akira_py)
        self.assertTrue(blocked)
        self.assertIn("not permitted", reason.lower())

        # check rm -rf / git clone commands targeting codebase or bash
        blocked, reason = security_guard.check_destructive_command("run_command", "rm -rf " + self.codebase_root)
        self.assertTrue(blocked)

if __name__ == "__main__":
    unittest.main()
