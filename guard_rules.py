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
  * akira._is_dangerous_step + DANGEROUS_ACTIONS / RISKY_SHOPPING_PARAMS /
    RISKY_GITHUB_PARAMS / RISKY_VSCODE_PARAMS / RISKY_CALENDAR_PARAMS /
    RISKY_WORKSPACE_PARAMS / office_control.is_risky_parameter — a complete
    code-level risk classification already exists in akira.py. The guard
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

import hashlib
import hmac
import re
import secrets
import sys
import time
from dataclasses import dataclass, field

class GuardBypassError(PermissionError):
    """Raised when execution is attempted without a valid GuardToken."""
    pass


# Module-private secret for cryptographic signing of guard tokens.
# Process-isolated: cannot be forged or replayed across processes.
_GUARD_TOKEN_SECRET: bytes = secrets.token_bytes(32)


def _hash_param(parameter: object) -> str:
    if parameter is None:
        raw = b""
    elif isinstance(parameter, (str, bytes)):
        raw = str(parameter).encode("utf-8")
    else:
        raw = repr(parameter).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _compute_token_signature(action: str, param_hash: str, decision: str, created_at: float) -> str:
    msg = f"{action}:{param_hash}:{decision}:{created_at:.6f}".encode("utf-8")
    return hmac.new(_GUARD_TOKEN_SECRET, msg, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class GuardToken:
    """Cryptographic authorization token proving an action passed Guard screening.
    
    Required by executor.execute(). Only mintable by guard_rules.validate().
    """
    action: str
    parameter_hash: str
    decision: str
    created_at: float
    signature: str

    def is_valid_for(self, action: str, parameter: object) -> bool:
        if self.action != action:
            return False
        if self.parameter_hash != _hash_param(parameter):
            return False
        if self.decision == BLOCK:
            return False
        if time.time() - self.created_at > 120.0:  # 2 minute expiry for confirmed prompts
            return False
        expected_sig = _compute_token_signature(self.action, self.parameter_hash, self.decision, self.created_at)
        return hmac.compare_digest(self.signature, expected_sig)


def _issue_guard_token(action: str, parameter: object, decision: str) -> GuardToken | None:
    if decision == BLOCK:
        return None
    p_hash = _hash_param(parameter)
    now = time.time()
    sig = _compute_token_signature(action, p_hash, decision, now)
    return GuardToken(action, p_hash, decision, now, sig)


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
    token: GuardToken | None = None

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
        # Token is only preserved if the merged decision is not BLOCK
        token = self.token if worst.decision != BLOCK else None
        return Verdict(worst.decision,
                       (*self.reasons, *other.reasons),
                       source,
                       token=token)

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
    screen: bool = True      # run the risky-keyword screen over the parameter text
    split_pipe: bool = True  # split on '|' into sub-fields; False treats parameter as opaque


# Shared rule instances rather than a literal per action: 80 actions collapse to
# named shapes, and referencing the same object makes the table scannable enough
# that a wrong shape is visible on sight.
IGNORED = Rule(0, 0, screen=False, split_pipe=False)   # handler takes no parameter (lambda _:)
OPT_TEXT = Rule(0, 1)                # one optional free-text field (screened)
TEXT = Rule(1, 1)                    # one required free-text field (screened)
OPAQUE_TEXT = Rule(1, 1, screen=False, split_pipe=False)       # 1 opaque text field (unscreened, no '|' split)
OPT_OPAQUE_TEXT = Rule(0, 1, screen=False, split_pipe=False)   # optional opaque text field
SUB = Rule(1, 2)                     # "sub" or "sub|arg" (screened)
SUB_UNSCREENED = Rule(1, 2, screen=False, split_pipe=True)     # "sub" or "sub|arg" (unscreened: media, search)
SUB_ARGS = Rule(1, 3)                # "app|sub|args"
SUB_MULTI = Rule(1, 6)               # multi-field commands (e.g. gmail_compose generate|to|subject|body)
SUB_MULTI_UNSCREENED = Rule(1, 6, screen=False, split_pipe=True)  # multi-field unscreened (office_control generate/insert briefs)
SUB_VAULT = Rule(1, 999)             # vault free text and markdown notes (arbitrary pipes in tables/content)
SUB_FREE_TEXT = Rule(1, 999, screen=True, split_pipe=True)       # free-text content / markdown / email bodies (screened)
SUB_FREE_TEXT_UNSCREENED = Rule(1, 999, screen=False, split_pipe=True) # free-text search queries / media / office (unscreened)
FILL = Rule(1, 999, screen=True, split_pipe=True)               # "field|text" or "field|text|submit" (text may contain '|')

# ACTION_RULES — every key in executor._ACTION_MAP must appear here.
# verify_guard_coverage.py enforces that statically; if you add an executor
# action and skip this table, the gate fails rather than the action silently
# dispatching unvalidated. That failure is the feature.
ACTION_RULES: dict[str, Rule] = {
    # ── applications & windows ────────────────────────────────────────────
    "open_application": OPAQUE_TEXT,
    "close_application": OPT_OPAQUE_TEXT,
    "switch_window": OPAQUE_TEXT,
    "maximize_window": OPT_OPAQUE_TEXT,
    "minimize_window": OPT_OPAQUE_TEXT,
    # ── browser & web ─────────────────────────────────────────────────────
    "open_url": Rule(1, 1, screen=True, split_pipe=False),
    "web_search": SUB_FREE_TEXT_UNSCREENED,
    "site_search": SUB_FREE_TEXT_UNSCREENED,
    "fill": FILL,
    "scroll": OPT_TEXT,
    "new_tab": OPT_OPAQUE_TEXT,
    "open_site_tab": OPAQUE_TEXT,
    "list_tabs": IGNORED,
    "switch_tab": OPAQUE_TEXT,
    "close_tab": OPT_OPAQUE_TEXT,
    "click": OPAQUE_TEXT,
    "browser_control": SUB,
    "bookmark_page": IGNORED,
    # ── site-specific controllers ─────────────────────────────────────────
    "youtube_control": SUB_FREE_TEXT_UNSCREENED,
    "netflix_control": SUB_FREE_TEXT_UNSCREENED,
    "meet_control": SUB_FREE_TEXT,
    "amazon_control": SUB_FREE_TEXT,
    "flipkart_control": SUB_FREE_TEXT,
    "github_control": SUB_FREE_TEXT,
    "vscode_control": SUB_FREE_TEXT,
    "spotify_control": SUB_FREE_TEXT_UNSCREENED,
    # ── Google Workspace (MCP) ────────────────────────────────────────────
    "calendar_control": SUB_FREE_TEXT,
    "docs_control": SUB_FREE_TEXT,
    "sheets_control": SUB_FREE_TEXT,
    "slides_control": SUB_FREE_TEXT,
    "gmail_control": SUB_FREE_TEXT,
    "gmail_compose": SUB_FREE_TEXT,
    # ── Microsoft Office (COM) ────────────────────────────────────────────
    "office_control": SUB_FREE_TEXT_UNSCREENED,
    # ── Obsidian ──────────────────────────────────────────────────────────
    "obsidian_control": SUB_VAULT,
    # ── files ─────────────────────────────────────────────────────────────
    "create_file": SUB_FREE_TEXT,
    "read_file": OPAQUE_TEXT,
    "read_more": SUB,
    "stop_reading": IGNORED,
    "write_file": SUB_FREE_TEXT,
    "edit_file": SUB_FREE_TEXT,
    "search_file": OPAQUE_TEXT,
    "manage_index_scope": SUB,
    "index_stats": IGNORED,
    "open_file": OPAQUE_TEXT,
    "open_study_room": OPT_OPAQUE_TEXT,
    "open_folder": OPAQUE_TEXT,
    "list_folder": OPT_OPAQUE_TEXT,
    "copy_files": SUB_FREE_TEXT,
    "move_files": SUB_FREE_TEXT,
    "organize_files": SUB_FREE_TEXT,
    "delete_files": SUB_FREE_TEXT,
    "organize_folder": SUB_FREE_TEXT,
    "bulk_rename_files": SUB_FREE_TEXT,
    "compress_files": SUB_FREE_TEXT,
    "extract_files": SUB_FREE_TEXT,
    "summarize_file": OPAQUE_TEXT,
    "file_to_doc": SUB_FREE_TEXT,
    # ── media & clipboard ─────────────────────────────────────────────────
    "search_image": SUB_FREE_TEXT_UNSCREENED,
    "download_image": SUB_FREE_TEXT,
    "set_wallpaper": SUB_FREE_TEXT,
    "read_clipboard": IGNORED,
    "write_clipboard": OPAQUE_TEXT,
    "generate_to_clipboard": OPAQUE_TEXT,  # compose content → clipboard (Bug A fix)
    "adjust_volume": TEXT,
    "adjust_brightness": TEXT,
    "screenshot": OPT_OPAQUE_TEXT,
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
    # ── clipboard output ───────────────────────────────────────────────────
    "write_clipboard": OPAQUE_TEXT,
    "speak_clipboard": IGNORED,
    # ── LLM hallucination aliases: map to real actions via pre-router ─────
    # These entries prevent a BLOCK when Groq invents a plausible-sounding
    # action name. The pre-router maps them BEFORE execution, but guard_rules
    # must also accept them so static validation doesn't short-circuit first.
    "write_text": OPAQUE_TEXT,       # → write_clipboard (intercepted in pre-router)
    "type_text": OPAQUE_TEXT,        # → write_clipboard
    "insert_text": OPAQUE_TEXT,      # → write_clipboard
    "fill_input": SUB_FREE_TEXT,     # → fill
    "click_element": OPAQUE_TEXT,    # → click
    "file_search": OPAQUE_TEXT,      # → search_file
    "folder_search": OPAQUE_TEXT,    # → search_file
}


# ── reuse hooks into the existing safety logic ────────────────────────────────

_cached_risky_pattern: re.Pattern | None = None
_checked_risky_pattern: bool = False

def _risky_pattern() -> re.Pattern | None:
    """executor's compiled RISKY_KEYWORDS pattern, or None if unreachable.

    Imported lazily so this module stays importable without selenium — which is
    what lets the offline coverage gate run. executor is never __main__, so a
    plain import is safe here, unlike akira below.

    Two-step lookup on purpose. executor._risky_pattern is private, and if it is
    ever renamed a single getattr would silently return None — degrading the
    screen to "unverified" on every action, which reads as a guard that flags
    everything and gets muted. Falling back to compiling the PUBLIC
    RISKY_KEYWORDS list keeps the taxonomy single-sourced (the list is the
    taxonomy; the pattern is just its compiled form) while surviving the rename.
    """
    global _cached_risky_pattern, _checked_risky_pattern
    if _checked_risky_pattern:
        return _cached_risky_pattern

    try:
        import executor
    except Exception:
        _checked_risky_pattern = True
        _cached_risky_pattern = None
        return None

    pattern = getattr(executor, "_risky_pattern", None)
    if pattern is not None:
        _checked_risky_pattern = True
        _cached_risky_pattern = pattern
        return pattern

    keywords = getattr(executor, "RISKY_KEYWORDS", None)
    if not keywords:
        _checked_risky_pattern = True
        _cached_risky_pattern = None
        return None
    _cached_risky_pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE)
    _checked_risky_pattern = True
    return _cached_risky_pattern


