"""
executor.py — Akira's hands.
Handles all PC control, browser automation, and action dispatch.
"""

import os
import re
import time
import glob
import shutil
import zipfile
import psutil
import winreg
import datetime
import threading
import webbrowser
import subprocess
import urllib.parse
import win32process
import win32gui
import requests
import pygetwindow as gw
import tkinter as tk
from PIL import ImageGrab
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from pycaw.pycaw import AudioUtilities

import image_flow
import system_control as _system_control
from guard_rules import GuardToken, GuardBypassError

# ── Constants ─────────────────────────────────────────────────────────────────

_home = os.path.expanduser("~")
_screenshot_dir = os.path.join(_home, "Pictures", "Screenshots")
os.makedirs(_screenshot_dir, exist_ok=True)

BRAVE_PATH  = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EDGE_PATH   = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

URI_MAP = {
    "settings": "ms-settings:", "calculator": "calculator:",
    "store": "ms-windows-store:", "copilot": "ms-copilot:",
    "msedge": "microsoft-edge:", "edge": "microsoft-edge:",
    "whatsapp": "whatsapp:", "paint": "ms-paint:",
    "camera": "microsoft.windows.camera:", "chatgpt": "chatgpt:",
    "clock": "ms-clock:", "teams": "msteams:", "xbox": "xbox:",
    "notepad": "notepad",
}

MANUAL_MAP = {
    "explorer": r"C:\Windows\explorer.exe",
    "files":    r"C:\Windows\explorer.exe",
    "brave":    BRAVE_PATH,
    "chrome":   CHROME_PATH,
    "firefox":  r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "edge":     EDGE_PATH,
    "discord":  os.path.join(_home, "AppData", "Local", "Discord", "Update.exe"),
    "vlc":      r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    "obsidian": os.path.join(_home, "AppData", "Local", "Programs", "Obsidian", "Obsidian.exe"),
    "notion":   os.path.join(_home, "AppData", "Local", "Programs", "Notion", "Notion.exe"),
    "winrar":   r"C:\Program Files (x86)\WinRAR\winrar.exe",
    "gitbash":  r"C:\Program Files\Git\git-bash.exe",
    "steam":    r"C:\Program Files (x86)\Steam\steam.exe",
    "capcut":   os.path.join(_home, "AppData", "Local", "CapCut", "Apps", "capcut.exe"),
    "adobe":    r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
    "acrobat":  r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
    "protonvpn":r"C:\Program Files\Proton\VPN\ProtonVPN.Launcher.exe",
    "vpn":      r"C:\Program Files\Proton\VPN\ProtonVPN.Launcher.exe",
    "githubapp":os.path.join(_home, "AppData", "Local", "GitHubDesktop", "GitHubDesktop.exe"),
    "canva":    os.path.join(_home, "AppData", "Local", "Programs", "Canva", "Canva.exe"),
    "word":     r"C:\Program Files\Microsoft Office\root\Office16\winword.exe",
    "excel":    r"C:\Program Files\Microsoft Office\root\Office16\excel.exe",
    "powerpoint":r"C:\Program Files\Microsoft Office\root\Office16\powerpnt.exe",
    "zoom":     os.path.join(_home, "AppData", "Roaming", "Zoom", "bin", "Zoom.exe"),
    "filmora":  os.path.join(_home, "AppData", "Local", "Wondershare", "Wondershare Filmora", "Filmora.exe"),
    "spotify":  os.path.join(_home, "AppData", "Roaming", "Spotify", "Spotify.exe"),
    "vscode":   next((p for p in [
        os.path.join(_home, "AppData", "Local", "Programs", "Microsoft VS Code", "Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
    ] if os.path.exists(p)), shutil.which("code") or r"C:\Program Files\Microsoft VS Code\Code.exe"),
    "code":     next((p for p in [
        os.path.join(_home, "AppData", "Local", "Programs", "Microsoft VS Code", "Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
    ] if os.path.exists(p)), shutil.which("code") or r"C:\Program Files\Microsoft VS Code\Code.exe"),
    "calc":     r"C:\Windows\System32\calc.exe" if os.path.exists(r"C:\Windows\System32\calc.exe") else "calc.exe",
    "notepad":  r"C:\Windows\System32\notepad.exe" if os.path.exists(r"C:\Windows\System32\notepad.exe") else "notepad.exe",
}

WEB_MAP = {
    "youtube": "https://youtube.com", "claude": "https://claude.ai",
    "gmail": "https://mail.google.com", "github": "https://github.com",
    "instagram": "https://instagram.com", "pinterest": "https://pinterest.com",
    "facebook": "https://facebook.com", "twitter": "https://x.com",
    "weather": "https://weather.com", "calendar": "https://calendar.google.com",
    "x": "https://x.com",
}

TOP_SITES_MAP = {
    **WEB_MAP,
    "netflix": "https://netflix.com", "prime video": "https://primevideo.com",
    "hotstar": "https://hotstar.com", "spotify": "https://open.spotify.com",
    "amazon": "https://amazon.in", "flipkart": "https://flipkart.com",
    "reddit": "https://reddit.com", "linkedin": "https://linkedin.com",
    "twitch": "https://twitch.tv", "discord": "https://discord.com/app",
    "notion": "https://notion.so", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "gemini": "https://gemini.google.com",
    "wikipedia": "https://en.wikipedia.org", "stackoverflow": "https://stackoverflow.com",
    "quora": "https://quora.com", "medium": "https://medium.com",
    "zoom": "https://zoom.us", "canva": "https://canva.com",
    "figma": "https://figma.com", "drive": "https://drive.google.com",
    "docs": "https://docs.google.com", "sheets": "https://sheets.google.com",
    "maps": "https://maps.google.com", "translate": "https://translate.google.com",
    "meet": "https://meet.google.com", "google meet": "https://meet.google.com",
}

def resolve_site_url(name: str) -> str:
    """Map a spoken site name to a URL. Handles full URLs, site names, and delimiters."""
    clean = (name or "").strip()
    if "|" in clean:
        clean = clean.split("|")[0].strip()
    if clean.startswith(("http://", "https://")):
        return clean
    key = clean.lower()
    if key in TOP_SITES_MAP:
        return TOP_SITES_MAP[key]
    guess = f"https://{key.replace(' ', '')}.com"
    return guess

SEARCH_URL_MAP = {
    "youtube":     "https://www.youtube.com/results?search_query={}",
    "google":      "https://www.google.com/search?q={}",
    "gmail":       "https://mail.google.com/mail/u/0/#search/{}",
    "github":      "https://github.com/search?q={}",
    "reddit":      "https://www.reddit.com/search/?q={}",
    "twitter":     "https://x.com/search?q={}",
    "x":           "https://x.com/search?q={}",
    "instagram":   "https://www.instagram.com/explore/search/keyword/?q={}",
    "pinterest":   "https://www.pinterest.com/search/pins/?q={}",
    "amazon":      "https://www.amazon.in/s?k={}",
    "flipkart":    "https://www.flipkart.com/search?q={}",
    "chatgpt":     "https://chatgpt.com/?q={}",
    "claude":      "https://claude.ai/new?q={}",
    "gemini":      "https://gemini.google.com/app?q={}",
    "perplexity":  "https://www.perplexity.ai/search?q={}",
    "stackoverflow":"https://stackoverflow.com/search?q={}",
    "wikipedia":   "https://en.wikipedia.org/w/index.php?search={}",
    "spotify":     "https://open.spotify.com/search/{}",
    "netflix":     "https://www.netflix.com/search?q={}",
    "makemytrip":  "https://www.makemytrip.com/hotels/",
    "ixigo":       "https://www.ixigo.com/hotels",
}

SITE_DOMAINS = {
    "youtube.com": "youtube", "amazon.in": "amazon", "amazon.com": "amazon",
    "flipkart.com": "flipkart", "github.com": "github", "reddit.com": "reddit",
    "netflix.com": "netflix", "spotify.com": "spotify", "instagram.com": "instagram",
    "twitter.com": "twitter", "x.com": "twitter", "pinterest.com": "pinterest",
    "stackoverflow.com": "stackoverflow", "wikipedia.org": "wikipedia",
}

WINDOW_TITLE_MAP = {
    "clock": "Clock", "calculator": "Calculator", "file explorer": "explorer",
    "photos": "Photos", "maps": "Maps", "calendar": "Calendar",
    "camera": "Camera", "mail": "Mail", "store": "Microsoft Store",
}

UWP_MAP = {"settings": "SystemSettings"}

MUTE_MAP = {
    "mute": 1, "quiet": 1, "silence": 1, "shut it": 1,
    "unmute": 0, "speak up": 0,
}

BRIGHTNESS_MAP = {
    "max": 100, "full": 100, "minimum": 0, "min": 0, "off": 0,
    "half": 50, "medium": 50, "mid": 50, "low": 25, "high": 75,
}

APP_ALIASES = {
    "microsoft word": "word", "microsoft excel": "excel",
    "microsoft powerpoint": "powerpoint", "microsoft store": "store",
    "microsoft teams": "teams", "google chrome": "chrome",
    "mozilla firefox": "firefox", "github desktop": "githubapp",
    "github": "github", "proton vpn": "protonvpn",
    "adobe acrobat": "acrobat", "adobe reader": "acrobat", "git bash": "gitbash",
    "file explorer": "explorer", "windows explorer": "explorer",
    "my computer": "explorer", "this pc": "explorer", "file manager": "explorer",
    "vs code": "vscode", "visual studio code": "vscode", "code": "vscode",
    "calculator": "calc", "calc": "calc", "notepad": "notepad",
}

# RISKY_KEYWORDS — word-boundary matched, not substring
RISKY_KEYWORDS = [
    "buy", "purchase", "checkout", "pay", "payment",
    "submit", "send", "confirm order", "place order", "delete",
    "cancel subscription", "sign up", "register", "donate",
    "transfer", "withdraw", "discard", "archive", "block",
    "unsubscribe", "forward", "subscribe", "remove", "report"
]
_risky_pattern = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in RISKY_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# ── Browser state ─────────────────────────────────────────────────────────────

_browsers: dict = {}
_last_browser_name: str | None = None


# ── Browser utilities ─────────────────────────────────────────────────────────

def _port_ready(port: int) -> bool:
    try:
        return requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1).status_code == 200
    except Exception:
        return False


def _kill_process(name: str) -> None:
    import security_guard
    if security_guard.is_system_critical_process(name):
        print(f"[_kill_process] Refusing to kill system-critical process: {name}")
        return
    subprocess.run(["taskkill", "/F", "/T", "/IM", name], capture_output=True)
    time.sleep(1.0)


def _ensure_current_handle(driver) -> None:
    """Ensure driver has a valid current window handle. Use whatever tab is active."""
    try:
        # Just verify we can access current handle - don't switch anything
        _ = driver.current_window_handle
    except Exception:
        # Only if completely broken, use first available handle
        if driver.window_handles:
            driver.switch_to.window(driver.window_handles[0])


def _ensure_akira_tab(driver) -> None:
    """Adopt or create Akira's own working tab. Reuses existing tab without
    expensive O(N) handle switching loops on every get_browser call."""
    if getattr(driver, "_akira_tab", None):
        return
    try:
        handles = driver.window_handles
        if handles:
            driver._akira_tab = handles[-1]
            return
        # If no tabs exist, create one via CDP
        target = driver.execute_cdp_cmd("Target.createTarget", {"url": "about:blank"})
        if target and target.get("targetId"):
            driver._akira_tab = target["targetId"]
    except Exception:
        pass


# ── Tab targeting & user activation ───────────────────────────────────────────
#
# ONE implementation of "make sure I am driving the right tab", replacing the
# ad-hoc `switch_to.window(browser._akira_tab)` that was copy-pasted across the
# control functions (each with its own silent `except: pass`, so a stale handle
# produced commands executed against the wrong page while still reporting
# success).
#
# Policy: never steal OS focus for ordinary DOM work. Only the handful of
# actions the BROWSER itself refuses without user activation (fullscreen,
# keyboard shortcuts) go through _with_user_activation.

# Virtual key codes for the shortcuts we actually send. Chrome ignores
# dispatchKeyEvent without a correct windowsVirtualKeyCode for non-text keys.
_VK_CODES = {
    'f': (0x46, 'KeyF', 'f'), 'm': (0x4D, 'KeyM', 'm'),
    's': (0x53, 'KeyS', 's'), 't': (0x54, 'KeyT', 't'),
    'c': (0x43, 'KeyC', 'c'), 'k': (0x4B, 'KeyK', 'k'),
    'j': (0x4A, 'KeyJ', 'j'), 'l': (0x4C, 'KeyL', 'l'),
    # d / e: Google Meet's own mic and camera shortcuts (ctrl+d, ctrl+e)
    'd': (0x44, 'KeyD', 'd'), 'e': (0x45, 'KeyE', 'e'),
    ' ': (0x20, 'Space', ' '),
    'escape': (0x1B, 'Escape', ''), 'esc': (0x1B, 'Escape', ''),
    'enter': (0x0D, 'Enter', '\r'),
    'left': (0x25, 'ArrowLeft', ''), 'up': (0x26, 'ArrowUp', ''),
    'right': (0x27, 'ArrowRight', ''), 'down': (0x28, 'ArrowDown', ''),
}







def _ensure_target_tab(browser) -> str | None:
    """Point the driver at Akira's working tab and RETURN its url.

    Re-resolves through _ensure_akira_tab when the stored handle has died, so
    a closed tab degrades to "adopt/create another" instead of executing the
    command against whatever tab happened to be active."""
    try:
        handles = browser.window_handles
    except Exception as e:
        print(f"[FOCUS] driver unreachable: {e}")
        return None

    target = getattr(browser, "_akira_tab", None)
    if not target or target not in handles:
        print(f"[FOCUS] stored tab {target!r} is stale — re-resolving")
        try:
            _ensure_akira_tab(browser)
            target = getattr(browser, "_akira_tab", None)
        except Exception as e:
            print(f"[FOCUS] re-resolve failed: {e}")
            target = None
    if not target:
        return None

    try:
        if browser.current_window_handle != target:
            browser.switch_to.window(target)
    except Exception:
        try:
            browser.switch_to.window(target)
        except Exception as e:
            print(f"[FOCUS] switch failed: {e}")
            return None

    try:
        url = browser.current_url or ""
    except Exception:
        url = ""
    print(f"[FOCUS] tab={target} url={url[:80]}")
    return url


def _activate_tab(browser) -> bool:
    """Make the working tab the ACTIVE tab inside its own window.

    Does not raise the window above other applications — a background tab
    cannot receive key events or enter fullscreen, but foregrounding the whole
    browser over the user's editor is a separate, more invasive step."""
    ok = False
    try:
        browser.execute_cdp_cmd("Page.bringToFront", {})
        ok = True
    except Exception as e:
        print(f"[FOCUS] bringToFront failed: {e}")
    return ok


def _browser_hwnd(browser) -> int | None:
    """Top-level window handle of the browser showing our working tab.

    Matched by the page TITLE rather than by pid: the pid on
    driver.service.process is chromedriver's, not the browser's (the browser is
    launched separately by _attach_cdp and merely attached to over CDP), so a
    pid comparison would never match. The current tab's title is in the window
    caption, which is a signal we actually have."""
    try:
        page_title = (browser.title or "").strip()
    except Exception:
        page_title = ""

    candidates: list[int] = []
    titled: list[int] = []

    def _cb(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            cls = win32gui.GetClassName(hwnd) or ""
            title = win32gui.GetWindowText(hwnd) or ""
            if "Chrome_WidgetWin" not in cls or not title:
                return
            candidates.append(hwnd)
            if page_title and page_title[:40] in title:
                titled.append(hwnd)
        except Exception:
            return

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception as e:
        print(f"[FOCUS] EnumWindows failed: {e}")
        return None
    if titled:
        return titled[0]
    return candidates[0] if candidates else None


def _is_browser_foreground(browser) -> bool:
    """True when a browser window is the OS foreground window. Logged on every
    activation attempt because "the click went to VS Code" is exactly the class
    of bug this tells us about."""
    try:
        fg = win32gui.GetForegroundWindow()
        cls = win32gui.GetClassName(fg) or ""
        title = win32gui.GetWindowText(fg) or ""
    except Exception:
        return False
    is_browser = "Chrome_WidgetWin" in cls
    print(f"[FOCUS] foreground='{title[:40]}' class={cls} browser={is_browser}")
    return is_browser


def _with_user_activation(browser) -> bool:
    """The ONLY path that raises the browser window over other apps.

    Reserved for actions the browser refuses without a transient user
    activation: requestFullscreen() and site keyboard shortcuts. Everything
    else must use _ensure_target_tab/_activate_tab and leave focus alone."""
    _activate_tab(browser)
    if _is_browser_foreground(browser):
        return True
    hwnd = _browser_hwnd(browser)
    if not hwnd:
        print("[FOCUS] no browser hwnd found — cannot grant user activation")
        return False
    try:
        win32gui.ShowWindow(hwnd, 5)          # SW_SHOW
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.25)
        print(f"[FOCUS] raised browser hwnd={hwnd}")
        return _is_browser_foreground(browser)
    except Exception as e:
        # SetForegroundWindow legitimately fails when the OS denies the
        # foreground lock; report it rather than pretending the key landed.
        print(f"[FOCUS] SetForegroundWindow failed: {e}")
        return False


def _send_trusted_key(browser, key: str, hold: float = 0.03,
                      modifiers: int = 0) -> bool:
    """Dispatch a key through CDP so it counts as REAL user input.

    A JS `.click()` or send_keys on <body> is untrusted: `event.isTrusted` is
    false and no user-activation window opens, so YouTube's/Netflix's handlers
    for fullscreen silently no-op. Input.dispatchKeyEvent goes in at the
    browser level and does carry activation."""
    k = (key or '').lower()
    vk, code, text = _VK_CODES.get(k, (0, '', key))
    key_name = {'escape': 'Escape', 'esc': 'Escape', 'enter': 'Enter',
                ' ': ' ', 'left': 'ArrowLeft', 'right': 'ArrowRight',
                'up': 'ArrowUp', 'down': 'ArrowDown'}.get(k, key)
    try:
        down = {"type": "keyDown", "key": key_name, "code": code,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                "modifiers": modifiers}
        # With a modifier held the event is a SHORTCUT, not text input —
        # sending "text" makes Chrome treat it as a character and the site's
        # ctrl+key handler never fires.
        if text and not modifiers:
            down["text"] = text
        browser.execute_cdp_cmd("Input.dispatchKeyEvent", down)
        time.sleep(hold)
        browser.execute_cdp_cmd("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": key_name, "code": code,
            "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
            "modifiers": modifiers})
        print(f"[FOCUS] sent trusted key {key_name!r} modifiers={modifiers}")
        return True
    except Exception as e:
        print(f"[FOCUS] trusted key {key!r} failed: {e}")
        return False


def _send_trusted_click(browser, selector: str) -> bool:
    """Trusted mouse press/release at an element's centre, for controls that
    (like fullscreen) require activation rather than a synthetic click."""
    try:
        box = browser.execute_script("""
            const el = document.querySelector(arguments[0]);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return null;
            return {x: r.left + r.width / 2, y: r.top + r.height / 2};
        """, selector)
    except Exception as e:
        print(f"[FOCUS] trusted click probe failed: {e}")
        return False
    if not box:
        print(f"[FOCUS] no element for trusted click: {selector}")
        return False
    try:
        for kind in ("mousePressed", "mouseReleased"):
            browser.execute_cdp_cmd("Input.dispatchMouseEvent", {
                "type": kind, "x": box["x"], "y": box["y"],
                "button": "left", "clickCount": 1})
            time.sleep(0.02)
        print(f"[FOCUS] trusted click at ({box['x']:.0f},{box['y']:.0f}) {selector}")
        return True
    except Exception as e:
        print(f"[FOCUS] trusted click failed: {e}")
        return False


def _await_state(check, timeout: float = 2.0, interval: float = 0.1) -> bool:
    """Poll a predicate until it holds. The single verify primitive shared by
    fullscreen and seek — both settle asynchronously, so checking once
    immediately after dispatch reports failure on a change that did land."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if check():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


def _fullscreen_on(browser) -> bool:
    try:
        return bool(browser.execute_script(
            "return !!(document.fullscreenElement || "
            "document.webkitFullscreenElement);"))
    except Exception:
        return False


def _set_fullscreen(browser, enter: bool, selectors: list[str],
                    key: str | None = None) -> bool:
    """Enter/exit fullscreen, then VERIFY document.fullscreenElement really
    changed before the caller reports success.

    requestFullscreen() requires a transient user activation, so a synthetic
    .click() silently no-ops — that is why this goes through
    _with_user_activation plus trusted input rather than JS clicks."""
    if _fullscreen_on(browser) == enter:
        print(f"[MEDIA] fullscreen already {'on' if enter else 'off'}")
        return True
    _with_user_activation(browser)
    for sel in selectors:
        if _send_trusted_click(browser, sel) and \
                _await_state(lambda: _fullscreen_on(browser) == enter):
            print(f"[MEDIA] fullscreen={enter} verified via {sel}")
            return True
    if key and _send_trusted_key(browser, key) and \
            _await_state(lambda: _fullscreen_on(browser) == enter):
        print(f"[MEDIA] fullscreen={enter} verified via key {key!r}")
        return True
    print(f"[MEDIA] fullscreen={enter} NOT verified — reporting failure")
    return False


def _video_time(browser) -> float | None:
    try:
        return browser.execute_script(
            "const v = document.querySelector('video');"
            "return v ? v.currentTime : null;")
    except Exception:
        return None


def _verify_seek(browser, before: float | None, expect_delta: float) -> bool:
    """Confirm currentTime actually moved in the intended direction by at
    least half the requested amount (playback drift makes exact equality
    unreliable), instead of assuming a dispatched key seeked."""
    if before is None:
        return False
    need = abs(expect_delta) / 2.0

    def moved():
        now = _video_time(browser)
        if now is None:
            return False
        shift = now - before
        return shift >= need if expect_delta > 0 else shift <= -need

    ok = _await_state(moved, timeout=3.0)
    print(f"[MEDIA] seek {expect_delta:+.0f}s from {before:.1f} "
          f"-> {_video_time(browser)} verified={ok}")
    return ok


def _sync_chrome_profile(dest_dir: str):
    """Sync logged-in accounts, preferences, and cookies from main Chrome profile into Akira Chrome profile."""
    dest_profile = os.path.join(dest_dir, "Default")
    if os.path.exists(os.path.join(dest_profile, "Preferences")):
        return  # already synced, avoid disk I/O
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    main_profile_src = os.path.join(local_appdata, "Google", "Chrome", "User Data", "Default")
    if not os.path.exists(main_profile_src):
        return
    os.makedirs(dest_profile, exist_ok=True)
    items = ["Preferences", "Login Data", "Web Data"]
    for item in items:
        src = os.path.join(main_profile_src, item)
        dst = os.path.join(dest_profile, item)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except Exception:
                pass


def _attach_cdp(binary_path: str, port: int, service) -> webdriver.Chrome:
    binary_name = os.path.basename(binary_path).lower()
    if not _port_ready(port):
        user_data_dir = os.environ.get("CHROME_USER_DATA_DIR")
        if not user_data_dir:
            # Dedicated Akira profile to run concurrently without profile lock conflict
            local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
            user_data_dir = os.path.join(local_appdata, "Akira", "AkiraChromeProfile")
            _sync_chrome_profile(user_data_dir)
        
        profile_name = os.environ.get("CHROME_PROFILE", "Default")
        os.makedirs(user_data_dir, exist_ok=True)

        cmd = [
            binary_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            f"--profile-directory={profile_name}",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--restore-last-session=false",
            "--remote-allow-origins=*",
        ]
        subprocess.Popen(cmd)
        for _ in range(25):
            if _port_ready(port):
                break
            time.sleep(0.1)
        else:
            # Retry fallback with dedicated fallback profile directory if primary port failed
            fb_dir = os.path.join(user_data_dir, "FallbackProfile")
            os.makedirs(fb_dir, exist_ok=True)
            cmd[2] = f"--user-data-dir={fb_dir}"
            subprocess.Popen(cmd)
            for _ in range(25):
                if _port_ready(port):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError(f"Browser at {binary_path} did not bind port {port} within 5s")

    options = Options()
    options.binary_location = binary_path
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    try:
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception:
        global _chromedriver_path
        _chromedriver_path = None
        raise


def _attach_cdp_edge(port: int) -> webdriver.Edge:
    if not _port_ready(port):
        for p in psutil.process_iter(["name"]):
            try:
                if p.info["name"] and p.info["name"].lower() == "msedge.exe":
                    _kill_process("msedge.exe")
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        subprocess.Popen([
            EDGE_PATH, f"--remote-debugging-port={port}",
            "--profile-directory=Default", "--no-first-run",
            "--disable-session-crashed-bubble", "--restore-last-session=false",
        ])
        for _ in range(20):
            if _port_ready(port):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"Edge did not bind port {port} within 10s")

    options = EdgeOptions()
    options.binary_location = EDGE_PATH
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    service = EdgeService(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=options)
    return driver


def _get_default_browser() -> str:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            if "brave" in prog_id:   return "brave"
            if "chrome" in prog_id:  return "chrome"
            if "firefox" in prog_id: return "firefox"
            if "edge" in prog_id:    return "edge"
    except Exception:
        pass
    return "edge"


_chromedriver_path: str | None = None


def _chromedriver() -> str:
    """Path to a chromedriver binary MATCHING the installed browser.

    Always resolved through webdriver-manager so a Chrome/Brave auto-update
    can't strand us on a stale driver ("only supports Chrome version 149,
    current browser version is 151..." — the live failure this replaced, which
    came from a hand-dropped chromedriver.exe next to this file being
    preferred over the manager). The bundled exe is now only a LAST-RESORT
    fallback for when the manager itself can't run, e.g. no network.

    Cached per process: install() is a network/disk check and get_browser()
    can be called on every action.
    """
    global _chromedriver_path
    if _chromedriver_path and os.path.exists(_chromedriver_path):
        return _chromedriver_path

    # 1. First check local ~/.wdm cache for latest downloaded chromedriver (instant 0.1ms)
    try:
        wdm_drivers = os.path.expanduser(r"~/.wdm/drivers/chromedriver/win64")
        if os.path.isdir(wdm_drivers):
            def _vkey(s):
                return [int(x) if x.isdigit() else 0 for x in s.split(".")]
            versions = [v for v in os.listdir(wdm_drivers) if os.path.isdir(os.path.join(wdm_drivers, v))]
            if versions:
                versions.sort(key=_vkey, reverse=True)
                for ver in versions:
                    cand = os.path.join(wdm_drivers, ver, "chromedriver-win64", "chromedriver.exe")
                    if os.path.exists(cand):
                        _chromedriver_path = cand
                        return _chromedriver_path
    except Exception:
        pass

    # 2. Check bundled chromedriver.exe next to this file
    local = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
    if os.path.exists(local):
        _chromedriver_path = local
        return _chromedriver_path

    # 3. Clean up any stale webdriver-manager lock files
    try:
        wdm_dir = os.path.expanduser(r"~/.wdm")
        if os.path.isdir(wdm_dir):
            for fname in os.listdir(wdm_dir):
                if fname.startswith(".wdm-lock"):
                    fpath = os.path.join(wdm_dir, fname)
                    if (time.time() - os.path.getmtime(fpath)) > 10.0:
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
    except Exception:
        pass

    # 4. Fallback to online resolution via ChromeDriverManager
    try:
        _chromedriver_path = ChromeDriverManager().install()
        return _chromedriver_path
    except Exception as e:
        print(f"[BROWSER] webdriver-manager failed ({e})")
    local = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
    if os.path.exists(local):
        print("[BROWSER] Falling back to bundled chromedriver.exe")
        _chromedriver_path = local
        return _chromedriver_path

    raise RuntimeError("No usable chromedriver executable found.")


def get_browser(name: str | None = None, incognito: bool = False) -> webdriver.Chrome:
    global _browsers, _last_browser_name
    name = (name or _get_default_browser()).lower().strip()
    key = f"{name}_incognito" if incognito else name

    # return cached driver if alive
    if key in _browsers:
        driver = _browsers[key]
        try:
            _ = driver.title
            _ensure_current_handle(driver)
            _ensure_akira_tab(driver)
            return driver
        except Exception:
            del _browsers[key]

    # create new driver
    if name == "brave":
        svc = Service(_chromedriver())
        if incognito:
            opt = Options()
            opt.binary_location = BRAVE_PATH
            opt.add_argument("--incognito")
            driver = webdriver.Chrome(service=svc, options=opt)
        else:
            driver = _attach_cdp(BRAVE_PATH, 9222, svc)

    elif name == "chrome":
        svc = Service(_chromedriver())
        if incognito:
            opt = Options()
            opt.binary_location = CHROME_PATH
            opt.add_argument("--incognito")
            driver = webdriver.Chrome(service=svc, options=opt)
        else:
            driver = _attach_cdp(CHROME_PATH, 9223, svc)

    elif name == "firefox":
        opt = FirefoxOptions()
        if incognito:
            opt.add_argument("-private")
        driver = webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=opt)

    elif name == "edge":
        if incognito:
            opt = EdgeOptions()
            opt.binary_location = EDGE_PATH
            opt.add_argument("--inprivate")
            driver = webdriver.Edge(service=EdgeService(EdgeChromiumDriverManager().install()), options=opt)
        else:
            driver = _attach_cdp_edge(9224)
    else:
        svc = Service(_chromedriver())
        driver = _attach_cdp(CHROME_PATH, 9223, svc)

    _ensure_akira_tab(driver)
    _browsers[key] = driver
    _last_browser_name = name
    return driver


_warmup_thread: threading.Thread | None = None

def warmup_browser(name: str | None = None) -> None:
    """Pre-warm Chrome browser asynchronously in a background daemon thread.
    
    Eliminates the ~1.5s cold-start latency on the first browser action so that
    opening sites, searching, or drafting emails happens in ~15ms immediately.
    """
    global _warmup_thread
    if _warmup_thread and _warmup_thread.is_alive():
        return

    def _do_warmup():
        try:
            t0 = time.perf_counter()
            _ = get_browser(name)
            dt_ms = (time.perf_counter() - t0) * 1000
            print(f"[BROWSER] Chrome pre-warmed & attached in {dt_ms:.1f}ms (ready for instant actions)")
        except Exception as e:
            print(f"[BROWSER] Background browser pre-warmup warning: {e}")

    _warmup_thread = threading.Thread(target=_do_warmup, daemon=True, name="AkiraBrowserWarmup")
    _warmup_thread.start()


# Note: warmup_browser() is called explicitly at runtime in akira.py, not on module import



def _navigate(url: str) -> None:
    """Navigate Akira's dedicated tab to a URL. Never touches user's other tabs."""
    browser = get_browser(_last_browser_name)
    akira_tab = getattr(browser, "_akira_tab", None)
    if akira_tab:
        try:
            if browser.current_window_handle != akira_tab:
                browser.switch_to.window(akira_tab)
        except Exception:
            pass
    try:
        browser.execute_cdp_cmd("Page.navigate", {"url": url})
    except Exception:
        browser.get(url)


_NAV_ALIASES = {
    'back': 'back', 'go back': 'back', 'back button': 'back',
    'previous page': 'back', 'go back a page': 'back',
    'forward': 'forward', 'go forward': 'forward',
    'forward button': 'forward', 'next page': 'forward',
    'reload': 'reload', 'refresh': 'reload', 'reload page': 'reload',
    'refresh page': 'reload', 'refresh the page': 'reload',
    'reload the page': 'reload',
}


def browser_control(parameter: str) -> dict:
    """Real browser history navigation: back / forward / reload.

    Exists because there was previously NO nav handler at all, so "go back"
    fell through to the click pipeline, missed in the DOM, and hit the
    coordinate-guessing fallback — which once clicked the editor instead of
    the browser. History navigation is never a DOM hunt.

    Uses _ensure_target_tab (not _with_user_activation): navigation needs the
    right TAB, not OS foreground, so this never steals focus from the user.
    Verifies the URL actually changed before reporting success."""
    key = (parameter or 'back').strip().lower()
    op = _NAV_ALIASES.get(key)
    if not op:
        op = next((v for k, v in _NAV_ALIASES.items() if k in key), None)
    if not op:
        return {"success": False, "message": f"I don't know how to '{parameter}'."}

    browser = get_browser(_last_browser_name)
    before = _ensure_target_tab(browser)
    if before is None:
        return {"success": False, "message": "I couldn't reach a browser tab."}

    try:
        getattr(browser, {'back': 'back', 'forward': 'forward',
                          'reload': 'refresh'}[op])()
    except Exception as e:
        print(f"[NAV] {op} failed: {e}")
        return {"success": False, "message": f"Couldn't go {op}: {e}"}

    # A reload lands on the SAME url, so settle on readyState instead.
    if op == 'reload':
        ok = _await_state(lambda: browser.execute_script(
            "return document.readyState") == "complete", timeout=8.0)
        print(f"[NAV] reload complete={ok} url={before[:60]}")
        return {"success": ok,
                "message": "Reloaded." if ok else "The page is still loading."}

    changed = _await_state(
        lambda: (browser.current_url or "") != before, timeout=5.0)
    after = browser.current_url if changed else before
    print(f"[NAV] {op}: {before[:50]} -> {after[:50]} changed={changed}")
    if not changed:
        end = "the start of" if op == 'back' else "the end of"
        return {"success": False,
                "message": f"Nothing to go {op} to — this is {end} the history."}
    return {"success": True, "message": f"Went {op}."}


def get_current_site(driver) -> str | None:
    try:
        domain = urllib.parse.urlparse(driver.current_url).netloc.replace("www.", "")
        for key, site in SITE_DOMAINS.items():
            if key in domain:
                return site
    except Exception:
        pass
    return None


def get_foreground_app() -> str | None:
    """Returns the process name of the currently focused window, or None."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name()
    except Exception:
        return None


