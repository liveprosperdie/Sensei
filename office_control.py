"""
Microsoft Office voice control via COM automation (word / excel / powerpoint),
plus Teams open/focus.

WHY COM: Word, Excel and PowerPoint all expose a documented, version-stable
Automation object model. Driving them with UI Automation or synthetic clicks
(as native_ui.py must do for the Settings app, which has no object model)
would break on every ribbon reshuffle and every language pack. So this module
never clicks anything — it talks to the applications directly.

TEAMS IS DIFFERENT AND DELIBERATELY SHALLOW: Teams (both the classic Electron
client and the new WebView2 client) ships NO COM object model — there is no
"Teams.Application" ProgID, no Automation type library, and no supported
scripting surface. Deep control is therefore impossible without unreliable
pixel/UIA clicking, which this codebase already refuses to promise. Teams gets
exactly two honest capabilities here: launch and focus. Anything beyond that is
reported as unsupported rather than faked.

Dispatch shape mirrors every other integration in this codebase
(docs_control / sheets_control / github_control):

    office_control("word",       "new")
    office_control("excel",      "read|Budget|B7")
    office_control("powerpoint", "next slide")
    office_control("teams",      "open")

Returns the standard {'success': bool, 'message': str} the executor already
understands. 'speak' marks a message whose content must be read aloud verbatim
(cell values — Akira must never paraphrase a number).

Destructive sub-actions (close without saving, save-as over an existing file)
are NOT gated here. They are declared in RISKY_OFFICE_PARAMS and gated by
sensei's existing confirmation_required safety net, so the codebase keeps
exactly ONE confirmation mechanism.
"""

import os

# pywin32 is Windows-only. Probing once at import keeps this module importable
# on any platform (and keeps `import executor` working in CI/sandbox) — every
# entry point checks _COM_ERROR before touching COM. Same guard shape as
# native_ui.py's pywinauto probe.
try:
    import win32com.client as _com
    _COM_ERROR: str | None = None
except Exception as e:                                        # pragma: no cover
    _com = None                                               # type: ignore[assignment]
    _COM_ERROR = str(e)


# Office file extensions per app, used to resolve a spoken document name to a
# real path on disk.
_EXTENSIONS = {
    "word":       (".docx", ".doc", ".rtf", ".txt"),
    "excel":      (".xlsx", ".xlsm", ".xls", ".csv"),
    "powerpoint": (".pptx", ".ppt"),
}

_APP_PROGID = {
    "word":       "Word.Application",
    "excel":      "Excel.Application",
    "powerpoint": "PowerPoint.Application",
}

_APP_LABEL = {"word": "Word", "excel": "Excel", "powerpoint": "PowerPoint"}


# ── COM plumbing ──────────────────────────────────────────────────────────────

def _app(kind: str, create: bool = True):
    """Return a running Office application object, or (None, message).

    GetActiveObject attaches to an ALREADY-OPEN instance so we act on the
    user's real session (their open documents, their unsaved edits) instead of
    silently spawning a second invisible copy. Dispatch is the fallback that
    starts one when nothing is running.
    """
    if _COM_ERROR:
        return None, ("Office control needs pywin32 on Windows — "
                      f"COM isn't available here ({_COM_ERROR}).")
    progid = _APP_PROGID[kind]
    try:
        return _com.GetActiveObject(progid), None
    except Exception:
        pass
    if not create:
        return None, f"{_APP_LABEL[kind]} isn't open."
    try:
        app = _com.Dispatch(progid)
        app.Visible = True
        return app, None
    except Exception as e:
        return None, (f"I couldn't start {_APP_LABEL[kind]} — "
                      f"it may not be installed ({e}).")


