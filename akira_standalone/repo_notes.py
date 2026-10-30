"""
repo_notes.py — turn a GitHub repository into a set of linked Obsidian notes.

WHAT THIS REUSES (nothing here is a second implementation)
- executor._gh_api / _gh_token / _gh_repo_from_url  — the existing GitHub REST
  layer, with its own auth, rate-limit and 404 handling already solved.
- obsidian_control._run_organize_step               — the existing Phase 1 vault
  primitives (create / append / link / moc / diagram). This module NEVER writes
  to the vault itself, so every note it produces goes through the same
  clobber-refusing, wikilink-generating code path as ordinary organization.
- claude_handler.summarize_code_batch / plan_repo_notes — the two-model split.
- background_tasks                                  — it never blocks the voice
  session; github_control hands the slow part off.

COST CONTROL, which is the whole design
The live failure was one giant call hitting max_tokens on a whole repo. Reading
an entire repo properly is unaffordable AND unnecessary, so cost is cut in four
independent places, cheapest lever first:

1. README-FIRST SHORT-CIRCUIT. If the repo explains itself, the cheapest correct
   answer is to believe it. A substantive README plus the file layout (which is
   one free API call, paths only, no content) goes straight to the structuring
   pass: ONE model call, no source code read at all.
2. AGGRESSIVE FILE FILTERING. Lockfiles, minified bundles, vendored trees,
   build output, binaries and generated code are dropped before anything is
   fetched. Reading node_modules teaches the model nothing and costs the most.
3. RANKING AND HARD CAPS. Remaining files are scored (entry points and shallow
   source first) and truncated to MAX_FILES, each clipped to MAX_FILE_CHARS.
   Cost is therefore bounded by constants, not by repo size — a 10,000-file
   monorepo costs the same as a 40-file one.
4. CHEAP MODEL FOR THE BULK. Per-file description is mechanical, so it runs on
   Haiku, batched several files per call. The expensive model sees only the short
   summaries, never source, and is called exactly once.

Near-identical files are deduped by content hash before summarization, since
repos routinely carry the same boilerplate in a dozen places.
"""

import re
import time
import hashlib

# ── Budget. Cost is bounded HERE, deliberately by constants rather than by
# anything about the repo, so worst-case spend is knowable before running.
MAX_FILES = 36            # files ever sent for summarization
MAX_FILE_CHARS = 9000     # per-file clip
BATCH_CHARS = 22000       # per cheap-model call
MAX_BATCHES = 8           # hard ceiling on cheap-model calls
NOTES_PER_BATCH = 2       # note BODIES per writing call — keeps output bounded
MAX_TREE_ENTRIES = 4000   # tree entries considered at all

# A README is "substantive" at this length AND with real structure. Length alone
# is a crude proxy — a long one-paragraph pitch is not documentation — so headings
# are required too. The tradeoff accepted here: a repo with an excellent but
# short README pays for the full read anyway. That errs toward better notes.
README_MIN_CHARS = 1500
README_MIN_HEADINGS = 3

# Paths containing any of these are never read: vendored, generated, or build
# output. Reading them costs the most and teaches the least.
_SKIP_SEGMENTS = frozenset({
    "node_modules", "__pycache__", ".git", ".github", "dist", "build", "vendor",
    "third_party", "thirdparty", "venv", ".venv", "env", "site-packages",
    ".next", ".nuxt", "out", "target", "bin", "obj", "coverage", ".cache",
    "bower_components", "pods", ".gradle", "migrations", "fixtures",
    "__snapshots__", "testdata", ".idea", ".vscode", "public", "assets",
    "static", "locales", "i18n", "docs", "examples", "example",
})

_SKIP_FILENAMES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "cargo.lock", "go.sum", "composer.lock", "gemfile.lock", "pipfile.lock",
    "license", "license.md", "license.txt", "changelog.md", "code_of_conduct.md",
    "contributing.md", ".gitignore", ".gitattributes", ".editorconfig",
})

# Source extensions worth summarizing.
_CODE_EXTS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java",
    ".kt", ".kts", ".rb", ".php", ".cs", ".cpp", ".cc", ".c", ".h", ".hpp",
    ".swift", ".m", ".mm", ".scala", ".sh", ".ps1", ".sql", ".vue", ".svelte",
    ".lua", ".dart", ".ex", ".exs", ".erl", ".clj", ".hs", ".ml", ".r", ".jl",
    ".pl", ".groovy", ".zig", ".nim",
})

