"""
file_index/content_extractor.py — Low-priority background document content extraction worker.
"""

import os
import sys
import zlib
import time
import ctypes
import threading
import sqlite3
from typing import Optional
from .db import (
    get_connection,
    reconstruct_folder_path,
    maybe_vacuum_database,
    _db_lock
)

# Text truncation cap per file (50KB)
MAX_CONTENT_CHARS = 50 * 1024
CHUNK_SIZE = 4 * 1024  # 4KB per chunk


def _set_low_thread_priority():
    """Set the calling thread's Windows priority to THREAD_PRIORITY_BELOW_NORMAL."""
    if sys.platform.startswith("win"):
        try:
            THREAD_PRIORITY_BELOW_NORMAL = -1
            handle = ctypes.windll.kernel32.GetCurrentThread()
            ctypes.windll.kernel32.SetThreadPriority(handle, THREAD_PRIORITY_BELOW_NORMAL)
        except Exception:
            pass


def extract_text_from_file(file_path: str) -> Optional[str]:
    """Extract up to 50KB of text from supported documents (PDF, DOCX, text/code)."""
    if not os.path.isfile(file_path):
        return None

    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    # 1. PDF extraction via pypdf
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            text_parts = []
            total_chars = 0
            for page in reader.pages:
                txt = page.extract_text() or ""
                text_parts.append(txt)
                total_chars += len(txt)
                if total_chars >= MAX_CONTENT_CHARS:
                    break
            return "".join(text_parts)[:MAX_CONTENT_CHARS]
        except Exception as e:
            return None

    # 2. DOCX extraction via python-docx
    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(file_path)
            text_parts = []
            total_chars = 0
            for p in doc.paragraphs:
                txt = p.text + "\n"
                text_parts.append(txt)
                total_chars += len(txt)
                if total_chars >= MAX_CONTENT_CHARS:
                    break
            return "".join(text_parts)[:MAX_CONTENT_CHARS]
        except Exception as e:
            return None

    # 3. Plain text / Markdown / Source code
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(MAX_CONTENT_CHARS)
    except Exception:
        return None


class ContentExtractionWorker:
    """Low-priority background worker that indexes document content for Standard/Pro users."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="AkiraContentExtractor"
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run_loop(self):
        _set_low_thread_priority()
        conn = get_connection(self.db_path)

        while not self._stop_event.is_set():
            # Check tier eligibility: only Standard and Pro tiers extract content
            try:
                import tiers
                allowed, _ = tiers.content_search_allowed()
                if not allowed:
                    # Sleep and re-check periodically
                    time.sleep(10.0)
                    continue
            except Exception:
                pass

            # Fetch small batch of pending files
            with _db_lock:
                cursor = conn.cursor()
                cursor.execute("""
                SELECT cp.file_id, f.folder_id, f.name
                FROM content_progress cp
                JOIN files f ON cp.file_id = f.id
                WHERE cp.status = 'pending'
                LIMIT 10;
                """)
                batch = cursor.fetchall()

            if not batch:
                # Idle: check if weekly VACUUM is due (7+ days), then sleep
                try:
                    maybe_vacuum_database(conn)
                except Exception:
                    pass
                time.sleep(5.0)
                continue

            for file_id, folder_id, name in batch:
                if self._stop_event.is_set():
                    break

                folder_path = reconstruct_folder_path(conn, folder_id)
                full_path = os.path.join(folder_path, name)

                extracted_text = extract_text_from_file(full_path)
                now = int(time.time())

                with _db_lock:
                    with conn:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM content_chunks WHERE file_id = ?;", (file_id,))
                        try:
                            cur.execute("DELETE FROM content_fts WHERE rowid = ?;", (file_id,))
                        except sqlite3.OperationalError:
                            pass

                        if extracted_text and extracted_text.strip():
                            # Chunk into segments, compress with zlib
                            chunks = [
                                extracted_text[i:i + CHUNK_SIZE]
                                for i in range(0, len(extracted_text), CHUNK_SIZE)
                            ]
                            for idx, chunk in enumerate(chunks):
                                compressed = zlib.compress(chunk.encode("utf-8"))
                                cur.execute("""
                                INSERT INTO content_chunks (file_id, chunk_index, compressed_text)
                                VALUES (?, ?, ?);
                                """, (file_id, idx, compressed))

                            # Insert decompressed text into contentless FTS5 index
                            cur.execute("""
                            INSERT INTO content_fts (rowid, text)
                            VALUES (?, ?);
                            """, (file_id, extracted_text))

                            cur.execute("""
                            UPDATE content_progress
                            SET status = 'indexed', last_indexed = ?, error = NULL
                            WHERE file_id = ?;
                            """, (now, file_id))
                        else:
                            cur.execute("""
                            UPDATE content_progress
                            SET status = 'unsupported', last_indexed = ?, error = 'No extractable text'
                            WHERE file_id = ?;
                            """, (now, file_id))

                # Yield briefly between files to keep system responsive
                time.sleep(0.05)
