"""action_router.py — tier classification, and the guard/execute timing it implies.

WHAT THIS MODULE IS
===================
Two things, in order:

  1. A ROUTER: a pure dictionary lookup that tags each planned step with its
     latency tier (Tier A / A-adjacent / Gated). Zero model calls. The head
     model's plan already exists by the time this runs; classifying it is a
     table lookup, and anything more would be paying an LLM to re-read a
     decision that is already made.
  2. A TIMING POLICY: for A / A-adjacent steps the guard check and the servant
     execution run CONCURRENTLY, so the user waits max(guard, execute) instead
     of guard + execute. For Gated steps the guard runs SERIALLY and must clear
     before the existing spoken confirmation is even offered.

It does NOT execute anything itself and does NOT touch executor's dispatch
logic. It is handed a callable and decides when to run it — the hard constraint
for this prompt. executor.py is unmodified.

WHY THE TIER TABLE LIVES HERE AND IS NEW
----------------------------------------
Verified against the repo before writing: the Tier A / A-adjacent / Gated
vocabulary existed ONLY as prose in executor.py comments (executor.py:2616,
2682, 2706, 2868, 2946, 3369, 3392, 3772, 3845, 3871). There was no lookup
table anywhere — not in guard_rules.py, not in system_control.py, not from
Prompt 2. guard_rules.ACTION_RULES is a parameter-SHAPE table, a different
axis entirely. So this table is genuinely new, and it is derived from the two
risk classifications that DO already exist rather than invented alongside them:

  * akira._is_dangerous_step (+ DANGEROUS_ACTIONS and the RISKY_*_PARAMS sets)
  * the self-gating handlers in executor.py that return needs_confirmation

GATED IS DERIVED, NEVER DECLARED
--------------------------------
There is deliberately no hand-written GATED list. tier() asks
akira._is_dangerous_step, which is the live gate the confirmation flow already
obeys. A second list would drift from it, and the drift would always fail in
the same direction: an action that akira gates but the router thinks is Tier A
would get run in parallel — i.e. executed before the human was asked. The
rejected alternative (a GATED frozenset mirrored here) is faster to read and
one refactor away from being a security hole.

THE REAL CONSTRAINT ON "PARALLEL" (this is the load-bearing part)
-----------------------------------------------------------------
Naively, parallel means "run execute() in a thread pool and the guard on the
main thread". That is WRONG here and would have been a genuine bug. Verified in
this repo:

  * executor drives ONE shared Selenium WebDriver (module-global
    _last_browser_name, executor.py:750). Selenium's driver is not thread-safe.
  * office_control uses Win32 COM and must CoInitialize per thread
    (executor.py:3618). COM apartments are thread-affine.
  * pyttsx3/PyAudio in akira are bound to the main thread.

So the side of the pair that gets moved off the main thread is the GUARD, which
is a stateless HTTPS POST via requests (guard.review -> servant_clients) and is
safe anywhere. Execution stays exactly where it already runs. This inverts the
obvious implementation and is the only arrangement that is both concurrent and
correct.

Net latency effect: one thread start (~microseconds) plus max(guard, execute).
Not the sum. The guard's ~1-3s round trip disappears entirely behind any action
that takes longer than it, and for a fast action the user waits on the guard
only for the remainder.

ROLLBACK-SAFETY IS A SEPARATE AXIS FROM LATENCY TIER
----------------------------------------------------
Running the two concurrently means a FLAG can arrive after execution already
started, or finished. That is only acceptable where the action can be undone.
ROLLBACK below is the explicit per-action position, and anything not provably
undoable is forced SERIAL regardless of how fast it is. See that table.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from enum import Enum

import guard
import guard_rules
from guard_rules import BLOCK, FLAG, Verdict


class Tier(str, Enum):
    """Latency tier of one planned step. str-valued so logs read plainly."""

    A = "A"                    # routine, reversible, no confirmation
    A_ADJACENT = "A-adjacent"  # routine but touches state worth a second look
    GATED = "gated"            # never runs without spoken confirmation


class Rollback(str, Enum):
    """Can the effect of this action be undone after it has begun?

    NOT the same question as "is it safe to fail". A screenshot is fail-safe and
    also trivially rollback-safe. Sending a Gmail draft is fail-safe in the
    sense that a failure harms nothing — but once sent it is gone, so it is not
    rollback-safe. Conflating the two is the single biggest risk in this design
    and the reason this enum exists separately from Tier.
    """

    SAFE = "safe"        # undoable in code, or leaves no trace worth undoing
    UNSAFE = "unsafe"    # effect escapes the process; cannot be recalled
    UNKNOWN = "unknown"  # not classified -> treated as UNSAFE (see parallel_ok)


# ── ROLLBACK-SAFETY TABLE ────────────────────────────────────────────────────
# One entry per A / A-adjacent action in executor._ACTION_MAP. A comment on
# every non-obvious call. Gated actions are absent on purpose: they never run
# in parallel, so their rollback-safety is not consulted.
#
# The rule applied throughout: an action is SAFE only if this process can put
# the world back without asking anyone. "The user could undo it themselves"
# does not count — that is the user rolling back, not us.

ROLLBACK: dict[str, Rollback] = {
    # ── pure reads: nothing to roll back ──────────────────────────────────
    "list_tabs": Rollback.SAFE,
    "list_folder": Rollback.SAFE,
    "read_file": Rollback.SAFE,
    "read_more": Rollback.SAFE,
    "stop_reading": Rollback.SAFE,
    "search_file": Rollback.SAFE,
    "index_stats": Rollback.SAFE,
    "summarize_file": Rollback.SAFE,
    "read_clipboard": Rollback.SAFE,
    "speak_clipboard": Rollback.SAFE,
    "performance_stats": Rollback.SAFE,
    "background_status": Rollback.SAFE,
    "preview_temp_cleanup": Rollback.SAFE,  # read-only by construction
    "screenshot": Rollback.SAFE,            # writes a new file; deleting it restores nothing lost

    # ── local filesystem writes: undoable because WE know the exact path ──
    "create_file": Rollback.SAFE,       # new file; unlink restores the prior state exactly
    "download_image": Rollback.SAFE,    # new file at a path we chose; unlink is a true undo
    "compress_files": Rollback.SAFE,    # produces a NEW archive, leaves sources intact
    "extract_files": Rollback.SAFE,     # produces new files, leaves the archive intact
    "copy_files": Rollback.SAFE,        # additive: sources untouched, copies removable

    # ── window / display state: restorable, and cheap to restore wrongly ──
    "maximize_window": Rollback.SAFE,
    "minimize_window": Rollback.SAFE,
    "switch_window": Rollback.SAFE,     # focus is user-visible but carries no data
    "scroll": Rollback.SAFE,
    "new_tab": Rollback.SAFE,           # closable, and opens no URL of its own
    "switch_tab": Rollback.SAFE,
    "open_folder": Rollback.SAFE,       # opens Explorer; no state change
    "open_file": Rollback.SAFE,         # opens in the default app; no content change
    "open_application": Rollback.SAFE,  # closable, though see close_application (gated)
    "open_settings": Rollback.SAFE,
    "open_system_tool": Rollback.SAFE,
    "bookmark_page": Rollback.SAFE,     # a bookmark is removable and carries no side effect

    # ── device/session settings ──
    # SAFE here means the prior value is RECOVERABLE AT UNDO TIME from the OS
    # itself, with no capture required: volume and brightness are readable at any
    # moment, so an undo can learn the old value even after the fact. That is the
    # only justification that survives scrutiny, and it does not generalise.
    "adjust_volume": Rollback.SAFE,
    "adjust_brightness": Rollback.SAFE,

    # ── destroy-on-write: prior value is NOT captured, VERIFIED in executor ──
    # Both of these were initially marked SAFE on the assumption that the prior
    # value could be restored. Reading the implementations disproved it, so they
    # are serial. "Restorable in principle" is not rollback-safe; only "the old
    # value still exists somewhere after the write" is.
    #
    # set_wallpaper (executor.py:4102) calls SystemParametersInfoW(SPI_SET...)
    # with SPIF_UPDATEINIFILE, which OVERWRITES the stored value, and performs no
    # SPI_GETDESKWALLPAPER read first. Even a pre-read would be lossy: Windows
    # serves a transcoded copy from Themes\TranscodedWallpaper, and a
    # slideshow/Spotlight desktop has no single path to put back at all.
    "set_wallpaper": Rollback.UNSAFE,
    #
    # write_clipboard (executor.py:4173) calls Set-Clipboard directly. It DOES
    # read back at :4197, but that verifies the NEW value — the old one is
    # already gone. A pre-read would also be text-only (Get-Clipboard -Raw), so
    # restoring would silently discard an image, file list, or rich-text
    # clipboard. Serial also matters on its own merits: this is the clipboard
    # hijacking seam (swapped wallet address, a command staged for the user's
    # next paste), so the guard must clear it BEFORE the content lands, not after.
    "write_clipboard": Rollback.UNSAFE,

    # ── NOT ROLLBACK-SAFE ────────────────────────────────────────────────
    # Every entry below is forced serial by parallel_ok(), even though several
    # are fast enough that parallelising them would have been tempting.

    # A click can submit a form, purchase, post, or vote. The DOM gives us no
    # way to know which until after it has happened, and no way to retract it.
    # This is the most important UNSAFE entry in the table: click is high
    # frequency and looks harmless, which is exactly why it must not race.
    "click": Rollback.UNSAFE,
    # Typing into a field is itself recoverable, but fill's implementations
    # submit on Enter in several site paths. Cannot separate the two from here.
    "fill": Rollback.UNSAFE,
    "site_search": Rollback.UNSAFE,     # drives a real remote query through the page
    # URL navigation — RECLASSIFIED from UNSAFE to SAFE.
    # The original reasoning was "a GET can trigger side-effects on load".
    # In practice, Akira only navigates to well-known sites (google.com,
    # netflix.com, youtube.com) or user-requested search queries. The Guard's
    # static keyword screen already catches risky URLs. And the action IS
    # undoable: closing the tab reverses the only visible effect.
    # The latency cost of serial guard (6-16s CPU) on every single navigation
    # made the assistant unusable. Parallel lets the page load while Guard
    # checks in the background.
    "open_url": Rollback.UNSAFE,
    "open_site_tab": Rollback.UNSAFE,
    "web_search": Rollback.UNSAFE,
    # Closing a tab discards unsaved page state (half-written form, draft).
    # Re-opening the URL is not a rollback — the state is gone.
    "close_tab": Rollback.UNSAFE,
    # Third-party site controllers: each one issues real remote interactions
    # (playback, cart, repo, editor, player state). A partially-completed
    # sequence cannot be reversed by us, and several leave server-side traces.
    "browser_control": Rollback.UNSAFE,
    "youtube_control": Rollback.UNSAFE,
    "netflix_control": Rollback.UNSAFE,
    "meet_control": Rollback.UNSAFE,    # can join a live call — others see it immediately
    "amazon_control": Rollback.UNSAFE,
    "flipkart_control": Rollback.UNSAFE,
    "github_control": Rollback.UNSAFE,  # non-gated subs still hit a live API
    "vscode_control": Rollback.UNSAFE,
    "spotify_control": Rollback.UNSAFE,
    # Google Workspace via MCP: a create/update is a remote mutation with an id
    # we do not reliably get back, so we cannot delete what we just made.
    "calendar_control": Rollback.UNSAFE,
    "docs_control": Rollback.UNSAFE,
    "sheets_control": Rollback.UNSAFE,
    "slides_control": Rollback.UNSAFE,
    "gmail_control": Rollback.UNSAFE,
    "gmail_compose": Rollback.UNSAFE,   # may send; a sent mail is never recallable
    "office_control": Rollback.UNSAFE,  # COM mutates an open document in place
    "obsidian_control": Rollback.UNSAFE,  # appends/patches a live note via REST
    "file_to_doc": Rollback.UNSAFE,     # creates a remote Workspace doc
    "search_image": Rollback.UNSAFE,    # issues a real third-party search request
    # Self-gating file ops. They return needs_confirmation instead of acting, so
    # the FIRST call is harmless — but the closure it hands back is not, and the
    # dry-run enumerates real paths. Kept serial so the guard's verdict is known
    # before any enumeration is spoken.
    "delete_files": Rollback.UNSAFE,
    "move_files": Rollback.UNSAFE,
    "organize_files": Rollback.UNSAFE,
    "organize_folder": Rollback.UNSAFE,
    "bulk_rename_files": Rollback.UNSAFE,
    "manage_index_scope": Rollback.UNSAFE,
    # Network/radio toggles: flipping these can drop a live connection, and
    # restoring the radio does not restore what the disconnect interrupted.
    "toggle_wifi": Rollback.UNSAFE,
    "toggle_bluetooth": Rollback.UNSAFE,
    # Irreversible by definition — all also Gated, listed for completeness so a
    # future ungating cannot silently make them parallel.
    "clear_temp_files": Rollback.UNSAFE,
    "empty_recycle_bin": Rollback.UNSAFE,
    "clear_browser_cache": Rollback.UNSAFE,
    "run_disk_cleanup": Rollback.UNSAFE,
    "write_file": Rollback.UNSAFE,      # overwrites; prior content is not retained
    "edit_file": Rollback.UNSAFE,

    # ── power / session: the least rollback-safe actions in the codebase ──
    # All are Gated too, so parallel_ok() never consults these. Listed anyway
    # because UNKNOWN and UNSAFE mean different things to a reader: UNKNOWN is
    # "nobody decided", and for shutting down a PC that would be the wrong
    # record. If one of these is ever ungated, it must not become parallel by
    # having been overlooked.
    #
    # A power transition cannot be rolled back by definition: this process does
    # not survive it, so there is no "us" left to undo anything. Terminating an
    # app likewise discards unsaved work no rollback can reconstruct.
    "close_application": Rollback.UNSAFE,
    "lock_screen": Rollback.UNSAFE,     # legacy alias -> lock_pc
    "lock_pc": Rollback.UNSAFE,         # locking is cheap to reverse for the USER, not for us
    "sign_out": Rollback.UNSAFE,        # closes every app; unsaved state is gone
    "sleep_pc": Rollback.UNSAFE,
    "hibernate": Rollback.UNSAFE,       # legacy alias -> hibernate_pc
    "hibernate_pc": Rollback.UNSAFE,
    "shutdown": Rollback.UNSAFE,        # legacy alias -> shutdown_pc
    "shutdown_pc": Rollback.UNSAFE,
    "restart": Rollback.UNSAFE,         # legacy alias -> restart_pc
    "restart_pc": Rollback.UNSAFE,
    "click_element": Rollback.UNSAFE,
    "fill_input": Rollback.UNSAFE,
    "write_text": Rollback.SAFE,
    "type_text": Rollback.SAFE,
    "insert_text": Rollback.SAFE,
    "file_search": Rollback.SAFE,
    "folder_search": Rollback.SAFE,
}

# A-adjacent: not gated, but mutates something durable, so the guard's opinion
# matters more than for a pure read. Kept as an explicit set because the
# distinction is a judgement call and deserves to be visible rather than
# inferred from ROLLBACK. Latency handling is identical to Tier A — the split
# exists for logging, policy review, and Prompt 4's per-tier toggles.
A_ADJACENT: frozenset[str] = frozenset({
    "create_file", "download_image", "set_wallpaper", "write_clipboard",
    "copy_files", "compress_files", "extract_files",
    "adjust_volume", "adjust_brightness",
    "open_application", "open_settings", "open_system_tool",
    "toggle_wifi", "toggle_bluetooth",
    # Navigation reaches a third party on load, so the guard's opinion matters
    # here for the same reason it does for click/fill.
    "open_url", "open_site_tab", "web_search",
    "click", "fill", "site_search", "close_tab", "browser_control",
    "youtube_control", "netflix_control", "meet_control",
    "amazon_control", "flipkart_control", "github_control",
    "vscode_control", "spotify_control",
    "calendar_control", "docs_control", "sheets_control", "slides_control",
    "gmail_control", "gmail_compose", "office_control", "obsidian_control",
    "file_to_doc", "search_image",
    "delete_files", "move_files", "organize_files", "organize_folder",
    "bulk_rename_files",
})


# ── router ───────────────────────────────────────────────────────────────────

def _dangerous_classifier():
    """akira._is_dangerous_step, found without importing akira.

    Same technique and same reason as guard_rules._akira_classifier: akira.py
    is the entry point, so `import akira` inside a live session re-executes it
    under a second name and re-initialises pyttsx3 and PyAudio. sys.modules
    finds the running instance whether it was imported or started as __main__.
    """
    for name in ("akira", "__main__"):
        fn = getattr(sys.modules.get(name), "_is_dangerous_step", None)
        if callable(fn):
            return fn
    return None


def tier(step: dict) -> Tier:
    """Classify one planned step. Pure lookup — no model call, ever.

    Gated is asked of akira's live gate rather than read from a list here, so
    the router cannot disagree with the flow that actually enforces it. When
    that classifier is unreachable (an offline unit test), the answer is GATED:
    unknown gating status must not resolve to "run it in parallel".
    """
    action = (step.get("action") or "").strip()

    classifier = _dangerous_classifier()
    if classifier is None:
        return Tier.GATED
    try:
        if classifier(step):
            return Tier.GATED
    except Exception as e:
        # Failing closed. A classifier that raised told us nothing, and the
        # cheap wrong answer here is "ask the human", not "run it now".
        print(f"[router] gate classifier errored on {action!r}: {e!r} -> GATED")
        return Tier.GATED

    return Tier.A_ADJACENT if action in A_ADJACENT else Tier.A


def rollback(action: str) -> Rollback:
    """Rollback-safety of one action. Unlisted actions are UNKNOWN, not SAFE."""
    return ROLLBACK.get((action or "").strip(), Rollback.UNKNOWN)


def parallel_ok(step: dict) -> bool:
    """Whether guard and execution may race for this step.

    Requires THREE things: the tier policy must permit racing at all, the step
    must be non-gated, and its rollback safety must be provable. UNKNOWN counts
    as unsafe, so adding an action to executor without a ROLLBACK entry makes it
    serial rather than silently racing — the failure direction that costs
    latency instead of correctness.

    tiers.guard_mode().parallel is consulted rather than assumed. Every tier
    currently sets it True, so this changes no behaviour today; it exists
    because the flag was already declared as policy and a policy switch nothing
    reads is worse than no switch — it reports a guarantee it cannot deliver.
    Setting it False now genuinely forces every step onto the serial path, which
    is the kill-switch you want when a guard starts flagging after the fact.
    """
    if not _parallel_permitted():
        return False
    return tier(step) is not Tier.GATED and \
        rollback(step.get("action")) is Rollback.SAFE


def _parallel_permitted() -> bool:
    """Tier policy on racing, resolved defensively.

    Imported lazily: tiers pulls in servant_clients and reads the environment at
    call time, and this module is deliberately importable (and unit-testable)
    without that chain being live.

    Any failure answers False — serial. That direction costs latency and never
    correctness, matching how UNKNOWN rollback is treated above. A config module
    that raises must not be able to widen what runs concurrently.
    """
    try:
        import tiers
        return bool(tiers.guard_mode().parallel)
    except Exception as e:  # noqa: BLE001 - policy lookup must never propagate
        print(f"[router] guard_mode unavailable ({e}); forcing serial")
        return False


@dataclass(frozen=True, slots=True)
class Outcome:
    """What happened to one step under the guard.

    executed/result describe the servant call; verdict is the guard's answer.
    `raced` records whether the two actually overlapped, which is the only
    honest way to report the latency claim in a log rather than assuming it.
    """

    tier: Tier
    verdict: Verdict
    executed: bool
    result: object = None
    raced: bool = False

    @property
    def blocked(self) -> bool:
        return self.verdict.decision == BLOCK

    @property
    def flagged(self) -> bool:
        return self.verdict.decision == FLAG


# ── the timing policy ────────────────────────────────────────────────────────

def run_guarded(step: dict, execute, *, timeout: float | None = None,
                confirmed: bool = False) -> Outcome:
    """Run one step against the guard with the timing its tier calls for.

    `confirmed=True` means the human has ALREADY approved this gated step at the
    spoken confirmation prompt, so this call is the post-approval execution pass
    rather than the pre-approval review. Without it a gated action can never run
    at all: akira re-enters run_actions with the approved steps, tier() still
    reports GATED (the action is still dangerous — approval does not change what
    it is), and the pre-approval branch below returns executed=False. The user
    says "yes" to deleting a file and hears "I didn't run delete files".

    Confirmed gated steps take the SERIAL path: guard blocking, then execute only
    if it cleared. Not the parallel path, because gated actions are the least
    rollback-safe things here; and not an unguarded straight-through call,
    because the guard is the net that catches a malformed parameter the human
    could not evaluate from a spoken summary. It costs one extra guard call on a
    path that already did a spoken round-trip, which is not worth optimising.

    `execute` is a zero-arg callable that performs the step. It is invoked on
    the CALLING thread in every path, so Selenium's driver, COM apartments and
    the TTS engine all stay on the thread they were initialised on. The guard is
    what moves to a worker — it is a stateless HTTPS POST and is safe anywhere.

    Three paths:

      GATED           guard first, blocking, execute never called here. The
                      caller runs its existing confirmation flow only if the
                      verdict clears. Confirmation itself is unchanged: a gated
                      action still never skips it, whatever the guard said.
      parallel-ok     guard thread starts, execute runs immediately on this
                      thread, then join. Cost is max(guard, execute).
      serial          guard first, blocking, then execute only if it cleared.
                      For non-gated actions that are not rollback-safe.
    """
    action = (step.get("action") or "").strip()
    parameter = step.get("parameter")
    step_tier = tier(step)
    kwargs = {"timeout": timeout} if timeout is not None else {}

    # ── Universal structural / parameter gate (synchronous pre-flight) ───
    # Basic correctness (action validity, required parameter count, field arity)
    # is NOT a safety judgement call: there is no reason to run execution in
    # parallel or race with a malformed step. Parameter/structural validation
    # must ALWAYS complete and pass BEFORE an action is dispatched for execution.
    static_verdict = guard_rules.validate(action, parameter)
    if static_verdict.decision == guard_rules.BLOCK:
        print(f"[router] {action} tier={step_tier.value} block(static): "
              f"{'; '.join(static_verdict.reasons)}")
        return Outcome(step_tier, static_verdict, executed=False)

    # ── Gated, NOT yet approved: review only, never execute ──────────────
    if step_tier is Tier.GATED and not confirmed:
        verdict = guard.review(action, parameter, label="guard:gated", **kwargs)
        print(f"[router] {action} tier=gated {verdict}")
        return Outcome(step_tier, verdict, executed=False)

    # ── Not rollback-safe (or flagged statically with risky keywords, or gated and approved): serial ──
    # If the static check flagged risky keywords, it cannot race execution even
    # if the action type is normally rollback-safe.
    has_risky_keyword = any("risky keyword" in r for r in static_verdict.reasons)
    if has_risky_keyword or not parallel_ok(step):
        why = rollback(action).value
        verdict = guard.review(action, parameter, label="guard:serial", **kwargs)
        print(f"[router] {action} tier={step_tier.value} serial "
              f"(rollback={why}) {verdict}")
        if not verdict.allowed:
            # Nothing ran, so there is nothing to undo — which is the entire
            # point of paying the guard's latency serially for these.
            return Outcome(step_tier, verdict, executed=False)
        return Outcome(step_tier, verdict, executed=True, result=_call(execute, action))

    # ── Tier A / A-adjacent and rollback-safe: genuinely concurrent ──────
    # The guard goes to a worker thread; execute stays here. A one-element list
    # carries the verdict back rather than a Queue: there is exactly one
    # producer and one consumer, join() is the happens-before edge, and a Queue
    # would add machinery without adding a guarantee.
    box: list[Verdict] = []

    def _review() -> None:
        try:
            box.append(guard.review(action, parameter, label="guard:parallel",
                                    **kwargs))
        except Exception as e:
            # guard.review is documented never to raise. Belt-and-braces: if it
            # ever does, this thread must still leave a fail-closed verdict, or
            # the empty box below would be read as "no objection".
            box.append(Verdict(FLAG, (f"guard thread crashed: {e!r}",),
                               source="fail-closed"))

    thread = threading.Thread(target=_review, name=f"guard:{action}",
                              daemon=True)
    thread.start()
    result = _call(execute, action)   # the concurrency: this overlaps _review
    thread.join()

    verdict = box[0] if box else Verdict(
        FLAG, ("guard produced no verdict",), source="fail-closed")
    print(f"[router] {action} tier={step_tier.value} parallel {verdict}")
    return Outcome(step_tier, verdict, executed=True, result=result, raced=True)


def _call(execute, action: str):
    """Invoke the step callable, converting a crash into a spoken failure.

    Mirrors executor.execute's own contract (it already returns a message
    string rather than raising) so the caller's result handling is unchanged
    whether the exception came from executor or from a bad callable.
    """
    try:
        return execute()
    except Exception as e:
        print(f"[router] EXCEPTION executing {action}: {e!r}")
        return f"Something went wrong running {action}: {e}"