def get_pc_context() -> dict:
    """Lightweight inventory of open windows and running applications.
    
    Zero browser action, zero CDP port polling. Browser tab inspection happens
    lazily right before a browser action executes.
    """
    windows = []
    try:
        windows = [w.title for w in gw.getAllWindows() if w.title.strip()][:10]
    except Exception:
        pass

    return {
        "open_windows": windows,
        "current_url": None,
        "current_page_title": None,
        "foreground_app": get_foreground_app(),
    }


def get_all_tabs() -> list[dict]:
    """Read all open tabs via CDP debug port — zero handle switching."""
    for port in [9222, 9223, 9224]:
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/json", timeout=1)
            return [
                {"title": t.get("title", ""), "url": t.get("url", "")}
                for t in resp.json()
                if t.get("type") == "page"
            ]
        except Exception:
            continue
    return []


# ── Element extraction — moved to dom_extract.py so the production
# extraction and the headless verification harness share ONE implementation.
# probe_element powers the O(1) staleness check in click_element.
from dom_extract import extract_interactive_elements, probe_element


# ── No-match reporting ────────────────────────────────────────────────────────

def _no_match_report(instruction: str, elements: list[dict], limit: int = 6) -> str:
    """Honest failure for a DOM/structural miss: say so and list what IS here.

    This replaces the old screenshot-and-guess-coordinates fallback, which
    clicked whatever window happened to hold OS focus (it once hit the editor
    instead of the browser). A miss is now reported, never guessed."""
    print(f"[CLICK] no match for '{instruction}' — reporting candidates")
    seen, names = set(), []
    for el in elements:
        text = (el.get('text') or '').strip()
        if not text or text.lower() in seen or len(text) < 2:
            continue
        seen.add(text.lower())
        names.append(text[:40])
        if len(names) >= limit:
            break
    if not names:
        return f"I couldn't find '{instruction}', and I don't see anything clickable on this page."
    return (f"I couldn't find '{instruction}' on this page. "
            f"I can see: {', '.join(names)}.")


# ── Atomic click ──────────────────────────────────────────────────────────────

def atomic_click(driver, text: str | None = None, href: str | None = None) -> bool:
    """Find AND click in ONE script execution — no staleness window.
    data-akira-index attributes die when SPAs (YouTube especially) re-stamp
    their DOM nodes during the LLM-match round-trip; re-finding by href/text
    at click time inside the same JS pass is immune to that."""
    if not text and not href:
        return False
    return bool(driver.execute_script("""
        const text = arguments[0], href = arguments[1];
        function visible(el) {
            const r = el.getBoundingClientRect();
            return r.width > 4 && r.height > 4;
        }
        if (href) {
            for (const a of document.querySelectorAll('a[href]')) {
                if (a.href === href && visible(a)) { a.click(); return true; }
            }
        }
        if (text) {
            const t = text.replace(/\\s+/g,' ').trim().toLowerCase();
            const sel = 'a[href], button, [role="button"], [role="menuitem"], [role="tab"], [role="option"], [onclick]';
            let best = null;
            for (const el of document.querySelectorAll(sel)) {
                if (!visible(el)) continue;
                const et = (el.innerText || el.textContent || el.getAttribute('aria-label') || '')
                           .replace(/\\s+/g,' ').trim().toLowerCase();
                if (!et) continue;
                if (et === t) { el.click(); return true; }
                if (!best && (et.includes(t) || t.includes(et)) && Math.min(et.length, t.length) > 3) best = el;
            }
            if (best) { best.click(); return true; }
        }
        return false;
    """, text, href))


# ── Click element (CDP path) ───────────────────────�������──────��───────────────────

def click_element(driver, index: int, expected_text: str | None = None,
                  expected_href: str | None = None, instruction: str | None = None,
                  elements: list | None = None) -> dict:
    """
    Click element at index. Validates staleness, checks RISKY_KEYWORDS.
    A miss returns a failure for the caller to report — there is no
    coordinate-guessing fallback anywhere in the click path.

    Staleness is checked with an O(1) single-node probe first — the old
    unconditional full-page re-extraction between match and click doubled
    per-click latency even when nothing on the page had changed. Only a
    failed probe pays for the full re-extract + re-match.
    """
    probe = probe_element(driver, index)
    # href is the strongest identity signal (probe text can legitimately
    # differ from extraction text for image anchors, whose extraction text
    # prefers the img alt attribute) �� compare text only when there's no href.
    stale = probe is None or (
        (expected_href is not None and probe.get("href") != expected_href) or
        (expected_href is None and expected_text is not None and
         probe.get("text") != expected_text)
    )

    if not stale:
        current = (elements[index] if elements and index < len(elements)
                   else {"index": index, "text": probe.get("text") or "",
                         "href": probe.get("href")})
    else:
        print(f"[CLICK] probe stale for index {index} — full re-extract")
        fresh = extract_interactive_elements(driver, max_elements=200)
        if instruction:
            from element_matcher import find_element_index
            new_idx = find_element_index(fresh, instruction)
            if new_idx is None or new_idx >= len(fresh):
                return {"success": False, "reason": "element changed and re-match failed"}
            index = new_idx
            current = fresh[index]
        elif index < len(fresh):
            current = fresh[index]
        else:
            return {"success": False, "reason": "element changed, no instruction to re-match"}

    needs_confirmation = bool(_risky_pattern.search(current["text"]))

    # use JS click — avoids ElementNotInteractableException
    def _do_click():
        clicked = driver.execute_script(f"""
            var el = document.querySelector('[data-akira-index="{index}"]');
            if (el) {{ el.click(); return true; }}
            return false;
        """)
        if not clicked:
            # attribute gone = SPA re-stamped the node during the LLM
            # round-trip (YouTube does this constantly). Re-find by the
            # element's OWN text/href atomically instead of failing.
            print(f"[CLICK] index {index} attribute stale — atomic re-find by text/href")
            if atomic_click(driver, text=current.get("text"), href=current.get("href")):
                return
            els = driver.find_elements(By.CSS_SELECTOR, f'[data-akira-index="{index}"]')
            if els:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", els[0])
                driver.execute_script("arguments[0].click();", els[0])
            else:
                raise RuntimeError(f"element at index {index} not found in DOM after injection")

    return {
        "success": True,
        "needs_confirmation": needs_confirmation,
        "element": current,
        "_execute": _do_click,
    }


# ── YouTube control ───────────────────────────────────────────────────────────

_last_youtube_tab_handle = None

def youtube_control(parameter: str) -> str:
    global _last_youtube_tab_handle
    browser = get_browser(_last_browser_name)
    param_raw = parameter.strip()
    param = param_raw.lower()

    # Support optional explicit tab handle in parameter e.g. "like|CDwindow-..."
    tab_override = None
    if "|" in param_raw:
        parts = param_raw.split("|", 1)
        param = parts[0].strip().lower()
        tab_override = parts[1].strip()

    target_handle = tab_override or getattr(browser, "_youtube_target_tab", None) or _last_youtube_tab_handle

    is_open_or_play = ((param.startswith("play ") and param not in ("play", "playing", "play video"))
                       or param.startswith("search ")
                       or param.startswith("search and play ")
                       or param.startswith("search and pick "))

    if not is_open_or_play:
        # Follow-up actions (like, subscribe, pause, etc.) MUST target the exact same tab/window handle
        if target_handle:
            if target_handle not in browser.window_handles:
                print(f"[youtube_control] guard fired: target handle {target_handle!r} not in {browser.window_handles}")
                return "Target tab lost."
            browser.switch_to.window(target_handle)
            browser._akira_tab = target_handle
        else:
            if "youtube.com" not in (browser.current_url or ""):
                print("[youtube_control] guard fired: no target tab and current window not on youtube")
                return "Target tab lost."

        if "youtube.com" not in (browser.current_url or ""):
            print("[youtube_control] guard fired: targeted tab is not on youtube.com")
            return "Target tab lost."
    else:
        if target_handle and target_handle in browser.window_handles:
            browser.switch_to.window(target_handle)
            browser._akira_tab = target_handle
        elif "youtube.com" not in (browser.current_url or ""):
            for handle in browser.window_handles:
                try:
                    browser.switch_to.window(handle)
                    if "youtube.com" in (browser.current_url or ""):
                        browser._akira_tab = handle
                        break
                except Exception:
                    pass

    try:
        if getattr(browser, "_akira_tab", None):
            browser.switch_to.window(browser._akira_tab)
        WebDriverWait(browser, 8).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass

    # ── Group 0: Direct Video Search & Auto-Play ───────────────────────────
    if is_open_or_play:
        query_str = re.sub(r"^(?:play|search(?:\s+and\s+(?:play|pick))?)\s+", "", param).strip()
        query = urllib.parse.quote(query_str)
        url = f"https://www.youtube.com/results?search_query={query}"
        browser.get(url)
        _last_youtube_tab_handle = browser.current_window_handle
        browser._youtube_target_tab = _last_youtube_tab_handle
        try:
            WebDriverWait(browser, 6).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "ytd-video-renderer a#video-title, a#video-title")))
            first_video = browser.find_element(By.CSS_SELECTOR, "ytd-video-renderer a#video-title, a#video-title")
            first_video.click()
            _last_youtube_tab_handle = browser.current_window_handle
            browser._youtube_target_tab = _last_youtube_tab_handle
            return f"Playing '{query_str}' on YouTube."
        except Exception:
            return f"Opened YouTube search results for '{query_str}'."

    if "youtube.com" not in (browser.current_url or ""):
        return "Target tab lost."

    # ── Aliases: Map skip forward / back / rewind to seek ──────────────────
    if param in ("skip forward", "skip ahead", "fast forward"):
        param = "seek 10"
    elif param in ("skip back", "skip backward", "rewind", "go back 10"):
        param = "seek -10"
    elif re.match(r"^(?:skip forward|fast forward)\s+(\d+)", param):
        m_skip = re.match(r"^(?:skip forward|fast forward)\s+(\d+)", param)
        param = f"seek {m_skip.group(1)}"
    elif re.match(r"^(?:skip back|rewind)\s+(\d+)", param):
        m_skip = re.match(r"^(?:skip back|rewind)\s+(\d+)", param)
        param = f"seek -{m_skip.group(1)}"

    # ── Group A: JS media controls — zero API cost ────────────────────

    if param in ("play", "pause", "resume"):
        # STATE-AWARE: v.pause()/v.play() are deterministic (video.click()
        # was a blind toggle — two 'pause' commands in a row would pause
        # then secretly resume). Reports actual state instead of "Done."
        state = browser.execute_script("""
            const v = document.querySelector('video');
            if (!v) return 'novideo';
            const wantPause = arguments[0] === 'pause';
            if (wantPause) {
                if (v.paused) return 'already_paused';
                v.pause(); return 'paused';
            }
            if (!v.paused) return 'already_playing';
            v.play(); return 'playing';
        """, param)
        return {"novideo": "There's no video on this page.",
                "already_paused": "It's already paused.",
                "paused": "Paused.",
                "already_playing": "It's already playing.",
                "playing": "Playing."}.get(state, "Done.")

    if param in ("next", "next video", "skip"):
        browser.execute_script("const btn = document.querySelector('.ytp-next-button'); if(btn) btn.click();")
        return "Skipped to next video."

    if param in ("like", "like video", "like song"):
        browser.execute_script("""
            const btn = document.querySelector('like-button-view-model button, button[title*="like"], button[aria-label*="like"]');
            if (btn) btn.click();
        """)
        return "Liked the video."

    if param in ("dislike", "dislike video"):
        browser.execute_script("""
            const btn = document.querySelector('dislike-button-view-model button, button[title*="dislike"], button[aria-label*="dislike"]');
            if (btn) btn.click();
        """)
        return "Disliked the video."

    if param in ("comments", "comment", "comments section", "open comments"):
        browser.execute_script("""
            const section = document.querySelector('#comments, ytd-comments');
            if (section) { section.scrollIntoView({behavior: 'smooth'}); }
        """)
        return "Scrolled to comments section."

    if param in ("sign_in", "signin", "login", "log in"):
        browser.execute_script("""
            const btn = document.querySelector('ytd-masthead a[href*="accounts.google.com"], a[aria-label*="Sign in"]');
            if (btn) btn.click();
            else window.location.href = "https://accounts.google.com";
        """)
        return "Opening YouTube sign-in page."

    if param == "skip ad":
        browser.execute_script("""
            var btn = document.querySelector('.ytp-skip-ad-button,.ytp-ad-skip-button,.ytp-ad-skip-button-modern');
            if (btn) btn.click();
        """)
        return "Ad skipped."

    if param.startswith("volume") or param in ("volume up", "volume down"):
        if "up" in param:
            browser.execute_script("var v=document.querySelector('video'); if(v) v.volume = Math.min(1, v.volume + 0.1);")
            return "Volume increased."
        if "down" in param:
            browser.execute_script("var v=document.querySelector('video'); if(v) v.volume = Math.max(0, v.volume - 0.1);")
            return "Volume decreased."
        try:
            cleaned = re.sub(r"[^\d]", "", param)
            if not cleaned:
                return "Give me a volume number from 0 to 100."
            val = max(0, min(100, int(cleaned)))
            browser.execute_script(f"var v=document.querySelector('video'); if(v) v.volume={val/100};")
            return f"Video volume {val}%."
        except ValueError:
            return "Give me a number."

    if param == "mute video":
        browser.execute_script("var v=document.querySelector('video'); if(v) v.muted=true;")
        return "Video muted."

    if param == "unmute video":
        browser.execute_script("var v=document.querySelector('video'); if(v) v.muted=false;")
        return "Video unmuted."

    if param in ("fullscreen", "full screen"):
        # requestFullscreen() needs a real user activation, so the old
        # synthetic .click() no-oped while still reporting "Fullscreen."
        ok = _set_fullscreen(browser, True, ['.ytp-fullscreen-button'], key="f")
        return "Fullscreen." if ok else \
               "I pressed fullscreen but the player didn't enter it."

    if param in ("theatre mode", "theater mode", "theatre", "theater"):
        # Theatre is a YouTube-side layout class, not the fullscreen API —
        # verify the player's theater flag actually flipped.
        def _theater():
            return bool(browser.execute_script(
                "const w = document.querySelector('ytd-watch-flexy');"
                "return w ? w.hasAttribute('theater') : null;"))
        if _theater():
            return "Already in theatre mode."
        _with_user_activation(browser)
        _send_trusted_click(browser, '.ytp-size-button')
        ok = _await_state(_theater)
        return "Theatre mode." if ok else "I couldn't switch to theatre mode."

    if param in ("default view", "exit fullscreen", "exit theatre", "exit theater"):
        if _fullscreen_on(browser):
            ok = _set_fullscreen(browser, False, ['.ytp-fullscreen-button'],
                                 key="escape")
            return "Default view." if ok else \
                   "I couldn't get out of fullscreen."
        _with_user_activation(browser)
        _send_trusted_click(browser, '.ytp-size-button')
        ok = _await_state(lambda: not browser.execute_script(
            "const w = document.querySelector('ytd-watch-flexy');"
            "return w ? w.hasAttribute('theater') : false;"))
        return "Default view." if ok else "I couldn't restore the default view."

    if param.startswith("speed "):
        speeds = {"0.25": 0.25, "0.5": 0.5, "0.75": 0.75, "normal": 1, "1": 1,
                  "1.25": 1.25, "1.5": 1.5, "1.75": 1.75, "2": 2, "2x": 2}
        val = param.replace("speed", "").strip()
        rate = speeds.get(val)
        if rate:
            browser.execute_script(f"var v=document.querySelector('video'); if(v) v.playbackRate={rate};")
            return f"Speed {val}."
        return "Valid speeds: 0.25, 0.5, 0.75, normal, 1.25, 1.5, 1.75, 2."

    if param in ("captions on", "subtitles on", "cc on"):
        browser.execute_script("document.querySelector('.ytp-subtitles-button')?.click();")
        return "Captions on."

    if param in ("captions off", "subtitles off", "cc off"):
        browser.execute_script("""
            var btn=document.querySelector('.ytp-subtitles-button');
            if(btn&&btn.getAttribute('aria-pressed')==='true') btn.click();
        """)
        return "Captions off."

    if param == "loop":
        browser.execute_script("var v=document.querySelector('video'); if(v) v.loop=!v.loop;")
        return "Loop toggled."

    if param.startswith("seek "):
        try:
            seconds = int(param.replace("seek", "").replace("s", "").strip())
        except ValueError:
            return "Give me seconds to seek."
        before = _video_time(browser)
        if before is None:
            return "There's no video on this page to seek."
        browser.execute_script(
            "const v = document.querySelector('video');"
            "if (v) v.currentTime += arguments[0];", seconds)
        # Verify currentTime really moved: a live stream or an unbuffered
        # region silently refuses the assignment.
        if _verify_seek(browser, before, seconds):
            return f"Seeked {seconds}s."
        return "I couldn't seek this video."

    # Nav goes through the one history-navigation implementation.
    if param in ("go back", "go forward"):
        return browser_control(param)["message"]

    if param.startswith("search "):
        query = urllib.parse.quote(param.replace("search", "").strip())
        browser.execute_script(f"window.location.href='https://www.youtube.com/results?search_query={query}';")
        return "Searching YouTube."

    if param.startswith("go to channel"):
        channel = param.replace("go to channel", "").strip()
        if not channel:
            # The channel link under a watch-page title is a stable element —
            # no reason to guess at screen coordinates for it.
            clicked = browser.execute_script("""
                for (const q of ['ytd-video-owner-renderer a[href]',
                                 '#owner #channel-name a[href]',
                                 'ytd-channel-name a[href]']) {
                    const el = document.querySelector(q);
                    if (el) { el.click(); return true; }
                }
                return false;
            """)
            return "Going to channel." if clicked else \
                   "I can't see a channel link on this page."
        query = urllib.parse.quote(channel)
        browser.execute_script(f"window.location.href='https://www.youtube.com/results?search_query={query}+channel';")
        return f"Searching for {channel}'s channel."

    # ── Group B: play video — DOM matching only ───────────────────────────────

    if param.startswith("play video") or param.startswith("click video"):
        description = param.replace("play video", "").replace("click video", "").strip()
        time.sleep(0.8)
        elements = extract_interactive_elements(browser, max_elements=150)
        from element_matcher import find_element_index
        idx = find_element_index(elements, description)
        if idx is None or idx >= len(elements):
            return "Couldn't find that video on the page."
        target = elements[idx]
        print(f"[YT] play-video matched idx={idx} text={target.get('text', '')[:60]!r} href={target.get('href')!r}")
        # data-akira-index dies during the LLM round-trip (YouTube re-stamps
        # its renderer nodes) — so NEVER click by index here. We already have
        # the video's href from extraction: navigating is 100% equivalent to
        # clicking a thumbnail and cannot go stale.
        href = target.get("href")
        if href and "watch" in href:
            browser.execute_script("window.location.href = arguments[0];", href)
            return f"Playing {target.get('text') or description}."
        # non-video match (channel, playlist, button) — atomic find+click
        if atomic_click(browser, text=target.get("text"), href=href):
            return f"Opening {target.get('text') or description}."
        return "Couldn't find that video on the page."

    # ── Group C: common controls — DOM matching only ─────────────────────

    # Map common commands to DOM selectors
    simple_actions = {
        "like": ".ytp-like-button, button[aria-label*='like' i]",
        "dislike": ".ytp-dislike-button, button[aria-label*='dislike' i]",
        "subscribe": "button[aria-label*='subscribe' i]:not([aria-label*='unsubscribe' i])",
        "unsubscribe": "button[aria-label*='unsubscribe' i]",
        "share": "button[aria-label*='share' i]",
        "save": "button[aria-label*='save' i]",
        "play next": ".ytp-next-button",
        "next video": ".ytp-next-button",
        "open comments": "#comments",
        "home": "a[title='Home' i]",
        "music": "a[title='Music' i]",
        "gaming": "a[title='Gaming' i]",
        "live": "a[title='Live' i]",
        "news": "a[title='News' i]",
    }
    
    if param in simple_actions:
        selector = simple_actions[param]
        clicked = browser.execute_script("""
            var el = document.querySelector(arguments[0]);
            if (el) { el.click(); return true; }
            return false;
        """, selector)
        return "Done." if clicked else f"Couldn't find {param}."
    
    # Menu items that need menu to be opened first. Menu item labels are
    # KNOWN text — atomic_click matches them directly in one JS pass, no
    # extract+LLM+stale-index round-trip needed at all.
    _menu_labels = {"ambient mode": "Ambient mode", "sleep timer": "Sleep timer",
                    "quality": "Quality", "playback speed menu": "Playback speed"}
    if param in _menu_labels:
        browser.execute_script("document.querySelector('.ytp-settings-button')?.click();")
        time.sleep(0.5)
        if atomic_click(browser, text=_menu_labels[param]):
            return "Done."
        return f"Couldn't find {param} in settings."

    if param in {"switch account", "sign out"}:
        browser.execute_script("document.querySelector('button#avatar-btn')?.click();")
        time.sleep(0.7)
        if atomic_click(browser, text=param.title() if param == "switch account" else "Sign out"):
            return "Done."
        return f"Couldn't find {param} in account menu."
    
    # If we get here, command not recognized
    return f"Don't know how to do '{param}' on YouTube."


# ── Netflix control ───────────────────────────────────────────────────���───────

# Netflix's internal player API (stable since ~2017, used by every Netflix
# extension). Gives direct play/pause/seek/volume/track control — far more
# reliable than clicking UI buttons that Netflix hides and re-renders.
_NFX_PLAYER_JS = """
function __nfxPlayer() {
    try {
        var vp = netflix.appContext.state.playerApp.getAPI().videoPlayer;
        var ids = vp.getAllPlayerSessionIds() || [];
        var sid = null;
        for (var i = 0; i < ids.length; i++) {
            if (String(ids[i]).indexOf('watch') === 0) { sid = ids[i]; break; }
        }
        if (sid === null && ids.length > 0) sid = ids[0];
        if (sid === null) return null;
        return vp.getVideoPlayerBySessionId(sid);
    } catch (e) { return null; }
}
"""


def _nfx_js(browser, body: str, *args):
    """Run JS on the Netflix tab with the __nfxPlayer() helper prepended."""
    return browser.execute_script(_NFX_PLAYER_JS + body, *args)


def _nfx_reveal_controls(browser):
    """Netflix hides player chrome after inactivity; synthesize mouse movement
    so control buttons exist in the DOM before we try to click them."""
    try:
        browser.execute_script("""
            var t = document.querySelector('.watch-video') || document.body;
            ['mousemove', 'mouseover'].forEach(function (ev) {
                t.dispatchEvent(new MouseEvent(ev, {
                    bubbles: true, cancelable: true,
                    clientX: Math.floor(window.innerWidth / 2),
                    clientY: Math.floor(window.innerHeight / 2)
                }));
            });
        """)
        time.sleep(0.5)
    except Exception:
        pass


def _nfx_click_first(browser, selectors: list) -> str | None:
    """Click the first VISIBLE element matching any selector in order.
    Returns the selector that matched, or None."""
    try:
        return browser.execute_script("""
            var sels = arguments[0];
            for (var i = 0; i < sels.length; i++) {
                var els = document.querySelectorAll(sels[i]);
                for (var j = 0; j < els.length; j++) {
                    if (els[j].offsetParent !== null) { els[j].click(); return sels[i]; }
                }
            }
            return null;
        """, selectors)
    except Exception:
        return None


def _nfx_parse_seconds(text: str) -> int | None:
    """Parse '90', '1:30', '1:02:03', '45 minutes', '1 hour' into seconds."""
    if not text:
        return None
    t = text.strip().lower()
    if ":" in t:
        try:
            parts = [int(p) for p in t.split(":")]
            secs = 0
            for p in parts:
                secs = secs * 60 + p
            return secs
        except ValueError:
            return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(hour|hr|h|minute|min|m|second|sec|s)?", t)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2) or "s"
    if unit in ("hour", "hr", "h"):
        return int(val * 3600)
    if unit in ("minute", "min", "m"):
        return int(val * 60)
    return int(val)


def _nfx_collect_cards(browser) -> list:
    """Collect title cards from search/browse pages as [{label, id}].
    Netflix wraps every result in .title-card with an <a> whose href
    contains /watch/<id>, ?jbv=<id>, or /title/<id>."""
    try:
        return browser.execute_script(r"""
            var seen = {};
            var out = [];
            var links = document.querySelectorAll(
                '.title-card a[href], [data-uia*="title-card"] a[href]');
            if (links.length === 0) {
                links = document.querySelectorAll(
                    'a[href*="/watch/"], a[href*="jbv="], a[href*="/title/"]');
            }
            for (var i = 0; i < links.length; i++) {
                var href = links[i].getAttribute('href') || '';
                var m = href.match(/\/watch\/(\d+)/) ||
                        href.match(/[?&]jbv=(\d+)/) ||
                        href.match(/\/title\/(\d+)/);
                if (!m) continue;
                if (seen[m[1]]) continue;
                seen[m[1]] = true;
                var label = links[i].getAttribute('aria-label') ||
                            (links[i].textContent || '').trim();
                if (!label) {
                    var img = links[i].querySelector('img[alt]');
                    if (img) label = img.getAttribute('alt');
                }
                out.push({ label: label || ('Title ' + m[1]), id: m[1] });
            }
            return out;
        """) or []
    except Exception:
        return []


def _pick_card(cards: list, parameter: str | None):
    """Shared picker for Netflix/Amazon/Flipkart result cards.
    Picks by ordinal ('first', '2') or fuzzy name match. Defaults to first."""
    if not cards:
        return None
    if not parameter:
        return cards[0]
    p = parameter.strip().lower()
    ordinals = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
                "fourth": 3, "4th": 3, "fifth": 4, "5th": 4}
    if p in ordinals:
        idx = ordinals[p]
        return cards[idx] if idx < len(cards) else cards[0]
    if p.isdigit():
        idx = int(p) - 1
        return cards[idx] if 0 <= idx < len(cards) else cards[0]
    # fuzzy name match: substring first, then token overlap
    for c in cards:
        if p in (c.get("label") or "").lower():
            return c
    p_tokens = set(p.split())
    best, best_score = None, 0
    for c in cards:
        score = len(p_tokens & set((c.get("label") or "").lower().split()))
        if score > best_score:
            best, best_score = c, score
    return best or cards[0]


def _shop_guarded_click(browser, el, spoken_name: str, retry_param: str,
                        pre_confirmed: bool = False) -> dict:
    """Shared risky-keyword recheck before any direct shopping click.
    pre_confirmed=True skips the recheck — used ONLY by checkout/address
    branches, which akira.py's safety net ALWAYS gates behind a spoken yes."""
    try:
        text = (el.text or el.get_attribute("value") or
                el.get_attribute("aria-label") or spoken_name).strip()
    except Exception:
        text = spoken_name
    if not pre_confirmed and _risky_pattern.search(text):
        def _do():
            browser.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            el.click()
        return {
            "needs_click_confirmation": True,
            "element_text": text[:80],
            "_execute": _do,
            "retry_parameter": retry_param,
        }
    try:
        browser.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.click()
        return {"success": True, "message": f"Clicked {spoken_name}."}
    except Exception as e:
        return {"success": False, "message": f"Couldn't click {spoken_name}: {e}"}


def _nfx_menu_select(browser, opener_selectors: list, item_prefixes: list, parameter: str) -> dict:
    """Open a player overlay menu and click the item whose data-uia or text
    matches `parameter`. Uses stable data-uia attributes (e.g.
    subtitle-item-English, audio-item)."""
    _nfx_reveal_controls(browser)
    opened = _nfx_click_first(browser, opener_selectors)
    if not opened:
        return {"success": False, "message": "Couldn't open the menu — make sure a video is playing."}
    time.sleep(0.8)  # overlay render
    try:
        result = browser.execute_script("""
            var prefixes = arguments[0];
            var want = String(arguments[1]).toLowerCase();
            var available = [];
            for (var k = 0; k < prefixes.length; k++) {
                var items = document.querySelectorAll('[data-uia^="' + prefixes[k] + '"]');
                for (var i = 0; i < items.length; i++) {
                    var uia = (items[i].getAttribute('data-uia') || '').toLowerCase();
                    var txt = (items[i].textContent || '').trim();
                    available.push(txt);
                    if (uia.indexOf(want) !== -1 || txt.toLowerCase().indexOf(want) !== -1) {
                        items[i].click();
                        return { ok: true, name: txt };
                    }
                }
            }
            return { ok: false, names: available };
        """, item_prefixes, parameter)
    except Exception as e:
        result = {"ok": False, "err": str(e)}
    # Close the overlay either way by nudging the mouse away
    try:
        browser.execute_script("""
            document.body.dispatchEvent(new MouseEvent('mousemove',
                { bubbles: true, clientX: 5, clientY: 5 }));
        """)
    except Exception:
        pass
    if result and result.get("ok"):
        return {"success": True, "message": f"Selected {result.get('name') or parameter}."}
    names = ", ".join((result or {}).get("names", [])[:8])
    extra = f" Available options: {names}." if names else ""
    return {"success": False, "message": f"Couldn't find '{parameter}' in the menu.{extra}"}


