"""Transport layer for the Obsidian "Local REST API with MCP" plugin.

    Plugin: https://github.com/coddingtonbear/obsidian-local-rest-api
    PIN VERSION 5.0.3 — NOT latest. See SETUP_OBSIDIAN_FOCUS_MODE.md.

WHY REST AND NOT THE PLUGIN'S BUILT-IN MCP SERVER
-------------------------------------------------
The plugin ships an MCP server and its README is right that this obsoletes
third-party Obsidian MCP servers. It still does not fit Sensei:

1. Transport mismatch. mcp_client.MCPServer speaks JSON-RPC over stdio to a
   CHILD PROCESS it spawns. The plugin's MCP server is Streamable HTTP inside
   an already-running Obsidian. Reaching it means writing a new transport, or
   shelling out to the `mcp-remote` Node bridge — a third moving part, plus
   npx, plus the same self-signed-cert problem, all to reach a server that
   also speaks plain REST.
2. Sensei is not a tool-loop agent. AKIRA_PROMPT mandates exactly ONE JSON
   object per reply and executor._ACTION_MAP dispatches action|parameter
   strings deterministically. MCP's value is a tool catalogue handed to a
   model that loops over tool calls; there is no such loop here.
3. Safety would regress. Every gate in this codebase is code-level at the
   dispatch layer (google_mcp.DENYLIST, sensei.DANGEROUS_ACTIONS,
   RISKY_*_PARAMS) because prompt-level-only gates are a documented failure
   mode here. The plugin's MCP surface includes command_execute (arbitrary
   command-palette execution), vault_delete, and whole-file vault_write.
   Handing that catalogue to the model puts destructive vault operations
   behind prompt text alone. REST lets us expose five verbs and never wire
   the dangerous ones — there is deliberately NO delete and NO command
   execution in this module.
4. Zero new dependencies: `requests` is already in requirements.txt.

What we DO take from the MCP-era plugin is its real REST surface — the
Markdown Patch 2.0 instruction engine, /search/simple/, and /active/ — rather
than the naive read-parse-rewrite the original plan assumed. Heading-targeted
appends happen SERVER-SIDE in one request, so Sensei never parses Markdown and
never races the user editing the same note in Obsidian.

CONNECTION MODEL
----------------
Default endpoint is HTTPS on 27124 with a SELF-SIGNED cert (not plain HTTP on
27123 — that one is opt-in via Settings -> Enable HTTP server). We resolve, in
order: OBSIDIAN_API_URL override -> https://127.0.0.1:27124 -> http://127.0.0.1:27123.
For TLS we pin the plugin's own cert as our CA when we can fetch it, and fall
back to unverified localhost TLS otherwise (see _session()).

Every public function returns {"success": bool, "message": str} — the same
shape the rest of the action pipeline expects, matching mcp_client.call_tool().
A transport error can never silently become success:True.
"""

import os
import ssl
import threading
import urllib.parse
import urllib.request

import requests
import urllib3

from dotenv import load_dotenv

load_dotenv()

# ── Endpoint resolution ──────────────────────────────────────────────────────

HTTPS_BASE = "https://127.0.0.1:27124"
HTTP_BASE = "http://127.0.0.1:27123"

# Version guard. 5.0.3 is the newest release installable on stable-channel
# Obsidian: 5.0.0/5.0.1 and 5.1.0 all set minAppVersion 1.13.1, a Catalyst-only
# early-access build. We warn rather than refuse — a user on Catalyst running
# 5.1.0 is fine, they just get no support promise from us.
PINNED_VERSION = "5.0.3"
KNOWN_GOOD_VERSIONS = ("5.0.2", "5.0.3")

_TIMEOUT = 10.0  # localhost; anything slower than this is a hung plugin

_session_lock = threading.Lock()
_session: requests.Session | None = None
_base_url: str | None = None
_version_warned = False

