"""
Windows system/settings control — everyday OS surfaces, split by risk tier.

TIER 1 (instant): settings pages, explorer folders, task manager, control
panel, wifi/bluetooth toggles, action center, calendar flyout, lock, and a
REAL performance query (psutil numbers, not "go read Task Manager yourself").

TIER 2 (confirmation-gated): temp cleanup, recycle bin, browser cache, disk
cleanup, shutdown/restart/sleep/hibernate/sign out. These are registered in
akira.DANGEROUS_ACTIONS so the EXISTING confirmation_required safety net
gates them — this module deliberately contains no confirmation logic of its
own, so there is exactly one confirmation mechanism in the codebase.

Every function returns the standard {'success': bool, 'message': str} the
executor's result handling already understands. 'speak' marks a message whose
numbers must be read aloud verbatim.
"""

import ctypes
import html
import os
import shutil
import subprocess
import tempfile
import time

import psutil

# CREATE_NO_WINDOW keeps helper processes from flashing a console at the user.
_NO_WINDOW = 0x08000000


def _run(args, timeout: float = 20.0, shell: bool = False) -> tuple[bool, str]:
    """Run a helper process quietly. Returns (ok, combined_output)."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, shell=shell,
                           timeout=timeout, creationflags=_NO_WINDOW)
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        return p.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


def _launch(target: str) -> bool:
    """Fire-and-forget a shell target (ms-settings: URI, folder, or exe).

    os.startfile is the right call for URI protocols and folders — subprocess
    cannot resolve 'ms-settings:' style targets.
    """
    try:
        os.startfile(target)
        return True
    except Exception as e:
        print(f"[SYS] launch {target!r} failed: {e}")
        return False


# ── Tier 1: settings pages & shell locations ──────────────────────────────────

# ms-settings: URIs are the documented, version-stable way into specific
# Settings pages. Poking the Settings UI with clicks would break every time
# Microsoft reshuffles the layout.
_SETTINGS_PAGES = {
    "settings": "", "wifi": "network-wifi", "wi-fi": "network-wifi",
    "wireless": "network-wifi", "network": "network-status",
    "internet": "network-status", "bluetooth": "bluetooth",
    "display": "display", "screen": "display", "brightness": "display",
    "sound": "sound", "audio": "sound", "volume": "sound",
    "notifications": "notifications", "storage": "storage",
    "windows update": "windowsupdate", "update": "windowsupdate",
    "updates": "windowsupdate",
    "apps": "appsfeatures", "apps and features": "appsfeatures",
    "apps & features": "appsfeatures", "installed apps": "appsfeatures",
    "battery": "batterysaver", "power": "powersleep", "privacy": "privacy",
    "personalization": "personalization", "themes": "themes",
    "default apps": "defaultapps", "mouse": "mousetouchpad",
    "keyboard": "easeofaccess-keyboard", "printers": "printers",
    "language": "regionlanguage", "date and time": "dateandtime",
    "about": "about",
}

_FOLDERS = {
    "downloads": "Downloads", "documents": "Documents", "desktop": "Desktop",
    "pictures": "Pictures", "music": "Music", "videos": "Videos",
}


def open_settings(parameter: str = "") -> dict:
    """Open the Settings app, or jump straight to a named page."""
    key = (parameter or "").strip().lower()
    page = _SETTINGS_PAGES.get(key)
    if page is None:
        # Tolerate "open wifi settings" phrasing that leaves noise words in.
        cleaned = key.replace("settings", "").replace("page", "").strip()
        page = _SETTINGS_PAGES.get(cleaned)
    if page is None:
        known = "Wi-Fi, Bluetooth, display, sound, notifications, storage, Windows Update, apps"
        return {"success": False,
                "message": f"I don't have a Settings page for '{parameter}'. I can open {known}."}
    ok = _launch(f"ms-settings:{page}")
    label = "Settings" if not page else (key or "Settings").title()
    return {"success": ok,
            "message": f"Opening {label}." if ok else "I couldn't open Settings."}


def open_folder(parameter: str = "") -> dict:
    """Open File Explorer, a known user folder, or an explicit path."""
    key = (parameter or "").strip().lower()
    if not key or key in ("file explorer", "explorer", "this pc"):
        return {"success": _launch("explorer.exe"),
                "message": "Opening File Explorer."}

    name = _FOLDERS.get(key) or _FOLDERS.get(key.rstrip("s")) or \
        _FOLDERS.get(key + "s")
    if name:
        path = os.path.join(os.path.expanduser("~"), name)
        if not os.path.isdir(path):
            return {"success": False, "message": f"I couldn't find your {name} folder."}
        return {"success": _launch(path), "message": f"Opening {name}."}

    expanded = os.path.expandvars(os.path.expanduser(parameter.strip()))
    if os.path.isdir(expanded):
        return {"success": _launch(expanded),
                "message": f"Opening {os.path.basename(expanded) or expanded}."}
    return {"success": False, "message": f"I couldn't find a folder called '{parameter}'."}


def open_system_tool(parameter: str = "") -> dict:
    """Task Manager, Control Panel, and the taskbar flyouts."""
    key = (parameter or "").strip().lower()

    if key in ("task manager", "taskmgr", "processes"):
        return {"success": _launch("taskmgr.exe"), "message": "Opening Task Manager."}
    if key in ("control panel", "controlpanel"):
        return {"success": _launch("control.exe"), "message": "Opening Control Panel."}
    if key in ("device manager", "devices"):
        return {"success": _launch("devmgmt.msc"), "message": "Opening Device Manager."}

    # Action center and the calendar flyout have no launchable target — they
    # are shell surfaces opened by their reserved hotkeys (Win+A / Win+N).
    if key in ("action center", "quick settings", "control center"):
        return {"success": _send_win_key("a"), "message": "Opening Action Center."}
    if key in ("notifications", "notification center", "notification centre"):
        return {"success": _send_win_key("n"), "message": "Opening notifications."}
    if key in ("calendar", "date", "clock", "time", "calendar flyout"):
        # Win+N opens notifications WITH the calendar in Windows 11.
        return {"success": _send_win_key("n"), "message": "Opening the calendar."}

    return {"success": False, "message": f"I don't know the tool '{parameter}'."}


def _send_win_key(letter: str) -> bool:
    """Press Win+<letter> for shell surfaces that have no launch target."""
    try:
        import pyautogui
        pyautogui.hotkey("win", letter)
        return True
    except Exception as e:
        print(f"[SYS] win+{letter} failed: {e}")
        return False


def lock_pc(parameter: str = "") -> dict:
    """Lock the workstation. Tier 1 — the user reverses it with their password."""
    try:
        ok = bool(ctypes.windll.user32.LockWorkStation())
        return {"success": ok,
                "message": "Locking your PC." if ok else "I couldn't lock the PC."}
    except Exception as e:
        return {"success": False, "message": f"I couldn't lock the PC: {e}"}


# ── Tier 1: radio toggles ─────────────────────────────────────────────────────

def _radio_powershell(kind: str, on: bool) -> tuple[bool, str]:
    """Flip a radio via WinRT Radio API.

    There is no supported plain-Win32 toggle, and netsh only handles adapters
    (which disables the whole NIC rather than the radio, and needs admin).
    """
    state = "On" if on else "Off"
    script = f"""
    [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime]|Out-Null
    [Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime]|Out-Null
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $task = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }}
    function Await($op, $t) {{
        $m = $task.MakeGenericMethod($t)
        $r = $m.Invoke($null, @($op)); $r.Wait(5000) | Out-Null; $r.Result
    }}
    Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
    $radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
    $target = $radios | Where-Object {{ $_.Kind -eq '{kind}' }}
    if (-not $target) {{ Write-Output 'NORADIO'; exit }}
    foreach ($r in $target) {{
        Await ($r.SetStateAsync('{state}')) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
    }}
    Write-Output 'OK'
    """
    ok, out = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", script], timeout=25.0)
    return (ok and "OK" in out), out


def _toggle_radio(kind: str, label: str, parameter: str) -> dict:
    p = (parameter or "").strip().lower()
    if p in ("on", "enable", "enabled", "turn on"):
        want = True
    elif p in ("off", "disable", "disabled", "turn off"):
        want = False
    else:
        return {"success": False, "message": f"Should I turn {label} on or off?"}

    ok, out = _radio_powershell(kind, want)
    if ok:
        return {"success": True, "message": f"{label} turned {'on' if want else 'off'}."}
    if "NORADIO" in out:
        return {"success": False, "message": f"I don't see a {label} radio on this PC."}
    print(f"[SYS] {label} radio API failed: {out[:200]}")

    # SECOND ATTEMPT via UI Automation on the real Settings switch. The WinRT
    # Radio API stays primary (it needs no window and no focus); UIA is the
    # fallback for the case where RequestAccessAsync is denied by policy.
    # This is a fallback rather than a parallel command so there is still one
    # entry point per concern.
    try:
        import native_ui
        res = native_ui.toggle_setting(label)
        if res.get("success"):
            return res
        print(f"[SYS] {label} UIA fallback failed: {res.get('message')}")
    except Exception as e:
        print(f"[SYS] {label} UIA fallback error: {e}")

    # Last resort: open the page so the request stays useful instead of
    # dead-ending — the user can flip the switch themselves in one tap.
    _launch(f"ms-settings:{'network-wifi' if kind == 'WiFi' else 'bluetooth'}")
    return {"success": False,
            "message": f"I couldn't toggle {label} directly, so I opened {label} settings for you."}


def toggle_wifi(parameter: str = "") -> dict:
    return _toggle_radio("WiFi", "Wi-Fi", parameter)


def toggle_bluetooth(parameter: str = "") -> dict:
    return _toggle_radio("Bluetooth", "Bluetooth", parameter)


# ── Tier 1: real performance query ────────────────────────────────────────────

def _gb(n: float) -> float:
    return round(n / (1024 ** 3), 1)


def performance_stats(parameter: str = "") -> dict:
    """Actual current CPU/RAM/disk numbers, spoken.

    Reads them programmatically instead of opening Task Manager and leaving
    the user to read the window themselves. 'speak' is set so the executor
    reads these exact numbers aloud rather than pre-baked LLM text.
    """
    # A 0.6s sampling window: cpu_percent() with no interval returns a
    # meaningless 0.0 on first call because it has no previous sample.
    cpu = psutil.cpu_percent(interval=0.6)
    mem = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage(os.path.abspath(os.sep))
    except Exception:
        disk = None

    want = (parameter or "").strip().lower()
    parts = []
    if not want or "cpu" in want or "processor" in want or "all" in want:
        parts.append(f"CPU is at {cpu:.0f} percent")
        try:
            freq = psutil.cpu_freq()
            if freq and freq.current:
                parts[-1] += f" across {psutil.cpu_count(logical=True)} threads"
        except Exception:
            pass
    if not want or any(k in want for k in ("ram", "memory", "mem", "all")):
        parts.append(f"memory {_gb(mem.used)} of {_gb(mem.total)} gigabytes used, "
                     f"{mem.percent:.0f} percent")
    if disk and (not want or any(k in want for k in ("disk", "drive", "storage", "all"))):
        parts.append(f"disk {_gb(disk.used)} of {_gb(disk.total)} gigabytes used, "
                     f"{disk.percent:.0f} percent full")

    if not parts:
        parts.append(f"CPU {cpu:.0f} percent, memory {mem.percent:.0f} percent")

    top = _top_processes(3)
    message = ", ".join(parts) + "."
    if top:
        message += " Heaviest right now: " + ", ".join(top) + "."

    # Visual companion to the spoken numbers. Failing to render must never
    # cost the user the spoken answer, so it is best-effort only.
    try:
        _show_perf_page(cpu, mem, disk, top)
    except Exception as e:
        print(f"[SYS] perf visual failed: {e}")

    print(f"[SYS] perf cpu={cpu} mem={mem.percent} "
          f"disk={disk.percent if disk else 'n/a'}")
    return {"success": True, "speak": True, "message": message,
            "cpu_percent": cpu, "memory_percent": mem.percent,
            "memory_used_gb": _gb(mem.used), "memory_total_gb": _gb(mem.total),
            "disk_percent": disk.percent if disk else None}


def _perf_page_path() -> str:
    return os.path.join(tempfile.gettempdir(), "akira_performance.html")


def _bar(label: str, pct: float, detail: str = "") -> str:
    """One labelled usage bar. Colour is a load threshold, not decoration, so
    a glance conveys the same thing the spoken summary does."""
    colour = "#3fb950" if pct < 60 else ("#e8b339" if pct < 85 else "#f85149")
    width = max(0.0, min(100.0, pct))
    return (f'<div class="row"><div class="head"><span>{html.escape(label)}</span>'
            f'<span class="pct">{pct:.0f}%</span></div>'
            f'<div class="track"><div class="fill" style="width:{width:.1f}%;'
            f'background:{colour}"></div></div>'
            + (f'<small>{html.escape(detail)}</small>' if detail else '')
            + '</div>')


def _show_perf_page(cpu: float, mem, disk, top: list[str]) -> None:
    """Render CPU/memory/disk bars to a temp HTML file and open it.

    Reuses the image picker's proven "write a local page, hand it to the shell"
    approach rather than adding a GUI toolkit dependency for three bars.
    """
    rows = [_bar("CPU", cpu, f"{psutil.cpu_count(logical=True) or '?'} threads"),
            _bar("Memory", mem.percent,
                 f"{_gb(mem.used)} of {_gb(mem.total)} GB used")]
    if disk:
        rows.append(_bar("Disk", disk.percent,
                         f"{_gb(disk.used)} of {_gb(disk.total)} GB used"))
    procs = ("<ul class='procs'>"
             + "".join(f"<li>{html.escape(t)}</li>" for t in top)
             + "</ul>") if top else ""

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>System performance</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; padding:28px; background:#111; color:#eee;
         font:15px/1.5 system-ui, sans-serif; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  p.when {{ margin:0 0 24px; color:#9a9a9a; font-size:13px; }}
  .row {{ margin-bottom:20px; max-width:560px; }}
  .head {{ display:flex; justify-content:space-between; font-weight:600;
          margin-bottom:6px; }}
  .pct {{ font-variant-numeric:tabular-nums; }}
  .track {{ height:14px; background:#1c1c1c; border:1px solid #2c2c2c;
           border-radius:7px; overflow:hidden; }}
  .fill {{ height:100%; border-radius:7px; }}
  small {{ display:block; margin-top:5px; color:#9a9a9a; }}
  h2 {{ font-size:14px; margin:28px 0 8px; color:#9a9a9a;
       text-transform:uppercase; letter-spacing:.06em; }}
  .procs {{ margin:0; padding-left:18px; color:#ccc; }}
</style></head><body>
<h1>System performance</h1>
<p class="when">Sampled {html.escape(time.strftime('%H:%M:%S'))}</p>
{''.join(rows)}
{f'<h2>Heaviest processes</h2>{procs}' if procs else ''}
</body></html>"""

    path = _perf_page_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    _launch(path)
    print(f"[SYS] perf visual at {path}")


