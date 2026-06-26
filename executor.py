import os
import json
import time
import shutil
import psutil
import winreg
import requests
import datetime
import webbrowser
import subprocess
import urllib.parse
import win32process
import pygetwindow as gw
from PIL import ImageGrab
from selenium import webdriver
from comtypes import CLSCTX_ALL
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions

URI_MAP = {
    "settings": "ms-settings:",
    "calculator": "calculator:",
    "store": "ms-windows-store:",#
    "copilot": "ms-copilot:",
    "msedge":"microsoft-edge:",
    "edge":"microsoft-edge:",#
    "whatsapp": "whatsapp:",
    "paint":"ms-paint:",
    "camera": "microsoft.windows.camera:",
    "chatgpt": "chatgpt:",
    "clock":"ms-clock:",
    "teams": "msteams:",#
    "xbox":  "xbox:",
    "notepad":"notepad"
}

_home = os.path.expanduser("~")

MANUAL_MAP = {
    "explorer": r"C:\Windows\explorer.exe",
    "files": r"C:\Windows\explorer.exe",
    "brave":      r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    "discord": os.path.join(_home, "AppData", "Local", "Discord", "app-1.0.9238", "discord.exe"),
    "vlc":        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    "obsidian":   os.path.join(_home, "AppData", "Local", "Programs", "Obsidian", "obsidian.exe"),
    "notion":     os.path.join(_home, "AppData", "Local", "Programs", "Notion", "notion.exe"),
    "winrar":     r"C:\Program Files (x86)\WinRAR\winrar.exe",
    "gitbash":    r"C:\Program Files\Git\git-bash.exe",
    "steam":      r"C:\Program Files (x86)\Steam\steam.exe",
    "capcut":     os.path.join(_home, "AppData", "Local", "CapCut", "Apps", "capcut.exe"),
    "filmora":    os.path.join(_home, "AppData", "Local", "Wondershare", "Wondershare Filmora", "15.5.25.19939", "filmora.exe"),
    "adobe":      r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
    "acrobat":    r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
    "protonvpn":  r"C:\Program Files\Proton\VPN\ProtonVPN.Launcher.exe",
    "vpn":        r"C:\Program Files\Proton\VPN\ProtonVPN.Launcher.exe",
    "chrome":     r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "firefox":    r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "githubapp":  os.path.join(_home, "AppData", "Local", "GitHubDesktop", "githubdesktop.exe"),
    "canva":      os.path.join(_home, "AppData", "Local", "Programs", "Canva", "canva.exe"),
    "word":       r"C:\Program Files\Microsoft Office\root\Office16\winword.exe",
    "excel":      r"C:\Program Files\Microsoft Office\root\Office16\excel.exe",
    "powerpoint": r"C:\Program Files\Microsoft Office\root\Office16\powerpnt.exe",
    "zoom":       os.path.join(_home, "AppData", "Roaming", "Zoom", "bin", "Zoom.exe"),
    "edge":       r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
}

WEB_MAP = {
    "youtube": "https://youtube.com",
    "claude": "https://claude.ai",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "instagram": "https://instagram.com",
    "pinterest": "https://pinterest.com",
    "facebook": "https://facebook.com",
    "twitter": "https://x.com",
    "weather": "https://weather.com",
    "calendar": "https://calendar.google.com",
    "x": "https://x.com"
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
    "makemytrip":  "https://www.makemytrip.com/hotels/",
    "ixigo":       "https://www.ixigo.com/hotels",
    "chatgpt":     "https://chatgpt.com/?q={}",
    "claude":      "https://claude.ai/new?q={}",
    "gemini":      "https://gemini.google.com/app?q={}",
    "perplexity":  "https://www.perplexity.ai/search?q={}",
    "stackoverflow": "https://stackoverflow.com/search?q={}",
    "wikipedia":   "https://en.wikipedia.org/w/index.php?search={}",
    "spotify":     "https://open.spotify.com/search/{}",
    "netflix":     "https://www.netflix.com/search?q={}",
}

WINDOW_TITLE_MAP = {
    "clock": "Clock",
    "calculator": "Calculator",
    "file explorer": "explorer",
    "photos": "Photos",
    "maps": "Maps",
    "calendar": "Calendar",
    "camera": "Camera",
    "mail": "Mail",
    "store": "Microsoft Store",
}

UWP_MAP = {
    "settings": "SystemSettings",
}

MUTE_MAP={
        "mute":1,
        "quiet":1,
        "silence":1,
        "shut it":1,
        "unmute":0,
        "speak up":0,
    }

BRIGHTNESS_MAP = {
    "max": 100,
    "full": 100,
    "minimum": 0,
    "min": 0,
    "off": 0,
    "half": 50,
    "medium": 50,
    "mid": 50,
    "low": 25,
    "high": 75,
}


_browsers = {}
_last_browser_name = None

BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

RISKY_KEYWORDS = [
    "buy", "purchase", "checkout", "pay", "payment", "subscribe",
    "submit", "send", "confirm order", "place order", "delete",
    "remove", "cancel subscription", "sign up", "register", "donate",
    "transfer", "withdraw", "discard", "archive", "block", "report",
    "unsubscribe", "forward"
]

SITE_DOMAINS = {
    "youtube.com": "youtube",
    "amazon.in": "amazon",
    "amazon.com": "amazon",
    "flipkart.com": "flipkart",
    "github.com": "github",
    "reddit.com": "reddit",
    "netflix.com": "netflix",
    "spotify.com": "spotify",
    "instagram.com": "instagram",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "pinterest.com": "pinterest",
    "stackoverflow.com": "stackoverflow",
    "wikipedia.org": "wikipedia",
}

def get_current_site(driver):
    try:
        from urllib.parse import urlparse
        domain = urlparse(driver.current_url).netloc.replace("www.", "")
        for key in SITE_DOMAINS:
            if key in domain:
                return SITE_DOMAINS[key]
    except:
        pass
    return None


