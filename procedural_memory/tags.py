"""procedural_memory/tags.py — Default-deny action and plan tagging registry.

Derives always-fresh from existing guard sources at runtime to guarantee recall can
never be looser than the security guard chain.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("akira.procedural_memory.tags")

# Tag constants
TAG_RECALL_ELIGIBLE = "recall-eligible"
TAG_ALWAYS_FRESH = "always-fresh"
TAG_CONTENT_GENERATED = "content-generated"

# Allowlist for open_system_tool targets (safe, non-destructive system diagnostics/tools)
VALID_SYSTEM_TOOLS = frozenset({
    "taskmgr", "calc", "notepad", "cmd", "powershell",
    "control", "explorer", "settings", "dxdiag", "snippingtool",
    "msinfo32", "cleanmgr", "resmon",
})

# Actions that are explicitly stateful, network-mutating, privacy-sensitive,
# dictated, or carry overwrite risks (per user corrections Section 3).
_EXPLICIT_ALWAYS_FRESH_ACTIONS = frozenset({
    # Dictated payloads
    "write_clipboard", "write_text", "type_text", "insert_text",
    # Overwrite / extraction risk
    "copy_files", "compress_files", "extract_files", "create_file",
    # Self-gating destructive file actions
    "delete_files", "move_files", "organize_files", "organize_folder", "bulk_rename_files",
    # Network / Cloud side effects
    "download_image", "file_to_doc",
    # Privacy-sensitive config
    "manage_index_scope", "index_stats",
    # State-dependent toggles and media/playback
    "toggle_wifi", "toggle_bluetooth", "meet_control", "spotify_control", "youtube_control",
    # Window / Tab state (depends on active desktop state)
    "close_tab", "switch_tab", "switch_window", "maximize_window", "minimize_window",
    "close_application", "new_tab", "open_site_tab", "list_tabs", "click", "click_element",
    "fill", "fill_input", "scroll", "browser_control", "bookmark_page",
    # Reading pagination / flow control
    "read_more", "stop_reading",
    # Screen / audio capture
    "screenshot", "background_status",
    # Procedural memory controls & system wiping
    "wipe_all_memory",
    # Google Workspace mutators (except pure list/search)
    "gmail_control", "gmail_compose", "docs_control", "sheets_control", "slides_control",
    # Obsidian note mutations
    "obsidian_control",
})

# Explicitly verified recall-eligible action names (when parameters pass sub-action checks)
_EXPLICIT_RECALL_ELIGIBLE_ACTIONS = frozenset({
    "open_settings",
    "open_folder",
    "open_system_tool",
    "lock_pc",
    "lock_screen",
    "performance_stats",
    "battery_status",
    "list_processes",
    "open_file",
    "read_file",
    "open_url",
    "web_search",
    "site_search",
    "file_search",
    "folder_search",
    "search_file",
    "search_image",
    "set_wallpaper",
    "calendar_control",  # list only
    "open_application",   # when not handled by Tier 1
    "netflix_control",   # open/search only
})


def _is_runtime_dangerous(action: str, parameter: Optional[str]) -> bool:
    """Check against live runtime guards from akira and system_control.
    Checks sys.modules first to avoid re-executing akira audio/VAD pipeline headlessly.
    """
    import sys
    akira_mod = sys.modules.get("akira") or sys.modules.get("__main__")
    if akira_mod:
        if hasattr(akira_mod, "DANGEROUS_ACTIONS") and action in akira_mod.DANGEROUS_ACTIONS:
            return True
        if hasattr(akira_mod, "_is_dangerous_step"):
            step = {"action": action, "parameter": parameter or ""}
            try:
                if akira_mod._is_dangerous_step(step):
                    return True
            except Exception:
                pass
    else:
        # Fallback if akira is not loaded: check system_control.TIER2_ACTIONS directly
        core_dangerous = frozenset({
            "close_application", "shutdown", "restart", "hibernate",
            "edit_file", "uninstall_application", "write_file", "wipe_all_memory",
        })
        if action in core_dangerous:
            return True

    try:
        import system_control
        if action in getattr(system_control, "TIER2_ACTIONS", {}):
            return True
    except Exception as e:
        logger.debug("[tags] Could not check system_control.TIER2_ACTIONS: %s", e)

    try:
        import office_control
        if action == "office_control" and hasattr(office_control, "is_risky_parameter"):
            if office_control.is_risky_parameter(parameter):
                return True
    except Exception as e:
        logger.debug("[tags] Could not check office_control: %s", e)

    return False


def get_step_tag(action: str, parameter: Optional[str] = None) -> str:
    """Return the tag for a single action step under default-deny.
    
    Returns one of:
    - TAG_RECALL_ELIGIBLE ("recall-eligible")
    - TAG_ALWAYS_FRESH ("always-fresh")
    - TAG_CONTENT_GENERATED ("content-generated")
    """
    act = (action or "").strip().lower()
    param = (parameter or "").strip()
    param_lower = param.lower()

    # Rule 1: Content-generated
    if act == "summarize_file":
        return TAG_CONTENT_GENERATED

    # Rule 2: Derive from existing runtime guards (DANGEROUS_ACTIONS, TIER2_ACTIONS, risky params)
    if _is_runtime_dangerous(act, param):
        return TAG_ALWAYS_FRESH

    # Rule 3: Explicit always-fresh set
    if act in _EXPLICIT_ALWAYS_FRESH_ACTIONS:
        return TAG_ALWAYS_FRESH

    # Rule 4: Sub-action parameter checks on potentially eligible actions
    if act == "calendar_control":
        # Only "list" is recall-eligible. Create/update/delete are always-fresh.
        if not param_lower.startswith("list"):
            return TAG_ALWAYS_FRESH
        return TAG_RECALL_ELIGIBLE

    if act in ("amazon_control", "flipkart_control"):
        # Any cart, buy, or checkout is always-fresh.
        if any(k in param_lower for k in ("cart", "buy", "order", "checkout", "address")):
            return TAG_ALWAYS_FRESH
        # Even search on shopping sites depends on live product availability, keep fresh
        return TAG_ALWAYS_FRESH

    if act == "github_control":
        # Cloning writes to disk and may embed credentials. All GitHub mutations are always-fresh.
        if "clone" in param_lower or any(k in param_lower for k in ("pull", "push", "repo", "branch", "commit", "issue")):
            return TAG_ALWAYS_FRESH
        return TAG_ALWAYS_FRESH

    if act == "vscode_control":
        # Any file creation or modification is always-fresh.
        if any(k in param_lower for k in ("create", "write", "edit", "new")):
            return TAG_ALWAYS_FRESH
        # Only opening or reading workspaces/files is eligible
        if param_lower.startswith("open") or param_lower.startswith("read"):
            return TAG_RECALL_ELIGIBLE
        return TAG_ALWAYS_FRESH

    if act == "open_system_tool":
        # Allowlist of safe system tools only
        tool = param_lower.split("|")[0].strip()
        if tool not in VALID_SYSTEM_TOOLS:
            return TAG_ALWAYS_FRESH
        return TAG_RECALL_ELIGIBLE

    if act == "office_control":
        # office_control formatting or typing is stateful/selection-based -> always fresh
        return TAG_ALWAYS_FRESH

    # Rule 5: Default-deny: only explicitly verified actions are recall-eligible
    if act in _EXPLICIT_RECALL_ELIGIBLE_ACTIONS:
        return TAG_RECALL_ELIGIBLE

    # Any unknown or unclassified action defaults to always-fresh
    return TAG_ALWAYS_FRESH


def get_plan_tag(actions: list[dict[str, Any]]) -> str:
    """Return the overall tag for a compound plan (most restrictive wins).
    
    If any step is always-fresh, the plan is TAG_ALWAYS_FRESH (and must not be stored).
    If any step is content-generated (and none always-fresh), the plan is TAG_CONTENT_GENERATED.
    Only if EVERY step is recall-eligible is the plan TAG_RECALL_ELIGIBLE.
    """
    if not actions:
        return TAG_ALWAYS_FRESH

    has_content_gen = False
    for step in actions:
        tag = get_step_tag(step.get("action", ""), step.get("parameter"))
        if tag == TAG_ALWAYS_FRESH:
            return TAG_ALWAYS_FRESH
        if tag == TAG_CONTENT_GENERATED:
            has_content_gen = True

    if has_content_gen:
        return TAG_CONTENT_GENERATED

    return TAG_RECALL_ELIGIBLE