# Config/manifest files that describe the project's shape. Worth reading even
# though they are not source, because they name the entry points and deps.
_MANIFEST_NAMES = frozenset({
    "package.json", "pyproject.toml", "requirements.txt", "setup.py",
    "setup.cfg", "cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "gemfile", "composer.json", "dockerfile", "docker-compose.yml",
    "makefile", "next.config.js", "next.config.mjs", "vite.config.ts",
    "tsconfig.json", "pubspec.yaml",
})

# Filename stems that usually ARE the architecture. Ranked to the front.
_ENTRY_HINTS = ("main", "index", "app", "server", "cli", "__init__", "core",
                "router", "routes", "handler", "executor", "engine", "client",
                "config", "schema", "models", "model", "api", "run")

# Bodies smaller than this are noise (re-export stubs, empty __init__).
_MIN_USEFUL_CHARS = 120


# ── GitHub reads (thin wrappers over executor's existing REST layer) ─────────

def _api(path: str):
    import executor
    return executor._gh_api(path)


def _raw_file(repo: str, ref: str, path: str) -> str | None:
    """File body as text via the contents API with raw.githubusercontent fallback.

    Uses the raw media type so no base64 round-trip is needed, and sends the
    token when there is one — unlike github_control's readme branch, this also
    works on private repos.
    """
    import urllib.parse
    import requests
    import executor

    headers = {"Accept": "application/vnd.github.raw+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    tok = executor._gh_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    quoted = urllib.parse.quote(path)
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/contents/{quoted}?ref={urllib.parse.quote(ref)}",
            headers=headers, timeout=15)
        if resp.status_code == 401 and tok:
            resp = requests.get(
                f"https://api.github.com/repos/{repo}/contents/{quoted}?ref={urllib.parse.quote(ref)}",
                headers={"Accept": "application/vnd.github.raw+json", "X-GitHub-Api-Version": "2022-11-28"},
                timeout=15)
    except Exception as e:
        print(f"[repo_notes] fetch failed {path}: {e}")
        resp = None

    text = None
    if resp is not None and resp.status_code == 200:
        text = resp.text
    else:
        # Fallback to raw.githubusercontent.com for public repos / rate limit bypass
        try:
            for branch in (ref, "main", "master"):
                raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{quoted}"
                raw_resp = requests.get(raw_url, timeout=15)
                if raw_resp.status_code == 200:
                    text = raw_resp.text
                    break
        except Exception:
            pass

    if not text or "\x00" in text[:1024]:      # binary that slipped the extension filter
        return None
    return text


def _readme(repo: str) -> str:
    """Raw README markdown, or "" if there isn't one."""
    import requests
    import executor

    headers = {"Accept": "application/vnd.github.raw+json"}
    tok = executor._gh_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        resp = requests.get(f"https://api.github.com/repos/{repo}/readme",
                            headers=headers, timeout=15)
        if resp.status_code == 401 and tok:
            resp = requests.get(f"https://api.github.com/repos/{repo}/readme",
                                headers={"Accept": "application/vnd.github.raw+json"}, timeout=15)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"[repo_notes] readme fetch failed: {e}")

    # Fallback to raw.githubusercontent.com for public repos
    try:
        for branch in ("main", "master", "HEAD"):
            for fname in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
                r = requests.get(f"https://raw.githubusercontent.com/{repo}/{branch}/{fname}", timeout=10)
                if r.status_code == 200:
                    return r.text
    except Exception:
        pass
    return ""


def _is_substantive(readme: str) -> bool:
    if len(readme) < README_MIN_CHARS:
        return False
    headings = len(re.findall(r"^#{1,3}\s+\S", readme, re.MULTILINE))
    return headings >= README_MIN_HEADINGS


# ── File selection ───────────────────────────────────────────────────────────

def _skip(path: str) -> bool:
    parts = [p.lower() for p in path.split("/")]
    if any(p in _SKIP_SEGMENTS for p in parts[:-1]):
        return True
    name = parts[-1]
    if name in _SKIP_FILENAMES:
        return True
    if name.startswith("."):
        return True
    if re.search(r"\.(min|bundle|generated|lock)\.", name) or name.endswith(".map"):
        return True
    if re.search(r"[._-](test|spec|stories)\.", name) or name.startswith("test_"):
        return True
    return False


