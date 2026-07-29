"""
Native Windows UI control via UI Automation (accessibility tree).

WHY UIA AND NOT PIXELS: screen-coordinate/vision clicking was removed from
browser control because it acts on whatever window happens to own that pixel —
the same failure mode is worse here, since these are OS-level toggles. UIA
identifies controls by name/control-type in the accessibility tree, so a click
either lands on the named control or honestly fails.

SCOPE (deliberately narrow): the Settings app only. Arbitrary "click any button
in any native app" is failure-prone, so anything else is reported as
unsupported instead of half-attempted. Task Manager, Explorer, etc. resolve to
an honest "I can't click inside that yet" via `unsupported_reason`.

Every function returns the standard {'success': bool, 'message': str} the
executor already understands.
"""

import time

# pywinauto is Windows-only and drags in comtypes; importing it on any other
# platform (or when it isn't installed) must not take the whole assistant down,
# so it is probed once here and every entry point checks _UIA_ERROR first.
try:
    from pywinauto import Application
    _UIA_ERROR: str | None = None
except Exception as e:                                    # pragma: no cover
    Application = None                                    # type: ignore[assignment]
    _UIA_ERROR = str(e)


# ── Native-app intent detection (routing, not clicking) ───────────────────────

# Native apps that have no DOM at all. A "click X in Task Manager" instruction
# can NEVER resolve through the browser structural/content matcher, so click
# routing checks this first instead of letting it fail with a confusing
# "0 candidates found" from a browser-only selector set.
_NATIVE_APPS = {
    "task manager":  "Task Manager",
    "taskmgr":       "Task Manager",
    "settings":      "Settings",
    "control panel": "Control Panel",
    "file explorer": "File Explorer",
    "explorer":      "File Explorer",
    "device manager": "Device Manager",
    "notepad":       "Notepad",
    "registry editor": "Registry Editor",
}

# Only Settings is actually driveable this phase.
_SUPPORTED = {"Settings"}


def detect_native_target(instruction: str) -> str | None:
    """Which native app an instruction names, e.g. "...in Task Manager".

    Matches on an explicit "in/on/from <app>" mention rather than a bare
    keyword, so "open the settings page on this website" is not mistaken for
    the Settings app. Returns the canonical app name, or None for browser work.
    """
    text = (instruction or "").lower()
    for phrase, app in _NATIVE_APPS.items():
        for prep in (" in ", " on ", " from ", " in the ", " under "):
            if prep + phrase in text or text.endswith(prep.rstrip() + " " + phrase):
                return app
    return None


def is_supported(app: str) -> bool:
    return app in _SUPPORTED


def unsupported_reason(app: str, instruction: str = "") -> dict:
    """An honest refusal for a native app that isn't driveable yet.

    Explicitly NOT a silent failure and not a browser-matcher error: the user
    is told which app is involved and what they can do instead.
    """
    return {
        "success": False,
        "speak": True,
        "message": (f"I can't click inside {app} yet — I can only control the "
                    f"Settings app that way for now. I can open {app} for you, "
                    f"or you can click it yourself."),
    }


# ── Settings app control ──────────────────────────────────────────────────────

def _settings_window(timeout: float = 8.0):
    """Connect to a RUNNING Settings app and return its main window.

    Does not launch it — callers that need it open use system_control's
    open_settings first, keeping "launch an app" in exactly one place.
    """
    app = Application(backend="uia").connect(path="SystemSettings.exe",
                                             timeout=timeout)
    win = app.top_window()
    win.wait("visible", timeout=timeout)
    return win


# Canonical Settings toggles: spoken name -> (UIA control name, ms-settings page)
_TOGGLES = {
    "wifi":      ("Wi-Fi",     "ms-settings:network-wifi"),
    "wi-fi":     ("Wi-Fi",     "ms-settings:network-wifi"),
    "wireless":  ("Wi-Fi",     "ms-settings:network-wifi"),
    "bluetooth": ("Bluetooth", "ms-settings:bluetooth"),
    "airplane mode": ("Airplane mode", "ms-settings:network-airplanemode"),
    "flight mode":   ("Airplane mode", "ms-settings:network-airplanemode"),
}


