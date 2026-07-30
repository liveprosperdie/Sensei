"""
image_flow.py — the complete image search/pick/download pipeline.

Extracted from executor.py so the flow is OS-independent and testable
headlessly (executor.py imports winreg/win32 and cannot load off Windows).

Flow contract (enforced here AND by action_guard.py at the chain level):
  1. search_image  — queries every available safe image API (Wikimedia
     Commons and Openverse keyless; Unsplash and Pinterest only when their
     token is configured) and INTERLEAVES the results, stores the candidates,
     renders a LOCAL numbered picker page
     with real thumbnails, and navigates the browser to it. Downloads NOTHING.
  2. The user picks one candidate by position or name (a real user turn).
  3. download_image — resolves the pick against the STORED candidate list
     (never by scraping any page DOM), downloads that single image to a
     UNIQUE filename, and returns the saved path.

Safety properties:
  - _is_safe_image_result() drops unsafe results before they reach the
    store, the picker page, or any spoken text (defense-in-depth on top of
    the providers' own filters).
  - resolve_pick() never defaults to a candidate on garbage input — an
    unresolvable pick is an error, not a silent first-result download.
  - _unique_path() guarantees downloads never overwrite an existing file.

executor.py wires platform hooks via configure(); everything else is pure.
"""

from __future__ import annotations

import os
import re
import html
import urllib.parse
import tempfile

import requests

# ── Platform hooks (wired by executor.py; no-op defaults keep this module
#    importable and testable anywhere) ─────────────────────────────────────────

_hooks = {
    "navigate": None,        # navigate(url) — drive the user's browser
    "remember": None,        # remember(path) — session file memory
    "normalize_path": None,  # normalize_path(spoken) -> absolute path
}


def configure(navigate=None, remember=None, normalize_path=None) -> None:
    """Install platform-specific callbacks. Call once from executor.py."""
    if navigate:
        _hooks["navigate"] = navigate
    if remember:
        _hooks["remember"] = remember
    if normalize_path:
        _hooks["normalize_path"] = normalize_path


# ── Constants & state ─────────────────────────────────────────────────────────

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}

_EXT_BY_CTYPE = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "image/webp": ".webp", "image/bmp": ".bmp",
}

_ORDINALS = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "sixth": 5, "6th": 5,
    "last": -1,
}

# Candidates from the LAST search_image call. Each:
# {"url", "title", "source_domain"}. download_image resolves picks against
# THIS list only — never against any page DOM.
_candidates: list[dict] = []
_query: str = ""

# Defense-in-depth: never surface a result whose URL, domain, or title trips
# this — even if the API's own filter misses it.
_UNSAFE_IMG_RE = re.compile(
    r"porn|xxx|sex|nude|naked|nsfw|adult|hentai|erotic|escort|fetish|xvideo|"
    r"xhamster|redtube|onlyfans|playboy|hustler|penthouse", re.IGNORECASE)


def _is_safe_image_result(url: str, title: str = "") -> bool:
    domain = urllib.parse.urlparse(url).netloc
    if _UNSAFE_IMG_RE.search(domain) or _UNSAFE_IMG_RE.search(url) or \
       (title and _UNSAFE_IMG_RE.search(title)):
        print(f"[search_image] SAFETY-FILTERED: {domain}")
        return False
    return True


# ── Provider search (Unsplash keyed -> Openverse keyless) ─────────────────────

