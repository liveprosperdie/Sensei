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


_KNOWN_APP_PROCESSES: dict[str, str] = {
    "chrome.exe": "Google Chrome",
    "brave.exe": "Brave Browser",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Mozilla Firefox",
    "code.exe": "Visual Studio Code",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "spotify.exe": "Spotify",
    "windowsterminal.exe": "Windows Terminal",
    "powershell.exe": "PowerShell",
    "cmd.exe": "Command Prompt",
    "notepad.exe": "Notepad",
    "slack.exe": "Slack",
    "discord.exe": "Discord",
    "zoom.exe": "Zoom",
    "obs64.exe": "OBS Studio",
    "vlc.exe": "VLC Media Player",
    "calc.exe": "Calculator",
    "calculatorapp.exe": "Calculator",
    "explorer.exe": "File Explorer",
}


def get_generalized_applications(open_windows: list[str] | None = None) -> list[str]:
    """Return a clean, generalized list of running desktop applications.
    Never reveals specific document names, confidential sheet titles, or private file paths.
    """
    apps = set()
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            try:
                pname = (p.info.get("name") or "").lower()
                if pname in _KNOWN_APP_PROCESSES:
                    apps.add(_KNOWN_APP_PROCESSES[pname])
            except Exception:
                pass
    except Exception:
        pass

    if open_windows:
        for w in open_windows:
            w_str = str(w).strip()
            for exe_name, app_name in _KNOWN_APP_PROCESSES.items():
                if app_name.lower() in w_str.lower():
                    apps.add(app_name)

    return sorted(list(apps))


def generalize_tab_title_and_url(title: str | None, url: str | None) -> str | None:
    """Generalize a browser tab to its clean service or domain name.
    Suppresses query parameters, tracking tokens, private doc titles, and video titles.
    """
    import urllib.parse
    url = url or ""
    title = title or ""

    if any(k in url.lower() for k in [
        "chrome-extension://", "blob:", "rotatecookiespage", "serviceworker",
        "stripe.com", "stripe.network", "about:blank", "chrome://"
    ]):
        return None

    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
    except Exception:
        host, path = "", ""

    if "docs.google.com" in host:
        return "Google Docs"
    if "drive.google.com" in host:
        return "Google Drive"
    if "calendar.google.com" in host:
        return "Google Calendar"
    if "mail.google.com" in host:
        return "Gmail"
    if "groq.com" in host:
        return "GroqCloud"
    if "claude.ai" in host:
        return "Claude"
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube"
    if "google.com" in host:
        if "search" in path or "q=" in parsed.query:
            return "Google Search"
        return "Google"
    if "github.com" in host:
        return "GitHub"
    if "reddit.com" in host:
        return "Reddit"
    if "spotify.com" in host:
        return "Spotify Web"
    if "linkedin.com" in host:
        return "LinkedIn"
    if "twitter.com" in host or "x.com" in host:
        return "X (Twitter)"
    if "netflix.com" in host:
        return "Netflix"
    if "amazon." in host:
        return "Amazon"

    if host:
        parts = host.split(".")
        if len(parts) >= 2:
            return parts[-2].capitalize()

    if title:
        if " - " in title:
            suffix = title.split(" - ")[-1].strip()
            if suffix.lower() not in ("google chrome", "brave", "edge", "firefox"):
                return suffix[:20]
        return title[:20].strip()

    return None


def get_generalized_tabs(tabs: list[dict[str, str]] | None = None) -> list[str]:
    """Return clean list of generalized active tabs (service names only)."""
    if not tabs:
        try:
            import requests
            for port in [9222, 9223, 9224]:
                try:
                    resp = requests.get(f"http://127.0.0.1:{port}/json", timeout=0.5)
                    if resp.status_code == 200:
                        tabs = [
                            {"title": t.get("title", ""), "url": t.get("url", "")}
                            for t in resp.json()
                            if t.get("type") == "page"
                        ]
                        break
                except Exception:
                    continue
        except Exception:
            tabs = []

    gen_tabs = []
    seen = set()
    for t in tabs or []:
        if isinstance(t, dict):
            g = generalize_tab_title_and_url(t.get("title"), t.get("url"))
            if g and g not in seen:
                seen.add(g)
                gen_tabs.append(g)

    return gen_tabs


@dataclass
class DesktopState:
    """Snapshot of visible desktop and browser context."""
    foreground_app: str = "unknown"
    open_windows: list[str] = field(default_factory=list)
    running_apps: list[str] = field(default_factory=list)
    running_tabs: list[str] = field(default_factory=list)
    tabs: list[dict[str, str]] = field(default_factory=list)
    current_url: str | None = None
    current_page_title: str | None = None
    note_context: str = ""
    previous_sessions_summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "foreground_app": self.foreground_app,
            "open_windows": list(self.open_windows),
            "running_apps": list(self.running_apps),
            "running_tabs": list(self.running_tabs),
            "tabs": [dict(t) for t in self.tabs],
            "current_url": self.current_url,
            "current_page_title": self.current_page_title,
            "note_context": self.note_context,
            "previous_sessions_summary": self.previous_sessions_summary,
            "timestamp": self.timestamp,
        }