def _search_dirs() -> list[str]:
    """Where a spoken document name is looked for, most likely first."""
    home = os.path.expanduser("~")
    cands = [os.getcwd(), os.path.join(home, "Documents"),
             os.path.join(home, "Desktop"), os.path.join(home, "Downloads"),
             os.path.join(home, "OneDrive", "Documents"), home]
    seen, out = set(), []
    for d in cands:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def _resolve_path(ref: str, kind: str) -> tuple[str | None, str | None]:
    """Resolve a spoken name ("budget", "report.docx") or a path to a real file.

    Returns (path, error_message). Only ever returns files that actually exist —
    COM's Open() on a missing path raises an opaque -2147352567, which would
    reach the user as noise instead of "I couldn't find that document".
    """
    ref = (ref or "").strip().strip('"')
    if not ref:
        return None, "Which document?"

    direct = os.path.expandvars(os.path.expanduser(ref))
    if os.path.isfile(direct):
        return os.path.abspath(direct), None
    if os.path.isabs(direct) or os.sep in direct:
        return None, f"I couldn't find a file at '{ref}'."

    exts = _EXTENSIONS[kind]
    stem = os.path.splitext(ref)[0].lower()
    for d in _search_dirs():
        try:
            names = os.listdir(d)
        except OSError:
            continue
        # Exact stem match wins over a partial one, so "report" prefers
        # report.docx over report-final-draft-v2.docx.
        for want_exact in (True, False):
            for n in names:
                base, ext = os.path.splitext(n)
                if ext.lower() not in exts:
                    continue
                b = base.lower()
                if (b == stem) if want_exact else (stem in b):
                    p = os.path.join(d, n)
                    if os.path.isfile(p):
                        return os.path.abspath(p), None
    return None, f"I couldn't find a {_APP_LABEL[kind]} file called '{ref}'."


def _save_target(ref: str, kind: str) -> str:
    """Absolute path for a save-as target, defaulting folder and extension."""
    ref = (ref or "").strip().strip('"')
    p = os.path.expandvars(os.path.expanduser(ref))
    if not os.path.isabs(p):
        p = os.path.join(os.path.expanduser("~"), "Documents", p)
    if not os.path.splitext(p)[1]:
        p += _EXTENSIONS[kind][0]
    return os.path.abspath(p)


def _ok(msg: str, **extra) -> dict:
    return {"success": True, "message": msg, **extra}


def _err(msg: str) -> dict:
    return {"success": False, "message": msg}


def _fields(parameter: str | None, count: int) -> list[str]:
    """Split a |-delimited parameter into exactly `count` stripped fields."""
    parts = (parameter or "").split("|", count - 1) if count > 1 \
        else [(parameter or "")]
    parts = [p.strip() for p in parts]
    return parts + [""] * (count - len(parts))


# ── Word ──────────────────────────────────────────────────────────────────────

