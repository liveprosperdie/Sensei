"""Source ingestion: user files (upload or voice-resolved path) and approved web pages.

Privacy/safety rules enforced here:
  * Only the EXTRACTED TEXT is stored. The original binary is discarded, never
    served back to the browser.
  * Every source carries `allow_cloud`. Text from a source without explicit
    consent is never included in a prompt that leaves the machine.
  * Secret-looking strings are scrubbed from any excerpt before it reaches a model.
  * Web fetches: https only, host on the vetted allowlist, DNS result must be a
    public address (blocks SSRF to localhost/LAN/cloud metadata), redirects are
    re-validated, response size and time are capped.
  * Everything extracted is treated as untrusted DATA, wrapped in tags the prompts
    tell the model never to obey.
"""

from __future__ import annotations

import io
import ipaddress
import re
import socket
from urllib.parse import urlparse, urljoin

from . import config, schema, workspace

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*\S{6,}"),
]


class SourceError(ValueError):
    pass


def scrub_secrets(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


# ── Extraction ──────────────────────────────────────────────────────────────

def _paginate(text: str) -> list[dict]:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    pages, buf = [], ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) > config.PAGE_CHARS:
            pages.append(buf.strip())
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        pages.append(buf.strip())
    return [{"page": i, "text": t} for i, t in enumerate(pages, start=1)]


def extract_pages(data: bytes, ext: str) -> list[dict]:
    ext = ext.lower()
    if ext in (".txt", ".md"):
        text = data.decode("utf-8", errors="replace")
        pages = _paginate(text)
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:  # pragma: no cover
            raise SourceError("PDF support needs the pypdf package") from e
        try:
            reader = PdfReader(io.BytesIO(data))
            if getattr(reader, "is_encrypted", False):
                raise SourceError("encrypted PDFs are not supported")
            pages = []
            for i, pg in enumerate(reader.pages[:800], start=1):
                t = (pg.extract_text() or "").strip()
                if t:
                    pages.append({"page": i, "text": t})
        except SourceError:
            raise
        except Exception as e:
            raise SourceError("could not read that PDF") from e
    elif ext == ".docx":
        try:
            import docx
        except ImportError as e:  # pragma: no cover
            raise SourceError("DOCX support needs the python-docx package") from e
        try:
            d = docx.Document(io.BytesIO(data))
            text = "\n\n".join(p.text for p in d.paragraphs if p.text.strip())
        except Exception as e:
            raise SourceError("could not read that DOCX") from e
        pages = _paginate(text)
    else:
        raise SourceError("unsupported file type")

    total = 0
    clipped = []
    for p in pages:
        t = p["text"].replace("\x00", "")
        if total + len(t) > config.MAX_SOURCE_CHARS:
            t = t[: max(0, config.MAX_SOURCE_CHARS - total)]
        if t.strip():
            clipped.append({"page": p["page"], "text": t})
        total += len(t)
        if total >= config.MAX_SOURCE_CHARS:
            break
    if not clipped:
        raise SourceError("no readable text found in that file")
    return clipped


# ── Registration ────────────────────────────────────────────────────────────

def _next_src_id(meta: dict) -> str:
    used = [int(s["id"].split("_")[1]) for grp in meta["sources"].values() for s in grp]
    return f"src_{(max(used) + 1) if used else 1}"


def safe_display_name(name: str) -> str:
    base = re.split(r"[\\/]", str(name or ""))[-1]
    return schema.clean_text(base, 80) or "document"


def add_local_file(slug: str, filename: str, data: bytes, allow_cloud: bool) -> dict:
    if not allow_cloud:
        # Allowed, but flagged: such a source is only ever read by a LOCAL model.
        pass
    name = safe_display_name(filename)
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in config.ALLOWED_UPLOAD_EXT:
        raise SourceError("only PDF, DOCX, TXT and MD files are supported")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise SourceError("file is larger than 15 MB")
    if not data:
        raise SourceError("file is empty")
    pages = extract_pages(data, ext)

    def mutate(meta: dict) -> None:
        count = len(meta["sources"]["local_files"]) + len(meta["sources"]["web_sources"])
        if count >= config.MAX_SOURCES_PER_TOPIC:
            raise SourceError("too many sources for one topic")
        sid = _next_src_id(meta)
        workspace.write_json(slug, f"sources/{sid}.json", {
            "id": sid, "name": name, "kind": "local", "type": ext.lstrip("."),
            "allow_cloud": bool(allow_cloud), "pages": pages,
        })
        meta["sources"]["local_files"].append({
            "id": sid, "name": name, "relative_path": f"sources/{sid}.json",
            "type": ext.lstrip("."), "allow_cloud": bool(allow_cloud), "pages": len(pages),
        })
        made.append(sid)

    made: list[str] = []
    meta = workspace.update_meta(slug, mutate)
    sid = made[0] if made else None
    return next(s for s in meta["sources"]["local_files"] if s["id"] == sid) if sid else {}


def remove_source(slug: str, src_id: str) -> None:
    if not schema.SRC_ID_RE.match(src_id or ""):
        raise SourceError("invalid source id")

    def mutate(meta: dict) -> None:
        for grp in ("local_files", "web_sources"):
            meta["sources"][grp] = [s for s in meta["sources"][grp] if s["id"] != src_id]
    workspace.update_meta(slug, mutate)
    p = workspace._safe_path(slug, f"sources/{src_id}.json")
    if p.exists():
        p.unlink()


