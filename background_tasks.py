"""
background_tasks.py — the one place a slow action goes to stop blocking the voice
session.

WHY THIS EXISTS
Sensei is a voice interface, so wall-clock latency is not a performance detail —
it is dead air, and dead air is indistinguishable from a hang. Several real
actions legitimately take 30-300s (a repo-to-notes pass, a git clone, an
organize plan). Running those inline means the user says something and then
stares at a silent machine for two minutes, unable to issue another command.

WHAT GETS BACKGROUNDED — the rule, stated once
Background work whose product is an ARTIFACT (notes written to the vault, a
generated document, a cloned repo). Keep work whose product is an ANSWER
blocking (summaries read aloud, deliberate()'s reasoning pass), because the user
asked a question and is standing there waiting for the reply — handing them
"I'll get back to you" instead of an answer is worse than the wait.

That rule is why deliberate() is deliberately NOT in the table below despite
being slow: it is the router's abstain path, and its output is a spoken answer.

DESIGN NOTES
- Multi-task registry, not a single slot. Barely more code than one global (a
  dict instead of a variable) and it means a second request while the first is
  still running cannot silently vanish. No pool, no queue, no concurrency caps —
  Sensei's usage pattern is one human talking, so contention is not a concern.
- Threads, not asyncio. The whole codebase is synchronous and the slow calls are
  blocking network I/O (Anthropic SDK, requests, subprocess), so a daemon thread
  per task is the honest fit. There is nothing to gain from an event loop here.
- Completion is ANNOUNCED, never spoken from the worker thread. TTS and the VAD
  barge-in flag are owned by the main loop; a worker calling speak() directly
  would overlap audio streams and corrupt the barge-in state. Workers therefore
  drop a line in a queue and the main loop speaks it at the earliest safe point.
"""

import time
import itertools
import threading

# ── State ────────────────────────────────────────────────────────────────────
# One lock guards all three. It is an RLock because status_line() calls the
# same accessors the public functions do.
_LOCK = threading.RLock()
_TASKS: dict[int, dict] = {}
_ANNOUNCE: list[str] = []      # completed-task lines waiting to be spoken
_ids = itertools.count(1)

RUNNING, DONE, FAILED = "running", "done", "failed"

# Finished records are kept so "did that work?" can still be answered after the
# completion line was spoken. Bounded so a long uptime can't grow forever.
_MAX_FINISHED = 12


# ── What to background ───────────────────────────────────────────────────────
# action name -> None (always background) or the set of sub-actions to background
# (matched against field 0 of the pipe-delimited parameter, the same way
# sensei._is_dangerous_step reads it).
#
# Add a slow action HERE rather than writing threading code in the action: that
# is the entire point of this module. Quick mechanical actions (click, open tab,
# volume) must never be added — immediate feedback matters more there than
# freeing up the session.
#
# NOTE ON github_control: its slow sub-actions (repo notes, clone repo) are
# deliberately NOT listed here. They need browser context (the current repo URL)
# to resolve their target, and Selenium is not thread-safe — reading current_url
# from a worker while the main loop drives the same browser is a real race. Those
# resolve their target on the MAIN thread and then call start() themselves with
# the slow remainder. Same primitive, correct thread.
_BACKGROUND_RULES: dict[str, frozenset | None] = {
    # plan_organization(): 120s timeout, max_tokens=8000
    "obsidian_control": frozenset({"organize"}),
    # generates a whole document body
    "file_to_doc":      None,
}

# Spoken noun phrases for the acknowledgement. Falls back to a generic phrase, so
# a new entry in _BACKGROUND_RULES works without touching this.
_LABELS: dict[str, str] = {
    "repo_notes":  "writing up notes on that repo",
    "repo notes":  "writing up notes on that repo",
    "generate notes": "writing up notes on that repo",
    "architecture notes": "writing up notes on that repo",
    "clone repo":  "cloning that repo",
    "organize":    "organizing that into your vault",
    "file_to_doc": "turning that file into a document",
}


def _sub_action(parameter) -> str:
    """Field 0 of a pipe parameter, normalised like sensei's gate reads it."""
    if not isinstance(parameter, str):
        return ""
    return parameter.split("|")[0].strip().lower().replace("_", " ")


def should_background(action: str, parameter) -> str | None:
    """Spoken label if this step should run in the background, else None."""
    action = (action or "").strip()
    if action not in _BACKGROUND_RULES:
        return None
    subs = _BACKGROUND_RULES[action]
    sub = _sub_action(parameter)
    if subs is not None and sub not in subs:
        return None
    return _LABELS.get(sub) or _LABELS.get(action) or "that"


# ── Running tasks ────────────────────────────────────────────────────────────

def _prune_finished() -> None:
    finished = [(tid, t) for tid, t in _TASKS.items() if t["state"] != RUNNING]
    if len(finished) <= _MAX_FINISHED:
        return
    finished.sort(key=lambda kv: kv[1].get("finished") or 0.0)
    for tid, _ in finished[:len(finished) - _MAX_FINISHED]:
        _TASKS.pop(tid, None)


