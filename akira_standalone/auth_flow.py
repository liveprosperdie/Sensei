"""auth_flow.py — Browser-based Login Hand-off and Local Loopback Receiver."""

from __future__ import annotations

import http.server
import logging
import secrets
import socketserver
import threading
import urllib.parse
import webbrowser
import requests
from gateway_client import GATEWAY_URL, save_tokens, get_valid_jwt

logger = logging.getLogger("akira.auth_flow")


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            params = urllib.parse.parse_qs(parsed.query)
            _CallbackHandler.code = params.get("code", [None])[0]
            _CallbackHandler.state = params.get("state", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html>
            <head><title>Akira Auth</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
                <h2>✓ Successfully Connected to Akira</h2>
                <p>Authentication complete. You can close this tab and return to Akira.</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress standard HTTP server console spam


def start_browser_login(login_base_url: str = "https://app.akira.ai/app-login", timeout: float = 120.0) -> bool:
    """Launch user's default browser to website login and receive one-time code via loopback."""
    nonce = secrets.token_urlsafe(24)
    _CallbackHandler.code = None
    _CallbackHandler.state = None

    # Find a free local port
    with socketserver.TCPServer(("127.0.0.1", 0), _CallbackHandler) as httpd:
        port = httpd.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/callback"
        auth_url = f"{login_base_url}?state={nonce}&redirect={urllib.parse.quote(redirect_uri)}"

        print(f"[auth] Opening browser for Akira login: {auth_url}")
        webbrowser.open(auth_url)

        # Serve one request in background thread
        t = threading.Thread(target=httpd.handle_request)
        t.start()
        t.join(timeout=timeout)

    code = _CallbackHandler.code
    state = _CallbackHandler.state

    if not code or state != nonce:
        logger.error("[auth] Browser login timed out or state nonce mismatched.")
        return False

    # Exchange one-time code via Gateway
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/v1/auth/exchange",
            json={"code": code, "nonce": nonce},
            timeout=10.0
        )
        if resp.status_code == 200:
            data = resp.json()
            save_tokens(data)
            print(f"[auth] Successfully authenticated as tier: {data.get('tier')}")
            return True
        else:
            logger.error("[auth] Code exchange failed: HTTP %d %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("[auth] Failed to exchange code with gateway: %s", e)

    return False


def is_authenticated() -> bool:
    """Check if the user currently holds a valid or refreshable session token."""
    return get_valid_jwt() is not None