def _top_processes(limit: int = 3) -> list[str]:
    """Top CPU consumers. Two-pass because the first cpu_percent() per process
    always reads 0.0 — a single pass would rank everything at zero."""
    try:
        procs = list(psutil.process_iter(["name"]))
        for p in procs:
            try:
                p.cpu_percent(None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(0.4)
        scored = []
        cores = psutil.cpu_count(logical=True) or 1
        for p in procs:
            try:
                pct = p.cpu_percent(None) / cores
                name = (p.info.get("name") or "").replace(".exe", "")
                if name and pct >= 1.0:
                    scored.append((pct, name))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        scored.sort(reverse=True)
        merged: dict[str, float] = {}
        for pct, name in scored:
            merged[name] = merged.get(name, 0.0) + pct
        ranked = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
        return [f"{n} at {v:.0f} percent" for n, v in ranked[:limit]]
    except Exception as e:
        print(f"[SYS] top processes failed: {e}")
        return []


# ── Tier 2: cleanup (confirmation-gated by akira's safety net) ───────────────

def _temp_targets() -> list[str]:
    """ONLY known-safe OS temp locations. Deliberately excludes every user
    document/media folder — a vague "clean my PC" must never reach them."""
    win = os.environ.get("SystemRoot", r"C:\Windows")
    cands = [os.environ.get("TEMP") or os.path.join(os.path.expanduser("~"),
             "AppData", "Local", "Temp"),
             os.path.join(win, "Temp"),
             os.path.join(win, "Prefetch")]
    return [p for p in cands if p and os.path.isdir(p)]


def _dir_size(path: str, cap: int = 500) -> tuple[int, int]:
    """(bytes, file_count), scanning at most `cap` files so a huge temp tree
    can't stall the voice loop."""
    total = files = 0
    try:
        for root, _dirs, names in os.walk(path):
            for n in names:
                try:
                    total += os.path.getsize(os.path.join(root, n))
                    files += 1
                except OSError:
                    continue
                if files >= cap:
                    return total, files
    except Exception:
        pass
    return total, files


def preview_temp_cleanup(parameter: str = "") -> dict:
    """What clear_temp_files WOULD delete. Used to build an honest
    confirmation message with real folders and a real size."""
    targets = _temp_targets()
    if not targets:
        return {"success": False, "message": "I couldn't find any temp folders."}
    total = files = 0
    lines = []
    for t in targets:
        b, f = _dir_size(t, cap=300)
        total += b
        files += f
        lines.append(f"{t} ({_gb(b)} GB, {f} files)")
    print(f"[SYS] temp preview: {lines}")
    return {"success": True, "speak": True, "targets": targets,
            "bytes": total, "files": files,
            "message": (f"I'd clear about {files} files ({_gb(total)} GB) "
                        f"from {len(targets)} temp folders.")}


def clear_temp_files(parameter: str = "") -> dict:
    """Non-destructive handoff: opens the user's Temp folder in File Explorer
    so the user can review and delete temp files themselves."""
    targets = _temp_targets()
    if not targets:
        return {"success": False, "message": "I couldn't find any temp folders."}
    if os.environ.get("AKIRA_HEADLESS_TEST") != "1":
        try:
            subprocess.Popen(["explorer.exe", os.path.normpath(targets[0])])
        except Exception as e:
            print(f"[SYS] open temp folder warning: {e}")
    return {
        "success": True,
        "speak": True,
        "handoff": True,
        "targets": targets,
        "message": (
            f"I don't delete files directly — I've opened your Temp folder ({targets[0]}) "
            f"in File Explorer. Now you can delete the temporary files yourself."
        ),
    }


def empty_recycle_bin(parameter: str = "") -> dict:
    """Non-destructive handoff: opens the Windows Recycle Bin in File Explorer
    so the user can review and empty it themselves."""
    if os.environ.get("AKIRA_HEADLESS_TEST") != "1":
        try:
            subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"])
        except Exception as e:
            print(f"[SYS] open recycle bin warning: {e}")
    return {
        "success": True,
        "speak": True,
        "handoff": True,
        "message": (
            "I don't empty the Recycle Bin directly — I've opened the Recycle Bin for you. "
            "Now you can delete the items yourself."
        ),
    }


def run_disk_cleanup(parameter: str = "") -> dict:
    """Launch the built-in cleanmgr rather than reimplementing its rules —
    Windows already knows what is safe to delete."""
    ok = _launch("cleanmgr.exe")
    return {"success": ok,
            "message": "Opening Disk Cleanup — pick the drive and it'll do the rest."
                       if ok else "I couldn't start Disk Cleanup."}


def clear_browser_cache(parameter: str = "") -> dict:
    """Clear cache for the browser Akira drives, via its own settings page.

    Deliberately does NOT delete profile files directly: a running browser
    holds them locked, and wiping the wrong profile directory would take
    logins and sessions with it. Opening the native dialog keeps the user in
    control of scope.
    """
    # Read the attribute off the module, not `from executor import ...` — the
    # latter binds a COPY at call time and would miss a later browser switch.
    import executor
    name = (parameter or getattr(executor, "_last_browser_name", None)
            or "chrome").strip().lower()
    pages = {
        "chrome": "chrome://settings/clearBrowserData",
        "edge": "edge://settings/clearBrowserData",
        "brave": "brave://settings/clearBrowserData",
        "firefox": "about:preferences#privacy",
    }
    url = pages.get(name)
    if not url:
        return {"success": False,
                "message": f"I don't know how to clear cache for '{name}'."}
    try:
        browser = executor.get_browser(name)
        browser.execute_script("window.open(arguments[0], '_blank');", url)
        return {"success": True,
                "message": f"Opened {name.title()}'s clear-data dialog — "
                           f"choose the range and confirm there."}
    except Exception as e:
        print(f"[SYS] browser cache page failed: {e}")
        return {"success": False,
                "message": f"I couldn't open {name.title()}'s clear-data page."}


# ── Tier 2: power state ───────────────────────────────────────────────────────

def hibernate_available() -> bool:
    """HiberFilePresent from SYSTEM_POWER_CAPABILITIES.

    Hibernate is disabled by default on many machines, so this is checked
    BEFORE claiming to hibernate — 'shutdown /h' fails silently otherwise.
    """
    try:
        # SYSTEM_POWER_CAPABILITIES is a large BOOLEAN-heavy struct; only the
        # HiberFilePresent byte (offset 6) is needed here.
        buf = ctypes.create_string_buffer(64)
        # SystemPowerCapabilities = 4
        rc = ctypes.windll.powrprof.CallNtPowerInformation(
            4, None, 0, buf, ctypes.sizeof(buf))
        if rc != 0:
            print(f"[SYS] CallNtPowerInformation rc={rc}")
            return False
        return bool(buf.raw[6])
    except Exception as e:
        print(f"[SYS] hibernate check failed: {e}")
        return False


def sleep_pc(parameter: str = "") -> dict:
    """Sleep via Application.SetSuspendState(Suspend).

    powrprof's SetSuspendState(bHibernate=FALSE) HIBERNATES anyway whenever
    hibernation is enabled, so it cannot be used for a real sleep. The
    WinForms call maps to the correct S3 transition.

    NOT run through _run(): SetSuspendState does not return until the machine
    WAKES UP again, so waiting on it always hit the subprocess timeout and
    reported "timed out" / FAILED even though the PC had genuinely slept —
    the log contradicted what the user saw. Spawned detached instead, so the
    outcome we report matches reality: success here means "suspend request
    issued", which is the last thing observable before the CPU stops.

    Hibernate is deliberately NOT disabled first. Turning it off to force S3
    would destroy the user's existing hibernate/fast-startup configuration as
    a side effect of a "sleep" command.
    """
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Windows.Forms; "
             "[System.Windows.Forms.Application]::SetSuspendState("
             "[System.Windows.Forms.PowerState]::Suspend, $false, $false)"],
            creationflags=_NO_WINDOW)
    except Exception as e:
        print(f"[SYS] sleep failed to launch: {e}")
        return {"success": False, "message": "I couldn't put the PC to sleep."}

    # Give the transition a moment to begin so a real launch failure (bad
    # assembly, blocked policy) still surfaces while we can speak.
    time.sleep(1.5)
    print("[SYS] sleep: suspend requested via SetSuspendState(Suspend)")
    return {"success": True, "message": "Going to sleep."}


