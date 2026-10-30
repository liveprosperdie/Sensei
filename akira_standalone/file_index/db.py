"""
file_index/db.py — SQLite database connection, schema management, FTS5 triggers, and VACUUM maintenance.
"""

import os
import sys
import time
import zlib
import sqlite3
import subprocess
import threading
from typing import Optional, Dict, Tuple, List

# Lock for multi-threaded SQLite operations
_db_lock = threading.Lock()
# In-memory folder cache: folder_id -> (name, parent_id, full_path)
_folder_cache: Dict[int, Tuple[str, Optional[int], str]] = {}
_folder_path_to_id: Dict[str, int] = {}
_ext_cache: Dict[str, int] = {}


def get_connection(db_path: str) -> sqlite3.Connection:
    """Create a configured SQLite connection with WAL journal mode and normal synchronous."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA cache_size=-10000;")  # ~10MB page cache
    return conn


def init_schema(conn: sqlite3.Connection):
    """Initialize normalized tables, indices, FTS5 virtual tables, sync triggers, and metadata."""
    with conn:
        # 1. Folders table (tree structure)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
            name TEXT NOT NULL
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);")

        # 2. Extensions table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS extensions (
            id INTEGER PRIMARY KEY,
            ext TEXT UNIQUE NOT NULL
        );
        """)

        # 3. Files table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            ext_id INTEGER REFERENCES extensions(id),
            size INTEGER,
            modified INTEGER,
            is_dir INTEGER DEFAULT 0
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext_id);")

        # 4. Files FTS5 virtual table (External content table)
        conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            name,
            content='files',
            content_rowid='id'
        );
        """)

        # Sync triggers for files -> files_fts
        conn.execute("""
        CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
            INSERT INTO files_fts(rowid, name) VALUES (new.id, new.name);
        END;
        """)
        conn.execute("""
        CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, name) VALUES ('delete', old.id, old.name);
        END;
        """)
        conn.execute("""
        CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, name) VALUES ('delete', old.id, old.name);
            INSERT INTO files_fts(rowid, name) VALUES (new.id, new.name);
        END;
        """)

        # 5. Content chunks table (Canonical compressed text chunks)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS content_chunks (
            id INTEGER PRIMARY KEY,
            file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
            chunk_index INTEGER,
            compressed_text BLOB
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file ON content_chunks(file_id);")

        # 6. Content FTS5 virtual table (Contentless FTS5 index over decompressed plaintext)
        conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
            text,
            content='',
            content_rowid='id'
        );
        """)

        # 7. Content extraction progress tracking
        conn.execute("""
        CREATE TABLE IF NOT EXISTS content_progress (
            file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
            status TEXT NOT NULL,  -- 'pending', 'indexed', 'failed', 'unsupported'
            last_indexed INTEGER,
            error TEXT
        );
        """)

        # 8. Metadata and state table (tracks last vacuum, schema version)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)


