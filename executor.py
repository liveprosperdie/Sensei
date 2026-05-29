import os
import shutil
import subprocess
import webbrowser

URI_MAP = {
    "settings": "ms-settings:",
    "calculator": "calculator:",
    "store": "ms-windows-store:",#
    "copilot": "ms-copilot:",
    "msedge":"microsoft-edge:",
    "edge":"microsoft-edge:",#
    "whatsapp": "whatsapp:",
    "paint":"ms-paint:",
    "chatgpt": "chatgpt:",
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

def open_application(parameter):
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


def execute(action, parameter):
    if action == "open_application":
        return open_application(parameter)
    if action == "open_url":
        webbrowser.open(parameter)
        return f"Opening {parameter}."
    if action == "web_search":
        webbrowser.open(f"https://www.google.com/search?q={parameter}")
        return f"Searching for {parameter}."
    return f"I don't know how to handle action: {action}"

