"""Teaching Mode configuration: workspace location and hard limits."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Uploaded/ingested documents. Only the *extracted text* is kept; the original
# binary is never stored or served back, so a hostile PDF/DOCX can't be replayed
# to the browser.
ALLOWED_UPLOAD_EXT = {".pdf", ".docx", ".txt", ".md"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB (accommodates textbooks with heavy diagrams & slides)
MAX_SOURCE_CHARS = 1_000_000          # per source, after extraction (~200k words)
MAX_SOURCES_PER_TOPIC = 12
MAX_TOPICS = 200
PAGE_CHARS = 3000                   # synthetic "page" size for txt/md/docx/web

MAX_WEB_BYTES = 1_500_000
WEB_TIMEOUT_S = 10

# Web sources are only ever fetched when (a) the host is on this vetted list AND
# (b) the student explicitly approved that source in the roadmap review screen.
# A model-invented URL on any other host is shown but can never be fetched.
WEB_ALLOWLIST = (
    "wikipedia.org", "arxiv.org", "rfc-editor.org", "ietf.org", "w3.org",
    "developer.mozilla.org", "docs.python.org", "python.org", "kubernetes.io",
    "docs.docker.com", "learn.microsoft.com", "docs.oracle.com", "nist.gov",
    "stanford.edu", "mit.edu", "berkeley.edu", "cmu.edu", "ox.ac.uk", "cam.ac.uk",
    "khanacademy.org", "openstax.org", "mathworld.wolfram.com", "nature.com",
    "ncbi.nlm.nih.gov", "who.int", "docs.aws.amazon.com", "cloud.google.com",
    "raft.github.io", "go.dev", "rust-lang.org", "doc.rust-lang.org",
    "pytorch.org", "tensorflow.org", "scikit-learn.org", "numpy.org",
)


def workspace_root() -> Path:
    """Dedicated directory for all teaching data. Created on first use.

    Defaults to %LOCALAPPDATA%\\Akira\\teaching_workspace (same per-user home as
    the procedural store) so it is never inside the git checkout. Override with
    AKIRA_TEACHING_DIR (tests do).
    """
    env = (os.environ.get("AKIRA_TEACHING_DIR") or "").strip()
    if env:
        root = Path(env)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        root = Path(base) / "Akira" / "teaching_workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()
