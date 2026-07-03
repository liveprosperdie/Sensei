"""
executor.py — Akira's hands.
Handles all PC control, browser automation, and action dispatch.
"""

import os
import re
import time
import glob
import shutil
import psutil
import winreg
import datetime
import webbrowser
import subprocess
import urllib.parse
import win32process
import win32gui
import requests
import pygetwindow as gw
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
}

WEB_MAP = {
    "youtube": "https://youtube.com", "claude": "https://claude.ai",
    "gmail": "https://mail.google.com", "github": "https://github.com",
    "instagram": "https://instagram.com", "pinterest": "https://pinterest.com",
    "facebook": "https://facebook.com", "twitter": "https://x.com",
    "weather": "https://weather.com", "calendar": "https://calendar.google.com",
    "x": "https://x.com",
}

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


def _attach_cdp(binary_path: str, port: int, service) -> webdriver.Chrome:
    binary_name = os.path.basename(binary_path).lower()
    if not _port_ready(port):
        for p in psutil.process_iter(["name"]):
            try:
                if p.info["name"] and p.info["name"].lower() == binary_name:
                    _kill_process(binary_name)
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        profile_dir = os.path.join(os.environ["LOCALAPPDATA"], "Sensei", "AkiraChromeProfile")
        os.makedirs(profile_dir, exist_ok=True)
        subprocess.Popen([
            binary_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--restore-last-session=false",
        ])
        for _ in range(40):
            if _port_ready(port):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"Browser at {binary_path} did not bind port {port} within 20s")

    options = Options()
    options.binary_location = binary_path
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    driver = webdriver.Chrome(service=service, options=options)
    _ensure_akira_tab(driver)
    return driver


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
    _ensure_akira_tab(driver)
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


def get_browser(name: str | None = None, incognito: bool = False) -> webdriver.Chrome:
    global _browsers, _last_browser_name
    name = (name or _get_default_browser()).lower().strip()
    key = f"{name}_incognito" if incognito else name

    # return cached driver if alive
    if key in _browsers:
        driver = _browsers[key]
        try:
            _ = driver.title
            _ensure_akira_tab(driver)
            return driver
        except Exception:
            del _browsers[key]

    # create new driver
    if name == "brave":
        svc_path = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
        svc = Service(svc_path if os.path.exists(svc_path) else ChromeDriverManager().install())
        if incognito:
            opt = Options()
            opt.binary_location = BRAVE_PATH
            opt.add_argument("--incognito")
            driver = webdriver.Chrome(service=svc, options=opt)
        else:
            driver = _attach_cdp(BRAVE_PATH, 9222, svc)

    elif name == "chrome":
        svc = Service(ChromeDriverManager().install())
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
        svc = Service(ChromeDriverManager().install())
        driver = _attach_cdp(CHROME_PATH, 9223, svc)

    _browsers[key] = driver
    _last_browser_name = name
    return driver


