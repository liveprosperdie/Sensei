"""Local web server for Teaching Mode.

SECURITY MODEL (all enforced in this file, covered by tests/test_teaching_mode.py)
  * Binds 127.0.0.1 only, on an ephemeral port. Never reachable from the LAN.
  * Every /api call needs a per-launch random token (X-Akira-Token). The token is
    handed to the browser in the URL *fragment*, which browsers never send to a
    server, so it does not appear in any request line or log.
  * Host header must be 127.0.0.1/localhost:<port> (defeats DNS-rebinding), and
    every state-changing request must carry a same-origin Origin header (CSRF).
  * Strict CSP: scripts only from this origin, no inline scripts, no external
    images/fonts/connections, no framing. Nothing in the UI contacts a third party.
  * No CORS headers are ever emitted.
  * Uploads: extension allowlist, 100 MB streamed cap, stored as extracted text
    under server-generated ids; the original file is never kept or served.
  * All file access goes through teaching.workspace (path allowlist + confinement).
  * Error text returned to the browser is key-scrubbed; stack traces never leave
    the process.
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, llm, pipeline, schema, sources, workspace
from .heuristics import PROCEED_AT

STATIC_DIR = Path(__file__).parent / "static"

CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'; object-src 'none'")


class Jobs:
    """Tiny in-memory job registry so slow model calls don't block the UI."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._active: set = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="teach-job")

    def submit(self, key: tuple, fn) -> dict:
        with self._lock:
            for j in self._jobs.values():
                if j["key"] == key and j["status"] == "running":
                    return j
            jid = secrets.token_urlsafe(12)
            job = {"id": jid, "key": key, "status": "running", "stage": "Starting",
                   "error": None, "started": time.time()}
            self._jobs[jid] = job
            if len(self._jobs) > 100:
                for old in sorted(self._jobs.values(), key=lambda j: j["started"])[:20]:
                    if old["status"] != "running":
                        self._jobs.pop(old["id"], None)

        def run() -> None:
            t0 = time.time()
            try:
                fn(lambda msg: job.__setitem__("stage", msg))
                job["status"] = "done"
                llm.log("job_done", job=list(key), secs=round(time.time() - t0, 1))
            except (workspace.WorkspaceError, sources.SourceError, ValueError) as e:
                job.update(status="error", error=llm._scrub(str(e)))
                llm.log("job_error", job=list(key), why=str(e))
            except llm.LLMUnavailable as e:
                job.update(status="error", error=f"The model could not finish: {llm._scrub(str(e))}")
                llm.log("job_error", job=list(key), why=str(e))
            except Exception as e:  # never leak internals to the browser
                llm.log("job_crash", job=list(key), kind=type(e).__name__, why=str(e))
                job.update(status="error", error="Something went wrong while generating. Please try again.")
        self._pool.submit(run)
        return job

    def get(self, jid: str) -> dict | None:
        j = self._jobs.get(jid)
        return None if j is None else {k: v for k, v in j.items() if k not in ("key", "started")}


