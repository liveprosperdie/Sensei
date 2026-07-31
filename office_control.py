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
import re as _re

import doc_image_plan

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


# ── Colour handling ───────────────────────────────────────────────────────────

_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "dark red": (192, 0, 0), "green": (0, 176, 80), "dark green": (0, 97, 0),
    "blue": (0, 112, 192), "dark blue": (0, 32, 96), "light blue": (0, 176, 240),
    "yellow": (255, 255, 0), "orange": (255, 153, 0), "purple": (112, 48, 160),
    "pink": (255, 102, 204), "grey": (128, 128, 128), "gray": (128, 128, 128),
    "light grey": (217, 217, 217), "light gray": (217, 217, 217),
    "brown": (132, 60, 12), "teal": (0, 128, 128),
}


def _color(spec: str) -> int | None:
    """Colour name, '#ff0000', or '255,0,0' -> the packed integer Office wants.

    Office stores colours as &HBBGGRR (blue in the HIGH byte), NOT as HTML RGB.
    Getting this backwards silently yields the wrong colour rather than an
    error, so the byte order is inverted here in exactly one place and every
    caller (Word font, Word shading, Excel fill) reuses it.
    """
    s = (spec or "").strip().lower()
    if not s:
        return None
    rgb = _COLORS.get(s)
    if rgb is None and s.startswith("#") and len(s) == 7:
        try:
            rgb = (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
        except ValueError:
            return None
    if rgb is None and "," in s:
        try:
            parts = [int(p) for p in s.split(",")]
        except ValueError:
            return None
        if len(parts) == 3 and all(0 <= p <= 255 for p in parts):
            rgb = tuple(parts)  # type: ignore[assignment]
    if rgb is None:
        return None
    r, g, b = rgb
    return r + (g << 8) + (b << 16)


# ── Image sourcing — REUSES the existing picker pipeline ──────────────────────

def _resolve_image(spec: str) -> tuple[str | None, str | None]:
    """Turn 'the third one' / a filename / a path into a local image path.

    Deliberately does NOT search: image_flow already owns search -> local
    numbered picker page -> strict pick resolution -> unique-filename download,
    and duplicating any of that would mean two divergent image pipelines and
    two safety-filter implementations. A spoken pick is handed straight to
    image_flow.download_image, which resolves it against the candidates the
    user actually saw and returns the saved path.
    """
    spec = (spec or "").strip().strip('"')
    if not spec:
        return None, ("Which image? Search for one first, then tell me which "
                      "one to use.")

    # An existing local file (or an explicit path) is used as-is — no network.
    local = os.path.expandvars(os.path.expanduser(spec))
    if os.path.isfile(local):
        if os.path.splitext(local)[1].lower() not in _IMG_EXTS:
            return None, f"{os.path.basename(local)} isn't an image file."
        return os.path.abspath(local), None
    if os.path.isabs(local) or os.sep in local:
        return None, f"I couldn't find an image at '{spec}'."

    # A bare filename that does NOT exist is the model inventing a plausible
    # path ("images.jpg", "image.images.jpg" — both seen live) while a picker
    # full of real numbered candidates is open. Handing that to resolve_pick
    # risks a fuzzy title match on the WRONG candidate, so refuse it outright
    # and ask for the number instead.
    if os.path.splitext(spec)[1].lower() in _IMG_EXTS:
        return None, (f"There's no file called {spec} — say the NUMBER of the "
                      f"image you want from the ones on your screen.")

    try:
        import image_flow
    except Exception as e:                                    # pragma: no cover
        return None, f"The image pipeline isn't available ({e})."

    res = image_flow.download_image(spec)
    if not res.get("success"):
        # Pass image_flow's own wording through — it already explains the
        # "search first" and "which one did you mean" cases precisely.
        return None, res.get("message", "I couldn't get that image.")
    return res.get("path"), None


_IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


# ── Mandatory batch image pass after generation ───────────────────────────────

def _image_pass_prompt(advance_first: bool) -> str:
    """Search images for the current (or next) section of the active plan and
    return the spoken prompt for it. Empty string once the pass is finished.

    Reuses image_flow.search_image untouched, so the user sees the SAME local
    numbered picker page as any other image search. Broader queries are tried
    automatically when a heading is too specific to return anything, and a
    section with no usable results is skipped rather than deadlocking the pass.
    """
    try:
        import image_flow
    except Exception as e:                                    # pragma: no cover
        print(f"[OFFICE] image pass unavailable ({e})")
        doc_image_plan.clear()
        return ""

    cur = doc_image_plan.advance() if advance_first else doc_image_plan.current()
    while cur:
        for query in doc_image_plan.query_candidates(cur["heading"],
                                                     cur["subject"],
                                                     cur["doc_title"]):
            try:
                res = image_flow.search_image(query)
            except Exception as e:
                print(f"[OFFICE] image search failed for {query!r}: {e}")
                continue
            if res.get("success"):
                return (f"Section {cur['index']} of {cur['total']}, "
                        f"{cur['heading']}. {res.get('message', '')} "
                        "Say a number to use one, or say skip.")
            print(f"[OFFICE] no results for {query!r} — broadening")
        print(f"[OFFICE] skipping images for section {cur['heading']!r}")
        cur = doc_image_plan.advance()
    return ""


def _word_insert_picture_after_heading(doc, heading: str, path: str) -> str | None:
    """Put the picture in its own centred paragraph directly under `heading`.
    Returns an error string, or None on success."""
    want = doc_image_plan.clean_heading(heading).lower()
    target = None
    try:
        for p in doc.Paragraphs:
            style, text, level = _para_info(p)
            if not text:
                continue
            is_heading = level != _WD_BODY_TEXT or style.lower().startswith("heading")
            if is_heading and doc_image_plan.clean_heading(text).lower() == want:
                target = p
                break
    except Exception as e:
        return f"couldn't read the document ({e})"
    if target is None:
        return f"couldn't find the '{heading}' heading"

    try:
        target.Range.InsertParagraphAfter()
        holder = target.Next()
        if holder is None:
            return "couldn't make room under that heading"
        normal = _word_style(doc, "normal")
        if normal is not None:
            try:
                holder.Style = normal
            except Exception as e:
                print(f"[OFFICE] image paragraph style failed: {e}")
        try:
            holder.Alignment = 1                              # wdAlignParagraphCenter
        except Exception:
            pass
        shape = holder.Range.InlineShapes.AddPicture(
            FileName=path, LinkToFile=False, SaveWithDocument=True)
    except Exception as e:
        return f"couldn't insert the picture ({e})"

    # Keep the picture inside the text column — Word does not scale it down.
    try:
        setup = doc.PageSetup
        max_w = setup.PageWidth - setup.LeftMargin - setup.RightMargin
        if shape.Width > max_w:
            shape.LockAspectRatio = -1                        # msoTrue
            shape.Width = max_w
    except Exception as e:
        print(f"[OFFICE] picture resize skipped: {e}")
    return None


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
            doc_image_plan.clear()      # the pass belonged to THAT document
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
        # 'detail' carries the paragraph STRUCTURE (style name + text) so the
        # next turn can target formatting by structural category instead of
        # asking the user to select text by hand. 'message' stays the short
        # spoken form — record_action_results prefers detail for the LLM.
        paras = _word_paragraphs(doc)
        if paras:
            outline = " | ".join(f"[{style}] {ptext[:100]}"
                                 for style, ptext in paras[:60])
            return _ok(snippet, speak=True,
                       detail=f"Document structure: {outline}")
        return _ok(snippet, speak=True)

    if sub == "generate":
        return _word_generate(app, doc, parameter)

    if sub == "format by style":
        return _word_format_by_style(doc, parameter)

    if sub in _WORD_FORMAT_SUBS:
        return _word_format(app, doc, sub, parameter)

    if sub in ("bullet list", "numbered list"):
        try:
            rng = _word_target(app, doc)[0]
            lf = rng.ListFormat
            # ApplyBulletDefault/ApplyNumberDefault use Word's own current
            # gallery defaults, so the result matches what the ribbon buttons
            # produce instead of a hand-built ListTemplate that ignores the
            # user's template.
            if sub == "bullet list":
                lf.ApplyBulletDefault()
            else:
                lf.ApplyNumberDefault()
            return _ok(f"Made that a {sub}.")
        except Exception as e:
            return _err(f"I couldn't apply the list: {e}")

    if sub == "remove list":
        try:
            _word_target(app, doc)[0].ListFormat.RemoveNumbers()
            return _ok("Removed the list formatting.")
        except Exception as e:
            return _err(f"I couldn't remove the list: {e}")

    if sub in ("new paragraph", "line break"):
        try:
            sel = app.Selection
            sel.Collapse(0)                                   # wdCollapseEnd
            # A real paragraph mark vs. a soft wrap are different things in
            # Word, and "new line" should not silently create a paragraph.
            if sub == "new paragraph":
                sel.TypeParagraph()
            else:
                sel.TypeText("\v")                            # vertical tab
            return _ok("Done.")
        except Exception as e:
            return _err(f"I couldn't do that: {e}")

    if sub == "skip image":
        cur = doc_image_plan.current() if doc_image_plan.is_active("word") else None
        if not cur:
            return _err("There's no image pass running right now.")
        nxt = _image_pass_prompt(True)
        if nxt:
            return _ok(f"Skipping the image for {cur['heading']}. {nxt}",
                       speak=True)
        return _ok("Skipped that one. That's every section covered.")

    if sub == "insert image":
        path, e = _resolve_image(parameter)
        if e:
            return _err(e)

        # Inside a batch image pass the picture belongs UNDER its section
        # heading, not wherever the caret happens to be sitting.
        cur = doc_image_plan.current() if doc_image_plan.is_active("word") else None
        if cur:
            err = _word_insert_picture_after_heading(doc, cur["heading"], path)
            if err:
                print(f"[OFFICE] section insert failed ({err}) — using the caret")
            placed = (f"Added that image under {cur['heading']}." if not err
                      else f"I couldn't place it under {cur['heading']} — "
                           f"{err}, so it went in at the cursor instead.")
            if err:
                try:
                    sel = app.Selection
                    sel.Collapse(0)
                    sel.InlineShapes.AddPicture(FileName=path, LinkToFile=False,
                                                SaveWithDocument=True)
                except Exception as ex:
                    return _err(f"I couldn't insert that image: {ex}")
            nxt = _image_pass_prompt(True)
            if nxt:
                return _ok(f"{placed} {nxt}", speak=True)
            return _ok(f"{placed} That's every section covered.")

        try:
            sel = app.Selection
            sel.Collapse(0)
            sel.InlineShapes.AddPicture(FileName=path, LinkToFile=False,
                                        SaveWithDocument=True)
            return _ok(f"Inserted {os.path.basename(path)} into the document.")
        except Exception as ex:
            return _err(f"I couldn't insert that image: {ex}")

    if sub == "undo":
        try:
            # Word has NO Application.Undo — undo lives on the Document and
            # returns False when the stack is empty (verified, not assumed).
            times = _int_arg(parameter) or 1
            if not doc.Undo(times):
                return _err("There's nothing left to undo.")
            return _ok("Undone." if times == 1 else f"Undid {times} steps.")
        except Exception as e:
            return _err(f"I couldn't undo that: {e}")

    return _err(f"I can't do '{sub}' in Word.")


# Formatting sub-actions Word accepts directly, so "make that bold" maps to
# office_control|word|bold rather than a nested format verb.
_WORD_FORMAT_SUBS = frozenset({
    "bold", "italic", "underline", "font", "font size", "text color",
    "highlight", "align",
})

_WD_ALIGN = {"left": 0, "center": 1, "centre": 1, "right": 2,
             "justify": 3, "justified": 3}

# wdColorIndex values — Word's highlight takes an index, not an RGB value.
_WD_HIGHLIGHT = {
    "yellow": 7, "bright green": 4, "green": 11, "turquoise": 3, "cyan": 3,
    "pink": 5, "magenta": 5, "blue": 2, "red": 6, "dark blue": 9,
    "teal": 10, "violet": 12, "gray": 15, "grey": 15, "none": 0, "off": 0,
}

_OFF_WORDS = {"off", "no", "none", "remove", "clear", "false", "un"}


def _word_target(app, doc):
    """(range, scope_label) for a formatting command.

    Formats the SELECTION when the user has highlighted something; falls back
    to the whole document when the caret is just sitting somewhere, because
    "make it bigger" with nothing selected means the document. The label is
    returned so the spoken reply always states which one happened — silently
    reformatting an entire document would be alarming.
    """
    try:
        sel = app.Selection
        # wdSelectionIP (1) == a collapsed caret, i.e. nothing is selected.
        if int(sel.Type) != 1 and len(sel.Range.Text or "") > 0:
            return sel.Range, "the selection"
    except Exception:
        pass
    return doc.Content, "the whole document"


def _int_arg(parameter: str | None) -> int | None:
    digits = "".join(c for c in (parameter or "") if c.isdigit())
    return int(digits) if digits else None


def _sentence(text: str) -> str:
    """Capitalise only the FIRST letter. str.capitalize() would lowercase the
    rest and turn "Times New Roman" into "times new roman" in the spoken reply.
    """
    return text[:1].upper() + text[1:] if text else text


def _apply_word_format(rng, what: str, value: str) -> tuple[str | None, str]:
    """Apply ONE formatting change to a Word range.

    Returns (error_message, description). Split out of _word_format so the
    selection path and the format-by-style path share exactly one
    implementation of every property — the alternative was a second copy that
    would drift on the first added property.
    """
    value = (value or "").strip()
    low = value.lower()
    try:
        if what in ("bold", "italic", "underline"):
            on = low not in _OFF_WORDS
            setattr(rng.Font, what.capitalize(), -1 if on else 0)
            return None, f"{'applied' if on else 'removed'} {what}"

        if what == "font":
            if not value:
                return "Which font?", ""
            rng.Font.Name = value
            return None, f"set to {value}"

        if what == "font size":
            size = _int_arg(value)
            if not size or not 1 <= size <= 1638:      # Word's own valid range
                return "What size? Word allows 1 to 1638 point.", ""
            rng.Font.Size = size
            return None, f"set to {size} point"

        if what == "text color":
            c = _color(value)
            if c is None:
                return f"I don't know the colour '{value}'.", ""
            rng.Font.Color = c
            return None, f"coloured {value}"

        if what == "highlight":
            idx = _WD_HIGHLIGHT.get(low)
            if idx is None:
                return (f"I can't highlight in '{value}'. "
                        "Try yellow, green, pink, or turquoise."), ""
            rng.HighlightColorIndex = idx
            return None, ("highlight removed" if idx == 0
                          else f"highlighted {value}")

        if what == "align":
            a = _WD_ALIGN.get(low)
            if a is None:
                return "Left, center, right, or justify?", ""
            rng.ParagraphFormat.Alignment = a
            return None, f"aligned {low}"
    except Exception as e:
        return f"I couldn't apply that formatting: {e}", ""

    return f"I can't apply '{what}' in Word.", ""


def _word_format(app, doc, what: str, parameter: str | None) -> dict:
    try:
        rng, scope = _word_target(app, doc)
    except Exception as e:
        return _err(f"I couldn't find what to format: {e}")

    err, described = _apply_word_format(rng, what, parameter or "")
    if err:
        return _err(err)
    return _ok(f"{_sentence(described)} on {scope}.")


# ── Word structure: paragraph styles, style-targeted formatting, generation ───

# Word's NEGATIVE built-in style indices. Using these instead of the English
# names is deliberate: Styles("Heading 1") raises on a non-English Word (it is
# "Titre 1" in French, "Überschrift 1" in German), while the built-in index is
# identical in every language pack.
_WD_BUILTIN_STYLES = {
    "normal": -1, "heading 1": -2, "heading 2": -3, "heading 3": -4,
    "heading 4": -5, "heading 5": -6, "title": -63,
}

# wdOutlineLevelBodyText — every non-heading paragraph reports this.
_WD_BODY_TEXT = 10


def _word_style(doc, key: str):
    """A Style object for a canonical key, or None if Word has neither form."""
    idx = _WD_BUILTIN_STYLES.get(key)
    if idx is not None:
        try:
            return doc.Styles(idx)
        except Exception:
            pass
    try:
        return doc.Styles(key.title())
    except Exception:
        return None


def _para_info(p) -> tuple[str, str, int]:
    """(style name, text, outline level) for one paragraph.

    Outline level is carried alongside the NAME because the name is localised
    and the level is not — structural matching uses the level, the spoken reply
    uses the name.
    """
    try:
        style = str(p.Style.NameLocal)
    except Exception:
        style = "Normal"
    try:
        text = (p.Range.Text or "").replace("\r", "").replace("\x07", "").strip()
    except Exception:
        text = ""
    try:
        level = int(p.OutlineLevel)
    except Exception:
        level = _WD_BODY_TEXT
    return style, text, level


def _word_paragraphs(doc) -> list[tuple[str, str]]:
    """[(style name, text)] for every non-empty paragraph."""
    out = []
    try:
        for p in doc.Paragraphs:
            style, text, _ = _para_info(p)
            if text:
                out.append((style, text))
    except Exception as e:
        print(f"[OFFICE] paragraph walk failed: {e}")
    return out


def _style_spec_matches(spec: str, style: str, level: int) -> bool:
    """Does a paragraph belong to the structural category the user named?

    Spoken instructions name a CATEGORY ("the titles", "body text"), not a
    style id, so headings are matched by outline level — that is the one
    property that survives localisation, custom style names and templates.
    """
    spec = (spec or "").strip().lower()
    style_low = style.lower()
    is_heading = level != _WD_BODY_TEXT or style_low.startswith("heading")

    if spec in ("heading", "headings", "header", "headers", "title", "titles",
                "section title", "section titles", "section heading",
                "section headings"):
        return is_heading or style_low == "title"
    if spec in ("body", "body text", "paragraph", "paragraphs", "normal",
                "text", "content"):
        return not is_heading and style_low != "title"
    m = _re.match(r"^heading\s*(\d)$", spec)
    if m:
        want = int(m.group(1))
        return level == want or style_low in (f"heading {want}",)
    # Anything else is treated as a style name (exact, then partial).
    return style_low == spec or spec in style_low


def _word_format_by_style(doc, parameter: str | None) -> dict:
    """format_by_style|<style or category>|<what>|<value>

    Exists so "make all the titles Times New Roman" resolves structurally
    instead of asking the user to select each heading by hand.
    """
    spec, what, value = _fields(parameter, 3)
    what = what.lower().replace("_", " ").strip()
    what = _ALIASES.get(what, what)
    if not spec:
        return _err("Which style — headings, or body text?")
    if what not in _WORD_FORMAT_SUBS:
        return _err(f"I can't apply '{what or 'that'}' to a style. "
                    "I can do font, font size, bold, italic, underline, "
                    "text color, highlight, or align.")

    try:
        paragraphs = list(doc.Paragraphs)
    except Exception as e:
        return _err(f"I couldn't read the document: {e}")

    targets, seen_styles = [], []
    for p in paragraphs:
        style, text, level = _para_info(p)
        if not text:
            continue
        if style not in seen_styles:
            seen_styles.append(style)
        if _style_spec_matches(spec, style, level):
            targets.append((p, style))

    if not targets:
        have = ", ".join(seen_styles[:6]) or "nothing"
        return _err(f"I couldn't find any '{spec}' paragraphs. "
                    f"This document uses: {have}.")

    described = ""
    for p, _style in targets:
        err, described = _apply_word_format(p.Range, what, value)
        if err:
            return _err(err)

    names = ", ".join(dict.fromkeys(s for _p, s in targets))
    count = len(targets)
    return _ok(f"{_sentence(described)} on {count} "
               f"{'paragraph' if count == 1 else 'paragraphs'} "
               f"styled {names}.")


# Gemini is asked for markdown-style heading markers and NOTHING else, so the
# heading structure survives the trip as plain text and becomes real Word
# styles here. Bold text would look similar and be structurally useless (no
# navigation pane, no table of contents, no format_by_style targeting).
_GEN_FORMAT_INSTRUCTIONS = (
    "Write it as a structured document. Start each section with its heading on "
    "its own line prefixed by '## '. Everything else is a normal body "
    "paragraph. Do not write a document title, it already exists. Use NO other "
    "markdown at all: no asterisks, no bold, no bullet characters, no "
    "backticks, no tables."
)

_GEN_LENGTHS = {"brief": "short", "short": "short", "detailed": "detailed",
                "long": "detailed", "full": "detailed", "": "short"}


def _parse_generated_blocks(text: str) -> list[tuple[str, str]]:
    """Generated plain text -> [(style key, paragraph text)]."""
    blocks: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("### "):
            blocks.append(("heading 3", line[4:].strip()))
        elif line.startswith("## "):
            blocks.append(("heading 2", line[3:].strip()))
        elif line.startswith("# "):
            blocks.append(("heading 1", line[2:].strip()))
        else:
            # A stray asterisk or bullet glyph would be read aloud and printed
            # literally, so strip the markdown the model was told not to use.
            blocks.append(("normal", line.strip("*• ").strip()))
    return [(style, body) for style, body in blocks if body]


def _word_write_blocks(app, doc, blocks: list[tuple[str, str]]) -> str | None:
    """Type styled paragraphs at the end of the document. Returns an error."""
    try:
        sel = app.Selection
        sel.EndKey(6)                                     # wdStory
        if (doc.Content.Text or "").strip():
            sel.TypeParagraph()                           # never join onto text
        for style_key, text in blocks:
            style = _word_style(doc, style_key)
            if style is not None:
                try:
                    sel.Style = style
                except Exception as e:
                    print(f"[OFFICE] style {style_key!r} failed: {e}")
            sel.TypeText(text)
            sel.TypeParagraph()
        # Leave the caret in body style so the next dictation isn't a heading.
        normal = _word_style(doc, "normal")
        if normal is not None:
            try:
                sel.Style = normal
            except Exception:
                pass
        return None
    except Exception as e:
        return str(e)


def _word_generate(app, doc, parameter: str | None) -> dict:
    """generate|<title>|<topic or instructions>|<brief or detailed>

    Content comes from gemini_content — the SAME generator docs_control uses.
    It deliberately never travels inside the routing JSON: that is what used to
    truncate the reply mid-string and kill the whole turn.
    """
    title, brief, length = _fields(parameter, 3)
    if not title or not brief:
        return _err("Generating needs a title and a short brief of what to write.")

    try:
        import gemini_content
    except Exception as e:                                # pragma: no cover
        return _err(f"The content generator isn't available ({e}).")

    gen = gemini_content.generate(
        brief, _GEN_FORMAT_INSTRUCTIONS,
        _GEN_LENGTHS.get(length.lower().strip(), "short"))
    if not gen.get("success"):
        return _err(gen.get("message", "I couldn't generate that content."))

    blocks = [("heading 1", title)] + _parse_generated_blocks(gen["text"])
    err = _word_write_blocks(app, doc, blocks)
    if err:
        return _err(f"I couldn't write it into the document: {err}")

    headings = [text for style, text in blocks[1:] if style.startswith("heading")]
    written = (f"Wrote {title} into the document with {len(headings)} "
               f"{'section' if len(headings) == 1 else 'sections'}.")

    # MANDATORY, NOT OPTIONAL: every generated document gets an image pass over
    # its sections once ALL the text exists. Batched at the end deliberately —
    # interleaving picks between sections broke the flow of the writing.
    # `brief` (what the USER asked for) anchors the image queries — the
    # generated headings are written for prose and search terribly on their own.
    if doc_image_plan.begin("word", title, headings, brief):
        prompt = _image_pass_prompt(False)
        if prompt:
            return _ok(f"{written} Now the images. {prompt}", speak=True)
    return _ok(written)


# ── Excel ──────────────────────────────────────────────���─────────────��────────

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

    if sub == "formula":
        # "formula|A1|=SUM(B1:B10)" or "formula|=SUM(B1:B10)" for the selection.
        cell, expr = _fields(parameter, 2)
        if not expr:
            cell, expr = "", cell
        if not expr:
            return _err("Which formula should I enter?")
        if not expr.startswith("="):
            expr = "=" + expr
        try:
            sheet = wb.ActiveSheet
            target = sheet.Range(cell) if cell else app.Selection
            target.Formula = expr
            where = cell or target.Address(False, False)
            # Read the computed result back and speak it: a formula that lands
            # as #REF! or #DIV/0! must not be reported as a success.
            val = target.Value
            shown = "empty" if val in (None, "") else _fmt(val)
            if isinstance(shown, str) and shown.startswith("#"):
                return _err(f"{where} came back as {shown} — "
                            "the formula doesn't work on that data.")
            return _ok(f"{where} is {shown}.", speak=True)
        except Exception as e:
            return _err(f"I couldn't enter that formula: {e}")

    if sub in _XL_FORMAT_SUBS:
        return _excel_format(app, wb, sub, parameter)

    if sub == "chart":
        return _excel_chart(app, wb, parameter)

    if sub == "undo":
        try:
            # Excel DOES expose Application.Undo (unlike Word). It only undoes
            # the last action and cannot be repeated reliably, so no count.
            app.Undo()
            return _ok("Undone.")
        except Exception as e:
            return _err(f"I couldn't undo that: {e}")

    return _err(f"I can't do '{sub}' in Excel.")


_XL_FORMAT_SUBS = frozenset({"bold", "italic", "font size", "fill color",
                             "text color", "number format"})

# Spoken format names -> Excel format codes. Raw codes pass through untouched.
_XL_NUMBER_FORMATS = {
    "currency": "$#,##0.00", "money": "$#,##0.00", "dollars": "$#,##0.00",
    "pounds": "£#,##0.00", "euros": "€#,##0.00",
    "percent": "0.00%", "percentage": "0.00%",
    "date": "yyyy-mm-dd", "short date": "m/d/yyyy", "time": "h:mm AM/PM",
    "number": "#,##0.00", "integer": "#,##0", "whole number": "#,##0",
    "text": "@", "general": "General", "accounting": "_($* #,##0.00_)",
}

# Chart types. "bar" colloquially means vertical columns, so it maps to
# xlColumnClustered (51); a true horizontal bar needs xlBarClustered (57).
_XL_CHART_TYPES = {
    "bar": 51, "column": 51, "vertical bar": 51, "horizontal bar": 57,
    "line": 4, "pie": 5, "doughnut": -4120, "area": 1,
    "scatter": -4169, "xy": -4169, "radar": -4151,
}

_A1_RE = None


def _looks_like_ref(s: str) -> bool:
    """True for 'B7', 'A1:D20', 'Sheet1!A1:B5' — used to tell an optional
    leading range argument apart from a value argument."""
    global _A1_RE
    if _A1_RE is None:
        import re
        _A1_RE = re.compile(
            r"^(?:[^!]{1,31}!)?\$?[A-Za-z]{1,3}\$?\d{1,7}"
            r"(?::\$?[A-Za-z]{1,3}\$?\d{1,7})?$")
    return bool(_A1_RE.match(s.strip()))


def _xl_target(app, wb, parameter: str | None) -> tuple[object, str, str]:
    """(range, remaining_value, label) for '<range>|<value>' or '<value>'.

    The range is optional in speech ("make it bold"), so a leading field is
    only treated as a range when it actually looks like one.
    """
    first, rest = _fields(parameter, 2)
    sheet = wb.ActiveSheet
    if first and _looks_like_ref(first):
        sheet_name, _, cells = first.rpartition("!")
        if sheet_name:
            sheet = wb.Worksheets(sheet_name)
        rng = sheet.Range(cells or first)
        return rng, rest, first
    value = (first + ("|" + rest if rest else "")).strip()
    rng = app.Selection
    try:
        label = str(rng.Address(False, False))
    except Exception:
        label = "the selection"
    return rng, value, label


def _excel_format(app, wb, what: str, parameter: str | None) -> dict:
    try:
        rng, value, label = _xl_target(app, wb, parameter)
    except Exception as e:
        return _err(f"That isn't a range I can format: {e}")
    low = value.strip().lower()

    try:
        if what in ("bold", "italic"):
            on = low not in _OFF_WORDS
            setattr(rng.Font, what.capitalize(), on)
            return _ok(f"{'Applied' if on else 'Removed'} {what} on {label}.")

        if what == "font size":
            size = _int_arg(value)
            if not size or not 1 <= size <= 409:      # Excel's own valid range
                return _err("What size? Excel allows 1 to 409 point.")
            rng.Font.Size = size
            return _ok(f"Set {label} to {size} point.")

        if what in ("fill color", "text color"):
            c = _color(value)
            if c is None:
                return _err(f"I don't know the colour '{value}'.")
            if what == "fill color":
                rng.Interior.Color = c
            else:
                rng.Font.Color = c
            return _ok(f"Set {label} {what.replace('color', 'colour')} to {value}.")

        if what == "number format":
            if not low:
                return _err("Which format? Currency, percent, or date?")
            code = _XL_NUMBER_FORMATS.get(low, value)
            rng.NumberFormat = code
            return _ok(f"Formatted {label} as {low}.")
    except Exception as e:
        return _err(f"I couldn't apply that formatting: {e}")

    return _err(f"I can't apply '{what}' in Excel.")


def _excel_chart(app, wb, parameter: str | None) -> dict:
    """chart|<type>|<range> — e.g. chart|bar|A1:B10.

    Uses Shapes.AddChart2 (verified as the current path; ChartObjects.Add is
    obsolete and demands hard-coded pixel dimensions) and falls back to the
    older AddChart on pre-2013 builds. SetSourceData lives on the Chart, not
    on the Shape.
    """
    first, second = _fields(parameter, 2)
    # Tolerate "A1:B10|bar" as well as "bar|A1:B10". The range keeps its
    # original casing so it reads back correctly in the spoken reply.
    if first and _looks_like_ref(first) and second:
        kind, ref = second.strip().lower(), first
    else:
        kind, ref = first.strip().lower(), second
    ctype = _XL_CHART_TYPES.get(kind)
    if ctype is None:
        return _err(f"I can't make a '{kind or 'that'}' chart. "
                    "I can do bar, line, pie, area, or scatter.")
    if not ref.strip():
        return _err("Which range should the chart use?")

    try:
        sheet = wb.ActiveSheet
        sheet_name, _, cells = ref.rpartition("!")
        if sheet_name:
            sheet = wb.Worksheets(sheet_name)
        source = sheet.Range(cells or ref)
    except Exception:
        return _err(f"'{ref}' isn't a range I can chart.")

    try:
        try:
            shape = sheet.Shapes.AddChart2(-1, ctype)
        except Exception:
            shape = sheet.Shapes.AddChart(ctype)
        chart = shape.Chart
        chart.SetSourceData(Source=source)
        return _ok(f"Added a {kind} chart from {ref}.")
    except Exception as e:
        return _err(f"I couldn't create the chart: {e}")


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

    if sub == "new slide":
        return _add_slide(app, pres, parameter)

    if sub == "delete slide":
        try:
            total = int(pres.Slides.Count)
            if total <= 0:
                return _err("There are no slides to delete.")
            n = _slide_number(parameter, pres) if (parameter or "").strip() \
                else _current_slide(app, pres)
            if n is None:
                return _err("Which slide should I delete?")
            if not 1 <= n <= total:
                return _err(f"There are only {total} slides.")
            pres.Slides(n).Delete()
            return _ok(f"Deleted slide {n}. {total - 1} left.")
        except Exception as e:
            return _err(f"I couldn't delete that slide: {e}")

    if sub in ("set title", "set content"):
        text = (parameter or "").strip()
        if not text:
            return _err("What should it say?")
        try:
            slide = pres.Slides(_current_slide(app, pres) or 1)
        except Exception as e:
            return _err(f"I couldn't find the slide: {e}")
        return _set_placeholder(slide, sub == "set title", text)

    if sub == "insert image":
        path, e = _resolve_image(parameter)
        if e:
            return _err(e)
        try:
            slide = pres.Slides(_current_slide(app, pres) or 1)
        except Exception as ex:
            return _err(f"I couldn't find the slide: {ex}")
        return _add_slide_picture(pres, slide, path)

    return _err(f"I can't do '{sub}' in PowerPoint.")


# ppLayout constants. ppLayoutText (2) is the ordinary title+content slide;
# ppLayoutBlank (12) has no placeholders at all.
_PP_LAYOUTS = {
    "title": 1, "title slide": 1, "title only": 11,
    "content": 2, "title and content": 2, "text": 2, "bullets": 2,
    "two content": 3, "comparison": 3, "blank": 12, "empty": 12,
}


def _current_slide(app, pres) -> int | None:
    """Index of the slide in view, whether presenting or editing."""
    try:
        show = pres.SlideShowWindow
        if show is not None:
            return int(show.View.Slide.SlideIndex)
    except Exception:
        pass
    try:
        return int(app.ActiveWindow.View.Slide.SlideIndex)
    except Exception:
        try:
            return int(pres.Slides.Count) or None
        except Exception:
            return None


def _add_slide(app, pres, parameter: str | None) -> dict:
    layout_name = (parameter or "").strip().lower() or "content"
    layout = _PP_LAYOUTS.get(layout_name)
    if layout is None:
        return _err(f"I don't know the '{layout_name}' layout. Try title, "
                    "title and content, or blank.")
    try:
        index = int(pres.Slides.Count) + 1
        slide = pres.Slides.Add(index, layout)
        try:
            # Follow the new slide in the editor so the user sees what they
            # just made — otherwise the view stays on the old slide and any
            # follow-up "set title" looks like it did nothing.
            app.ActiveWindow.View.GotoSlide(index)
        except Exception:
            pass
        return _ok(f"Added slide {slide.SlideIndex} ({layout_name}).")
    except Exception as e:
        return _err(f"I couldn't add a slide: {e}")


def _set_placeholder(slide, is_title: bool, text: str) -> dict:
    """Write into the title or the body placeholder.

    Placeholders(1) is not reliably the title on every layout, so the title
    goes through Shapes.Title (which Office resolves correctly) and the body
    is found by scanning for the first non-title placeholder.
    """
    try:
        if is_title:
            try:
                slide.Shapes.Title.TextFrame.TextRange.Text = text
                return _ok("Set the slide title.")
            except Exception:
                return _err("This slide has no title placeholder — "
                            "add a title layout slide first.")
        for i in range(1, int(slide.Shapes.Placeholders.Count) + 1):
            ph = slide.Shapes.Placeholders(i)
            try:
                if ph.Name and "title" in str(ph.Name).lower():
                    continue
                if not ph.HasTextFrame:
                    continue
            except Exception:
                continue
            ph.TextFrame.TextRange.Text = text
            return _ok("Added the text to the slide.")
        return _err("This slide has no content placeholder — "
                    "try a title and content layout.")
    except Exception as e:
        return _err(f"I couldn't set that text: {e}")


def _add_slide_picture(pres, slide, path: str) -> dict:
    """AddPicture, then scale-to-fit and centre.

    A phone-resolution photo dropped in at native size lands far larger than
    the slide, so it is fitted to 90% of the slide and centred — otherwise the
    insert "works" while the picture hangs off the canvas invisibly.
    """
    try:
        try:
            shape = slide.Shapes.AddPicture(
                FileName=path, LinkToFile=False, SaveWithDocument=True,
                Left=0, Top=0)
        except Exception:
            # Some builds insist on explicit dimensions; -1 keeps native size.
            shape = slide.Shapes.AddPicture(
                FileName=path, LinkToFile=False, SaveWithDocument=True,
                Left=0, Top=0, Width=-1, Height=-1)
        try:
            sw = float(pres.PageSetup.SlideWidth)
            sh = float(pres.PageSetup.SlideHeight)
            w, h = float(shape.Width), float(shape.Height)
            scale = min((sw * 0.9) / w, (sh * 0.9) / h, 1.0)
            if scale < 1.0:
                shape.Width, shape.Height = w * scale, h * scale
            shape.Left = (sw - float(shape.Width)) / 2
            shape.Top = (sh - float(shape.Height)) / 2
        except Exception as e:
            print(f"[OFFICE] picture fit/centre skipped: {e}")
        return _ok(f"Added {os.path.basename(path)} to the slide.")
    except Exception as e:
        return _err(f"I couldn't add that image: {e}")


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
    # long-form generation (Word) — same verb docs_control uses
    "write document": "generate", "write doc": "generate",
    "generate content": "generate", "generate document": "generate",
    "compose": "generate", "draft": "generate",
    # structural formatting
    "format style": "format by style",
    "style format": "format by style", "format headings": "format by style",
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
    # formatting
    "make bold": "bold", "embolden": "bold", "make italic": "italic",
    "italics": "italic", "underline text": "underline",
    "size": "font size", "text size": "font size", "font name": "font",
    "typeface": "font", "set font": "font",
    "color": "text color", "colour": "text color", "font color": "text color",
    "text colour": "text color", "fill": "fill color",
    "cell color": "fill color", "background color": "fill color",
    "fill colour": "fill color", "shade": "fill color",
    "highlight text": "highlight", "alignment": "align", "align text": "align",
    "center": "align", "centre": "align",
    "format": "number format", "format cells": "number format",
    "number style": "number format", "currency": "number format",
    # lists & paragraphs
    "bullets": "bullet list", "bullet points": "bullet list",
    "bulleted list": "bullet list", "numbered": "numbered list",
    "number list": "numbered list", "ordered list": "numbered list",
    "paragraph": "new paragraph", "new line": "line break",
    "newline": "line break", "break": "line break",
    # images
    "add image": "insert image", "insert picture": "insert image",
    "add picture": "insert image", "insert photo": "insert image",
    "add photo": "insert image", "put image": "insert image",
    # batch image pass: moving past a section without an image
    "skip": "skip image", "no image": "skip image",
    "skip section": "skip image", "skip picture": "skip image",
    "next section": "skip image",
    # formulas & charts
    "enter formula": "formula", "add formula": "formula",
    "set formula": "formula", "sum": "formula", "calculate": "formula",
    "insert chart": "chart", "add chart": "chart", "create chart": "chart",
    "make chart": "chart", "graph": "chart", "insert graph": "chart",
    # slides
    "add slide": "new slide", "insert slide": "new slide",
    "create slide": "new slide", "remove slide": "delete slide",
    "title": "set title", "set heading": "set title",
    "slide title": "set title", "content": "set content",
    "set body": "set content", "slide text": "set content",
    # undo
    "undo that": "undo", "revert": "undo", "take that back": "undo",
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
# Deliberately NOT gated: formatting, lists, formulas, charts, image inserts
# and slide adds are all reversible (undo exists for exactly this) and gating
# them would make normal dictation a confirmation slog. Only actions that
# destroy work or overwrite a file are listed.
RISKY_OFFICE_PARAMS = frozenset({"close", "save as", "delete slide"})


def _canonical_sub(parameter: str | None) -> str:
    """The canonical sub-action for an "app|sub|args" parameter.

    Alias resolution MUST happen before any risk check. "remove slide",
    "close document" and "rename" are aliases of delete slide / close /
    save as, so a risk check against the raw spoken word silently let the
    destructive forms through the confirmation gate unconfirmed.
    """
    fields = (parameter or "").split("|")
    sub = (fields[1] if len(fields) > 1 else "").lower().replace("_", " ").strip()
    return _ALIASES.get(sub, sub)


def is_risky_parameter(parameter: str | None) -> bool:
    """Does this office_control parameter need confirmation? Single source of
    truth, consumed by sensei's confirmation_required gate."""
    return _canonical_sub(parameter) in RISKY_OFFICE_PARAMS


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