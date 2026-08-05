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
import hashlib

# ── Budget. Cost is bounded HERE, deliberately by constants rather than by
# anything about the repo, so worst-case spend is knowable before running.
MAX_FILES = 36            # files ever sent for summarization
MAX_FILE_CHARS = 9000     # per-file clip
BATCH_CHARS = 22000       # per cheap-model call
MAX_BATCHES = 8           # hard ceiling on cheap-model calls
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
    """File body as text via the contents API.

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
    except Exception as e:
        print(f"[repo_notes] fetch failed {path}: {e}")
        return None
    if resp.status_code != 200:
        return None
    text = resp.text
    if "\x00" in text[:1024]:      # binary that slipped the extension filter
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
    except Exception as e:
        print(f"[repo_notes] readme fetch failed: {e}")
        return ""
    return resp.text if resp.status_code == 200 else ""


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
    if not ok or not isinstance(data, dict):
        return [], False
    entries = [e for e in (data.get("tree") or [])
               if e.get("type") == "blob"][:MAX_TREE_ENTRIES]
    return entries, bool(data.get("truncated"))


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


# ── Entry point ──────────────────────────────────────────────────────────────

def generate(repo: str) -> dict:
    """Read `repo` (owner/name) and write linked notes about its architecture.

    Returns the usual {"success", "message"} shape. Runs for minutes, so it is
    always called from a background task, never inline.
    """
    import claude_handler

    repo = (repo or "").strip().strip("/")
    if "/" not in repo:
        return {"success": False,
                "message": "I need the repository as owner and name to do that."}

    ok, info = _api(f"/repos/{repo}")
    if not ok:
        return {"success": False, "message": str(info)}
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

    # ── Path 1: the repo documents itself. One expensive call, no source read.
    summaries: dict = {}
    if _is_substantive(readme):
        print(f"[repo_notes] README-first path ({len(readme)} chars)")
    elif not entries:
        return {"success": False,
                "message": f"I couldn't read the file list for {repo}, and its "
                           f"readme wasn't enough to work from."}
    else:
        # ── Path 2: read the code, cheaply and in batches.
        chosen = _select(entries)
        if not chosen:
            if not readme.strip():
                return {"success": False,
                        "message": f"I couldn't find any source files in {repo} "
                                   f"that I could make sense of."}
            print("[repo_notes] no readable source files — README only")
        else:
            bodies = _fetch_bodies(repo, ref, chosen)
            summaries = _summarize(repo, bodies) if bodies else {}
            if not summaries and not readme.strip():
                return {"success": False,
                        "message": f"I read {repo} but couldn't summarize any of "
                                   f"it, so I haven't written anything."}

    plan = claude_handler.plan_repo_notes(repo, meta, readme, summaries)
    # The original live failure, now recoverable: retry once on a genuinely
    # SMALLER input, because output size tracks input size here. Whichever input
    # is actually carrying the weight is the one that gets halved — on the
    # README-first path there are no summaries to trim, so trimming them would
    # resend byte-identical input and buy an identical failure.
    if isinstance(plan, dict) and plan.get("hit_max_tokens"):
        # Halve the summaries when there are enough of them to halve. With 0 or 1
        # summary that is a no-op, so the README is trimmed instead — otherwise
        # the "retry" would resend byte-identical input and buy an identical
        # failure at full price.
        retry_summaries = summaries
        retry_readme = readme
        if len(summaries) > 1:
            retry_summaries = dict(list(summaries.items())[:len(summaries) // 2])
        elif len(readme) > README_MIN_CHARS:
            retry_readme = readme[:max(README_MIN_CHARS, len(readme) // 2)]

        shrank = (len(retry_summaries) < len(summaries)
                  or len(retry_readme) < len(readme))
        if not shrank:
            # Nothing left to cut. The input is already minimal, so a retry would
            # be identical; don't pay for it twice.
            print("[repo_notes] input already minimal — not retrying")
            plan = None
        else:
            print(f"[repo_notes] retrying with {len(retry_summaries)} summaries, "
                  f"{len(retry_readme)} chars of readme")
            plan = claude_handler.plan_repo_notes(
                repo, meta, retry_readme, retry_summaries)
            if isinstance(plan, dict) and plan.get("hit_max_tokens"):
                plan = None
    if not plan or not plan.get("plan"):
        return {"success": False,
                "message": f"I read through {repo} but couldn't settle on a good "
                           f"note structure for it, so I haven't written anything."}

    done, failures = _write_plan(plan["plan"])
    if not done:
        return {"success": False,
                "message": failures[0] if failures
                else f"Nothing was written to your vault for {repo}."}

    message = plan["summary"] or (
        f"Wrote {len(done)} notes on {repo}: {', '.join(done[:4])}.")
    if failures:
        message += f" {len(failures)} of the writes didn't go through."
    return {"success": True, "speak": True, "message": message}