def enable_ntfs_compression(dir_path: str) -> bool:
    """Enable NTFS transparent compression on index folder using compact.exe."""
    if not sys.platform.startswith("win"):
        return False
    try:
        abs_p = os.path.abspath(dir_path)
        os.makedirs(abs_p, exist_ok=True)
        # compact /c /i /q compresses folder and sets compression flag for future files
        res = subprocess.run(
            ["compact.exe", "/c", "/i", "/q", abs_p],
            capture_output=True,
            text=True,
            creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
        return res.returncode == 0
    except Exception as e:
        print(f"[file_index.db] enable_ntfs_compression error: {e}")
        return False


def maybe_vacuum_database(conn: sqlite3.Connection, force: bool = False) -> bool:
    """
    Check if 7+ days (604,800s) have passed since last VACUUM.
    If so (or if forced), executes VACUUM to reclaim disk space and updates last_vacuum_time.
    """
    now = time.time()
    with _db_lock:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM index_meta WHERE key = 'last_vacuum_time';")
            row = cursor.fetchone()
            last_vacuum = float(row[0]) if row else 0.0

            if force or (now - last_vacuum) >= 7 * 86400:
                print(f"[file_index.db] Executing periodic VACUUM on search index (last run: {last_vacuum})...")
                # VACUUM cannot be run inside a transaction block
                conn.commit()
                conn.isolation_level = None
                conn.execute("VACUUM;")
                conn.isolation_level = ""
                conn.execute(
                    "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('last_vacuum_time', ?);",
                    (str(now),)
                )
                conn.commit()
                print("[file_index.db] VACUUM completed successfully.")
                return True
        except Exception as e:
            print(f"[file_index.db] VACUUM check warning: {e}")
    return False


_CONN_CACHES: Dict[int, Tuple[Dict[str, int], Dict[int, Tuple[str, Optional[int], str]], Dict[str, int]]] = {}


def _get_caches(conn: sqlite3.Connection) -> Tuple[Dict[str, int], Dict[int, Tuple[str, Optional[int], str]], Dict[str, int]]:
    cid = id(conn)
    if cid not in _CONN_CACHES:
        _CONN_CACHES[cid] = ({}, {}, {})
    return _CONN_CACHES[cid]


def clear_caches(conn: Optional[sqlite3.Connection] = None):
    if conn is not None:
        _CONN_CACHES.pop(id(conn), None)
    else:
        _CONN_CACHES.clear()


def get_or_create_extension(conn: sqlite3.Connection, ext: str) -> int:
    """Get extension ID, caching in memory for high speed."""
    ext_norm = ext.lower().strip()
    if not ext_norm.startswith(".") and ext_norm:
        ext_norm = "." + ext_norm
    _, _, ext_cache = _get_caches(conn)
    if ext_norm in ext_cache:
        return ext_cache[ext_norm]

    cursor = conn.cursor()
    cursor.execute("SELECT id FROM extensions WHERE ext = ?;", (ext_norm,))
    row = cursor.fetchone()
    if row:
        eid = row[0]
    else:
        cursor.execute("INSERT OR IGNORE INTO extensions(ext) VALUES (?);", (ext_norm,))
        eid = cursor.lastrowid or get_or_create_extension(conn, ext_norm)
    ext_cache[ext_norm] = eid
    return eid


def get_or_create_folder(conn: sqlite3.Connection, full_folder_path: str) -> int:
    """
    Walk up the directory hierarchy and insert any missing folders,
    caching path-to-id mappings in memory per connection.
    """
    folder_path_to_id, folder_cache, _ = _get_caches(conn)
    norm_path = os.path.normpath(full_folder_path)
    if norm_path in folder_path_to_id:
        return folder_path_to_id[norm_path]

    # Split into path components
    drive, rest = os.path.splitdrive(norm_path)
    parts = [p for p in rest.replace("/", "\\").split("\\") if p]
    if drive:
        root_name = drive + "\\"
    else:
        root_name = "/"

    # Handle root folder
    current_parent_id: Optional[int] = None
    accum_path = root_name
    if accum_path in folder_path_to_id:
        current_parent_id = folder_path_to_id[accum_path]
    else:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM folders WHERE parent_id IS NULL AND name = ?;", (root_name,))
        row = cursor.fetchone()
        if row:
            current_parent_id = row[0]
        else:
            cursor.execute("INSERT INTO folders(parent_id, name) VALUES (NULL, ?);", (root_name,))
            current_parent_id = cursor.lastrowid
        folder_path_to_id[accum_path] = current_parent_id
        folder_cache[current_parent_id] = (root_name, None, accum_path)

    # Handle subfolders
    for part in parts:
        accum_path = os.path.join(accum_path, part)
        if accum_path in folder_path_to_id:
            current_parent_id = folder_path_to_id[accum_path]
        else:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM folders WHERE parent_id = ? AND name = ?;", (current_parent_id, part))
            row = cursor.fetchone()
            if row:
                fid = row[0]
            else:
                cursor.execute("INSERT INTO folders(parent_id, name) VALUES (?, ?);", (current_parent_id, part))
                fid = cursor.lastrowid
            folder_path_to_id[accum_path] = fid
            folder_cache[fid] = (part, current_parent_id, accum_path)
            current_parent_id = fid

    return current_parent_id


def reconstruct_folder_path(conn: sqlite3.Connection, folder_id: int) -> str:
    """Reconstruct full folder path from folder_id using in-memory cache or CTE fallback."""
    _, folder_cache, _ = _get_caches(conn)
    if folder_id in folder_cache:
        return folder_cache[folder_id][2]

    # CTE fallback
    sql = """
    WITH RECURSIVE folder_path(id, parent_id, path) AS (
        SELECT id, parent_id, name FROM folders WHERE parent_id IS NULL
        UNION ALL
        SELECT f.id, f.parent_id,
               CASE
                   WHEN fp.path LIKE '%\\' OR fp.path LIKE '%/' THEN fp.path || f.name
                   ELSE fp.path || '\\' || f.name
               END
        FROM folders f JOIN folder_path fp ON f.parent_id = fp.id
    )
    SELECT path FROM folder_path WHERE id = ?;
    """
    cursor = conn.cursor()
    cursor.execute(sql, (folder_id,))
    row = cursor.fetchone()
    path = row[0] if row else ""
    return path


def get_index_size_bytes(db_path: str) -> int:
    """Return total size in bytes of the index database including WAL file if present."""
    total = 0
    if os.path.exists(db_path):
        total += os.path.getsize(db_path)
    wal_path = db_path + "-wal"
    if os.path.exists(wal_path):
        total += os.path.getsize(wal_path)
    return total