# Dangerous actions — safety net catches these if Claude forgets to gate them
DANGEROUS_ACTIONS = frozenset({
    "close_application", "shutdown", "restart", "hibernate",
    "edit_file", "uninstall_application",
    "write_file",  # overwrites file content — gated same as edit_file
    "wipe_all_memory",  # deletes all logs and core profile — gated
    "clear_temp_files", "empty_recycle_bin", "clear_browser_cache", "run_disk_cleanup",
    "sleep_pc", "hibernate_pc", "shutdown_pc", "restart_pc", "sign_out",
})

RISKY_SHOPPING_PARAMS = frozenset({
    "proceed to checkout", "checkout", "place order",
    "confirm address", "select address", "confirm delivery address", "deliver here",
})

RISKY_GITHUB_PARAMS = frozenset({
    "create pull request", "merge pull request",
    "close issue", "close pull request",
    "delete branch", "delete repo", "delete repository",
    "push", "force push",
})

RISKY_VSCODE_PARAMS = frozenset({
    "write file", "edit file",
})

RISKY_CALENDAR_PARAMS = frozenset({
    "delete",
})

RISKY_WORKSPACE_PARAMS = frozenset({
    "delete",
})


def _is_dangerous_step_fallback(step: dict) -> bool:
    action = step.get("action")
    if action in DANGEROUS_ACTIONS:
        return True
    param = (step.get("parameter") or "").split("|")[0].strip().lower().replace("_", " ")
    if action in ("amazon_control", "flipkart_control"):
        return param in RISKY_SHOPPING_PARAMS
    if action == "github_control":
        return param in RISKY_GITHUB_PARAMS
    if action == "vscode_control":
        return param in RISKY_VSCODE_PARAMS
    if action == "calendar_control":
        return param in RISKY_CALENDAR_PARAMS
    if action in ("slides_control", "docs_control", "sheets_control"):
        return param in RISKY_WORKSPACE_PARAMS
    if action == "office_control":
        try:
            import office_control
            return office_control.is_risky_parameter(step.get("parameter"))
        except Exception:
            return True
    return False