def hibernate_pc(parameter: str = "") -> dict:
    """Non-destructive handoff for hibernate."""
    return {
        "success": True,
        "speak": True,
        "handoff": True,
        "message": (
            "I don't force power state transitions directly — open the Windows Start menu "
            "power options and now you can hibernate your PC yourself."
        ),
    }


def sign_out(parameter: str = "") -> dict:
    """Non-destructive handoff for sign out."""
    return {
        "success": True,
        "speak": True,
        "handoff": True,
        "message": (
            "I don't sign you out directly to prevent losing unsaved work — open the Start menu "
            "profile icon and now you can sign out yourself."
        ),
    }


def shutdown_pc(parameter: str = "") -> dict:
    """Non-destructive handoff for shutdown."""
    return {
        "success": True,
        "speak": True,
        "handoff": True,
        "message": (
            "I don't shut down your PC directly — press Alt+F4 on your desktop or open the "
            "Start menu power button, and now you can shut it down yourself."
        ),
    }


def restart_pc(parameter: str = "") -> dict:
    """Non-destructive handoff for restart."""
    return {
        "success": True,
        "speak": True,
        "handoff": True,
        "message": (
            "I don't restart your PC directly — press Alt+F4 on your desktop or open the "
            "Start menu power button, and now you can restart it yourself."
        ),
    }


# ── Dispatch ──────────────────────────────────────────────────────────────────

# Exported so executor's _ACTION_MAP and akira's DANGEROUS_ACTIONS stay in
# sync from ONE definition instead of three hand-maintained lists.
TIER1_ACTIONS = {
    "open_settings":      open_settings,
    "open_folder":        open_folder,
    "open_system_tool":   open_system_tool,
    "toggle_wifi":        toggle_wifi,
    "toggle_bluetooth":   toggle_bluetooth,
    "lock_pc":            lock_pc,
    "performance_stats":  performance_stats,
}

TIER2_ACTIONS = {
    "clear_temp_files":     clear_temp_files,
    "empty_recycle_bin":    empty_recycle_bin,
    "clear_browser_cache":  clear_browser_cache,
    "run_disk_cleanup":     run_disk_cleanup,
    "sleep_pc":             sleep_pc,
    "hibernate_pc":         hibernate_pc,
    "sign_out":             sign_out,
    "shutdown_pc":          shutdown_pc,
    "restart_pc":           restart_pc,
}

ACTIONS = {**TIER1_ACTIONS, **TIER2_ACTIONS,
           "preview_temp_cleanup": preview_temp_cleanup}