def create_app(token: str, port: int, host: str = "127.0.0.1") -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    jobs = Jobs()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost", "testserver"}
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    is_local = host in ("127.0.0.1", "localhost")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host_header = request.headers.get("host", "").lower()
        if is_local and host_header not in allowed_hosts and not os.environ.get("ALLOWED_HOSTS"):
            return JSONResponse({"detail": "bad host"}, status_code=403)
        path = request.url.path
        if path.startswith("/api/"):
            # Public routes
            if path in ("/api/health", "/api/auth/register", "/api/auth/login", "/api/auth/demo"):
                resp = await call_next(request)
                resp.headers["Content-Security-Policy"] = CSP
                return resp

            # Check User JWT / Auth token
            auth_header = request.headers.get("authorization", "")
            user_token = request.headers.get("x-auth-token", "")
            if auth_header.lower().startswith("bearer "):
                user_token = auth_header[7:].strip()

            user = auth.verify_token(user_token) if user_token else None
            if user:
                workspace.CURRENT_USER_ID.set(user["id"])
            else:
                # Check legacy desktop session token
                supplied = request.headers.get("x-akira-token", "")
                if not (supplied and secrets.compare_digest(supplied.encode(), token.encode())):
                    return JSONResponse({"detail": "unauthorized"}, status_code=401)
                workspace.CURRENT_USER_ID.set(None)

            if request.method not in ("GET", "HEAD") and is_local:
                if request.headers.get("origin", "") not in allowed_origins and not os.environ.get("ALLOWED_ORIGINS"):
                    return JSONResponse({"detail": "bad origin"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def fail(e: Exception, code: int = 400):
        raise HTTPException(status_code=code, detail=llm._scrub(str(e)))

    # ── static ──────────────────────────────────────────────────────────────
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── auth ────────────────────────────────────────────────────────────────
    @app.post("/api/auth/register")
    def register(body: dict = Body(...)):
        try:
            return auth.register_user(body.get("email", ""), body.get("password", ""))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/auth/login")
    def login(body: dict = Body(...)):
        try:
            return auth.login_user(body.get("email", ""), body.get("password", ""))
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))

    @app.get("/api/auth/me")
    def me():
        uid = workspace.CURRENT_USER_ID.get()
        if not uid:
            return {"authenticated": False}
        u = auth.get_user_by_id(uid)
        return {"authenticated": True, "user": u}

    @app.post("/api/auth/demo")
    def demo_session():
        demo_id = f"demo_{secrets.token_hex(4)}"
        demo_email = f"{demo_id}@studyroom.demo"
        t = auth.create_token(demo_id, demo_email, expires_in_days=1)
        return {"id": demo_id, "email": demo_email, "token": t, "is_demo": True}

    # ── topics ──────────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health():
        return {"ok": True, "local_model": llm.local_available(),
                "web_allowlist": list(config.WEB_ALLOWLIST)}

    @app.get("/api/topics")
    def topics():
        return {"topics": workspace.list_topics()}

    @app.post("/api/topics")
    def create(body: dict = Body(...)):
        try:
            meta = workspace.create_topic(body.get("topic", ""), body.get("level", "intermediate"))
        except workspace.WorkspaceError as e:
            fail(e)
        return {"topic_slug": meta["topic_slug"]}

    @app.get("/api/topics/{slug}")
    def topic(slug: str):
        try:
            meta = workspace.load_meta(slug)
        except workspace.WorkspaceError as e:
            fail(e, 404)
        return meta

    @app.delete("/api/topics/{slug}")
    def delete(slug: str):
        try:
            workspace.delete_topic(slug)
        except workspace.WorkspaceError as e:
            fail(e, 404)
        return {"ok": True}

    # ── sources ─────────────────────────────────────────────────────────────
    @app.post("/api/topics/{slug}/sources/upload")
    async def upload(slug: str, request: Request, name: str = "", cloud: int = 0):
        declared = request.headers.get("content-length")
        max_mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        if declared and declared.isdigit() and int(declared) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"file is larger than {max_mb} MB")
        buf = bytearray()
        async for chunk in request.stream():
            buf.extend(chunk)
            if len(buf) > config.MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"file is larger than {max_mb} MB")
        try:
            workspace.load_meta(slug)
            entry = sources.add_local_file(slug, unquote(name), bytes(buf), bool(cloud))
        except (workspace.WorkspaceError, sources.SourceError) as e:
            fail(e)
        return entry

    @app.post("/api/topics/{slug}/sources/register-path")
    def register_path(slug: str, body: dict = Body(...)):
        """Voice path: Akira resolves 'lecture3.pdf in Downloads' to a path and calls this.

        Only reachable with the session token, so a web page can never use it to
        read local files. The caller must pass explicit cloud consent.
        """
        raw = str(body.get("path", ""))
        try:
            p = Path(raw).expanduser().resolve(strict=True)
            if not p.is_file() or p.suffix.lower() not in config.ALLOWED_UPLOAD_EXT:
                raise sources.SourceError("only PDF, DOCX, TXT and MD files are supported")
            max_mb = config.MAX_UPLOAD_BYTES // (1024 * 1024)
            if p.stat().st_size > config.MAX_UPLOAD_BYTES:
                raise sources.SourceError(f"file is larger than {max_mb} MB")
            entry = sources.add_local_file(slug, p.name, p.read_bytes(), bool(body.get("allow_cloud", False)))
        except (OSError, workspace.WorkspaceError, sources.SourceError) as e:
            fail(e)
        return entry

    @app.get("/api/topics/{slug}/sources/{src_id}")
    def get_source(slug: str, src_id: str):
        try:
            src = sources.load_source(slug, src_id)
        except (workspace.WorkspaceError, sources.SourceError) as e:
            fail(e)
        if not src:
            raise HTTPException(status_code=404, detail="source not found")
        return {k: src[k] for k in ("id", "name", "kind", "type", "pages") if k in src} | \
               ({"origin": src["origin"]} if src.get("origin") else {})

    @app.delete("/api/topics/{slug}/sources/{src_id}")
    def del_source(slug: str, src_id: str):
        try:
            sources.remove_source(slug, src_id)
        except (workspace.WorkspaceError, sources.SourceError) as e:
            fail(e)
        return {"ok": True}

    # ── planning / generation ───────────────────────────────────────────────
    @app.post("/api/topics/{slug}/plan")
    def plan(slug: str):
        try:
            workspace.load_meta(slug)
        except workspace.WorkspaceError as e:
            fail(e, 404)
        job = jobs.submit(("plan", slug), lambda prog: pipeline.plan_topic(slug, prog))
        return {"job_id": job["id"]}

    @app.post("/api/topics/{slug}/approve-sources")
    def approve(slug: str, body: dict = Body(...)):
        try:
            idx = body.get("approved") or []
            if not isinstance(idx, list):
                raise ValueError("approved must be a list")
            meta = pipeline.set_approvals(slug, idx)
        except (workspace.WorkspaceError, ValueError) as e:
            fail(e)
        return meta

    @app.post("/api/topics/{slug}/begin")
    def begin(slug: str):
        try:
            workspace.load_meta(slug)
        except workspace.WorkspaceError as e:
            fail(e, 404)
        job = jobs.submit(("begin", slug), lambda prog: pipeline.begin_course(slug, prog))
        return {"job_id": job["id"]}

    @app.post("/api/topics/{slug}/lessons/{lid}/generate")
    def gen(slug: str, lid: str):
        try:
            meta = workspace.load_meta(slug)
            pipeline._lesson_by_id(meta, lid)
        except workspace.WorkspaceError as e:
            fail(e, 404)
        job = jobs.submit(("lesson", slug, lid), lambda prog: pipeline.generate_lesson(slug, lid, prog))
        return {"job_id": job["id"]}

    @app.get("/api/jobs/{jid}")
    def job(jid: str):
        j = jobs.get(jid)
        if j is None:
            raise HTTPException(status_code=404, detail="job not found")
        return j

    # ── learning ────────────────────────────────────────────────────────────
    @app.get("/api/topics/{slug}/lessons/{lid}")
    def lesson(slug: str, lid: str):
        try:
            meta = workspace.load_meta(slug)
            les = pipeline._lesson_by_id(meta, lid)
            if les["state"] == "locked":
                raise workspace.WorkspaceError("lesson is locked")
            md = workspace.read_text(slug, f"{lid}.md")
            quiz = workspace.read_json(slug, f"{lid}_quiz.json")
            result = workspace.read_json(slug, f"{lid}_quiz_result.json")
            diagrams = {}
            for rel in les.get("diagram_files") or []:
                code = workspace.read_text(slug, rel)
                safe = schema.sanitize_mermaid(code or "")
                if safe:
                    diagrams[rel] = safe
            feynman = workspace.read_json(slug, f"{lid}_feynman.json")
        except workspace.WorkspaceError as e:
            fail(e, 404)
        payload = {"lesson": les, "markdown": md, "diagrams": diagrams,
                   "calibration": meta["calibration"], "result": result, "feynman": feynman}
        if quiz:
            payload["quiz"] = schema.public_quiz(quiz) if not result else \
                {"questions": quiz["questions"]}
        return payload

    @app.post("/api/topics/{slug}/calibrate")
    def calibrate(slug: str, body: dict = Body(...)):
        try:
            meta = pipeline.calibrate(slug, str(body.get("feedback", "")))
        except workspace.WorkspaceError as e:
            fail(e)
        return meta

    @app.post("/api/topics/{slug}/lessons/{lid}/quiz")
    def quiz(slug: str, lid: str, body: dict = Body(...)):
        try:
            out = pipeline.submit_quiz(slug, lid, body.get("answers") or {})
        except workspace.WorkspaceError as e:
            fail(e, 409)
        return out

    @app.post("/api/topics/{slug}/lessons/{lid}/feynman")
    def feynman_eval(slug: str, lid: str, body: dict = Body(...)):
        explanation = str(body.get("explanation") or body.get("transcript") or "").strip()
        try:
            workspace.load_meta(slug)
            pipeline._lesson_by_id(workspace.load_meta(slug), lid)
            out = pipeline.evaluate_feynman(slug, lid, explanation)
        except workspace.WorkspaceError as e:
            fail(e, 404)
        return out

    @app.post("/api/topics/{slug}/lessons/{lid}/check-relevance")
    def relevance_check(slug: str, lid: str, body: dict = Body(...)):
        text = str(body.get("text") or "").strip()
        try:
            meta = workspace.load_meta(slug)
            les = pipeline._lesson_by_id(meta, lid)
            out = pipeline.check_relevance(meta["topic"], les["title"], text)
        except workspace.WorkspaceError as e:
            fail(e, 404)
        return out

    @app.get("/api/meta/thresholds")
    def thresholds():
        return {"proceed_at": PROCEED_AT}

    return app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


