"""Static guard rules — the deterministic floor beneath the Guard model.

WHY THIS MODULE EXISTS
======================
The Guard validates a planned action before it is dispatched. Two thirds of
that job needs no model at all and must not depend on one being reachable:

  * is this action name real?            -> compare against executor's map
  * is the parameter the right shape?    -> per-action field arity, below
  * does it touch something risky?       -> the taxonomy that ALREADY exists

Doing that here, synchronously and offline, means the model call is an
ADDITIONAL opinion rather than the only one. A guard whose entire verdict comes
from a paid endpoint is a guard that stops existing the moment a key expires.

WHAT IS REUSED VS WHAT IS NEW (asked for explicitly — no parallel taxonomy)
--------------------------------------------------------------------------
REUSED, not redeclared:
  * executor.RISKY_KEYWORDS (executor.py:189) — the keyword list and its
    word-boundary compiled pattern already existed before this prompt. It is
    read from executor at runtime, so the guard can never drift from the list
    the click path screens against.
  * sensei._is_dangerous_step + DANGEROUS_ACTIONS / RISKY_SHOPPING_PARAMS /
    RISKY_GITHUB_PARAMS / RISKY_VSCODE_PARAMS / RISKY_CALENDAR_PARAMS /
    RISKY_WORKSPACE_PARAMS / office_control.is_risky_parameter — a complete
    code-level risk classification already exists in sensei.py. The guard
    DELEGATES to it rather than mirroring it, because that function already
    knows the two things a copy would get wrong: office_control's sub-action
    sits in field 1 (not 0) and may be a spoken alias.

NEW in this prompt, flagged as such:
  * ACTION_RULES — per-action parameter SHAPE. Nothing in the codebase
    validated parameter arity before dispatch; executor's handlers index
    p.split("|") positionally and raise or misbehave on the wrong arity. This
    is the genuinely new rule set, and it is why the coverage gate exists.

FAIL-CLOSED, STATICALLY
-----------------------
An unknown action or a malformed parameter returns BLOCK, not FLAG. Those are
not judgement calls a human confirmation prompt can improve: if the router
emitted an action executor cannot dispatch, or three fields where the handler
reads two, the correct answer is "don't run this", and asking the user to
approve a shape they cannot see would launder a bug into consent.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

# Verdict vocabulary. Deliberately three-valued rather than a bool: "needs a
# human" and "refuse outright" are different outcomes, and collapsing them is
# how a guard becomes either useless or unusable.
ALLOW = "allow"   # no static objection — safe to dispatch as-is
FLAG = "flag"     # dispatchable, but only behind explicit confirmation
BLOCK = "block"   # do not dispatch; the step is malformed or unknown

# Ordered worst-first so combining verdicts is a max(), not a tangle of ifs.
_SEVERITY = {ALLOW: 0, FLAG: 1, BLOCK: 2}


@dataclass(frozen=True, slots=True)
class Verdict:
    """The Guard's answer about one action step.

    Frozen because a verdict that can be edited after the fact is a verdict the
    caller can quietly upgrade to ALLOW — the whole point is that this object
    is evidence, not a suggestion.
    """

    decision: str
    reasons: tuple[str, ...] = ()
    source: str = "static"  # static | model | fail-closed

    @property
    def allowed(self) -> bool:
        """True only for an explicit ALLOW.

        Written as an equality test rather than `!= BLOCK` so that any future
        decision value added to this module defaults to not-allowed. A new
        verdict kind must opt IN to permitting execution.
        """
        return self.decision == ALLOW

    @property
    def needs_confirmation(self) -> bool:
        return self.decision == FLAG

    def merge(self, other: "Verdict") -> "Verdict":
        """Combine two verdicts, keeping the stricter decision and all reasons.

        Used to fold the model's opinion into the static one. The static verdict
        can only ever be made STRICTER by the model, never relaxed — a model
        that says "looks fine" cannot overturn a shape violation.
        """
        worst = self if _SEVERITY[self.decision] >= _SEVERITY[other.decision] \
            else other
        # Both sources are recorded when neither is stricter. Otherwise a step
        # both halves cleared would log as source="static" and leave no trace
        # that the model was consulted at all — indistinguishable from a guard
        # that was silently skipped, which is the thing an audit most needs to
        # tell apart.
        source = worst.source if self.source == other.source else (
            f"{self.source}+{other.source}"
            if _SEVERITY[self.decision] == _SEVERITY[other.decision]
            else worst.source)
        return Verdict(worst.decision,
                       (*self.reasons, *other.reasons),
                       source)

    def __str__(self) -> str:
        why = "; ".join(self.reasons) or "no objection"
        return f"{self.decision}({self.source}): {why}"


@dataclass(frozen=True, slots=True)
class Rule:
    """Parameter shape for one action: how many `|`-separated fields are legal.

    Arity only. This is not a type system and must not grow into one — path
    validity, URL validity and app names are executor's business, and
    duplicating them here would create exactly the second taxonomy this module
    exists to avoid.
    """

    min_fields: int
    max_fields: int
    screen: bool = True  # run the risky-keyword screen over the parameter text


# Shared rule instances rather than a literal per action: 80 actions collapse to
# five shapes, and referencing the same object makes the table scannable enough
# that a wrong shape is visible on sight.
IGNORED = Rule(0, 0, screen=False)   # handler takes no parameter (lambda _:)
OPT_TEXT = Rule(0, 1)                # one optional free-text field
TEXT = Rule(1, 1)                    # one required free-text field
SUB = Rule(1, 2)                     # "sub" or "sub|arg"
SUB_ARGS = Rule(1, 3)                # "app|sub|args" (office_control only)

# ACTION_RULES — every key in executor._ACTION_MAP must appear here.
# verify_guard_coverage.py enforces that statically; if you add an executor
# action and skip this table, the gate fails rather than the action silently
# dispatching unvalidated. That failure is the feature.
ACTION_RULES: dict[str, Rule] = {
    # ── applications & windows ────────────────────────────────────────────
    "open_application": TEXT,
    "close_application": TEXT,
    "switch_window": TEXT,
    "maximize_window": OPT_TEXT,
    "minimize_window": OPT_TEXT,
    # ── native app typing (added for voice-driven text input) ─────────────
    "type_in_app": SUB,   # "app name|text to type"
    # ── system control dispatcher (voice shortcuts: bluetooth_on, volume:N) ─
    "system_control": TEXT,   # single token like "bluetooth_on", "volume:40"
    # ── browser & web ─────────────────────────────────────────────────────
    "open_url": TEXT,
    "web_search": TEXT,
    "site_search": SUB,
    "fill": SUB,
    "scroll": OPT_TEXT,
    "new_tab": OPT_TEXT,
    "open_site_tab": TEXT,
    "list_tabs": IGNORED,
    "switch_tab": TEXT,
    "close_tab": OPT_TEXT,
    "click": TEXT,
    "browser_control": SUB,
    "bookmark_page": IGNORED,
    # ── site-specific controllers ─────────────────────────────────────────
    "youtube_control": SUB,
    "netflix_control": SUB,
    "meet_control": SUB,
    "amazon_control": SUB,
    "flipkart_control": SUB,
    "github_control": SUB,
    "vscode_control": SUB,
    "spotify_control": SUB,
    # ── Google Workspace (MCP) ────────────────────────────────────────────
    "calendar_control": SUB,
    "docs_control": SUB,
    "sheets_control": SUB,
    "slides_control": SUB,
    "gmail_control": SUB,
    "gmail_compose": SUB,
    # ── Microsoft Office (COM) ────────────────────────────────────────────
    # The only three-field shape in the table: "app|sub|args". Field 1 is the
    # sub-action, which is why risk classification is delegated rather than
    # copied — see the module docstring.
    "office_control": SUB_ARGS,
    # ── Obsidian ──────────────────────────────────────────────────────────
    "obsidian_control": SUB,
    # ── files ─────────────────────────────────────────────────────────────
    "create_file": TEXT,
    "read_file": TEXT,
    "read_more": IGNORED,
    "stop_reading": IGNORED,
    "write_file": SUB,
    "edit_file": SUB,
    "search_file": TEXT,
    "open_file": TEXT,
    "open_folder": TEXT,
    "list_folder": OPT_TEXT,
    "copy_files": SUB,
    "move_files": SUB,
    "organize_files": OPT_TEXT,
    "delete_files": TEXT,
    "organize_folder": OPT_TEXT,
    "bulk_rename_files": SUB,
    "compress_files": SUB,
    "extract_files": SUB,
    "summarize_file": TEXT,
    "file_to_doc": SUB,
    # ── media & clipboard ─────────────────────────────────────────────────
    "search_image": TEXT,
    "download_image": TEXT,
    "set_wallpaper": TEXT,
    "read_clipboard": IGNORED,
    "write_clipboard": TEXT,
    "adjust_volume": TEXT,
    "adjust_brightness": TEXT,
    "screenshot": IGNORED,
    "background_status": IGNORED,
    # ── power & session (legacy aliases onto system_control) ──────────────
    "lock_screen": IGNORED,
    "hibernate": IGNORED,
    "shutdown": IGNORED,
    "restart": IGNORED,
    # ── system_control.ACTIONS (spread into _ACTION_MAP with **) ──────────
    # Listed explicitly rather than imported: importing system_control here
    # would pull pywin32/psutil into a module that must stay importable by an
    # offline gate. The gate resolves the ** spread through AST instead, so a
    # new system action still fails coverage until it gets a rule.
    "open_settings": TEXT,
    "open_system_tool": TEXT,
    "toggle_wifi": OPT_TEXT,
    "toggle_bluetooth": OPT_TEXT,
    "lock_pc": IGNORED,
    "performance_stats": IGNORED,
    "clear_temp_files": IGNORED,
    "empty_recycle_bin": IGNORED,
    "clear_browser_cache": OPT_TEXT,
    "run_disk_cleanup": IGNORED,
    "sleep_pc": IGNORED,
    "hibernate_pc": IGNORED,
    "sign_out": IGNORED,
    "shutdown_pc": IGNORED,
    "restart_pc": IGNORED,
    "preview_temp_cleanup": IGNORED,
}


# ── reuse hooks into the existing safety logic ────────────────────────────────

def _risky_pattern() -> re.Pattern | None:
    """executor's compiled RISKY_KEYWORDS pattern, or None if unreachable.

    Imported lazily so this module stays importable without selenium — which is
    what lets the offline coverage gate run. executor is never __main__, so a
    plain import is safe here, unlike sensei below.

    Two-step lookup on purpose. executor._risky_pattern is private, and if it is
    ever renamed a single getattr would silently return None — degrading the
    screen to "unverified" on every action, which reads as a guard that flags
    everything and gets muted. Falling back to compiling the PUBLIC
    RISKY_KEYWORDS list keeps the taxonomy single-sourced (the list is the
    taxonomy; the pattern is just its compiled form) while surviving the rename.
    """
    try:
        import executor
    except Exception:
        return None

    pattern = getattr(executor, "_risky_pattern", None)
    if pattern is not None:
        return pattern

    keywords = getattr(executor, "RISKY_KEYWORDS", None)
    if not keywords:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
                      re.IGNORECASE)


def _sensei_classifier():
    """sensei._is_dangerous_step, located WITHOUT importing sensei.

    sensei.py is the application entry point, so `import sensei` from inside a
    running session would execute the module a second time under a different
    name — re-initialising pyttsx3 and the audio stack. Looking it up in
    sys.modules finds the live instance whether it was imported as a module or
    started as __main__, and returns None when neither applies (an offline
    unit test), so the caller can fail closed instead of guessing.
    """
    for name in ("sensei", "__main__"):
        mod = sys.modules.get(name)
        fn = getattr(mod, "_is_dangerous_step", None)
        if callable(fn):
            return fn
    return None


# ── the static gate itself ───────────────────────────────────────────────────

def _fields(parameter) -> list[str]:
    raw = "" if parameter is None else str(parameter)
    return [] if not raw.strip() else raw.split("|")


def validate(action: str, parameter=None) -> Verdict:
    """Check one action step against the static rules. Never raises.

    Never raises on purpose: this sits in front of dispatch, and a guard that
    can throw is a guard that can take down the assistant on a step it was
    supposed to merely refuse.
    """
    reasons: list[str] = []
    name = (action or "").strip()

    rule = ACTION_RULES.get(name)
    if rule is None:
        # Unknown to the guard means one of two things, both BLOCK: the router
        # hallucinated an action, or someone added one to executor without a
        # rule. The coverage gate exists so the second never reaches runtime.
        return Verdict(BLOCK, (f"no guard rule for action {name!r}",))

    fields = _fields(parameter)
    if len(fields) < rule.min_fields:
        reasons.append(
            f"{name} needs {rule.min_fields} parameter field(s), got "
            f"{len(fields)}")
    elif len(fields) > rule.max_fields:
        # Extra fields are how a positional handler gets fed an argument the
        # caller never intended — "path|content|--force" style smuggling. On
        # Windows '|' is illegal in filenames, so a pipe in a one-field shape
        # is malformed rather than merely unusual.
        reasons.append(
            f"{name} accepts at most {rule.max_fields} parameter field(s), "
            f"got {len(fields)}")
    elif fields and not fields[0].strip():
        reasons.append(f"{name} has an empty leading parameter field")

    if reasons:
        return Verdict(BLOCK, tuple(reasons))

    # Shape is sound; now the risk questions, both delegated.
    classifier = _sensei_classifier()
    if classifier is None:
        # No live classifier: cannot prove the step is safe, so do not claim it.
        # FLAG rather than BLOCK because this is our own plumbing being absent,
        # not evidence against the action.
        reasons.append("risk classifier unavailable — unverified")
    else:
        try:
            if classifier({"action": name, "parameter": parameter}):
                reasons.append("classified dangerous by existing safety net")
        except Exception as e:
            reasons.append(f"risk classifier errored ({e!r}) — unverified")

    if rule.screen:
        pattern = _risky_pattern()
        if pattern is None:
            reasons.append("keyword screen unavailable — unverified")
        else:
            hits = sorted({m.group(1).lower()
                           for m in pattern.finditer("|".join(fields))})
            if hits:
                reasons.append(f"risky keyword(s): {', '.join(hits)}")

    return Verdict(FLAG if reasons else ALLOW, tuple(reasons))
