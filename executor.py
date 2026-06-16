import os
import time
import socket
import shutil
import psutil
import winreg
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
    "discord":    os.path.join(_home, "AppData", "Local", "Discord", "app-1.0.9238", "discord.exe"),
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

BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

def _get_default_browser():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice") as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
            if "brave" in prog_id: return "brave"
            if "chrome" in prog_id: return "chrome"
            if "firefox" in prog_id: return "firefox"
            if "edge" in prog_id: return "edge"
    except:
        pass
    return "edge"


def get_browser(name=None, incognito=False):
    global _browsers
    if name is None:
        name = _get_default_browser()
    name = name.lower().strip()
    key = f"{name}_incognito" if incognito else name
    if key in _browsers:
        try:
            _ = _browsers[key].title
            return _browsers[key]
        except:
            del _browsers[key]
    if name == "brave":
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', 9222))
        sock.close()
        if result != 0:
            subprocess.Popen([
                BRAVE_PATH,
                "--remote-debugging-port=9222",
                "--profile-directory=Default"
            ])
            time.sleep(3)
        options = Options()
        options.binary_location = BRAVE_PATH
        options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
        brave_driver = os.path.join(os.path.dirname(__file__), "chromedriver.exe")
        service = Service(brave_driver if os.path.exists(brave_driver) else ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        existing = set(driver.window_handles)
        # Check if we already have a live Akira tab
        if hasattr(driver, '_akira_tab') and driver._akira_tab in driver.window_handles:
            pass  # reuse it
        else:
            driver.execute_cdp_cmd('Target.createTarget', {'url': 'about:blank'})
            for _ in range(10):
                new_handles = [h for h in driver.window_handles if h not in existing]
                if new_handles:
                    break
                time.sleep(0.3)
            driver._akira_tab = new_handles[0]
        driver.switch_to.window(driver._akira_tab)
        def _ensure_akira_tab(browser):
            if hasattr(browser, '_akira_tab') and browser._akira_tab in browser.window_handles:
                browser.switch_to.window(browser._akira_tab)
                return
            # Tab was closed, create a new one
            existing = set(browser.window_handles)
            browser.execute_cdp_cmd('Target.createTarget', {'url': 'about:blank'})
            for _ in range(10):
                new_handles = [h for h in browser.window_handles if h not in existing]
                if new_handles:
                    break
                time.sleep(0.3)
            browser._akira_tab = new_handles[0]
            browser.switch_to.window(browser._akira_tab)
    elif name == "chrome":
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--new-window")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    elif name == "firefox":
        options = FirefoxOptions()
        if incognito:
            options.add_argument("-private")
        service = FirefoxService(GeckoDriverManager().install())
        driver = webdriver.Firefox(service=service, options=options)
    elif name == "edge":
        options = EdgeOptions()
        if incognito:
            options.add_argument("--inprivate")
        service = EdgeService(EdgeChromiumDriverManager().install())
        driver = webdriver.Edge(service=service, options=options)
    else:
        options = Options()
        options.add_argument("--start-maximized")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    _browsers[key] = driver
    return driver

def new_tab(parameter=None):
    browser = get_browser()
    existing = set(browser.window_handles)
    browser.execute_cdp_cmd('Target.createTarget', {'url': 'chrome://newtab'})
    for _ in range(10):
        new_handles = [h for h in browser.window_handles if h not in existing]
        if new_handles:
            break
        time.sleep(0.3)
    browser._akira_tab = new_handles[0]
    browser.switch_to.window(browser._akira_tab)
    if parameter:
        query = urllib.parse.quote(parameter)
        browser.get(f"https://www.google.com/search?q={query}")
        return f"Searching {parameter} in a new tab."
    return "Opened a new tab."

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
    subprocess.Popen(f"start {parameter}", shell=True)
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
        pass   


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
    if action == "web_search":
        query = urllib.parse.quote(parameter)
        browser = get_browser()
        browser.switch_to.window(browser._akira_tab)
        browser.get(f"https://www.google.com/search?q={query}")
        return f"Searching for {parameter}."
    if action == "bookmark_page":
        get_browser().execute_script("window.bookmarks = window.bookmarks || []; window.bookmarks.push(document.URL);")
        get_browser().execute_script("document.title = document.title;")
        get_browser().find_element(By.TAG_NAME, "body").send_keys("\ue009d")
        return "Bookmarked."
    if action == "new_tab":
        return new_tab(parameter)
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
    return f"I don't know how to handle action: {action}"