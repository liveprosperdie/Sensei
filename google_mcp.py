"""Google Workspace MCP wiring — shared by all workspace *_control modules.

TWO server instances, because the server's OAuth scopes are all-or-nothing
per mode (verified in @dguido/google-workspace-mcp v3.4.4 source):
  - normal mode requests gmail.modify + FULL mail.google.com for Gmail
  - GOOGLE_WORKSPACE_READ_ONLY=true narrows EVERYTHING to *.readonly
Neither alone satisfies "Calendar/Docs write + Gmail strictly read-only", so:

  workspace : calendar,docs,sheets,slides,drive — write mode. Gmail is
              hard-stripped from this instance's service list, so NO gmail
              scope is ever requested on its token.
  gmail     : gmail only, READ_ONLY=true — requests exactly
              https://www.googleapis.com/auth/gmail.readonly and the server
              itself refuses to expose write tools in this mode.

Each instance keeps its own token file (named profiles), so the gmail token
physically cannot carry write scopes.
"""

import os
import shutil

from mcp_client import MCPServer

# Tools that must NEVER be reachable, regardless of which instance somehow
# exposes them. Outbound/sharing actions are locked out at this dispatch
# layer per project policy — a stray LLM tool-call or future refactor must
# hit this wall, not "just not be wired".
DENYLIST = frozenset({
    "send_email", "draft_email", "delete_email", "modify_email",
    "create_filter", "delete_filter", "update_label", "delete_label",
    "get_or_create_label",                      # creates labels = outbound-adjacent mutation
    "share_file", "batch_share", "remove_permission",  # sharing "fails outward"
    "batch_delete", "empty_trash",  # bulk/irreversible drive ops stay locked
    # delete_item is deliberately NOT denylisted (changed for the slides
    # delete fix): it moves ONE item to the Drive TRASH — recoverable, not
    # permanent (verified in v3.4.4: "Move items to trash"). Its only caller
    # is slides_control's delete action, which sensei.py confirmation-gates
    # in code via RISKY_WORKSPACE_PARAMS — the same code-level mechanism as
    # calendar delete, per the "never prompt-level-only gates" lesson.
})

_PACKAGE = "@dguido/google-workspace-mcp"
_instances: dict[str, MCPServer] = {}
_auth_ok: set[str] = set()


def _npx() -> list[str]:
    """Resolve npx cross-platform (npx.cmd on Windows). -y avoids an
    interactive install prompt breaking the stdio protocol."""
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if not exe:
        raise FileNotFoundError("npx not found — install Node.js from nodejs.org first.")
    return [exe, "-y", _PACKAGE]


def _get(instance: str) -> MCPServer:
    if instance in _instances:
        return _instances[instance]
    if instance == "workspace":
        services = os.environ.get("GOOGLE_WORKSPACE_SERVICES",
                                  "calendar,docs,sheets,slides,drive")
        # hard-strip gmail: it must never ride on the write-mode token
        services = ",".join(s for s in services.split(",")
                            if s.strip() and s.strip() != "gmail")
        env = {"GOOGLE_WORKSPACE_SERVICES": services,
               "GOOGLE_WORKSPACE_MCP_PROFILE": "sensei-workspace"}
    elif instance == "gmail":
        env = {"GOOGLE_WORKSPACE_SERVICES": "gmail",
               "GOOGLE_WORKSPACE_READ_ONLY": "true",
               "GOOGLE_WORKSPACE_MCP_PROFILE": "sensei-gmail-ro"}
    else:
        raise ValueError(f"unknown instance: {instance}")
    for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        if os.environ.get(var):
            env[var] = os.environ[var]
    _instances[instance] = MCPServer(f"google-{instance}", _npx(), env=env)
    return _instances[instance]


def _check_auth(server: MCPServer, instance: str) -> dict | None:
    """One-time-per-session token check via the server's get_status tool.
    Returns an error dict if not connected, else None."""
    if instance in _auth_ok:
        return None
    status = server.call_tool("get_status", {})
    text = status["message"].lower()
    # Live-observed shape (v3.4.4): "[ERROR] ... Issues: credentials,
    # config_validation, token_file, api_validation. Set up OAuth..." —
    # an issues list naming credentials/token problems, not structured JSON.
    if not status["success"] or (
            "issues:" in text and ("credentials" in text or "token" in text)):
        return {"success": False,
                "message": "Google account not connected, please re-authenticate."}
    _auth_ok.add(instance)
    return None


def call(instance: str, tool: str, arguments: dict, *,
         speak_summary: bool = False) -> dict:
    """The single funnel every workspace dispatcher routes through.
    Enforces the denylist, checks auth, returns {"success","message"}.
    speak_summary=True marks a successful READ result (raw API dump) for
    same-turn LLM synthesis into a spoken reply — see sensei.handle_response.
    Set it only on read actions whose message is not directly speakable."""
    if tool in DENYLIST:
        print(f"[google_mcp] BLOCKED denylisted tool: {tool}")
        return {"success": False,
                "message": f"The action '{tool}' is disabled by policy in Sensei."}
    try:
        server = _get(instance)
    except (FileNotFoundError, ValueError) as e:
        return {"success": False, "message": str(e)}
    auth_err = _check_auth(server, instance)
    if auth_err:
        return auth_err
    result = server.call_tool(tool, arguments)
    if speak_summary and result.get("success"):
        result["speak_summary"] = True
    return result
