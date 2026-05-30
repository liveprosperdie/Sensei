import os
import shutil
import datetime
import webbrowser
import subprocess
from PIL import ImageGrab
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

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

  
def execute(action, parameter):
    if action == "open_application":
        return open_application(parameter)
    if action == "open_url":
        webbrowser.open(parameter)
        return f"Opening {parameter}."
    if action == "web_search":
        webbrowser.open(f"https://www.google.com/search?q={parameter}")        
        return f"Searching for {parameter}."
    if action == "adjust_volume":
        return adjust_volume(parameter)
    if action == "close_application":
        return close_application(parameter)
    if action == "hibernate":
        return hibernate()
    if action == "lock_screen":
        return lock_screen()
    if action == "screenshot":
        return screenshot()
    return f"I don't know how to handle action: {action}"