def is_running(label: str) -> bool:
    with _LOCK:
        return any(t["state"] == RUNNING and t["label"] == label
                   for t in _TASKS.values())


def running_count() -> int:
    with _LOCK:
        return sum(1 for t in _TASKS.values() if t["state"] == RUNNING)


def start(label: str, fn, *, ack: str | None = None) -> dict:
    """Run fn() on a daemon thread. Returns the result dict to speak NOW.

    fn should return the same {"success", "message"} shape actions already use;
    a plain string is accepted and treated as the message. Whatever it returns
    becomes the completion announcement, so it must be speakable.
    """
    # Same job already in flight — don't run it twice because the user repeated
    # themselves or the router emitted it twice.
    if is_running(label):
        return {"success": True, "speak": True,
                "message": f"I'm already {label} — I'll tell you when it's done."}

    with _LOCK:
        tid = next(_ids)
        _TASKS[tid] = {"id": tid, "label": label, "state": RUNNING,
                       "started": time.time(), "finished": None,
                       "message": ""}
        _prune_finished()

    def _run() -> None:
        try:
            result = fn()
        except Exception as e:
            print(f"[background] task {tid} ({label}) raised: {e!r}")
            _finish(tid, False, f"it failed with an error: {e}")
            return
        if isinstance(result, dict):
            ok = result.get("success") is not False
            msg = (result.get("message") or result.get("reason") or "").strip()
        else:
            ok = True
            msg = str(result or "").strip()
        print(f"[background] task {tid} ({label}) -> {ok} {msg[:80]!r}")
        _finish(tid, ok, msg)

    threading.Thread(target=_run, daemon=True,
                     name=f"bg-{tid}").start()
    print(f"[background] started task {tid}: {label}")
    return {"success": True, "speak": True,
            "message": ack or (f"I'll get started on {label} in the background "
                               f"and let you know when it's done.")}


def _finish(tid: int, ok: bool, message: str) -> None:
    """Record the outcome and queue the line the main loop will speak."""
    with _LOCK:
        task = _TASKS.get(tid)
        if task is None:
            return
        task["state"] = DONE if ok else FAILED
        task["finished"] = time.time()
        task["message"] = message
        label = task["label"]
        # Self-describing on purpose: this may be spoken minutes later, possibly
        # in a different session, long after the user forgot what they asked for.
        if ok:
            line = (f"Finished {label}. {message}" if message
                    else f"Finished {label}.")
        else:
            line = (f"That background job, {label}, didn't work out. {message}"
                    if message else f"I couldn't finish {label}.")
        _ANNOUNCE.append(line)


# ── Completion announcements (drained by sensei's main loop) ─────────────────

def has_announcements() -> bool:
    with _LOCK:
        return bool(_ANNOUNCE)


def take_announcements() -> list[str]:
    """Pop everything queued. Caller is responsible for actually speaking it."""
    with _LOCK:
        lines, _ANNOUNCE[:] = list(_ANNOUNCE), []
    return lines


# ── Status checks ("how's that going?") ─────────────────────────────────────

def _ago(seconds: float) -> str:
    secs = max(0, int(seconds))
    if secs < 60:
        return f"{secs} seconds"
    mins = secs // 60
    return f"{mins} minute{'s' if mins != 1 else ''}"


def status_line() -> str:
    """An honest current-state answer. Never silently ignores the question."""
    now = time.time()
    with _LOCK:
        running = [t for t in _TASKS.values() if t["state"] == RUNNING]
        finished = sorted((t for t in _TASKS.values() if t["state"] != RUNNING),
                          key=lambda t: t.get("finished") or 0.0)

        if running:
            # Below ~15s, an elapsed number is both useless and faintly absurd
            # ("going 0 seconds now"), so it just says it only just began.
            def _progress(t: dict) -> str:
                elapsed = now - t["started"]
                if elapsed < 15:
                    return f"{t['label']}, only just started"
                return f"{t['label']}, going {_ago(elapsed)} now"

            parts = [_progress(t) for t in running]
            if len(parts) == 1:
                line = f"Still working on it: {parts[0]}."
            else:
                line = ("I've got " + str(len(parts)) + " things running: "
                        + "; ".join(parts) + ".")
            # Mention the most recent completion too, so a status check right
            # after one finished doesn't sound like it never happened.
            if finished:
                last = finished[-1]
                line += (f" {'Also finished' if last['state'] == DONE else 'And this one failed'}"
                         f" {last['label']}.")
            return line

        if finished:
            last = finished[-1]
            elapsed = now - (last["finished"] or now)
            # "about 0 seconds ago" is worse than saying nothing about timing.
            when = "just now" if elapsed < 15 else f"about {_ago(elapsed)} ago"
            if last["state"] == DONE:
                return (f"That's done — I finished {last['label']} {when}. "
                        + (last["message"] or "")).strip()
            return (f"That one failed, {when}. "
                    + (last["message"] or "")).strip()

    return "I don't have anything running in the background right now."