def load_source(slug: str, src_id: str) -> dict | None:
    if not schema.SRC_ID_RE.match(src_id or ""):
        raise SourceError("invalid source id")
    return workspace.read_json(slug, f"sources/{src_id}.json")


# ── Web (approved + allowlisted only) ───────────────────────────────────────

def host_allowed(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in config.WEB_ALLOWLIST)


def url_status(url: str) -> str:
    """'ok' | 'bad_url' | 'not_allowlisted' — used by the roadmap review screen."""
    try:
        u = urlparse(url)
    except ValueError:
        return "bad_url"
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        return "bad_url"
    if u.port not in (None, 443):
        return "bad_url"
    return "ok" if host_allowed(u.hostname) else "not_allowlisted"


def _public_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|form)\b.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|br|section|article)>", "\n\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as _h
    text = _h.unescape(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def fetch_web_page(url: str) -> tuple[str, list[dict]]:
    import requests

    cur = url
    for _ in range(4):
        if url_status(cur) != "ok":
            raise SourceError("that address is not on the trusted-source list")
        host = urlparse(cur).hostname
        if not _public_ip(host):
            raise SourceError("address did not resolve to a public host")
        try:
            r = requests.get(
                cur, timeout=config.WEB_TIMEOUT_S, allow_redirects=False, stream=True,
                headers={"User-Agent": "AkiraTeaching/1.0 (+local study tool)",
                         "Accept": "text/html,text/plain;q=0.8"},
            )
        except requests.RequestException as e:
            raise SourceError("could not reach that page") from e
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location")
            r.close()
            if not loc:
                raise SourceError("bad redirect")
            cur = urljoin(cur, loc)
            continue
        if r.status_code != 200:
            r.close()
            raise SourceError(f"page returned status {r.status_code}")
        ctype = (r.headers.get("Content-Type") or "").lower()
        if not (ctype.startswith("text/html") or ctype.startswith("text/plain")):
            r.close()
            raise SourceError("page is not text")
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf.extend(chunk)
            if len(buf) > config.MAX_WEB_BYTES:
                break
        r.close()
        raw = bytes(buf).decode(r.encoding or "utf-8", errors="replace")
        text = _html_to_text(raw) if "html" in ctype else raw
        pages = _paginate(text[: config.MAX_SOURCE_CHARS])
        if not pages:
            raise SourceError("page had no readable text")
        return cur, pages
    raise SourceError("too many redirects")


def add_web_source(slug: str, name: str, url: str) -> dict | None:
    final_url, pages = fetch_web_page(url)

    def mutate(meta: dict) -> None:
        count = len(meta["sources"]["local_files"]) + len(meta["sources"]["web_sources"])
        if count >= config.MAX_SOURCES_PER_TOPIC:
            raise SourceError("too many sources for one topic")
        sid = _next_src_id(meta)
        workspace.write_json(slug, f"sources/{sid}.json", {
            "id": sid, "name": schema.clean_text(name, 80) or urlparse(final_url).hostname,
            "kind": "web", "type": "web", "origin": final_url,
            "allow_cloud": True, "pages": pages,   # public page: nothing private to protect
        })
        meta["sources"]["web_sources"].append({
            "id": sid, "name": schema.clean_text(name, 80), "url": final_url,
            "relative_path": f"sources/{sid}.json", "pages": len(pages),
        })
        made.append(sid)
    made: list[str] = []
    meta = workspace.update_meta(slug, mutate)
    sid = made[0] if made else None
    return next((s for s in meta["sources"]["web_sources"] if s["id"] == sid), None)


# ── Context assembly for prompts ────────────────────────────────────────────

_WORD = re.compile(r"[a-z0-9]{3,}")


def build_context(slug: str, meta: dict, query: str, budget_chars: int,
                  local_model: bool) -> tuple[str, list[str]]:
    """Pick the most relevant source pages for this lesson, within a budget.

    Returns (context_text, used_source_ids). Sources lacking cloud consent are
    included ONLY when the model that will read them runs locally.
    """
    words = set(_WORD.findall(query.lower()))
    scored = []
    for grp in ("local_files", "web_sources"):
        for entry in meta["sources"][grp]:
            if not entry.get("allow_cloud", True) and not local_model:
                continue
            src = load_source(slug, entry["id"])
            if not src:
                continue
            for p in src["pages"]:
                tokens = set(_WORD.findall(p["text"].lower()))
                score = len(words & tokens)
                scored.append((score, -p["page"], src["id"], src["name"], p["page"], p["text"]))
    if not scored:
        return "", []
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    chosen, used, size = [], [], 0
    for score, _neg, sid, name, page, text in scored:
        if chosen and score == 0 and size > budget_chars // 3:
            break
        excerpt = scrub_secrets(text)[:2400]
        block = f'<untrusted_source id="{sid}" name="{schema.clean_text(name, 60)}" page="{page}">\n{excerpt}\n</untrusted_source>'
        if size + len(block) > budget_chars:
            continue
        chosen.append(block)
        size += len(block)
        if sid not in used:
            used.append(sid)
    return "\n\n".join(chosen), used