class SessionContextCache:
    """In-memory cache tracking desktop state across turns of an active session."""

    def __init__(self) -> None:
        self._cached_state: DesktopState | None = None
        self._current_session_id: str | None = None
        self._turn_index: int = 0
        self._last_assistant_response: str = ""

    def set_last_assistant_response(self, text: str) -> None:
        """Store the most recent spoken or emitted assistant response."""
        self._last_assistant_response = (text or "").strip()

    def get_last_assistant_response(self) -> str:
        """Retrieve the most recent spoken or emitted assistant response."""
        return self._last_assistant_response

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

        running_apps = get_generalized_applications(cleaned_windows)
        running_tabs = get_generalized_tabs(cleaned_tabs)

        prev_summary = ""
        try:
            import session_crypto_logger
            prev_summary = session_crypto_logger.get_generalized_previous_sessions_summary(max_sessions=2)
        except Exception:
            prev_summary = ""

        return DesktopState(
            foreground_app=str(ctx.get("foreground_app") or "unknown"),
            open_windows=cleaned_windows,
            running_apps=running_apps,
            running_tabs=running_tabs,
            tabs=cleaned_tabs,
            current_url=ctx.get("current_url"),
            current_page_title=ctx.get("current_page_title"),
            note_context=note_ctx,
            previous_sessions_summary=prev_summary,
            timestamp=time.time(),
        )

    def compute_delta(self, prev: DesktopState, curr: DesktopState) -> dict[str, Any]:
        """Compute minimal delta dictionary containing only changed fields."""
        delta: dict[str, Any] = {}

        # 1. Running apps and tabs tracking
        prev_apps_set = set(prev.running_apps)
        curr_apps_set = set(curr.running_apps)
        opened_apps = [a for a in curr.running_apps if a not in prev_apps_set]
        closed_apps = [a for a in prev.running_apps if a not in curr_apps_set]
        if opened_apps:
            delta["opened_apps"] = opened_apps
        if closed_apps:
            delta["closed_apps"] = closed_apps

        prev_tabs_set = set(prev.running_tabs)
        curr_tabs_set = set(curr.running_tabs)
        opened_tabs = [t for t in curr.running_tabs if t not in prev_tabs_set]
        closed_tabs = [t for t in prev.running_tabs if t not in curr_tabs_set]
        if opened_tabs:
            delta["opened_tabs"] = opened_tabs
        if closed_tabs:
            delta["closed_tabs"] = closed_tabs

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
        """Format complete generalized desktop state for turn 1."""
        from datetime import datetime
        now_str = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
        time_block = f"[CURRENT SYSTEM TIME & DATE: {now_str}]\n\n"

        last_resp = self.get_last_assistant_response()
        last_resp_block = f"[LAST ASSISTANT RESPONSE]\n{last_resp}\n\n" if last_resp else ""

        actions_block = ""
        if action_lines:
            actions_block = "[RECENT ACTIONS THIS SESSION]\n" + "\n".join(action_lines) + "\n\n"

        apps_str = ", ".join(state.running_apps) or "None"
        tabs_str = ", ".join(state.running_tabs) or "None"
        env_block = (
            "[DESKTOP ENVIRONMENT]\n"
            f"Running Applications: {apps_str}\n"
            f"Active Browser Tabs: {tabs_str}\n\n"
        )

        prev_block = (
            f"[PREVIOUS SESSIONS MEMORY]\n{state.previous_sessions_summary}\n\n"
            if state.previous_sessions_summary else ""
        )

        note_block = f"[NOTE CONTEXT]\n{state.note_context}\n\n" if state.note_context else ""

        return (
            "[SESSION START]\n"
            f"{time_block}"
            f"{env_block}"
            f"{prev_block}"
            f"{last_resp_block}"
            f"{actions_block}"
            f"{note_block}"
        )

    def format_delta_context(self, delta: dict[str, Any], action_lines: list[str] | None = None) -> str:
        """Format minimal delta object with generalized environment awareness for turns 2+."""
        from datetime import datetime
        now_str = datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
        time_block = f"[CURRENT SYSTEM TIME & DATE: {now_str}]\n\n"

        last_resp = self.get_last_assistant_response()
        last_resp_block = f"[LAST ASSISTANT RESPONSE]\n{last_resp}\n\n" if last_resp else ""

        actions_block = ""
        if action_lines:
            actions_block = "[RECENT ACTIONS THIS SESSION]\n" + "\n".join(action_lines) + "\n\n"

        current_apps = delta.get("current_apps") or (self._cached_state.running_apps if self._cached_state else [])
        current_tabs = delta.get("current_tabs") or (self._cached_state.running_tabs if self._cached_state else [])
        apps_str = ", ".join(current_apps) or "None"
        tabs_str = ", ".join(current_tabs) or "None"
        env_block = (
            "[DESKTOP ENVIRONMENT]\n"
            f"Running Applications: {apps_str}\n"
            f"Active Browser Tabs: {tabs_str}\n\n"
        )

        delta_json = json.dumps(delta, ensure_ascii=False)
        return (
            f"{time_block}"
            f"{env_block}"
            f"{last_resp_block}"
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


def set_last_assistant_response(text: str) -> None:
    """Convenience accessor to set the last assistant response on the global cache."""
    _session_context_cache.set_last_assistant_response(text)


def get_last_assistant_response() -> str:
    """Convenience accessor to get the last assistant response from the global cache."""
    return _session_context_cache.get_last_assistant_response()