def _navigate(url: str) -> None:
    """Navigate Akira's tab to a URL. Single source of truth for navigation."""
    browser = get_browser(_last_browser_name)
    browser.switch_to.window(browser._akira_tab)
    browser.get(url)


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
    windows = []
    try:
        windows = [w.title for w in gw.getAllWindows() if w.title.strip()][:10]
    except Exception:
        pass

    current_url, current_title = None, None
    try:
        browser = get_browser()
        current_url = browser.current_url
        current_title = browser.title
    except Exception:
        pass

    return {
        "open_windows": windows,
        "current_url": current_url,
        "current_page_title": current_title,
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


# ── Element extraction ────────────────────────────────────────────────────────

def extract_interactive_elements(driver, max_elements: int = 80) -> list[dict]:
    """
    CDP accessibility tree → element list with data-akira-index injected via
    a single Runtime.evaluate call (not one CDP call per node).
    Falls back to DOM extraction if CDP fails.
    """
    try:
        result = driver.execute_cdp_cmd("Accessibility.getFullAXTree", {})
        nodes = result.get("nodes", [])

        interactive_roles = {
            "button", "link", "menuitem", "option", "checkbox", "radio",
            "tab", "textbox", "searchbox", "combobox", "listbox",
            "menuitemcheckbox", "menuitemradio", "switch", "treeitem",
        }

        items = []
        backend_ids = []

        for node in nodes:
            if len(items) >= max_elements:
                break
            role = node.get("role", {}).get("value", "")
            if role not in interactive_roles:
                continue
            name = node.get("name", {}).get("value", "").strip()
            if not name:
                continue
            backend_id = node.get("backendDOMNodeId")
            if not backend_id:
                continue
            items.append({
                "index": len(items),
                "role": role,
                "text": name[:150],
                "href": None,
                "_backend_id": backend_id,
            })
            backend_ids.append(backend_id)

        if not items:
            raise ValueError("No interactive nodes found in AX tree")

        # inject data-akira-index in a single JS evaluation
        inject_script = """
        (function(backendIds) {
            backendIds.forEach(function(backendId, idx) {
                try {
                    var el = __selenium_target__(backendId);
                    if (el) {
                        el.setAttribute('data-akira-index', String(idx));
                    }
                } catch(e) {}
            });
        })(arguments[0]);
        """
        # Use CDP DOM.resolveNode + Runtime.callFunctionOn per node in batches
        # Fallback: use JS to walk all elements and tag them
        tag_script = """
        (function() {
            var all = document.querySelectorAll('a,button,input,textarea,select,[role]');
            var idx = 0;
            var tagged = 0;
            for (var i = 0; i < all.length && tagged < arguments[0]; i++) {
                var el = all[i];
                var existing = el.getAttribute('data-akira-index');
                if (existing !== null) { tagged++; continue; }
                var role = el.getAttribute('role') || el.tagName.toLowerCase();
                var name = el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '';
                name = name.trim();
                if (!name) continue;
                el.setAttribute('data-akira-index', String(idx));
                idx++;
                tagged++;
            }
        })();
        """

        # Try resolving each node via CDP and injecting index
        resolved_count = 0
        for i, item in enumerate(items):
            bid = item.pop("_backend_id")
            try:
                resolve = driver.execute_cdp_cmd("DOM.resolveNode", {"backendNodeId": bid})
                obj_id = resolve.get("object", {}).get("objectId")
                if obj_id:
                    driver.execute_cdp_cmd("Runtime.callFunctionOn", {
                        "objectId": obj_id,
                        "functionDeclaration": f"function(){{this.setAttribute('data-akira-index','{i}')}}",
                        "returnByValue": True,
                    })
                    # grab href for links
                    if item["role"] == "link":
                        href_res = driver.execute_cdp_cmd("Runtime.callFunctionOn", {
                            "objectId": obj_id,
                            "functionDeclaration": "function(){return this.href||null}",
                            "returnByValue": True,
                        })
                        item["href"] = href_res.get("result", {}).get("value")
                    resolved_count += 1
            except Exception:
                pass

        print(f"[DEBUG] extract_elements (CDP) found {len(items)}, resolved {resolved_count}")
        return items

    except Exception as e:
        print(f"[DEBUG] CDP extraction failed, using DOM fallback: {e}")

    # DOM fallback — single JS call
    script = """
    const items = [];
    const sel = 'a,button,input,textarea,select,[role="button"],[onclick]';
    const els = document.querySelectorAll(sel);
    let idx = 0;
    for (const el of els) {
        if (idx >= arguments[0]) break;
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const s = window.getComputedStyle(el);
        if (s.visibility === 'hidden' || s.display === 'none') continue;
        let text = (el.innerText || el.value || el.placeholder ||
                    el.getAttribute('aria-label') || el.getAttribute('title') ||
                    el.getAttribute('alt') || '').replace(/\\s+/g,' ').trim().slice(0,150);
        if (!text && el.tagName !== 'INPUT') continue;
        const act = ['INPUT','TEXTAREA','BUTTON','SELECT'].includes(el.tagName);
        if (!el.href && !act) continue;
        el.setAttribute('data-akira-index', idx);
        items.push({index:idx, role:el.tagName.toLowerCase(), text, href:el.href||null});
        idx++;
    }
    return items;
    """
    elements = driver.execute_script(script, max_elements)
    print(f"[DEBUG] extract_elements (DOM fallback) found {len(elements)}")
    return elements


# ── Vision click ──────────────────────────────────────────────────────────────

_vision_call_count = 0

def vision_click(browser, instruction: str) -> bool:
    """Screenshot → Sonnet vision → JS click at coordinates. Returns success bool."""
    global _vision_call_count
    _vision_call_count += 1
    print(f"[COST] vision_click call #{_vision_call_count} — instruction: '{instruction}'")
    path = os.path.join(_screenshot_dir, f"akira_v_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    img = ImageGrab.grab()
    if img.width > 1280:
        ratio = 1280 / img.width
        img = img.resize((1280, int(img.height * ratio)))
    img.save(path)
    try:
        from claude_handler import vision_match
        coords = vision_match(path, instruction)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass

    if not coords:
        print(f"[DEBUG] vision_click: no match for '{instruction}'")
        return False

    x, y = coords
    browser.execute_script(f"document.elementFromPoint({x},{y})?.click();")
    print(f"[DEBUG] vision_click: clicked at ({x},{y}) for '{instruction}'")
    return True


# ── Click element (CDP path) ──────────────────────────────────────────────────

def click_element(driver, index: int, expected_text: str | None = None,
                  expected_href: str | None = None, instruction: str | None = None) -> dict:
    """
    Click element at index. Validates staleness, checks RISKY_KEYWORDS,
    falls back to vision if DOM lookup fails.
    """
    fresh = extract_interactive_elements(driver, max_elements=100)

    if index >= len(fresh):
        return {"success": False, "reason": "index out of range"}

    current = fresh[index]
    stale = (
        (expected_text is not None and current["text"] != expected_text) or
        (expected_href is not None and current["href"] != expected_href)
    )

    if stale:
        if instruction:
            from claude_handler import find_element_index
            new_idx = find_element_index(fresh, instruction)
            if new_idx is None or new_idx >= len(fresh):
                return {"success": False, "reason": "element changed and re-match failed"}
            index = new_idx
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

def youtube_control(parameter: str) -> str:
    browser = get_browser(_last_browser_name)
    param = parameter.lower().strip()

    try:
        browser.switch_to.window(browser._akira_tab)
        WebDriverWait(browser, 8).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass

    # ── Group A: JS media controls — zero API cost ────────────────────

    if param in ("play", "pause"):
        browser.execute_script("document.querySelector('video')?.click();")
        return "Done."

    if param == "skip ad":
        browser.execute_script("""
            var btn = document.querySelector('.ytp-skip-ad-button,.ytp-ad-skip-button,.ytp-ad-skip-button-modern');
            if (btn) btn.click();
        """)
        return "Ad skipped."

    if param.startswith("volume "):
        try:
            val = max(0, min(100, int(param.replace("volume", "").replace("%", "").strip())))
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
        browser.execute_script("document.querySelector('.ytp-fullscreen-button')?.click();")
        return "Fullscreen."

    if param in ("theatre mode", "theater mode", "theatre", "theater"):
        browser.execute_script("document.querySelector('.ytp-size-button')?.click();")
        return "Theatre mode."

    if param in ("default view", "exit fullscreen", "exit theatre", "exit theater"):
        browser.execute_script("""
            if (document.fullscreenElement) document.exitFullscreen();
            else document.querySelector('.ytp-size-button')?.click();
        """)
        return "Default view."

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
            browser.execute_script(f"var v=document.querySelector('video'); if(v) v.currentTime+={seconds};")
            return f"Seeked {seconds}s."
        except ValueError:
            return "Give me seconds to seek."

    if param == "go back":
        browser.back()
        return "Going back."

    if param == "go forward":
        browser.forward()
        return "Going forward."

    if param.startswith("search "):
        query = urllib.parse.quote(param.replace("search", "").strip())
        browser.execute_script(f"window.location.href='https://www.youtube.com/results?search_query={query}';")
        return "Searching YouTube."

    if param.startswith("go to channel"):
        channel = param.replace("go to channel", "").strip()
        if not channel:
            vision_click(browser, "channel name link below the video title")
            return "Going to channel."
        query = urllib.parse.quote(channel)
        browser.execute_script(f"window.location.href='https://www.youtube.com/results?search_query={query}+channel';")
        return f"Searching for {channel}'s channel."

    # ── Group B: play video — CDP then vision ─────────────────────────

    if param.startswith("play video") or param.startswith("click video"):
        description = param.replace("play video", "").replace("click video", "").strip()
        time.sleep(1.0)
        elements = extract_interactive_elements(browser, max_elements=100)
        from claude_handler import find_element_index
        idx = find_element_index(elements, description)
        if idx is not None:
            clicked = browser.execute_script(f"""
                var el=document.querySelector('[data-akira-index="{idx}"]');
                if(el){{el.click();return true;}}return false;
            """)
            if clicked:
                return f"Playing {description}."
        success = vision_click(browser, f"video thumbnail or title: {description}")
        return "Playing it." if success else "Couldn't find that video."

    # ── Group C: everything else — vision primary ─────────────────────

    vision_descriptions = {
        "like":           "like button thumbs up below the video",
        "dislike":        "dislike button thumbs down below the video",
        "subscribe":      "subscribe button below the video title",
        "unsubscribe":    "unsubscribe button below the video title",
        "share":          "share button below the video",
        "save":           "save button below the video",
        "play next":      "next video button in player controls",
        "next video":     "next video button in player controls",
        "history":        "history item in left sidebar",
        "watch later":    "watch later item in left sidebar",
        "liked videos":   "liked videos item in left sidebar",
        "playlists":      "playlists item in left sidebar",
        "your channel":   "your channel item in left sidebar",
        "downloads":      "downloads item in left sidebar",
        "home":           "home button in left sidebar",
        "open comments":  "comments section on page",
        "settings":       "settings gear icon in video player",
        "ambient mode":   "ambient mode toggle in settings menu",
        "sleep timer":    "sleep timer option in settings menu",
        "quality":        "quality option in settings menu",
        "switch account": "account avatar button top right",
        "sign out":       "sign out option in account menu",
        "music":          "music filter chip at top of page",
        "gaming":         "gaming filter chip at top of page",
        "live":           "live filter chip at top of page",
        "news":           "news filter chip at top of page",
        "ask":            "ask button below the video",
        "clips":          "clip button below the video",
    }

    # pre-open menus for nested items
    if param in {"ambient mode", "sleep timer", "quality", "playback speed menu"}:
        browser.execute_script("document.querySelector('.ytp-settings-button')?.click();")
        time.sleep(0.5)
    elif param in {"switch account", "sign out", "manage premium"}:
        browser.execute_script("document.querySelector('button#avatar-btn')?.click();")
        time.sleep(0.5)

    instruction = vision_descriptions.get(param, param)
    success = vision_click(browser, instruction)
    return "Done." if success else f"Couldn't find {param} on the page."


# ── System actions ────────────────────────────────────────────────────────────

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


def _open_single_app(name: str) -> str:
    param = APP_ALIASES.get(name.lower().strip(), name.lower().strip())

    if param in URI_MAP:
        try:
            os.startfile(URI_MAP[param])
            return f"Opening {name}."
        except Exception:
            return f"Couldn't open {name}."

    if param in WEB_MAP:
        webbrowser.open(WEB_MAP[param])
        return f"Opening {name}."

    exe = _find_exe(param)
    if exe:
        subprocess.Popen(exe)
        return f"Opening {name}."

    # last resort
    try:
        subprocess.Popen(["cmd", "/c", "start", "", name])
        return f"Trying to open {name}."
    except Exception:
        return f"Couldn't find {name}."


def open_application(parameter: str) -> str:
    for app in [p.strip() for p in parameter.split(",")]:
        _open_single_app(app)
    return "Done."


def _close_single_app(name: str) -> str:
    param = name.lower().strip()
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
                "system", "registry", "smss.exe", "sensei.py"}
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"].lower() not in safe:
                    proc.kill()
            except Exception:
                pass
        return "Closed everything."
    for app in [p.strip() for p in parameter.split(",")]:
        _close_single_app(app)
    return "Done."


def adjust_volume(parameter: str) -> str:
    devices = AudioUtilities.GetSpeakers()
    volume = devices.EndpointVolume
    param = parameter.lower().strip()
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


def screenshot() -> str:
    path = os.path.join(_screenshot_dir, f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    ImageGrab.grab().save(path)
    return f"Screenshot saved."


def lock_screen() -> str:
    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "Locking screen."


def hibernate() -> str:
    subprocess.Popen(["shutdown", "/h"])
    return "Hibernating."


def shutdown() -> str:
    subprocess.Popen(["shutdown", "/s", "/t", "0", "/f"])
    return "Shutting down."


def restart() -> str:
    subprocess.Popen(["shutdown", "/r", "/t", "0", "/f"])
    return "Restarting."


def _find_window(param: str):
    for win in gw.getAllWindows():
        if win.title and param in win.title.lower():
            return win
    for win in gw.getAllWindows():
        if not win.title:
            continue
        try:
            _, pid = win32process.GetWindowThreadProcessId(win._hWnd)
            proc = psutil.Process(pid)
            if param in proc.name().lower():
                return win
        except Exception:
            continue
    return None


def switch_window(parameter: str) -> str:
    win = _find_window(parameter.lower().strip())
    if win:
        try:
            win.activate()
        except Exception:
            pass
        return f"Switched to {parameter}."
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


def fill(parameter: str) -> str:
    if not parameter or "|" not in parameter:
        return "I need a field description and text to type."
    parts = parameter.split("|")
    instruction, text = parts[0].strip(), parts[1].strip()
    should_submit = len(parts) > 2 and parts[2].strip().lower() == "submit"
    browser = get_browser(_last_browser_name)
    elements = extract_interactive_elements(browser, max_elements=100)
    from claude_handler import find_element_index
    index = find_element_index(elements, instruction)
    if index is None or index >= len(elements):
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

    explicit_web = any(w in parameter.lower() for w in ["on the web", "on google", "google it", "on web"])
    query_clean = re.sub(r"\b(on the web|on google|google it|on web)\b", "", parameter, flags=re.I).strip()

    browser = get_browser(name=browser_name)

    if not explicit_web:
        current_site = get_current_site(browser)
        # only route to site search if user is actively on that site's content page
        # never route if on homepage, blank tab, or search results already
        current_url = browser.current_url or ""
        is_content_page = current_site and not any(
            x in current_url for x in ["search_query=", "/results?", "about:blank", "newtab", "google.com"]
        )
        if is_content_page and current_site in SEARCH_URL_MAP:
            return _handle_site_search(f"{current_site}|{query_clean}")

    _navigate(f"https://www.google.com/search?q={urllib.parse.quote(query_clean if explicit_web else parameter)}")

    # dismiss consent popups
    try:
        for selector in [
            "button[id*='reject']", "button[aria-label*='Reject']",
            "button[aria-label*='Accept all']", "form[action*='consent'] button",
        ]:
            try:
                btn = WebDriverWait(browser, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                btn.click()
                break
            except Exception:
                continue
    except Exception:
        pass

    return f"Searching for {parameter}."


def _handle_site_search(parameter: str) -> str:
    if not parameter or "|" not in parameter:
        return "I need a site and a query."
    site, query = parameter.split("|", 1)
    site, query = site.strip().lower(), query.strip()
    template = SEARCH_URL_MAP.get(site)
    url = template.format(urllib.parse.quote(query)) if template else \
          f"https://www.google.com/search?q={urllib.parse.quote(query)}+site:{site}.com"
    _navigate(url)
    return f"Searching {query} on {site}."


def _handle_click(parameter: str) -> str | dict:
    browser = get_browser(_last_browser_name)
    try:
        WebDriverWait(browser, 5).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except Exception:
        pass

    elements = extract_interactive_elements(browser, max_elements=100)
    from claude_handler import find_element_index
    index = find_element_index(elements, parameter)
    print(f"[DEBUG] click: matched index={index} for '{parameter}'")

    if index is None or index >= len(elements):
        print(f"[DEBUG] click: vision fallback")
        return "Done." if vision_click(browser, parameter) else "Couldn't find that on the page."

    target = elements[index]
    try:
        result = click_element(browser, index, expected_text=target["text"],
                               expected_href=target["href"], instruction=parameter)
    except Exception as e:
        print(f"[DEBUG] click_element exception: {e!r}")
        return f"Couldn't click that: {e}"

    if not result["success"]:
        # fallback to vision on element failure
        print(f"[DEBUG] click: element failed ({result['reason']}), trying vision")
        return "Done." if vision_click(browser, parameter) else f"Couldn't click that: {result['reason']}"

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
        print(f"[DEBUG] _execute exception: {e!r}")
        return f"Couldn't click that: {e}"

    return f"Clicked {result['element']['text']}."


# Dispatch table — replaces 150-line if/elif chain
_ACTION_MAP = {
    "open_application":  open_application,
    "close_application": close_application,
    "open_url":          _handle_open_url,
    "web_search":        _handle_web_search,
    "site_search":       _handle_site_search,
    "fill":              fill,
    "scroll":            scroll,
    "new_tab":           new_tab,
    "click":             _handle_click,
    "youtube_control":   youtube_control,
    "adjust_volume":     adjust_volume,
    "adjust_brightness": adjust_brightness,
    "screenshot":        lambda _: screenshot(),
    "lock_screen":       lambda _: lock_screen(),
    "hibernate":         lambda _: hibernate(),
    "shutdown":          lambda _: shutdown(),
    "restart":           lambda _: restart(),
    "switch_window":     switch_window,
    "maximize_window":   maximize_window,
    "minimize_window":   minimize_window,
    "bookmark_page":     lambda _: _bookmark(),
}


def _bookmark() -> str:
    try:
        browser = get_browser(_last_browser_name)
        browser.find_element(By.TAG_NAME, "body").send_keys("\ue009d")
        return "Bookmarked."
    except Exception:
        return "Couldn't bookmark."


def execute(action: str, parameter) -> str | dict:
    handler = _ACTION_MAP.get(action)
    if handler:
        try:
            return handler(parameter)
        except Exception as e:
            print(f"[DEBUG] execute: unhandled exception in {action}: {e!r}")
            return f"Something went wrong with {action}: {e}"
    return f"Unknown action: {action}"