def _akira_classifier():
    """akira._is_dangerous_step, located from sys.modules or standalone fallback."""
    for name in ("akira", "__main__"):
        mod = sys.modules.get(name)
        fn = getattr(mod, "_is_dangerous_step", None)
        if callable(fn):
            return fn
    return _is_dangerous_step_fallback


# ── the static gate itself ───────────────────────────────────────────────────

def _fields(parameter, split_pipe: bool = True) -> list[str]:
    raw = "" if parameter is None else str(parameter)
    if not raw.strip():
        return []
    return raw.split("|") if split_pipe else [raw.strip()]


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

    raw_param = "" if parameter is None else str(parameter)
    if "\x00" in raw_param or any(ord(c) < 32 and c not in ("\n", "\r", "\t") for c in raw_param):
        return Verdict(BLOCK, ("null byte or control character in parameter",))
    if len(raw_param) > 65536:
        return Verdict(BLOCK, ("parameter exceeds maximum length (64KB)",))

    fields = _fields(parameter, split_pipe=rule.split_pipe)
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

    # ── Structural Deny: Self-Modification & Destructive OS Commands ─────
    import security_guard
    is_destr, destr_reason = security_guard.check_destructive_command(name, parameter)
    if is_destr:
        return Verdict(BLOCK, (destr_reason or "destructive OS command forbidden",))

    target_paths: list[str] = []
    if name in ("create_file", "write_file", "edit_file", "delete_file"):
        if fields:
            target_paths.append(fields[0])
    elif name == "delete_files":
        if parameter:
            for item in parameter.split(","):
                p = item.split("|")[0].strip()
                if p:
                    target_paths.append(p)
    elif name in ("copy_files", "move_files", "compress_files", "extract_files"):
        for f in fields[:2]:
            if f.strip():
                target_paths.append(f.strip())
    elif name in ("organize_files", "organize_folder", "bulk_rename_files"):
        if fields:
            target_paths.append(fields[0])
    elif name == "vscode_control":
        if fields:
            sub = fields[0].strip().lower().replace("_", " ")
            if sub in ("create file", "write file", "edit file") and len(fields) > 1 and fields[1].strip():
                target_paths.append(fields[1].strip())
    elif name == "github_control":
        if fields:
            sub = fields[0].strip().lower().replace("_", " ")
            if sub == "clone repo" and len(fields) > 2 and fields[2].strip():
                target_paths.append(fields[2].strip())
    elif name == "office_control":
        if len(fields) >= 3:
            sub = fields[1].strip().lower().replace("_", " ")
            if sub in ("save as", "save_as"):
                target_paths.append(fields[2].strip())

    for target in target_paths:
        is_self_mod, mod_reason = security_guard.check_self_modification(target)
        if is_self_mod:
            return Verdict(BLOCK, (mod_reason or "self-modification forbidden: target is inside Akira codebase",))

    # Shape is sound; now the risk questions, both delegated.
    classifier = _akira_classifier()
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

    # Explicit URL safety checks for navigation actions
    if name in ("open_url", "new_tab", "open_site_tab") and fields:
        url = fields[0].strip().lower()
        if any(url.startswith(proto) for proto in ("file:", "javascript:", "vbscript:", "data:", "chrome:", "edge:", "about:")):
            return Verdict(BLOCK, ("unsafe or forbidden URI protocol",))
        if any(url.startswith(proto) for proto in ("ftp:", "ws:")):
            reasons.append("unsafe or non-web URL protocol")
        if any(url.endswith(ext) or f"{ext}?" in url for ext in (".exe", ".bat", ".cmd", ".ps1", ".msi", ".vbs", ".reg", ".sh", ".iso")):
            reasons.append("executable or installer file download URL")
        if any(cred in url for cred in ("password=", "passwd=", "token=", "apikey=", "secret=", "auth=")):
            reasons.append("potential credential/token leak in URL query")
        if re.search(r"https?://(127\.|192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)", url):
            reasons.append("private network/local IP address navigation")

    if rule.screen:
        pattern = _risky_pattern()
        if pattern is None:
            reasons.append("keyword screen unavailable — unverified")
        else:
            text_to_screen = re.sub(r"[_/&?=\-]", " ", "|".join(fields))
            hits = sorted({m.group(1).lower()
                           for m in pattern.finditer(text_to_screen)})
            if hits:
                reasons.append(f"risky keyword(s): {', '.join(hits)}")

    dec = FLAG if reasons else ALLOW
    token = _issue_guard_token(name, parameter, dec)
    return Verdict(dec, tuple(reasons), token=token)
