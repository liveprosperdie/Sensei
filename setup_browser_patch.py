"""
One-time admin setup: patches Brave, Chrome, and Edge shortcuts to launch
with --remote-debugging-port baked in, so Akira can attach via CDP no
matter how the user opens their browser (desktop icon, start menu, taskbar).

Run once, as administrator:
    python setup_browser_patch.py
"""

import os
import sys
import ctypes
import win32com.client

BROWSER_PORTS = {
    "Brave.lnk": 9222,
    "Google Chrome.lnk": 9223,
    "Microsoft Edge.lnk": 9224,
}

SHORTCUT_DIRS = [
    r"C:\Users\Public\Desktop",
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    os.path.expandvars(r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"),
]

FLAG_TEMPLATE = '--remote-debugging-port={port} --profile-directory=Default'


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


import re

def patch_shortcut(path, port):
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(path)
    current_args = shortcut.Arguments or ""

    # strip any existing remote-debugging-port flag, correct or wrong
    cleaned = re.sub(r'--remote-debugging-port=\d+\s*', '', current_args).strip()

    flag = f"--remote-debugging-port={port}"
    if flag in cleaned:
        new_args = cleaned
    else:
        new_args = f"{cleaned} {flag}".strip()

    if "--profile-directory=Default" not in new_args:
        new_args = f"{new_args} --profile-directory=Default".strip()

    if new_args == current_args:
        print(f"  already patched: {path}")
        return

    shortcut.Arguments = new_args
    shortcut.save()
    print(f"  patched: {path} -> {new_args}")


def main():
    if not is_admin():
        print("This script needs to run as administrator.")
        print("Right-click your terminal and 'Run as administrator', then re-run this script.")
        sys.exit(1)

    print("Patching browser shortcuts for Akira browser control...\n")

    patched_count = 0
    for directory in SHORTCUT_DIRS:
        if not os.path.isdir(directory):
            continue
        for fname in os.listdir(directory):
            if fname in BROWSER_PORTS:
                full_path = os.path.join(directory, fname)
                try:
                    patch_shortcut(full_path, BROWSER_PORTS[fname])
                    patched_count += 1
                except Exception as e:
                    print(f"  FAILED: {full_path} -> {e}")

    print(f"\nDone. {patched_count} shortcuts processed.")
    print("Browser control is now ready. You can run Akira normally.")


if __name__ == "__main__":
    main()