def extract_interactive_elements(driver, max_elements=80):
    """
    Uses CDP accessibility tree for richer, more reliable element extraction.
    Falls back to DOM extraction if CDP fails.
    """
    try:
        # get full accessibility tree via CDP
        result = driver.execute_cdp_cmd("Accessibility.getFullAXTree", {})
        nodes = result.get("nodes", [])
        
        items = []
        idx = 0
        
        # roles we care about
        interactive_roles = {
            "button", "link", "menuitem", "option", "checkbox", "radio",
            "tab", "textbox", "searchbox", "combobox", "listbox",
            "menuitemcheckbox", "menuitemradio", "switch", "treeitem"
        }
        
        for node in nodes:
            if idx >= max_elements:
                break
                
            role = node.get("role", {}).get("value", "")
            if role not in interactive_roles:
                continue
            
            # get name from accessibility tree
            name = node.get("name", {}).get("value", "").strip()
            if not name:
                continue
            
            # get backend node id for DOM injection
            backend_id = node.get("backendDOMNodeId")
            if not backend_id:
                continue
            
            # inject data-akira-index onto the real DOM node
            try:
                driver.execute_cdp_cmd("DOM.setAttributeValue", {
                    "nodeId": backend_id,
                    "name": "data-akira-index",
                    "value": str(idx)
                })
            except Exception:
                # DOM.setAttributeValue needs nodeId not backendDOMNodeId — resolve it
                try:
                    resolve = driver.execute_cdp_cmd("DOM.resolveNode", {"backendNodeId": backend_id})
                    obj_id = resolve.get("object", {}).get("objectId")
                    if obj_id:
                        driver.execute_cdp_cmd("Runtime.callFunctionOn", {
                            "objectId": obj_id,
                            "functionDeclaration": f"function(){{this.setAttribute('data-akira-index','{idx}')}}",
                            "returnByValue": True
                        })
                except Exception:
                    pass
            
            # get href if link
            href = None
            if role == "link":
                try:
                    resolve = driver.execute_cdp_cmd("DOM.resolveNode", {"backendNodeId": backend_id})
                    obj_id = resolve.get("object", {}).get("objectId")
                    if obj_id:
                        href_result = driver.execute_cdp_cmd("Runtime.callFunctionOn", {
                            "objectId": obj_id,
                            "functionDeclaration": "function(){return this.href || null}",
                            "returnByValue": True
                        })
                        href = href_result.get("result", {}).get("value")
                except Exception:
                    pass
            
            items.append({
                "index": idx,
                "role": role,
                "text": name[:150],
                "href": href
            })
            idx += 1
        
        if items:
            print(f"[DEBUG] extract_interactive_elements (CDP) found {len(items)} elements")
            return items
            
    except Exception as e:
        print(f"[DEBUG] CDP accessibility failed, falling back to DOM: {e}")
    
    # DOM fallback
    script = """
    const items = [];
    const selector = 'a, button, input, textarea, select, [role="button"], [onclick]';
    const elements = document.querySelectorAll(selector);
    let idx = 0;
    for (const el of elements) {
        const rect = el.getBoundingClientRect();
        const visible = rect.width > 0 && rect.height > 0 &&
            window.getComputedStyle(el).visibility !== 'hidden' &&
            window.getComputedStyle(el).display !== 'none';
        if (!visible) continue;
        let text = (el.innerText || el.value || el.placeholder || 
                   el.getAttribute('aria-label') || el.getAttribute('title') || 
                   el.getAttribute('alt') || '');
        text = text.replace(/\\s+/g, ' ').trim().slice(0, 150);
        if (!text && el.tagName !== 'INPUT') continue;
        const isActionable = ['INPUT', 'TEXTAREA', 'BUTTON', 'SELECT'].includes(el.tagName);
        if (!el.href && !isActionable) continue;
        items.push({
            index: idx,
            role: el.tagName.toLowerCase(),
            text: text,
            href: el.href || null
        });
        el.setAttribute('data-akira-index', idx);
        idx++;
        if (idx >= arguments[0]) break;
    }
    return items;
    """
    elements = driver.execute_script(script, max_elements)
    print(f"[DEBUG] extract_interactive_elements (DOM fallback) found {len(elements)} elements")
    return elements


def click_element(driver, index, expected_text=None, expected_href=None, instruction=None):
    """
    Clicks the element at `index`. Re-extracts the DOM fresh to guard against
    staleness. If the element at that index no longer matches what was
    originally matched, re-runs the matching layer once (costs one Haiku call)
    instead of clicking the wrong thing.
    """
    fresh_elements = extract_interactive_elements(driver, max_elements=100)

    if index >= len(fresh_elements):
        return {"success": False, "reason": "index out of range after re-extraction"}

    current = fresh_elements[index]
    stale = (
        (expected_text is not None and current["text"] != expected_text) or
        (expected_href is not None and current["href"] != expected_href)
    )

    if stale and instruction:
        from claude_handler import find_element_index
        new_index = find_element_index(fresh_elements, instruction)
        if new_index is None or new_index >= len(fresh_elements):
            return {"success": False, "reason": "element not found after page changed"}
        index = new_index
        current = fresh_elements[index]
    elif stale:
        return {"success": False, "reason": "element changed, no instruction to re-match against"}

    text_lower = current["text"].lower()
    needs_confirmation = any(kw in text_lower for kw in RISKY_KEYWORDS)

    selector = f'[data-akira-index="{index}"]'
    matched_elements = driver.find_elements(By.CSS_SELECTOR, selector)
    if not matched_elements:
        return {"success": False, "reason": "element not found in DOM after extraction"}
    selenium_element = matched_elements[0]

    def _do_click(el=selenium_element):
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            driver.execute_script("arguments[0].click();", el)

    return {
        "success": True,
        "needs_confirmation": needs_confirmation,
        "element": current,
        "_execute": _do_click
    }