def _interesting(path: str) -> bool:
    name = path.split("/")[-1].lower()
    if name in _MANIFEST_NAMES:
        return True
    dot = name.rfind(".")
    return dot != -1 and name[dot:] in _CODE_EXTS


def _score(entry: dict) -> tuple:
    """Rank: entry points and shallow source first. Lower sorts earlier."""
    path = entry["path"]
    name = path.split("/")[-1].lower()
    stem = name.split(".")[0]
    depth = path.count("/")
    hint = 0 if stem in _ENTRY_HINTS else (1 if any(
        stem.startswith(h) for h in _ENTRY_HINTS) else 2)
    manifest = 0 if name in _MANIFEST_NAMES else 1
    # Mid-sized files carry the most architecture per token; huge ones get
    # clipped anyway and tiny ones say nothing.
    size = entry.get("size") or 0
    size_rank = 0 if 800 <= size <= 60000 else 1
    return (manifest, hint, size_rank, depth, path)


def _tree(repo: str, ref: str) -> tuple[list[dict], bool]:
    """(file entries, truncated) for the whole repo — one API call, no bodies."""
    ok, data = _api(f"/repos/{repo}/git/trees/{ref}?recursive=1")
    if ok and isinstance(data, dict):
        entries = [e for e in (data.get("tree") or [])
                   if e.get("type") == "blob"][:MAX_TREE_ENTRIES]
        return entries, bool(data.get("truncated"))

    # Fallback: GitHub archive zip for public repos if git/trees API rate limited
    try:
        import requests, zipfile, io
        for branch in (ref, "main", "master"):
            resp = requests.get(f"https://github.com/{repo}/archive/refs/heads/{branch}.zip", timeout=20)
            if resp.status_code == 200:
                zf = zipfile.ZipFile(io.BytesIO(resp.content))
                namelist = zf.namelist()
                prefix = namelist[0].split('/')[0] + '/' if namelist else ""
                entries = []
                for info in zf.infolist():
                    if not info.is_dir() and info.filename.startswith(prefix):
                        rel = info.filename[len(prefix):]
                        if rel:
                            entries.append({"path": rel, "size": info.file_size, "type": "blob"})
                print(f"[repo_notes] tree obtained via archive zip fallback: {len(entries)} entries")
                return entries[:MAX_TREE_ENTRIES], False
    except Exception as e:
        print(f"[repo_notes] tree zip fallback failed: {e}")

    return [], False


def _layout(entries: list[dict], limit: int = 220) -> str:
    """Compact path listing. Free context for the structuring pass — the tree
    call already happened, and paths alone reveal a lot of the architecture."""
    paths = sorted(e["path"] for e in entries if not _skip(e["path"]))
    shown = paths[:limit]
    extra = len(paths) - len(shown)
    text = "\n".join(shown)
    if extra > 0:
        text += f"\n... and {extra} more files"
    return text


def _select(entries: list[dict]) -> list[dict]:
    candidates = [e for e in entries
                  if not _skip(e["path"]) and _interesting(e["path"])]
    candidates.sort(key=_score)
    return candidates[:MAX_FILES]


# ── Summarization ────────────────────────────────────────────────────────────

def _fetch_bodies(repo: str, ref: str, chosen: list[dict]) -> list[dict]:
    """Fetch and clip bodies, dropping stubs and exact duplicates."""
    out: list[dict] = []
    seen: set[str] = set()
    for entry in chosen:
        text = _raw_file(repo, ref, entry["path"])
        if not text or len(text.strip()) < _MIN_USEFUL_CHARS:
            continue
        clipped = text[:MAX_FILE_CHARS]
        # Repos carry the same boilerplate in many places; paying to summarize
        # it more than once is pure waste.
        digest = hashlib.sha256(clipped.encode("utf-8", "replace")).hexdigest()
        if digest in seen:
            print(f"[repo_notes] duplicate body skipped: {entry['path']}")
            continue
        seen.add(digest)
        if len(text) > MAX_FILE_CHARS:
            clipped += "\n... [file truncated]"
        out.append({"path": entry["path"], "text": clipped})
    print(f"[repo_notes] FETCHED {len(out)} REAL FILES from {repo} (ref={ref}):")
    for f in out:
        print(f"  - {f['path']}: {len(f['text'])} bytes")
    return out


