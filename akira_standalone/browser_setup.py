import os
import socket
import winreg
import win32com.client

BROWSERS = {
    "brave": {
        "port": 9222,
        "candidates": [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ],
        "shortcut_names": ["Brave", "Brave Browser"],
        "user_data": os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware", "Brave-Browser", "User Data"),
    },
    "edge": {
        "port": 9223,
        "candidates": [
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        ],
        "shortcut_names": ["Microsoft Edge", "Edge"],
        "user_data": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"),
    },
    "chrome": {
        "port": 9224,
        "candidates": [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ],
        "shortcut_names": ["Google Chrome", "Chrome"],
        "user_data": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data"),
    },
    "firefox": {
        "port": 9225,
        "candidates": [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Mozilla Firefox", "firefox.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Mozilla Firefox", "firefox.exe"),
        ],
        "shortcut_names": ["Firefox", "Mozilla Firefox"],
        "user_data": os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles"),
    },
}

SHORTCUT_SEARCH_DIRS = [
    os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
    os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
    os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
    os.path.join(os.environ.get("PUBLIC", ""), "Desktop"),
]


def find_exe(candidates):
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def find_shortcuts(shortcut_names):
    found = []
    shell = win32com.client.Dispatch("WScript.Shell")
    for search_dir in SHORTCUT_SEARCH_DIRS:
        if not os.path.exists(search_dir):
            continue
        for root, dirs, files in os.walk(search_dir):
            for f in files:
                if not f.endswith(".lnk"):
                    continue
                name = f.replace(".lnk", "")
                if any(name.lower() == s.lower() for s in shortcut_names):
                    found.append(os.path.join(root, f))
    return found


def patch_shortcut(shortcut_path, exe_path, port, user_data):
    shell = win32com.client.Dispatch("WScript.Shell")
    lnk = shell.CreateShortcut(shortcut_path)
    current_args = lnk.Arguments or ""
    if f"--remote-debugging-port={port}" in current_args:
        return False  # already patched
    new_args = f'--remote-debugging-port={port} --restore-last-session'
    lnk.TargetPath = exe_path
    lnk.Arguments = new_args
    lnk.Save()
    return True


def setup_browsers():
    results = {}
    for name, config in BROWSERS.items():
        exe = find_exe(config["candidates"])
        if not exe:
            results[name] = "not installed"
            continue
        shortcuts = find_shortcuts(config["shortcut_names"])
        if not shortcuts:
            results[name] = "installed but no shortcut found"
            continue
        patched = 0
        for sc in shortcuts:
            try:
                did_patch = patch_shortcut(sc, exe, config["port"], config["user_data"])
                if did_patch:
                    patched += 1
            except Exception as e:
                print(f"  Failed to patch {sc}: {e}")
        results[name] = f"patched {patched} shortcut(s)" if patched > 0 else "already patched"
    return results


def is_port_open(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0


if __name__ == "__main__":
    print("Setting up browser debug ports...")
    results = setup_browsers()
    for browser, status in results.items():
        print(f"  {browser}: {status}")
    print("\nDone. Please restart your browsers for changes to take effect.")