def _attach_cdp_browser(binary_path, port, driver_service):
    def _port_ready():
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return resp.status_code == 200
        except Exception:
            return False

    if not _port_ready():
        # Check if browser is already running without debug port
        binary_name = os.path.basename(binary_path).lower()
        already_running = False
        for p in psutil.process_iter(['name']):
            try:
                if p.info['name'] and p.info['name'].lower() == binary_name:
                    already_running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if already_running:
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", binary_name],
                capture_output=True
            )
            time.sleep(1.0)

        akira_profile_dir = os.path.join(os.environ['LOCALAPPDATA'], 'Sensei', 'AkiraChromeProfile')
        os.makedirs(akira_profile_dir, exist_ok=True)

        subprocess.Popen([
            binary_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={akira_profile_dir}",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--restore-last-session=false"
        ])

        for _ in range(40):
            if _port_ready():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(
                f"Browser at {binary_path} did not bind debug port {port} within 20 seconds"
            )

    options = Options()
    options.binary_location = binary_path
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    driver = webdriver.Chrome(service=driver_service, options=options)

    existing = set(driver.window_handles)
    if hasattr(driver, '_akira_tab') and driver._akira_tab in driver.window_handles:
        pass
    else:
        driver.execute_cdp_cmd('Target.createTarget', {'url': 'about:blank'})
        for _ in range(10):
            new_handles = [h for h in driver.window_handles if h not in existing]
            if new_handles:
                break
            time.sleep(0.3)
        driver._akira_tab = new_handles[0]

    driver.switch_to.window(driver._akira_tab)
    return driver


def _attach_cdp_edge(port):
    def _port_ready():
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return resp.status_code == 200
        except Exception:
            return False

    if not _port_ready():
        already_running = False
        for p in psutil.process_iter(['name']):
            try:
                if p.info['name'] and p.info['name'].lower() == "msedge.exe":
                    already_running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if already_running:
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", "msedge.exe"],
                capture_output=True
            )
            time.sleep(1.0)

        subprocess.Popen([
            EDGE_PATH,
            f"--remote-debugging-port={port}",
            "--profile-directory=Default",
            "--no-first-run",
            "--disable-session-crashed-bubble",
            "--restore-last-session=false"
        ])

        for _ in range(20):
            if _port_ready():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"Edge did not bind debug port {port} within 10 seconds")

    options = EdgeOptions()
    options.binary_location = EDGE_PATH
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    service = EdgeService(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=options)

    existing = set(driver.window_handles)
    if hasattr(driver, '_akira_tab') and driver._akira_tab in driver.window_handles:
        pass
    else:
        driver.execute_cdp_cmd('Target.createTarget', {'url': 'about:blank'})
        for _ in range(10):
            new_handles = [h for h in driver.window_handles if h not in existing]
            if new_handles:
                break
            time.sleep(0.3)
        driver._akira_tab = new_handles[0]

    driver.switch_to.window(driver._akira_tab)
    return driver

def _get_default_browser():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice") as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            print(f"[DEBUG] _get_default_browser raw ProgId: {prog_id}")
            if "brave" in prog_id: return "brave"
            if "chrome" in prog_id: return "chrome"
            if "firefox" in prog_id: return "firefox"
            if "edge" in prog_id: return "edge"
    except Exception as e:
        print(f"[DEBUG] _get_default_browser registry read failed: {e}")
    return "edge"


