"""
file_index/scanner.py — One-time initial disk scan with walk-time exclude pruning.
"""

import os
import time
import sqlite3
from typing import Optional, List, Callable
from .config import IndexScopeConfig, get_available_drives, DEFAULT_CONTENT_EXTENSIONS
from .db import (
    get_connection,
    init_schema,
    get_or_create_folder,
    get_or_create_extension,
    _db_lock
)


def scan_directory_tree(
    conn: sqlite3.Connection,
    root_dir: str,
    scope_config: Optional[IndexScopeConfig] = None,
    batch_size: int = 2000,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    scope: Optional[IndexScopeConfig] = None
) -> int:
    """
    Walk a root directory tree, pruning excluded directories at walk time,
    and batching inserts into folders, files, and content_progress.
    """
    if scope_config is None:
        scope_config = scope or IndexScopeConfig()
    total_files_indexed = 0
    file_batch = []
    content_queue = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # 1. Prune excluded directories at walk time so they are never traversed
        dirnames[:] = [
            d for d in dirnames
            if not scope_config.is_excluded(d, os.path.join(dirpath, d))
        ]

        # 2. Ensure current folder exists in folders table
        folder_id = get_or_create_folder(conn, dirpath)

        for fn in filenames:
            full_path = os.path.join(dirpath, fn)
            try:
                stat = os.stat(full_path)
                size = stat.st_size
                mtime = int(stat.st_mtime)
            except (OSError, PermissionError):
                continue

            _, ext = os.path.splitext(fn)
            ext_id = get_or_create_extension(conn, ext)

            file_batch.append((folder_id, fn, ext_id, size, mtime, 0, ext.lower()))
            total_files_indexed += 1

            if len(file_batch) >= batch_size:
                _commit_file_batch(conn, file_batch)
                file_batch.clear()
                if progress_callback:
                    progress_callback(total_files_indexed, dirpath)

    if file_batch:
        _commit_file_batch(conn, file_batch)
        file_batch.clear()
        if progress_callback:
            progress_callback(total_files_indexed, root_dir)

    return total_files_indexed


def _commit_file_batch(conn: sqlite3.Connection, batch: list):
    """Commit batch of files into `files` table and queue eligible documents in `content_progress`."""
    with _db_lock:
        with conn:
            cursor = conn.cursor()
            for folder_id, name, ext_id, size, mtime, is_dir, ext_lower in batch:
                cursor.execute("""
                INSERT INTO files (folder_id, name, ext_id, size, modified, is_dir)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (folder_id, name, ext_id, size, mtime, is_dir))
                file_id = cursor.lastrowid

                # Enqueue eligible documents for Standard/Pro background content extraction
                if ext_lower in DEFAULT_CONTENT_EXTENSIONS and size < 20 * 1024 * 1024:  # < 20MB file
                    cursor.execute("""
                    INSERT OR IGNORE INTO content_progress (file_id, status)
                    VALUES (?, 'pending');
                    """, (file_id,))


def initial_scan(
    db_path: str,
    roots: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> int:
    """
    Perform full initial scan across all drives or given roots.
    Populates SQLite database and marks initial scan complete.
    """
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    init_schema(conn)

    scope_config = IndexScopeConfig()

    if not roots:
        drives = get_available_drives()
        roots = [d["root"] for d in drives]

    print(f"[file_index.scanner] Starting initial scan across roots: {roots}")
    total_indexed = 0
    for root in roots:
        if os.path.exists(root):
            try:
                count = scan_directory_tree(conn, root, scope_config, progress_callback=progress_callback)
                total_indexed += count
                print(f"[file_index.scanner] Finished root {root}: {count} files indexed.")
            except Exception as e:
                print(f"[file_index.scanner] Error scanning root {root}: {e}")

    dt = time.perf_counter() - t0
    print(f"[file_index.scanner] Initial scan complete: {total_indexed} files indexed in {dt:.2f}s.")

    with _db_lock:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('initial_scan_completed', ?);",
                (str(time.time()),)
            )

    return total_indexed
