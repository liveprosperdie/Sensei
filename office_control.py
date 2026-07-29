"""Microsoft Office voice control via COM automation.

COM (win32com) is the right tool here, not UI Automation or clicking: Word,
Excel and PowerPoint all ship a documented object model, so we manipulate
documents directly instead of hunting for on-screen controls. That means no
dependence on window size, theme, focus or ribbon layout.

Teams is the deliberate exception — see teams_control().

Dispatchers follow the same "action|parameter" contract as every other
*_control module so executor's single _ACTION_MAP stays the only dispatch
mechanism. Destructive actions (close, save as) are confirmation-gated by
sensei's existing safety net via RISKY_OFFICE_PARAMS, and save-as additionally
refuses to clobber an existing file in code.
"""

from __future__ import annotations

import os

# Imported lazily inside _app() so this module still imports on non-Windows
# (the Linux sandbox) and so a missing pywin32 degrades to a spoken message
# rather than an import crash at startup.
_COM_ERROR: str | None = None

_PROG_IDS = {
    "word":       "Word.Application",
    "excel":      "Excel.Application",
    "powerpoint": "PowerPoint.Application",
}

# Where a bare document name gets resolved from, in order.
_SEARCH_DIRS = ("Documents", "Desktop", "Downloads", "OneDrive/Documents")

_EXTS = {
    "word":       (".docx", ".doc", ".rtf", ".txt"),
    "excel":      (".xlsx", ".xlsm", ".xls", ".csv"),
    "powerpoint": (".pptx", ".ppt"),
}


# ── COM plumbing ──────────────────────────────────────────────────────────────

def _com_ready() -> tuple[bool, str]:
    """Initialise COM for THIS thread.

    Required because actions run on a worker thread, not the main thread —
    without CoInitialize every Dispatch here would fail with
    "CoInitialize has not been called".
    """
    try:
        import pythoncom
        try:
            pythoncom.CoInitialize()
        except Exception:
            # Already initialised on this thread — harmless.
            pass
        return True, ""
    except Exception as e:
        return False, str(e)


def _app(kind: str, visible: bool = True):
    """Attach to a running Office app or start one.

    Dispatch() reuses the existing instance for these ProgIDs, so this will not
    strand a second hidden copy of Word holding the user's file open.
    """
    ok, err = _com_ready()
    if not ok:
        raise RuntimeError(f"COM unavailable: {err}")
    import win32com.client
    app = win32com.client.Dispatch(_PROG_IDS[kind])
    if visible:
        try:
            app.Visible = True
        except Exception:
            # PowerPoint refuses Visible=False and some versions throw on set;
            # a non-settable Visible is not a reason to abort the real work.
            pass
    return app


def _resolve(name: str, kind: str) -> str | None:
    """Turn a spoken document name into a real path.

    Accepts a full path, or a bare//extension-less name to look up under the
    usual user folders. Returns None when nothing matches so the caller can say
    so instead of letting COM raise a bare "file not found".
    """
    name = (name or "").strip().strip('"')
    if not name:
        return None
    if os.path.isabs(name) and os.path.isfile(name):
        return name

    exts = _EXTS[kind]
    target = name.lower()
    home = os.path.expanduser("~")
    roots = [os.path.join(home, d) for d in _SEARCH_DIRS]

    exact_wanted = os.path.splitext(target)[1] in exts
    fallback = None
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            entries = os.listdir(root)
        except Exception:
            continue
        for entry in entries:
            low = entry.lower()
            if not low.endswith(exts):
                continue
            full = os.path.join(root, entry)
            if not os.path.isfile(full):
                continue
            if low == target or (not exact_wanted and os.path.splitext(low)[0] == target):
                return full
            # Loose contains-match is a last resort only, so "report" still
            # finds "Q3 report.docx" without beating an exact filename match.
            if fallback is None and target in low:
                fallback = full
    return fallback


def _fail(msg: str) -> dict:
    return {"success": False, "message": msg}


def _ok(msg: str, speak: bool = False) -> dict:
    return {"success": True, "speak": speak, "message": msg}


def _norm(action: str) -> str:
    return (action or "").strip().lower().replace("_", " ")


# ── Word ──────────────────────────────────────────────────────────────────────