def _word(sub: str, parameter: str | None) -> dict:
    app, err = _app("word", create=sub != "close")
    if err:
        return _err(err)

    if sub == "open":
        return _ok("Word is open.")

    if sub == "new":
        try:
            doc = app.Documents.Add()
            doc.Activate()
            return _ok("New Word document ready.")
        except Exception as e:
            return _err(f"I couldn't create a document: {e}")

    if sub == "open document":
        path, e = _resolve_path(parameter, "word")
        if e:
            return _err(e)
        try:
            app.Documents.Open(path)
            return _ok(f"Opened {os.path.basename(path)}.")
        except Exception as ex:
            return _err(f"I couldn't open that document: {ex}")

    # Everything below needs an active document.
    try:
        doc = app.ActiveDocument
    except Exception:
        return _err("There's no document open in Word.")

    if sub in ("insert", "dictate"):
        text = (parameter or "").strip()
        if not text:
            return _err("What should I type?")
        try:
            # Collapse to the end of the current selection first, so dictating
            # never silently overwrites text the user has highlighted.
            sel = app.Selection
            sel.Collapse(0)          # wdCollapseEnd
            sel.TypeText(text)
            return _ok("Added that to the document.")
        except Exception as e:
            return _err(f"I couldn't type that: {e}")

    if sub == "save":
        try:
            if not doc.Path:
                return _err("This document has never been saved — "
                            "tell me a name and I'll save it.")
            doc.Save()
            return _ok(f"Saved {doc.Name}.")
        except Exception as e:
            return _err(f"I couldn't save it: {e}")

    if sub == "save as":
        if not (parameter or "").strip():
            return _err("What should I call it?")
        path = _save_target(parameter, "word")
        try:
            doc.SaveAs2(path)
        except Exception:
            try:
                doc.SaveAs(path)     # older Word has no SaveAs2
            except Exception as e:
                return _err(f"I couldn't save it there: {e}")
        return _ok(f"Saved as {os.path.basename(path)}.")

    if sub == "close":
        try:
            saved = bool(doc.Saved)
            name = doc.Name
            doc.Close(SaveChanges=-1 if not saved else 0)   # wdSaveChanges
            return _ok(f"Closed {name}." if saved
                       else f"Saved and closed {name}.")
        except Exception as e:
            return _err(f"I couldn't close it: {e}")

    if sub == "read":
        try:
            text = (doc.Content.Text or "").strip()
        except Exception as e:
            return _err(f"I couldn't read the document: {e}")
        if not text:
            return _ok("That document is empty.")
        snippet = text[:600] + ("..." if len(text) > 600 else "")
        return _ok(snippet, speak=True)

    return _err(f"I can't do '{sub}' in Word.")


# ── Excel ─────────────────────────────────────────────────────────────────────

def _excel(sub: str, parameter: str | None) -> dict:
    app, err = _app("excel", create=sub != "close")
    if err:
        return _err(err)

    if sub == "open":
        return _ok("Excel is open.")

    if sub == "new":
        try:
            app.Workbooks.Add()
            return _ok("New workbook ready.")
        except Exception as e:
            return _err(f"I couldn't create a workbook: {e}")

    if sub == "open workbook":
        path, e = _resolve_path(parameter, "excel")
        if e:
            return _err(e)
        try:
            app.Workbooks.Open(path)
            return _ok(f"Opened {os.path.basename(path)}.")
        except Exception as ex:
            return _err(f"I couldn't open that workbook: {ex}")

    try:
        wb = app.ActiveWorkbook
        if wb is None:
            raise AttributeError("no workbook")
    except Exception:
        return _err("There's no workbook open in Excel.")

    if sub == "read":
        # "read|workbook|range" or "read|range" — the workbook field is
        # optional so "what's in B7" works on whatever is already open.
        first, second = _fields(parameter, 2)
        ref = second or first
        if second and first:
            path, e = _resolve_path(first, "excel")
            if e:
                return _err(e)
            try:
                wb = app.Workbooks.Open(path)
            except Exception as ex:
                return _err(f"I couldn't open that workbook: {ex}")
        if not ref:
            return _err("Which cell or range?")
        return _read_range(wb, ref)

    if sub == "write":
        # "write|A1|value" or "write|value" (into the current selection).
        cell, value = _fields(parameter, 2)
        if not value:
            cell, value = "", cell
        if not value:
            return _err("What should I put in there?")
        try:
            sheet = wb.ActiveSheet
            target = sheet.Range(cell) if cell else app.Selection
            target.Value = _coerce(value)
            where = cell or "the selected cell"
            return _ok(f"Put {value} in {where}.")
        except Exception as e:
            return _err(f"I couldn't write to '{cell or 'the selection'}': {e}")

    if sub == "save":
        try:
            if not wb.Path:
                return _err("This workbook has never been saved — "
                            "tell me a name and I'll save it.")
            wb.Save()
            return _ok(f"Saved {wb.Name}.")
        except Exception as e:
            return _err(f"I couldn't save it: {e}")

    if sub == "save as":
        if not (parameter or "").strip():
            return _err("What should I call it?")
        path = _save_target(parameter, "excel")
        try:
            wb.SaveAs(path)
            return _ok(f"Saved as {os.path.basename(path)}.")
        except Exception as e:
            return _err(f"I couldn't save it there: {e}")

    if sub == "close":
        try:
            name = wb.Name
            saved = bool(wb.Saved)
            wb.Close(SaveChanges=True if not saved else False)
            return _ok(f"Closed {name}." if saved
                       else f"Saved and closed {name}.")
        except Exception as e:
            return _err(f"I couldn't close it: {e}")

    return _err(f"I can't do '{sub}' in Excel.")