def _batch(files: list[dict]) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for f in files:
        if current and size + len(f["text"]) > BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append(f)
        size += len(f["text"])
    if current:
        batches.append(current)
    return batches[:MAX_BATCHES]


def _batch_notes(notes: list[dict]) -> list[list[dict]]:
    """Group outline notes into body-writing batches.

    NOTES_PER_BATCH is small on purpose: it is the knob that keeps each writing
    call's OUTPUT bounded, which is the whole reason structuring was split. The
    overview note is written alone — it is the longest and most important body,
    so it gets the full per-call budget to itself.
    """
    overview = [n for n in notes if n.get("overview")]
    rest = [n for n in notes if not n.get("overview")]
    batches = [[n] for n in overview[:1]]
    rest = overview[1:] + rest
    for i in range(0, len(rest), NOTES_PER_BATCH):
        batches.append(rest[i:i + NOTES_PER_BATCH])
    return [b for b in batches if b]


def _summarize(repo: str, files: list[dict]) -> dict:
    import claude_handler

    summaries: dict = {}
    batches = _batch(files)
    print(f"[repo_notes] summarizing {len(files)} files in {len(batches)} batches")
    for i, batch in enumerate(batches, 1):
        got = claude_handler.summarize_code_batch(repo, batch)
        print(f"[repo_notes] batch {i}/{len(batches)} -> {len(got)} summaries")
        # A failed batch is survivable: understanding accumulates across batches,
        # so the structuring pass still gets everything that did come back.
        summaries.update(got)
    return summaries


# ── Vault write-out ──────────────────────────────────────────────────────────

def _write_plan(steps: list) -> tuple[list[str], list[str]]:
    """Execute planned ops through the EXISTING vault primitives."""
    import obsidian_control

    done: list[str] = []
    failures: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        res = obsidian_control._run_organize_step(step)
        print(f"[repo_notes] {step.get('op')} -> {res.get('success')} "
              f"{str(res.get('message', ''))[:80]!r}")
        if res.get("success"):
            title = obsidian_control._note_title((step.get("note") or ""))
            if title:
                done.append(title)
                try:
                    import obsidian_context
                    obsidian_context.note_mentioned(title)
                except Exception:
                    pass
        else:
            failures.append(res.get("message") or "one step failed")
    return done, failures


# ── Word-doc write-out (COM) ──────────────────────────────────────────────────