def word_control(action: str, parameter: str | None = None) -> dict:
    act = _norm(action)
    try:
        if act in ("open", "open word", "launch"):
            _app("word")
            return _ok("Word is open.")

        if act in ("new", "new document", "create", "create document"):
            app = _app("word")
            app.Documents.Add()
            return _ok("New document ready.")

        if act in ("open document", "open file"):
            if not parameter:
                return _fail("Which document should I open?")
            path = _resolve(parameter, "word")
            if not path:
                return _fail(f"I couldn't find a Word document called {parameter}.")
            _app("word").Documents.Open(path)
            return _ok(f"Opened {os.path.basename(path)}.")

        if act in ("type", "insert", "insert text", "dictate", "write"):
            if not parameter:
                return _fail("What should I type?")
            app = _app("word")
            if app.Documents.Count == 0:
                app.Documents.Add()
            # TypeText inserts at the cursor, matching what dictation should do,
            # and keeps the user's existing content intact.
            app.Selection.TypeText(parameter)
            return _ok("Typed that in.")

        if act == "save":
            app = _app("word")
            if app.Documents.Count == 0:
                return _fail("There's no document open to save.")
            doc = app.ActiveDocument
            if not doc.Path:
                return _fail("This document has never been saved. Tell me a name "
                             "and I'll save it, for example: save as report.")
            doc.Save()
            return _ok(f"Saved {doc.Name}.")

        if act in ("save as", "saveas"):
            if not parameter:
                return _fail("What name should I save it as?")
            app = _app("word")
            if app.Documents.Count == 0:
                return _fail("There's no document open to save.")
            path = _target_path(parameter, ".docx")
            if os.path.exists(path):
                # In-code clobber guard: the spoken confirmation only asked
                # about saving, not about destroying a different file.
                return _fail(f"{os.path.basename(path)} already exists. "
                             f"Pick another name, or say overwrite {parameter}.")
            app.ActiveDocument.SaveAs2(path)
            return _ok(f"Saved as {os.path.basename(path)}.")

        if act in ("overwrite", "save as overwrite"):
            if not parameter:
                return _fail("Which file should I overwrite?")
            app = _app("word")
            if app.Documents.Count == 0:
                return _fail("There's no document open to save.")
            app.ActiveDocument.SaveAs2(_target_path(parameter, ".docx"))
            return _ok(f"Overwrote {parameter}.")

        if act in ("close", "close document"):
            app = _app("word")
            if app.Documents.Count == 0:
                return _fail("No document is open.")
            doc = app.ActiveDocument
            name = doc.Name
            saved = bool(doc.Path)          # must be read BEFORE Close
            if saved:
                # -1 = wdSaveChanges: never silently discard the user's work.
                doc.Close(-1)
                return _ok(f"Closed {name}.")
            # No filename yet, so there is nothing to save it into. Refuse
            # rather than destroy unsaved work behind a vague "close".
            return _fail(f"{name} has never been saved, so closing it would lose "
                         f"the work. Say save as, then a name — or say close "
                         f"without saving if you really want to discard it.")

        if act in ("close without saving", "discard", "close discard"):
            app = _app("word")
            if app.Documents.Count == 0:
                return _fail("No document is open.")
            name = app.ActiveDocument.Name
            app.ActiveDocument.Close(0)          # 0 = wdDoNotSaveChanges
            return _ok(f"Closed {name} without saving.")

        if act in ("quit", "quit word", "close word"):
            _app("word", visible=False).Quit(-1)
            return _ok("Word closed.")

        return _fail(f"Unknown Word action: {action}")

    except Exception as e:
        print(f"[OFFICE] word {act!r} failed: {e}")
        return _fail(f"Word wouldn't do that: {_clean(e)}")


def _target_path(name: str, default_ext: str) -> str:
    """Absolute save path for a spoken name, defaulting to Documents."""
    name = name.strip().strip('"')
    if not os.path.splitext(name)[1]:
        name += default_ext
    if os.path.isabs(name):
        return name
    return os.path.join(os.path.expanduser("~"), "Documents", name)


def _clean(e: Exception) -> str:
    """Trim COM's noisy multi-part errors down to something speakable."""
    msg = str(e)
    if "', '" in msg:
        parts = [p.strip(" '()") for p in msg.split("', '")]
        msg = next((p for p in parts if p and not p.startswith("0x")
                    and "None" not in p), msg)
    return msg[:120]


# ── Excel ─────────────────────────────────────────────────────────────────────

