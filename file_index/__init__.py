"""
file_index — High-performance local file indexing and search subsystem for Akira.
"""

import os
import time
import threading
from typing import Optional, Dict, Any, Callable

from .config import (
    IndexScopeConfig,
    resolve_saved_location,
    save_index_location,
    recommend_default_location,
    get_available_drives
)
from .db import (
    get_connection,
    init_schema,
    enable_ntfs_compression,
    maybe_vacuum_database,
    get_index_size_bytes,
    _db_lock
)
from .scanner import initial_scan, scan_directory_tree, export_directory_map
from .watcher import IndexWatcher
from .content_extractor import ContentExtractionWorker
from .search import search_files as _search_files

_active_db_path: Optional[str] = None
_active_watcher: Optional[IndexWatcher] = None
_active_extractor: Optional[ContentExtractionWorker] = None
_init_lock = threading.Lock()


def get_active_db_path() -> Optional[str]:
    global _active_db_path
    if not _active_db_path:
        path, _, _ = resolve_saved_location()
        _active_db_path = path
    return _active_db_path


def init_file_index(
    background: bool = True,
    prompt_callback: Optional[Callable[[str, str], str]] = None
) -> str:
    """
    Initialize index location, resolve drive changes, run one-time scan if fresh,
    start real-time watcher, start background content worker, and schedule VACUUM.
    """
    global _active_db_path, _active_watcher, _active_extractor

    with _init_lock:
        resolved_path, last_known, reason = resolve_saved_location()

        if not resolved_path:
            # Missing or first run — prompt user or choose recommended default
            suggested_path, is_single_drive = recommend_default_location()
            if prompt_callback:
                chosen_path = prompt_callback(last_known or suggested_path, reason or "")
            else:
                chosen_path = suggested_path

            save_index_location(chosen_path)
            resolved_path = chosen_path
            print(f"[file_index] Initialized search index at: {resolved_path}")

        _active_db_path = resolved_path
        index_dir = os.path.dirname(resolved_path)

        # Enable NTFS transparent compression on the index folder
        enable_ntfs_compression(index_dir)

        conn = get_connection(resolved_path)
        init_schema(conn)

        # Check if weekly VACUUM is due
        maybe_vacuum_database(conn)

        # Check if initial scan has ever run
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM index_meta WHERE key = 'initial_scan_completed';")
        has_completed = cursor.fetchone()

        def _startup_worker():
            if not has_completed:
                print("[file_index] Performing one-time initial disk scan...")
                initial_scan(resolved_path)
            else:
                # Ensure directory map exists and is up to date on boot
                try:
                    export_directory_map(resolved_path)
                except Exception as _map_err:
                    print(f"[file_index] warning exporting directory map: {_map_err}")

            # Start real-time filesystem watcher
            global _active_watcher
            if _active_watcher is None:
                _active_watcher = IndexWatcher(resolved_path)
                _active_watcher.start()

            # Start background content extraction worker
            global _active_extractor
            if _active_extractor is None:
                _active_extractor = ContentExtractionWorker(resolved_path)
                _active_extractor.start()

        if background:
            t = threading.Thread(target=_startup_worker, daemon=True, name="AkiraIndexStartup")
            t.start()
        else:
            _startup_worker()

        return resolved_path


def search_files(
    query: str,
    root: Optional[str] = None,
    content: bool = False,
    max_results: int = 20
) -> Dict[str, Any]:
    """Execute search query using active SQLite database."""
    db_path = get_active_db_path()
    if not db_path or not os.path.exists(db_path):
        db_path = init_file_index(background=False)
    return _search_files(db_path, query, root=root, content=content, max_results=max_results)


def manage_index_scope(action: str, folder_path: Optional[str] = None) -> Dict[str, Any]:
    """Include or exclude specific folders, updating config, SQLite rows, and live watcher."""
    scope = IndexScopeConfig()
    act = action.strip().lower()

    if act == "status":
        return {
            "success": True,
            "speak": True,
            "message": f"Index scope: {len(scope.custom_excludes)} custom excludes, {len(scope.custom_includes)} custom includes.",
            "excludes": list(scope.custom_excludes),
            "includes": list(scope.custom_includes)
        }

    if not folder_path or not folder_path.strip():
        return {"success": False, "message": "Please specify a folder path to manage."}

    norm_path = os.path.normpath(folder_path.strip())
    db_path = get_active_db_path()

    if act in ("exclude", "remove"):
        stored_path = scope.exclude_folder(norm_path)
        # Prune existing entries from database under this folder
        if db_path and os.path.exists(db_path):
            conn = get_connection(db_path)
            with _db_lock:
                with conn:
                    cur = conn.cursor()
                    base = os.path.basename(norm_path)
                    cur.execute("SELECT id FROM folders WHERE name = ?;", (base,))
                    rows = cur.fetchall()
                    for (fid,) in rows:
                        cur.execute("DELETE FROM folders WHERE id = ?;", (fid,))
        return {
            "success": True,
            "speak": True,
            "message": f"Excluded {norm_path} from search index and cleaned up existing entries."
        }

    if act in ("include", "add"):
        if not os.path.exists(norm_path):
            return {"success": False, "message": f"Folder does not exist: {norm_path}"}
        stored_path = scope.include_folder(norm_path)
        # Trigger targeted scan of just this newly included folder
        if db_path and os.path.exists(db_path):
            conn = get_connection(db_path)
            scan_directory_tree(conn, norm_path, scope)
        return {
            "success": True,
            "speak": True,
            "message": f"Included {norm_path} in search index and scanned its contents."
        }

    return {"success": False, "message": f"Unknown scope action: {action}. Use include, exclude, or status."}


def get_index_stats() -> Dict[str, Any]:
    """Report current index database size on disk and file statistics."""
    db_path = get_active_db_path()
    if not db_path or not os.path.exists(db_path):
        return {
            "success": False,
            "message": "Search index is not initialized yet.",
            "size_mb": 0.0
        }

    size_bytes = get_index_size_bytes(db_path)
    size_mb = size_bytes / (1024 * 1024)

    conn = get_connection(db_path)
    with _db_lock:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM files;")
        total_files = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM folders;")
        total_folders = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM content_progress WHERE status = 'indexed';")
        content_docs = cur.fetchone()[0]

    return {
        "success": True,
        "speak": True,
        "message": f"Your search index contains {total_files:,} files ({content_docs:,} document contents indexed) and uses {size_mb:.1f} MB on disk.",
        "size_mb": round(size_mb, 2),
        "total_files": total_files,
        "file_count": total_files,
        "folder_count": total_folders,
        "content_docs": content_docs,
        "db_path": db_path
    }