def netflix_control(action: str, parameter: str | None = None) -> dict:
    """
    Complete Netflix automation. Dispatch groups:

    BROWSE/SEARCH (any Netflix page):
      search|query            -> go to search results, report top titles
      play_result|first/name  -> play a search/home result by ordinal or name
      play_title|name         -> search a title and play the best match
      open_title|name         -> open the title's detail page without playing

    PLAYER (watch page, via Netflix's internal player API):
      play, pause, mute, unmute
      volume|0.7 / volume|up / volume|down
      seek|1:02:03 (absolute) — also '45 minutes', '3600'
      skip forward|30 / skip back|30 (default 10s)
      playback speed|1.5
      now playing              -> reports title + timestamp

    PLAYER UI (stable data-uia selectors + keyboard fallbacks):
      fullscreen, exit fullscreen, next episode, skip intro
      subtitle|English / subtitle|off
      audio|English
      episodes|Episode 5
      back to browse

    PROFILES:
      switch profile|name     -> delegates to structural_ui (fuzzy name match)

    Returns {'success': bool, 'message': str}.
    """
    print(f"[netflix_control] called with action={action!r}, parameter={parameter!r}")
    browser = get_browser(_last_browser_name)

    try:
        browser.switch_to.window(browser._akira_tab)
    except Exception:
        return {"success": False, "message": "Lost track of my working tab."}
    try:
        WebDriverWait(browser, 0.5).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass

    try:
        current_url = browser.current_url or ""
    except Exception:
        return {"success": False, "message": "Could not read current URL"}

    action = (action or "").strip().lower().replace("_", " ")
    on_watch_page = "/watch/" in current_url

    # ── PROFILES ────────────────────────────────────────────────────────────
    # Delegated so profile picking has ONE implementation (fuzzy name match
    # over structurally-extracted profiles) shared with the generic click path.
    if action in ("switch profile", "change profile", "profile"):
        from structural_ui import resolve_structural
        return resolve_structural(browser, ('profile', (parameter or "").strip()))

    # ── BROWSE / SEARCH actions (navigate, so they work from any page) ──────
    if action == "search":
        if not parameter:
            return {"success": False, "message": "Search needs a query."}
        _navigate("https://www.netflix.com/search?q=" + urllib.parse.quote(parameter))
        return {"success": True, "message": f"Browsing {parameter} on Netflix."}

    if action in ("play result", "open result", "click result"):
        if "netflix.com" not in current_url:
            return {"success": False, "message": "Not a Netflix tab. Switch to Netflix first."}
        cards = _nfx_collect_cards(browser)
        if not cards:
            return {"success": False, "message": "I don't see any titles on this page. Try searching first."}
        pick = _pick_card(cards, parameter)
        if action == "open result":
            browser.get(f"https://www.netflix.com/title/{pick['id']}")
            return {"success": True, "message": f"Opened {pick['label']}."}
        browser.get(f"https://www.netflix.com/watch/{pick['id']}")
        try:
            WebDriverWait(browser, 12).until(
                EC.presence_of_element_located((By.TAG_NAME, "video")))
        except Exception:
            pass
        return {"success": True, "message": f"Playing {pick['label']}."}

    if action in ("direct play", "play direct", "quick play", "play title", "open title") or (action == "play" and parameter):
        name = parameter
        if not name:
            return {"success": False, "message": "Tell me what title to play."}

        req_clean = name.strip().lower()

        # Fast path 1: Direct Netflix URL or numeric ID pattern
        id_m = re.search(r"(?:netflix\.com/(?:watch|title)/)?(\d{6,})", name.strip())
        if id_m:
            direct_id = id_m.group(1)
            browser.get(f"https://www.netflix.com/watch/{direct_id}")
            try:
                WebDriverWait(browser, 12).until(
                    EC.presence_of_element_located((By.TAG_NAME, "video")))
            except Exception:
                pass
            return {"success": True, "message": f"Playing {direct_id} directly on Netflix."}

        # Fast path 2: If already on a Netflix page, check visible cards for unambiguous match
        pick = None
        if "netflix.com" in current_url:
            cards = _nfx_collect_cards(browser)
            if cards:
                top_label = (cards[0].get("label") or "").strip().lower()
                if top_label == req_clean:
                    pick = cards[0]
                    print(f"[netflix_control] Direct play: '{cards[0]['label']}' exact match on screen, skipping search detour.")
                else:
                    import difflib
                    scored = []
                    for idx, card in enumerate(cards):
                        card_label = (card.get("label") or "").strip().lower()
                        sim = difflib.SequenceMatcher(None, req_clean, card_label).ratio()
                        if req_clean in card_label or card_label in req_clean:
                            sim = max(sim, min(0.95, len(req_clean) / max(len(card_label), 1)))
                        scored.append((sim, -idx, card, idx))
                    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
                    if scored and scored[0][0] >= 0.95:
                        pick = scored[0][2]
                        print(f"[netflix_control] Direct play: '{pick['label']}' high match ({scored[0][0]:.3f}) on screen, skipping search detour.")

        if not pick:
            browser.get("https://www.netflix.com/search?q=" + urllib.parse.quote(name))
            try:
                WebDriverWait(browser, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".title-card, [data-uia*='title-card']")))
            except Exception:
                pass
            time.sleep(0.5)
            cards = _nfx_collect_cards(browser)
            if not cards:
                return {"success": False, "message": f"Couldn't find {name} on Netflix."}

        req_clean = name.strip().lower()
        pick = None

        # 2. If top result is exact case-insensitive match, pick immediately
        top_label = (cards[0].get("label") or "").strip().lower()
        if top_label == req_clean:
            pick = cards[0]
            print(f"[netflix_control] Top result {cards[0]['label']!r} is an exact match for requested title {name!r}")
        else:
            # 3. Otherwise, pick highest string-similarity score with result position as tiebreaker
            import difflib
            scored_candidates = []
            for idx, card in enumerate(cards):
                card_label = (card.get("label") or "").strip().lower()
                sim = difflib.SequenceMatcher(None, req_clean, card_label).ratio()
                if req_clean in card_label or card_label in req_clean:
                    sub_ratio = len(req_clean) / max(len(card_label), 1)
                    sim = max(sim, min(0.95, sub_ratio))
                scored_candidates.append((sim, -idx, card, idx))

            scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            best_score, _, best_card, best_pos = scored_candidates[0]

            # 4. Log which candidate was picked and why
            print(f"[netflix_control] Evaluated {len(cards)} candidates for {name!r}: best is {best_card['label']!r} (similarity={best_score:.3f}, position={best_pos})")

            # 5. If nothing clears similarity threshold (0.6), fail loudly
            if best_score < 0.6:
                print(f"[netflix_control] Match failure: no candidate cleared threshold 0.6 for {name!r} (best score {best_score:.3f})")
                return {"success": False, "message": f"Couldn't find a matching title for '{name}' on Netflix."}

            pick = best_card
            print(f"[netflix_control] Picked {pick['label']!r} (score={best_score:.3f}, position={best_pos}) for query {name!r}")

        if action == "open title":
            browser.get(f"https://www.netflix.com/title/{pick['id']}")
            return {"success": True, "message": f"Opened {pick['label']}."}
        browser.get(f"https://www.netflix.com/watch/{pick['id']}")
        try:
            WebDriverWait(browser, 12).until(
                EC.presence_of_element_located((By.TAG_NAME, "video")))
        except Exception:
            pass
        return {"success": True, "message": f"Playing {pick['label']}."}

    # Everything below requires an actual Netflix tab
    if "netflix.com" not in current_url:
        return {"success": False, "message": "Not a Netflix tab. Switch to Netflix first."}

    # ── PLAYER actions via internal API ��───────────────────────────────����────
    if action in ("play", "pause", "resume"):
        op = "pause" if action == "pause" else "play"
        ok = _nfx_js(browser, """
            var p = __nfxPlayer();
            if (!p) return false;
            if (arguments[0] === 'pause') p.pause(); else p.play();
            return true;
        """, op)
        if ok:
            return {"success": True, "message": f"{'Paused' if op == 'pause' else 'Playing'}."}
        # keyboard fallback (space toggles play/pause on the watch page)
        # Space toggles play/pause on the watch page; verify the paused state
        # actually flipped rather than trusting the dispatch.
        if on_watch_page:
            was = browser.execute_script(
                "const v = document.querySelector('video');"
                "return v ? v.paused : null;")
            if _send_trusted_key(browser, " ") and was is not None and \
                    _await_state(lambda: browser.execute_script(
                        "const v = document.querySelector('video');"
                        "return v ? v.paused : null;") is not was):
                return {"success": True, "message": "Toggled playback."}
        return {"success": False, "message": "No video is playing right now."}

    if action in ("mute", "unmute"):
        ok = _nfx_js(browser, """
            var p = __nfxPlayer();
            if (p && p.setMuted) { p.setMuted(arguments[0]); return true; }
            var v = document.querySelector('video');
            if (v) { v.muted = arguments[0]; return true; }
            return false;
        """, action == "mute")
        return {"success": bool(ok), "message": f"{'Muted' if action == 'mute' else 'Unmuted'}." if ok else "No video found to mute."}

    if action == "volume":
        if parameter is None:
            return {"success": False, "message": "Volume needs a value (0-1, a percent, or up/down)."}
        p = parameter.strip().lower().rstrip("%")
        try:
            if p in ("up", "down"):
                delta = 0.1 if p == "up" else -0.1
                ok = _nfx_js(browser, """
                    var p = __nfxPlayer();
                    if (p && p.getVolume && p.setVolume) {
                        var v = Math.max(0, Math.min(1, p.getVolume() + arguments[0]));
                        p.setVolume(v); return v;
                    }
                    var vid = document.querySelector('video');
                    if (vid) {
                        vid.volume = Math.max(0, Math.min(1, vid.volume + arguments[0]));
                        return vid.volume;
                    }
                    return null;
                """, delta)
                if ok is not None:
                    return {"success": True, "message": f"Volume {p} to {int(float(ok) * 100)} percent."}
                return {"success": False, "message": "No video found."}
            val = float(p)
            if val > 1:  # spoken as percent
                val = val / 100.0
            val = max(0.0, min(1.0, val))
            ok = _nfx_js(browser, """
                var p = __nfxPlayer();
                if (p && p.setVolume) { p.setVolume(arguments[0]); return true; }
                var v = document.querySelector('video');
                if (v) { v.volume = arguments[0]; return true; }
                return false;
            """, val)
            return {"success": bool(ok), "message": f"Volume set to {int(val * 100)} percent." if ok else "No video found."}
        except ValueError:
            return {"success": False, "message": f"Couldn't parse volume '{parameter}'."}

    if action in ("seek", "seek to", "jump to", "go to"):
        secs = _nfx_parse_seconds(parameter or "")
        if secs is None:
            return {"success": False, "message": "Tell me a time to jump to, like 45 minutes or 1:20:00."}
        ok = _nfx_js(browser, """
            var p = __nfxPlayer();
            if (!p || !p.seek) return false;
            var dur = p.getDuration ? p.getDuration() : null;
            var ms = arguments[0] * 1000;
            if (dur && ms > dur) ms = dur - 5000;
            p.seek(ms);
            return true;
        """, secs)
        mins, s = divmod(secs, 60)
        h, m = divmod(mins, 60)
        stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        return {"success": bool(ok), "message": f"Jumped to {stamp}." if ok else "No video is playing to seek in."}

    if action in ("skip forward", "skip back", "skip backward", "rewind", "forward"):
        n = _nfx_parse_seconds(parameter or "") or 10
        back = action in ("skip back", "skip backward", "rewind")
        ok = _nfx_js(browser, """
            var p = __nfxPlayer();
            if (!p || !p.seek || !p.getCurrentTime) return false;
            var cur = p.getCurrentTime();
            var dur = p.getDuration ? p.getDuration() : null;
            var target = cur + (arguments[0] * 1000 * (arguments[1] ? -1 : 1));
            if (target < 0) target = 0;
            if (dur && target > dur) target = dur - 5000;
            p.seek(target);
            return true;
        """, n, back)
        return {"success": bool(ok), "message": f"Skipped {'back' if back else 'forward'} {n} seconds." if ok else "No video is playing."}

    if action in ("playback speed", "speed"):
        if parameter is None:
            return {"success": False, "message": "Playback speed needs a value like 1.5."}
        try:
            val = float(parameter.strip().lower().rstrip("x"))
            ok = browser.execute_script("""
                var v = document.querySelector('video');
                if (v) { v.playbackRate = arguments[0]; return true; }
                return false;
            """, val)
            return {"success": bool(ok), "message": f"Playback speed set to {val}x." if ok else "No video found."}
        except ValueError:
            return {"success": False, "message": f"Couldn't parse speed '{parameter}'."}

    if action in ("now playing", "info", "status", "what's playing"):
        info = _nfx_js(browser, """
            var p = __nfxPlayer();
            var titleEl = document.querySelector('[data-uia="video-title"]');
            var title = titleEl ? titleEl.textContent.trim() : null;
            if (!p) return { title: title };
            return {
                title: title,
                cur: p.getCurrentTime ? Math.floor(p.getCurrentTime() / 1000) : null,
                dur: p.getDuration ? Math.floor(p.getDuration() / 1000) : null,
                paused: p.isPaused ? p.isPaused() : null
            };
        """)
        if not info or (not info.get("title") and info.get("cur") is None):
            return {"success": False, "message": "Nothing seems to be playing."}
        parts = []
        if info.get("title"):
            parts.append(f"Playing {info['title']}")
        if info.get("cur") is not None and info.get("dur"):
            cm, cs = divmod(info["cur"], 60)
            dm, ds = divmod(info["dur"], 60)
            parts.append(f"at {cm}:{cs:02d} of {dm}:{ds:02d}")
        if info.get("paused"):
            parts.append("(paused)")
        return {"success": True, "message": " ".join(parts) + "."}

    # ── PLAYER UI actions (stable data-uia selectors + keyboard fallback) ───
    if action == "fullscreen":
        _nfx_reveal_controls(browser)
        ok = _set_fullscreen(browser, True, [
            '[data-uia="control-fullscreen-enter"]',
            'button[aria-label="Full screen"]',
            'button[aria-label="Fullscreen"]',
        ], key="f")
        return {"success": ok,
                "message": "Fullscreen on." if ok else
                           "I pressed fullscreen but the player didn't enter it."}

    if action == "exit fullscreen":
        _nfx_reveal_controls(browser)
        ok = _set_fullscreen(browser, False, [
            '[data-uia="control-fullscreen-exit"]',
            'button[aria-label="Exit full screen"]',
        ], key="escape")
        return {"success": ok,
                "message": "Exited fullscreen." if ok else
                           "I couldn't get the player out of fullscreen."}

    if action == "next episode":
        _nfx_reveal_controls(browser)
        if _nfx_click_first(browser, [
            '[data-uia="control-next"]',
            '[data-uia="next-episode-seamless-button"]',
            '[data-uia="next-episode-seamless-button-draining"]',
            'button[aria-label="Next Episode"]',
        ]):
            return {"success": True, "message": "Next episode."}
        return {"success": False, "message": "No next-episode button — this might be a movie."}

    if action in ("skip intro", "skip recap", "skip credits"):
        _nfx_reveal_controls(browser)
        if _nfx_click_first(browser, [
            '[data-uia="player-skip-intro"]',
            '[data-uia="player-skip-recap"]',
            '.watch-video--skip-content-button',
            '.watch-video--skip-preplay-button',
            'button[data-uia^="player-skip"]',
        ]):
            return {"success": True, "message": "Skipped."}
        # S is Netflix's skip-intro shortcut. With no skip button present it is
        # a no-op, so require a real forward jump (>5s, well beyond the ~0.3s
        # of normal playback drift) before claiming we skipped anything.
        before = _video_time(browser)
        if _send_trusted_key(browser, "s") and _verify_seek(browser, before, 10):
            return {"success": True, "message": "Skipped."}
        return {"success": False, "message": "Nothing to skip right now."}

    if action == "back to browse":
        if _nfx_click_first(browser, [
            '[data-uia="control-nav-back"]',
            'button[aria-label="Back to Browse"]',
        ]):
            return {"success": True, "message": "Back to browsing."}
        browser.get("https://www.netflix.com/browse")
        return {"success": True, "message": "Back to browsing."}

    if action in ("subtitle", "subtitles", "captions"):
        if not parameter:
            return {"success": False, "message": "Tell me which subtitles, like English, or off."}
        # Preferred: internal API — no menus, works even in fullscreen
        result = _nfx_js(browser, """
            var p = __nfxPlayer();
            if (!p || !p.getTextTrackList) return { ok: false, err: 'noplayer' };
            var want = String(arguments[0]).toLowerCase();
            var list = p.getTextTrackList() || [];
            var names = [];
            for (var i = 0; i < list.length; i++) {
                var n = String(list[i].displayName || '');
                names.push(n);
                if (n.toLowerCase().indexOf(want) !== -1) {
                    p.setTextTrack(list[i]);
                    return { ok: true, name: n };
                }
            }
            return { ok: false, err: 'nomatch', names: names };
        """, parameter)
        if result and result.get("ok"):
            return {"success": True, "message": f"Subtitles set to {result['name']}."}
        if result and result.get("err") == "nomatch":
            names = ", ".join(result.get("names", [])[:8])
            return {"success": False, "message": f"No '{parameter}' subtitles. Available: {names}."}
        # Fallback: overlay menu with stable data-uia items (subtitle-item-English etc.)
        return _nfx_menu_select(
            browser,
            ['[data-uia="control-audio-subtitle"]', 'button[aria-label="Audio & Subtitles"]'],
            ["subtitle-item"],
            parameter,
        )

    if action == "audio":
        if not parameter:
            return {"success": False, "message": "Tell me which audio track, like English or Hindi."}
        result = _nfx_js(browser, """
            var p = __nfxPlayer();
            if (!p || !p.getAudioTrackList) return { ok: false, err: 'noplayer' };
            var want = String(arguments[0]).toLowerCase();
            var list = p.getAudioTrackList() || [];
            var names = [];
            for (var i = 0; i < list.length; i++) {
                var n = String(list[i].displayName || '');
                names.push(n);
                if (n.toLowerCase().indexOf(want) !== -1) {
                    p.setAudioTrack(list[i]);
                    return { ok: true, name: n };
                }
            }
            return { ok: false, err: 'nomatch', names: names };
        """, parameter)
        if result and result.get("ok"):
            return {"success": True, "message": f"Audio set to {result['name']}."}
        if result and result.get("err") == "nomatch":
            names = ", ".join(result.get("names", [])[:8])
            return {"success": False, "message": f"No '{parameter}' audio. Available: {names}."}
        return _nfx_menu_select(
            browser,
            ['[data-uia="control-audio-subtitle"]', 'button[aria-label="Audio & Subtitles"]'],
            ["audio-item"],
            parameter,
        )

    if action == "episodes":
        if not parameter:
            return {"success": False, "message": "Tell me which episode, like Episode 5."}
        _nfx_reveal_controls(browser)
        opened = _nfx_click_first(browser, [
            '[data-uia="control-episodes"]',
            'button[aria-label="Episodes"]',
        ])
        if not opened:
            return {"success": False, "message": "Couldn't open the episodes menu — this might be a movie."}
        time.sleep(0.9)
        try:
            result = browser.execute_script("""
                var want = String(arguments[0]).toLowerCase();
                // Episode entries live inside the episodes overlay; match by
                // number ('episode 5' / '5.') or by title text.
                var num = (want.match(/\\d+/) || [null])[0];
                var candidates = document.querySelectorAll(
                    '[data-uia^="episode"], .episode-item, [class*="episodeSelector"] li, [class*="episode"] [role="button"]');
                var texts = [];
                for (var i = 0; i < candidates.length; i++) {
                    var el = candidates[i];
                    if (el.offsetParent === null) continue;
                    var txt = (el.textContent || '').trim();
                    texts.push(txt.slice(0, 40));
                    var low = txt.toLowerCase();
                    if (low.indexOf(want) !== -1 ||
                        (num && (low.indexOf('episode ' + num) !== -1 ||
                                 low.indexOf(num + '.') === 0 ||
                                 low.indexOf('e' + num) === 0))) {
                        el.click();
                        return { ok: true, name: txt.slice(0, 60) };
                    }
                }
                return { ok: false, names: texts };
            """, parameter)
        except Exception as e:
            result = {"ok": False, "err": str(e)}
        if result and result.get("ok"):
            return {"success": True, "message": f"Playing {result['name']}."}
        return {"success": False, "message": f"Couldn't find '{parameter}' in the episodes list."}

    return {"success": False, "message": f"Unknown netflix_control action: {action}"}


# ── Google Meet control ───────────────────────────────────────────────────────
# Meet is a WEB app, so it rides the SAME browser pipeline as Netflix/YouTube:
# the driver's working tab, aria-label based element resolution, and CDP for
# trusted input. No vision clicking, no new automation layer.
#
# WHY ARIA-LABELS AND data-is-muted, AND NOTHING ELSE: Meet's class names and
# jsname attributes are compiled and rotate constantly, but every control in
# the bottom bar is a real button with a stateful aria-label ("Turn off
# microphone" / "Turn on microphone", "Leave call") and the mic and camera
# buttons additionally carry data-is-muted="true|false". That attribute is the
# only way to know the CURRENT state, which is what makes "mute" idempotent
# instead of a blind toggle that unmutes an already-muted mic.
#
# HONEST LIMITS: this joins, mutes, unmutes, toggles the camera, leaves,
# raises/lowers the hand and opens the chat panel. It does not schedule
# meetings, admit participants, present a screen, or read the roster.

_MEET_STATE_JS = r"""
    function visible(el) {
        try {
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return false;
            const s = window.getComputedStyle(el);
            return s.visibility !== 'hidden' && s.display !== 'none';
        } catch (e) { return false; }
    }
    const out = { mic_muted: null, cam_off: null, labels: [], in_call: false };
    const btns = document.querySelectorAll(
        'button[aria-label], [role="button"][aria-label]');
    for (const b of btns) {
        if (!visible(b)) continue;
        const label = (b.getAttribute('aria-label') || '').trim();
        if (label) out.labels.push(label.slice(0, 60));
        const low = label.toLowerCase();
        const muted = b.getAttribute('data-is-muted');
        if (muted !== null) {
            if (low.indexOf('microphone') !== -1 || low.indexOf('mic') !== -1)
                out.mic_muted = (muted === 'true');
            else if (low.indexOf('camera') !== -1 || low.indexOf('video') !== -1)
                out.cam_off = (muted === 'true');
        }
        if (low.indexOf('leave call') !== -1 || low.indexOf('leave the call') !== -1)
            out.in_call = true;
    }
    return out;
"""

_MEET_CLICK_JS = r"""
    const wants = arguments[0].map(s => String(s).toLowerCase());
    const btns = Array.prototype.slice.call(document.querySelectorAll(
        'button[aria-label], [role="button"][aria-label], button, [role="button"]'));
    function visible(el) {
        try {
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return false;
            const s = window.getComputedStyle(el);
            return s.visibility !== 'hidden' && s.display !== 'none';
        } catch (e) { return false; }
    }
    // Wants are tried IN ORDER so the caller controls priority, e.g. prefer
    // 'turn off microphone' over the looser 'microphone'.
    for (const w of wants) {
        for (const b of btns) {
            if (!visible(b)) continue;
            const label = ((b.getAttribute('aria-label') || '') + ' ' +
                           (b.textContent || '')).toLowerCase();
            if (label.indexOf(w) !== -1) {
                try { b.scrollIntoView({ block: 'center' }); } catch (e) {}
                b.click();
                return (b.getAttribute('aria-label') ||
                        (b.textContent || '').trim()).slice(0, 60);
            }
        }
    }
    return null;
"""

# A Meet code is three-four-three letters, which is how users read a link out.
_MEET_CODE = re.compile(r"\b([a-z]{3}-[a-z]{4}-[a-z]{3})\b", re.IGNORECASE)


def _meet_state(browser) -> dict:
    try:
        return browser.execute_script(_MEET_STATE_JS) or {}
    except Exception as e:
        print(f"[meet_control] state read failed: {e}")
        return {}


def _meet_click(browser, wants: list) -> str | None:
    try:
        return browser.execute_script(_MEET_CLICK_JS, wants)
    except Exception as e:
        print(f"[meet_control] click failed: {e}")
        return None


def _meet_toggle(browser, device: str, want_off: bool) -> dict:
    """Set mic or camera to an exact state and VERIFY it landed.

    Order: read state (already right -> say so), click the labelled button,
    re-read, then fall back to Meet's own ctrl+d / ctrl+e shortcut through CDP.
    A blind toggle is never used — that is how "mute me" ends up unmuting.
    """
    key = "mic_muted" if device == "microphone" else "cam_off"
    state = _meet_state(browser)
    if not state:
        return {"success": False,
                "message": "I can't see the Meet controls. Is the meeting open?"}
    current = state.get(key)
    noun = "microphone" if device == "microphone" else "camera"
    if current is want_off and current is not None:
        return {"success": True,
                "message": (f"Your {noun} is already "
                            f"{'off' if want_off else 'on'}.")}

    verb = "turn off" if want_off else "turn on"
    wants = [f"{verb} {noun}"]
    if noun == "microphone":
        wants.append(f"{verb} mic")
    label = _meet_click(browser, wants)
    if label:
        if _await_state(lambda: _meet_state(browser).get(key) is want_off, 2.0):
            return {"success": True,
                    "message": f"{noun.capitalize()} {'off' if want_off else 'on'}."}

    # Meet's documented shortcuts, dispatched as REAL input (modifier 2 = ctrl).
    shortcut = "d" if device == "microphone" else "e"
    if _send_trusted_key(browser, shortcut, modifiers=2):
        if _await_state(lambda: _meet_state(browser).get(key) is want_off, 2.0):
            return {"success": True,
                    "message": f"{noun.capitalize()} {'off' if want_off else 'on'}."}

    return {"success": False,
            "message": (f"I couldn't change the {noun} — Meet didn't report the "
                        "change, so I'm not claiming it worked.")}


def meet_control(action: str, parameter: str | None = None) -> dict:
    """
    Google Meet automation over the existing browser pipeline.

      join|<link, meeting code, or nothing>  -> open and join (or ask to join)
      mute / unmute                          -> microphone, state-verified
      camera off / camera on                 -> camera, state-verified
      leave                                  -> leave the call
      raise hand / lower hand
      chat                                   -> open the chat panel
      state                                  -> report mic/camera/in-call

    Returns {'success': bool, 'message': str}.
    """
    print(f"[meet_control] action={action!r} parameter={parameter!r}")
    browser = get_browser(_last_browser_name)
    try:
        browser.switch_to.window(browser._akira_tab)
    except Exception:
        return {"success": False, "message": "Lost track of my working tab."}

    action = (action or "").strip().lower().replace("_", " ")
    try:
        current_url = browser.current_url or ""
    except Exception:
        current_url = ""

    if action in ("join", "join meeting", "open", "start"):
        target = (parameter or "").strip()
        if target:
            code = _MEET_CODE.search(target)
            if target.startswith("http"):
                url = target
            elif code:
                url = "https://meet.google.com/" + code.group(1).lower()
            else:
                url = "https://meet.google.com/" + urllib.parse.quote(
                    target.replace(" ", ""))
            browser.get(url)
        elif "meet.google.com" not in current_url:
            browser.get("https://meet.google.com/")
            return {"success": False,
                    "message": ("Meet is open. Give me the meeting link or code "
                                "and I'll join it.")}
        # The green-room join button only renders after devices initialise.
        label = None
        deadline = time.time() + 12
        while time.time() < deadline and not label:
            label = _meet_click(browser, ["join now", "ask to join",
                                          "join meeting", "switch here"])
            if not label:
                time.sleep(0.6)
        if not label:
            state = _meet_state(browser)
            if state.get("in_call"):
                return {"success": True, "message": "You're already in the meeting."}
            return {"success": False,
                    "message": ("I opened Meet but couldn't find the join button. "
                                "It may still be loading, or it needs you to sign in.")}
        joined = _await_state(lambda: _meet_state(browser).get("in_call"), 8.0)
        if "ask" in label.lower():
            return {"success": True,
                    "message": "I asked to join. Waiting on the host to let you in."}
        return {"success": True,
                "message": ("You're in the meeting." if joined
                            else "Clicked join. It's still connecting.")}

    if "meet.google.com" not in current_url:
        return {"success": False,
                "message": "That's not a Meet tab. Tell me the meeting link first."}

    if action in ("mute", "mute mic", "mute microphone", "microphone off",
                  "mic off"):
        return _meet_toggle(browser, "microphone", True)
    if action in ("unmute", "unmute mic", "unmute microphone",
                  "microphone on", "mic on"):
        return _meet_toggle(browser, "microphone", False)
    if action in ("camera off", "video off", "turn off camera", "stop video"):
        return _meet_toggle(browser, "camera", True)
    if action in ("camera on", "video on", "turn on camera", "start video"):
        return _meet_toggle(browser, "camera", False)

    if action in ("leave", "leave call", "leave meeting", "hang up", "end call"):
        label = _meet_click(browser, ["leave call", "leave the call", "hang up"])
        if not label:
            return {"success": False,
                    "message": "I couldn't find the leave button on this page."}
        return {"success": True, "message": "Left the meeting."}

    if action in ("raise hand", "raise my hand", "hand up"):
        if _meet_click(browser, ["raise hand"]):
            return {"success": True, "message": "Hand raised."}
        return {"success": False, "message": "I couldn't find the raise hand button."}

    if action in ("lower hand", "lower my hand", "hand down"):
        if _meet_click(browser, ["lower hand"]):
            return {"success": True, "message": "Hand lowered."}
        return {"success": False, "message": "Your hand doesn't look raised."}

    if action in ("chat", "open chat", "show chat", "chat panel"):
        if _meet_click(browser, ["chat with everyone", "open chat", "chat"]):
            return {"success": True, "message": "Chat panel is open."}
        return {"success": False, "message": "I couldn't open the chat panel."}

    if action in ("state", "status", "am i muted"):
        state = _meet_state(browser)
        if not state:
            return {"success": False, "message": "I can't read the Meet controls."}
        mic = state.get("mic_muted")
        cam = state.get("cam_off")
        parts = []
        if mic is not None:
            parts.append("mic is " + ("muted" if mic else "live"))
        if cam is not None:
            parts.append("camera is " + ("off" if cam else "on"))
        if not parts:
            return {"success": False,
                    "message": "I can see Meet but not the mic or camera state."}
        prefix = "You're in a meeting, " if state.get("in_call") else ""
        return {"success": True, "message": prefix + " and ".join(parts) + "."}

    return {"success": False, "message": f"Unknown meet_control action: {action}"}


# ── Amazon control ────────────────────────────────────���──────────────��───��────
# SCOPE: search → product → cart → checkout → address confirmation.
# HARD STOP before payment-method selection. No payment actions exist here.