# Cached CA bundle path for the plugin's self-signed cert, or False once we
# have tried and failed (so we do not re-fetch on every call).
_ca_path: str | bytes | bool | None = None


def _api_key() -> str | None:
    return (os.environ.get("OBSIDIAN_API_KEY") or "").strip() or None


def _fetch_plugin_cert() -> str | bool:
    """Download the plugin's self-signed cert and cache it as a CA bundle.

    The plugin serves it unauthenticated at /obsidian-local-rest-api.crt. Once
    pinned as our CA, `verify=<path>` gives us REAL certificate validation
    against the plugin's own key instead of blanket verify=False. We must fetch
    it over an unverified context, which is safe here for one narrow reason:
    the connection is to 127.0.0.1, so there is no network path for a MITM to
    sit on, and a local attacker able to bind the port has already won.
    """
    import tempfile

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"{HTTPS_BASE}/obsidian-local-rest-api.crt"
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT, context=ctx) as r:
            pem = r.read()
    except Exception as e:
        print(f"[obsidian_api] could not fetch plugin cert ({e}) — "
              f"falling back to unverified localhost TLS")
        return False
    if b"BEGIN CERTIFICATE" not in pem:
        return False
    fd, path = tempfile.mkstemp(prefix="obsidian-local-rest-api-", suffix=".pem")
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    print(f"[obsidian_api] pinned plugin certificate as CA: {path}")
    return path


def _probe(session: requests.Session, base: str, verify) -> bool:
    """GET / — the plugin's unauthenticated status endpoint."""
    try:
        r = session.get(f"{base}/", timeout=_TIMEOUT, verify=verify)
        return r.status_code < 500
    except requests.RequestException:
        return False


def _connect() -> tuple[requests.Session, str] | tuple[None, None]:
    """Resolve a working base URL once per process and remember it."""
    global _session, _base_url, _ca_path

    if _session is not None and _base_url is not None:
        return _session, _base_url

    session = requests.Session()
    override = (os.environ.get("OBSIDIAN_API_URL") or "").strip().rstrip("/")
    candidates = [override] if override else [HTTPS_BASE, HTTP_BASE]

    for base in candidates:
        if base.startswith("https"):
            if _ca_path is None:
                _ca_path = _fetch_plugin_cert()
            verify = _ca_path if _ca_path else False
            if verify is False:
                # Only silence the warning we are knowingly accepting, and only
                # for this localhost session.
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        else:
            verify = True
        if _probe(session, base, verify):
            session.verify = verify
            _session, _base_url = session, base
            print(f"[obsidian_api] connected: {base}")
            _check_version(session, base)
            return session, base

    return None, None


def _check_version(session: requests.Session, base: str) -> None:
    """Warn once if the running plugin is outside the known-good range.

    Cheap insurance against the recurring minAppVersion regression: 5.0.0/5.0.1
    shipped broken for stable Obsidian, 5.0.2 fixed it, and 5.1.0 broke it
    again. A clear warning here beats an opaque failure three calls later.
    """
    global _version_warned
    if _version_warned:
        return
    _version_warned = True
    try:
        data = session.get(f"{base}/", timeout=_TIMEOUT).json()
    except Exception:
        return
    version = str(data.get("versions", {}).get("self")
                  or data.get("version") or "").strip()
    if not version:
        return
    if version not in KNOWN_GOOD_VERSIONS:
        print(f"[obsidian_api] WARNING: plugin version {version} is untested with "
              f"Sensei (pinned: {PINNED_VERSION}). If notes misbehave, see "
              f"SETUP_OBSIDIAN_FOCUS_MODE.md — do NOT just install latest.")
    else:
        print(f"[obsidian_api] plugin version {version} OK")


def reset() -> None:
    """Drop the cached connection (used by tests and after a config change)."""
    global _session, _base_url, _ca_path, _version_warned
    if _session is not None:
        _session.close()
    _session = _base_url = None
    _ca_path = None
    _version_warned = False


# ── Request funnel ───────────────────────────────────────────────────────────

