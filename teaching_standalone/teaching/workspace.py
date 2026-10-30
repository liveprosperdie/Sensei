"""File store for Teaching Mode. All reads/writes are confined to one directory.

Every path is built from a validated slug plus a relative path that must match
schema.ALLOWED_REL, then re-checked to resolve inside the topic directory. There
is no code path that turns user- or model-supplied text into an arbitrary path.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import contextvars
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config, schema

_LOCK = threading.RLock()
CURRENT_USER_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("current_user_id", default=None)


class WorkspaceError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def user_root(user_id: Optional[str] = None) -> Path:
    uid = user_id or CURRENT_USER_ID.get()
    if uid:
        base = config.workspace_root() / "users" / uid
    else:
        base = config.workspace_root()
    base.mkdir(parents=True, exist_ok=True)
    return base


def topic_dir(slug: str, user_id: Optional[str] = None) -> Path:
    if not isinstance(slug, str) or not schema.SLUG_RE.match(slug):
        raise WorkspaceError("invalid topic id")
    root = user_root(user_id)
    d = (root / slug).resolve()
    if d.parent != root:
        raise WorkspaceError("invalid topic id")
    return d


def _safe_path(slug: str, rel: str) -> Path:
    if not schema.is_allowed_rel(rel):
        raise WorkspaceError("path not allowed")
    d = topic_dir(slug)
    p = (d / rel).resolve()
    if d not in p.parents and p != d:
        raise WorkspaceError("path escapes topic")
    return p


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text(slug: str, rel: str, text: str) -> None:
    with _LOCK:
        _atomic_write(_safe_path(slug, rel), text)


def read_text(slug: str, rel: str) -> str | None:
    p = _safe_path(slug, rel)
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def write_json(slug: str, rel: str, obj) -> None:
    write_text(slug, rel, json.dumps(obj, ensure_ascii=False, indent=2))


def read_json(slug: str, rel: str):
    raw = read_text(slug, rel)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ── Topics ──────────────────────────────────────────────────────────────────

def list_topics(user_id: Optional[str] = None) -> list[dict]:
    out = []
    root = user_root(user_id)
    for d in sorted(root.iterdir()) if root.exists() else []:
        if not d.is_dir() or not schema.SLUG_RE.match(d.name):
            continue
        meta = read_json(d.name, "_topic_meta.json")
        if isinstance(meta, dict):
            out.append(summarize(meta))
    out.sort(key=lambda m: m.get("updated_at") or m.get("created_at") or "", reverse=True)
    return out


def summarize(meta: dict) -> dict:
    lessons = meta.get("lessons") or []
    done = sum(1 for l in lessons if l.get("state") == "completed")
    scores = [l["quiz_score"] for l in lessons if isinstance(l.get("quiz_score"), (int, float))]
    return {
        "topic": meta.get("topic"),
        "topic_slug": meta.get("topic_slug"),
        "status": meta.get("status"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "level": (meta.get("calibration") or {}).get("calibrated_depth"),
        "lesson_count": len(lessons),
        "completed": done,
        "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
        "has_sources": bool((meta.get("sources") or {}).get("local_files")
                            or (meta.get("sources") or {}).get("web_sources")),
    }


def create_topic(topic: str, level: str = "intermediate") -> dict:
    topic = schema.clean_text(topic, 100)
    if len(topic) < 2:
        raise WorkspaceError("topic is too short")
    with _LOCK:
        if len(list_topics()) >= config.MAX_TOPICS:
            raise WorkspaceError("topic limit reached")
        slug = schema.new_slug(topic)
        d = topic_dir(slug)
        d.mkdir(parents=True, exist_ok=False)
        level = schema.clamp_level(level)
        meta = {
            "topic": topic,
            "topic_slug": slug,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "status": "draft",
            "curriculum_architecture": {
                "designed_by": None, "assumed_level": level,
                "audience_note": "", "reliable_sources": [],
            },
            "sources": {"local_files": [], "web_sources": []},
            "calibration": {
                "overview_lesson_id": "lesson_1", "student_feedback": None,
                "calibrated_depth": level, "is_calibrated": False,
            },
            "lessons": [],
            "revision_log": [],
        }
        write_json(slug, "_topic_meta.json", meta)
        return meta


def load_meta(slug: str) -> dict:
    meta = read_json(slug, "_topic_meta.json")
    if not isinstance(meta, dict):
        raise WorkspaceError("topic not found")
    return meta


def save_meta(slug: str, meta: dict) -> None:
    meta["updated_at"] = now_iso()
    write_json(slug, "_topic_meta.json", meta)


def update_meta(slug: str, fn) -> dict:
    """Read-modify-write under the lock so concurrent jobs can't clobber each other."""
    with _LOCK:
        meta = load_meta(slug)
        fn(meta)
        save_meta(slug, meta)
        return meta


def delete_topic(slug: str) -> None:
    with _LOCK:
        d = topic_dir(slug)
        if not d.exists():
            raise WorkspaceError("topic not found")
        shutil.rmtree(d)


def log_revision(meta: dict, trigger: str, action: str, detail: str, after: str | None = None) -> None:
    meta.setdefault("revision_log", []).append({
        "at": now_iso(), "trigger": trigger, "action": action,
        "detail": schema.clean_text(detail, 300), "after_lesson": after,
    })