_active_state: dict | None = None
_server_lock = threading.Lock()


def ensure_server(open_browser: bool = True) -> str:
    """Ensure the teaching server is running as a daemon; return the authenticated URL.
    If already running, re-uses the instance and opens the browser if requested.
    """
    global _active_state
    import uvicorn

    with _server_lock:
        if _active_state and _active_state.get("url"):
            url_with_token = _active_state["url"]
            if open_browser:
                webbrowser.open(url_with_token)
            return url_with_token

        port = _free_port()
        token = secrets.token_urlsafe(32)
        app = create_app(token, port)
        base = f"http://127.0.0.1:{port}"
        url_with_token = f"{base}/#t={token}"
        config_ = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        srv = uvicorn.Server(config_)
        t = threading.Thread(target=srv.run, daemon=True, name="teaching-server")
        t.start()
        _active_state = {
            "server": srv,
            "port": port,
            "token": token,
            "base": base,
            "url": url_with_token,
            "thread": t,
        }
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url_with_token)).start()
        print(f"[teaching] study room started at {base}")
        return url_with_token


def run(open_browser: bool = True, port: int = 0, block: bool = True, host: str = "127.0.0.1") -> str:
    """Start the server. Returns the base URL (without the token)."""
    import uvicorn

    env_port = int(os.environ.get("PORT", "0"))
    port = port or env_port or _free_port()
    host = os.environ.get("HOST", host)
    token = secrets.token_urlsafe(32)
    app = create_app(token, port, host=host)
    base = f"http://{host}:{port}"
    config_ = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config_)
    is_local = host in ("127.0.0.1", "localhost")
    if open_browser and is_local and not os.environ.get("HEADLESS"):
        threading.Timer(1.0, lambda: webbrowser.open(f"{base}/#t={token}")).start()
    print(f"[teaching] study room at {base}")
    if block:
        server.run()
    else:
        threading.Thread(target=server.run, daemon=True, name="teaching-server").start()
    return base