def _commons(query: str, limit: int) -> list[dict]:
    """Wikimedia Commons — keyless, and the only source in the pool that
    reliably returns LABELLED reference material (anatomy plates, diagrams,
    maps) rather than stock photography. Ranked first for that reason.

    SVG results are dropped: Word's AddPicture and the Content-Type→extension
    mapping in download_image both expect a raster file.
    """
    resp = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params={"action": "query", "generator": "search", "gsrsearch": query,
                "gsrnamespace": "6", "gsrlimit": str(limit * 3),
                "prop": "imageinfo", "iiprop": "url|mime",
                "iiurlwidth": "1600", "format": "json"},
        headers={"User-Agent": "AkiraAssistant/1.0"}, timeout=15)
    resp.raise_for_status()
    out = []
    for page in (resp.json().get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime") or ""
        if not mime.startswith("image/") or "svg" in mime:
            continue
        # thumburl is a scaled JPEG/PNG; full-size originals can be 50 MB+.
        url = info.get("thumburl") or info.get("url")
        title = _re_sub_file_prefix(page.get("title") or "")
        if url and _is_safe_image_result(url, title):
            out.append({"url": url, "title": title,
                        "source_domain": "commons.wikimedia.org"})
        if len(out) >= limit:
            break
    return out


def _re_sub_file_prefix(title: str) -> str:
    """'File:Human skeleton front.png' -> 'Human skeleton front'."""
    return os.path.splitext(re.sub(r"^File:", "", title.strip()))[0]


def _pinterest(query: str, limit: int) -> list[dict]:
    """Pinterest, via the OFFICIAL v5 /search/partner/pins endpoint.

    Only runs when PINTEREST_ACCESS_TOKEN is set: that endpoint is a gated
    beta needing OAuth plus partner approval, and the unofficial scrapers are
    fragile and against Pinterest's terms, so there is deliberately no
    keyless path here. With no token this is a silent no-op and the rest of
    the pool answers.
    """
    token = os.environ.get("PINTEREST_ACCESS_TOKEN")
    if not token:
        return []
    resp = requests.get(
        "https://api.pinterest.com/v5/search/partner/pins",
        params={"term": query, "country_code": os.environ.get("PINTEREST_COUNTRY", "US"),
                "limit": str(limit * 2)},
        headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()
    out = []
    for pin in resp.json().get("items", []):
        images = (pin.get("media") or {}).get("images") or {}
        best = images.get("1200x") or images.get("600x") or images.get("originals")
        url = (best or {}).get("url")
        title = (pin.get("title") or pin.get("alt_text") or "").strip()
        if url and _is_safe_image_result(url, title):
            out.append({"url": url, "title": title,
                        "source_domain": "pinterest.com"})
        if len(out) >= limit:
            break
    return out


def _unsplash(query: str, limit: int) -> list[dict]:
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        return []
    resp = requests.get(
        "https://api.unsplash.com/search/photos",
        params={"query": query, "per_page": limit * 2, "content_filter": "high"},
        headers={"Authorization": f"Client-ID {key}"}, timeout=10)
    resp.raise_for_status()
    out = []
    for r in resp.json().get("results", []):
        url = r.get("urls", {}).get("full") or r.get("urls", {}).get("regular")
        title = (r.get("description") or r.get("alt_description") or "").strip()
        if url and _is_safe_image_result(url, title):
            out.append({"url": url, "title": title,
                        "source_domain": "unsplash.com"})
        if len(out) >= limit:
            break
    return out


def _openverse(query: str, limit: int) -> list[dict]:
    resp = requests.get(
        "https://api.openverse.org/v1/images/",
        params={"q": query, "page_size": limit * 3, "mature": "false"},
        headers={"User-Agent": "AkiraAssistant/1.0"}, timeout=15)
    resp.raise_for_status()
    out = []
    for r in resp.json().get("results", []):
        url, title = r.get("url"), (r.get("title") or "").strip()
        if url and _is_safe_image_result(url, title):
            out.append({"url": url, "title": title,
                        "source_domain": urllib.parse.urlparse(url).netloc})
        if len(out) >= limit:
            break
    return out


# Order = ranking. Commons leads because document illustrations want labelled
# reference images; the stock sources fill in when a topic has no reference art.
_PROVIDERS = (("Pinterest", _pinterest), ("Commons", _commons),
              ("Unsplash", _unsplash), ("Openverse", _openverse))


def _search_image_urls(query: str, limit: int = 6) -> tuple[list, str | None]:
    """Up to `limit` safe image results. Each: {url, title, source_domain}.

    EVERY available provider is queried and the results are INTERLEAVED rather
    than stopping at the first that answers, so one source having a bad day
    can't wreck a picker — and the user always sees a mix to choose from.
    Returns (results, error).
    """
    pools: list[list[dict]] = []
    for name, fn in _PROVIDERS:
        try:
            got = fn(query, limit)
        except requests.RequestException as e:
            print(f"[search_image] {name} failed ({e}) — skipping")
            continue
        except Exception as e:                                # malformed payload
            print(f"[search_image] {name} returned something unusable ({e})")
            continue
        if got:
            print(f"[search_image] {name}: {len(got)} results")
            pools.append(got)

    out, seen = [], set()
    for row in range(limit):
        for pool in pools:
            if row < len(pool) and pool[row]["url"] not in seen:
                seen.add(pool[row]["url"])
                out.append(pool[row])
                if len(out) >= limit:
                    return out, None
    if not out:
        return [], f"No image results for '{query}'."
    return out, None


# ── Picker page — a LOCAL page Sensei generates and shows in the browser so
#    the user SEES the numbered candidates they hear ──────────────────────────

def picker_page_path() -> str:
    return os.path.join(tempfile.gettempdir(), "akira_image_picker.html")


def render_picker_page(query: str, candidates: list[dict]) -> str:
    """Write the numbered-grid picker HTML and return its file:// URL.
    Thumbnails come from the SAME candidate URLs the voice list reads out,
    so screen and speech always match exactly."""
    cards = "\n".join(
        '<figure class="card">'
        f'<span class="num" aria-hidden="true">{i + 1}</span>'
        f'<img src="{html.escape(c["url"], quote=True)}" '
        f'alt="{html.escape(c["title"] or "untitled")}" loading="lazy">'
        '<figcaption>'
        f'<strong>{i + 1}. {html.escape((c["title"] or "untitled")[:80])}</strong>'
        f'<small>{html.escape(c["source_domain"])}</small>'
        '</figcaption></figure>'
        for i, c in enumerate(candidates))
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pick an image — {html.escape(query)}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; padding: 24px; background: #111; color: #eee;
         font: 15px/1.5 system-ui, sans-serif; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  p  {{ margin: 0 0 20px; color: #9a9a9a; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 16px; }}
  .card {{ position: relative; margin: 0; width: 300px; background: #1c1c1c;
          border: 1px solid #2c2c2c; border-radius: 10px; overflow: hidden; }}
  .card img {{ display: block; width: 100%; height: 200px; object-fit: cover;
              background: #000; }}
  .num {{ position: absolute; top: 8px; left: 8px; min-width: 28px; height: 28px;
         display: flex; align-items: center; justify-content: center;
         background: #e8b339; color: #111; font-weight: 700; font-size: 15px;
         border-radius: 6px; }}
  figcaption {{ padding: 10px 12px; }}
  figcaption strong {{ display: block; font-size: 14px; font-weight: 600; }}
  figcaption small {{ color: #9a9a9a; }}
</style></head><body>
<h1>Images for &ldquo;{html.escape(query)}&rdquo;</h1>
<p>Say a number or a name to download one &mdash; e.g. &ldquo;the third one&rdquo;.</p>
<div class="grid">
{cards}
</div></body></html>"""
    path = picker_page_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return "file:///" + path.replace(os.sep, "/").lstrip("/")


# ── Pick resolution — STRICT: no match means error, never default-to-first ────

def resolve_pick(candidates: list[dict], spec: str) -> dict | None:
    """Resolve a spoken pick ('third', '3', 'the sunset one') against the
    candidate list. Returns the candidate or None — NEVER silently defaults,
    because a wrong guess here downloads the wrong image."""
    if not candidates or not spec:
        return None
    p = spec.strip().lower()
    for word, idx in _ORDINALS.items():
        if re.search(r"\b" + word + r"\b", p):
            return candidates[idx] if -len(candidates) <= idx < len(candidates) else None
    m = re.search(r"\b(\d+)\b", p)
    if m:
        idx = int(m.group(1)) - 1
        return candidates[idx] if 0 <= idx < len(candidates) else None
    # fuzzy title/source match: substring, then token overlap
    for c in candidates:
        hay = f"{c['title']} {c['source_domain']}".lower()
        if p in hay:
            return c
    p_tokens = set(re.findall(r"\w+", p)) - {"the", "one", "image", "picture", "photo"}
    best, best_score = None, 0
    for c in candidates:
        hay_tokens = set(re.findall(r"\w+", f"{c['title']} {c['source_domain']}".lower()))
        score = len(p_tokens & hay_tokens)
        if score > best_score:
            best, best_score = c, score
    return best  # None when nothing overlapped at all


def _unique_path(path: str) -> str:
    """Never overwrite: image.jpg -> image (2).jpg -> image (3).jpg ..."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{root} ({n}){ext}"):
        n += 1
    return f"{root} ({n}){ext}"


# ── Actions ───────────────────────────────────────────────────────────────────

def search_image(parameter: str | None = None) -> dict:
    """search_image|query — finds 4-6 safe candidates, shows them on a local
    numbered picker page in the browser, speaks the same numbered list, and
    downloads NOTHING. The user then picks via download_image."""
    global _candidates, _query
    print(f"[search_image] called with parameter={parameter!r}")
    query = (parameter or "").split("|")[0].strip()
    if not query:
        return {"success": False, "message": "Search for what? Describe the image you want."}
    results, err = _search_image_urls(query)
    if err:
        return {"success": False, "message": err}
    _candidates, _query = results, query
    print(f"[search_image] {len(results)} safe results: "
          f"{[r['source_domain'] for r in results]}")

    # Visible navigation step: the browser opens the picker page so the user
    # SEES exactly the candidates Akira reads out. Best-effort — a browser
    # hiccup must not kill the voice flow.
    picker_url = render_picker_page(query, results)
    if _hooks["navigate"]:
        try:
            _hooks["navigate"](picker_url)
            print(f"[search_image] picker page opened: {picker_url}")
        except Exception as e:
            print(f"[search_image] picker navigation failed (non-fatal): {e}")

    listing = "; ".join(
        f"number {i + 1}, {c['title'][:60] if c['title'] else 'untitled'}"
        for i, c in enumerate(results))
    return {"success": True, "speak": True,
            "message": f"Found {len(results)} images for {query} — they're on your "
                       f"screen now: {listing}. Which one should I download?"}


def download_image(parameter: str | None = None) -> dict:
    """download_image|url-or-pick|optional save path. URL → direct download;
    anything else → STRICT pick from the last search_image candidates via
    resolve_pick. Saves to a unique filename, returns the path in
    message AND result['path']."""
    print(f"[download_image] called with parameter={parameter!r}")
    parts = (parameter or "").split("|")
    spec = parts[0].strip() if parts and parts[0].strip() else None
    if not spec:
        return {"success": False, "message": "Download what? Search for images first and pick one."}

    if spec.lower().startswith(("http://", "https://")):
        url, query, title = spec, None, None
    else:
        if not _candidates:
            return {"success": False,
                    "message": f"I haven't searched for images yet. Say search for {spec} first, then pick one."}
        pick = resolve_pick(_candidates, spec)
        if pick is None:
            listing = "; ".join(
                f"number {i + 1}, {c['title'][:60] if c['title'] else 'untitled'}"
                for i, c in enumerate(_candidates))
            return {"success": False, "speak": True,
                    "message": f"I couldn't tell which one you meant by '{spec}'. "
                               f"The options are: {listing}. Say a number or a name."}
        url, query, title = pick["url"], _query, pick["title"]
        print(f"[download_image] resolved pick {spec!r} -> "
              f"#{_candidates.index(pick) + 1} {title[:50]!r} ({url[:80]})")

    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"success": False, "message": f"Couldn't download the image: {e}"}
    if not resp.headers.get("Content-Type", "").startswith("image/"):
        return {"success": False, "message": "That URL didn't return an image."}

    ctype = resp.headers["Content-Type"].split(";")[0]
    url_ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    ext = _EXT_BY_CTYPE.get(ctype) or (url_ext if url_ext in IMG_EXTS else ".jpg")

    base_name = re.sub(r"[^\w\- ]", "", (title or query or
                       os.path.splitext(os.path.basename(urllib.parse.urlparse(url).path))[0]
                       or "image")).strip()[:60] or "image"
    if len(parts) > 1 and parts[1].strip():
        normalize = _hooks["normalize_path"] or os.path.expanduser
        save_path = normalize(parts[1].strip())
        if os.path.isdir(save_path) or not os.path.splitext(save_path)[1]:
            save_path = os.path.join(save_path, base_name + ext)
    else:
        save_path = os.path.join(os.path.expanduser("~/Pictures"), base_name + ext)
    save_path = _unique_path(save_path)

    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(resp.content)
    except OSError as e:
        return {"success": False, "message": f"Downloaded but couldn't save it: {e}"}
    if _hooks["remember"]:
        _hooks["remember"](save_path)
    print(f"[download_image] saved {os.path.getsize(save_path)} bytes -> {save_path}")
    return {"success": True, "path": save_path,
            "message": f"Image saved to {save_path}"}
