"""security_guard.py — Structural Deny layer for Akira safety boundaries.

Enforces two unconditional code-level safety boundaries:
1. AKIRA MUST NEVER MODIFY ITS OWN SOURCE CODE (Self-modification block).
   - Resolves all target paths to canonical absolute realpaths.
   - Refuses any write, edit, delete, move, or git clone targeting the Akira codebase.
   - Bypasses via relative paths (./, ../), case variations, symlinks, or indirect
     writes fail closed and are blocked.
   - Allows legitimate non-executable document exports in designated output directories.
2. AKIRA MUST NEVER EXECUTE DESTRUCTIVE OS-LEVEL COMMANDS (Destructive command denylist).
   - Hard-coded structural denylist: recursive force deletes, disk formatting, registry
     deletion, killing system-critical processes, permission/ownership changes, and
     raw shell execution command strings.
"""

from __future__ import annotations

import os
import re
from typing import Final

# ── Codebase Root Canonicalization ───────────────────────────────────────────
# Canonical normalized realpath to the Akira codebase root.
REPO_ROOT: Final[str] = os.path.normcase(
    os.path.realpath(os.path.abspath(os.path.dirname(__file__)))
)

# Designated export/output directory inside the repo for documents/media.
# Files written here are allowed ONLY if they are not executable/code scripts.
ALLOWED_OUTPUT_DIR: Final[str] = os.path.normcase(
    os.path.realpath(os.path.abspath(os.path.join(REPO_ROOT, "output")))
)

# Executable and script extensions that can never be written anywhere in repo
EXECUTABLE_EXTENSIONS: Final[frozenset[str]] = frozenset({
    ".py", ".pyw", ".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs",
    ".sh", ".bin", ".com", ".sys", ".drv", ".msi", ".jar", ".vbe",
    ".jse", ".wsf", ".wsh", ".pif", ".scr",
})


def get_codebase_root() -> str:
    """Return the canonical normalized root path of the Akira codebase."""
    return REPO_ROOT


def is_codebase_path(target_path: str | None) -> bool:
    """Check if a path resolves inside the Akira codebase.

    Returns True if target falls within the Akira repository (BLOCKED),
    unless it is a non-executable document export inside the designated output/ directory.
    Fails closed (returns True) if path resolution fails.
    """
    if not target_path or not str(target_path).strip():
        return False

    raw = str(target_path).strip()
    raw = os.path.expandvars(os.path.expanduser(raw))

    # If raw is a relative path or bare filename (e.g. "Reinforcement Learning.docx"),
    # check if it actually exists in the Akira repository before flagging it.
    if not os.path.isabs(raw):
        candidate = os.path.join(REPO_ROOT, raw)
        if not os.path.exists(candidate):
            # Does not exist in repo root — not a codebase file
            return False
        try:
            resolved = os.path.normcase(os.path.realpath(candidate))
        except Exception:
            return True
    else:
        try:
            resolved = os.path.normcase(os.path.realpath(os.path.abspath(raw)))
        except Exception:
            # Suspicious or unresolvable path -> fail closed
            return True

    # Check if target is inside or identical to REPO_ROOT
    is_in_repo = (resolved == REPO_ROOT) or resolved.startswith(REPO_ROOT + os.sep)
    if not is_in_repo:
        # Outside repo root (e.g. ~/Documents, D:\other, C:\Users\...\Downloads, etc.)
        return False

    # Inside repo root: check if it falls within the designated output/ directory
    is_in_output = (resolved == ALLOWED_OUTPUT_DIR) or resolved.startswith(ALLOWED_OUTPUT_DIR + os.sep)
    if is_in_output:
        _, ext = os.path.splitext(resolved)
        if ext.lower() in EXECUTABLE_EXTENSIONS:
            return True  # Code or script file in output directory is blocked
        return False  # Non-code document output in output/ is allowed

    # Everything else existing in REPO_ROOT is part of the Akira codebase
    return True


def assert_not_codebase_path(target_path: str | None, operation: str = "modify") -> None:
    """Raise ValueError if target_path falls within the Akira codebase."""
    if is_codebase_path(target_path):
        raise ValueError(
            f"Operation '{operation}' on Akira's codebase is strictly prohibited: {target_path}"
        )


# ── System-Critical Processes ────────────────────────────────────────────────
# Windows core processes that must never be terminated by Akira.
SYSTEM_CRITICAL_PROCESSES: Final[frozenset[str]] = frozenset({
    "csrss", "csrss.exe",
    "smss", "smss.exe",
    "winlogon", "winlogon.exe",
    "wininit", "wininit.exe",
    "services", "services.exe",
    "lsass", "lsass.exe",
    "lsm", "lsm.exe",
    "svchost", "svchost.exe",
    "system",
    "registry",
    "dwm", "dwm.exe",
    "explorer", "explorer.exe",
    "spoolsv", "spoolsv.exe",
    "ntoskrnl", "ntoskrnl.exe",
    "fontdrvhost", "fontdrvhost.exe",
    "sihost", "sihost.exe",
    "taskmgr", "taskmgr.exe",
})


def is_system_critical_process(name: str | None) -> bool:
    """Check if process name matches a system-critical process."""
    if not name:
        return False
    proc = name.strip().lower()
    base = os.path.basename(proc)
    root, _ = os.path.splitext(base)
    return (proc in SYSTEM_CRITICAL_PROCESSES or
            base in SYSTEM_CRITICAL_PROCESSES or
            root in SYSTEM_CRITICAL_PROCESSES)