_NOT_RUNNING = (
    "I can't reach Obsidian's REST API. Make sure Obsidian is open and the "
    "Local REST API plugin is enabled."
)
_NO_KEY = (
    "I don't have an Obsidian API key. Copy it from Obsidian's Local REST API "
    "settings into OBSIDIAN_API_KEY in your .env file."
)


def request(method: str, path: str, *, params: dict | None = None,
            json_body: dict | None = None, data: str | None = None,
            headers: dict | None = None) -> dict:
    """One request against the plugin. Returns {"success", "message", ...}.

    `path` is server-relative and must already be URL-encoded where needed —
    use vault_path() for note paths. Never raises for HTTP-level problems.
    """
    with _session_lock:
        session, base = _connect()
    if session is None:
        return {"success": False, "message": _NOT_RUNNING}

    key = _api_key()
    if not key:
        return {"success": False, "message": _NO_KEY}

    hdrs = {"Authorization": f"Bearer {key}"}
    if headers:
        hdrs.update(headers)
    if json_body is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/json"
    if data is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "text/markdown"

    url = f"{base}{path}"
    print(f"[obsidian_api] {method} {path}")
    try:
        resp = session.request(
            method, url, params=params, json=json_body,
            data=data.encode("utf-8") if isinstance(data, str) else data,
            headers=hdrs, timeout=_TIMEOUT)
    except requests.RequestException as e:
        reset()  # force re-probe next call; Obsidian may have been closed
        return {"success": False, "message": f"{_NOT_RUNNING} ({e.__class__.__name__})"}

    return _translate(resp)


def _translate(resp: requests.Response) -> dict:
    """Map every plugin response shape onto {"success","message"}.

    Mirrors mcp_client._translate's contract: a non-2xx or an error body can
    never come back as success:True.
    """
    if resp.status_code == 401:
        return {"success": False,
                "message": "Obsidian rejected the API key. Re-copy it from the "
                           "Local REST API settings pane into OBSIDIAN_API_KEY."}
    if resp.status_code == 404:
        return {"success": False, "message": "That note doesn't exist in the vault."}

    text = (resp.text or "").strip()
    if not resp.ok:
        detail = text
        try:
            body = resp.json()
            detail = body.get("message") or body.get("error") or text
        except ValueError:
            pass
        return {"success": False,
                "message": f"Obsidian returned {resp.status_code}: {detail[:300]}"}

    ctype = resp.headers.get("Content-Type", "")
    if "json" in ctype:
        try:
            return {"success": True, "message": text, "json": resp.json()}
        except ValueError:
            pass
    return {"success": True, "message": text}


# ── Path helpers ─────────────────────────────────────────────────────────────

def vault_path(note: str) -> str:
    """Turn a note name or vault-relative path into an encoded /vault/ path.

    Adds .md when the caller gave a bare name. Each path SEGMENT is encoded
    separately so directory separators survive but spaces and '#' do not break
    the URL.
    """
    note = (note or "").strip().lstrip("/")
    if not note.lower().endswith(".md"):
        note += ".md"
    segs = [urllib.parse.quote(s, safe="") for s in note.split("/") if s]
    return "/vault/" + "/".join(segs)


def heading_path(note: str, heading: str) -> str:
    """/vault/{path}/heading/{h} — for reading one section directly."""
    return f"{vault_path(note)}/heading/{urllib.parse.quote(heading, safe='')}"


def is_configured() -> bool:
    """True if an API key is present. Does NOT touch the network."""
    return _api_key() is not None


def status() -> dict:
    """Human-readable connectivity check, for the SETUP guide's troubleshooting."""
    with _session_lock:
        session, base = _connect()
    if session is None:
        return {"success": False, "message": _NOT_RUNNING}
    if not _api_key():
        return {"success": False, "message": _NO_KEY}
    res = request("GET", "/vault/")
    if res["success"]:
        return {"success": True, "message": f"Obsidian is connected at {base}."}
    return res
