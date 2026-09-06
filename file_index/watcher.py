"""
file_index/watcher.py — Real-time filesystem watcher keeping SQLite index in continuous sync.
"""

import os
import time
import queue
import threading
from typing import List, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from .config import IndexScopeConfig, DEFAULT_CONTENT_EXTENSIONS
from .db import (
    get_connection,
    get_or_create_folder,
    get_or_create_extension,
    _db_lock
)


class IndexChangeHandler(FileSystemEventHandler):
    """Event handler that filters events against scope config and queues database sync operations."""

    def __init__(self, event_queue: queue.Queue, scope_config: IndexScopeConfig):
        super().__init__()
        self.queue = event_queue
        self.scope_config = scope_config

    def _should_ignore(self, path: str) -> bool:
        norm = os.path.normpath(path)
        base = os.path.basename(norm)
        return self.scope_config.is_excluded(base, norm)

    def on_created(self, event: FileSystemEvent):
        if not self._should_ignore(event.src_path):
            self.queue.put(("created", event.is_directory, event.src_path, None))

    def on_deleted(self, event: FileSystemEvent):
        if not self._should_ignore(event.src_path):
            self.queue.put(("deleted", event.is_directory, event.src_path, None))

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.queue.put(("modified", False, event.src_path, None))

    def on_moved(self, event: FileSystemEvent):
        dest_ignored = self._should_ignore(event.dest_path)
        src_ignored = self._should_ignore(event.src_path)
        if not dest_ignored or not src_ignored:
            self.queue.put(("moved", event.is_directory, event.src_path, event.dest_path))


class IndexWatcher:
    """Manages background watchdog observer and sync worker thread."""

    def __init__(self, db_path: str, roots: Optional[List[str]] = None):
        self.db_path = db_path
        self.roots = roots or []
        self.scope_config = IndexScopeConfig()
        self.event_queue: queue.Queue = queue.Queue()
        self.observer = Observer()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def start(self):
        if not self.roots:
            from .config import get_available_drives
            self.roots = [d["root"] for d in get_available_drives() if os.path.exists(d["root"])]

        handler = IndexChangeHandler(self.event_queue, self.scope_config)
        for root in self.roots:
            if os.path.exists(root):
                try:
                    self.observer.schedule(handler, path=root, recursive=True)
                    print(f"[file_index.watcher] Watching root: {root}")
                except Exception as e:
                    print(f"[file_index.watcher] Could not watch {root}: {e}")

        self.observer.start()

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._process_events_loop,
            daemon=True,
            name="AkiraIndexWatcherWorker"
        )
        self._worker_thread.start()

    def stop(self):
        self._stop_event.set()
        try:
            self.observer.stop()
            self.observer.join(timeout=2.0)
        except Exception:
            pass
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)

    def _process_events_loop(self):
        conn = get_connection(self.db_path)
        while not self._stop_event.is_set():
            try:
                # Wait for next event with a 1-second timeout
                item = self.event_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            event_type, is_dir, src_path, dest_path = item
            try:
                self._apply_event(conn, event_type, is_dir, src_path, dest_path)
            except Exception as e:
                print(f"[file_index.watcher] Error processing {event_type} for {src_path}: {e}")

    def _apply_event(self, conn, event_type: str, is_dir: bool, src_path: str, dest_path: Optional[str]):
        src_path = os.path.normpath(src_path)
        parent_dir = os.path.dirname(src_path)
        name = os.path.basename(src_path)

        with _db_lock:
            with conn:
                cur = conn.cursor()
                if event_type == "created":
                    if is_dir:
                        get_or_create_folder(conn, src_path)
                    else:
                        if not os.path.isfile(src_path):
                            return
                        try:
                            st = os.stat(src_path)
                            size = st.st_size
                            mtime = int(st.st_mtime)
                        except OSError:
                            return

                        folder_id = get_or_create_folder(conn, parent_dir)
                        _, ext = os.path.splitext(name)
                        ext_id = get_or_create_extension(conn, ext)

                        cur.execute("""
                        INSERT OR REPLACE INTO files (folder_id, name, ext_id, size, modified, is_dir)
                        VALUES (?, ?, ?, ?, ?, 0);
                        """, (folder_id, name, ext_id, size, mtime))
                        file_id = cur.lastrowid

                        if ext.lower() in DEFAULT_CONTENT_EXTENSIONS:
                            cur.execute("""
                            INSERT OR REPLACE INTO content_progress (file_id, status)
                            VALUES (?, 'pending');
                            """, (file_id,))

                elif event_type == "deleted":
                    if is_dir:
                        # Deleting folder cascades to all child folders and files
                        cur.execute("SELECT id FROM folders WHERE name = ?;", (name,))
                        rows = cur.fetchall()
                        for r in rows:
                            cur.execute("DELETE FROM folders WHERE id = ?;", (r[0],))
                    else:
                        cur.execute("""
                        DELETE FROM files
                        WHERE name = ? AND folder_id IN (
                            SELECT id FROM folders WHERE name = ?
                        );
                        """, (name, os.path.basename(parent_dir)))

                elif event_type == "modified":
                    if not is_dir and os.path.isfile(src_path):
                        try:
                            st = os.stat(src_path)
                            size = st.st_size
                            mtime = int(st.st_mtime)
                        except OSError:
                            return

                        cur.execute("""
                        UPDATE files
                        SET size = ?, modified = ?
                        WHERE name = ? AND folder_id IN (
                            SELECT id FROM folders WHERE name = ?
                        );
                        """, (size, mtime, name, os.path.basename(parent_dir)))

                        # Re-queue content extraction if file is in content_progress
                        cur.execute("""
                        UPDATE content_progress
                        SET status = 'pending'
                        WHERE file_id IN (
                            SELECT id FROM files WHERE name = ?
                        );
                        """, (name,))

                elif event_type == "moved" and dest_path:
                    dest_path = os.path.normpath(dest_path)
                    new_parent = os.path.dirname(dest_path)
                    new_name = os.path.basename(dest_path)

                    if is_dir:
                        new_parent_id = get_or_create_folder(conn, new_parent)
                        cur.execute("""
                        UPDATE folders
                        SET name = ?, parent_id = ?
                        WHERE name = ?;
                        """, (new_name, new_parent_id, name))
                    else:
                        new_folder_id = get_or_create_folder(conn, new_parent)
                        _, ext = os.path.splitext(new_name)
                        ext_id = get_or_create_extension(conn, ext)
                        cur.execute("""
                        UPDATE files
                        SET name = ?, folder_id = ?, ext_id = ?
                        WHERE name = ?;
                        """, (new_name, new_folder_id, ext_id, name))