def _write_word_doc(repo: str, meta: str, outline: dict, bodies: dict, total_words: int, file_summaries: dict | None = None, real_entries: list[dict] | None = None) -> dict:
    """Save repo architecture notes as a brand new Word document via COM.

    Replaces the Obsidian sink. Creates a new doc via Documents.Add(), writes H1
    title, H2 Executive Summary (small summary of whole repo at once), H2 File & Module
    Index (one line for what each file does), H2 per section, strips wikilinks/mermaid,
    and saves to Documents.
    """
    import os
    import re
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass

    try:
        import win32com.client as win32_client
        try:
            word_app = win32_client.GetActiveObject("Word.Application")
        except Exception:
            word_app = win32_client.Dispatch("Word.Application")
        word_app.Visible = True
    except Exception as e:
        print(f"[repo_notes] Word COM dispatch failed: {e}")
        return {"success": False, "message": f"Couldn't start Microsoft Word via COM: {e}"}

    try:
        # 1. BRAND NEW Word document via COM — do NOT operate on ActiveDocument
        doc = word_app.Documents.Add()
    except Exception as e:
        return {"success": False, "message": f"Failed to create new Word document: {e}"}

    try:
        def _get_style(s_id):
            try:
                return doc.Styles(s_id)
            except Exception:
                return None

        h1_style = _get_style(-2) or _get_style("Heading 1")
        h2_style = _get_style(-3) or _get_style("Heading 2")
        norm_style = _get_style(-1) or _get_style("Normal")

        sel = word_app.Selection
        sel.EndKey(6)  # wdStory

        # 2. Heading 1 with repo/project title
        if h1_style is not None:
            try:
                sel.Style = h1_style
            except Exception:
                pass
        title_text = f"{repo} — Architecture & Technical Overview"
        sel.TypeText(title_text)
        sel.TypeParagraph()

        # Heading 2: Executive Summary (Small summary of whole repo at once)
        if h2_style is not None:
            try:
                sel.Style = h2_style
            except Exception:
                pass
        sel.TypeText("Executive Summary")
        sel.TypeParagraph()

        if norm_style is not None:
            try:
                sel.Style = norm_style
            except Exception:
                pass

        summary_intro = outline.get("overview_summary") or outline.get("summary") or ""
        intro_sentences = [
            f"{repo} is an open-source codebase documented by Akira.",
            summary_intro if summary_intro else f"This technical document provides an architectural analysis and structural overview of {repo}.",
            "It breaks down the primary subsystems, core modules, key data structures, and operational workflows.",
            "Each subsequent section details a specific component, explaining its design responsibilities, dependencies, and integration with the system.",
        ]
        sel.TypeText(" ".join(s.strip() for s in intro_sentences if s.strip()))
        sel.TypeParagraph()
        sel.TypeParagraph()

        # Heading 2: File & Module Index (One line for what each file does)
        file_map: dict[str, str] = {}
        real_paths = {e["path"] for e in real_entries if not _skip(e.get("path", ""))} if real_entries else None
        if file_summaries:
            for f_path, f_desc in file_summaries.items():
                if f_path and f_desc:
                    clean_desc = str(f_desc).strip().splitlines()[0]
                    file_map[f_path] = clean_desc
        if outline.get("file_index"):
            for f_path, f_desc in outline["file_index"].items():
                # STRICT FILTER: Only accept from outline if the file actually exists in real_paths!
                if real_paths is not None and f_path not in real_paths and f_path.lower() not in {p.lower() for p in real_paths}:
                    print(f"[repo_notes] Dropping hallucinated file from outline file_index: {f_path}")
                    continue
                if f_path and f_desc and f_path not in file_map:
                    file_map[f_path] = str(f_desc).strip().splitlines()[0]
        for note in outline.get("notes", []):
            purpose = note.get("purpose", "")
            for f_path in note.get("files", []):
                if real_paths is not None and f_path not in real_paths and f_path.lower() not in {p.lower() for p in real_paths}:
                    continue
                if f_path and f_path not in file_map and purpose:
                    file_map[f_path] = purpose

        if file_map:
            if h2_style is not None:
                try:
                    sel.Style = h2_style
                except Exception:
                    pass
            sel.TypeText("File & Module Index")
            sel.TypeParagraph()

            if norm_style is not None:
                try:
                    sel.Style = norm_style
                except Exception:
                    pass
            sel.TypeText(f"The following index outlines the primary files and modules in {repo} along with the specific operational role of each component:")
            sel.TypeParagraph()

            for f_path, f_desc in sorted(file_map.items()):
                sel.TypeText(f"  • {f_path} — {f_desc}")
                sel.TypeParagraph()
            sel.TypeParagraph()

        # 3. For each outline section: Heading 2 with section title, then insert body
        # 4. Skips mermaid diagram embedding and wikilink rendering entirely
        def _clean_body_for_word(text: str) -> list[str]:
            # Wikilinks [[target|display]] -> display, [[target]] -> target
            cleaned = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
            cleaned = re.sub(r"\[\[([^\]]+)\]\]", r"\1", cleaned)
            lines = cleaned.splitlines()
            out_lines = []
            in_mermaid = False
            for line in lines:
                if re.match(r"^```+\s*mermaid", line.strip(), re.IGNORECASE):
                    in_mermaid = True
                    out_lines.append("Component Architecture:")
                    continue
                if in_mermaid:
                    if re.match(r"^```+", line.strip()):
                        in_mermaid = False
                        continue
                    stripped = line.strip()
                    if stripped and not stripped.startswith("graph ") and not stripped.startswith("flowchart "):
                        clean_rel = re.sub(r"[-=]>+|-+[-=]>", " connects to ", stripped)
                        out_lines.append(f"  • {clean_rel}")
                    continue
                if line.startswith("#"):
                    line = line.lstrip("#").strip()
                out_lines.append(line)
            return "\n".join(out_lines).split("\n\n")

        notes = outline.get("notes", [])
        for note in notes:
            t = note["title"]
            body = bodies.get(t, "")
            if not body:
                continue

            if h2_style is not None:
                try:
                    sel.Style = h2_style
                except Exception:
                    pass
            sel.TypeText(t)
            sel.TypeParagraph()

            if norm_style is not None:
                try:
                    sel.Style = norm_style
                except Exception:
                    pass

            for para in _clean_body_for_word(body):
                p_text = para.strip()
                if p_text:
                    sel.TypeText(p_text)
                    sel.TypeParagraph()
            sel.TypeParagraph()

        # 6. Save doc in standard app output location: ~/Documents
        safe_name = repo.replace("/", "_").replace("\\", "_")
        docs_dir = os.path.join(os.path.expanduser("~"), "Documents")
        os.makedirs(docs_dir, exist_ok=True)
        base_name = f"{safe_name}_Architecture_Notes"
        filename = f"{base_name}.docx"
        file_path = os.path.join(docs_dir, filename)

        # Close previous instance of this file if already open in Word
        try:
            for open_d in list(word_app.Documents):
                if open_d != doc:
                    try:
                        if getattr(open_d, "FullName", "").lower() == file_path.lower():
                            open_d.Close(False)
                    except Exception:
                        pass
        except Exception:
            pass

        saved_ok = False
        for target_path, target_name in [
            (file_path, filename),
            (os.path.join(docs_dir, f"{base_name}_{int(time.time())}.docx"), f"{base_name}_{int(time.time())}.docx")
        ]:
            try:
                doc.SaveAs2(target_path)
                file_path, filename = target_path, target_name
                saved_ok = True
                break
            except Exception:
                try:
                    doc.SaveAs(target_path)
                    file_path, filename = target_path, target_name
                    saved_ok = True
                    break
                except Exception:
                    continue

        if not saved_ok:
            return {"success": False, "message": f"Word could not save document to {file_path}."}

        # Confirm file exists and is non-empty
        if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
            return {"success": False, "message": f"Word document was not created at {file_path}."}

        # 7. Exact same background_status completion signal shape
        msg = f"Saved {len(bodies)} sections on {repo} to Word document {filename} ({total_words} words)."
        return {"success": True, "speak": True, "message": msg, "path": file_path}
    except Exception as e:
        print(f"[repo_notes] Error writing Word document: {e}")
        return {"success": False, "message": f"Failed while writing Word document: {e}"}
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ── Entry point ──────────────────────────────────────────────────────────────

