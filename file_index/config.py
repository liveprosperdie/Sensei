"""
file_index/config.py — Storage location, drive volume serial tracking, and scope config.
"""

import os
import sys
import json
import string
import ctypes
import shutil
from typing import Optional, Tuple, List, Dict

# Reviewable, editable default exclude constants
DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    "node_modules",
    ".git",
    ".svn",
    ".hg",
    "AppData",
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "Recovery",
    "PerfLogs",
    "MSOCache",
    "Boot",
    "EFI",
    ".ssh",
    ".aws",
    ".gnupg",
    ".azure",
    ".kube",
    ".docker",
    "$Recycle.Bin",
    "$RECYCLE.BIN",
    "System Volume Information",
    "Temp",
    "tmp",
    "Cache",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    "target",
    "build",
    "dist",
})

DEFAULT_CONTENT_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".py", ".json", ".csv", ".log", ".pdf", ".docx",
    ".html", ".htm", ".xml", ".yaml", ".yml", ".ini", ".cfg", ".toml",
    ".rst", ".tex", ".c", ".cpp", ".h", ".hpp", ".cs", ".java", ".js",
    ".ts", ".jsx", ".tsx", ".sh", ".bat", ".ps1", ".sql", ".rb", ".go", ".rs"
})


def get_config_dir() -> str:
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    config_dir = os.path.join(local_appdata, "Akira")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def get_secure_vault_dir() -> str:
    """Hidden, protected directory on C: drive strictly excluded from LLM context."""
    vault = os.path.join(get_config_dir(), "secure_vault")
    os.makedirs(vault, exist_ok=True)
    return vault


def get_secure_drive_map_json() -> str:
    return os.path.join(get_secure_vault_dir(), "akira_drive_map.json")


def get_secure_drive_map_txt() -> str:
    return os.path.join(get_secure_vault_dir(), "akira_drive_map.txt")


def get_location_config_file() -> str:
    return os.path.join(get_config_dir(), "index_location.json")


def get_scope_config_file() -> str:
    return os.path.join(get_config_dir(), "index_scope.json")


def get_directory_map_file(target_dir: Optional[str] = None) -> str:
    """Return path to directory_map.txt inside target_dir or config directory."""
    if target_dir and os.path.isdir(target_dir):
        return os.path.join(target_dir, "directory_map.txt")
    return os.path.join(get_config_dir(), "directory_map.txt")


def get_volume_serial(path: str) -> str:
    """Retrieve 8-character hex volume serial number for a Windows drive."""
    if not sys.platform.startswith("win"):
        return "00000000"
    try:
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        if not drive:
            drive = os.environ.get("SystemDrive", "C:")
        root = drive.rstrip("\\") + "\\"
        serial = ctypes.c_ulong()
        res = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            None, 0,
            ctypes.byref(serial),
            None, None, None, 0
        )
        if res != 0:
            return f"{serial.value:08X}"
    except Exception as e:
        print(f"[file_index.config] get_volume_serial warning: {e}")
    return ""


def find_drive_by_serial(target_serial: str) -> Optional[str]:
    """Scan connected Windows drives to find the one matching the given volume serial number."""
    if not sys.platform.startswith("win") or not target_serial:
        return None
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                root = f"{letter}:\\"
                serial = ctypes.c_ulong()
                if ctypes.windll.kernel32.GetVolumeInformationW(
                    ctypes.c_wchar_p(root), None, 0, ctypes.byref(serial), None, None, None, 0
                ):
                    if f"{serial.value:08X}".upper() == target_serial.upper():
                        return root
            bitmask >>= 1
    except Exception as e:
        print(f"[file_index.config] find_drive_by_serial warning: {e}")
    return None


def get_system_drive() -> str:
    return (os.environ.get("SystemDrive", "C:")[:2] + "\\").upper()


def get_available_drives() -> List[Dict]:
    """List all connected fixed/removable drives with free space and volume serials."""
    drives = []
    if not sys.platform.startswith("win"):
        total, used, free = shutil.disk_usage("/")
        drives.append({
            "root": "/",
            "is_system": True,
            "total_gb": total / (1024**3),
            "free_gb": free / (1024**3),
            "volume_serial": "00000000"
        })
        return drives

    sys_drive = get_system_drive()
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            root = f"{letter}:\\"
            dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
            # DRIVE_FIXED = 3, DRIVE_REMOVABLE = 2
            if dtype in (2, 3):
                try:
                    total, used, free = shutil.disk_usage(root)
                    serial = get_volume_serial(root)
                    drives.append({
                        "root": root,
                        "is_system": (root.upper() == sys_drive),
                        "total_gb": total / (1024**3),
                        "free_gb": free / (1024**3),
                        "volume_serial": serial
                    })
                except Exception:
                    pass
        bitmask >>= 1
    return drives


