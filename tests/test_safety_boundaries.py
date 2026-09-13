"""
Comprehensive automated tests for Akira's hard safety boundaries:
1. Codebase self-modification deny (realpath resolution, relative path traversal, case normalization)
2. Destructive OS commands deny (recursive deletes, disk format, registry edit, critical processes, shell command injection)
3. Honest AI disclosure (prompt instructions, honest direct acknowledgment)
"""

import os
import sys
import unittest
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import security_guard
import guard_rules
from guard_rules import Verdict, BLOCK, ALLOW, FLAG
import executor
import claude_handler
import speech_head


class TestSafetyBoundaries(unittest.TestCase):
    def setUp(self):
        self.codebase_root = security_guard.get_codebase_root()

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Codebase Self-Modification Deny
    # ──────────────────────────────────────────────────────────────────────────

    def test_codebase_path_detection(self):
        # Codebase root
        self.assertTrue(security_guard.is_codebase_path(self.codebase_root))
        
        # Files and subdirectories
        self.assertTrue(security_guard.is_codebase_path(os.path.join(self.codebase_root, "akira.py")))
        self.assertTrue(security_guard.is_codebase_path(os.path.join(self.codebase_root, "executor.py")))
        self.assertTrue(security_guard.is_codebase_path(os.path.join(self.codebase_root, "file_index", "config.py")))
        
        # Relative path traversal
        self.assertTrue(security_guard.is_codebase_path("./akira.py"))
        self.assertTrue(security_guard.is_codebase_path("akira.py"))
        self.assertTrue(security_guard.is_codebase_path(os.path.join(self.codebase_root, "tests", "..", "akira.py")))

        # Case variations (Windows filesystem case-insensitivity)
        self.assertTrue(security_guard.is_codebase_path(self.codebase_root.upper()))
        self.assertTrue(security_guard.is_codebase_path(os.path.join(self.codebase_root.upper(), "AKIRA.PY")))

        # Paths outside codebase should be allowed
        temp_file = os.path.join(tempfile.gettempdir(), "test_outside.txt")
        self.assertFalse(security_guard.is_codebase_path(temp_file))

    def test_guard_rules_blocks_codebase_self_modification(self):
        akira_py = os.path.join(self.codebase_root, "akira.py")

        for act in ("create_file", "write_file", "edit_file", "delete_files", "copy_files", "move_files", "organize_folder"):
            v = guard_rules.validate(act, f"{akira_py}|some content")
            self.assertEqual(v.decision, BLOCK, f"Action {act} on akira.py was not blocked by guard_rules!")
            self.assertTrue(any("codebase" in r.lower() or "self-modification" in r.lower() for r in v.reasons),
                            f"Reasons for {act} did not mention codebase or self-modification: {v.reasons}")

    def test_executor_refuses_codebase_modifications(self):
        akira_py = os.path.join(self.codebase_root, "akira.py")

        # create_file
        res = executor.create_file(f"{akira_py}|malicious code")
        self.assertFalse(res.get("success", False))

        # write_file
        res = executor.write_file(f"{akira_py}|malicious overwrite")
        self.assertFalse(res.get("success", False))

        # edit_file
        res = executor.edit_file(f"{akira_py}|old text|new text")
        self.assertFalse(res.get("success", False))

        # delete_files
        res = executor.delete_files(akira_py)
        self.assertFalse(res.get("success", False))

        # organize_folder
        res = executor.organize_folder(self.codebase_root)
        self.assertFalse(res.get("success", False))

        # github_control clone repo into codebase root
        res = executor.github_control(f"clone repo|https://github.com/test/repo|{self.codebase_root}")
        self.assertFalse(res.get("success", False))

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Destructive OS Commands Deny
    # ──────────────────────────────────────────────────────────────────────────

    def test_destructive_commands_denylist(self):
        # Recursive / force deletion
        blocked, _ = security_guard.check_destructive_command("run_command", "rm -rf /")
        self.assertTrue(blocked)
        blocked, _ = security_guard.check_destructive_command("run_command", "del /s /f C:\\Windows")
        self.assertTrue(blocked)
        blocked, _ = security_guard.check_destructive_command("run_command", "Remove-Item -Recurse -Force C:\\")
        self.assertTrue(blocked)

        # Disk format / partitioning
        blocked, _ = security_guard.check_destructive_command("run_command", "format C: /fs:NTFS")
        self.assertTrue(blocked)
        blocked, _ = security_guard.check_destructive_command("run_command", "diskpart")
        self.assertTrue(blocked)

        # Registry manipulation
        blocked, _ = security_guard.check_destructive_command("run_command", "reg delete HKLM\\Software")
        self.assertTrue(blocked)

        # Shell command execution via open_application
        blocked, _ = security_guard.check_destructive_command("open_application", "cmd.exe /c del /s C:\\")
        self.assertTrue(blocked)
        blocked, _ = security_guard.check_destructive_command("open_application", "powershell -Command Remove-Item C:\\")
        self.assertTrue(blocked)

    def test_system_critical_process_termination_blocked(self):
        for proc in ("csrss", "csrss.exe", "lsass", "winlogon", "services", "system", "svchost.exe"):
            self.assertTrue(security_guard.is_system_critical_process(proc))
            
            # Guard check
            blocked, reason = security_guard.check_destructive_command("close_application", proc)
            self.assertTrue(blocked, f"Process {proc} was not blocked in security_guard")

            # guard_rules.validate
            v = guard_rules.validate("close_application", proc)
            self.assertEqual(v.decision, BLOCK, f"Process {proc} was not blocked by guard_rules")

            # executor._close_single_app
            res = executor._close_single_app(proc)
            res_str = str(res).lower()
            self.assertTrue("critical" in res_str or "blocked" in res_str or "security policy" in res_str)

    def test_root_drive_deletion_blocked(self):
        for root in ("C:\\", "C:", "D:\\", "C:\\Windows", "C:\\Program Files"):
            v = guard_rules.validate("delete_files", root)
            self.assertEqual(v.decision, BLOCK, f"Deleting {root} was not blocked by guard_rules")

            res = executor.delete_files(root)
            self.assertFalse(res.get("success", False))

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Honest AI Disclosure
    # ──────────────────────────────────────────────────────────────────────────

    def test_claude_prompt_contains_honest_ai_disclosure(self):
        from claude_handler import AKIRA_PROMPT
        
        # Verify old deceptive instruction is NOT present
        self.assertNotIn("never say AI or language model", AKIRA_PROMPT)
        
        # Verify honest disclosure instructions are present
        self.assertIn("are you an AI", AKIRA_PROMPT)
        self.assertIn("answer honestly and directly that yes, you are an AI assistant", AKIRA_PROMPT)
        self.assertIn("Never denies being an AI or claims to be human", AKIRA_PROMPT)

    def test_speech_head_prompt_contains_honest_ai_disclosure(self):
        import inspect
        src = inspect.getsource(speech_head.generate_conversation_reply)
        self.assertIn("If sincerely and directly asked if you are an AI, answer honestly and directly that yes, you are an AI assistant", src)


if __name__ == "__main__":
    unittest.main()
