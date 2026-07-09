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
}

def resolve_site_url(name: str) -> str:
    """Map a spoken site name to a URL. Falls back to guessing the domain, 
    then Google search if the guess looks wrong."""
    key = name.lower().strip()
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


def _ensure_akira_tab(driver) -> None:
    """Create Akira's own working tab if it doesn't exist. Never switches 
    focus away from the user's active tab unless _navigate() is called."""
    if hasattr(driver, "_akira_tab") and driver._akira_tab in driver.window_handles:
        return
    existing = set(driver.window_handles)
    driver.execute_cdp_cmd("Target.createTarget", {"url": "about:blank", "background": True})
    for _ in range(10):
        new = [h for h in driver.window_handles if h not in existing]
        if new:
            driver._akira_tab = new[0]
            return
        time.sleep(0.3)


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
            _ensure_current_handle(driver)
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

    _ensure_akira_tab(driver)
    _browsers[key] = driver
    _last_browser_name = name
    return driver


def _navigate(url: str) -> None:
    """Navigate Akira's dedicated tab to a URL. Never touches user's other tabs."""
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

def extract_interactive_elements(driver, max_elements: int = 150) -> list[dict]:
    """
    Extract interactive elements using aggressive DOM approach (no CDP tree overhead).
    Captures YouTube video thumbnails, address bar, and all clickable elements.
    """

    # Aggressive DOM extraction script - wrapped in try-catch
    script = """
    try {
        const items = [];
        let idx = 0;
        const maxItems = arguments[0];
        
        // Helper to get visible text
        function getText(el) {
            try {
                return (el.innerText || el.textContent || el.value || el.placeholder ||
                        el.getAttribute('aria-label') || el.getAttribute('title') ||
                        el.getAttribute('alt') || el.getAttribute('name') || '')
                       .replace(/\\s+/g,' ').trim().slice(0, 200);
            } catch(e) {
                return '';
            }
        }
        
        // Helper to check visibility
        function isVisible(el) {
            try {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                if (r.width < 5 || r.height < 5) return false;
                const s = window.getComputedStyle(el);
                return s.visibility !== 'hidden' && s.display !== 'none';
            } catch(e) {
                return false;
            }
        }
        
        function addElement(el, role, text, href = null) {
            try {
                if (idx >= maxItems) return false;
                if (!text && role !== 'input' && role !== 'textbox') return true;
                el.setAttribute('data-akira-index', String(idx));
                items.push({index: idx, role: role, text: text, href: href});
                idx++;
                return true;
            } catch(e) {
                return true;
            }
        }
        
        // 1. PRIORITY: YouTube video thumbnails (most common miss)
        try {
            document.querySelectorAll('ytd-video-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer').forEach(el => {
                if (!isVisible(el)) return;
                const titleEl = el.querySelector('#video-title, .title');
                const thumbnailEl = el.querySelector('a#thumbnail');
                if (titleEl && thumbnailEl) {
                    const text = getText(titleEl);
                    const href = thumbnailEl.href;
                    if (text) addElement(thumbnailEl, 'video', text, href);
                }
            });
        } catch(e) {}
        
        // 2. Address bar (omnibox) - critical for URL editing
        try {
            const omnibox = document.querySelector('input[type="text"][role="combobox"]') ||
                            document.querySelector('input.omnibox') ||
                            document.querySelector('#searchInput');
            if (omnibox && isVisible(omnibox)) {
                addElement(omnibox, 'addressbar', 'address bar', null);
            }
        } catch(e) {}
        
        // 3. All standard links
        try {
            document.querySelectorAll('a[href]').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el);
                if (text) addElement(el, 'link', text, el.href);
            });
        } catch(e) {}
        
        // 4. Buttons (explicit and implicit)
        try {
            document.querySelectorAll('button, [role="button"], [onclick], input[type="button"], input[type="submit"]').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el);
                addElement(el, 'button', text || 'button', null);
            });
        } catch(e) {}
        
        // 5. Form inputs
        try {
            document.querySelectorAll('input:not([type="hidden"]), textarea, select').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el) || el.type || 'input';
                addElement(el, 'input', text, null);
            });
        } catch(e) {}
        
        // 6. Video controls (play/pause buttons)
        try {
            document.querySelectorAll('video, [class*="play"], [class*="pause"], [aria-label*="play"], [aria-label*="pause"]').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el) || el.className.split(' ').find(c => c.includes('play') || c.includes('pause')) || 'media control';
                if (text) addElement(el, 'media', text, null);
            });
        } catch(e) {}
        
        // 7. Clickable divs with role or aria-label (common in modern web apps)
        try {
            document.querySelectorAll('[role="menuitem"], [role="tab"], [role="option"], [role="checkbox"], [role="radio"], [aria-label][onclick]').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el);
                if (text) addElement(el, el.getAttribute('role') || 'clickable', text, null);
            });
        } catch(e) {}
        
        return items;
    } catch(e) {
        console.error('Element extraction failed:', e);
        return [];
    }
    """
    
    try:
        elements = driver.execute_script(script, max_elements)
    except Exception as e:
        print(f"[EXTRACT] Script execution failed: {e}")
        return []
    
    if not elements:
        current_url = driver.current_url if hasattr(driver, 'current_url') else 'page'
        print(f"[EXTRACT] No elements found on {current_url[:50] if current_url else 'page'}")
        return []
    
    current_url = driver.current_url if hasattr(driver, 'current_url') else 'page'
    print(f"[EXTRACT] Found {len(elements)} elements on {current_url[:50] if current_url else 'page'}")
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
    Click element at index. Validates staleness, checks RISKY_KEYWORDS.
    No vision fallback here - that's handled by caller.
    """
    fresh = extract_interactive_elements(driver, max_elements=200)

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

    if "youtube.com" not in (browser.current_url or ""):
        return "This isn't a YouTube tab right now. Switch to YouTube first."

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

    # ── Group B: play video — DOM matching, NO vision ─────────────────────────

    if param.startswith("play video") or param.startswith("click video"):
        description = param.replace("play video", "").replace("click video", "").strip()
        time.sleep(0.8)
        elements = extract_interactive_elements(browser, max_elements=150)
        from claude_handler import find_element_index
        idx = find_element_index(elements, description)
        if idx is not None and idx < len(elements):
            clicked = browser.execute_script(f"""
                var el=document.querySelector('[data-akira-index="{idx}"]');
                if(el){{el.click();return true;}}return false;
            """)
            if clicked:
                return f"Playing {description}."
        return f"Couldn't find that video on the page."

    # ── Group C: common controls — DOM matching only ─────────────────────

    # Map common commands to DOM selectors (no vision needed)
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
    
    # Menu items that need menu to be opened first
    if param in {"ambient mode", "sleep timer", "quality", "playback speed menu"}:
        browser.execute_script("document.querySelector('.ytp-settings-button')?.click();")
        time.sleep(0.5)
        elements = extract_interactive_elements(browser, max_elements=150)
        from claude_handler import find_element_index
        idx = find_element_index(elements, param)
        if idx is not None:
            browser.execute_script(f"document.querySelector('[data-akira-index=\"{idx}\"]')?.click();")
            return "Done."
        return f"Couldn't find {param} in settings."
    
    if param in {"switch account", "sign out"}:
        browser.execute_script("document.querySelector('button#avatar-btn')?.click();")
        time.sleep(0.5)
        elements = extract_interactive_elements(browser, max_elements=150)
        from claude_handler import find_element_index
        idx = find_element_index(elements, param)
        if idx is not None:
            browser.execute_script(f"document.querySelector('[data-akira-index=\"{idx}\"]')?.click();")
            return "Done."
        return f"Couldn't find {param} in account menu."
    
    # If we get here, command not recognized
    return f"Don't know how to do '{param}' on YouTube."


# ── Netflix control ───────────────────────────────────────────────────────────

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


def _nfx_press_key(browser, key: str) -> bool:
    """Send a real keyboard shortcut to the page (Netflix player supports:
    space=play/pause, f=fullscreen, esc=exit, m=mute, s=skip intro,
    left/right arrows=seek 10s, up/down=volume)."""
    try:
        browser.find_element(By.TAG_NAME, "body").send_keys(key)
        return True
    except Exception:
        return False


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
    branches, which sensei.py's safety net ALWAYS gates behind a spoken yes."""
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

    Returns {'success': bool, 'message': str}.
    """
    print(f"[netflix_control] called with action={action!r}, parameter={parameter!r}")
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
    on_watch_page = "/watch/" in current_url

    # ── BROWSE / SEARCH actions (navigate, so they work from any page) ──────
    if action == "search":
        if not parameter:
            return {"success": False, "message": "Search needs a query."}
        browser.get("https://www.netflix.com/search?q=" + urllib.parse.quote(parameter))
        try:
            WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".title-card, [data-uia*='title-card']")))
        except Exception:
            pass
        time.sleep(0.5)
        cards = _nfx_collect_cards(browser)
        if not cards:
            return {"success": False, "message": f"No results found for {parameter}."}
        top = ", ".join(c["label"] for c in cards[:5])
        return {"success": True, "message": f"Found {len(cards)} results for {parameter}. Top results: {top}. Say play first result, or name one."}

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

    if action in ("play title", "open title") or (action == "play" and parameter):
        name = parameter
        if not name:
            return {"success": False, "message": "Tell me what title to play."}
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
        pick = _pick_card(cards, name)
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

    # ── PLAYER actions via internal API ─────────────────────────────────────
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
        if on_watch_page and _nfx_press_key(browser, " "):
            return {"success": True, "message": f"Toggled playback."}
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
        if _nfx_click_first(browser, [
            '[data-uia="control-fullscreen-enter"]',
            'button[aria-label="Full screen"]',
            'button[aria-label="Fullscreen"]',
        ]):
            return {"success": True, "message": "Fullscreen on."}
        # F key is Netflix's fullscreen shortcut and carries user activation
        if _nfx_press_key(browser, "f"):
            return {"success": True, "message": "Fullscreen on."}
        return {"success": False, "message": "Couldn't enter fullscreen."}

    if action == "exit fullscreen":
        _nfx_reveal_controls(browser)
        if _nfx_click_first(browser, [
            '[data-uia="control-fullscreen-exit"]',
            'button[aria-label="Exit full screen"]',
        ]):
            return {"success": True, "message": "Exited fullscreen."}
        if _nfx_press_key(browser, "\ue00c"):  # ESC
            return {"success": True, "message": "Exited fullscreen."}
        return {"success": False, "message": "Couldn't exit fullscreen."}

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
        # S is Netflix's skip-intro shortcut
        if _nfx_press_key(browser, "s"):
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


# ── Amazon control ────────────────────────────────────────────────────────────
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
    dict shape that _handle_click returns (so sensei.py's pause logic works).
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
        browser.get("https://www.amazon.in/s?k=" + urllib.parse.quote(parameter))
        try:
            WebDriverWait(browser, 10).until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div[data-component-type="s-search-result"]')))
        except Exception:
            pass
        time.sleep(0.5)
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
        # reuse the existing generic click pipeline (vision fallback included).
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
        # This branch is ONLY reachable after sensei.py's safety net got a
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
        # Category 2: reuse the generic click pipeline (with vision fallback)
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
        # This branch is ONLY reachable after sensei.py's safety net got a
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
#   GATED  -> merge/delete/close/create-PR go through sensei.py's safety net
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
    Gated by sensei.py safety net: create pull request, merge pull request,
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

    # ── Tier A: reads via unauthenticated REST API ───────────────────────────
    if action in ("search repos", "search repo", "search"):
        if not parameter:
            return {"success": False, "message": "Search needs a query."}
        ok, data = _gh_api("/search/repositories?per_page=10&q=" + urllib.parse.quote(parameter))
        if not ok:
            return {"success": False, "message": data}
        items = data.get("items", [])
        if not items:
            return {"success": False, "message": f"No repos found for {parameter}."}
        _gh_last_repos = [{"label": it["full_name"], "href": it["html_url"],
                           "desc": (it.get("description") or "")[:80],
                           "stars": it.get("stargazers_count", 0)} for it in items]
        browser.get("https://github.com/search?type=repositories&q=" + urllib.parse.quote(parameter))
        top = "; ".join(f"{c['label']} ({c['stars']} stars)" for c in _gh_last_repos[:4])
        return {"success": True, "message": f"Found {len(_gh_last_repos)} repos. Top: {top}. Say open first repo, or name one."}

    if action in ("open repo", "open repository", "open result"):
        if parameter and "/" in parameter and " " not in parameter.strip():
            full = parameter.strip().strip("/")
            ok, data = _gh_api(f"/repos/{full}")
            if not ok:
                return {"success": False, "message": data}
            browser.get(data["html_url"])
            return {"success": True, "message": f"Opened {data['full_name']}."}
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

    if action == "clone repo":
        # Interpreted as "give me the clone URL on the clipboard" — NOT a local
        # git clone (no git operations in scope). Windows clip.exe, no deps.
        if not repo:
            return {"success": False, "message": "Open a repo first."}
        url = f"https://github.com/{repo}.git"
        try:
            subprocess.run("clip", input=url.encode(), check=True, shell=True)
            return {"success": True, "message": f"Clone URL for {repo} copied to your clipboard."}
        except Exception:
            return {"success": True, "message": f"The clone URL is {url}"}

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

    # ── GATED actions (only reachable after sensei.py's confirmation gate) ──
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
    """Opens the requested site in Akira's tab if it's still blank/unused,
    otherwise in a NEW tab, separate from the user's existing tabs."""
    browser = get_browser(_last_browser_name)
    url = resolve_site_url(parameter.strip())

    # Reuse Akira's blank working tab instead of creating a duplicate.
    # _ensure_akira_tab eagerly creates an about:blank tab; if it's still
    # unused, navigate it directly rather than opening yet another tab.
    akira_tab = getattr(browser, "_akira_tab", None)
    if akira_tab and akira_tab in browser.window_handles:
        try:
            original_handle = browser.current_window_handle
        except Exception:
            original_handle = None
        try:
            browser.switch_to.window(akira_tab)
            current = browser.current_url or ""
            if current in ("", "about:blank") or not browser.title:
                browser.get(url)
                return f"Opened {parameter} in a new tab."
            # Akira tab has real content — restore focus, fall through to new tab
            if original_handle and original_handle in browser.window_handles:
                browser.switch_to.window(original_handle)
        except Exception:
            pass  # fall through to creating a genuinely new tab

    existing = set(browser.window_handles)
    browser.execute_cdp_cmd("Target.createTarget", {"url": url})
    for _ in range(10):
        new_handles = [h for h in browser.window_handles if h not in existing]
        if new_handles:
            browser.switch_to.window(new_handles[0])
            browser._akira_tab = new_handles[0]
            return f"Opened {parameter} in a new tab."
        time.sleep(0.3)
    return f"Tried to open {parameter} but couldn't confirm the new tab."


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
    browser.switch_to.window(browser._akira_tab)
    current_site = get_current_site(browser) if not explicit_web else None

    if current_site and current_site in SEARCH_URL_MAP:
        return _handle_site_search(f"{current_site}|{query_clean}")

    _navigate(f"https://www.google.com/search?q={urllib.parse.quote(query_clean if explicit_web else parameter)}")

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

    elements = extract_interactive_elements(browser, max_elements=200)
    
    # Debug: print first 5 element texts to see what we're getting
    if elements:
        print(f"[DEBUG] First 5 elements: {[el['text'][:40] for el in elements[:5]]}")
    
    from claude_handler import find_element_index
    index = find_element_index(elements, parameter)
    print(f"[CLICK] Matched index={index} for '{parameter}'")

    if index is None or index >= len(elements):
        print(f"[CLICK] DOM match failed, trying vision fallback")
        return "Done." if vision_click(browser, parameter) else "Couldn't find that on the page."

    target = elements[index]
    print(f"[CLICK] Target: [{target['role']}] '{target['text'][:50]}'")
    
    try:
        result = click_element(browser, index, expected_text=target["text"],
                               expected_href=target["href"], instruction=parameter)
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
    "scroll":            scroll,
    "new_tab":           new_tab,
    "open_site_tab":     open_site_tab,
    "list_tabs":         lambda _: list_open_tabs(),
    "switch_tab":        switch_tab,
    "close_tab":         close_tab,
    "click":             _handle_click,
    "youtube_control":   youtube_control,
    "netflix_control":   lambda p: netflix_control(p.split("|")[0], p.split("|")[1] if "|" in p else None),
    "amazon_control":    lambda p: amazon_control(p.split("|")[0], p.split("|")[1] if "|" in p else None),
    "flipkart_control":  lambda p: flipkart_control(p.split("|")[0], p.split("|")[1] if "|" in p else None),
    "github_control":    lambda p: github_control(p.split("|")[0], p.split("|", 1)[1] if "|" in p else None),
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