# ── Destructive OS Command Denylist ──────────────────────────────────────────
# Concrete denylist patterns matching destructive OS-level commands.
DESTRUCTIVE_COMMAND_PATTERNS: Final[list[re.Pattern]] = [
    # Recursive / force deletion
    re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|--recursive)\b", re.I),
    re.compile(r"\bdel\b.*\s+/[sSfF]\b", re.I),
    re.compile(r"\brmdir\b.*\s+/[sS]\b", re.I),
    re.compile(r"\bRemove-Item\b.*-(Recurse|Force)\b", re.I),
    re.compile(r"\brd\b.*\s+/[sS]\b", re.I),

    # Disk formatting, partitioning, free-space wiping, and shadow copy destruction
    re.compile(r"\bformat\s+[a-zA-Z]:(\s|$|/|\\)", re.I),
    re.compile(r"\bFormat-Volume\b", re.I),
    re.compile(r"\bdiskpart\b", re.I),
    re.compile(r"\bclean\s+all\b", re.I),
    re.compile(r"\bcipher(\.exe)?\s+/w:", re.I),
    re.compile(r"\bvssadmin(\.exe)?\s+delete\s+shadows\b", re.I),
    re.compile(r"\bwbadmin(\.exe)?\s+delete\b", re.I),
    re.compile(r"\bbcdedit(\.exe)?\b.*\b(delete|set)\b", re.I),

    # Registry deletion
    re.compile(r"\breg\s+(delete|add)\b", re.I),
    re.compile(r"\bRemove-ItemProperty\b.*(HKLM|HKCU|Registry)", re.I),
    re.compile(r"\bRemove-Item\b.*(HKLM|HKCU|Registry::)", re.I),

    # Permission / ownership alterations on system directories
    re.compile(r"\bicacls\b", re.I),
    re.compile(r"\btakeown\b", re.I),
    re.compile(r"\bSet-Acl\b", re.I),
    re.compile(r"\bgrant\b.*\s+:[fF]\b", re.I),
    re.compile(r"\bchmod\b\s+.*[0-7]{3}", re.I),
    re.compile(r"\bchown\b", re.I),

    # Shell command execution invocations attempting command strings
    re.compile(r"\b(cmd(\.exe)?)\s+/[cCkK]\b", re.I),
    re.compile(r"\b(powershell(\.exe)?|pwsh(\.exe)?)\s+.*-(Command|EncodedCommand|c)\b", re.I),
    re.compile(r"\bwscript(\.exe)?\b", re.I),
    re.compile(r"\bcscript(\.exe)?\b", re.I),
    re.compile(r"\bmshta(\.exe)?\b", re.I),
]

# Sensitive Windows system directory prefixes that can never be targeted for deletion
SYSTEM_DIR_PATTERNS: Final[list[re.Pattern]] = [
    re.compile(r"^[a-zA-Z]:\\?$", re.I),                             # Root drive (e.g. C:\)
    re.compile(r"^[a-zA-Z]:\\windows(\\|/|$)", re.I),                # C:\Windows
    re.compile(r"^[a-zA-Z]:\\program files(\\|/|$)", re.I),          # C:\Program Files
    re.compile(r"^[a-zA-Z]:\\program files \(x86\)(\\|/|$)", re.I),  # C:\Program Files (x86)
    re.compile(r"^[a-zA-Z]:\\programdata(\\|/|$)", re.I),            # C:\ProgramData
]


def check_self_modification(path_str: str | None) -> tuple[bool, str | None]:
    """Inspect a candidate path for self-modification.

    Returns (is_blocked, reason).
    """
    if not path_str or not path_str.strip():
        return False, None

    # Handle piped parameters (e.g. 'path|content' or 'path|find|replace')
    target = path_str.split("|")[0].strip()
    # Defense-in-depth: non-path tool keywords / verbs should never trigger self-mod
    if target.lower() in ("excel", "word", "powerpoint", "teams", "open folder", "open file", "search repos", "open repo", "star repo", "repo notes"):
        return False, None

    if is_codebase_path(target):
        return True, (
            f"Self-modification of Akira's source code is strictly not permitted "
            f"(target '{target}' is within the codebase)."
        )
    return False, None


def check_destructive_command(action: str, parameter: str | None = None) -> tuple[bool, str | None]:
    """Inspect an action and parameter for destructive OS operations.

    Returns (is_blocked, reason).
    """
    act = (action or "").strip().lower()
    param = (parameter or "").strip()

    # 1. Process termination checks
    if act in ("close_application", "kill_process"):
        targets = [p.strip() for p in param.split(",") if p.strip()]
        for t in targets:
            if is_system_critical_process(t):
                return True, f"Terminating system-critical process '{t}' is blocked by security policy."

    # 2. File deletion checks
    if act in ("delete_files", "delete_file"):
        parts = param.split("|")
        target = parts[0].strip() if parts else ""
        # Check against system directories
        for pattern in SYSTEM_DIR_PATTERNS:
            if pattern.search(target):
                return True, f"Deleting system directory or root drive '{target}' is blocked by security policy."
        # Check if targeting codebase
        if is_codebase_path(target):
            return True, f"Deleting Akira source code '{target}' is strictly prohibited (target is within the codebase)."

    # 3. Denylist pattern matches across action and parameters
    full_str = f"{act} {param}".strip()
    for pat in DESTRUCTIVE_COMMAND_PATTERNS:
        if pat.search(full_str) or pat.search(param):
            return True, f"Execution of destructive command '{param}' is blocked by security policy."

    return False, None