def excel_control(action: str, parameter: str | None = None) -> dict:
    act = _norm(action)
    try:
        if act in ("open", "open excel", "launch"):
            _app("excel")
            return _ok("Excel is open.")

        if act in ("new", "new workbook", "create", "create workbook"):
            _app("excel").Workbooks.Add()
            return _ok("New workbook ready.")

        if act in ("open workbook", "open file", "open spreadsheet"):
            if not parameter:
                return _fail("Which workbook should I open?")
            path = _resolve(parameter, "excel")
            if not path:
                return _fail(f"I couldn't find a spreadsheet called {parameter}.")
            _app("excel").Workbooks.Open(path)
            return _ok(f"Opened {os.path.basename(path)}.")

        if act in ("read cell", "read", "read range", "get cell", "what is cell"):
            if not parameter:
                return _fail("Which cell should I read?")
            app = _app("excel")
            if app.Workbooks.Count == 0:
                return _fail("No workbook is open.")
            sheet, ref = _split_ref(app, parameter)
            if sheet is None:
                return _fail(f"I couldn't find sheet {parameter.split('!')[0]}.")
            values = _read_ref(sheet, ref)
            if values is None:
                return _fail(f"{ref} doesn't look like a cell or range.")
            if not values:
                return _ok(f"{ref} is empty.", speak=True)
            if len(values) == 1:
                return _ok(f"{ref} is {values[0]}.", speak=True)
            return _ok(f"{ref} contains: " + ", ".join(values) + ".", speak=True)

        if act in ("write cell", "write", "enter data", "set cell", "enter"):
            if not parameter:
                return _fail("Tell me the cell and the value, like A1 and 42.")
            ref_part, _, value = parameter.partition("|")
            if not value:
                return _fail("What value should go in that cell?")
            app = _app("excel")
            if app.Workbooks.Count == 0:
                app.Workbooks.Add()
            sheet, ref = _split_ref(app, ref_part)
            if sheet is None:
                return _fail(f"I couldn't find sheet {ref_part.split('!')[0]}.")
            sheet.Range(ref).Value = _coerce(value)
            return _ok(f"Put {value} in {ref}.")

        if act == "save":
            app = _app("excel")
            if app.Workbooks.Count == 0:
                return _fail("There's no workbook open to save.")
            wb = app.ActiveWorkbook
            if not wb.Path:
                return _fail("This workbook has never been saved. Tell me a name, "
                             "for example: save as budget.")
            wb.Save()
            return _ok(f"Saved {wb.Name}.")

        if act in ("save as", "saveas"):
            if not parameter:
                return _fail("What name should I save it as?")
            app = _app("excel")
            if app.Workbooks.Count == 0:
                return _fail("There's no workbook open to save.")
            path = _target_path(parameter, ".xlsx")
            if os.path.exists(path):
                return _fail(f"{os.path.basename(path)} already exists. "
                             f"Pick another name, or say overwrite {parameter}.")
            app.ActiveWorkbook.SaveAs(path)
            return _ok(f"Saved as {os.path.basename(path)}.")

        if act in ("overwrite", "save as overwrite"):
            if not parameter:
                return _fail("Which file should I overwrite?")
            app = _app("excel")
            if app.Workbooks.Count == 0:
                return _fail("There's no workbook open to save.")
            app.DisplayAlerts = False
            try:
                app.ActiveWorkbook.SaveAs(_target_path(parameter, ".xlsx"))
            finally:
                # Leaving alerts off would silence Excel's own prompts for the
                # rest of the user's session.
                app.DisplayAlerts = True
            return _ok(f"Overwrote {parameter}.")

        if act in ("close", "close workbook"):
            app = _app("excel")
            if app.Workbooks.Count == 0:
                return _fail("No workbook is open.")
            wb = app.ActiveWorkbook
            name = wb.Name
            if not wb.Path:
                return _fail(f"{name} has never been saved, so closing it would "
                             f"lose the data. Say save as, then a name — or say "
                             f"close without saving to discard it.")
            wb.Close(True)
            return _ok(f"Closed {name}.")

        if act in ("close without saving", "discard", "close discard"):
            app = _app("excel")
            if app.Workbooks.Count == 0:
                return _fail("No workbook is open.")
            name = app.ActiveWorkbook.Name
            app.ActiveWorkbook.Close(False)
            return _ok(f"Closed {name} without saving.")

        if act in ("quit", "quit excel", "close excel"):
            app = _app("excel", visible=False)
            app.DisplayAlerts = False
            app.Quit()
            return _ok("Excel closed.")

        return _fail(f"Unknown Excel action: {action}")

    except Exception as e:
        print(f"[OFFICE] excel {act!r} failed: {e}")
        return _fail(f"Excel wouldn't do that: {_clean(e)}")