def _coerce(value: str):
    """Numbers must land in Excel as numbers, not text, or every formula
    downstream of a dictated value silently breaks."""
    v = value.strip()
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return value


def _read_range(wb, ref: str) -> dict:
    """Read a cell or range and phrase it for speech.

    speak=True because a value read aloud must be the REAL number — the LLM
    must never restate or round it from its own text.
    """
    ref = ref.strip()
    # Accept "Sheet1!B7", "B7", or "B2:D5".
    sheet_name, _, cells = ref.rpartition("!")
    try:
        sheet = wb.Worksheets(sheet_name) if sheet_name else wb.ActiveSheet
    except Exception:
        return _err(f"I couldn't find a sheet called '{sheet_name}'.")
    try:
        rng = sheet.Range(cells or ref)
    except Exception:
        return _err(f"'{ref}' isn't a cell or range I can read.")

    try:
        count = rng.Count
    except Exception:
        count = 1

    try:
        if count == 1:
            val = rng.Value
            shown = "empty" if val in (None, "") else _fmt(val)
            return _ok(f"{rng.Address(False, False)} is {shown}.", speak=True)

        # Multi-cell: flatten, cap the spoken list so a huge range can't
        # monopolise the voice loop, and report the true total.
        raw = rng.Value
        flat = []
        for row in (raw if isinstance(raw, tuple) else [(raw,)]):
            cells_row = row if isinstance(row, tuple) else (row,)
            flat.extend(_fmt(c) for c in cells_row if c not in (None, ""))
        if not flat:
            return _ok(f"{ref} is empty.", speak=True)
        shown = flat[:12]
        msg = f"{ref} has {', '.join(shown)}"
        if len(flat) > len(shown):
            msg += f", and {len(flat) - len(shown)} more values"
        return _ok(msg + ".", speak=True)
    except Exception as e:
        return _err(f"I couldn't read {ref}: {e}")


