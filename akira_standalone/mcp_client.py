"""Generic MCP (Model Context Protocol) client over stdio.

Reusable for any stdio MCP server (Google Workspace today; filesystem etc.
later). Not coupled to Google in any way. One MCPServer = one child process,
lazily spawned on first call, restarted once if it dies mid-session.

Every public method returns/raises predictably:
- call_tool() ALWAYS returns {"success": bool, "message": str} — the same
  shape the rest of the action pipeline expects. MCP-level errors
  (JSON-RPC error, result.isError, empty content) are ALL mapped to
  success:False. An MCP error can never silently become success:True.
"""

import json
import os
import shutil
import subprocess
import threading

_PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    def __init__(self, name: str, command: list[str], env: dict | None = None,
                 call_timeout: float = 90.0):
        """name: label for debug prints. command: full argv (e.g. resolved
        npx + package). env: EXTRA environment merged over os.environ.
        call_timeout: 90s default — first-ever Google call opens a browser
        OAuth consent flow, which is slow; plain API calls finish in <5s,
        but a timeout shorter than the consent flow would break first-run."""
        self.name = name
        self.command = command
        self.extra_env = env or {}
        self.call_timeout = call_timeout
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self._restarted = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        print(f"[mcp:{self.name}] starting: {' '.join(self.command)}")
        env = dict(os.environ)
        env.update(self.extra_env)
        self._proc = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, text=True, encoding="utf-8",
            # Windows: suppress the flash of a console window
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._rpc("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "akira", "version": "1.0"},
        }, timeout=30)
        self._notify("notifications/initialized")
        print(f"[mcp:{self.name}] initialized")

    def _ensure_started(self) -> None:
        if not self._alive():
            self._start()

    def stop(self) -> None:
        """Terminate the child process (idempotent)."""
        if self._alive():
            self._proc.terminate()
        self._proc = None

    # ── JSON-RPC plumbing ────────────────────────────────────────────────

    def _notify(self, method: str) -> None:
        self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self._proc.stdin.flush()

    def _rpc(self, method: str, params: dict, timeout: float | None = None) -> dict:
        """Send one request, block for its response. Raises on transport
        failure or timeout (callers translate to success:False)."""
        self._id += 1
        req_id = self._id
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id,
                              "method": method, "params": params})
        self._proc.stdin.write(payload + "\n")
        self._proc.stdin.flush()

        result: dict = {}
        error: list = []

        def _reader():
            try:
                while True:
                    line = self._proc.stdout.readline()
                    if not line:
                        error.append("server process closed its output")
                        return
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # non-protocol noise on stdout
                    if msg.get("id") == req_id:
                        result.update(msg)
                        return
            except Exception as e:
                error.append(str(e))

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout or self.call_timeout)
        if t.is_alive():
            raise TimeoutError(f"{method} timed out after {timeout or self.call_timeout}s")
        if error:
            raise ConnectionError(error[0])
        return result

    # ── public API ───────────────────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        """Return the server's tool definitions (name/description/inputSchema)."""
        with self._lock:
            self._ensure_started()
            resp = self._rpc("tools/list", {}, timeout=30)
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, tool: str, arguments: dict) -> dict:
        """Call one MCP tool. Returns {"success": bool, "message": str}.
        message is the concatenated text content on success, or the error
        text on failure. Never raises for MCP-level problems; only prints."""
        with self._lock:
            try:
                self._ensure_started()
                resp = self._rpc("tools/call", {"name": tool, "arguments": arguments})
            except (TimeoutError, ConnectionError, BrokenPipeError, OSError) as e:
                # one restart attempt if the child died (npx hiccup etc.)
                if not self._restarted and not self._alive():
                    print(f"[mcp:{self.name}] process died ({e}) — restarting once")
                    self._restarted = True
                    self.stop()
                    try:
                        self._ensure_started()
                        resp = self._rpc("tools/call", {"name": tool, "arguments": arguments})
                    except Exception as e2:
                        return {"success": False, "message": f"MCP server '{self.name}' failed: {e2}"}
                else:
                    return {"success": False, "message": f"MCP server '{self.name}' failed: {e}"}

        return self._translate(tool, resp)

    def _translate(self, tool: str, resp: dict) -> dict:
        """Map every MCP response shape onto {"success","message"}.
        Failure paths: JSON-RPC error object, result.isError=True, or a
        result with no text content (observed live from this server when
        unauthenticated — silence is NOT success)."""
        if "error" in resp:
            err = resp["error"]
            return {"success": False,
                    "message": f"{tool} failed: {err.get('message', err)}"}
        result = resp.get("result", {})
        texts = [c.get("text", "") for c in result.get("content", [])
                 if c.get("type") == "text" and c.get("text")]
        text = "\n".join(texts).strip()
        if result.get("isError"):
            return {"success": False, "message": f"{tool} failed: {text or 'unknown MCP error'}"}
        if not text:
            return {"success": False,
                    "message": f"{tool} returned no data — likely not authenticated or an empty result."}
        return {"success": True, "message": text}