def amazon_control(action: str, parameter: str | None = None) -> dict:
    """
    Amazon.in shopping automation up to (and not past) order-review/address.

    Actions:
      search|query           -> search results page, reports top products
      select result|first    -> open a product from results by ordinal or name
      select variant|desc    -> pick size/color via generic click (Category 2)
      quantity|2             -> set quantity dropdown on product page
      add to cart            -> #add-to-cart-button (CONFIRMED stable id)
      view cart              -> cart page
      proceed to checkout    -> risky-keyword recheck, needs_confirmation
      confirm address        -> pick saved address (PLACEHOLDER-UNVERIFIED)

    Returns {'success': bool, 'message': str} or the needs_click_confirmation
    dict shape that _handle_click returns (so akira.py's pause logic works).
    """
    print(f"[amazon_control] called with action={action!r}, parameter={parameter!r}")
    browser = get_browser(_last_browser_name)
    try:
        browser.switch_to.window(browser._akira_tab)
    except Exception:
        return {"success": False, "message": "Lost track of my working tab."}
    try:
        WebDriverWait(browser, 8).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass
    try:
        current_url = browser.current_url or ""
    except Exception:
        return {"success": False, "message": "Could not read current URL"}

    action = (action or "").strip().lower().replace("_", " ")

    def _amz_collect_cards() -> list:
        """CONFIRMED: search results use div[data-component-type='s-search-result']
        with a data-asin attribute; title lives in the h2, link in h2 a / a[href*='/dp/']."""
        try:
            return browser.execute_script(r"""
                var out = [], seen = {};
                var cards = document.querySelectorAll(
                    'div[data-component-type="s-search-result"][data-asin]');
                for (var i = 0; i < cards.length; i++) {
                    var asin = cards[i].getAttribute('data-asin');
                    if (!asin || seen[asin]) continue;
                    var link = cards[i].querySelector('h2 a, a.a-link-normal[href*="/dp/"]');
                    if (!link) continue;
                    var h2 = cards[i].querySelector('h2');
                    var label = h2 ? h2.textContent.trim() : (link.textContent || '').trim();
                    if (!label) continue;
                    seen[asin] = true;
                    out.push({ label: label.slice(0, 120), href: link.href, asin: asin });
                }
                return out;
            """) or []
        except Exception:
            return []

    def _amz_find_visible(selectors: list):
        """Return the first visible Selenium element matching any CSS selector."""
        for sel in selectors:
            try:
                for el in browser.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed():
                        return el
            except Exception:
                continue
        return None

    def _guarded_click(el, spoken_name: str, retry_param: str, pre_confirmed: bool = False):
        return _shop_guarded_click(browser, el, spoken_name, retry_param, pre_confirmed)

    # ── search (reuses SEARCH_URL_MAP url, adds card reporting) ─────────────
    if action == "search":
        if not parameter:
            return {"success": False, "message": "Search needs a query."}
        _navigate("https://www.amazon.in/s?k=" + urllib.parse.quote(parameter))
        try:
            WebDriverWait(browser, 4).until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div[data-component-type="s-search-result"]')))
        except Exception:
            pass
        cards = _amz_collect_cards()
        if not cards:
            return {"success": False, "message": f"No Amazon results found for {parameter}."}
        top = "; ".join(c["label"][:60] for c in cards[:4])
        return {"success": True, "message": f"Found {len(cards)} products for {parameter}. Top results: {top}. Say select first result, or name one."}

    if "amazon" not in current_url:
        return {"success": False, "message": "Not an Amazon tab. Search Amazon first."}

    if action in ("select result", "open result", "select product", "open product"):
        cards = _amz_collect_cards()
        if not cards:
            return {"success": False, "message": "I don't see any products on this page. Try searching first."}
        pick = _pick_card(cards, parameter)
        browser.get(pick["href"])
        try:
            WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.ID, "productTitle")))
        except Exception:
            pass
        return {"success": True, "message": f"Opened {pick['label'][:60]}."}

    if action in ("select variant", "variant", "select option"):
        # Category 2: variant widgets (twister) vary too much per product —
        # reuse the existing generic click pipeline.
        if not parameter:
            return {"success": False, "message": "Tell me which option, like size medium or color black."}
        result = _handle_click(parameter)
        if isinstance(result, dict):
            return result
        ok = not str(result).lower().startswith("couldn't")
        return {"success": ok, "message": str(result)}

    if action == "quantity":
        if not parameter:
            return {"success": False, "message": "Tell me a quantity, like 2."}
        qty = re.sub(r"\D", "", parameter) or "1"
        try:
            ok = browser.execute_script("""
                var sel = document.querySelector('#quantity, select[name="quantity"]');
                if (!sel) return false;
                sel.value = arguments[0];
                sel.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            """, qty)
            if ok:
                return {"success": True, "message": f"Quantity set to {qty}."}
            return {"success": False, "message": "No quantity selector on this page."}
        except Exception as e:
            return {"success": False, "message": f"Couldn't set quantity: {e}"}

    if action == "add to cart":
        # CONFIRMED: #add-to-cart-button has been Amazon's stable id for years
        el = _amz_find_visible([
            "#add-to-cart-button",
            'input[name="submit.add-to-cart"]',
            "#add-to-cart-button-ubb",
        ])
        if not el:
            return {"success": False, "message": "Couldn't find the Add to Cart button — are you on a product page?"}
        result = _guarded_click(el, "Add to Cart", "add to cart")
        if result.get("success"):
            time.sleep(1.0)
            return {"success": True, "message": "Added to cart."}
        return result

    if action in ("view cart", "cart", "open cart", "go to cart"):
        browser.get("https://www.amazon.in/gp/cart/view.html")
        try:
            WebDriverWait(browser, 8).until(EC.presence_of_element_located((By.ID, "sc-active-cart")))
        except Exception:
            pass
        return {"success": True, "message": "Opened your Amazon cart."}

    if action in ("proceed to checkout", "checkout"):
        # CONFIRMED ids from cart page + post-add side sheet.
        # This branch is ONLY reachable after akira.py's safety net got a
        # spoken yes (RISKY_SHOPPING_PARAMS gate), so pre_confirmed=True.
        el = _amz_find_visible([
            'input[name="proceedToRetailCheckout"]',
            "#sc-buy-box-ptc-button input",
            "#sc-buy-box-ptc-button",
            "#hlb-ptc-btn-native",
            'a[href*="proceedToCheckout"]',
        ])
        if not el:
            return {"success": False, "message": "Couldn't find the checkout button — open the cart first."}
        result = _guarded_click(el, "Proceed to Checkout", "proceed to checkout", pre_confirmed=True)
        if result.get("success"):
            return {"success": True, "message": "Moved to checkout. Next step is address confirmation — I stop before payment."}
        return result

    if action in ("confirm address", "select address", "confirm delivery address"):
        # PLACEHOLDER-UNVERIFIED: address book ids seen in research
        # (#address-book-entry-0, ship-to-this-address) need a live capture of
        # the amazon.in "Select a delivery address" page to confirm.
        sel_list = [
            "#address-book-entry-0 a, #address-book-entry-0 input",
            ".ship-to-this-address a, .ship-to-this-address input",
            'input[data-testid="Address_selectShipToAddress"]',
        ]
        if parameter and parameter.strip().isdigit():
            n = int(parameter.strip()) - 1
            sel_list.insert(0, f"#address-book-entry-{n} a, #address-book-entry-{n} input")
        el = _amz_find_visible(sel_list)
        if not el:
            return {"success": False, "message": "Couldn't find a saved address to select — the address page may look different. This is where I stop before payment."}
        result = _guarded_click(el, "delivery address", "confirm address", pre_confirmed=True)
        if result.get("success"):
            return {"success": True, "message": "Address confirmed. Stopping here — the next screen is payment selection, which I won't touch."}
        return result

    return {"success": False, "message": f"Unknown amazon_control action: {action}"}


# ── Flipkart control ──────────────────────────────────────────────────────────
# SCOPE: identical hard boundary — stop before payment-method selection.
# Flipkart rotates its class names as anti-scraping, so all selectors here are
# text/attribute-based, never class-based.

def flipkart_control(action: str, parameter: str | None = None) -> dict:
    """
    Flipkart shopping automation up to (and not past) address confirmation.

    Actions:
      search|query           -> search results, closes login popup, reports top products
      select result|first    -> open a product by ordinal or name (new-tab aware)
      select variant|desc    -> size/color via generic click (Category 2)
      add to cart            -> text-matched button (classes rotate; text doesn't)
      view cart              -> /viewcart
      proceed to checkout    -> Flipkart's cart button is literally "Place Order",
                                which hits RISKY_KEYWORDS -> needs_confirmation
      confirm address        -> "Deliver Here" button (PLACEHOLDER-UNVERIFIED)

    Returns {'success': bool, 'message': str} or the needs_click_confirmation dict.
    """
    print(f"[flipkart_control] called with action={action!r}, parameter={parameter!r}")
    browser = get_browser(_last_browser_name)
    try:
        browser.switch_to.window(browser._akira_tab)
    except Exception:
        return {"success": False, "message": "Lost track of my working tab."}
    try:
        WebDriverWait(browser, 8).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass
    try:
        current_url = browser.current_url or ""
    except Exception:
        return {"success": False, "message": "Could not read current URL"}

    action = (action or "").strip().lower().replace("_", " ")

    def _fk_close_login_popup():
        """Flipkart throws a login modal over search results; its close button
        is a bare '✕'. Class-independent: match by text."""
        try:
            browser.execute_script("""
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var t = (btns[i].textContent || '').trim();
                    if (t === '\\u2715' || t === '\\u2716' || t === 'X' || t === '\\u00d7') {
                        btns[i].click(); return true;
                    }
                }
                return false;
            """)
        except Exception:
            pass

    def _fk_collect_cards() -> list:
        """div[data-id] wrappers are Flipkart's stable per-product attribute;
        product links always contain /p/. Labels come from link title attr,
        img alt, or text — never class names."""
        try:
            return browser.execute_script(r"""
                var out = [], seen = {};
                var wraps = document.querySelectorAll('div[data-id]');
                for (var i = 0; i < wraps.length; i++) {
                    var id = wraps[i].getAttribute('data-id');
                    if (!id || seen[id]) continue;
                    var link = wraps[i].querySelector('a[href*="/p/"]');
                    if (!link) continue;
                    var label = link.getAttribute('title') || '';
                    if (!label) {
                        var img = wraps[i].querySelector('img[alt]');
                        if (img) label = img.getAttribute('alt') || '';
                    }
                    if (!label) label = (link.textContent || '').trim();
                    if (!label) continue;
                    seen[id] = true;
                    out.push({ label: label.slice(0, 120), href: link.href, id: id });
                }
                // fallback: pages without data-id wrappers
                if (out.length === 0) {
                    var links = document.querySelectorAll('a[href*="/p/"]');
                    for (var j = 0; j < links.length; j++) {
                        var href = links[j].href;
                        if (seen[href]) continue;
                        var lb = links[j].getAttribute('title') ||
                                 (links[j].querySelector('img[alt]') ?
                                  links[j].querySelector('img[alt]').getAttribute('alt') : '') ||
                                 (links[j].textContent || '').trim();
                        if (!lb) continue;
                        seen[href] = true;
                        out.push({ label: lb.slice(0, 120), href: href, id: href });
                    }
                }
                return out;
            """) or []
        except Exception:
            return []

    def _fk_find_button_by_text(phrases: list):
        """Find a visible button/anchor whose text contains any phrase
        (case-insensitive). Flipkart classes rotate; text is the stable handle."""
        try:
            xpath_parts = []
            for ph in phrases:
                ph_lower = ph.lower()
                xpath_parts.append(
                    f"contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), \"{ph_lower}\")")
            xpath = ("//button[" + " or ".join(xpath_parts) + "]"
                     " | //a[" + " or ".join(xpath_parts) + "]"
                     " | //span[" + " or ".join(xpath_parts) + "]/ancestor::button")
            for el in browser.find_elements(By.XPATH, xpath):
                if el.is_displayed():
                    return el
        except Exception:
            pass
        return None

    def _guarded_click(el, spoken_name: str, retry_param: str, pre_confirmed: bool = False):
        return _shop_guarded_click(browser, el, spoken_name, retry_param, pre_confirmed)

    if action == "search":
        if not parameter:
            return {"success": False, "message": "Search needs a query."}
        browser.get("https://www.flipkart.com/search?q=" + urllib.parse.quote(parameter))
        try:
            WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-id], a[href*="/p/"]')))
        except Exception:
            pass
        _fk_close_login_popup()
        time.sleep(0.5)
        cards = _fk_collect_cards()
        if not cards:
            return {"success": False, "message": f"No Flipkart results found for {parameter}."}
        top = "; ".join(c["label"][:60] for c in cards[:4])
        return {"success": True, "message": f"Found {len(cards)} products for {parameter}. Top results: {top}. Say select first result, or name one."}

    if "flipkart" not in current_url:
        return {"success": False, "message": "Not a Flipkart tab. Search Flipkart first."}

    if action in ("select result", "open result", "select product", "open product"):
        _fk_close_login_popup()
        cards = _fk_collect_cards()
        if not cards:
            return {"success": False, "message": "I don't see any products on this page. Try searching first."}
        pick = _pick_card(cards, parameter)
        # Flipkart product links open new tabs by default; navigating directly
        # keeps everything in Akira's tab so _akira_tab stays valid.
        browser.get(pick["href"])
        time.sleep(1.0)
        _fk_close_login_popup()
        return {"success": True, "message": f"Opened {pick['label'][:60]}."}

    if action in ("select variant", "variant", "select option"):
        # Category 2: reuse the generic click pipeline
        if not parameter:
            return {"success": False, "message": "Tell me which option, like size large."}
        result = _handle_click(parameter)
        if isinstance(result, dict):
            return result
        ok = not str(result).lower().startswith("couldn't")
        return {"success": ok, "message": str(result)}

    if action == "add to cart":
        _fk_close_login_popup()
        el = _fk_find_button_by_text(["add to cart"])
        if not el:
            return {"success": False, "message": "Couldn't find the Add to Cart button — are you on a product page? You may need to be logged in to Flipkart."}
        result = _guarded_click(el, "Add to Cart", "add to cart")
        if result.get("success"):
            time.sleep(1.5)
            return {"success": True, "message": "Added to cart."}
        return result

    if action in ("view cart", "cart", "open cart", "go to cart"):
        browser.get("https://www.flipkart.com/viewcart")
        time.sleep(1.0)
        _fk_close_login_popup()
        return {"success": True, "message": "Opened your Flipkart cart."}

    if action in ("proceed to checkout", "checkout", "place order"):
        # Flipkart's cart-page progression button is literally "Place Order".
        # This branch is ONLY reachable after akira.py's safety net got a
        # spoken yes (RISKY_SHOPPING_PARAMS gate), so pre_confirmed=True.
        # It lands on login/address selection, still pre-payment.
        _fk_close_login_popup()
        el = _fk_find_button_by_text(["place order"])
        if not el:
            return {"success": False, "message": "Couldn't find the Place Order button — open the cart first. You may need to be logged in."}
        result = _guarded_click(el, "Place Order", "proceed to checkout", pre_confirmed=True)
        if result.get("success"):
            return {"success": True, "message": "Moved to address selection — I stop before payment."}
        return result

    if action in ("confirm address", "select address", "confirm delivery address", "deliver here"):
        # PLACEHOLDER-UNVERIFIED: 'Deliver Here' is the button text seen in
        # research on the address-selection step; needs a live capture of the
        # Flipkart address page to confirm exact structure.
        el = _fk_find_button_by_text(["deliver here", "deliver to this address"])
        if not el:
            return {"success": False, "message": "Couldn't find a Deliver Here button — the address page may look different. This is where I stop before payment."}
        result = _guarded_click(el, "Deliver Here", "confirm address", pre_confirmed=True)
        if result.get("success"):
            return {"success": True, "message": "Address confirmed. Stopping here — the next screen is payment, which I won't touch."}
        return result

    return {"success": False, "message": f"Unknown flipkart_control action: {action}"}


# ── GitHub control ────────────────────────────────────────────────────────────
# HYBRID STRATEGY (researched, not assumed):
#   READS  -> unauthenticated GitHub REST API (stable, official; 60 req/hr,
#             search 10/min — plenty for voice usage). Browser navigates too,
#             so the user SEES the page while the API supplies reliable data.
#   WRITES -> DOM via the logged-in browser session (api.github.com does NOT
#             accept browser cookies; writes need a PAT). If GITHUB_TOKEN env
#             var is set, the API is preferred for writes too.
#   GATED  -> merge/delete/close/create-PR go through akira.py's safety net
#             (RISKY_GITHUB_PARAMS), the SAME fixed mechanism as checkout.
#   OUT OF SCOPE (flagged, not built): push / force_push — no git operations.

_gh_last_repos: list = []  # cards from the last "search repos" call


def _gh_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or None


def _gh_api(path: str, method: str = "GET", body: dict | None = None):
    """Call the GitHub REST API. Returns (ok, json_or_error_message)."""
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    tok = _gh_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        resp = requests.request(method, "https://api.github.com" + path,
                                headers=headers, json=body, timeout=10)
        if resp.status_code in (200, 201, 204):
            return True, (resp.json() if resp.content else {})
        if resp.status_code == 401:
            if tok and method == "GET":
                # Fallback to unauthenticated read for public repos if token is invalid
                h_no_tok = {k: v for k, v in headers.items() if k != "Authorization"}
                try:
                    resp_retry = requests.request(method, "https://api.github.com" + path,
                                                  headers=h_no_tok, json=body, timeout=10)
                    if resp_retry.status_code in (200, 201, 204):
                        return True, (resp_retry.json() if resp_retry.content else {})
                    if resp_retry.status_code == 404:
                        return False, "Not found — repo may be private or the name is wrong."
                    if resp_retry.status_code == 403:
                        return False, "GitHub API rate limit hit — try again in a minute."
                except Exception:
                    pass
            return False, "GitHub API auth failed — GITHUB_TOKEN is invalid."
        if resp.status_code == 403:
            return False, "GitHub API rate limit hit — try again in a minute."
        if resp.status_code == 404:
            return False, "Not found — repo may be private or the name is wrong."
        return False, f"GitHub API error {resp.status_code}."
    except Exception as e:
        return False, f"GitHub API unreachable: {e}"


def _gh_repo_from_url(url: str) -> str | None:
    """Extract 'owner/repo' from a github.com URL."""
    m = re.search(r"github\.com/([\w.-]+)/([\w.-]+)", url or "")
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if owner in ("search", "settings", "notifications", "topics", "orgs",
                 "marketplace", "explore", "login", "features"):
        return None
    return f"{owner}/{repo}"


def _get_user_github_owner() -> str:
    """Resolve the current user's GitHub username / owner without hardcoding."""
    tok = _gh_token()
    if tok:
        ok, udata = _gh_api("/user")
        if ok and isinstance(udata, dict) and udata.get("login"):
            return udata["login"]
    # Check git config for github.user
    try:
        proc = subprocess.run(["git", "config", "--get", "github.user"],
                              capture_output=True, text=True, timeout=2)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    # Check remote origin url e.g. https://github.com/liveprosperdie/Sensei.git
    try:
        proc = subprocess.run(["git", "config", "--get", "remote.origin.url"],
                              capture_output=True, text=True, timeout=2)
        if proc.returncode == 0 and proc.stdout.strip():
            m = re.search(r"github\.com[:/]([\w.-]+)/", proc.stdout.strip())
            if m:
                return m.group(1)
    except Exception:
        pass
    return os.environ.get("GITHUB_USER") or os.environ.get("GITHUB_USERNAME") or "liveprosperdie"


def _resolve_repo_target(parameter: str | None, current_repo: str | None) -> tuple[str | None, str | None]:
    """
    Resolve a user-specified repo name into full 'owner/repo'.
    Returns (resolved_full_name, error_message).
    If error_message is not None, resolution failed and the caller MUST fail loudly
    instead of silently guessing or substituting another repo.
    """
    p = (parameter or "").strip().strip("/")
    if p:
        if "/" in p:
            # Explicit owner/repo provided
            ok, info = _gh_api(f"/repos/{p}")
            if ok and isinstance(info, dict) and "full_name" in info:
                return info["full_name"], None
            return None, f"Couldn't find a repo named '{p}' on GitHub."
        else:
            # Bare repo name e.g. 'filesense' -> resolve against user's GitHub account
            owner = _get_user_github_owner()
            ok, info = _gh_api(f"/repos/{owner}/{p}")
            if ok and isinstance(info, dict) and "full_name" in info:
                return info["full_name"], None
            # Also check user's repo list for case-insensitive matches
            ok2, repos = _gh_api(f"/users/{owner}/repos?per_page=100")
            if ok2 and isinstance(repos, list):
                for r in repos:
                    if r.get("name", "").lower() == p.lower():
                        return r.get("full_name"), None
            return None, f"Couldn't find a repo named '{p}' on your GitHub ({owner})."

    # No repo named: check open browser tab or last search
    if current_repo:
        return current_repo, None
    if _gh_last_repos:
        return _gh_last_repos[0]["label"], None
    return None, "Open a repo first, or tell me which repo you want."


def _gh_click_text_button(browser, phrases: list):
    """Visible button/summary/anchor by case-insensitive text — GitHub's React
    migration rotates classes, but button labels are stable."""
    try:
        parts = [f"contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                 f"'abcdefghijklmnopqrstuvwxyz'), \"{p.lower()}\")" for p in phrases]
        cond = " or ".join(parts)
        xpath = f"//button[{cond}] | //summary[{cond}] | //a[{cond}]"
        for el in browser.find_elements(By.XPATH, xpath):
            if el.is_displayed():
                return el
    except Exception:
        pass
    return None


def github_control(action: str, parameter: str | None = None) -> dict:
    """
    GitHub automation. '|' splits parameter fields (e.g. create issue|title|body).

    Tier A (no confirmation): search repos, open repo, view file, view issues,
      view pull requests, read readme, star repo, unstar repo, fork repo,
      clone repo, create issue.
    Gated by akira.py safety net: create pull request, merge pull request,
      close issue, close pull request, delete branch, delete repo.
    NOT built: push / force push (out of scope — no git operations).
    """
    print(f"[github_control] called with action={action!r}, parameter={parameter!r}")
    browser = get_browser(_last_browser_name)
    try:
        browser.switch_to.window(browser._akira_tab)
    except Exception:
        return {"success": False, "message": "Lost track of my working tab."}
    try:
        current_url = browser.current_url or ""
    except Exception:
        current_url = ""

    action = (action or "").strip().lower().replace("_", " ")
    global _gh_last_repos

    def _current_repo() -> str | None:
        return _gh_repo_from_url(current_url)

    # ── Tier A: reads via REST API with user repo resolution ────────────────
    if action in ("search repos", "search repo", "search"):
        if not parameter:
            return {"success": False, "message": "Search needs a query."}

        # Resolve against user's own GitHub account first
        owner = _get_user_github_owner()
        resolved, _ = _resolve_repo_target(parameter, None)
        if resolved:
            ok, data = _gh_api(f"/repos/{resolved}")
            if ok and isinstance(data, dict):
                url = data.get("html_url", f"https://github.com/{resolved}")
                _gh_last_repos = [{"label": data.get("full_name", resolved), "href": url,
                                   "desc": (data.get("description") or "")[:80],
                                   "stars": data.get("stargazers_count", 0)}]
                browser.get(url)
                return {"success": True, "message": f"Found {data.get('full_name', resolved)} in your repos ({owner}). Say open repository or repo notes."}

        # Fallback to global public search if no match on user's account
        ok, data = _gh_api("/search/repositories?per_page=10&q=" + urllib.parse.quote(parameter))
        if not ok:
            return {"success": False, "message": data}
        items = data.get("items", [])
        if not items:
            return {"success": False, "message": f"Couldn't find {parameter} in your repos ({owner}) or anywhere on GitHub."}
        _gh_last_repos = [{"label": it["full_name"], "href": it["html_url"],
                           "desc": (it.get("description") or "")[:80],
                           "stars": it.get("stargazers_count", 0)} for it in items]
        browser.get("https://github.com/search?type=repositories&q=" + urllib.parse.quote(parameter))
        top = "; ".join(f"{c['label']} ({c['stars']} stars)" for c in _gh_last_repos[:4])
        return {"success": True, "message": f"Couldn't find {parameter} in your repos ({owner}), but found {len(_gh_last_repos)} public repos on GitHub. Top: {top}."}

    if action in ("open repo", "open repository", "open result"):
        if parameter:
            # Call _resolve_repo_target FIRST against user's own GitHub account
            resolved, err = _resolve_repo_target(parameter, None)
            if resolved:
                ok, data = _gh_api(f"/repos/{resolved}")
                url = data.get("html_url") if (ok and isinstance(data, dict)) else f"https://github.com/{resolved}"
                name = data.get("full_name", resolved) if (ok and isinstance(data, dict)) else resolved
                browser.get(url)
                return {"success": True, "message": f"Opened {name}."}

            # Fallback to global public search if no match on user's account
            owner = _get_user_github_owner()
            ok, data = _gh_api("/search/repositories?per_page=5&q=" + urllib.parse.quote(parameter))
            if ok and isinstance(data, dict) and data.get("items"):
                first = data["items"][0]
                _gh_last_repos = [{"label": it["full_name"], "href": it["html_url"],
                                   "desc": (it.get("description") or "")[:80],
                                   "stars": it.get("stargazers_count", 0)} for it in data["items"]]
                browser.get(first["html_url"])
                return {"success": True, "message": f"Couldn't find {parameter} in your repos ({owner}), but found public repo {first['full_name']} — opened that instead."}
            return {"success": False, "message": err or f"Couldn't find a repo named {parameter} in your repos or on GitHub."}

        if not _gh_last_repos:
            return {"success": False, "message": "No repo results yet — search repos first, or say the owner/name."}
        pick = _pick_card(_gh_last_repos, parameter)
        browser.get(pick["href"])
        return {"success": True, "message": f"Opened {pick['label']}."}

    # everything below needs a repo context or a github tab
    repo = _current_repo()

    if action == "view file":
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        if not parameter:
            return {"success": False, "message": "Tell me the file path, like src/main.py."}
        path = parameter.strip().lstrip("/")
        ok, _ = _gh_api(f"/repos/{repo}/contents/{urllib.parse.quote(path)}")
        if not ok:
            return {"success": False, "message": f"Couldn't find {path} in {repo}."}
        browser.get(f"https://github.com/{repo}/blob/HEAD/{path}")
        return {"success": True, "message": f"Opened {path}."}

    if action in ("view issues", "view pull requests", "view prs"):
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        kind = "issues" if "issue" in action else "pulls"
        ok, data = _gh_api(f"/repos/{repo}/{kind}?state=open&per_page=5")
        if not ok:
            return {"success": False, "message": data}
        # /issues also returns PRs — filter them out
        if kind == "issues":
            data = [d for d in data if "pull_request" not in d]
        browser.get(f"https://github.com/{repo}/{'issues' if kind == 'issues' else 'pulls'}")
        if not data:
            return {"success": True, "message": f"No open {'issues' if kind == 'issues' else 'pull requests'} in {repo}."}
        top = "; ".join(f"#{d['number']} {d['title'][:50]}" for d in data[:4])
        return {"success": True, "message": f"Open {'issues' if kind == 'issues' else 'pull requests'} in {repo}: {top}."}

    if action in ("read readme", "summarize repo", "summarise repo"):
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        try:
            resp = requests.get(f"https://api.github.com/repos/{repo}/readme",
                                headers={"Accept": "application/vnd.github.raw+json"},
                                timeout=10)
            if resp.status_code != 200:
                return {"success": False, "message": f"No readme found in {repo}."}
            text = re.sub(r"[#*`\[\]()>|-]", " ", resp.text)
            text = re.sub(r"\s+", " ", text).strip()[:400]
            return {"success": True, "message": f"Readme of {repo}: {text}"}
        except Exception as e:
            return {"success": False, "message": f"Couldn't fetch the readme: {e}"}

    if action in ("repo notes", "generate notes", "architecture notes",
                  "write notes", "document repo"):
        # Reads the repo and writes linked Obsidian notes about its architecture.
        # Minutes of model calls, so it runs in the background — but the TARGET is
        # resolved right here on the main thread, because resolving it needs the
        # browser's current URL and Selenium is not thread-safe. Only the slow,
        # browser-free remainder is handed off.
        target, err = _resolve_repo_target(parameter, repo)
        if err or not target:
            return {"success": False, "message": err or "Open a repo first, or tell me which repo you want."}
        import background_tasks
        import repo_notes
        return background_tasks.start(
            f"writing up notes on {target}",
            lambda: repo_notes.generate(target),
            ack=f"I'll read through {target} and write up notes on its "
                f"architecture in the background. Keep talking to me, and I'll "
                f"tell you when it's done.")

    if action == "clone repo":
        # REAL git clone into Documents\GitHub Clones (default, spoken aloud).
        # Optional parameter overrides the destination: "clone repo|D:\code".
        # PAT auth for private repos goes through an env var + credential
        # helper so the token NEVER lands in .git/config or process lists.
        if not repo and parameter and "/" in (parameter or "") and "\\" not in parameter:
            repo = parameter.strip()
            parameter = None
        if not repo:
            return {"success": False, "message": "Open a repo first, or say the full owner/name."}
        if shutil.which("git") is None:
            return {"success": False, "message": "Git isn't installed or isn't on your PATH, so I can't clone. Install Git for Windows first."}
        base_dir = (parameter.strip() if parameter and parameter.strip()
                    else os.path.join(os.path.expanduser("~"), "Documents", "GitHub Clones"))
        dest = os.path.join(base_dir, repo.split("/")[1])
        import security_guard
        if security_guard.is_codebase_path(dest) or security_guard.is_codebase_path(base_dir):
            return {"success": False, "message": "Cloning into Akira's source code tree is strictly not permitted."}
        if os.path.isdir(dest) and os.listdir(dest):
            return {"success": False, "message": f"{repo.split('/')[1]} already exists in {base_dir} — it looks like you've cloned it before."}
        try:
            os.makedirs(base_dir, exist_ok=True)
        except Exception as e:
            return {"success": False, "message": f"Couldn't create the folder {base_dir}: {e}"}
        url = f"https://github.com/{repo}.git"
        env = os.environ.copy()
        cmd = ["git", "clone", "--", url, dest]
        if _gh_token():
            # credential helper reads the PAT from env — keeps it out of the
            # remote URL, .git/config, and the visible command line
            env["GIT_ASKPASS_TOKEN"] = _gh_token()
            cmd = ["git",
                   "-c", 'credential.helper=!f() { echo "username=x-access-token"; echo "password=$GIT_ASKPASS_TOKEN"; }; f',
                   "clone", "--", url, dest]
        else:
            env["GIT_TERMINAL_PROMPT"] = "0"  # fail fast instead of hanging on a prompt
        # Everything above is fast validation and stays inline, so a bad path or
        # a missing git is still reported instantly. Only the clone itself — up to
        # five minutes of network I/O — goes to the background, because the user
        # has no reason to sit in silence waiting for a download.
        def _run_clone() -> dict:
            try:
                proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired:
                return {"success": False, "message": f"Cloning {repo} timed out after five minutes — it may be a huge repo or a slow connection."}
            except Exception as e:
                return {"success": False, "message": f"Couldn't run git: {e}"}
            if proc.returncode == 0:
                return {"success": True, "message": f"Cloned {repo} into {dest}."}
            err = (proc.stderr or "").strip().splitlines()
            err_line = err[-1] if err else "unknown git error"
            if "Authentication failed" in str(proc.stderr) or "could not read" in str(proc.stderr):
                return {"success": False, "message": f"Git couldn't authenticate for {repo} — if it's private, check that your GITHUB_TOKEN has repo scope."}
            if "already exists" in str(proc.stderr):
                return {"success": False, "message": f"{repo.split('/')[1]} already exists in {base_dir}."}
            return {"success": False, "message": f"Clone failed: {err_line[:120]}"}

        import background_tasks
        return background_tasks.start(
            f"cloning {repo}",
            _run_clone,
            ack=f"Cloning {repo} into {base_dir} in the background. I'll tell you "
                f"when it's finished.")

    # ── Tier A: writes via DOM (logged-in session) or PAT if available ──────
    if action in ("star repo", "unstar repo"):
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        starring = action == "star repo"
        if _gh_token():
            ok, err = _gh_api(f"/user/starred/{repo}", "PUT" if starring else "DELETE")
            if ok:
                return {"success": True, "message": f"{'Starred' if starring else 'Unstarred'} {repo}."}
        # DOM: .starring-container holds both forms; the visible one is current state
        clicked = _nfx_click_first(browser, [
            f'.starring-container .{"unstarred" if starring else "starred"} button',
            f'button[aria-label*="{"Star this repository" if starring else "Unstar this repository"}"]',
        ])
        if clicked:
            return {"success": True, "message": f"{'Starred' if starring else 'Unstarred'} {repo}."}
        return {"success": False, "message": "Couldn't find the star button — are you logged into GitHub?"}

    if action == "fork repo":
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        if _gh_token():
            ok, data = _gh_api(f"/repos/{repo}/forks", "POST")
            if ok:
                return {"success": True, "message": f"Forked {repo} to {data.get('full_name', 'your account')}."}
        browser.get(f"https://github.com/{repo}/fork")
        time.sleep(1.5)
        el = _gh_click_text_button(browser, ["create fork"])
        if el:
            el.click()
            return {"success": True, "message": f"Forking {repo}."}
        return {"success": False, "message": "Couldn't find the Create Fork button — are you logged in? You may already have a fork."}

    if action == "create issue":
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        parts = (parameter or "").split("|")
        title = parts[0].strip() if parts and parts[0].strip() else None
        issue_body = parts[1].strip() if len(parts) > 1 else ""
        if not title:
            return {"success": False, "message": "Give me a title for the issue."}
        if _gh_token():
            ok, data = _gh_api(f"/repos/{repo}/issues", "POST",
                               {"title": title, "body": issue_body})
            if ok:
                return {"success": True, "message": f"Created issue #{data['number']}: {title}."}
            return {"success": False, "message": data}
        # PLACEHOLDER-UNVERIFIED: GitHub's new React issue form. Navigates and
        # fills by aria-label/placeholder; needs a live capture to confirm.
        browser.get(f"https://github.com/{repo}/issues/new")
        time.sleep(1.5)
        try:
            filled = browser.execute_script("""
                var t = document.querySelector(
                    'input[aria-label="Add a title"], input[placeholder="Title"], #issue_title');
                var b = document.querySelector(
                    'textarea[aria-label*="description" i], textarea[placeholder*="description" i], #issue_body');
                if (!t) return false;
                var setV = function (el, v) {
                    var proto = el.tagName === 'TEXTAREA' ?
                        HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                };
                setV(t, arguments[0]);
                if (b) setV(b, arguments[1]);
                return true;
            """, title, issue_body)
        except Exception:
            filled = False
        if not filled:
            return {"success": False, "message": "Couldn't fill the issue form — the page may have changed, or you need to log in. With a GITHUB_TOKEN set I can do this reliably."}
        el = _gh_click_text_button(browser, ["submit new issue", "create"])
        if el:
            el.click()
            return {"success": True, "message": f"Created issue: {title}."}
        return {"success": False, "message": "Filled the form but couldn't find the submit button."}

    # ── GATED actions (only reachable after akira.py's confirmation gate) ──
    if action in ("close issue", "close pull request"):
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        num = re.sub(r"\D", "", parameter or "")
        if not num:
            return {"success": False, "message": "Which number? Say close issue 12."}
        if _gh_token():
            path = f"/repos/{repo}/issues/{num}" if action == "close issue" else f"/repos/{repo}/pulls/{num}"
            ok, data = _gh_api(path, "PATCH", {"state": "closed"})
            if ok:
                return {"success": True, "message": f"Closed #{num}."}
            return {"success": False, "message": data}
        kind = "issues" if action == "close issue" else "pull"
        browser.get(f"https://github.com/{repo}/{kind}/{num}")
        time.sleep(1.5)
        el = _gh_click_text_button(browser, ["close issue", "close pull request", "close with comment"])
        if el:
            el.click()
            return {"success": True, "message": f"Closed #{num}."}
        return {"success": False, "message": f"Couldn't find the close button on #{num} — you may not have permission."}

    if action == "merge pull request":
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        num = re.sub(r"\D", "", parameter or "")
        if not num:
            return {"success": False, "message": "Which PR number? Say merge pull request 7."}
        if _gh_token():
            ok, data = _gh_api(f"/repos/{repo}/pulls/{num}/merge", "PUT", {})
            if ok:
                return {"success": True, "message": f"Merged pull request #{num}."}
            return {"success": False, "message": data}
        # CONFIRMED current selector via refined-github's maintained list:
        # merge box lives in [data-testid="mergebox-partial"]
        browser.get(f"https://github.com/{repo}/pull/{num}")
        time.sleep(2.0)
        clicked = _nfx_click_first(browser, ['[data-testid="mergebox-partial"] button'])
        if not clicked:
            el = _gh_click_text_button(browser, ["merge pull request"])
            if el:
                el.click()
                clicked = True
        if not clicked:
            return {"success": False, "message": f"Couldn't find the merge button on #{num} — it may have conflicts or need reviews."}
        time.sleep(1.0)
        el = _gh_click_text_button(browser, ["confirm merge"])
        if el:
            el.click()
            return {"success": True, "message": f"Merged pull request #{num}."}
        return {"success": False, "message": "Opened the merge menu but couldn't confirm — please check the page."}

    if action == "create pull request":
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        if not parameter:
            return {"success": False, "message": "Tell me the branch, like create pull request feature-x."}
        if _gh_token():
            parts = parameter.split("|")
            head = parts[0].strip()
            title = parts[1].strip() if len(parts) > 1 else f"Merge {head}"
            ok, repo_data = _gh_api(f"/repos/{repo}")
            base = repo_data.get("default_branch", "main") if ok else "main"
            ok, data = _gh_api(f"/repos/{repo}/pulls", "POST",
                               {"title": title, "head": head, "base": base})
            if ok:
                return {"success": True, "message": f"Created pull request #{data['number']}: {title}."}
            return {"success": False, "message": data}
        # PLACEHOLDER-UNVERIFIED: compare page flow needs a live capture
        head = parameter.split("|")[0].strip()
        browser.get(f"https://github.com/{repo}/compare/{urllib.parse.quote(head)}?expand=1")
        time.sleep(1.5)
        el = _gh_click_text_button(browser, ["create pull request"])
        if el:
            el.click()
            time.sleep(1.5)
            el2 = _gh_click_text_button(browser, ["create pull request"])
            if el2:
                el2.click()
                return {"success": True, "message": f"Created pull request from {head}."}
        return {"success": False, "message": "Couldn't complete the PR form — with a GITHUB_TOKEN set I can do this reliably."}

    if action == "delete branch":
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        if not parameter:
            return {"success": False, "message": "Which branch? Say delete branch old-feature."}
        if _gh_token():
            ok, data = _gh_api(f"/repos/{repo}/git/refs/heads/{urllib.parse.quote(parameter.strip())}", "DELETE")
            if ok:
                return {"success": True, "message": f"Deleted branch {parameter}."}
            return {"success": False, "message": data}
        return {"success": False, "message": "Deleting branches needs a GITHUB_TOKEN — I won't do this through fragile page clicks."}

    if action in ("delete repo", "delete repository"):
        # Same severity as shutdown/delete_files. PAT-ONLY by design: the DOM
        # flow (settings -> danger zone -> retype repo name) is too fragile to
        # trust for something this destructive.
        if not repo and parameter and "/" in parameter:
            repo = parameter.strip()
        if not repo:
            return {"success": False, "message": "Open the repo first or say the full owner/name."}
        if not _gh_token():
            return {"success": False, "message": f"Deleting {repo} needs a GITHUB_TOKEN with delete permissions. I won't attempt this through page clicks — it's irreversible."}
        ok, data = _gh_api(f"/repos/{repo}", "DELETE")
        if ok:
            return {"success": True, "message": f"Deleted {repo}. That's permanent."}
        return {"success": False, "message": data}

    if action in ("push", "force push"):
        return {"success": False, "message": "Pushing code is out of my scope — I don't run git operations. Do that from your terminal."}

    return {"success": False, "message": f"Unknown github_control action: {action}"}