def _find_toggle(win, name: str):
    """Locate a toggle by accessible name.

    Tries the exact control first, then falls back to scanning descendants,
    because Windows 11 nests these under varying containers between builds —
    a single rigid child_window path breaks on the next release.
    """
    try:
        ctrl = win.child_window(title=name, control_type="Button")
        if ctrl.exists(timeout=2.0):
            return ctrl
    except Exception:
        pass
    try:
        for ctrl in win.descendants(control_type="Button"):
            try:
                if (ctrl.window_text() or "").strip().lower() == name.lower():
                    if hasattr(ctrl, "get_toggle_state"):
                        return ctrl
            except Exception:
                continue
    except Exception:
        pass
    return None


def toggle_setting(parameter: str = "") -> dict:
    """Flip a Settings toggle (Wi-Fi/Bluetooth/Airplane mode) and VERIFY it.

    Reads toggle state before and after and only reports success when the
    state actually changed — clicking without verifying is how "done!" gets
    said about a click that landed on nothing.
    """
    if _UIA_ERROR:
        return {"success": False,
                "message": "Native UI control isn't available on this machine "
                           f"({_UIA_ERROR})."}

    want = (parameter or "").strip().lower()
    entry = next((v for k, v in _TOGGLES.items() if k in want), None)
    if not entry:
        return {"success": False,
                "message": "I can toggle Wi-Fi, Bluetooth, or Airplane mode in "
                           "Settings. I didn't catch which one you meant."}
    name, page = entry

    # The control only exists in the tree while its own page is showing.
    # _launch takes the raw ms-settings: URI; open_settings() expects friendly
    # keys like "wifi" and would reject these, so the URI goes direct.
    import system_control
    system_control._launch(page)

    win = None
    last: Exception | None = None
    for _ in range(3):
        try:
            win = _settings_window()
            break
        except Exception as e:
            last = e
            time.sleep(1.0)
    if win is None:
        print(f"[NATIVE] settings connect failed: {last}")
        return {"success": False,
                "message": "I couldn't attach to the Settings window."}

    ctrl = None
    for _ in range(4):                    # the page needs a moment to render
        ctrl = _find_toggle(win, name)
        if ctrl is not None:
            break
        time.sleep(0.8)
    if ctrl is None:
        print(f"[NATIVE] toggle {name!r} not found in Settings tree")
        return {"success": False,
                "message": f"I opened Settings but couldn't find the {name} "
                           f"switch to flip."}

    try:
        before = ctrl.get_toggle_state()
    except Exception as e:
        print(f"[NATIVE] read state failed: {e}")
        return {"success": False,
                "message": f"I found the {name} switch but couldn't read its state."}

    try:
        ctrl.toggle()
    except Exception as e:
        print(f"[NATIVE] toggle failed: {e}")
        return {"success": False, "message": f"I couldn't flip the {name} switch."}

    # VERIFY: poll for a real state change instead of trusting the click.
    after = before
    for _ in range(6):
        time.sleep(0.5)
        try:
            after = ctrl.get_toggle_state()
        except Exception:
            break
        if after != before:
            break

    print(f"[NATIVE] {name} toggle before={before} after={after}")
    if after == before:
        return {"success": False, "speak": True,
                "message": (f"I clicked the {name} switch but it's still "
                            f"{'on' if before == 1 else 'off'} — it may be "
                            f"blocked by a hardware switch or policy.")}
    return {"success": True, "speak": True,
            "message": f"{name} is now {'on' if after == 1 else 'off'}."}


def click_native(parameter: str = "") -> dict:
    """Click a named control in the Settings app by accessible name.

    Name-based, never coordinate-based. Anything outside Settings is refused
    by the caller's routing before reaching here.
    """
    if _UIA_ERROR:
        return {"success": False,
                "message": "Native UI control isn't available on this machine "
                           f"({_UIA_ERROR})."}
    target = (parameter or "").strip()
    if not target:
        return {"success": False, "message": "I didn't catch what to click."}

    try:
        win = _settings_window()
    except Exception as e:
        print(f"[NATIVE] settings connect failed: {e}")
        return {"success": False,
                "message": "Settings doesn't look open, so there was nothing to click."}

    low = target.lower()
    for ctrl in win.descendants():
        try:
            text = (ctrl.window_text() or "").strip()
            if not text:
                continue
            if low == text.lower() or low in text.lower():
                ctrl.click_input()
                print(f"[NATIVE] clicked {text!r} in Settings")
                return {"success": True,
                        "message": f"Clicked {text} in Settings."}
        except Exception:
            continue

    print(f"[NATIVE] no control named {target!r} in Settings")
    return {"success": False,
            "message": f"I couldn't find anything called '{target}' in Settings."}