def _fmt(v) -> str:
    """Speech-friendly value. Whole floats lose the '.0' — COM returns every
    Excel number as a float, and "42.0" read aloud sounds wrong."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# ── PowerPoint ────────────────────────────────────────────────────────────────

def _powerpoint(sub: str, parameter: str | None) -> dict:
    app, err = _app("powerpoint", create=sub != "close")
    if err:
        return _err(err)

    if sub == "open":
        return _ok("PowerPoint is open.")

    if sub == "new":
        try:
            app.Presentations.Add()
            return _ok("New presentation ready.")
        except Exception as e:
            return _err(f"I couldn't create a presentation: {e}")

    if sub == "open presentation":
        path, e = _resolve_path(parameter, "powerpoint")
        if e:
            return _err(e)
        try:
            app.Presentations.Open(path)
            return _ok(f"Opened {os.path.basename(path)}.")
        except Exception as ex:
            return _err(f"I couldn't open that presentation: {ex}")

    try:
        pres = app.ActivePresentation
    except Exception:
        return _err("There's no presentation open in PowerPoint.")

    if sub == "start slideshow":
        try:
            pres.SlideShowSettings.Run()
            return _ok("Starting the slideshow.")
        except Exception as e:
            return _err(f"I couldn't start the slideshow: {e}")

    if sub == "end slideshow":
        try:
            if pres.SlideShowWindow is None:
                raise AttributeError("not running")
            pres.SlideShowWindow.View.Exit()
            return _ok("Ended the slideshow.")
        except Exception:
            return _err("There's no slideshow running.")

    if sub in ("next slide", "previous slide", "go to slide"):
        return _navigate(app, pres, sub, parameter)

    if sub == "save":
        try:
            if not pres.Path:
                return _err("This presentation has never been saved — "
                            "tell me a name and I'll save it.")
            pres.Save()
            return _ok(f"Saved {pres.Name}.")
        except Exception as e:
            return _err(f"I couldn't save it: {e}")

    if sub == "save as":
        if not (parameter or "").strip():
            return _err("What should I call it?")
        path = _save_target(parameter, "powerpoint")
        try:
            pres.SaveAs(path)
            return _ok(f"Saved as {os.path.basename(path)}.")
        except Exception as e:
            return _err(f"I couldn't save it there: {e}")

    if sub == "close":
        try:
            name = pres.Name
            if not pres.Saved and pres.Path:
                pres.Save()
            pres.Close()
            return _ok(f"Closed {name}.")
        except Exception as e:
            return _err(f"I couldn't close it: {e}")

    return _err(f"I can't do '{sub}' in PowerPoint.")


def _navigate(app, pres, sub: str, parameter: str | None) -> dict:
    """Slide navigation. Presenting and editing are two DIFFERENT views in the
    object model, so the live slideshow window is driven when one exists and
    the edit window otherwise — one function, because to the user "next slide"
    is one command either way."""
    try:
        show = pres.SlideShowWindow
    except Exception:
        show = None

    if show is not None:
        try:
            view = show.View
            if sub == "next slide":
                view.Next()
                return _ok("Next slide.")
            if sub == "previous slide":
                view.Previous()
                return _ok("Previous slide.")
            n = _slide_number(parameter, pres)
            if n is None:
                return _err("Which slide number?")
            view.GotoSlide(n)
            return _ok(f"On slide {n}.")
        except Exception as e:
            return _err(f"I couldn't move slides: {e}")

    try:
        total = pres.Slides.Count
        current = app.ActiveWindow.View.Slide.SlideIndex
        if sub == "next slide":
            target = current + 1
            if target > total:
                return _err("That's the last slide.")
        elif sub == "previous slide":
            target = current - 1
            if target < 1:
                return _err("That's the first slide.")
        else:
            target = _slide_number(parameter, pres)
            if target is None:
                return _err("Which slide number?")
            if not 1 <= target <= total:
                return _err(f"There are only {total} slides.")
        app.ActiveWindow.View.GotoSlide(target)
        return _ok(f"On slide {target} of {total}.")
    except Exception as e:
        return _err(f"I couldn't move slides: {e}")


def _slide_number(parameter: str | None, pres) -> int | None:
    p = (parameter or "").strip().lower()
    if p in ("last", "final", "end"):
        try:
            return int(pres.Slides.Count)
        except Exception:
            return None
    if p in ("first", "start", "beginning"):
        return 1
    digits = "".join(c for c in p if c.isdigit())
    return int(digits) if digits else None


# ── Teams (open / focus only — no COM object model exists) ─────────────────────

# Verified before implementing: Microsoft ships no Automation/COM object model
# for either Teams client, so there is no supported way to send a message,
# join a meeting, or toggle mute from COM. Rather than fake depth with pixel
# clicking, Teams exposes launch + focus and says so out loud.
_TEAMS_TITLES = ("microsoft teams", "teams")


def _teams(sub: str, parameter: str | None) -> dict:
    if sub in ("open", "focus", "switch"):
        return _open_teams(focus_only=sub != "open")
    return _err("Teams has no automation interface, so I can only open it or "
                "bring it to the front — I can't drive it from here.")


def _focus_teams() -> bool:
    """Bring an already-running Teams window forward. Reuses pygetwindow, the
    same window layer executor's switch_window uses."""
    try:
        import pygetwindow as gw
    except Exception:
        return False
    try:
        for w in gw.getAllWindows():
            title = (w.title or "").strip().lower()
            if title and any(t in title for t in _TEAMS_TITLES):
                try:
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                except Exception:
                    pass
                return True
    except Exception as e:
        print(f"[OFFICE] teams focus failed: {e}")
    return False