# ── Gmail compose (browser automation, DRAFT ONLY — send is unreachable) ────

def gmail_compose(action: str, parameter: str | None = None) -> dict:
    """
    Fill a Gmail compose window in the browser and STOP. Never sends.

    Actions:
      draft|to|subject|body      body is user-dictated text (may contain |)
      generate|to|subject|brief  Gemini (gemini_content.py) writes the body

    SEND-SAFETY IS STRUCTURAL, NOT CONVENTIONAL. Audit checklist for anyone
    editing this function — all of these must stay true:
      1. The ONLY navigation is the compose=new URL; the ONLY element writes
         are send_keys to the To/Subject fields and a JS innerText set on the
         Body div, each located by a fixed allowlisted selector.
      2. There is NO .click() call, NO delegation to _handle_click /
         atomic_click, and NO selector that can match the
         Send button (its aria-label and tooltip contain "Send"; nothing
         here queries by aria-label except the exact strings below).
      3. NO keyboard chords are ever emitted — Gmail sends on Ctrl+Enter /
         Cmd+Enter, so no Keys.CONTROL / Keys.COMMAND / Keys.ENTER is sent
         anywhere in this function. Newlines in the body are inserted via
         JS text assignment, not keystrokes.
    Deliberately avoids the Gmail MCP server for drafting: its draft_email
    tool requires a send-capable OAuth token (gmail.modify + mail.google.com),
    which would break the token-level read-only guarantee on akira-gmail-ro.
    """
    print(f"[gmail_compose] action={action!r}, parameter={parameter!r}")
    action_clean = (action or "").strip().lower()
    if action_clean not in ("draft", "generate"):
        full_param = f"{action}|{parameter}" if parameter else (action or "")
        parts = full_param.split("|", 2)
        action = "draft"
    else:
        action = action_clean
        parts = (parameter or "").split("|", 2)

    if len(parts) < 3 or not parts[0].strip():
        return {"success": False,
                "message": "Drafting needs a recipient, a subject, and the "
                           "body or a brief: to|subject|text."}
    to, subject, body = parts[0].strip(), parts[1].strip(), parts[2].strip()

    if action == "generate":
        # Pro-only: AI-authored email composition is a premium capability.
        # The 'draft' action (user-dictated text) stays on Standard.
        import tiers
        if tiers.plan_for(tiers.Layer.SERVANT) != tiers.PRO:
            return {"success": False, "speak": True,
                    "message": "AI-generated email drafting is a Pro tier feature. "
                               "You can still draft emails with your own text using 'draft'."}
        import gemini_content
        gen = gemini_content.generate(
            body,
            format_instructions=(
                "Write it as a plain-text email body only — no subject line, "
                "no To/From headers, no markdown, no signature placeholders "
                "like [Your Name] unless a name was given in the brief."),
            length="short")
        if not gen.get("success"):
            return gen
        body = gen["text"]
        # Post-processing: strip markdown bold/italics/headers so raw syntax never lands in the Gmail DOM
        body = re.sub(r'\*\*(.+?)\*\*', r'\1', body)
        body = re.sub(r'__(.+?)__', r'\1', body)
        body = re.sub(r'^#{1,6}\s+', '', body, flags=re.MULTILINE)

    browser = get_browser(_last_browser_name)
    try:
        browser.switch_to.window(browser._akira_tab)
    except Exception:
        return {"success": False, "message": "Lost track of my working tab."}

    # compose=new opens the compose window straight from the URL — no
    # Compose-button click needed, which keeps rule 2 above trivially true.
    browser.get("https://mail.google.com/mail/u/0/#inbox?compose=new")
    try:
        WebDriverWait(browser, 15).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, 'input[name="subjectbox"]')))
    except Exception:
        return {"success": False,
                "message": "Gmail's compose window didn't open — you may "
                           "not be signed in to Gmail in this browser."}
    time.sleep(0.5)  # compose dialog finishes wiring its fields

    def _first_visible(selectors: list):
        for sel in selectors:
            try:
                for el in browser.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed():
                        return el
            except Exception:
                continue
        return None

    to_el = _first_visible(['input[peoplekit-id="BbVjBd"]',
                            'input[aria-label="To recipients"]',
                            'textarea[name="to"]'])
    if not to_el:
        return {"success": False, "message": "Couldn't find the To field in the compose window."}
    to_el.send_keys(to)   # plain characters only — never Keys.* constants

    subj_el = _first_visible(['input[name="subjectbox"]'])
    if not subj_el:
        return {"success": False, "message": "Couldn't find the Subject field."}
    subj_el.send_keys(subject)  # focusing subject also chips the recipient

    # Body is contenteditable; set text via JS so multi-line content needs
    # zero keystrokes (rule 3) and long bodies don't crawl through send_keys.
    ok = browser.execute_script("""
        var el = document.querySelector('div[aria-label="Message Body"]')
              || document.querySelector('div[g_editable="true"][role="textbox"]');
        if (!el) return false;
        el.focus();
        el.innerText = arguments[0];
        el.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
    """, body)
    if not ok:
        return {"success": False, "message": "Couldn't find the message body field."}

    return {"success": True,
            "message": f"Draft is ready in Gmail — to {to}, subject {subject}. "
                       "I never touch Send: review it and send it yourself."}


# ������ File operations (standalone) + VS Code control ───────────────────────────
# One function per capability. Standalone actions (create_file, read_file,
# write_file, edit_file, search_file) are the default route; vscode_control
# calls the SAME functions when the user explicitly says "in VS Code".
# Gating travels with the capability: write_file / edit_file are gated by
# akira.py's safety net under BOTH entry points.

_vsc_last_folder: str | None = None   # session memory for path resolution
_vsc_last_file: str | None = None

_WIN_VAR = re.compile(r"%([^%]+)%")


def _normalize_path(path: str) -> str:
    """Expand env vars (both $VAR and %VAR% styles) and ~, on ANY platform.
    os.path.expandvars only handles %VAR% on Windows — the live-log bug was
    a literal %USERNAME% surviving into a file operation, so we expand
    %VAR% manually as a portable second pass."""
    p = path.strip().strip('"').strip("'")
    p = os.path.expandvars(p)
    p = _WIN_VAR.sub(lambda m: os.environ.get(m.group(1), m.group(0)), p)
    return os.path.expanduser(p)


def _vsc_code_cli() -> str | None:
    """Find the VS Code CLI — same preflight pattern as git in clone_repo.
    Windows installs 'code.cmd'; shutil.which finds either."""
    return shutil.which("code") or shutil.which("code.cmd")


def _resolve_path(path: str | None, want_dir: bool = False) -> tuple[str | None, str | None]:
    """Deterministic path resolution: explicit absolute path > relative to
    last-used session folder > relative to home. Returns (path, error)."""
    if not path or not path.strip():
        return None, ("Which folder?" if want_dir else "Which file?") + \
            " Tell me the full path, or a name inside the folder we're working in."
    p = _normalize_path(path)
    if os.path.isabs(p):
        return p, None
    # relative: try last session folder first, then home
    if _vsc_last_folder:
        candidate = os.path.join(_vsc_last_folder, p)
        if os.path.exists(candidate) or want_dir is False:
            return candidate, None
    return os.path.join(os.path.expanduser("~"), p), None


def _remember(fpath: str):
    global _vsc_last_folder, _vsc_last_file
    _vsc_last_file = fpath
    _vsc_last_folder = os.path.dirname(fpath)