def recommend_default_location() -> Tuple[str, bool]:
    """
    Prefer the largest non-system drive if one exists;
    otherwise fall back to system drive with is_single_drive note.
    Returns: (suggested_full_path, is_single_drive_setup)
    """
    drives = get_available_drives()
    non_system = [d for d in drives if not d["is_system"]]
    if non_system:
        # Sort by total space descending
        non_system.sort(key=lambda d: d["total_gb"], reverse=True)
        chosen = non_system[0]["root"]
        target_dir = os.path.join(chosen, "AkiraIndex")
        return os.path.join(target_dir, "akira_index.db"), False

    # Single-drive fallback
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    target_dir = os.path.join(local_appdata, "Akira", "Index")
    return os.path.join(target_dir, "akira_index.db"), True


def resolve_saved_location() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Resolve saved index location from index_location.json.
    Survives drive-letter reassignment by checking volume_serial.
    Returns: (resolved_path, last_known_path, failure_reason)
    If valid: (resolved_path, None, None)
    If invalid/missing: (None, last_known_path, reason)
    """
    config_file = get_location_config_file()
    if not os.path.exists(config_file):
        return None, None, "No index location configured yet."

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return None, None, f"Configuration file corrupted: {e}"

    saved_path = data.get("path")
    saved_serial = data.get("volume_serial", "")

    if not saved_path:
        return None, None, "Configuration contains empty path."

    # 1. Check if saved_path exists directly and matches serial
    drive = os.path.splitdrive(saved_path)[0]
    if drive and os.path.exists(saved_path):
        current_serial = get_volume_serial(drive + "\\")
        if not saved_serial or current_serial.upper() == saved_serial.upper():
            return saved_path, None, None

    # 2. Drive letter may have moved — check all connected drives by serial
    if saved_serial:
        new_drive_root = find_drive_by_serial(saved_serial)
        if new_drive_root:
            new_drive = new_drive_root.rstrip("\\")
            old_drive = drive
            rel_path = saved_path[len(old_drive):].lstrip("\\/")
            candidate_path = os.path.join(new_drive + "\\", rel_path)
            if os.path.exists(candidate_path):
                # Update saved path with new drive letter
                save_index_location(candidate_path)
                print(f"[file_index.config] Drive remapped from {old_drive} to {new_drive} by volume serial {saved_serial}")
                return candidate_path, None, None

    return None, saved_path, f"Index file not found or drive with serial {saved_serial} disconnected."


def save_index_location(db_path: str, serial: Optional[str] = None) -> dict:
    """Save chosen index location and drive volume serial number."""
    abs_path = os.path.abspath(db_path)
    parent_dir = os.path.dirname(abs_path)
    try:
        os.makedirs(parent_dir, exist_ok=True)
    except OSError:
        pass
    if serial is None:
        serial = get_volume_serial(abs_path)
    data = {
        "path": abs_path,
        "volume_serial": serial,
        "updated_at": os.path.getmtime(abs_path) if os.path.exists(abs_path) else None
    }
    config_file = get_location_config_file()
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


class IndexScopeConfig:
    """Manages persistent included/excluded folder scopes."""

    def __init__(self):
        self.config_path = get_scope_config_file()
        self.custom_excludes: set[str] = set()
        self.custom_includes: set[str] = set()
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.custom_excludes = set(os.path.abspath(p) for p in data.get("excludes", []))
                    self.custom_includes = set(os.path.abspath(p) for p in data.get("includes", []))
            except Exception as e:
                print(f"[file_index.config] Error loading scope config: {e}")

    def save(self):
        data = {
            "excludes": sorted(list(self.custom_excludes)),
            "includes": sorted(list(self.custom_includes))
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def exclude_folder(self, folder_path: str) -> str:
        abs_p = os.path.abspath(folder_path)
        self.custom_includes.discard(abs_p)
        self.custom_excludes.add(abs_p)
        self.save()
        try:
            import procedural_memory as pm
            pm.get_store().purge_by_path(abs_p)
        except Exception:
            pass
        return abs_p

    def include_folder(self, folder_path: str) -> str:
        abs_p = os.path.abspath(folder_path)
        self.custom_excludes.discard(abs_p)
        self.custom_includes.add(abs_p)
        self.save()
        return abs_p

    def is_excluded(self, folder_name: str, full_path: str) -> bool:
        """Check if folder matches default excludes or custom user excludes."""
        abs_p = os.path.abspath(full_path)
        # Custom includes explicitly override default exclusions
        for inc in self.custom_includes:
            if abs_p == inc or abs_p.startswith(inc + os.sep):
                return False

        # Check custom excludes
        for exc in self.custom_excludes:
            if abs_p == exc or abs_p.startswith(exc + os.sep):
                return True

        # Check default exclude directory names
        if folder_name in DEFAULT_EXCLUDE_DIRS or folder_name.lower() in {d.lower() for d in DEFAULT_EXCLUDE_DIRS}:
            return True

        # Hidden or temporary system folders
        if folder_name.startswith("$") or folder_name.startswith("."):
            if folder_name not in {".", ".."}:
                return True

        return False