def _open_teams(focus_only: bool = False) -> dict:
    if _focus_teams():
        return _ok("Teams is up front.")
    if focus_only:
        return _err("Teams doesn't look like it's running.")
    # msteams: is the registered protocol handler for both clients and is what
    # actually launches Teams whether it's the Store app or the classic
    # installer, so it beats guessing at an exe path.
    try:
        os.startfile("msteams:")
        return _ok("Opening Teams. I can open and focus it, "
                   "but I can't control it from inside.")
    except Exception as e:
        print(f"[OFFICE] msteams: launch failed: {e}")
    try:
        import executor
        res = executor.open_application("teams")
        if isinstance(res, str) and not res.lower().startswith("couldn't"):
            return _ok("Opening Teams.")
    except Exception as e:
        print(f"[OFFICE] teams exe launch failed: {e}")
    return _err("I couldn't open Teams — it may not be installed.")


# ── Dispatch ──────────────────────────────────────────────────────────────────

# Spoken phrasings normalised onto the canonical sub-actions above, so the
# handlers never have to re-guess wording.
_ALIASES = {
    "create": "new", "new document": "new", "new doc": "new",
    "new workbook": "new", "new spreadsheet": "new",
    "new presentation": "new", "new deck": "new",
    "open doc": "open document", "open file": "open document",
    "open spreadsheet": "open workbook", "open sheet": "open workbook",
    "open deck": "open presentation", "open ppt": "open presentation",
    "type": "insert", "write text": "insert", "insert text": "insert",
    "read cell": "read", "read range": "read", "get cell": "read",
    "enter": "write", "enter data": "write", "set cell": "write",
    "write cell": "write", "put": "write",
    "saveas": "save as", "save file as": "save as", "rename": "save as",
    "next": "next slide", "previous": "previous slide",
    "prev slide": "previous slide", "back slide": "previous slide",
    "goto slide": "go to slide", "slide": "go to slide",
    "present": "start slideshow", "presentation mode": "start slideshow",
    "slideshow": "start slideshow", "start presentation": "start slideshow",
    "exit slideshow": "end slideshow", "stop slideshow": "end slideshow",
    "close document": "close", "close workbook": "close",
    "close presentation": "close",
}

_HANDLERS = {"word": _word, "excel": _excel,
             "powerpoint": _powerpoint, "teams": _teams}

_APP_ALIASES = {
    "doc": "word", "docs": "word", "ms word": "word", "winword": "word",
    "spreadsheet": "excel", "sheet": "excel", "ms excel": "excel",
    "ppt": "powerpoint", "power point": "powerpoint",
    "slides": "powerpoint", "ms powerpoint": "powerpoint",
    "ms teams": "teams", "microsoft teams": "teams",
}

# Sub-actions that can lose work. Gated by sensei's existing
# confirmation_required safety net — this module holds NO confirmation logic,
# exactly like system_control's Tier 2.
RISKY_OFFICE_PARAMS = frozenset({"close", "save as"})


def office_control(action: str, parameter: str | None = None) -> dict:
    """Single entry point. action = app name; parameter = "sub|args...".

    Called as office_control|word|insert|Hello there from the action map, so
    the first parameter field is the sub-action and the rest are its arguments.
    """
    app = (action or "").strip().lower()
    app = _APP_ALIASES.get(app, app)
    handler = _HANDLERS.get(app)
    if not handler:
        return _err(f"I don't control '{action}'. I can do Word, Excel, "
                    "PowerPoint, and opening Teams.")

    sub, rest = _fields(parameter, 2)
    sub = sub.lower().replace("_", " ").strip()
    if not sub:
        sub = "open"
    sub = _ALIASES.get(sub, sub)
    print(f"[office_control] app={app!r} sub={sub!r} rest={rest!r}")
    return handler(sub, rest or None)