def create_file(parameter: str | None = None) -> dict:
    """create_file|path|optional content — refuses to clobber existing files."""
    print(f"[create_file] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    fpath, err = _resolve_path(parts[0] if parts and parts[0] else None)
    if err:
        return {"success": False, "message": err}
    import security_guard
    if security_guard.is_codebase_path(fpath):
        return {"success": False, "message": "Self-modification of Akira's source code is strictly not permitted."}
    if os.path.exists(fpath):
        return {"success": False, "message": f"{os.path.basename(fpath)} already exists — say write file if you want to overwrite it."}
    content = "|".join(parts[1:]) if len(parts) > 1 else ""
    try:
        os.makedirs(os.path.dirname(fpath) or ".", exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "message": f"Couldn't create the file: {e}"}
    _remember(fpath)
    return {"success": True, "message": f"Created {os.path.basename(fpath)} in {os.path.dirname(fpath)}."}


def _extract_document_text(fpath: str, max_chars: int = 24000) -> tuple[str | None, str | None]:
    """Shared PDF/docx text extraction. Returns (text, error) — exactly one
    is None. Factored out of summarize_file (where it was proven live) so
    read_file and file_to_doc reuse the SAME extraction path instead of
    growing second implementations."""
    name = os.path.basename(fpath)
    ext = os.path.splitext(fpath)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # older install name
            except ImportError:
                return None, "I need the pypdf package to read PDFs — run pip install pypdf and I'll be able to read them."
        try:
            reader = PdfReader(fpath)
            pages = [p.extract_text() or "" for p in reader.pages[:15]]
            text = "\n".join(pages).strip()
        except Exception as e:
            return None, f"Couldn't read that PDF: {e}"
        if not text:
            return None, f"{name} has no extractable text — it's probably scanned images."
        return text[:max_chars], None
    if ext == ".docx":
        try:
            import docx  # python-docx
            text = "\n".join(p.text for p in docx.Document(fpath).paragraphs).strip()
        except ImportError:
            return None, "I need the python-docx package for Word files — run pip install python-docx."
        except Exception as e:
            return None, f"Couldn't read that document: {e}"
        if not text:
            return None, f"{name} is empty — nothing to read."
        return text[:max_chars], None
    return None, f"No text extractor for {ext[1:] if ext else 'that kind of'} files."


# Memory guard for loading a text file to read aloud. NOT a spoken limit — the
# spoken limit is chunked_read.SPOKEN_CHUNK_CHARS. A file bigger than this is
# still read, just not held in memory beyond this point.
_READ_ALOUD_MAX_CHARS = 400_000


def _summarize_for_speech(text: str, filename: str) -> str:
    """Generate a crisp 1-2 sentence spoken summary for voice output.
    Uses gemini_content / groq if available, falling back cleanly to heuristic extraction."""
    t_clean = (text or "").strip()
    if not t_clean:
        return f"{filename} is empty."
    if len(t_clean) <= 200:
        return f"{filename} reads: {t_clean}"
    try:
        import gemini_content
        res = gemini_content.generate(
            f"Summarize the following document content in 1 or 2 concise spoken sentences for a voice assistant. No markdown, no preambles: {t_clean[:4000]}",
            "Output 1 to 2 clear spoken sentences describing what the file is and its main highlights. Plain spoken English.",
            "short"
        )
        if res.get("success") and res.get("text"):
            s = res["text"].strip().replace("\n", " ")
            s = (s.replace("\u2011", "-")
                  .replace("\u2013", "-")
                  .replace("\u2014", "-")
                  .replace("\u2018", "'")
                  .replace("\u2019", "'")
                  .replace("\u201c", '"')
                  .replace("\u201d", '"'))
            if len(s) > 15:
                return s
    except Exception:
        pass

    # Fast offline fallback: extract clean title / opening line
    lines = [ln.strip() for ln in t_clean.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    first_few = " ".join(lines[:2])[:150]
    words = len(t_clean.split())
    return f"{filename} is a {words}-word file covering {first_few}."


def read_file(parameter: str | None = None) -> dict:
    """read_file|path|[detailed] — summarizes the file by default and primes
    chunked_read for detailed reading on follow-up. If 'detailed' is explicitly
    passed, speaks the first chunk immediately."""
    print(f"[read_file] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    fpath, err = _resolve_path(parts[0] if parts and parts[0] else None)
    if err:
        return {"success": False, "message": err}
    if not os.path.isfile(fpath):
        return {"success": False, "message": f"That file doesn't exist: {fpath}"}
    ext = os.path.splitext(fpath)[1].lower()
    name = os.path.basename(fpath)
    is_detailed = len(parts) > 1 and parts[1].strip().lower() in ("detail", "detailed", "full", "all", "verbatim")

    # PDFs/docx are extractable — same proven path summarize_file uses
    if ext in {".pdf", ".docx"}:
        text, xerr = _extract_document_text(fpath)
        if xerr:
            return {"success": False, "message": xerr}
        _remember(fpath)
        import chunked_read
        if is_detailed:
            first = chunked_read.begin(name, text)
            return {"success": True, "speak": True, "message": first["message"]}
        chunked_read.prime(name, text)
        summary = _summarize_for_speech(text, name)
        return {"success": True, "speak": True,
                "message": f"{summary} Would you like me to read it in detail?",
                "detail": f"File: {name}\n" + text[:2000]}

    # binary guard — reading an image/exe as text produces spoken garbage
    if ext in {".doc", ".xls", ".xlsx", ".ppt", ".pptx",
               ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic",
               ".mp3", ".mp4", ".wav", ".mkv", ".avi", ".mov", ".zip", ".rar",
               ".7z", ".exe", ".msi", ".dll", ".bin", ".iso"}:
        return {"success": False,
                "message": f"{name} is a {ext[1:]} file — I can't read it as text. Say 'open it' and I'll launch it in the default app instead."}
    try:
        with open(fpath, "rb") as f:
            raw = f.read(_READ_ALOUD_MAX_CHARS)
        if b"\x00" in raw[:4000]:  # unknown binary format
            return {"success": False,
                    "message": f"{name} looks like a binary file — I can't read it as text. Want me to open it instead?"}
        content = raw.decode("utf-8", errors="replace")
    except Exception as e:
        return {"success": False, "message": f"Couldn't read the file: {e}"}
    _remember(fpath)
    import chunked_read
    if is_detailed:
        first = chunked_read.begin(name, content)
        return {"success": True, "speak": True, "message": first["message"]}
    chunked_read.prime(name, content)
    summary = _summarize_for_speech(content, name)
    return {"success": True, "speak": True,
            "message": f"{summary} Would you like me to read it in detail?",
            "detail": f"File: {name}\n" + content[:2000]}


def read_more(parameter: str | None = None) -> dict:
    """read_more — speak the NEXT chunk of the read already in progress.

    Exists so 'yes, keep going' after a chunked read has somewhere to route.
    Holds no content of its own; chunked_read owns the cursor.
    """
    print(f"[read_more] called with parameter={parameter!r}")
    import chunked_read
    nxt = chunked_read.more()
    if nxt is None:
        return {"success": False, "speak": True,
                "message": "I'm not part-way through anything right now. "
                           "Tell me what to read and I'll start."}
    return {"success": True, "speak": True, "message": nxt["message"]}


def stop_reading(parameter: str | None = None) -> dict:
    """stop_reading — abandon the read in progress."""
    print(f"[stop_reading] called with parameter={parameter!r}")
    import chunked_read
    return {"success": True, "speak": True,
            "message": "Stopped there." if chunked_read.stop()
            else "I wasn't reading anything."}


def write_file(parameter: str | None = None) -> dict:
    """write_file|path|content — overwrites. GATED by akira.py's safety net
    (RISKY file actions) under EVERY entry point before this runs."""
    print(f"[write_file] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    fpath, err = _resolve_path(parts[0] if parts and parts[0] else None)
    if err:
        return {"success": False, "message": err}
    import security_guard
    if security_guard.is_codebase_path(fpath):
        return {"success": False, "message": "Self-modification of Akira's source code is strictly not permitted."}
    if len(parts) < 2:
        return {"success": False, "message": "Tell me what to write, like write file|notes.txt|the content."}
    content = "|".join(parts[1:])  # content may legitimately contain |
    existed = os.path.isfile(fpath)
    try:
        os.makedirs(os.path.dirname(fpath) or ".", exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return {"success": False, "message": f"Couldn't write the file: {e}"}
    _remember(fpath)
    return {"success": True, "message": f"{'Overwrote' if existed else 'Wrote'} {os.path.basename(fpath)} ({len(content)} chars)."}


def edit_file(parameter: str | None = None) -> dict:
    """edit_file|path|find|replace — single unique occurrence only; fails
    loud on 0 or >1 matches. GATED like write_file."""
    print(f"[edit_file] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    if len(parts) < 3:
        return {"success": False, "message": "Edit needs a file, the text to find, and the replacement — edit file|path|find|replace."}
    fpath, err = _resolve_path(parts[0] if parts[0] else None)
    if err:
        return {"success": False, "message": err}
    import security_guard
    if security_guard.is_codebase_path(fpath):
        return {"success": False, "message": "Self-modification of Akira's source code is strictly not permitted."}
    if not os.path.isfile(fpath):
        return {"success": False, "message": f"That file doesn't exist: {fpath}"}
    find_text, replace_text = parts[1], parts[2]
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {"success": False, "message": f"Couldn't read the file: {e}"}
    count = content.count(find_text)
    if count == 0:
        return {"success": False, "message": f"I couldn't find '{find_text[:40]}' in {os.path.basename(fpath)} — nothing was changed."}
    if count > 1:
        # fail loud, never guess which occurrence
        return {"success": False, "message": f"'{find_text[:40]}' appears {count} times in {os.path.basename(fpath)} — I won't guess which one. Give me more surrounding text to make it unique."}
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content.replace(find_text, replace_text, 1))
    except Exception as e:
        return {"success": False, "message": f"Couldn't write the edit: {e}"}
    _remember(fpath)
    return {"success": True, "message": f"Replaced it in {os.path.basename(fpath)}."}


def search_file(parameter: str | None = None) -> dict:
    """search_file|query|optional search_root|optional content_flag —
    fast indexed search over SQLite index. Zero live filesystem walks."""
    print(f"[search_file] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    name = parts[0].strip() if parts and parts[0].strip() else None
    if not name:
        return {"success": False, "message": "What file should I look for?"}

    root = None
    if len(parts) > 1 and parts[1].strip():
        resolved_root, rerr = _resolve_folder(parts[1])
        if not rerr:
            root = resolved_root

    is_content = False
    if len(parts) > 2 and parts[2].strip().lower() in ("content", "true", "1", "inside"):
        is_content = True
    elif any(kw in name.lower() for kw in ("containing ", "search inside ", "with text ")):
        is_content = True
        name = re.sub(r"\b(containing|search inside|with text)\b", "", name, flags=re.I).strip()

    try:
        import file_index
        return file_index.search_files(name, root=root, content=is_content)
    except Exception as e:
        print(f"[search_file] file_index error: {e}")
        return {"success": False, "message": f"Could not complete file search: {e}"}


def manage_index_scope(parameter: str | None = None) -> dict:
    """manage_index_scope|action|folder_path — voice management of indexed scope."""
    import file_index
    parts = (parameter or "").split("|")
    action = parts[0].strip() if parts and parts[0].strip() else "status"
    folder = parts[1].strip() if len(parts) > 1 else None
    if folder:
        clean_folder = re.sub(r"^my\s+", "", folder, flags=re.I).strip()
        resolved, _ = _resolve_folder(clean_folder)
        if resolved:
            folder = resolved
    return file_index.manage_index_scope(action, folder)


def index_stats(parameter: str | None = None) -> dict:
    """index_stats — report current index database size and statistics."""
    import file_index
    return file_index.get_index_stats()


# ── Bulk file operations ──────────────────────────────────────────────────────
# MCP NOTE (bible §7.1): no MCP client is wired into this app yet, so these
# are custom implementations. move_files and file search map cleanly onto the
# official MCP filesystem server (move_file / search_files) and should migrate
# once an MCP client exists; copy/delete/compress/extract/organize/bulk-rename
# have NO official MCP filesystem equivalents and stay custom regardless.
#
# GATING PATTERN: destructive bulk ops do a DRY-RUN RESOLVE first and return
# {"needs_confirmation", "confirm_message" (spoken enumeration), "_execute"}.
# akira.py speaks the enumeration and only runs _execute after a spoken yes —
# the same pause machinery as click confirmation. Gating lives HERE, with the
# implementation, so no entry point can bypass it.

_VAGUE_SPECS = frozenset({"*", "*.*", "everything", "all", "all files", "files"})


def _resolve_targets(spec: str | None, root: str | None = None,
                     include_dirs: bool = False) -> tuple[list, str | None, str | None]:
    """Resolve a comma-list / glob / partial name to an EXACT target list.
    include_dirs=True lets delete/move/copy/compress operate on FOLDERS too.
    Returns (targets, root_used, error). Never guesses broadly."""
    if not spec or not spec.strip():
        return [], None, "Which files? Give me names or a pattern like *.png."
    if spec.strip().lower() in _VAGUE_SPECS:
        return [], None, "That's too broad — tell me which files specifically, like *.png or the file names."
    base = _normalize_path(root) if root else (_vsc_last_folder or os.path.expanduser("~"))
    if not os.path.isdir(base):
        return [], None, f"That folder doesn't exist: {base}"

    def _ok(p: str) -> bool:
        return os.path.isfile(p) or (include_dirs and os.path.isdir(p))

    files: list = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        p = _normalize_path(part)
        p_name = os.path.basename(p) if os.path.sep in p else part
        p_stem = os.path.splitext(p_name)[0].lower()

        # 1. Exact match
        if os.path.isabs(p) and _ok(p):
            files.append(p)
            continue

        # 2. Check common extensions if given without extension
        ext_hit = None
        for ext in (".docx", ".pdf", ".txt", ".xlsx", ".csv", ".doc", ".png", ".jpg", ".zip"):
            candidate = p + ext if os.path.isabs(p) else os.path.join(base, part + ext)
            if _ok(candidate):
                ext_hit = candidate
                break
        if ext_hit:
            files.append(ext_hit)
            continue

        if any(ch in part for ch in "*?["):
            files.extend(f for f in glob.glob(os.path.join(base, part)) if _ok(f))
        elif _ok(os.path.join(base, part)):
            files.append(os.path.join(base, part))
        else:  # partial name / stem — search directory tree and user folders
            hits = []
            # If path has a directory component, check it and its subdirectories (e.g. Downloads/Documents)
            p_dir = os.path.dirname(p) if os.path.isabs(p) or os.path.sep in p else base
            if os.path.isdir(p_dir):
                for root_dir, dirs, fn_list in os.walk(p_dir):
                    for fn in fn_list:
                        if (p_stem in fn.lower() or part.lower() in fn.lower()) and _ok(os.path.join(root_dir, fn)):
                            hits.append(os.path.join(root_dir, fn))
                    if len(root_dir) > len(p_dir) + 30:  # don't walk too deep
                        break

            if not hits:
                # Check user's Downloads, Documents, Desktop
                for alt_dir in [
                    os.path.join(os.path.expanduser("~"), "Downloads"),
                    os.path.join(os.path.expanduser("~"), "Documents"),
                    os.path.join(os.path.expanduser("~"), "Desktop")
                ]:
                    if os.path.isdir(alt_dir) and alt_dir != p_dir:
                        for root_dir, dirs, fn_list in os.walk(alt_dir):
                            for fn in fn_list:
                                if (p_stem in fn.lower() or part.lower() in fn.lower()) and _ok(os.path.join(root_dir, fn)):
                                    hits.append(os.path.join(root_dir, fn))
                            if len(root_dir) > len(alt_dir) + 30:
                                break
                            if hits:
                                break

            if not hits:
                # Finally, query the drive map
                try:
                    from file_index.scanner import lookup_in_drive_map
                    for query_term in (p_stem, p_name, part):
                        map_hits = lookup_in_drive_map(query_term)
                        for mh in map_hits:
                            mp = mh.get("path")
                            if mp and _ok(mp) and mp not in hits:
                                hits.append(mp)
                        if hits:
                            break
                except Exception:
                    pass

            hits = list(dict.fromkeys(hits))  # preserve order, deduplicate
            if len(hits) == 1:
                files.append(hits[0])
            elif len(hits) > 1:
                names = ", ".join(os.path.basename(h) for h in hits[:6])
                return [], base, f"'{part}' matches {len(hits)} items: {names}. Which ones?"
            else:
                return [], base, f"I couldn't find '{part}' in {base} or your user folders."
    files = sorted(set(files))
    if not files:
        return [], base, f"Nothing matched '{spec}' in {base}."
    return files, base, None


def _count_kinds(targets: list) -> str:
    """'3 files' / '2 folders' / '2 folders and 3 files' — for spoken plans."""
    d = sum(1 for t in targets if os.path.isdir(t))
    f = len(targets) - d
    parts = []
    if d:
        parts.append(f"{d} folder{'s' if d != 1 else ''}")
    if f:
        parts.append(f"{f} file{'s' if f != 1 else ''}")
    return " and ".join(parts)


def _enumerate_files(files: list, limit: int = 8) -> str:
    """Spoken enumeration of exact file names — the confirmation payload."""
    names = [os.path.basename(f) for f in files[:limit]]
    extra = f", and {len(files) - limit} more" if len(files) > limit else ""
    return ", ".join(names) + extra


def _move_batch(pairs: list) -> dict:
    """Shared executor for move/organize/rename: [(src, dest_path), ...]."""
    moved, failed = 0, []
    for src, dest in pairs:
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
            moved += 1
        except Exception as e:
            failed.append(f"{os.path.basename(src)} ({e})")
    if failed:
        return {"success": moved > 0,
                "message": f"Moved {moved}, but {len(failed)} failed: {'; '.join(failed[:3])}"}
    return {"success": True, "message": f"Done — {moved} file{'s' if moved != 1 else ''} moved."}


def _gated(confirm_message: str, execute_fn) -> dict:
    """Standard gated-plan result — akira.py speaks confirm_message and runs
    execute_fn only after a spoken yes."""
    return {"needs_confirmation": True, "confirm_message": confirm_message,
            "message": confirm_message, "_execute": execute_fn}


# Spoken names for standard user folders — the LLM sends what the user SAYS
# ("pictures", "downloads"), not a path. Resolved before any disk lookup.
_KNOWN_FOLDERS = {
    "home": "~", "user folder": "~",
    "desktop": "~/Desktop", "documents": "~/Documents", "docs": "~/Documents",
    "downloads": "~/Downloads", "download": "~/Downloads",
    "pictures": "~/Pictures", "photos": "~/Pictures", "images": "~/Pictures",
    "music": "~/Music", "videos": "~/Videos", "movies": "~/Videos",
    "screenshots": "~/Pictures/Screenshots",
    "c drive": "C:\\", "c": "C:\\", "d drive": "D:\\", "e drive": "E:\\",
}


def _resolve_folder(name: str | None) -> tuple[str | None, str | None]:
    """Resolve a spoken folder reference: known name > absolute path >
    relative to session folder > relative to home. Returns (path, error)."""
    if not name or not name.strip():
        return None, "Which folder? Say a name like downloads, or a full path."
    key = name.strip().strip('"').lower().rstrip("\\/") or name.strip()
    if key in _KNOWN_FOLDERS:
        return os.path.expanduser(_KNOWN_FOLDERS[key].replace("/", os.sep)), None
    p = _normalize_path(name)
    if os.path.isabs(p):
        return p, None
    # the session folder ITSELF ("list New Folder" right after opening it)
    if _vsc_last_folder and os.path.basename(_vsc_last_folder).lower() == p.lower():
        return _vsc_last_folder, None
    # subfolder of session folder, sibling (parent's child), or under home
    bases = [_vsc_last_folder,
             os.path.dirname(_vsc_last_folder) if _vsc_last_folder else None,
             os.path.expanduser("~")]
    for base in filter(None, bases):
        candidate = os.path.join(base, p)
        if os.path.isdir(candidate):
            return candidate, None
    # last chance: case-insensitive partial match inside session folder
    if _vsc_last_folder and os.path.isdir(_vsc_last_folder):
        hits = [d for d in os.listdir(_vsc_last_folder)
                if p.lower() in d.lower() and os.path.isdir(os.path.join(_vsc_last_folder, d))]
        if len(hits) == 1:
            return os.path.join(_vsc_last_folder, hits[0]), None
    return None, f"I couldn't find a folder called '{name}'. Give me the full path or say one of your main folders like documents or downloads."


def _navigate_existing_explorer(folder: str) -> bool:
    """Navigate an already-open File Explorer window to `folder` instead of
    spawning a new window every time. Uses the Shell.Application COM API.
    Returns True if an existing window was reused."""
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("Shell.Application")
            for w in shell.Windows():
                try:
                    # Explorer windows report explorer.exe as FullName;
                    # skip Internet Explorer/Edge shell windows
                    if not w or "explorer" not in os.path.basename(str(w.FullName)).lower():
                        continue
                    w.Navigate2(folder)
                    try:  # bring it to the front
                        win32gui.SetForegroundWindow(w.HWND)
                    except Exception:
                        pass
                    return True
                except Exception:
                    continue
        finally:
            pythoncom.CoUninitialize()
    except Exception as e:
        print(f"[open_folder] COM navigate unavailable: {e}")
    return False


def open_folder(parameter: str | None = None) -> dict:
    """open_folder|name or path — navigates the EXISTING File Explorer window
    when one is open (no window spam), otherwise opens a new one. This is THE
    way to navigate File Explorer: by path, never by clicking the GUI."""
    print(f"[open_folder] called with parameter={parameter!r}")
    folder, err = _resolve_folder(parameter)
    if err:
        return {"success": False, "message": err}
    if not os.path.isdir(folder):
        return {"success": False, "message": f"That folder doesn't exist: {folder}"}
    global _vsc_last_folder
    if os.name == "nt" and _navigate_existing_explorer(folder):
        _vsc_last_folder = folder
        return {"success": True, "message": f"Opened {os.path.basename(folder) or folder}."}
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception as e:
        return {"success": False, "message": f"Couldn't open it: {e}"}
    _vsc_last_folder = folder
    return {"success": True, "message": f"Opened {os.path.basename(folder) or folder} in File Explorer."}


def list_folder(parameter: str | None = None) -> dict:
    """list_folder|name or path|[detailed] — speaks a concise summary of what's
    inside a folder by default and primes chunked_read for detailed listing on follow-up.
    If 'detailed' is passed, speaks the full listing. Ungated, read-only."""
    print(f"[list_folder] called with parameter={parameter!r}")
    global _vsc_last_folder
    parts = (parameter or "").split("|")
    raw_folder = parts[0].strip() if parts and parts[0].strip() else None
    is_detailed = len(parts) > 1 and parts[1].strip().lower() in ("detail", "detailed", "all", "full", "verbatim")

    folder, err = _resolve_folder(raw_folder or _vsc_last_folder or "~")
    if err:
        return {"success": False, "message": err}
    if not os.path.isdir(folder):
        return {"success": False, "message": f"That folder doesn't exist: {folder}"}
    try:
        entries = sorted(os.listdir(folder), key=str.lower)
    except Exception as e:
        return {"success": False, "message": f"Couldn't read that folder: {e}"}
    dirs = [e for e in entries if os.path.isdir(os.path.join(folder, e)) and not e.startswith((".", "$"))]
    files = [e for e in entries if os.path.isfile(os.path.join(folder, e)) and not e.startswith((".", "$"))]
    _vsc_last_folder = folder
    if not dirs and not files:
        return {"success": True, "speak": True, "message": f"{os.path.basename(folder) or folder} is empty."}
    name = os.path.basename(folder) or folder

    full = []
    if dirs:
        full.append(f"{len(dirs)} folders: {', '.join(dirs[:200])}"
                    + (f" (+{len(dirs) - 200} more not shown)" if len(dirs) > 200 else ""))
    if files:
        full.append(f"{len(files)} files: {', '.join(files[:200])}"
                    + (f" (+{len(files) - 200} more not shown)" if len(files) > 200 else ""))

    if is_detailed:
        spoken = []
        if dirs:
            shown = ", ".join(dirs[:10]) + (f", and {len(dirs) - 10} more" if len(dirs) > 10 else "")
            spoken.append(f"{len(dirs)} folder{'s' if len(dirs) != 1 else ''}: {shown}")
        if files:
            shown = ", ".join(files[:10]) + (f", and {len(files) - 10} more" if len(files) > 10 else "")
            spoken.append(f"{len(files)} file{'s' if len(files) != 1 else ''}: {shown}")
        spoken_msg = f"In {name}: " + ". ".join(spoken) + "."
    else:
        total_items = len(dirs) + len(files)
        if total_items <= 3:
            all_items = [f"{d}/" for d in dirs] + files
            spoken_msg = f"In {name}: {', '.join(all_items)}."
        else:
            cat_counts = {}
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                cat = next((c for c, exts in _ORGANIZE_CATEGORIES.items() if ext in exts), "other")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            top_cats = [f"{cat.lower()} ({n})" for cat, n in sorted(cat_counts.items(), key=lambda x: -x[1])[:2]]
            types_str = f", mainly {', '.join(top_cats)}" if top_cats else ""
            folder_str = f"{len(dirs)} folder{'s' if len(dirs) != 1 else ''}" if dirs else ""
            file_str = f"{len(files)} file{'s' if len(files) != 1 else ''}" if files else ""
            counts_str = " and ".join(filter(None, [folder_str, file_str]))
            spoken_msg = f"{name} contains {counts_str}{types_str}. Would you like me to list them in detail?"

            # Prime chunked_read so if user says "yes" or "read in detail", it lists them
            import chunked_read
            listing_lines = []
            if dirs:
                listing_lines.append(f"Folders in {name}:\n" + "\n".join(f"- {d}" for d in dirs[:50]))
            if files:
                listing_lines.append(f"Files in {name}:\n" + "\n".join(f"- {f}" for f in files[:100]))
            chunked_read.prime(f"Contents of {name}", "\n\n".join(listing_lines))

    return {"success": True, "speak": True,
            "message": spoken_msg,
            "detail": f"COMPLETE listing of {folder}: " + ". ".join(full) + "."}


def open_file(parameter: str | None = None) -> dict:
    """open_file|path — opens with the OS default application. If the path is
    actually a folder, delegates to open_folder instead of failing. Ungated."""
    print(f"[open_file] called with parameter={parameter!r}")
    fpath, err = _resolve_path(parameter)
    if err:
        return {"success": False, "message": err}
    if os.path.isdir(fpath):
        return open_folder(parameter)   # user said "open X" and X is a folder
    if not os.path.isfile(fpath):
        # not on disk at the exact path — maybe it's a spoken folder name
        folder, ferr = _resolve_folder(parameter)
        if not ferr and os.path.isdir(folder):
            return open_folder(parameter)
        return {"success": False, "message": f"That file doesn't exist: {fpath}"}
    try:
        if hasattr(os, "startfile"):        # Windows
            os.startfile(fpath)
        else:                               # dev sandbox fallback
            subprocess.Popen(["xdg-open", fpath])
    except Exception as e:
        return {"success": False, "message": f"Couldn't open it: {e}"}
    _remember(fpath)
    return {"success": True, "message": f"Opened {os.path.basename(fpath)}."}


def open_study_room(parameter: str | None = None) -> dict:
    """Launch Akira Teaching Mode study room in the background and open authenticated browser.
    Ungated local application launcher.
    """
    try:
        from teaching import server
        url = server.ensure_server(open_browser=True)
        topic = (parameter or "").strip()
        msg = f"Opening your study room for {topic}." if topic else "Opening the study room."
        return {"success": True, "message": msg, "url": url}
    except Exception as e:
        print(f"[executor] open_study_room error: {e}")
        return {"success": False, "message": f"Could not launch study room: {e}"}


def _resolve_dest(raw: str) -> tuple[str | None, str | None]:
    """Destination folder: spoken name ('desktop') > absolute > relative to
    session folder. Creating a NEW folder is fine if the parent exists."""
    known, err = _resolve_folder(raw)
    if not err and known:
        return known, None
    p = _normalize_path(raw)
    if os.path.isabs(p):
        return p, None
    if _vsc_last_folder:
        return os.path.join(_vsc_last_folder, p), None
    return None, f"Where exactly? I couldn't resolve '{raw}' — give me a folder name like desktop or a full path."


def copy_files(parameter: str | None = None) -> dict:
    """copy_files|spec|dest_folder — files AND folders, non-destructive, ungated."""
    print(f"[copy_files] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    if len(parts) < 2 or not parts[1].strip():
        return {"success": False, "message": "Copy needs files and a destination — copy files|*.png|D:\\backup."}
    targets, _, err = _resolve_targets(parts[0], include_dirs=True)
    if err:
        return {"success": False, "message": err}
    dest, derr = _resolve_dest(parts[1])
    if derr:
        return {"success": False, "message": derr}
    import security_guard
    if security_guard.is_codebase_path(dest):
        return {"success": False, "message": "Copying files into Akira's source code directory is strictly prohibited."}
    try:
        os.makedirs(dest, exist_ok=True)
        for t in targets:
            target_path = os.path.join(dest, os.path.basename(t))
            if os.path.isdir(t):
                shutil.copytree(t, target_path, dirs_exist_ok=True)
            else:
                shutil.copy2(t, target_path)
    except Exception as e:
        return {"success": False, "message": f"Copy failed: {e}"}
    return {"success": True, "message": f"Copied {_count_kinds(targets)} to {os.path.basename(dest) or dest}."}


def move_files(parameter: str | None = None) -> dict:
    """move_files|spec|dest_folder — files AND folders. GATED: enumerates
    exactly what moves where, then waits for a spoken yes."""
    print(f"[move_files] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    if len(parts) < 2 or not parts[1].strip():
        return {"success": False, "message": "Move needs files and a destination — move files|*.pdf|D:\\archive."}
    is_confirmed = any(p.strip().lower() in ("confirmed", "yes", "true") for p in parts[2:])
    targets, _, err = _resolve_targets(parts[0], include_dirs=True)
    if err:
        return {"success": False, "message": err}
    import security_guard
    if any(security_guard.is_codebase_path(t) for t in targets):
        return {"success": False, "message": "Moving Akira's source code files is strictly not permitted."}
    dest, derr = _resolve_dest(parts[1])
    if derr:
        return {"success": False, "message": derr}
    pairs = [(t, os.path.join(dest, os.path.basename(t))) for t in targets]
    if is_confirmed:
        res = _move_batch(pairs)
        res["speak"] = True
        return res
    msg = (f"I'll move {_count_kinds(targets)} to {os.path.basename(dest) or dest}: "
           f"{_enumerate_files(targets)}. Should I go ahead?")
    return _gated(msg, lambda: _move_batch(pairs))


def organize_files(parameter: str | None = None) -> dict:
    """organize_files|spec|dest_folder — same operation as move_files
    (resolve, enumerate, gate); alias kept for natural phrasing."""
    print(f"[organize_files] called with parameter={parameter!r}")
    return move_files(parameter)


def delete_files(parameter: str | None = None) -> dict:
    """delete_files|spec|root? — files AND folders. STRICTEST gate: exact
    resolution first, ambiguity refused, hard cap, full enumeration spoken.
    Folders are deleted recursively — the confirmation says so explicitly."""
    print(f"[delete_files] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    is_confirmed = any(p.strip().lower() in ("confirmed", "yes", "true", "proceed", "go ahead") for p in parts[1:])
    targets, _, err = _resolve_targets(parts[0] if parts and parts[0] else None,
                                       parts[1] if len(parts) > 1 and parts[1].strip().lower() not in ("confirmed", "yes", "true") else None,
                                       include_dirs=True)
    if err:
        return {"success": False, "message": err}   # vague/ambiguous → ask, never guess
    import security_guard
    if any(security_guard.is_codebase_path(t) for t in targets):
        return {"success": False, "message": "Self-modification or deletion of Akira's source code is strictly not permitted."}
    if len(targets) > 15:
        return {"success": False, "message": f"That would delete {len(targets)} items — too many to do safely in one go. Narrow it down and I'll enumerate them."}
    n_dirs = sum(1 for t in targets if os.path.isdir(t))
    kinds = _count_kinds(targets)  # BEFORE deletion — isdir() is False after
    def _do():
        failed = []
        for t in targets:
            try:
                if os.path.isdir(t):
                    shutil.rmtree(t)
                else:
                    os.remove(t)
            except Exception as e:
                failed.append(f"{os.path.basename(t)} ({e})")
        if failed:
            return {"success": len(failed) < len(targets),
                    "message": f"Deleted {len(targets) - len(failed)}, but couldn't delete: {'; '.join(failed[:3])}"}
        return {"success": True, "message": f"Deleted {kinds}. That's permanent."}
    if is_confirmed:
        res = _do()
        res["speak"] = True
        return res
    warning = " Folders go with everything inside them." if n_dirs else ""
    msg = (f"This will permanently delete {kinds}: "
           f"{_enumerate_files(targets, limit=15)}.{warning} Are you sure?")
    return _gated(msg, _do)


_ORGANIZE_CATEGORIES = {
    "Images":     {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".heic"},
    "Documents":  {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".md"},
    "Videos":     {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "Audio":      {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
    "Archives":   {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installers": {".exe", ".msi", ".dmg"},
    "Code":       {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".c", ".cpp", ".sh"},
}


def organize_folder(parameter: str | None = None) -> dict:
    """organize_folder|folder — plans category subfolders by extension,
    GATED with a spoken per-category enumeration. If confirmed, executes directly."""
    print(f"[organize_folder] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    raw_folder = parts[0].strip() if parts else parameter
    is_confirmed = len(parts) > 1 and parts[1].strip().lower() in ("confirmed", "yes", "true", "proceed", "go ahead")
    folder, err = _resolve_path(raw_folder, want_dir=True)
    if err:
        return {"success": False, "message": err}
    import security_guard
    if security_guard.is_codebase_path(folder):
        return {"success": False, "message": "Organizing Akira's source code directory is strictly prohibited."}
    if not os.path.isdir(folder):
        return {"success": False, "message": f"That folder doesn't exist: {folder}"}
    pairs, counts = [], {}
    for fn in os.listdir(folder):
        src = os.path.join(folder, fn)
        if not os.path.isfile(src):
            continue
        ext = os.path.splitext(fn)[1].lower()
        cat = next((c for c, exts in _ORGANIZE_CATEGORIES.items() if ext in exts), "Other")
        pairs.append((src, os.path.join(folder, cat, fn)))
        counts[cat] = counts.get(cat, 0) + 1
    if not pairs:
        return {"success": False, "message": f"There are no loose files to organize in {folder}."}
    if is_confirmed:
        res = _move_batch(pairs)
        res["speak"] = True
        return res
    top_cats = sorted(counts.items(), key=lambda x: -x[1])[:2]
    cat_summary = " and ".join(f"{cat} ({n})" for cat, n in top_cats)
    other_count = sum(n for cat, n in counts.items() if cat not in dict(top_cats))
    if other_count > 0:
        cat_summary += f", plus {other_count} other files"
    msg = (f"I found {len(pairs)} loose files in {os.path.basename(folder)}, mainly {cat_summary}. "
           f"Should I organize them into category subfolders?")
    return _gated(msg, lambda: _move_batch(pairs))


def bulk_rename_files(parameter: str | None = None) -> dict:
    """bulk_rename_files|spec|new_base — renames to new_base-001.ext etc.,
    GATED with old-to-new enumeration."""
    print(f"[bulk_rename_files] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    if len(parts) < 2 or not parts[1].strip():
        return {"success": False, "message": "Rename needs files and a new base name — bulk rename files|*.jpg|vacation."}
    files, _, err = _resolve_targets(parts[0])
    if err:
        return {"success": False, "message": err}
    new_base = re.sub(r'[<>:"/\\|?*]', "", parts[1].strip())
    pairs = [(f, os.path.join(os.path.dirname(f), f"{new_base}-{i:03d}{os.path.splitext(f)[1]}"))
             for i, f in enumerate(files, 1)]
    preview = "; ".join(f"{os.path.basename(s)} to {os.path.basename(d)}" for s, d in pairs[:4])
    extra = f", and {len(pairs) - 4} more the same way" if len(pairs) > 4 else ""
    msg = f"I'll rename {len(pairs)} files: {preview}{extra}. Should I go ahead?"
    return _gated(msg, lambda: _move_batch(pairs))


def compress_files(parameter: str | None = None) -> dict:
    """compress_files|spec|folder-or-name? — files AND folders into a NEW zip;
    never touches the sources. Second field is smart: if it's an existing
    FOLDER it's the search root (the LLM often sends 'file|folder'), otherwise
    it's the archive name. Ungated by design."""
    print(f"[compress_files] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    spec = parts[0].strip() if parts and parts[0] else None
    root, name = None, None
    for extra in (p.strip() for p in parts[1:] if p.strip()):
        maybe_dir, ferr = _resolve_folder(extra)
        if not ferr and maybe_dir and os.path.isdir(maybe_dir) and not extra.lower().endswith(".zip"):
            root = maybe_dir          # "spec|folder" pattern
        else:
            name = extra              # "spec|archive-name" pattern
    targets, base, err = _resolve_targets(spec, root, include_dirs=True)
    if err:
        return {"success": False, "message": err}
    if not name:
        name = (os.path.splitext(os.path.basename(targets[0]))[0] if len(targets) == 1 else "archive")
    if not name.lower().endswith(".zip"):
        name += ".zip"
    archive = os.path.join(base, name)
    if os.path.exists(archive):
        n = 2
        while os.path.exists(os.path.join(base, f"{name[:-4]}-{n}.zip")):
            n += 1
        archive = os.path.join(base, f"{name[:-4]}-{n}.zip")
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for t in targets:
                if os.path.isdir(t):
                    for dirpath, _dirs, fnames in os.walk(t):
                        for fn in fnames:
                            full = os.path.join(dirpath, fn)
                            zf.write(full, os.path.relpath(full, os.path.dirname(t)))
                else:
                    zf.write(t, os.path.basename(t))
    except Exception as e:
        return {"success": False, "message": f"Couldn't create the archive: {e}"}
    return {"success": True, "message": f"Zipped {_count_kinds(targets)} into {os.path.basename(archive)}. The originals are untouched."}


def extract_files(parameter: str | None = None) -> dict:
    """extract_files|archive|dest? — extracts into a NEW folder named after
    the archive; refuses to spill into a non-empty folder. Archive resolves
    like other targets: full path, or name/partial name in the session folder."""
    print(f"[extract_files] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    spec = parts[0].strip() if parts and parts[0] else None
    if not spec:
        return {"success": False, "message": "Which archive? Give me the zip name or path."}
    hits, _, err = _resolve_targets(spec)
    if err:
        return {"success": False, "message": err}
    if len(hits) > 1:
        return {"success": False, "message": f"'{spec}' matched {len(hits)} files: {_enumerate_files(hits)}. Which one?"}
    fpath = hits[0]
    if not zipfile.is_zipfile(fpath):
        return {"success": False, "message": f"{os.path.basename(fpath)} isn't a zip file — I can only extract zips for now."}
    dest = (_normalize_path(parts[1]) if len(parts) > 1 and parts[1].strip()
            else os.path.join(os.path.dirname(fpath), os.path.splitext(os.path.basename(fpath))[0]))
    if os.path.isdir(dest) and os.listdir(dest):
        return {"success": False, "message": f"{dest} already exists and isn't empty — give me a different destination."}
    try:
        with zipfile.ZipFile(fpath) as zf:
            names = zf.namelist()
            # zip-slip guard: a malicious entry like ../../evil.dll would
            # escape dest via extractall. Resolve every member's real target
            # path and refuse the WHOLE extraction if any falls outside dest.
            dest_real = os.path.realpath(dest)
            for member in names:
                target = os.path.realpath(os.path.join(dest, member))
                if target != dest_real and not target.startswith(dest_real + os.sep):
                    return {"success": False,
                            "message": f"Refusing to extract {os.path.basename(fpath)} — entry '{member}' would land outside the destination folder. That's a malicious archive pattern."}
            zf.extractall(dest)
    except Exception as e:
        return {"success": False, "message": f"Couldn't extract it: {e}"}
    return {"success": True, "message": f"Extracted {len(names)} item{'s' if len(names) != 1 else ''} into {dest}."}


def summarize_file(parameter: str | None = None) -> dict:
    """summarize_file|path-or-name — extracts text (txt/code/pdf/docx) and
    asks the LLM for a 4-5 line spoken summary. Ungated, read-only."""
    print(f"[summarize_file] called with parameter={parameter!r}")
    spec = (parameter or "").split("|")[0].strip()
    if not spec:
        return {"success": False, "message": "Which file should I summarize?"}
    hits, _, err = _resolve_targets(spec)
    if err:
        return {"success": False, "message": err}
    if len(hits) > 1:
        return {"success": False, "message": f"'{spec}' matched {len(hits)} files: {_enumerate_files(hits)}. Which one?"}
    fpath = hits[0]
    name = os.path.basename(fpath)
    ext = os.path.splitext(fpath)[1].lower()

    text = None
    if ext in {".pdf", ".docx"}:
        # shared extraction path — same function read_file/file_to_doc use
        text, xerr = _extract_document_text(fpath)
        if xerr:
            return {"success": False, "message": xerr}
    else:
        # text/code route with the same binary guard as read_file
        if ext in {".doc", ".xls", ".xlsx", ".ppt", ".pptx", ".png", ".jpg",
                   ".jpeg", ".gif", ".webp", ".mp3", ".mp4", ".zip", ".exe",
                   ".msi", ".dll"}:
            return {"success": False, "message": f"I can't summarize {ext[1:]} files yet — text, code, PDF, and docx only."}
        try:
            with open(fpath, "rb") as f:
                raw = f.read(24000)
            if b"\x00" in raw:
                return {"success": False, "message": f"{name} is a binary file — I can't summarize it."}
            text = raw.decode("utf-8", errors="replace").strip()
        except Exception as e:
            return {"success": False, "message": f"Couldn't read it: {e}"}
    if not text:
        return {"success": False, "message": f"{name} is empty — nothing to summarize."}

    try:
        import claude_handler  # lazy: no cycle (claude_handler never imports executor)
        summary = claude_handler.summarize_text(text[:24000], name)
    except Exception as e:
        return {"success": False, "message": f"I read the file but the summary call failed: {e}"}
    return {"success": True, "speak": True, "message": f"Here's the gist of {name}: {summary}"}


def file_to_doc(parameter: str | None = None) -> dict:
    """file_to_doc|path-or-name|Doc Title|what to put in the doc|[short or detailed]
    Extracts text from a local file (pdf/docx/txt/code — same extraction path
    as summarize_file) and hands it to Gemini as SOURCE material for a new
    Google Doc. The extracted text stays inside this process — it never
    travels through the action-routing JSON (see gemini_content.py header),
    which is why this is one action and not a read_file→docs_control chain:
    {{step.result}} substitution only carries the spoken 600-char snippet."""
    print(f"[file_to_doc] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    if len(parts) < 3 or not parts[0].strip() or not parts[1].strip() or not parts[2].strip():
        return {"success": False,
                "message": "I need the file, a document title, and what to put in it — file to doc|file|Title|what to extract."}
    spec, title, instruction = parts[0].strip(), parts[1].strip(), parts[2].strip()
    length = parts[3].strip().lower() if len(parts) > 3 and parts[3].strip() else "short"

    hits, _, err = _resolve_targets(spec)
    if err:
        return {"success": False, "message": err}
    if len(hits) > 1:
        return {"success": False,
                "message": f"'{spec}' matched {len(hits)} files: {_enumerate_files(hits)}. Which one?"}
    fpath = hits[0]
    name = os.path.basename(fpath)
    ext = os.path.splitext(fpath)[1].lower()

    if ext in {".pdf", ".docx"}:
        text, xerr = _extract_document_text(fpath)
        if xerr:
            return {"success": False, "message": xerr}
    else:
        try:
            with open(fpath, "rb") as f:
                raw = f.read(24000)
            if b"\x00" in raw:
                return {"success": False, "message": f"{name} is a binary file — I can't read it as text."}
            text = raw.decode("utf-8", errors="replace").strip()
        except Exception as e:
            return {"success": False, "message": f"Couldn't read it: {e}"}
    if not text:
        return {"success": False, "message": f"{name} is empty — nothing to put in a doc."}

    import gemini_content  # lazy, same as docs_control
    gen = gemini_content.generate(
        f"{instruction}\n\nUse ONLY the following source text extracted from "
        f"{name}. Do not invent content that isn't in it.\n\n--- SOURCE ---\n"
        f"{text[:24000]}",
        "Write plain text suitable for a Google Doc. No markdown syntax, "
        "no # headers, no asterisks.",
        length)
    if not gen["success"]:
        return gen
    import google_mcp
    result = google_mcp.call("workspace", "create_google_doc",
                             {"name": title, "content": gen["text"]})
    if result.get("success"):
        import re
        has_id = bool(re.search(r"([-\w]{25,}|https?://docs\.google\.com/[^\s]+)", str(result)))
        if not has_id:
            return {"success": False, "message": f"Created {title} from {name}, but no file ID or link was returned."}
        result["message"] = f"Created {title} from {name}. {result.get('message', '')}".strip()
    return result


# ── Images & wallpaper ────────────────────────────────────────────────────────
# The search/pick/download pipeline lives in image_flow.py (OS-independent,
# headlessly testable, chain rules enforced by action_guard.py). executor
# only wires the platform hooks and re-exports the two actions.

image_flow.configure(navigate=_navigate, remember=_remember,
                     normalize_path=_normalize_path)

_IMG_EXTS = image_flow.IMG_EXTS
search_image = image_flow.search_image
download_image = image_flow.download_image


def set_wallpaper(parameter: str | None = None) -> dict:
    """set_wallpaper|local image path. Local files ONLY — no download logic."""
    print(f"[set_wallpaper] called with parameter={parameter!r}")
    fpath, err = _resolve_path(parameter)
    if err:
        return {"success": False, "message": err}
    if not os.path.isfile(fpath):
        return {"success": False, "message": f"That image doesn't exist: {fpath}"}
    if os.path.splitext(fpath)[1].lower() not in _IMG_EXTS:
        return {"success": False, "message": f"{os.path.basename(fpath)} isn't an image file."}
    import ctypes
    # SPI_SETDESKWALLPAPER=20, SPIF_UPDATEINIFILE|SPIF_SENDCHANGE=3
    ok = ctypes.windll.user32.SystemParametersInfoW(20, 0, os.path.abspath(fpath), 3)
    if not ok:
        return {"success": False,
                "message": f"Windows refused that wallpaper (error {ctypes.GetLastError()})."}
    return {"success": True,
            "message": f"Wallpaper set to {os.path.basename(fpath)}."}


# ── Clipboard operations ──────────────────────────────────────────────────────
# PRIMARY route: PowerShell Get-Clipboard / Set-Clipboard via subprocess, with
# content passed as BASE64 to sidestep quoting and console-codepage encoding
# issues entirely. tkinter is LAST RESORT only — on live Windows it lost the
# clipboard content when the Tk root was destroyed (no owner process persists
# the data) while still reporting success. write_clipboard VERIFIES by reading
# the clipboard back and comparing — success is never reported unchecked again.

import base64 as _b64


def _ps_read_clipboard() -> str | None:
    """Get-Clipboard via PowerShell, base64-encoded on the PS side so the
    content survives the console codepage untouched. None on failure."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string](Get-Clipboard -Raw)))"],
        capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        return None
    payload = result.stdout.strip()
    if not payload:
        return ""
    return _b64.b64decode(payload).decode("utf-8")


def read_clipboard(parameter: str | None = None) -> dict:
    """read_clipboard — reads current clipboard text for Akira to speak or
    use in chained actions. Ungated. (parameter accepted and ignored — every
    action is dispatched with one positional argument.)"""
    print(f"[read_clipboard] called")
    try:
        content = _ps_read_clipboard()
        if content is not None:
            text = content.rstrip("\r\n")
            wrapped = f"<untrusted_external_context>\n{text}\n</untrusted_external_context>" if text else ""
            return {"success": True, "speak": True, "raw_content": text,
                    "message": f"Your clipboard says: {wrapped}" if text else "Your clipboard is empty."}
    except Exception as e:
        print(f"[read_clipboard] powershell route failed: {e}")
    # LAST RESORT: tkinter (known-flaky on Windows — see header note)
    try:
        root = tk.Tk()
        root.withdraw()
        content = root.clipboard_get()
        root.destroy()
        wrapped = f"<untrusted_external_context>\n{content}\n</untrusted_external_context>" if content else ""
        return {"success": True, "speak": True, "raw_content": content,
                "message": f"Your clipboard says: {wrapped}" if content else "Your clipboard is empty."}
    except Exception as e:
        return {"success": False, "message": f"Couldn't read clipboard: {e}"}


def write_clipboard(parameter: str | None = None) -> dict:
    """write_clipboard|exact content — writes exact user-dictated content
    verbatim, no paraphrasing or reformatting per bible §6.4. Ungated, but
    VERIFIED: reads the clipboard back and only reports success on a match."""
    print(f"[write_clipboard] called with parameter={parameter!r}")
    if not parameter:
        return {"success": False, "message": "Tell me what to write to the clipboard."}
    if parameter.strip().lower().startswith("generate|"):
        brief = parameter.split("|", 1)[1].strip()
        return generate_to_clipboard(brief)
    wrote = False
    try:
        # base64 the content INTO the PowerShell command — no quoting, no
        # stdin codepage mangling, handles any characters including newlines
        payload = _b64.b64encode(parameter.encode("utf-8")).decode("ascii")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')))"],
            capture_output=True, text=True, timeout=5)
        wrote = result.returncode == 0
        if not wrote:
            print(f"[write_clipboard] powershell route failed: {result.stderr.strip()[:120]}")
    except Exception as e:
        print(f"[write_clipboard] powershell route failed: {e}")
    if not wrote:
        # LAST RESORT: tkinter — kept alive briefly so the content propagates
        try:
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(parameter)
            root.update()
            time.sleep(0.2)  # give the clipboard owner handoff a moment
            root.destroy()
            wrote = True
        except Exception as e:
            return {"success": False, "message": f"Couldn't write clipboard: {e}"}
    # VERIFY — never report unchecked success
    try:
        readback = _ps_read_clipboard()
        if readback is not None and readback.rstrip("\r\n") == parameter.rstrip("\r\n"):
            return {"success": True, "message": f"Copied to clipboard and verified ({len(parameter)} chars)."}
        print(f"[write_clipboard] VERIFY FAILED: readback={readback!r:.120}")
        return {"success": False, "message": "I wrote to the clipboard but the read-back doesn't match — the copy didn't stick."}
    except Exception as e:
        # write appeared to succeed but verification wasn't possible — say so
        return {"success": True, "message": f"Copied to clipboard ({len(parameter)} chars), but I couldn't verify it: {e}"}


def generate_to_clipboard(parameter: str | None = None) -> dict:
    """generate_to_clipboard|brief — generates content from a brief/prompt using
    model_pool (with automatic failover across Groq/Cerebras/etc.), then writes
    the produced text to the clipboard.

    BUG FIX (2026-09): the Fast Pre-Router previously treated "write an essay on
    llms in notepad" as literal dictation and copied the instruction text itself
    to the clipboard. This action is the fix — it invokes actual AI content
    generation and writes the RESULT, not the instruction.

    Routed through model_pool.call_model() so generation doesn't go dark when
    one provider's free quota runs out — the pool automatically fails over to
    the next available endpoint.
    """
    print(f"[generate_to_clipboard] called with brief={parameter!r}")
    if not parameter:
        return {"success": False, "message": "Tell me what to write — for example, 'write an essay on LLMs'."}

    _CONTENT_SYSTEM = (
        "You are a professional content writer. Output ONLY the requested final text. "
        "Do NOT include thinking tags, <think> blocks, preambles, greetings, or conversational commentary."
    )
    _is_concise = any(k in parameter.lower() for k in ("summary", "sentence", "bullet", "short", "quick", "brief", "note", "two-sentence"))
    _max_tokens = 160 if _is_concise else 512
    _word_limit = 60 if _is_concise else 250

    prompt = (
        f"Write the following content concisely in roughly {_word_limit} words or fewer. "
        f"Output ONLY the final content without thinking tags or preambles:\n\n"
        f"{parameter}"
    )

    try:
        import model_pool
        pool = model_pool.get_pool()
        result = pool.call_model(
            messages=[{"role": "user", "content": prompt}],
            system=_CONTENT_SYSTEM,
            json_mode=False,       # prose output, not JSON
            timeout=15.0,
            max_tokens=_max_tokens,
        )
        text = (result.text or "").strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        provider_info = f"{result.provider}/{result.model}"
    except Exception as e:
        print(f"[generate_to_clipboard] model_pool call failed: {e!r}")
        # Fallback: try gemini_content.generate() directly (single-provider)
        try:
            import gemini_content
            gen = gemini_content.generate(
                brief=parameter,
                format_instructions="Write clean, well-structured prose with appropriate paragraphs. Do not output think tags.",
                length="short",
            )
            if not gen.get("success"):
                return {"success": False, "message": f"I couldn't generate that content: {gen.get('message', 'all providers exhausted')}"}
            text = gen["text"]
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            provider_info = "gemini_content (fallback)"
        except Exception as e2:
            return {"success": False, "message": f"Content generation failed — all providers exhausted: {e}; fallback: {e2}"}

    # SAFETY: never write empty or suspiciously short content to the clipboard
    # and report success — that violates the "never report false success" rule.
    if not text or len(text) < 20:
        print(f"[generate_to_clipboard] generation returned empty/trivial text ({len(text) if text else 0} chars)")
        return {
            "success": False,
            "message": "Content generation returned empty or trivially short text. Please try again.",
        }

    print(f"[generate_to_clipboard] generated {len(text)} chars via {provider_info}, writing to clipboard")

    # Reuse write_clipboard to actually set the clipboard and verify
    cb_result = write_clipboard(text)
    if cb_result.get("success"):
        return {
            "success": True,
            "message": f"Generated and copied to clipboard ({len(text)} chars). You can paste it now.",
        }
    return {
        "success": False,
        "message": f"I wrote the content but clipboard copy failed: {cb_result.get('message', 'unknown error')}",
    }


# ── Spotify ────────────────���───────────────────────────────────��──────────────
# HYBRID control, priority order (never ask the user which):
#   1. Desktop app installed -> Web API against it (launch + poll if not running)
#   2. No app -> web player via Web API (open open.spotify.com, poll for device)
#   3. No API device establishable -> DOM control of open.spotify.com
#      (transport only; volume/shuffle/repeat/queue fail loud in DOM mode)
# OAuth: spotipy (SpotifyOAuth = auth-code flow + token cache + refresh built
# in). Raw-requests fallback deliberately NOT built — it duplicates ~100 lines
# of security-sensitive redirect/refresh code that can't be verified here.

# playlist-read-private + user-library-read added for open_playlist /
# open_library. Scope change means the cached token lacks them — delete
# ~/.akira_spotify_cache once and re-auth in the browser popup.
_SPOTIFY_SCOPES = ("user-read-playback-state user-modify-playback-state "
                   "user-read-currently-playing playlist-read-private "
                   "user-library-read")
_spotify_client_cache = None
_spotify_premute_volume = None  # volume % before mute, restored by unmute


def _spotify_client():
    """Returns (spotipy_client_or_None, error_message_or_None). Cached."""
    global _spotify_client_cache
    if _spotify_client_cache is not None:
        return _spotify_client_cache, None
    cid = os.environ.get("SPOTIFY_CLIENT_ID")
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not cid or not secret:
        return None, ("Spotify API needs SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET "
                      "in the .env — create an app at developer.spotify.com/dashboard.")
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        return None, "I need the spotipy package — run pip install spotipy."
    try:
        auth = SpotifyOAuth(
            client_id=cid, client_secret=secret,
            redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            scope=_SPOTIFY_SCOPES,
            cache_path=os.path.join(os.path.expanduser("~"), ".akira_spotify_cache"),
            open_browser=True)
        client = spotipy.Spotify(auth_manager=auth, requests_timeout=10)
        _spotify_client_cache = client
        return client, None
    except Exception as e:
        return None, f"Spotify auth failed: {e}"


def _spotify_app_running() -> bool:
    try:
        return any((p.info["name"] or "").lower() == "spotify.exe"
                   for p in psutil.process_iter(["name"]))
    except Exception:
        return False


def _spotify_pick(devices: list, prefer_local: bool = False) -> dict | None:
    """Default priority: active > this computer > web player > anything.
    prefer_local=True (used when STARTING playback): THIS computer first —
    otherwise 'play X' lands on whatever device was last active (a TV,
    a phone) instead of the machine the user is talking to."""
    def _is_local(d):
        return d.get("type") == "Computer" and "web player" not in (d.get("name") or "").lower()
    def _is_web(d):
        return "web player" in (d.get("name") or "").lower()
    # prefer_local: BOTH local options (app, then web player) outrank a
    # remote active device like a TV — that's the whole point of the flag
    order = ([_is_local, _is_web, lambda d: d.get("is_active")] if prefer_local
             else [lambda d: d.get("is_active"), _is_local, _is_web])
    for test in order:
        for d in devices:
            if test(d):
                return d
    return devices[0] if devices else None


def _spotify_is_local(d: dict) -> bool:
    return bool(d) and d.get("type") == "Computer"


def _spotify_device(sp, prefer_local: bool = False) -> tuple[dict | None, str, str | None]:
    """Establish a playback device. Returns (device, path_used, error).
    prefer_local: NEVER silently settle for a remote device (TV/phone) —
    bring up THIS machine's app or web player first; only fall back to the
    remote with path='remote fallback' so the caller can disclose it."""
    try:
        devices = sp.devices().get("devices", [])
    except Exception as e:
        return None, "none", f"Couldn't query Spotify devices: {e}"
    d = _spotify_pick(devices, prefer_local)
    if prefer_local and d and not _spotify_is_local(d):
        print(f"[spotify_control] only remote device online ({d.get('name')}) — bringing up local")
        local, lerr = _spotify_bring_up_local(sp)
        if local:
            return local, "local device (launched)", None
        print(f"[spotify_control] local bring-up failed ({lerr}) — remote fallback")
        return d, "remote fallback", None
    if d:
        path = ("desktop app device" if d.get("type") == "Computer"
                and "web player" not in (d.get("name") or "").lower() else "web player device")
        return d, path, None
    # no device at all — bring up a local one
    local, lerr = _spotify_bring_up_local(sp)
    if local:
        return local, "local device (launched)", None
    return None, "none", lerr or ("I couldn't find an active Spotify device — is Spotify "
                                  "installed or open and logged in anywhere?")


def _spotify_bring_up_local(sp) -> tuple[dict | None, str | None]:
    """Launch THIS machine's Spotify (desktop app > web player) and poll until
    it registers as a Connect device. Returns (local_device, error)."""
    exe = _find_exe("spotify")
    if exe:
        if not _spotify_app_running():
            print("[spotify_control] launching desktop app")
            try:
                subprocess.Popen(exe)
            except Exception as e:
                print(f"[spotify_control] app launch failed: {e}")
        wait = 12
    else:
        print("[spotify_control] app not installed — opening web player")
        try:
            get_browser()
            _navigate("https://open.spotify.com")
        except Exception as e:
            return None, f"Couldn't open the Spotify web player: {e}"
        wait = 14
    for _ in range(wait):
        time.sleep(1)
        try:
            devs = sp.devices().get("devices", [])
        except Exception:
            devs = []
        for d in devs:
            if _spotify_is_local(d):
                print(f"[spotify_control] local device registered: {d.get('name')}")
                return d, None
    return None, "Spotify opened here but never showed up as a playback device — is it logged in?"


def _spotify_dom(action: str) -> dict:
    """LAST-RESORT DOM control of open.spotify.com — transport only."""
    print(f"[spotify_control] using DOM fallback for {action}")
    testids = {"pause": "control-button-playpause", "resume": "control-button-playpause",
               "next_track": "control-button-skip-forward",
               "previous_track": "control-button-skip-back"}
    try:
        browser = get_browser()
        if "open.spotify.com" not in (browser.current_url or ""):
            _navigate("https://open.spotify.com")
            time.sleep(4)
        if action == "now_playing":
            el = browser.find_elements(By.CSS_SELECTOR, '[data-testid="now-playing-widget"]')
            if el and el[0].text.strip():
                return {"success": True, "speak": True,
                        "message": "Now playing: " + el[0].text.replace("\n", " by ", 1).replace("\n", ", ")}
            return {"success": False, "message": "Nothing seems to be playing in the web player."}
        tid = testids.get(action)
        if not tid:
            return {"success": False, "message": f"I can't do {action.replace('_', ' ')} without API access — set up SPOTIFY_CLIENT_ID and SECRET and I'll control Spotify properly."}
        els = [e for e in browser.find_elements(By.CSS_SELECTOR, f'[data-testid="{tid}"]') if e.is_displayed()]
        if not els:
            return {"success": False, "message": "I couldn't find the player controls — are you logged in to the Spotify web player?"}
        els[0].click()
        return {"success": True, "message": f"Done — {action.replace('_', ' ')}."}
    except Exception as e:
        return {"success": False, "message": f"Spotify web player control failed: {e}"}


def _focus_browser_window() -> None:
    """Bring the automation browser's window to the foreground and make sure
    the Akira tab is the visible one — 'show me X' means SHOW, not background."""
    try:
        browser = get_browser(_last_browser_name)
        browser.switch_to.window(browser._akira_tab)
        browser.execute_cdp_cmd("Page.bringToFront", {})
    except Exception as e:
        print(f"[spotify_control] couldn't focus browser window: {e}")


def _spotify_show_uri(app_uri: str, web_path: str, label: str) -> dict:
    """SHOW a Spotify UI surface. Desktop app running -> spotify: deep link
    (opens INSIDE the app — library, playlists, liked songs are all
    deep-linkable even though the app has no automation API). Otherwise ->
    the same page on the web player in the controlled browser."""
    if _spotify_app_running():
        print(f"[spotify_control] deep-linking app UI: {app_uri}")
        try:
            os.startfile(app_uri)  # Windows protocol handler -> Spotify app
            time.sleep(0.8)
            for w in gw.getWindowsWithTitle("Spotify"):
                try:
                    w.activate()
                    break
                except Exception:
                    pass
            return {"success": True, "message": f"Showing {label} in Spotify."}
        except Exception as e:
            print(f"[spotify_control] deep link failed ({e}) — web fallback")
    try:
        get_browser()
        _navigate(f"https://open.spotify.com/{web_path}")
        _focus_browser_window()
        return {"success": True, "message": f"Showing {label} in the Spotify web player."}
    except Exception as e:
        return {"success": False, "message": f"Couldn't open {label}: {e}"}


_SPOTIFY_ALIASES = {
    "next": "next_track", "skip": "next_track", "previous": "previous_track",
    "back": "previous_track", "volume": "set_volume", "queue": "add_to_queue",
    "play_by_mood": "play_mood", "mood": "play_mood",
    "playlist": "open_playlist", "library": "open_library",
    "view_saved": "open_library", "saved": "open_library",
    "liked": "open_library", "liked_songs": "open_library",
    "current_volume": "get_volume", "get_current_volume": "get_volume",
    "forward": "skip_forward", "rewind": "skip_back", "backward": "skip_back",
    "skip_backward": "skip_back", "seek_to": "seek", "whats_playing": "now_playing",
    "lyrics": "show_lyrics", "open_lyrics": "show_lyrics",
    "view_library": "show_library", "open_my_library": "show_library",
    "show_liked_songs": "show_liked", "view_liked": "show_liked",
    "view_playlist": "show_playlist", "open_playlist_ui": "show_playlist",
}


def spotify_control(action: str, parameter: str | None = None) -> dict:
    """Spotify hybrid control. Ungated — playback actions are all reversible."""
    action = (action or "").strip().lower().replace(" ", "_")
    action = _SPOTIFY_ALIASES.get(action, action)
    print(f"[spotify_control] action={action!r} parameter={parameter!r}")
    sp, err = _spotify_client()
    if sp is None:
        # No API possible — DOM fallback for transport, loud fail otherwise.
        # show_lyrics/show_library are pure navigation, no API needed.
        print(f"[spotify_control] no API client ({err}) — DOM fallback")
        if action in ("pause", "resume", "next_track", "previous_track", "now_playing"):
            return _spotify_dom(action)
        if action == "show_lyrics":
            pass  # handled below, needs no client
        elif action in ("show_library", "show_liked"):
            pass  # deep link / web nav, needs no client
        else:
            return {"success": False, "message": err}

    if action == "show_lyrics":
        # No lyrics DATA via the API (licensed Musixmatch), but we CAN show
        # the lyrics UI: the web player's /lyrics page mirrors the currently
        # playing track across ALL devices via Spotify Connect.
        try:
            get_browser()
            _navigate("https://open.spotify.com/lyrics")
            _focus_browser_window()
            return {"success": True, "message": "Lyrics are up on screen."}
        except Exception as e:
            return {"success": False, "message": f"Couldn't open the lyrics view: {e}"}

    if action in ("show_library", "show_liked"):
        uri = "spotify:collection:tracks" if action == "show_liked" else "spotify:collection"
        web = "collection/tracks" if action == "show_liked" else "collection"
        return _spotify_show_uri(uri, web,
                                 "Liked Songs" if action == "show_liked" else "your library")

    if action == "show_playlist":
        if not parameter:
            return {"success": False, "message": "Which playlist?"}
        want = parameter.strip().lower()
        try:
            pls, offset = [], 0
            while offset < 200:
                batch = sp.current_user_playlists(limit=50, offset=offset).get("items", [])
                pls.extend(batch)
                if len(batch) < 50:
                    break
                offset += 50
            hits = [pl for pl in pls if pl and want in (pl.get("name") or "").lower()]
        except Exception as e:
            return {"success": False, "message": f"Couldn't look up your playlists: {e}"}
        if not hits:
            names = ", ".join((pl.get("name") or "?") for pl in pls[:8]) or "none found"
            return {"success": False, "message": f"No playlist matching '{parameter}'. You have: {names}."}
        pl = hits[0]
        pid = pl["uri"].split(":")[-1]
        return _spotify_show_uri(pl["uri"], f"playlist/{pid}", pl["name"])

    if action == "search":
        if not parameter:
            return {"success": False, "message": "Search for what?"}
        try:
            res = sp.search(parameter, limit=5, type="track,artist")
            tracks = [f"{t['name']} by {t['artists'][0]['name']}"
                      for t in res.get("tracks", {}).get("items", [])[:4]]
            artists = [a["name"] for a in res.get("artists", {}).get("items", [])[:2]]
            if not tracks and not artists:
                return {"success": False, "message": f"No Spotify results for '{parameter}'."}
            bits = []
            if tracks:
                bits.append("Tracks: " + "; ".join(tracks))
            if artists:
                bits.append("Artists: " + ", ".join(artists))
            return {"success": True, "speak": True, "message": ". ".join(bits) + "."}
        except Exception as e:
            return {"success": False, "message": f"Spotify search failed: {e}"}

    if action == "devices":
        try:
            devs = sp.devices().get("devices", [])
        except Exception as e:
            return {"success": False, "message": f"Couldn't list Spotify devices: {e}"}
        if not devs:
            return {"success": True, "speak": True, "message": "No Spotify devices are online right now."}
        named = ", ".join(f"{d['name']}{' (active)' if d.get('is_active') else ''}" for d in devs)
        return {"success": True, "speak": True, "message": f"Spotify devices: {named}."}

    if action == "transfer":
        try:
            devs = sp.devices().get("devices", [])
        except Exception as e:
            return {"success": False, "message": f"Couldn't list Spotify devices: {e}"}
        want = (parameter or "").strip().lower()
        target = None
        if want in ("laptop", "computer", "pc", "this", "here", "desktop"):
            target = next((d for d in devs if d.get("type") == "Computer"
                           and "web player" not in (d.get("name") or "").lower()), None) \
                     or next((d for d in devs if "web player" in (d.get("name") or "").lower()), None)
        elif want:
            hits = [d for d in devs if want in (d.get("name") or "").lower()]
            if len(hits) > 1:
                return {"success": False, "message": f"'{parameter}' matches several devices: {', '.join(d['name'] for d in hits)}. Which one?"}
            target = hits[0] if hits else None
        if not target:
            names = ", ".join(d["name"] for d in devs) or "none online"
            return {"success": False, "message": f"I couldn't find a device matching '{parameter}'. Available: {names}."}
        try:
            sp.transfer_playback(target["id"], force_play=True)
            return {"success": True, "message": f"Moved playback to {target['name']}."}
        except Exception as e:
            return {"success": False, "message": f"Couldn't move playback: {e}"}

    # play STARTS new playback -> prefer THIS computer, not whatever device
    # happened to be active (that's how it ended up on the FireTV Stick)
    device, path, derr = _spotify_device(sp, prefer_local=(action == "play"))
    if derr:
        return {"success": False, "message": derr}
    print(f"[spotify_control] using {path}: {device.get('name')}")
    dev_id = device["id"]
    try:
        if action == "play":
            if not parameter:
                return {"success": False, "message": "Play what? Give me a track or artist."}
            # Search limit=5 avoids Spotify's limit=1 ranker anomaly and enables title/artist matching
            res = sp.search(parameter, limit=5, type="track")
            items = res.get("tracks", {}).get("items", [])
            if not items:
                return {"success": False, "message": f"Couldn't find '{parameter}' on Spotify."}
            want = (parameter or "").strip().lower()
            best_track = next((t for t in items if want in t["name"].lower() or any(want in a["name"].lower() for a in t["artists"])), items[0])
            t = best_track
            sp.start_playback(device_id=dev_id, uris=[t["uri"]])
            msg = f"Playing {t['name']} by {t['artists'][0]['name']} on {device.get('name')}."
            if path == "remote fallback":
                # never silently play on a TV/phone — disclose and offer to move
                msg = (f"Heads up — I couldn't get Spotify running on this computer, "
                       f"so it's playing on {device.get('name')}. Say 'play it here' to move it.")
            return {"success": True, "speak": path == "remote fallback", "message": msg}
        if action == "pause":
            sp.pause_playback(device_id=dev_id)
            return {"success": True, "message": "Paused."}
        if action == "resume":
            sp.start_playback(device_id=dev_id)
            return {"success": True, "message": "Resumed."}
        if action == "next_track":
            sp.next_track(device_id=dev_id)
            return {"success": True, "message": "Skipped."}
        if action == "previous_track":
            sp.previous_track(device_id=dev_id)
            return {"success": True, "message": "Back a track."}
        if action == "set_volume":
            try:
                vol = max(0, min(100, int(re.sub(r"\D", "", parameter or ""))))
            except ValueError:
                return {"success": False, "message": "Volume needs a number, 0 to 100."}
            sp.volume(vol, device_id=dev_id)
            return {"success": True, "message": f"Spotify volume at {vol}."}
        if action == "now_playing":
            cur = sp.current_playback()
            if not cur or not cur.get("item"):
                return {"success": True, "speak": True, "message": "Nothing is playing right now."}
            t = cur["item"]
            state = "playing" if cur.get("is_playing") else "paused"
            return {"success": True, "speak": True,
                    "message": f"{t['name']} by {t['artists'][0]['name']}, {state} on {cur.get('device', {}).get('name', 'unknown device')}."}
        if action == "add_to_queue":
            if not parameter:
                return {"success": False, "message": "Queue what?"}
            res = sp.search(parameter, limit=1, type="track")
            items = res.get("tracks", {}).get("items", [])
            if not items:
                return {"success": False, "message": f"Couldn't find '{parameter}' on Spotify."}
            t = items[0]
            sp.add_to_queue(t["uri"], device_id=dev_id)
            return {"success": True, "message": f"Queued {t['name']} by {t['artists'][0]['name']}."}
        if action == "shuffle":
            state = (parameter or "").strip().lower() in ("on", "true", "yes", "1")
            sp.shuffle(state, device_id=dev_id)
            return {"success": True, "message": f"Shuffle {'on' if state else 'off'}."}
        if action == "repeat":
            mode = (parameter or "off").strip().lower()
            if mode not in ("track", "context", "off"):
                mode = "context" if mode in ("on", "all", "playlist") else "off"
            sp.repeat(mode, device_id=dev_id)
            return {"success": True, "message": f"Repeat set to {mode}."}

        if action in ("skip_forward", "skip_back", "seek"):
            cur = sp.current_playback()
            if not cur or not cur.get("item"):
                return {"success": False, "message": "Nothing is playing to seek in."}
            pos, dur = cur.get("progress_ms", 0), cur["item"].get("duration_ms", 0)
            p = (parameter or "").strip().lower()
            if action == "seek":
                # "1:30" / "90" / "1 minute 30" -> ms
                m = re.match(r"^(\d+):(\d{1,2})$", p)
                if m:
                    target = (int(m.group(1)) * 60 + int(m.group(2))) * 1000
                else:
                    mins = re.search(r"(\d+)\s*min", p)
                    secs = re.search(r"(\d+)\s*sec", p)
                    if mins or secs:
                        target = ((int(mins.group(1)) if mins else 0) * 60
                                  + (int(secs.group(1)) if secs else 0)) * 1000
                    elif p.isdigit():
                        target = int(p) * 1000
                    else:
                        return {"success": False, "message": "Seek to where? Give me a time like 1:30."}
            else:
                delta = int(re.sub(r"\D", "", p) or "10") * 1000
                target = pos + delta if action == "skip_forward" else pos - delta
            target = max(0, min(target, max(dur - 1000, 0)))
            sp.seek_track(target, device_id=dev_id)
            return {"success": True, "message": f"Jumped to {target // 60000}:{(target // 1000) % 60:02d}."}

        if action == "get_volume":
            pct = device.get("volume_percent")
            if pct is None:
                cur = sp.current_playback()
                pct = (cur or {}).get("device", {}).get("volume_percent")
            if pct is None:
                return {"success": False, "message": "Couldn't read the Spotify volume."}
            return {"success": True, "speak": True, "message": f"Spotify volume is at {pct} percent."}

        if action in ("mute", "unmute"):
            global _spotify_premute_volume
            if action == "mute":
                pct = device.get("volume_percent")
                if pct:
                    _spotify_premute_volume = pct
                sp.volume(0, device_id=dev_id)
                return {"success": True, "message": "Spotify muted."}
            restore = _spotify_premute_volume or 50
            sp.volume(restore, device_id=dev_id)
            return {"success": True, "message": f"Spotify back at {restore}."}

        if action == "open_playlist":
            if not parameter:
                return {"success": False, "message": "Which playlist?"}
            want = parameter.strip().lower()
            pls, offset = [], 0
            while offset < 200:  # user playlists, paged
                batch = sp.current_user_playlists(limit=50, offset=offset).get("items", [])
                pls.extend(batch)
                if len(batch) < 50:
                    break
                offset += 50
            hits = [pl for pl in pls if pl and want in (pl.get("name") or "").lower()]
            if not hits:  # fall back to public playlist search
                res = sp.search(parameter, limit=1, type="playlist")
                hits = [pl for pl in res.get("playlists", {}).get("items", []) if pl]
            if not hits:
                return {"success": False, "message": f"I couldn't find a playlist called '{parameter}'."}
            pl = hits[0]
            sp.start_playback(device_id=dev_id, context_uri=pl["uri"])
            return {"success": True, "message": f"Playing your playlist {pl['name']}."}

        if action in ("open_library", "liked_songs"):
            # voice context has no UI to "browse" — most useful default is
            # playing Liked Songs (saved tracks have no context_uri, so queue
            # the first batch as a uri list)
            saved = sp.current_user_saved_tracks(limit=50).get("items", [])
            uris = [it["track"]["uri"] for it in saved if it.get("track")]
            if not uris:
                return {"success": False, "message": "Your Liked Songs list looks empty."}
            sp.start_playback(device_id=dev_id, uris=uris)
            return {"success": True, "message": f"Playing your Liked Songs — {len(uris)} tracks queued."}

        if action == "play_mood":
            # No mood API — smart query construction: mood words -> genre/
            # keyword search terms, play the top playlist match for variety
            if not parameter:
                return {"success": False, "message": "What kind of mood?"}
            moods = {"calm": "calm acoustic chill", "relax": "chill lofi relax",
                     "sleep": "sleep ambient calm", "sad": "sad acoustic mellow",
                     "happy": "happy feel good hits", "upbeat": "upbeat energy pop",
                     "energetic": "high energy workout", "workout": "workout pump",
                     "party": "party dance hits", "focus": "deep focus instrumental",
                     "study": "study beats instrumental", "romantic": "romantic love songs",
                     "angry": "rage metal intense", "nostalgic": "throwback classics"}
            p = parameter.strip().lower()
            query = next((q for k, q in moods.items() if k in p), f"{p} mix")
            res = sp.search(query, limit=1, type="playlist")
            items = [pl for pl in res.get("playlists", {}).get("items", []) if pl]
            if not items:
                return {"success": False, "message": f"Couldn't find anything for that mood."}
            sp.start_playback(device_id=dev_id, context_uri=items[0]["uri"])
            return {"success": True, "message": f"Playing {items[0]['name']} for you."}

        return {"success": False, "message": f"Unknown spotify action: {action}"}
    except Exception as e:
        msg = str(e)
        if "PREMIUM_REQUIRED" in msg or "403" in msg:
            return {"success": False, "message": "Spotify says that needs a Premium account — playback control over the API is Premium-only."}
        if "NO_ACTIVE_DEVICE" in msg or "404" in msg:
            return {"success": False, "message": "Spotify lost the active device — start playing something once on any device and I'll take it from there."}
        return {"success": False, "message": f"Spotify {action.replace('_', ' ')} failed: {e}"}


def vscode_control(action: str, parameter: str | None = None) -> dict:
    """
    VS Code control — used when the user explicitly says 'in VS Code'.
    File actions delegate to the standalone functions (no duplicated logic);
    write file / edit file stay gated regardless of entry point.
    OUT OF SCOPE: running code, extensions, editor keystrokes.
    """
    print(f"[vscode_control] called with action={action!r}, parameter={parameter!r}")

    action = (action or "").strip().lower().replace("_", " ")
    parts = (parameter or "").split("|")

    if action == "open folder":
        cli = _vsc_code_cli()
        if not cli:
            return {"success": False, "message": "VS Code's 'code' command isn't on your PATH. In VS Code, run 'Shell Command: Install code command' or reinstall with the PATH option checked."}
        folder, err = _resolve_path(parts[0] if parts[0] else None, want_dir=True)
        if err:
            return {"success": False, "message": err}
        if not os.path.isdir(folder):
            return {"success": False, "message": f"That folder doesn't exist: {folder}"}
        try:
            subprocess.Popen([cli, folder], shell=False)
        except Exception as e:
            return {"success": False, "message": f"Couldn't launch VS Code: {e}"}
        global _vsc_last_folder
        _vsc_last_folder = folder
        return {"success": True, "message": f"Opened {os.path.basename(folder)} in VS Code."}

    if action == "open file":
        cli = _vsc_code_cli()
        if not cli:
            return {"success": False, "message": "VS Code's 'code' command isn't on your PATH. In VS Code, run 'Shell Command: Install code command' or reinstall with the PATH option checked."}
        fpath, err = _resolve_path(parts[0] if parts[0] else None)
        if err:
            return {"success": False, "message": err}
        if not os.path.isfile(fpath):
            return {"success": False, "message": f"That file doesn't exist: {fpath}"}
        try:
            subprocess.Popen([cli, fpath], shell=False)
        except Exception as e:
            return {"success": False, "message": f"Couldn't launch VS Code: {e}"}
        _remember(fpath)
        return {"success": True, "message": f"Opened {os.path.basename(fpath)} in VS Code."}

    # File actions: delegate to the SAME standalone functions, then open the
    # result in VS Code where it makes sense (create only — best-effort).
    if action == "create file":
        result = create_file(parameter)
        if result.get("success"):
            cli = _vsc_code_cli()
            if cli and _vsc_last_file:
                try:
                    subprocess.Popen([cli, _vsc_last_file], shell=False)
                    result["message"] = result["message"].rstrip(".") + " and opened it in VS Code."
                except Exception:
                    pass  # file was created — opening is best-effort
        return result

    if action == "read file":
        return read_file(parameter)

    if action in ("read more", "read_more"):
        return read_more(parameter)

    if action in ("stop reading", "stop_reading"):
        return stop_reading(parameter)

    if action == "write file":
        return write_file(parameter)   # gated upstream under both entry points

    if action == "edit file":
        return edit_file(parameter)    # gated upstream under both entry points

    if action == "search file":
        return search_file(parameter)

    if action in ("run", "run code", "execute", "install extension", "keystroke", "type"):
        return {"success": False, "message": "Running code, extensions, and typing into the editor are out of my scope for now — file operations only."}

    return {"success": False, "message": f"Unknown vscode_control action: {action}"}


# ── System actions ────────────────────────────���───────────────────────────────

def _find_exe(name: str) -> str | None:
    """Try to find an executable using glob for version-agnostic paths."""
    if name in MANUAL_MAP:
        path = MANUAL_MAP[name]
        if os.path.exists(path):
            return path
        # try glob for versioned paths
        parent = os.path.dirname(path)
        pattern = os.path.join(os.path.dirname(parent), "**", os.path.basename(path))
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return matches[0]
    return shutil.which(name)


def _activate_launched_window(name: str) -> None:
    """Best-effort bring-to-foreground for a freshly launched application.
    Fast-polls synchronously up to 0.8s for light apps, then continues polling
    in a background thread up to 6.0s for slow Electron apps (Spotify, Discord, VSCode)
    so open_application never blocks or prints false failures.
    """
    title_hint = WINDOW_TITLE_MAP.get(name.lower(), name.title())

    def _try_focus() -> bool:
        try:
            wins = gw.getWindowsWithTitle(title_hint)
            if not wins:
                for w in gw.getAllWindows():
                    if name.lower() in (w.title or "").lower():
                        wins = [w]
                        break
            if wins:
                hwnd = wins[0]._hWnd
                win32gui.ShowWindow(hwnd, 5)          # SW_SHOW
                win32gui.SetForegroundWindow(hwnd)
                print(f"[open_application] activated window hwnd={hwnd} title={wins[0].title!r}")
                return True
        except Exception as e:
            pass
        return False

    # 1. Fast synchronous attempts (0.8s) for snappy local apps
    for _ in range(4):
        time.sleep(0.2)
        if _try_focus():
            return

    # 2. Asynchronous background poll up to 6s for slow cold-starts
    def _bg_poll():
        for _ in range(12):
            time.sleep(0.5)
            if _try_focus():
                return
        print(f"[open_application] background window check ended for {name!r}")

    threading.Thread(target=_bg_poll, daemon=True).start()


def _open_single_app(name: str) -> str:
    param = APP_ALIASES.get(name.lower().strip(), name.lower().strip())

    if param in URI_MAP:
        try:
            os.startfile(URI_MAP[param])
            _activate_launched_window(name)
            return f"Opening {name}."
        except Exception:
            return f"Couldn't open {name}."

    if param in WEB_MAP:
        # MUST go through the Selenium-controlled browser, NOT
        # webbrowser.open() — that launched the system default browser as a
        # separate process, so youtube_control etc. (which check
        # get_browser().current_url) never saw the page ("This isn't a
        # YouTube tab" every time, plus the mystery blank tab).
        print(f"[open_application] '{param}' is web-only — routing to open_site_tab")
        try:
            return open_site_tab(param)
        except Exception as e:
            print(f"[open_application] controlled browser failed ({e}) — system browser fallback")
            webbrowser.open(WEB_MAP[param])
            return f"Opening {name} in your default browser — I won't be able to control that tab."

    exe = _find_exe(param)
    if exe:
        try:
            subprocess.Popen(exe)
            _activate_launched_window(name)
            return f"Opening {name}."
        except Exception as e:
            return f"Couldn't open {name}: {e}"

    # Try Windows App Paths or direct shell association
    try:
        os.startfile(param)
        _activate_launched_window(name)
        return f"Opening {name}."
    except Exception:
        pass

    try:
        os.startfile(name)
        _activate_launched_window(name)
        return f"Opening {name}."
    except Exception:
        pass

    return f"Couldn't find {name}."


def safe_open_app(name: str, is_indirect: bool = False) -> str:
    """Open an application with safety validation for indirect/untrusted inputs.

    Direct voice commands execute without overhead; indirect sources
    (clipboard, browser titles, notes) are checked via POST /v1/validate-command.
    """
    if is_indirect:
        import gateway_client
        ok, msg = gateway_client.validate_indirect_command(name)
        if not ok:
            print(f"[safe_open_app] Blocked indirect app name: {name} ({msg})")
            return "Invalid application name — blocked for safety."
    return _open_single_app(name)


def open_application(parameter: str, is_indirect: bool = False) -> str:
    apps = [p.strip() for p in parameter.split(",") if p.strip()]
    if not apps:
        return "No application specified."
    results = []
    for app in apps:
        res = safe_open_app(app, is_indirect=is_indirect)
        results.append(res)
    failures = [r for r in results if r.startswith(("Couldn't", "Invalid", "Unknown"))]
    if failures:
        return " ".join(results)
    if len(results) == 1:
        return results[0]
    return f"Opening {', '.join(apps)}."


def _close_single_app(name: str) -> str:
    param = name.lower().strip()
    import security_guard
    if security_guard.is_system_critical_process(param):
        return f"Closing system-critical process '{name}' is blocked by security policy."
    try:
        title = WINDOW_TITLE_MAP.get(param, param.title())
        wins = gw.getWindowsWithTitle(title)
        if wins:
            wins[0].close()
            return f"Closed {name}."
    except Exception:
        pass
    if param in UWP_MAP:
        result = subprocess.run(["taskkill", "/F", "/IM", UWP_MAP[param] + ".exe"], capture_output=True)
        return f"Closed {name}." if result.returncode == 0 else f"Couldn't close {name}."
    exe_name = os.path.basename(MANUAL_MAP[param]) if param in MANUAL_MAP else param + ".exe"
    result = subprocess.run(["taskkill", "/F", "/IM", exe_name], capture_output=True)
    return f"Closed {name}." if result.returncode == 0 else f"Couldn't find {name} running."


def close_application(parameter: str) -> str:
    if parameter.strip().lower() == "all":
        safe = {"explorer.exe", "python.exe", "pythonw.exe", "svchost.exe",
                "system", "registry", "smss.exe", "akira.py"}
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"].lower() not in safe:
                    proc.kill()
            except Exception:
                pass
        return "Closed everything."
    apps = [p.strip() for p in parameter.split(",") if p.strip()]
    if not apps:
        fg = get_foreground_app()
        if not fg:
            return "No application specified."
        target = fg[:-4] if fg.lower().endswith(".exe") else fg
        apps = [target]
    results = [_close_single_app(app) for app in apps]
    return " ".join(results)


def adjust_volume(parameter: str) -> str:
    devices = AudioUtilities.GetSpeakers()
    volume = devices.EndpointVolume
    param = parameter.lower().strip()
    if param in ("up", "higher", "louder"):
        param = "+10"
    elif param in ("down", "lower", "softer"):
        param = "-10"
    if param in MUTE_MAP:
        volume.SetMute(MUTE_MAP[param], None)
        return f"Volume {'muted' if MUTE_MAP[param] else 'unmuted'}."
    if param.startswith(("+", "-")):
        current = round(volume.GetMasterVolumeLevelScalar() * 100)
        new = max(0, min(100, current + int(param)))
        volume.SetMasterVolumeLevelScalar(new / 100.0, None)
        return f"Volume {new}%."
    try:
        p = max(0, min(100, int(param)))
        volume.SetMasterVolumeLevelScalar(p / 100.0, None)
        return f"Volume {p}%."
    except ValueError:
        return f"Don't understand '{parameter}' as volume."


def adjust_brightness(parameter: str) -> str:
    param = parameter.lower().strip()
    if param in BRIGHTNESS_MAP:
        new = BRIGHTNESS_MAP[param]
    elif param.startswith(("+", "-")):
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
                capture_output=True, text=True,
            )
            current = int(result.stdout.strip())
            new = max(0, min(100, current + int(param)))
        except Exception:
            return "Couldn't read current brightness."
    else:
        try:
            new = max(0, min(100, int(param)))
        except ValueError:
            return f"Don't understand '{parameter}' as brightness."
    result = subprocess.run(
        ["powershell", "-Command",
         f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{new})"],
        capture_output=True,
    )
    return f"Brightness {new}%." if result.returncode == 0 else "Couldn't change brightness."


def screenshot() -> dict:
    # AUDIT FIX: returned a bare string with no path — unchainable and
    # unverifiable. Now returns success + path so {{step.result}} works.
    path = os.path.join(_screenshot_dir, f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    ImageGrab.grab().save(path)
    return {"success": True, "path": path, "message": "Screenshot saved."}


# lock_screen / hibernate / shutdown / restart now live in system_control.py
# (see _ACTION_MAP aliases) so power handling has a single implementation.


def _normalize_win_text(text: str) -> str:
    """Normalize window title / query for robust matching.
    - Case-insensitive
    - Map number words to digits ('one' -> '1', 'four' -> '4')
    - Normalize number-letter adjacency ('Book1' <-> 'book 1')
    - Strip punctuation and excess whitespace
    """
    import re
    if not text:
        return ""
    t = text.lower().strip()
    # Word numbers to digits
    num_words = {
        "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        "first": "1", "second": "2", "third": "3", "fourth": "4",
    }
    for word, digit in num_words.items():
        t = re.sub(r"\b" + word + r"\b", digit, t)
    # Insert space between letters and numbers: "book1" -> "book 1"
    t = re.sub(r"([a-z])(\d+)", r"\1 \2", t)
    t = re.sub(r"(\d+)([a-z])", r"\1 \2", t)
    # Strip non-alphanumeric punctuation
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _find_window(param: str):
    """Locate open window using multi-stage normalized and token-based matching."""
    import re
    raw_param = (param or "").strip()
    if not raw_param:
        return None

    norm_param = _normalize_win_text(raw_param)
    param_tokens = set(norm_param.split()) if norm_param else set()
    collapsed_param = re.sub(r"\s+", "", norm_param)

    all_windows = []
    try:
        all_windows = list(gw.getAllWindows())
    except Exception:
        all_windows = []

    # Stage 1: Exact / substring match on normalized title
    for win in all_windows:
        if not win.title:
            continue
        norm_title = _normalize_win_text(win.title)
        collapsed_title = re.sub(r"\s+", "", norm_title)
        if raw_param.lower() in win.title.lower():
            return win
        if norm_param and norm_param in norm_title:
            return win
        if collapsed_param and (collapsed_param in collapsed_title or collapsed_title in collapsed_param):
            return win

    # Stage 2: Token overlap on title
    if param_tokens:
        best_win = None
        best_score = 0
        for win in all_windows:
            if not win.title:
                continue
            norm_title = _normalize_win_text(win.title)
            title_tokens = set(norm_title.split())
            overlap = len(param_tokens & title_tokens)
            if overlap > best_score and overlap >= len(param_tokens) * 0.5:
                best_score = overlap
                best_win = win
        if best_win:
            return best_win

    # Stage 3: Process name matching
    for win in all_windows:
        if not win.title:
            continue
        try:
            _, pid = win32process.GetWindowThreadProcessId(win._hWnd)
            proc = psutil.Process(pid)
            p_name = proc.name().lower()
            if raw_param.lower() in p_name or norm_param in p_name:
                return win
        except Exception:
            continue

    # Stage 4: Semantic application fallbacks
    app_synonyms = {
        "excel": ("excel", "sheet", "spreadsheet", "book", "workbook"),
        "word": ("word", "winword", "doc", "document"),
        "powerpoint": ("powerpoint", "powerpnt", "presentation", "slide", "slides", "deck"),
        "spotify": ("spotify", "music", "playlist"),
        "chrome": ("chrome", "browser", "tab", "web"),
        "code": ("code", "vscode", "visual studio code"),
    }
    for app_key, synonyms in app_synonyms.items():
        if any(syn in norm_param.split() or syn in raw_param.lower() for syn in synonyms):
            for win in all_windows:
                if not win.title:
                    continue
                t_lower = win.title.lower()
                if any(syn in t_lower for syn in synonyms):
                    return win
                try:
                    _, pid = win32process.GetWindowThreadProcessId(win._hWnd)
                    proc = psutil.Process(pid)
                    if app_key in proc.name().lower():
                        return win
                except Exception:
                    continue

    return None


def switch_window(parameter: str) -> str:
    param_clean = (parameter or "").strip()
    win = _find_window(param_clean)
    if win:
        try:
            win.activate()
        except Exception:
            pass
        return f"Switched to {win.title or parameter}."

    open_titles = [w.title for w in gw.getAllWindows() if w.title and w.title.strip()]
    if open_titles:
        return f"Couldn't find {parameter}. Open windows: {', '.join(open_titles[:4])}."
    return f"Couldn't find {parameter}."



def maximize_window(parameter: str) -> str:
    win = _find_window(parameter.lower().strip())
    if win:
        try:
            win.activate()
        except Exception:
            pass
        win.maximize()
        return f"Maximized {parameter}."
    return f"Couldn't find {parameter}."


def minimize_window(parameter: str) -> str:
    win = _find_window(parameter.lower().strip())
    if win:
        win.minimize()
        return f"Minimized {parameter}."
    return f"Couldn't find {parameter}."


def scroll(parameter: str) -> str:
    browser = get_browser(_last_browser_name)
    param = parameter.lower().strip()
    if "|" in param:
        parts = param.split("|")
        param = parts[0].strip()
        target_tab = parts[1].replace("tab:", "").strip()
        if target_tab:
            switch_tab(target_tab)
    scripts = {
        "down":   "window.scrollBy(0,500);",
        "up":     "window.scrollBy(0,-500);",
        "top":    "window.scrollTo(0,0);",
        "bottom": "window.scrollTo(0,document.body.scrollHeight);",
    }
    if param in scripts:
        browser.execute_script(scripts[param])
        return f"Scrolled {param}."
    try:
        browser.execute_script(f"window.scrollBy(0,{int(param)});")
        return f"Scrolled {param}px."
    except ValueError:
        return "Don't understand that scroll direction."


def new_tab(parameter: str | None = None) -> str:
    browser_name = None
    if parameter and "|browser:" in parameter:
        parameter, browser_name = parameter.split("|browser:", 1)
        parameter = parameter.strip()
        browser_name = browser_name.strip()
    browser = get_browser(browser_name)
    existing = set(browser.window_handles)
    new_handles = []
    browser.execute_cdp_cmd("Target.createTarget", {"url": "chrome://newtab"})
    for _ in range(10):
        new_handles = [h for h in browser.window_handles if h not in existing]
        if new_handles:
            break
        time.sleep(0.3)
    browser.switch_to.window(new_handles[0])
    if parameter:
        browser.get(f"https://www.google.com/search?q={urllib.parse.quote(parameter)}")
        return f"Searching {parameter} in new tab."
    return "New tab opened."


def open_site_tab(parameter: str) -> str:
    """Opens the requested site. If an existing tab for this site is already open,
    switches to that tab instead of opening a redundant new tab.
    Only creates a new tab if no existing matching tab is found."""
    browser = get_browser(_last_browser_name)
    site_clean = (parameter or "").strip().lower()
    url = resolve_site_url(parameter.strip())

    # Extract site keyword (e.g., 'youtube', 'amazon', 'netflix', 'github')
    site_keyword = site_clean.replace("https://", "").replace("http://", "").replace("www.", "").split(".")[0]
    if not site_keyword or len(site_keyword) < 3:
        site_keyword = site_clean

    matching_handle = None
    original_handle = None
    try:
        original_handle = browser.current_window_handle
    except Exception:
        pass

    try:
        for handle in browser.window_handles:
            try:
                browser.switch_to.window(handle)
                cur_url = (browser.current_url or "").lower()
                cur_title = (browser.title or "").lower()
                if site_keyword in cur_url or site_keyword in cur_title or (url.lower() in cur_url):
                    matching_handle = handle
                    break
            except Exception:
                continue
    except Exception:
        pass

    if matching_handle:
        browser.switch_to.window(matching_handle)
        browser._akira_tab = matching_handle
        if "youtube" in site_clean:
            browser._youtube_target_tab = matching_handle
            global _last_youtube_tab_handle
            _last_youtube_tab_handle = matching_handle
        return f"Switched to existing {parameter} tab."

    # Restore original window if no match was found during inspection
    if original_handle:
        try:
            browser.switch_to.window(original_handle)
        except Exception:
            pass

    existing = set(browser.window_handles)
    browser.execute_cdp_cmd("Target.createTarget", {"url": url})
    for _ in range(10):
        new_handles = [h for h in browser.window_handles if h not in existing]
        if new_handles:
            browser.switch_to.window(new_handles[0])
            browser._akira_tab = new_handles[0]
            if "youtube" in parameter.lower():
                browser._youtube_target_tab = new_handles[0]
                _last_youtube_tab_handle = new_handles[0]
            return f"Opened {parameter} in a new tab."
        time.sleep(0.02)
    return f"Opened {parameter} in browser."


def list_open_tabs() -> str:
    tabs = get_all_tabs()
    if not tabs:
        return "No tabs open."
    names = ", ".join(t["title"][:30] for t in tabs[:10] if t["title"])
    return f"Open tabs: {names}."


def switch_tab(parameter: str) -> str:
    """Switch focus to a tab matching the given name/title fragment.
    If multiple tabs match, prefer the last one in window_handles order 
    (most recently opened, since Selenium appends new handles at the end)."""
    browser = get_browser(_last_browser_name)
    target = parameter.lower().strip()
    matches = []
    for handle in browser.window_handles:
        browser.switch_to.window(handle)
        if target in browser.title.lower() or target in (browser.current_url or "").lower():
            matches.append((handle, browser.title[:40]))
    if not matches:
        return f"Couldn't find an open tab matching '{parameter}'."
    chosen_handle, chosen_title = matches[-1]
    browser.switch_to.window(chosen_handle)
    browser._akira_tab = chosen_handle
    return f"Switched to {chosen_title}."


def close_tab(parameter: str) -> str:
    """Close a tab matching the given name/title fragment. Never closes 
    Akira's own working tab."""
    browser = get_browser(_last_browser_name)
    target = parameter.lower().strip()
    for handle in browser.window_handles:
        if handle == getattr(browser, "_akira_tab", None):
            continue
        browser.switch_to.window(handle)
        if target in browser.title.lower() or target in (browser.current_url or "").lower():
            title = browser.title[:40]
            browser.close()
            remaining = [h for h in browser.window_handles if h != handle]
            if remaining:
                browser.switch_to.window(remaining[0])
            return f"Closed {title}."
    return f"Couldn't find an open tab matching '{parameter}' to close."


def fill(parameter: str) -> str:
    if not parameter or "|" not in parameter:
        return "I need a field description and text to type."
    parts = parameter.split("|")
    instruction, text = parts[0].strip(), parts[1].strip()
    should_submit = len(parts) > 2 and parts[2].strip().lower() == "submit"
    browser = get_browser(_last_browser_name)
    elements = extract_interactive_elements(browser, max_elements=100)
    from element_matcher import find_element_index
    index = find_element_index(elements, instruction)
    if index is None or index >= len(elements):
        # Fallback to first visible input/textarea on the page if exact match fails
        inputs = browser.find_elements(By.CSS_SELECTOR, 'input:not([type="hidden"]), textarea')
        for inp in inputs:
            if inp.is_displayed():
                try:
                    inp.click()
                    inp.clear()
                    inp.send_keys(text)
                    if should_submit:
                        from selenium.webdriver.common.keys import Keys
                        inp.send_keys(Keys.RETURN)
                    return f"Typed '{text}' into input field." + (" Submitted." if should_submit else "")
                except Exception:
                    continue
        return "Couldn't find that field."
    el = browser.find_elements(By.CSS_SELECTOR, f'[data-akira-index="{index}"]')
    if not el:
        return "Couldn't locate field in DOM."
    try:
        el[0].click()
        el[0].clear()
        el[0].send_keys(text)
        if should_submit:
            from selenium.webdriver.common.keys import Keys
            el[0].send_keys(Keys.RETURN)
    except Exception as e:
        return f"Couldn't type: {e}"
    return f"Typed '{text}'." + (" Submitted." if should_submit else "")


# ── Action dispatch ───────────────────────────────────────────────────────────

def _handle_open_url(parameter: str) -> str:
    if not parameter or not parameter.startswith(("https://", "http://")):
        return "That doesn't look like a valid URL."
    _navigate(parameter)
    return f"Opening {parameter}."


def _handle_web_search(parameter: str) -> str:
    browser_name = None
    if parameter and "|browser:" in parameter:
        parameter, browser_name = parameter.split("|browser:", 1)
        parameter, browser_name = parameter.strip(), browser_name.strip()

    has_explicit_prefix = False
    search_query = parameter or ""
    if "|" in search_query:
        prefix, rest = search_query.split("|", 1)
        if prefix.lower() in ("google", "web", "search", "bing", "yahoo"):
            has_explicit_prefix = True
            search_query = rest.strip()

    explicit_web = has_explicit_prefix or any(w in search_query.lower() for w in ["on the web", "on google", "google it", "on web"])
    query_clean = re.sub(r"\b(on the web|on google|google it|on web)\b", "", search_query, flags=re.I).strip()

    browser = get_browser(name=browser_name)
    browser.switch_to.window(browser._akira_tab)
    current_site = get_current_site(browser) if not explicit_web else None

    if current_site and current_site in SEARCH_URL_MAP:
        return _handle_site_search(f"{current_site}|{query_clean}")

    target_query = query_clean if explicit_web else search_query
    _navigate(f"https://www.google.com/search?q={urllib.parse.quote(target_query)}")

    try:
        browser.execute_script("""
            var sels = ["button[id*='reject']", "button[aria-label*='Reject']",
                        "button[aria-label*='Accept all']", "form[action*='consent'] button"];
            for (var i = 0; i < sels.length; i++) {
                var btn = document.querySelector(sels[i]);
                if (btn && btn.offsetParent !== null) { btn.click(); break; }
            }
        """)
    except Exception:
        pass

    return f"Searching for {parameter}."


# Search inputs, most specific first. A site's own box is always better than
# a Google click-through, which is what unlisted domains used to get.
_SEARCH_INPUT_JS = r"""
    const q = arguments[0];
    const sels = ['input[type="search"]', 'input[name="s"]', 'input[name="q"]',
                  'input[name="query"]', 'input[name="keyword"]',
                  'input[name="search"]', 'input[id*="search" i]',
                  'input[placeholder*="search" i]',
                  'input[aria-label*="search" i]', 'form[role="search"] input',
                  'input[type="text"]'];
    function visible(el) {
        const r = el.getBoundingClientRect();
        if (r.width < 30 || r.height < 10) return false;
        const s = getComputedStyle(el);
        return s.visibility !== 'hidden' && s.display !== 'none';
    }
    for (const sel of sels) {
        let el;
        try { el = document.querySelector(sel); } catch (e) { continue; }
        if (!el || !visible(el)) continue;
        el.focus();
        el.value = q;
        el.dispatchEvent(new Event('input',  {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        const form = el.closest('form');
        if (form) {
            if (form.requestSubmit) form.requestSubmit(); else form.submit();
        } else {
            for (const type of ['keydown', 'keypress', 'keyup']) {
                el.dispatchEvent(new KeyboardEvent(type, {key: 'Enter',
                    code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
            }
        }
        return sel;
    }
    return null;
"""


def _normalize_site(site: str) -> str:
    """'mangafreak.me', 'www.mangafreak.me', 'MangaFreak' -> lookup key + host."""
    s = (site or '').strip().lower().rstrip('/')
    s = re.sub(r'^https?://', '', s)
    s = re.sub(r'^www\.', '', s)
    return s.split('/')[0]


def _handle_site_search(parameter: str) -> str:
    """Search a named site. Known sites use their direct search URL; ANY other
    named domain is driven through its OWN search box, with a Google
    `site:` query only as the final fallback.

    Previously an unlisted domain went straight to a Google click-through,
    which is why "search mangafreak.me for one piece" never searched the site.
    """
    if not parameter or "|" not in parameter:
        return "I need a site and a query."
    site, query = parameter.split("|", 1)
    site, query = _normalize_site(site), query.strip()
    if not query:
        return "What should I search for?"
    encoded = urllib.parse.quote(query)

    # 1. Known site with a direct search URL.
    template = SEARCH_URL_MAP.get(site) or SEARCH_URL_MAP.get(site.split('.')[0])
    if template:
        _navigate(template.format(encoded))
        return f"Searching {query} on {site}."

    # 2. Unlisted domain: drive the site's own search box.
    host = site if '.' in site else f"{site}.com"
    _navigate(f"https://{host}/")
    browser = get_browser(_last_browser_name)
    try:
        WebDriverWait(browser, 8).until(
            EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass
    try:
        used = browser.execute_script(_SEARCH_INPUT_JS, query)
    except Exception as e:
        print(f"[SITESEARCH] {host} probe failed: {e}")
        used = None
    if used:
        print(f"[SITESEARCH] {host} via own search input {used!r}")
        # Confirm the submit actually navigated/queried before claiming it.
        root = f"https://{host}/"
        if _await_state(lambda: (browser.current_url or "") != root, timeout=6.0):
            return f"Searching {query} on {host}."
        print(f"[SITESEARCH] {host} submit did not navigate")

    # 3. No usable search box — fall back to a scoped Google query.
    print(f"[SITESEARCH] {host} has no search input, using Google site: query")
    _navigate(f"https://www.google.com/search?q={encoded}+site:{host}")
    return f"That site has no search box I could use, so I searched Google for {query} on {host}."


def _handle_click(parameter: str) -> str | dict:
    # NATIVE-APP ROUTING FIRST. structural_ui's selectors are browser-DOM-only
    # (role="tab", href, aria), so "click the Performance tab in Task Manager"
    # can never resolve there — it previously reported "0 tab candidates",
    # which reads as a bug rather than the real answer. A named native app is
    # either driven through UI Automation or honestly declined, and neither
    # path should start a browser.
    import native_ui
    native_app = native_ui.detect_native_target(parameter)
    if native_app:
        if not native_ui.is_supported(native_app):
            return native_ui.unsupported_reason(native_app, parameter)
        return native_ui.click_native(parameter)

    browser = get_browser(_last_browser_name)
    try:
        WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass

    # Structural controls and history nav are classified BEFORE any content
    # matching. "go back" has no DOM element at all, and a tab/profile routed
    # through the content matcher gets hijacked by role_intent.
    from structural_ui import classify_structural_intent, resolve_structural
    intent = classify_structural_intent(parameter)
    if intent:
        kind, value = intent
        if kind == 'nav':
            return browser_control(value)["message"]
        return resolve_structural(browser, intent)["message"]

    elements = extract_interactive_elements(browser, max_elements=200)
    
    # Debug: print first 5 element texts to see what we're getting
    if elements:
        print(f"[DEBUG] First 5 elements: {[el['text'][:40] for el in elements[:5]]}")
    
    from element_matcher import find_element_index
    index = find_element_index(elements, parameter)
    print(f"[CLICK] Matched index={index} for '{parameter}'")

    if index is None or index >= len(elements):
        # Report the failure and name what IS on the page. Guessing by screen
        # coordinates used to click whatever window held OS focus.
        return _no_match_report(parameter, elements)

    target = elements[index]
    print(f"[CLICK] Target: [{target['role']}] '{target['text'][:50]}'")
    
    try:
        result = click_element(browser, index, expected_text=target["text"],
                               expected_href=target["href"], instruction=parameter,
                               elements=elements)
    except Exception as e:
        print(f"[CLICK] Exception: {e!r}")
        return f"Couldn't click that: {e}"

    if not result["success"]:
        return f"Couldn't click that: {result['reason']}"

    if result["needs_confirmation"]:
        return {
            "needs_click_confirmation": True,
            "element_text": result["element"]["text"],
            "_execute": result["_execute"],
            "retry_parameter": parameter,
        }

    try:
        result["_execute"]()
    except Exception as e:
        print(f"[CLICK] Execute failed: {e!r}")
        return f"Couldn't click that: {e}"

    return f"Clicked {result['element']['text'][:50]}."


# Dispatch table — replaces 150-line if/elif chain
_ACTION_MAP = {
    "open_application":  open_application,
    "close_application": close_application,
    "open_url":          _handle_open_url,
    "web_search":        _handle_web_search,
    "site_search":       _handle_site_search,
    "fill":              fill,
    "fill_input":        fill,
    "scroll":            scroll,
    "new_tab":           new_tab,
    "open_site_tab":     open_site_tab,
    "list_tabs":         lambda _: list_open_tabs(),
    "switch_tab":        switch_tab,
    "close_tab":         close_tab,
    "click":             _handle_click,
    "browser_control":   browser_control,
    "youtube_control":   youtube_control,
    "netflix_control":   lambda p: netflix_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "meet_control":      lambda p: meet_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "amazon_control":    lambda p: amazon_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "flipkart_control":  lambda p: flipkart_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "github_control":    lambda p: github_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "vscode_control":    lambda p: vscode_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "spotify_control":   lambda p: spotify_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    # Google Workspace via MCP (lazy imports: node/npx only needed on first use)
    "calendar_control":  lambda p: __import__("calendar_control").calendar_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "docs_control":      lambda p: __import__("docs_control").docs_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "sheets_control":    lambda p: __import__("sheets_control").sheets_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "slides_control":    lambda p: __import__("slides_control").slides_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "gmail_control":     lambda p: __import__("gmail_control").gmail_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    # Microsoft Office via COM (lazy import: pywin32 COM only touched on use)
    "office_control":    lambda p: __import__("office_control").office_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    # Obsidian via the Local REST API plugin (lazy: no network touched until used).
    # REST, not the plugin's MCP server — see obsidian_api's module docstring for
    # why (stdio-only MCP client, no tool-loop, and the safety gates live here).
    "obsidian_control":  lambda p: __import__("obsidian_control").obsidian_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    # browser-side Gmail drafting — deliberately NOT the Gmail MCP (see gmail_compose docstring)
    "gmail_compose":     lambda p: gmail_compose(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
    "create_file":       create_file,
    "read_file":         read_file,
    "read_more":         read_more,
    "stop_reading":      stop_reading,
    "write_file":        write_file,
    "edit_file":         edit_file,
    "search_file":       search_file,
    "manage_index_scope": manage_index_scope,
    "index_stats":       index_stats,
    "open_file":         open_file,
    "open_study_room":   open_study_room,
    "open_folder":       open_folder,
    "list_folder":       list_folder,
    "copy_files":        copy_files,
    "move_files":        move_files,
    "organize_files":    organize_files,
    "delete_files":      delete_files,
    "organize_folder":   organize_folder,
    "bulk_rename_files": bulk_rename_files,
    "compress_files":    compress_files,
    "extract_files":     extract_files,
    "summarize_file":    summarize_file,
    "file_to_doc":       file_to_doc,
    "search_image":      search_image,
    "download_image":    download_image,
    "set_wallpaper":     set_wallpaper,
    "read_clipboard":    read_clipboard,
    "speak_clipboard":   read_clipboard,
    "write_clipboard":   write_clipboard,
    "generate_to_clipboard": generate_to_clipboard,
    "adjust_volume":     adjust_volume,
    "adjust_brightness": adjust_brightness,
    "screenshot":        lambda _: screenshot(),
    # "how's that going?" / "is it done yet?" — answers from the background task
    # registry. Lazy import keeps executor's import graph unchanged.
    "background_status": lambda _: {
        "success": True, "speak": True,
        "message": __import__("background_tasks").status_line()},
    # Legacy action names kept as aliases onto the single system_control
    # implementation — the old local copies used bare `shutdown /f`, which
    # force-killed apps past unsaved work, and never checked whether
    # hibernate was even enabled.
    "lock_screen":       _system_control.lock_pc,
    "hibernate":         _system_control.hibernate_pc,
    "shutdown":          _system_control.shutdown_pc,
    "restart":           _system_control.restart_pc,
    "switch_window":     switch_window,
    "maximize_window":   maximize_window,
    "minimize_window":   minimize_window,
    "bookmark_page":     lambda _: _bookmark(),
    # Windows system/settings control. Imported as one dict so adding an
    # action there needs no edit here. Tier 2 entries are confirmation-gated
    # by akira's existing safety net, not by anything in this map.
    **_system_control.ACTIONS,
    # ── LLM hallucination aliases ─────────────────────────────────────────
    # Groq sometimes invents plausible action names that don't exist. These
    # aliases route them to the closest real handler so they execute cleanly
    # instead of failing with "Unknown action".
    "write_text":    write_clipboard,   # "write text in notepad" → clipboard
    "type_text":     write_clipboard,   # "type this text" → clipboard
    "insert_text":   write_clipboard,   # "insert text" → clipboard
    "click_element": _handle_click,     # "click element" → _handle_click
    "file_search":   search_file,       # "find a file named X" → search_file
    "folder_search": search_file,       # "find a folder named X" → search_file
}


def _bookmark() -> str:
    try:
        browser = get_browser(_last_browser_name)
        browser.find_element(By.TAG_NAME, "body").send_keys("\ue009d")
        return "Bookmarked."
    except Exception:
        return "Couldn't bookmark."


def execute(action: str, parameter, guard_token: GuardToken | None = None) -> str | dict:
    if guard_token is None:
        raise GuardBypassError(
            f"GUARD bypass rejected: execution of {action!r} structurally blocked (missing required GuardToken)."
        )
    if not isinstance(guard_token, GuardToken) or not guard_token.is_valid_for(action, parameter):
        raise GuardBypassError(
            f"GUARD bypass rejected: execution of {action!r} structurally blocked (invalid, forged, or mismatched GuardToken)."
        )
    handler = _ACTION_MAP.get(action)
    if handler:
        try:
            return handler(parameter)
        except Exception as e:
            print(f"[DEBUG] execute: unhandled exception in {action}: {e!r}")
            return f"Something went wrong with {action}: {e}"
    return f"Unknown action: {action}"