def get_browser(name=None, incognito=False):
    global _browsers
    if name is None:
        name = _get_default_browser()
    name = name.lower().strip()
    key = f"{name}_incognito" if incognito else name
    if key in _browsers:
        driver = _browsers[key]
        try:
            _ = driver.title  # checks session is alive
            # now validate the akira tab specifically
            if hasattr(driver, '_akira_tab') and driver._akira_tab not in driver.window_handles:
                # tab was closed — recreate it
                existing = set(driver.window_handles)
                driver.execute_cdp_cmd('Target.createTarget', {'url': 'about:blank'})
                for _ in range(10):
                    new_handles = [h for h in driver.window_handles if h not in existing]
                    if new_handles:
                        break
                    time.sleep(0.3)
                driver._akira_tab = new_handles[0]
                driver.switch_to.window(driver._akira_tab)
            return driver
        except:
            del _browsers[key]
    if name == "brave":
        if incognito:
            options = Options()
            options.binary_location = BRAVE_PATH
            options.add_argument("--incognito")
            service_path = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
            service = Service(service_path if os.path.exists(service_path) else ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        else:
            service_path = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
            service = Service(service_path if os.path.exists(service_path) else ChromeDriverManager().install())
            driver = _attach_cdp_browser(BRAVE_PATH, 9222, service)

    elif name == "chrome":
        if incognito:
            options = Options()
            options.binary_location = CHROME_PATH
            options.add_argument("--incognito")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        else:
            service = Service(ChromeDriverManager().install())
            driver = _attach_cdp_browser(CHROME_PATH, 9223, service)

    elif name == "firefox":
        options = FirefoxOptions()
        if incognito:
            options.add_argument("-private")
        service = FirefoxService(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=options)

    elif name == "edge":
        if incognito:
            options = EdgeOptions()
            options.binary_location = EDGE_PATH
            options.add_argument("--inprivate")
            service = EdgeService(EdgeChromiumDriverManager().install())
            driver = webdriver.Edge(service=service, options=options)
        else:
            driver = _attach_cdp_edge(9224)
    else:
        service = Service(ChromeDriverManager().install())
        driver = _attach_cdp_browser(CHROME_PATH, 9223, service)
    _browsers[key] = driver
    global _last_browser_name
    _last_browser_name = name
    return driver

def new_tab(parameter=None):
    browser_name = None
    if parameter and "|browser:" in parameter:
        parameter, browser_name = parameter.split("|browser:", 1)
        parameter = parameter.strip()
        browser_name = browser_name.strip()
    browser = get_browser(browser_name)
    existing = set(browser.window_handles)
    browser.execute_cdp_cmd('Target.createTarget', {'url': 'chrome://newtab'})
    for _ in range(10):
        new_handles = [h for h in browser.window_handles if h not in existing]
        if new_handles:
            break
        time.sleep(0.3)
    new_handle = new_handles[0]
    browser.switch_to.window(new_handle)
    # DO NOT update _akira_tab
    if parameter:
        query = urllib.parse.quote(parameter)
        browser.get(f"https://www.google.com/search?q={query}")
        return f"Searching {parameter} in a new tab."
    return "Opened a new tab."

def youtube_control(parameter):
    browser = get_browser(_last_browser_name)
    param = parameter.lower().strip()
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    try:
        WebDriverWait(browser, 8).until(
            EC.presence_of_element_located((By.TAG_NAME, "ytd-app"))
        )
    except Exception:
        pass
    
    # for visual/thumbnail descriptions, grab richer context
    if any(w in param for w in ["thumbnail", "face", "image", "picture", "guy", "man", "woman", "person"]):
        script = """
            const videos = document.querySelectorAll('ytd-rich-item-renderer, ytd-video-renderer');
            const data = [];
            let i = 0;
            for (const v of videos) {
                const title = v.querySelector('#video-title, #title')?.textContent?.trim() || '';
                const thumb = v.querySelector('img')?.getAttribute('alt') || '';
                const ch = v.querySelector('#channel-name, #text')?.textContent?.trim() || '';
                if (title) data.push({index: i, title, thumb, channel: ch});
                v.setAttribute('data-akira-index', i);
                i++;
            }
            return data;
        """
        try:
            videos = browser.execute_script(script)
            if videos:
                videos_text = "\n".join(f"{v['index']}: title=\"{v['title']}\" alt=\"{v['thumb']}\" channel=\"{v['channel']}\"" for v in videos)
                from claude_handler import find_element_index_from_text
                # fallback to regular find with richer text
                message = __import__('anthropic').Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")).messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=10,
                    system="Match the instruction to a video by index. Reply with ONLY the index number or NONE.",
                    messages=[{"role": "user", "content": f"Videos:\n{videos_text}\n\nInstruction: {param}"}]
                )
                result = message.content[0].text.strip()
                if result != "NONE":
                    try:
                        idx = int(result)
                        browser.execute_script(f"""
                            var els = document.querySelectorAll('[data-akira-index="{idx}"] a#thumbnail, [data-akira-index="{idx}"] a');
                            if (els.length) els[0].click();
                        """)
                        return "Playing that video."
                    except:
                        pass
        except Exception as e:
            print(f"[DEBUG] youtube visual match failed: {e}")

    # ── Group A: Pure JS ──────────────────────────────────────────────

    if param in ("play", "pause"):
        browser.execute_script("document.querySelector('video') && document.querySelector('video').click();")
        return "Done."

    if param == "skip ad":
        browser.execute_script("""
            var btn = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern');
            if (btn) btn.click();
        """)
        return "Ad skipped."

    if param.startswith("volume "):
        try:
            val = int(param.replace("volume ", "").replace("%", "").strip())
            val = max(0, min(100, val))
            browser.execute_script(f"document.querySelector('video').volume = {val/100};")
            return f"Video volume set to {val}%."
        except ValueError:
            return "Give me a number for volume."

    if param == "mute video":
        browser.execute_script("document.querySelector('video').muted = true;")
        return "Video muted."

    if param == "unmute video":
        browser.execute_script("document.querySelector('video').muted = false;")
        return "Video unmuted."

    if param in ("fullscreen", "full screen"):
        browser.execute_script("document.querySelector('.ytp-fullscreen-button')?.click();")
        return "Fullscreen."

    if param in ("theatre mode", "theater mode", "theatre", "theater"):
        browser.execute_script("document.querySelector('.ytp-size-button')?.click();")
        return "Theatre mode."

    if param in ("default view", "exit fullscreen", "exit theatre", "exit theater"):
        browser.execute_script("""
            var vid = document.querySelector('video');
            if (document.fullscreenElement) document.exitFullscreen();
            else document.querySelector('.ytp-size-button')?.click();
        """)
        return "Default view."

    if param.startswith("speed "):
        speeds = {"0.25":0.25,"0.5":0.5,"0.75":0.75,"normal":1,"1":1,"1.25":1.25,"1.5":1.5,"1.75":1.75,"2":2,"2x":2}
        val = param.replace("speed ", "").strip()
        rate = speeds.get(val)
        if rate:
            browser.execute_script(f"document.querySelector('video').playbackRate = {rate};")
            return f"Speed set to {val}."
        return "Valid speeds: 0.25, 0.5, 0.75, normal, 1.25, 1.5, 1.75, 2."

    if param in ("captions on", "subtitles on", "cc on"):
        browser.execute_script("document.querySelector('.ytp-subtitles-button')?.click();")
        return "Captions on."

    if param in ("captions off", "subtitles off", "cc off"):
        browser.execute_script("""
            var btn = document.querySelector('.ytp-subtitles-button');
            if (btn && btn.getAttribute('aria-pressed') === 'true') btn.click();
        """)
        return "Captions off."

    if param == "loop":
        browser.execute_script("document.querySelector('video').loop = !document.querySelector('video').loop;")
        return "Loop toggled."

    if param.startswith("seek "):
        try:
            seconds = int(param.replace("seek ", "").replace("s","").strip())
            browser.execute_script(f"document.querySelector('video').currentTime += {seconds};")
            return f"Seeked {seconds} seconds."
        except ValueError:
            return "Give me seconds to seek."

    if param == "like":
        browser.execute_script("""
            var btn = document.querySelector('button[aria-label*="like this video"], button[aria-label*="Like"]');
            if (btn) btn.click();
        """)
        return "Liked."

    if param == "dislike":
        browser.execute_script("""
            var btn = document.querySelector('button[aria-label*="dislike"], button[aria-label*="Dislike"]');
            if (btn) btn.click();
        """)
        return "Disliked."

    if param == "ambient mode":
        # open settings then click ambient mode toggle
        browser.execute_script("document.querySelector('.ytp-settings-button')?.click();")
        time.sleep(0.5)
        elements = extract_interactive_elements(browser, max_elements=60)
        from claude_handler import find_element_index
        idx = find_element_index(elements, "ambient mode")
        if idx is not None:
            sel = f'[data-akira-index="{idx}"]'
            els = browser.find_elements(By.CSS_SELECTOR, sel)
            if els: els[0].click()
        return "Ambient mode toggled."

    # ── Group B: Settings menu items ─────────────────────────────────

    if param in ("sleep timer", "set sleep timer"):
        browser.execute_script("document.querySelector('.ytp-settings-button')?.click();")
        time.sleep(0.5)
        elements = extract_interactive_elements(browser, max_elements=60)
        from claude_handler import find_element_index
        idx = find_element_index(elements, "sleep timer")
        if idx is not None:
            sel = f'[data-akira-index="{idx}"]'
            els = browser.find_elements(By.CSS_SELECTOR, sel)
            if els: els[0].click()
        return "Sleep timer menu opened."

    if param in ("quality", "change quality", "video quality"):
        browser.execute_script("document.querySelector('.ytp-settings-button')?.click();")
        time.sleep(0.5)
        elements = extract_interactive_elements(browser, max_elements=60)
        from claude_handler import find_element_index
        idx = find_element_index(elements, "quality")
        if idx is not None:
            sel = f'[data-akira-index="{idx}"]'
            els = browser.find_elements(By.CSS_SELECTOR, sel)
            if els: els[0].click()
        return "Quality menu opened."

    if param in ("playback speed menu", "speed menu"):
        browser.execute_script("document.querySelector('.ytp-settings-button')?.click();")
        time.sleep(0.5)
        elements = extract_interactive_elements(browser, max_elements=60)
        from claude_handler import find_element_index
        idx = find_element_index(elements, "playback speed")
        if idx is not None:
            sel = f'[data-akira-index="{idx}"]'
            els = browser.find_elements(By.CSS_SELECTOR, sel)
            if els: els[0].click()
        return "Playback speed menu opened."

    # ── Group C: Click-based ──────────────────────────────────────────

    click_targets = {
        "subscribe":        "subscribe button",
        "unsubscribe":      "unsubscribe button",
        "share":            "share button",
        "save":             "save to playlist button",
        "play next":        "next video button",
        "next video":       "next video button",
        "history":          "history in sidebar",
        "watch later":      "watch later in sidebar",
        "liked videos":     "liked videos in sidebar",
        "playlists":        "playlists in sidebar",
        "your channel":     "your channel in sidebar",
        "downloads":        "downloads in sidebar",
        "youtube studio":   "youtube studio menu item",
        "settings":         "settings menu item",
        "open comments":    "comments section",
        "show comments":    "comments section",
        "home":             "home in sidebar",
        "explore":          "explore in sidebar",
        "music":            "music filter chip",
        "movies":           "movies filter chip or sidebar",
        "news":             "news filter chip",
        "gaming":           "gaming filter chip",
        "live":             "live filter chip",
        "ask":              "ask button below video",
        "clips":            "clips button",
    }

    if param in click_targets:
        elements = extract_interactive_elements(browser, max_elements=100)
        from claude_handler import find_element_index
        idx = find_element_index(elements, click_targets[param])
        if idx is None:
            # open sidebar first for sidebar items then retry
            sidebar_items = {"history","watch later","liked videos","playlists","your channel","downloads","youtube studio","settings","home"}
            if param in sidebar_items:
                browser.execute_script("document.querySelector('#guide-button, button[aria-label=\'Guide\']')?.click();")
                time.sleep(0.8)
                elements = extract_interactive_elements(browser, max_elements=100)
                idx = find_element_index(elements, click_targets[param])
            if idx is None:
                print(f"[DEBUG] youtube_control: trying vision fallback for {param}")
                import datetime
                screenshot_path = os.path.join(_home, "Pictures", "Screenshots", f"akira_vision_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                from PIL import ImageGrab
                img = ImageGrab.grab()
                img.save(screenshot_path)
                from claude_handler import vision_match
                coords = vision_match(screenshot_path, click_targets[param])
                os.remove(screenshot_path)
                if coords is None:
                    return f"Couldn't find {param} on the page."
                x, y = coords
                browser.execute_script(f"""
                    var el = document.elementFromPoint({x}, {y});
                    if (el) el.click();
                """)
                return "Done."
        sel = f'[data-akira-index="{idx}"]'
        els = browser.find_elements(By.CSS_SELECTOR, sel)
        if els:
            els[0].click()
            return f"Done."
        return f"Couldn't click {param}."

    # ── Group D: Navigation ───────────────────────────────────────────

    if param == "go back":
        browser.back()
        return "Going back."

    if param == "go forward":
        browser.forward()
        return "Going forward."

    if param.startswith("go to channel "):
        channel = param.replace("go to channel ", "").strip()
        query = urllib.parse.quote(channel + " youtube channel")
        browser.execute_script(f"window.location.href='https://www.youtube.com/results?search_query={query}';")
        return f"Searching for {channel}'s channel."

    if param.startswith("search "):
        query = param.replace("search ", "").strip()
        encoded = urllib.parse.quote(query)
        browser.execute_script(f"window.location.href='https://www.youtube.com/results?search_query={encoded}';")
        return f"Searching {query} on YouTube."

    if param.startswith("play video ") or param.startswith("click video "):
        description = param.replace("play video ", "").replace("click video ", "").strip()
        elements = extract_interactive_elements(browser, max_elements=100)
        from claude_handler import find_element_index
        idx = find_element_index(elements, description)
        if idx is None:
            return "Couldn't find that video."
        sel = f'[data-akira-index="{idx}"]'
        els = browser.find_elements(By.CSS_SELECTOR, sel)
        if els:
            els[0].click()
            return f"Playing {description}."
        return "Couldn't click that video."

    # ── Group E: Account (confirmation handled by sensei.py) ─────────

    if param in ("switch account", "sign out", "manage premium", "premium benefits"):
        # open account menu first
        browser.execute_script("document.querySelector('button#avatar-btn, button[aria-label*=\"Account\"]')?.click();")
        time.sleep(0.5)
        elements = extract_interactive_elements(browser, max_elements=60)
        from claude_handler import find_element_index
        idx = find_element_index(elements, param)
        if idx is not None:
            sel = f'[data-akira-index="{idx}"]'
            els = browser.find_elements(By.CSS_SELECTOR, sel)
            if els: els[0].click()
        return f"Opened {param}."

    return f"I don't know that YouTube control: {param}"

def scroll(parameter):
    browser = get_browser(_last_browser_name)
    param = parameter.lower().strip()
    
    if param == "down":
        browser.execute_script("window.scrollBy(0, 500);")
    elif param == "up":
        browser.execute_script("window.scrollBy(0, -500);")
    elif param == "top":
        browser.execute_script("window.scrollTo(0, 0);")
    elif param == "bottom":
        browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    else:
        try:
            px = int(param)
            browser.execute_script(f"window.scrollBy(0, {px});")
        except ValueError:
            return "I don't understand that scroll direction."
    return f"Scrolled {parameter}."


def _open_single_app(parameter):
    param = parameter.lower().strip()
    ALIASES = {
        "microsoft word": "word",
        "microsoft excel": "excel",
        "microsoft powerpoint": "powerpoint",
        "microsoft store": "store",
        "microsoft teams": "teams",
        "google chrome": "chrome",
        "mozilla firefox": "firefox",
        "github desktop": "githubapp",
        "github": "github",
        "proton vpn": "protonvpn",
        "adobe acrobat": "acrobat",
        "adobe reader": "acrobat",
        "git bash": "gitbash",
    }
    param = ALIASES.get(param, param)
    if param in URI_MAP:
        try:
            os.startfile(URI_MAP[param])
            return f"Opening {parameter}."
        except Exception:
            return f"Couldn't open {parameter}."

    if param in WEB_MAP:
        webbrowser.open(WEB_MAP[param])
        return f"Opening {parameter} in your browser."

    if param in MANUAL_MAP:
        path = MANUAL_MAP[param]
        if os.path.exists(path):
            subprocess.Popen(path)
            return f"Opening {parameter}."
        else:
            return f"I couldn't find {parameter} on this PC."
    
    exe = shutil.which(param)
    if exe:
        subprocess.Popen(exe)
        return f"Opening {parameter}."
    try:
        os.startfile(f"{param}:")
        return f"Opening {parameter}."
    except:
        pass
    subprocess.Popen(["cmd", "/c", "start", "", parameter])
    return f"Trying to open {parameter}."


def open_application(parameter):
    apps = [p.strip() for p in parameter.split(",")]
    for app in apps:
        _open_single_app(app)
    return "Done."


def _close_single_app(parameter):
    param = parameter.lower().strip()

    try:
        import pygetwindow as gw
        title = WINDOW_TITLE_MAP.get(param, param.title())
        wins = gw.getWindowsWithTitle(title)
        if wins:
            wins[0].close()
            return f"Closed {parameter}."
    except Exception:
        pass

    if param in UWP_MAP:
        result = subprocess.run(["taskkill", "/F", "/IM", UWP_MAP[param] + ".exe"], capture_output=True)
        return f"Closed {parameter}." if result.returncode == 0 else f"Couldn't close {parameter}."

    if param in MANUAL_MAP:
        name = os.path.basename(MANUAL_MAP[param])
    else:
        name = param + ".exe"

    result = subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
    return f"Closed {parameter}." if result.returncode == 0 else f"Couldn't find {parameter} running."


def close_application(parameter):
    if parameter.strip().lower() == "all":
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'].lower() not in [
                    "explorer.exe", "sensei.py", "python.exe", "pythonw.exe",
                    "svchost.exe", "system", "registry", "smss.exe"
                ]:
                    proc.kill()
            except:
                pass
        return "Closed everything."
    apps = [p.strip() for p in parameter.split(",")]
    for app in apps:
        _close_single_app(app)
    return "Done."