def _split_ref(app, parameter: str):
    """Split "Sheet1!A1" into (worksheet, "A1"); bare refs use the active sheet."""
    ref = (parameter or "").strip().strip('"')
    if "!" in ref:
        sheet_name, _, ref = ref.partition("!")
        sheet_name = sheet_name.strip()
        for i in range(1, app.ActiveWorkbook.Sheets.Count + 1):
            sheet = app.ActiveWorkbook.Sheets(i)
            if sheet.Name.strip().lower() == sheet_name.lower():
                return sheet, ref.strip()
        return None, ref.strip()
    return app.ActiveSheet, ref


def _read_ref(sheet, ref: str) -> list[str] | None:
    """Read a cell or range into flat display strings, skipping blanks."""
    try:
        rng = sheet.Range(ref)
    except Exception:
        return None
    raw = rng.Value
    out: list[str] = []
    if isinstance(raw, tuple):
        for row in raw:
            cells = row if isinstance(row, tuple) else (row,)
            out.extend(_fmt(c) for c in cells if c is not None and str(c) != "")
    elif raw is not None and str(raw) != "":
        out.append(_fmt(raw))
    return out


def _fmt(value) -> str:
    """Speakable form of a cell value — 12 not 12.0, and no float noise."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).strip()


def _coerce(value: str):
    """Numbers entered by voice should land as numbers, not text."""
    v = value.strip()
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


# ── PowerPoint ────────────────────────────────────────────────────────────────

def powerpoint_control(action: str, parameter: str | None = None) -> dict:
    act = _norm(action)
    try:
        if act in ("open", "open powerpoint", "launch"):
            _app("powerpoint")
            return _ok("PowerPoint is open.")

        if act in ("new", "new presentation", "create", "create presentation"):
            _app("powerpoint").Presentations.Add()
            return _ok("New presentation ready.")

        if act in ("open presentation", "open file", "open deck"):
            if not parameter:
                return _fail("Which presentation should I open?")
            path = _resolve(parameter, "powerpoint")
            if not path:
                return _fail(f"I couldn't find a presentation called {parameter}.")
            _app("powerpoint").Presentations.Open(path)
            return _ok(f"Opened {os.path.basename(path)}.")

        if act in ("start presentation", "present", "start slideshow",
                   "slideshow", "start slide show", "play"):
            app = _app("powerpoint")
            if app.Presentations.Count == 0:
                return _fail("No presentation is open.")
            app.ActivePresentation.SlideShowSettings.Run()
            return _ok("Presenting now.")

        if act in ("end presentation", "exit slideshow", "stop presentation",
                   "end slideshow", "stop"):
            app = _app("powerpoint")
            view = _show_view(app)
            if view is None:
                return _fail("No slideshow is running.")
            view.Exit()
            return _ok("Ended the slideshow.")

        if act in ("next slide", "next", "forward"):
            return _move_slide(1)

        if act in ("previous slide", "previous", "back", "prior slide"):
            return _move_slide(-1)

        if act in ("go to slide", "slide"):
            if not parameter or not parameter.strip().isdigit():
                return _fail("Which slide number?")
            n = int(parameter.strip())
            app = _app("powerpoint")
            if app.Presentations.Count == 0:
                return _fail("No presentation is open.")
            total = app.ActivePresentation.Slides.Count
            if not 1 <= n <= total:
                return _fail(f"There are only {total} slides.")
            view = _show_view(app)
            if view is not None:
                view.GotoSlide(n)
            else:
                app.ActiveWindow.View.GotoSlide(n)
            return _ok(f"On slide {n}.")

        if act == "save":
            app = _app("powerpoint")
            if app.Presentations.Count == 0:
                return _fail("There's no presentation open to save.")
            pres = app.ActivePresentation
            if not pres.Path:
                return _fail("This presentation has never been saved. Tell me a "
                             "name, for example: save as pitch.")
            pres.Save()
            return _ok(f"Saved {pres.Name}.")

        if act in ("save as", "saveas"):
            if not parameter:
                return _fail("What name should I save it as?")
            app = _app("powerpoint")
            if app.Presentations.Count == 0:
                return _fail("There's no presentation open to save.")
            path = _target_path(parameter, ".pptx")
            if os.path.exists(path):
                return _fail(f"{os.path.basename(path)} already exists. "
                             f"Pick another name, or say overwrite {parameter}.")
            app.ActivePresentation.SaveAs(path)
            return _ok(f"Saved as {os.path.basename(path)}.")

        if act in ("overwrite", "save as overwrite"):
            if not parameter:
                return _fail("Which file should I overwrite?")
            app = _app("powerpoint")
            if app.Presentations.Count == 0:
                return _fail("There's no presentation open to save.")
            app.ActivePresentation.SaveAs(_target_path(parameter, ".pptx"))
            return _ok(f"Overwrote {parameter}.")

        if act in ("close", "close presentation"):
            app = _app("powerpoint")
            if app.Presentations.Count == 0:
                return _fail("No presentation is open.")
            pres = app.ActivePresentation
            name = pres.Name
            if not pres.Path:
                return _fail(f"{name} has never been saved, so closing it would "
                             f"lose the slides. Say save as, then a name — or say "
                             f"close without saving to discard it.")
            pres.Save()
            pres.Close()
            return _ok(f"Closed {name}.")

        if act in ("close without saving", "discard", "close discard"):
            app = _app("powerpoint")
            if app.Presentations.Count == 0:
                return _fail("No presentation is open.")
            name = app.ActivePresentation.Name
            app.ActivePresentation.Close()
            return _ok(f"Closed {name} without saving.")

        if act in ("quit", "quit powerpoint", "close powerpoint"):
            _app("powerpoint", visible=False).Quit()
            return _ok("PowerPoint closed.")

        return _fail(f"Unknown PowerPoint action: {action}")

    except Exception as e:
        print(f"[OFFICE] powerpoint {act!r} failed: {e}")
        return _fail(f"PowerPoint wouldn't do that: {_clean(e)}")


def _show_view(app):
    """The running slideshow's view, or None when not presenting.

    SlideShowWindow raises rather than returning None when no show is running,
    so this has to be probed, not tested truthily.
    """
    try:
        if app.SlideShowWindows.Count > 0:
            return app.SlideShowWindows(1).View
    except Exception:
        pass
    return None


def _move_slide(step: int) -> dict:
    """Next/previous, working both in a live slideshow and in edit view."""
    app = _app("powerpoint")
    if app.Presentations.Count == 0:
        return _fail("No presentation is open.")

    view = _show_view(app)
    if view is not None:
        view.Next() if step > 0 else view.Previous()
        return _ok("Next slide." if step > 0 else "Previous slide.")

    # Edit view: GotoSlide needs an explicit index, and clamping avoids a COM
    # error at either end of the deck.
    window = app.ActiveWindow
    total = app.ActivePresentation.Slides.Count
    try:
        current = window.View.Slide.SlideIndex
    except Exception:
        current = 1
    target = current + step
    if target < 1:
        return _ok("Already on the first slide.")
    if target > total:
        return _ok("Already on the last slide.")
    window.View.GotoSlide(target)
    return _ok(f"Slide {target}.")


# ── Teams ─────────────────────────────────────────────────────────────────────

def teams_control(action: str, parameter: str | None = None) -> dict:
    """Open/focus Teams only — deliberately NOT deep control.

    Teams has no usable COM object model: both the classic and new clients are
    Electron/WebView2 apps, and the only COM registrations that exist are
    private presence hooks for Outlook, not a public automation surface. So
    there is nothing to Dispatch to, and anything beyond launching and focusing
    the window would mean blind coordinate clicking through the chat list —
    which could land on the wrong conversation or call someone. Refusing is the
    honest behaviour; the window actions below are real and reliable.
    """
    act = _norm(action)
    try:
        import executor

        if act in ("open", "open teams", "launch", "start"):
            # ms-teams: is the documented launch protocol and works for both
            # the Store and classic installs, unlike guessing an exe path.
            import system_control
            system_control._launch("ms-teams:")
            return _ok("Opening Teams.")

        if act in ("focus", "switch", "switch to teams", "bring to front",
                   "show", "show teams"):
            result = executor.switch_window("Teams")
            # switch_window reports its own miss; surface that rather than
            # claiming success.
            return {"success": "Couldn't" not in result, "message": result}

        if act in ("minimize", "hide"):
            return {"success": True, "message": executor.minimize_window("Teams")}

        if act in ("close", "quit", "close teams", "quit teams"):
            return {"success": True, "message": executor.close_application("Teams")}

        return _fail(
            "I can open, focus or close Teams, but I can't drive what's inside "
            "it — Teams doesn't expose an automation interface, so I'd be "
            "guessing at buttons and could message or call the wrong person.")

    except Exception as e:
        print(f"[OFFICE] teams {act!r} failed: {e}")
        return _fail(f"I couldn't do that with Teams: {_clean(e)}")
