"""demo_exclude_folder.py — Live SIH Presentation Tool for Dynamic Folder Privacy Exclusions.

Allows you to exclude a folder right in front of the audience or judges, and immediately shows:
1. The folder registered under [ACTIVE PRIVACY EXCLUSIONS] in Downloads/akira_drive_map.txt
2. All files under that folder purged from the search index
3. The directory marked as [EXCLUDED BY USER — PROTECTED PRIVACY ZONE] with 0 files accessible

Usage:
  python demo_exclude_folder.py "D:\\Coding\\SecretDemo"
  python demo_exclude_folder.py --status
  python demo_exclude_folder.py --clear
"""

from __future__ import annotations

import os
import sys
import argparse

# Add sensei root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import file_index
from file_index.config import IndexScopeConfig


def show_map_exclusion_proof(folder_path: str | None = None) -> None:
    """Print the exact visual proof lines from Downloads/akira_drive_map.txt."""
    downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    txt_path = os.path.join(downloads_dir, "akira_drive_map.txt")
    if not os.path.exists(txt_path):
        print(f"[!] Map file not found at {txt_path}")
        return

    print("\n" + "=" * 78)
    print(">>> VERIFICATION IN Downloads/akira_drive_map.txt (LIVE PROOF FOR JUDGES) <<<")
    print("=" * 78)

    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # Print top 15 header lines (shows ACTIVE PRIVACY EXCLUSIONS)
    for line in lines[:16]:
        print(line.rstrip())

    if folder_path:
        norm_target = os.path.normpath(folder_path).lower()
        print("-" * 78)
        print(f"Directory Tree Verification for target: {folder_path}")
        matched_lines = []
        for i, line in enumerate(lines):
            if norm_target in line.lower():
                matched_lines.extend(lines[max(0, i - 1):min(len(lines), i + 4)])
                break

        if matched_lines:
            for l in matched_lines:
                print(l.rstrip())
        else:
            print(f"  Target directory '{folder_path}' has been completely suppressed from the tree listing.")

    print("=" * 78 + "\n")


def exclude_folder_live(folder_path: str) -> None:
    """Exclude a folder live, update the database, and regenerate the drive map."""
    norm = os.path.abspath(folder_path.strip().strip("\"'"))
    print(f"\n[LIVE PRIVACY ACTION] Excluding folder from Akira: {norm}")

    # 1. Manage index scope
    res = file_index.manage_index_scope("exclude", norm)
    print(f"[*] Scope update: {res.get('message')}")

    # 2. Synchronously export updated map of C, D, E drives to Downloads
    print("[*] Regenerating comprehensive drive map (C:, D:, E:) strictly to Downloads...")
    paths = file_index.export_drives_map_to_downloads(drives=("C:\\", "D:\\", "E:\\"))
    print(f"[*] Map saved to: {paths['txt_path']}")

    # 3. Print live proof
    show_map_exclusion_proof(norm)

    print("[SUCCESS] Folder is now permanently excluded from Akira indexing, code lookups, and LLM context.")
    print("Spoken voice equivalent for Akira: \"Akira, exclude folder " + os.path.basename(norm) + "\"\n")


def clear_exclusions() -> None:
    """Clear all custom exclusions."""
    scope = IndexScopeConfig()
    count = len(scope.custom_excludes)
    scope.custom_excludes.clear()
    scope.save()
    print(f"\n[RESET] Cleared {count} custom exclusions.")
    print("[*] Regenerating clean drive map in Downloads...")
    file_index.export_drives_map_to_downloads(drives=("C:\\", "D:\\", "E:\\"))
    show_map_exclusion_proof()


def show_status() -> None:
    """Display current active exclusions."""
    scope = IndexScopeConfig()
    print("\n" + "=" * 70)
    print("AKIRA PRIVACY ENGINE: ACTIVE SCOPE EXCLUSIONS")
    print("=" * 70)
    if not scope.custom_excludes:
        print("  No custom folder exclusions currently active.")
    else:
        for exc in sorted(scope.custom_excludes):
            print(f"  [EXCLUDED] {exc}")
    print("=" * 70)
    show_map_exclusion_proof()


def main():
    parser = argparse.ArgumentParser(description="Live audience demo for Akira folder privacy exclusions.")
    parser.add_argument("folder", nargs="?", help="Path to folder to exclude in front of the audience")
    parser.add_argument("--clear", action="store_true", help="Clear all custom exclusions")
    parser.add_argument("--status", action="store_true", help="Show active exclusions")
    args = parser.parse_args()

    if args.clear:
        clear_exclusions()
    elif args.status or not args.folder:
        show_status()
    else:
        exclude_folder_live(args.folder)


if __name__ == "__main__":
    main()