def lock_screen():
    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "Locking your screen."


def adjust_volume(parameter):
    devices = AudioUtilities.GetSpeakers()
    volume = devices.EndpointVolume  
    parameter=parameter.lower().strip()
    if parameter.startswith("+") or parameter.startswith("-"):
        current = round(volume.GetMasterVolumeLevelScalar() * 100)
        new = max(0, min(100, current + int(parameter)))
        volume.SetMasterVolumeLevelScalar(new / 100.0, None)
        return f"Volume set to {new}%."
    if parameter in MUTE_MAP:
        volume.SetMute(MUTE_MAP[parameter],None)
        return f"Volume {'muted' if MUTE_MAP[parameter] else 'unmuted'}."   
    try:
        p=int(parameter)
        if p<0:
            p=0
        elif p>100:
            p=100
        vol=p/100.0
        volume.SetMasterVolumeLevelScalar(vol,None)
        return f"Volume set to {p}%."
    except ValueError:
        return f"I don't understand '{parameter}' as a volume level."


def hibernate():
    subprocess.Popen(["shutdown", "/h"])
    return "Hibernating. See you later."


def screenshot():
    filename = f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(_home, "Pictures", "Screenshots", filename)
    img = ImageGrab.grab()
    img.save(path)
    return f"Screenshot saved as {filename}."