def generate(repo: str) -> dict:
    """Read `repo` (owner/name) and write linked notes about its architecture.

    Returns the usual {"success", "message"} shape. Runs for minutes, so it is
    always called from a background task, never inline.
    """
    import claude_handler

    repo = (repo or "").strip().strip("/")
    if "/" not in repo:
        import executor
        resolved, err = executor._resolve_repo_target(repo, None)
        if err or not resolved:
            return {"success": False,
                    "message": err or f"Couldn't find a repo named '{repo}' on your GitHub."}
        repo = resolved

    ok, info = _api(f"/repos/{repo}")
    if not ok:
        if "rate limit" in str(info).lower():
            print(f"[repo_notes] GitHub API rate limit hit on repo info, using fallback metadata for {repo}")
            info = {"full_name": repo, "default_branch": "main", "description": repo, "language": "unknown"}
        else:
            return {"success": False, "message": str(info)}
    repo = info.get("full_name", repo)
    ref = info.get("default_branch") or "HEAD"
    meta_bits = [f"full name: {info.get('full_name')}",
                 f"description: {info.get('description') or 'none'}",
                 f"primary language: {info.get('language') or 'unknown'}",
                 f"stars: {info.get('stargazers_count', 0)}",
                 f"default branch: {ref}"]
    topics = info.get("topics") or []
    if topics:
        meta_bits.append("topics: " + ", ".join(topics[:10]))

    entries, truncated = _tree(repo, ref)
    if truncated:
        meta_bits.append("note: the file tree was too large to list completely")
    layout = _layout(entries) if entries else ""
    if layout:
        meta_bits.append("file layout:\n" + layout)
    meta = "\n".join(meta_bits)

    readme = _readme(repo)

    # ── STAGE 1: ALWAYS read and summarize real source files if available
    chosen = _select(entries) if entries else []
    bodies = []
    summaries: dict = {}
    if chosen:
        bodies = _fetch_bodies(repo, ref, chosen)
        if bodies:
            summaries = _summarize(repo, bodies)

    if not summaries:
        if not readme.strip():
            return {"success": False,
                    "message": f"I couldn't find any readable source files or readme in {repo}."}
        print("[repo_notes] no readable source files — falling back to README only")
    else:
        print(f"[repo_notes] source files summarized: {len(summaries)} files -> {list(summaries.keys())}")

    # ── STAGE 2: decide the structure only. Small, bounded output.
    outline = claude_handler.plan_repo_outline(repo, meta, readme, summaries)
    if isinstance(outline, dict) and outline.get("hit_max_tokens"):
        # The outline carries no prose bodies, so hitting the ceiling here means
        # the INPUT was genuinely too big — trimming it is the right lever, unlike
        # before, when the ceiling was an output problem that trimming could not
        # touch. Whichever input is carrying the weight gets halved.
        retry_summaries, retry_readme = summaries, readme
        if len(summaries) > 1:
            retry_summaries = dict(list(summaries.items())[:len(summaries) // 2])
        elif len(readme) > README_MIN_CHARS:
            retry_readme = readme[:max(README_MIN_CHARS, len(readme) // 2)]
        if (len(retry_summaries) < len(summaries)
                or len(retry_readme) < len(readme)):
            print(f"[repo_notes] outline retry: {len(retry_summaries)} summaries, "
                  f"{len(retry_readme)} chars readme")
            outline = claude_handler.plan_repo_outline(
                repo, meta, retry_readme, retry_summaries)
            if isinstance(outline, dict) and outline.get("hit_max_tokens"):
                outline = None
        else:
            print("[repo_notes] outline input already minimal — not retrying")
            outline = None
    if not outline or not outline.get("notes"):
        return {"success": False,
                "message": f"I read through {repo} but couldn't settle on a good "
                           f"note structure for it, so I haven't written anything."}

    notes = outline["notes"]
    print(f"[repo_notes] outline: {len(notes)} notes -> "
          f"{[n['title'] for n in notes]}")

    # ── STAGE 3: write the bodies in batches. Each call's output is bounded by
    # the batch size, so repo size can no longer blow the ceiling.
    bodies: dict = {}
    for batch in _batch_notes(notes):
        got = claude_handler.write_note_bodies(
            repo, meta, notes, batch, summaries)
        # A dropped/truncated note is retried alone, where it gets the full
        # per-call budget to itself instead of sharing with its batch.
        missing = [n for n in batch if n["title"] not in got]
        if missing and len(batch) > 1:
            for n in missing:
                print(f"[repo_notes] retrying {n['title']!r} alone")
                got.update(claude_handler.write_note_bodies(
                    repo, meta, notes, [n], summaries))
        bodies.update(got)
        print(f"[repo_notes] batch of {len(batch)} -> {len(got)} bodies")

    if not bodies:
        return {"success": False,
                "message": f"I planned out notes for {repo} but couldn't write "
                           f"their content, so I haven't saved anything."}

    # ── STAGE 4: Enforce length >= 900 words (~2 pages) via prompt detail
    total_words = sum(len(b.split()) for b in bodies.values())
    print(f"[repo_notes] generated {total_words} words across {len(bodies)} notes")
    if total_words < 900:
        print(f"[repo_notes] word count ({total_words}) < 900 words (~2 pages). Re-prompting for deeper detail...")
        detail_msg = (
            "Provide an in-depth, thorough technical breakdown for each file and component. "
            "Detail specific architectural responsibilities, key functions, input/output data flow, "
            "and cross-module integrations so that the total output expands to at least 900 words (~2 full pages)."
        )
        expanded = {}
        for batch in _batch_notes(notes):
            got = claude_handler.write_note_bodies(
                repo, meta, notes, batch, summaries, detail_instruction=detail_msg)
            expanded.update(got)
        if sum(len(b.split()) for b in expanded.values()) > total_words:
            bodies.update(expanded)
            total_words = sum(len(b.split()) for b in bodies.values())
            print(f"[repo_notes] length enforcement updated total to {total_words} words")

    # ── STAGE 5: Sink to Word Document (Task 1 sink)
    return _write_word_doc(repo, meta, outline, bodies, total_words, file_summaries=summaries, real_entries=entries)