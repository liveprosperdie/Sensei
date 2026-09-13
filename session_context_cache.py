"""session_context_cache.py — In-memory desktop state caching and diffing for Akira.

Captures full desktop/browser/window state on session start (turn 1) and
computes minimal delta objects on subsequent turns (turns 2+) to eliminate
wasteful token usage and reduce data exposure.

All state is kept in-memory only — never written to disk.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("akira.session_context_cache")


@dataclass
class DesktopState:
    """Snapshot of visible desktop and browser context."""
    foreground_app: str = "unknown"
    open_windows: list[str] = field(default_factory=list)
    tabs: list[dict[str, str]] = field(default_factory=list)
    current_url: str | None = None
    current_page_title: str | None = None
    note_context: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "foreground_app": self.foreground_app,
            "open_windows": list(self.open_windows),
            "tabs": [dict(t) for t in self.tabs],
            "current_url": self.current_url,
            "current_page_title": self.current_page_title,
            "note_context": self.note_context,
            "timestamp": self.timestamp,
        }


class SessionContextCache:
    """In-memory cache tracking desktop state across turns of an active session."""

    def __init__(self) -> None:
        self._cached_state: DesktopState | None = None
        self._current_session_id: str | None = None
        self._turn_index: int = 0

    @property
    def turn_index(self) -> int:
        return self._turn_index

    @property
    def session_id(self) -> str | None:
        return self._current_session_id

    def start_session(self, session_id: str) -> None:
        """Start a new session: clears previous cache and resets turn index to 0."""
        self._current_session_id = session_id
        self._cached_state = None
        self._turn_index = 0
        logger.info("[SessionContextCache] Session %s started — cache reset", session_id)

    def reset(self) -> None:
        """Reset all in-memory cached state."""
        self._cached_state = None
        self._turn_index = 0

    def capture_state(self, get_pc_context_fn, get_all_tabs_fn, get_note_fn=None) -> DesktopState:
        """Query local PC APIs for current desktop and browser state."""
        try:
            ctx = get_pc_context_fn() if callable(get_pc_context_fn) else {}
        except Exception as e:
            logger.warning("[SessionContextCache] get_pc_context failed: %s", e)
            ctx = {}

        try:
            tabs = get_all_tabs_fn() if callable(get_all_tabs_fn) else []
        except Exception as e:
            logger.warning("[SessionContextCache] get_all_tabs failed: %s", e)
            tabs = []

        note_ctx = ""
        if callable(get_note_fn):
            try:
                note_ctx = get_note_fn() or ""
            except Exception:
                note_ctx = ""

        windows = ctx.get("open_windows") or []
        cleaned_windows = [w for w in windows if isinstance(w, str) and w.strip()][:10]

        cleaned_tabs = []
        for t in tabs:
            if isinstance(t, dict) and t.get("title"):
                cleaned_tabs.append({
                    "title": str(t.get("title", "")).strip(),
                    "url": str(t.get("url", "")).strip()
                })

        return DesktopState(
            foreground_app=str(ctx.get("foreground_app") or "unknown"),
            open_windows=cleaned_windows,
            tabs=cleaned_tabs,
            current_url=ctx.get("current_url"),
            current_page_title=ctx.get("current_page_title"),
            note_context=note_ctx,
            timestamp=time.time(),
        )

    def compute_delta(self, prev: DesktopState, curr: DesktopState) -> dict[str, Any]:
        """Compute minimal delta dictionary containing only changed fields."""
        delta: dict[str, Any] = {}

        # 1. Foreground app
        if curr.foreground_app != prev.foreground_app:
            delta["foreground_app_changed"] = True
            delta["new_foreground_app"] = curr.foreground_app

        # 2. Windows
        prev_win = prev.open_windows
        curr_win = curr.open_windows
        if curr_win != prev_win:
            prev_win_set = set(prev_win)
            curr_win_set = set(curr_win)
            opened = [w for w in curr_win if w not in prev_win_set]
            closed = [w for w in prev_win if w not in curr_win_set]

            if curr_win and (not prev_win or curr_win[0] != prev_win[0]):
                delta["active_window_changed"] = True
                delta["new_window"] = curr_win[0]
            if opened:
                delta["opened_windows"] = opened[:5]
            if closed:
                delta["closed_windows"] = closed[:5]

        # 3. Tabs
        prev_tab_titles = [t["title"] for t in prev.tabs if t.get("title")]
        curr_tab_titles = [t["title"] for t in curr.tabs if t.get("title")]
        if curr_tab_titles != prev_tab_titles:
            prev_tabs_set = set(prev_tab_titles)
            curr_tabs_set = set(curr_tab_titles)
            opened_tabs = [t for t in curr_tab_titles if t not in prev_tabs_set]
            closed_tabs = [t for t in prev_tab_titles if t not in curr_tabs_set]

            if opened_tabs or closed_tabs:
                delta["tabs_changed"] = True
                if opened_tabs:
                    delta["opened_tabs"] = opened_tabs[:8]
                if closed_tabs:
                    delta["closed_tabs"] = closed_tabs[:8]
            if curr_tab_titles and (not prev_tab_titles or curr_tab_titles[0] != prev_tab_titles[0]):
                delta["active_tab"] = curr_tab_titles[0]

        # 4. URL
        if curr.current_url != prev.current_url:
            delta["url_changed"] = True
            delta["new_url"] = curr.current_url or "none"

        # 5. Note context
        if curr.note_context != prev.note_context:
            delta["note_changed"] = True
            delta["new_note"] = curr.note_context

        if not delta:
            return {"changed": False}
        delta["changed"] = True
        return delta

    def format_full_context(self, state: DesktopState, action_lines: list[str] | None = None) -> str:
        """Format complete desktop state for turn 1."""
        tabs_str = ", ".join(t["title"] for t in state.tabs[:8] if t.get("title")) or "none"
        windows_str = ", ".join(state.open_windows[:5]) or "none"
        url_str = state.current_url or "none"

        actions_block = ""
        if action_lines:
            actions_block = "[RECENT ACTIONS THIS SESSION]\n" + "\n".join(action_lines) + "\n\n"

        tabs_block = f"[CURRENT BROWSER TABS]\n{tabs_str}\n\n"

        raw_ctx = (
            f"Focused app: {state.foreground_app} | "
            f"Current page: {url_str} | "
            f"Windows: {windows_str}"
            + (f" | {state.note_context}" if state.note_context else "")
        )

        return (
            "[SESSION START]\n"
            f"{actions_block}"
            "<untrusted_external_context>\n"
            f"{tabs_block}"
            "[PC STATE]\n"
            f"{raw_ctx}\n"
            "</untrusted_external_context>\n\n"
        )

    def format_delta_context(self, delta: dict[str, Any], action_lines: list[str] | None = None) -> str:
        """Format minimal delta object for turns 2+."""
        actions_block = ""
        if action_lines:
            actions_block = "[RECENT ACTIONS THIS SESSION]\n" + "\n".join(action_lines) + "\n\n"

        delta_json = json.dumps(delta, ensure_ascii=False)
        return (
            f"{actions_block}"
            "<untrusted_external_context>\n"
            "[CONTEXT DELTA]\n"
            f"{delta_json}\n"
            "</untrusted_external_context>\n\n"
        )

    def get_context_for_turn(
        self,
        session_id: str,
        turn_index: int,
        get_pc_context_fn,
        get_all_tabs_fn,
        get_note_fn=None,
        action_lines: list[str] | None = None,
    ) -> str:
        """Build full context on turn 1 or minimal delta on turns 2+ with corruption safeguard.
        
        Updates the cached state upon successful computation.
        """
        # Detect new session
        if self._current_session_id != session_id:
            self.start_session(session_id)

        self._turn_index = turn_index
        current_state = self.capture_state(get_pc_context_fn, get_all_tabs_fn, get_note_fn)

        # Turn 1: Always emit full context and cache current state
        if turn_index <= 1 or self._cached_state is None:
            self._cached_state = current_state
            return self.format_full_context(current_state, action_lines)

        # Turns 2+: Attempt minimal delta computation
        try:
            delta = self.compute_delta(self._cached_state, current_state)
            self._cached_state = current_state
            return self.format_delta_context(delta, action_lines)
        except Exception as err:
            # Hard cap: if diff computation ever fails or state is corrupted,
            # fall back to sending full context for that turn only, log a warning,
            # and reset the cache — never send stale or null context silently.
            logger.warning("[SessionContextCache] Diff computation failed: %s — resetting cache and falling back to full context", err)
            print(f"[context_cache] WARNING: diff failed: {err!r} — resetting cache and falling back to full context")
            self._cached_state = current_state
            return self.format_full_context(current_state, action_lines)

    def update_after_turn(self, state: DesktopState | None = None) -> None:
        """Explicitly update or touch the cache after turn execution."""
        if state is not None:
            self._cached_state = state


# Global singleton cache instance for Akira
_session_context_cache = SessionContextCache()


def get_cache() -> SessionContextCache:
    """Return the global session context cache instance."""
    return _session_context_cache