def adjust_brightness(parameter):
    param = parameter.lower().strip()

    if param in BRIGHTNESS_MAP:
        new = BRIGHTNESS_MAP[param]
    elif param.startswith("+") or param.startswith("-"):
        try:
            get_cmd = "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"
            result = subprocess.run(["powershell", "-Command", get_cmd], capture_output=True, text=True)
            current = int(result.stdout.strip())
            new = max(0, min(100, current + int(param)))
        except:
            return "Couldn't read current brightness."
    else:
        try:
            new = max(0, min(100, int(param)))
        except ValueError:
            return f"I don't understand '{parameter}' as a brightness level."
    try:
        set_cmd = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {new})"
        result = subprocess.run(["powershell", "-Command", set_cmd], capture_output=True)
        if result.returncode != 0:
            return "Couldn't change brightness — WMI may not be supported on this display."
        return f"Brightness set to {new}%."
    except Exception as e:
        return f"Failed to set brightness: {e}"


def switch_window(parameter):
    if not parameter:
        return "Which window do you want to switch to?"
    param = parameter.lower().strip()
    for win in gw.getAllWindows():
        if param in win.title.lower() and win.title:
            try:
                win.activate()
            except:
                pass
            return f"Switched to {parameter}."
    for win in gw.getAllWindows():
        if not win.title:
            continue
        try:
            _, pid = win32process.GetWindowThreadProcessId(win._hWnd)
            proc = psutil.Process(pid)
            if param in proc.name().lower():
                try:
                    win.activate()
                except:
                    pass
                return f"Switched to {parameter}."
        except:
            continue
    return f"Couldn't find {parameter} window."


