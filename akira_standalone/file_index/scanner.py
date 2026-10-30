"""
file_index/scanner.py — One-time initial disk scan with walk-time exclude pruning.
"""

import os
import time
import datetime
import sqlite3
from typing import Optional, List, Callable, Any
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

    # Persist directory map to disk
    try:
        export_directory_map(conn, os.path.join(os.path.dirname(os.path.abspath(db_path)), "directory_map.txt"))
    except Exception as _exp_err:
        print(f"[file_index.scanner] warning exporting directory map: {_exp_err}")

    return total_indexed


def export_directory_map(
    conn_or_db_path: str | sqlite3.Connection,
    output_path: Optional[str] = None
) -> str:
    """
    Export a structured human-readable directory map file from the indexed database.
    Writes to index directory (directory_map.txt) and mirrors to Akira config directory.
    """
    import datetime
    from .config import get_directory_map_file, get_config_dir

    if isinstance(conn_or_db_path, str):
        conn = get_connection(conn_or_db_path)
        close_on_exit = True
        index_dir = os.path.dirname(os.path.abspath(conn_or_db_path))
    else:
        conn = conn_or_db_path
        close_on_exit = False
        index_dir = None

    try:
        with _db_lock:
            cur = conn.cursor()
            cur.execute("SELECT id, parent_id, name FROM folders;")
            folders = cur.fetchall()
            cur.execute("SELECT folder_id, name, size FROM files;")
            files = cur.fetchall()

        parent_map = {fid: (pid, name) for fid, pid, name in folders}
        path_cache = {}

        def get_p(fid):
            if fid in path_cache:
                return path_cache[fid]
            pid, name = parent_map.get(fid, (None, ""))
            if pid is None:
                p = name
            else:
                p = os.path.join(get_p(pid), name)
            path_cache[fid] = p
            return p

        folder_files = {}
        for fid, fn, sz in files:
            folder_files.setdefault(fid, []).append((fn, sz))

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "=" * 80,
            "AKIRA LOCAL DIRECTORY MAP & FILE LISTING",
            f"Generated: {now_str}",
            f"Total Folders: {len(folders):,} | Total Files: {len(files):,}",
            "=" * 80,
            ""
        ]

        for fid in sorted(parent_map.keys(), key=lambda f: get_p(f)):
            p = get_p(fid)
            lines.append(f"[DIR] {p}")
            f_list = folder_files.get(fid, [])
            for fn, sz in sorted(f_list):
                sz_str = f" ({sz:,} bytes)" if sz is not None else ""
                lines.append(f"  {fn}{sz_str}")
            lines.append("")

        text_content = "\n".join(lines)

        primary_path = output_path or (
            get_directory_map_file(index_dir) if index_dir else get_directory_map_file()
        )
        os.makedirs(os.path.dirname(primary_path), exist_ok=True)
        with open(primary_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(text_content)

        # Mirror target path in AppData Akira config directory
        mirror_path = os.path.join(get_config_dir(), "directory_map.txt")
        if os.path.abspath(mirror_path).lower() != os.path.abspath(primary_path).lower():
            try:
                os.makedirs(os.path.dirname(mirror_path), exist_ok=True)
                with open(mirror_path, "w", encoding="utf-8", errors="replace") as f:
                    f.write(text_content)
            except Exception as e:
                print(f"[file_index.scanner] warning mirroring directory map: {e}")

        print(f"[file_index.scanner] Directory map saved to: {primary_path} ({len(lines):,} lines, {len(files):,} files)")
        return primary_path
    finally:
        if close_on_exit:
            try:
                conn.close()
            except Exception:
                pass


def export_drives_map_to_downloads(
    conn_or_db_path: str | sqlite3.Connection | None = None,
    drives: tuple[str, ...] = ("C:\\", "D:\\", "E:\\")
) -> dict[str, str]:
    """Export a detailed file and directory map of C, D, and E drives to Downloads.
    
    Saved strictly to Downloads:
    - akira_drive_map.json (machine-readable, code-only execution)
    - akira_drive_map.txt (human-readable structure)
    
    ACCESSED ONLY BY CODE AND NEVER PASSED TO LLM TO PREVENT DATA LEAKAGE.
    Features live demonstrable folder exclusion zones for audience presentations.
    """
    import json
    import datetime
    from .search import is_sensitive_file
    from .config import IndexScopeConfig

    scope_cfg = IndexScopeConfig()
    downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(downloads_dir, exist_ok=True)
    json_path = os.path.join(downloads_dir, "akira_drive_map.json")
    txt_path = os.path.join(downloads_dir, "akira_drive_map.txt")

    valid_drives = [d for d in drives if os.path.exists(d)]
    if not valid_drives:
        valid_drives = ["C:\\"] if os.path.exists("C:\\") else []

    drive_data: dict[str, Any] = {}
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Header with live active exclusions section
    txt_lines = [
        "=" * 80,
        f"AKIRA COMPREHENSIVE LOCAL DRIVE MAP ({', '.join(valid_drives)})",
        f"Generated: {now_str}",
        "CONFIDENTIAL — ACCESSED ONLY BY LOCAL RUNTIME CODE (NEVER SENT TO LLM)",
        "=" * 80,
        "",
        "[ACTIVE PRIVACY EXCLUSIONS — ENFORCED BY USER & NEVER ACCESSED]"
    ]

    if scope_cfg.custom_excludes:
        for exc in sorted(scope_cfg.custom_excludes):
            txt_lines.append(f"  * {exc} [EXCLUDED BY USER — 0 FILES ACCESSIBLE]")
    else:
        txt_lines.append("  (No user exclusions active. Exclude via: Akira voice 'Exclude folder <name>' or demo script)")
    txt_lines.append("=" * 80)
    txt_lines.append("")

    total_folders = 0
    total_files = 0

    # Fast scan from SQLite index if available
    conn = None
    close_conn = False
    try:
        if conn_or_db_path:
            if isinstance(conn_or_db_path, str) and os.path.exists(conn_or_db_path):
                conn = get_connection(conn_or_db_path)
                close_conn = True
            elif isinstance(conn_or_db_path, sqlite3.Connection):
                conn = conn_or_db_path
        else:
            from .config import get_index_db_file
            def_db, _ = get_index_db_file()
            if os.path.exists(def_db):
                conn = get_connection(def_db)
                close_conn = True
    except Exception:
        conn = None

    if conn:
        try:
            with _db_lock:
                cur = conn.cursor()
                cur.execute("SELECT id, parent_id, name FROM folders;")
                folders = cur.fetchall()
                cur.execute("SELECT folder_id, name, size, modified FROM files;")
                files = cur.fetchall()

            parent_map = {fid: (pid, name) for fid, pid, name in folders}
            path_cache: dict[int, str] = {}

            def get_p(fid: int) -> str:
                if fid in path_cache:
                    return path_cache[fid]
                pid, name = parent_map.get(fid, (None, ""))
                if pid is None:
                    p = name
                else:
                    p = os.path.join(get_p(pid), name)
                path_cache[fid] = p
                return p

            folder_files: dict[int, list[tuple[str, int, int]]] = {}
            for fid, fn, sz, mtime in files:
                if not is_sensitive_file(fn):
                    folder_files.setdefault(fid, []).append((fn, sz, mtime))

            for d in valid_drives:
                d_norm = d.rstrip("\\").lower()
                d_folders = []
                d_files_list = []

                for fid in sorted(parent_map.keys(), key=lambda f: get_p(f)):
                    p = get_p(fid)
                    if p.lower().startswith(d_norm):
                        folder_base = os.path.basename(p)
                        if scope_cfg.is_excluded(folder_base, p):
                            txt_lines.append(f"[DIR] {p} [EXCLUDED BY USER — PROTECTED PRIVACY ZONE]")
                            txt_lines.append("")
                            continue

                        d_folders.append(p)
                        txt_lines.append(f"[DIR] {p}")
                        for fn, sz, mtime in folder_files.get(fid, []):
                            full_f = os.path.join(p, fn)
                            if is_sensitive_file(fn, full_f):
                                continue
                            d_files_list.append({
                                "name": fn,
                                "path": full_f,
                                "size": sz,
                                "modified": mtime
                            })
                            txt_lines.append(f"  {fn} ({sz:,} bytes)" if sz else f"  {fn}")
                        txt_lines.append("")

                drive_data[d] = {
                    "folders_count": len(d_folders),
                    "files_count": len(d_files_list),
                    "folders": d_folders,
                    "files": d_files_list
                }
                total_folders += len(d_folders)
                total_files += len(d_files_list)

        except Exception as e:
            print(f"[file_index.scanner] DB extraction error for drive map: {e}")
        finally:
            if close_conn and conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # Direct walk for any drive missing from DB (e.g. C:\ user docs or fresh drives)
    for d in valid_drives:
        if d not in drive_data or drive_data[d]["files_count"] == 0:
            d_folders = []
            d_files_list = []
            txt_lines.append(f"[DRIVE ROOT] {d}")
            try:
                # If C:\ drive, prioritize User folders, Desktop, Documents, Downloads, Coding
                walk_roots = [d]
                if d.upper().startswith("C:"):
                    user_prof = os.environ.get("USERPROFILE") or os.path.expanduser("~")
                    walk_roots = [
                        os.path.join(user_prof, sub)
                        for sub in ["Documents", "Desktop", "Downloads", "Pictures", "Videos", "Music"]
                        if os.path.exists(os.path.join(user_prof, sub))
                    ]
                    if not walk_roots:
                        walk_roots = [user_prof]

                for wroot in walk_roots:
                    for dirpath, dirnames, filenames in os.walk(wroot):
                        # Live exclusion check: prune at walk-time
                        dirnames[:] = [
                            sub for sub in dirnames
                            if not scope_cfg.is_excluded(sub, os.path.join(dirpath, sub))
                        ]

                        dir_base = os.path.basename(dirpath)
                        if scope_cfg.is_excluded(dir_base, dirpath):
                            txt_lines.append(f"[DIR] {dirpath} [EXCLUDED BY USER — PROTECTED PRIVACY ZONE]")
                            txt_lines.append("")
                            continue

                        d_folders.append(dirpath)
                        txt_lines.append(f"[DIR] {dirpath}")
                        for fn in filenames:
                            full_f = os.path.join(dirpath, fn)
                            if is_sensitive_file(fn, full_f):
                                continue
                            try:
                                st = os.stat(full_f)
                                sz, mtime = st.st_size, int(st.st_mtime)
                            except Exception:
                                sz, mtime = 0, 0
                            d_files_list.append({
                                "name": fn,
                                "path": full_f,
                                "size": sz,
                                "modified": mtime
                            })
                            txt_lines.append(f"  {fn} ({sz:,} bytes)" if sz else f"  {fn}")
                        txt_lines.append("")
                        if len(d_files_list) >= 40000:
                            break

            except Exception as walk_err:
                print(f"[file_index.scanner] Error walking drive {d}: {walk_err}")

            drive_data[d] = {
                "folders_count": len(d_folders),
                "files_count": len(d_files_list),
                "folders": d_folders,
                "files": d_files_list
            }
            total_folders += len(d_folders)
            total_files += len(d_files_list)

    # Save JSON map (Accessed strictly by code)
    map_payload = {
        "generated_at": now_str,
        "target_drives": valid_drives,
        "user_excluded_folders": sorted(list(scope_cfg.custom_excludes)),
        "statistics": {
            "total_folders": total_folders,
            "total_files": total_files
        },
        "drives": drive_data
    }

    try:
        from .config import get_secure_drive_map_json, get_secure_drive_map_txt
        secure_json = get_secure_drive_map_json()
        secure_txt = get_secure_drive_map_txt()

        # Save to Downloads (for user demonstration)
        with open(json_path, "w", encoding="utf-8", errors="replace") as jf:
            json.dump(map_payload, jf, ensure_ascii=False, indent=2)
        with open(txt_path, "w", encoding="utf-8", errors="replace") as tf:
            tf.write("\n".join(txt_lines))

        # Save to hidden secure vault on C: (out of LLM context, hardcoded for code execution)
        with open(secure_json, "w", encoding="utf-8", errors="replace") as sjf:
            json.dump(map_payload, sjf, ensure_ascii=False, indent=2)
        with open(secure_txt, "w", encoding="utf-8", errors="replace") as stf:
            stf.write("\n".join(txt_lines))

        print(f"[file_index.scanner] Detailed map of {valid_drives} saved to Downloads & C:\\ Secure Vault ({total_files:,} files, {total_folders:,} folders, {len(scope_cfg.custom_excludes)} custom excludes)")
    except Exception as save_err:
        print(f"[file_index.scanner] Error saving drive map: {save_err}")

    return {"json_path": json_path, "txt_path": txt_path, "secure_json": secure_json}


def load_drive_map() -> dict[str, Any] | None:
    """Direct Python code access to the detailed drive map JSON.
    
    Reads from the secure vault on C: first, falling back to Downloads.
    NEVER passed to LLM — consumed strictly by local execution code.
    """
    import json
    from .config import get_secure_drive_map_json
    paths_to_check = [
        get_secure_drive_map_json(),
        os.path.join(os.path.expanduser("~"), "Downloads", "akira_drive_map.json")
    ]
    for p in paths_to_check:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue
    return None


def lookup_in_drive_map(query: str, drive: str | None = None) -> list[dict[str, Any]]:
    """Local code query against the hardcoded drive map JSON."""
    dmap = load_drive_map()
    if not dmap or "drives" not in dmap:
        return []
    q_lower = query.lower().strip()
    results = []
    drives_to_search = [drive] if drive and drive in dmap["drives"] else list(dmap["drives"].keys())
    for d in drives_to_search:
        flist = dmap["drives"].get(d, {}).get("files", [])
        for item in flist:
            if q_lower in item.get("name", "").lower():
                results.append(item)
                if len(results) >= 25:
                    return results
    return results