def maximize_window(parameter):
    if not parameter:
        return "Which window do you want to maximize?"
    param = parameter.lower().strip()   
    for win in gw.getAllWindows():
        if param in win.title.lower() and win.title:
            try:
                win.activate()
            except:
                pass
            win.maximize()
            return f"Maximized {parameter}."    
    for win in gw.getAllWindows():
        if not win.title:
            continue
        try:
            _, pid = win32process.GetWindowThreadProcessId(win._hWnd)
            proc = psutil.Process(pid)
            if param in proc.name().lower():
                try:
                    win.activate()
                except:
                    pass
                win.maximize()
                return f"Maximized {parameter}."
        except:
            continue
    return f"Couldn't find {parameter} window."


def minimize_window(parameter):
    if not parameter:
        return "Which window do you want to minimize?"
    param = parameter.lower().strip()   
    for win in gw.getAllWindows():
        if param in win.title.lower() and win.title:
            win.minimize()
            return f"Minimized {parameter}."   
    for win in gw.getAllWindows():
        if not win.title:
            continue
        try:
            _, pid = win32process.GetWindowThreadProcessId(win._hWnd)
            proc = psutil.Process(pid)
            if param in proc.name().lower():
                win.minimize()
                return f"Minimized {parameter}."
        except:
            continue
    return f"Couldn't find {parameter} window."


def shutdown():
    subprocess.Popen(["shutdown", "/s", "/t", "0", "/f"])
    return "Shutting down. Goodbye."


def restart():
    subprocess.Popen(["shutdown", "/r", "/t", "0", "/f"])
    return "Restarting. Be right back."


def execute(action, parameter):
    if action == "open_application":
        return open_application(parameter)
    if action == "open_url":
        if not parameter or not parameter.startswith(("https://", "http://")):
            return "That doesn't look like a valid URL."
        browser = get_browser()
        existing = set(browser.window_handles)
        browser.execute_cdp_cmd('Target.createTarget', {'url': parameter})
        for _ in range(10):
            new_handles = [h for h in browser.window_handles if h not in existing]
            if new_handles:
                break
            time.sleep(0.3)
        browser.switch_to.window(new_handles[0])
        return f"Opening {parameter}."
    if action == "fill":
        # parameter format: "description|text to type|submit" or "description|text to type"
        # submit is optional, if present hits Enter after typing
        if not parameter or "|" not in parameter:
            return "I need a field description and text to type."
        parts = parameter.split("|")
        instruction = parts[0].strip()
        text = parts[1].strip()
        should_submit = len(parts) > 2 and parts[2].strip().lower() == "submit"
        browser = get_browser(_last_browser_name)
        elements = extract_interactive_elements(browser, max_elements=100)
        from claude_handler import find_element_index
        index = find_element_index(elements, instruction)
        if index is None or index >= len(elements):
            return "I couldn't find that field on the page."
        selector = f'[data-akira-index="{index}"]'
        matched = browser.find_elements(By.CSS_SELECTOR, selector)
        if not matched:
            return "Couldn't locate that field in the DOM."
        el = matched[0]
        try:
            el.click()
            el.clear()
            el.send_keys(text)
            if should_submit:
                from selenium.webdriver.common.keys import Keys
                el.send_keys(Keys.RETURN)
        except Exception as e:
            return f"Couldn't type into that field: {e}"
        return f"Typed '{text}' into {instruction}." + (" Submitted." if should_submit else "")
    if action == "site_search":
        if not parameter or "|" not in parameter:
            return "I need a site and a query to search."
        site, query = parameter.split("|", 1)
        site = site.strip().lower()
        query = query.strip()
        url_template = SEARCH_URL_MAP.get(site)
        url = url_template.format(urllib.parse.quote(query)) if url_template else f"https://www.google.com/search?q={urllib.parse.quote(query)}+site:{site}.com"
        browser = get_browser(_last_browser_name)
        existing = set(browser.window_handles)
        browser.execute_cdp_cmd('Target.createTarget', {'url': url})
        for _ in range(10):
            new_handles = [h for h in browser.window_handles if h not in existing]
            if new_handles:
                break
            time.sleep(0.3)
        browser.switch_to.window(new_handles[0])
        return f"Searching {query} on {site}."
    if action == "web_search":
        print(f"[DEBUG] web_search called with action={action} parameter={parameter}")
        browser_name = None
        if parameter and "|browser:" in parameter:
            parts = parameter.split("|browser:")
            parameter = parts[0].strip()
            browser_name = parts[1].strip()

        # context-aware routing — if on a supported site, search there unless user said "on the web"
        explicit_web = any(w in parameter.lower() for w in ["on the web", "on google", "google it", "on web"])
        parameter_clean = parameter.lower().replace("on the web","").replace("on google","").replace("google it","").replace("on web","").strip()

        try:
            browser = get_browser(name=browser_name)
        except RuntimeError as e:
            print(f"[DEBUG] get_browser raised: {e}")
            return str(e)

        if not explicit_web:
            current_site = get_current_site(browser)
            if current_site and current_site in SEARCH_URL_MAP:
                print(f"[DEBUG] web_search: routing to site_search for {current_site}")
                return execute("site_search", f"{current_site}|{parameter_clean}")

        print(f"[DEBUG] browser_name={browser_name} query={parameter_clean}")
        query = urllib.parse.quote(parameter_clean if explicit_web else parameter)
        print(f"[DEBUG] got browser, all handles: {browser.window_handles}")
        print(f"[DEBUG] akira_tab: {browser._akira_tab}")
        print(f"[DEBUG] current handle before switch: {browser.current_window_handle}")
        browser.switch_to.window(browser._akira_tab)
        print(f"[DEBUG] navigating to: https://www.google.com/search?q={query}")
        browser.get(f"https://www.google.com/search?q={query}")
        print(f"[DEBUG] done, current url: {browser.current_url}")
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            reject_selectors = [
                "button[id*='reject']",
                "button[aria-label*='Reject']",
                "button[aria-label*='Accept all']",
                "form[action*='consent'] button",
            ]
            for selector in reject_selectors:
                try:
                    btn = WebDriverWait(browser, 2).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    btn.click()
                    print(f"[DEBUG] web_search: dismissed popup via selector: {selector}")
                    break
                except Exception:
                    continue
        except Exception as e:
            print(f"[DEBUG] web_search: popup dismiss failed silently: {e!r}")
        return f"Searching for {parameter}."
    if action == "bookmark_page":
        get_browser().execute_script("window.bookmarks = window.bookmarks || []; window.bookmarks.push(document.URL);")
        get_browser().execute_script("document.title = document.title;")
        get_browser().find_element(By.TAG_NAME, "body").send_keys("\ue009d")
        return "Bookmarked."
    if action == "new_tab":
        return new_tab(parameter)
    if action == "youtube_control":
        return youtube_control(parameter)
    if action == "adjust_volume":
        return adjust_volume(parameter)
    if action == "close_application":
        return close_application(parameter)
    if action == "hibernate":
        return hibernate()
    if action == "lock_screen":
        return lock_screen()
    if action == "adjust_brightness":
        return adjust_brightness(parameter)
    if action == "screenshot":
        return screenshot()
    if action == "switch_window":
        return switch_window(parameter)
    if action == "maximize_window":
        return maximize_window(parameter)
    if action == "minimize_window":
        return minimize_window(parameter)
    if action == "shutdown":
        return shutdown()
    if action == "restart":
        return restart()
    if action == "click":
        browser = get_browser(_last_browser_name)
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By as SeleniumBy
        try:
            WebDriverWait(browser, 5).until(
                EC.presence_of_element_located((SeleniumBy.TAG_NAME, "body"))
            )
        except Exception:
            pass
        elements = extract_interactive_elements(browser, max_elements=100)
        from claude_handler import find_element_index
        index = find_element_index(elements, parameter)
        print(f"[DEBUG] click: matched index={index} for instruction='{parameter}'")
        if index is None or index >= len(elements):
            # vision fallback
            print(f"[DEBUG] click: element not found, trying vision fallback")
            import datetime
            screenshot_path = os.path.join(_home, "Pictures", "Screenshots", f"akira_vision_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.save(screenshot_path)
            from claude_handler import vision_match
            coords = vision_match(screenshot_path, parameter)
            os.remove(screenshot_path)
            if coords is None:
                return "I couldn't find that on the page."
            x, y = coords
            browser.execute_script(f"""
                var el = document.elementFromPoint({x}, {y});
                if (el) el.click();
            """)
            print(f"[DEBUG] click: vision fallback clicked at ({x}, {y})")
            return f"Clicked it."
        target = elements[index]
        try:
            result = click_element(browser, index, expected_text=target["text"], expected_href=target["href"], instruction=parameter)
        except Exception as e:
            print(f"[DEBUG] click: EXCEPTION in click_element: {e!r}")
            return f"Couldn't click that: {e}"
        print(f"[DEBUG] click: click_element returned keys={list(result.keys()) if isinstance(result, dict) else result!r}")
        if not result["success"]:
            print(f"[DEBUG] click: returning failure")
            return f"Couldn't click that: {result['reason']}"
        if result["needs_confirmation"]:
            print(f"[DEBUG] click: needs confirmation, returning dict")
            return {"needs_click_confirmation": True, "element_text": result["element"]["text"], "_execute": result["_execute"], "retry_parameter": parameter}
        print(f"[DEBUG] click: calling _execute()")
        try:
            result["_execute"]()
        except Exception as e:
            print(f"[DEBUG] click: EXCEPTION in _execute(): {e!r}")
            return f"Couldn't click that: {e}"
        print(f"[DEBUG] click: _execute() done, returning success")
        return f"Clicked {result['element']['text']}."
    if action == "scroll":
        return scroll(parameter)
    return f"I don't know how to handle action: {action}"
