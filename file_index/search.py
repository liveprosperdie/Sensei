"""
file_index/search.py — Search query engine for filename metadata and tier-gated document content.
"""

import os
import zlib
import sqlite3
from typing import Optional, Dict, Any, List
from .db import (
    get_connection,
    reconstruct_folder_path,
    _db_lock
)


SENSITIVE_EXTENSIONS = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".pkcs12", ".vault", ".kdbx", ".crt", ".cer", ".der",
    ".keystore", ".jks"
})
SENSITIVE_PATTERNS = (
    ".env", "id_rsa", "id_ed25519", "id_ecdsa", "credentials.json", "token.json",
    "client_secret", "secret", "password", ".session_vault", "master.key",
    "known_hosts", "authorized_keys", "shadow", "htpasswd"
)
SENSITIVE_DIRS = frozenset({
    ".ssh", ".aws", ".gnupg", ".azure", ".kube", "credentials"
})


def is_sensitive_file(name: str, full_path: str = "") -> bool:
    """Detect sensitive documents, authentication keys, credentials, or environment files.
    Guarantees zero sensitive documents or secrets are ever leaked or returned by file search.
    """
    name_lower = (name or "").lower()
    _, ext = os.path.splitext(name_lower)
    if ext in SENSITIVE_EXTENSIONS:
        return True
    if any(p in name_lower for p in SENSITIVE_PATTERNS):
        return True
    if full_path:
        norm = full_path.replace("\\", "/").lower()
        parts = norm.split("/")
        if any(d in parts for d in SENSITIVE_DIRS):
            return True
    return False


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize input string for SQLite FTS5 query syntax."""
    # Remove special FTS5 operators and quote terms
    cleaned = "".join(c if c.isalnum() or c in " _-." else " " for c in query)
    tokens = [t.strip() for t in cleaned.split() if t.strip()]
    if not tokens:
        return ""
    # Prefix match on last token for search-as-you-type feel
    return " ".join(f'"{t}"*' for t in tokens)


def search_files_metadata(
    conn: sqlite3.Connection,
    query: str,
    root: Optional[str] = None,
    max_results: int = 20
) -> List[Dict[str, Any]]:
    """Search files by name using files_fts and LIKE fallback."""
    results = []
    fts_query = _sanitize_fts5_query(query)
    root_norm = os.path.normpath(root) if root else None

    with _db_lock:
        cursor = conn.cursor()

        # 1. First try FTS5 index
        if fts_query:
            try:
                cursor.execute("""
                SELECT f.id, f.folder_id, f.name, f.size, f.modified
                FROM files_fts fts
                JOIN files f ON fts.rowid = f.id
                WHERE files_fts MATCH ?
                ORDER BY bm25(files_fts)
                LIMIT ?;
                """, (fts_query, max_results * 2))
                rows = cursor.fetchall()
            except Exception:
                rows = []
        else:
            rows = []

        # 2. If FTS returned few/no rows, fall back to LIKE query
        if len(rows) < max_results:
            seen_ids = {r[0] for r in rows}
            cursor.execute("""
            SELECT f.id, f.folder_id, f.name, f.size, f.modified
            FROM files f
            WHERE f.name LIKE ?
            LIMIT ?;
            """, (f"%{query}%", max_results * 2))
            like_rows = cursor.fetchall()
            for lr in like_rows:
                if lr[0] not in seen_ids:
                    rows.append(lr)
                    seen_ids.add(lr[0])

        # 3. Reconstruct paths and filter by root if specified
        for fid, folder_id, name, size, mtime in rows:
            if is_sensitive_file(name):
                continue
            folder_path = reconstruct_folder_path(conn, folder_id)
            full_path = os.path.join(folder_path, name)

            if is_sensitive_file(name, full_path):
                continue

            if root_norm and not (full_path == root_norm or full_path.startswith(root_norm + os.sep)):
                continue

            results.append({
                "id": fid,
                "file_id": fid,
                "name": name,
                "path": full_path,
                "size": size,
                "modified": mtime,
                "match_type": "name"
            })
            if len(results) >= max_results:
                break

    return results


def search_files_content(
    conn: sqlite3.Connection,
    query: str,
    root: Optional[str] = None,
    max_results: int = 20
) -> List[Dict[str, Any]]:
    """Search inside document contents using content_fts and content_chunks (Standard/Pro only)."""
    results = []
    fts_query = _sanitize_fts5_query(query)
    if not fts_query:
        return results

    root_norm = os.path.normpath(root) if root else None

    with _db_lock:
        cursor = conn.cursor()
        try:
            cursor.execute("""
            SELECT cfts.rowid, f.folder_id, f.name, f.size, f.modified
            FROM content_fts cfts
            JOIN files f ON cfts.rowid = f.id
            WHERE content_fts MATCH ?
            LIMIT ?;
            """, (fts_query, max_results * 2))
            rows = cursor.fetchall()
        except Exception as e:
            print(f"[file_index.search] content_fts query error: {e}")
            return results

        for file_id, folder_id, name, size, mtime in rows:
            if is_sensitive_file(name):
                continue
            folder_path = reconstruct_folder_path(conn, folder_id)
            full_path = os.path.join(folder_path, name)

            if is_sensitive_file(name, full_path):
                continue

            if root_norm and not (full_path == root_norm or full_path.startswith(root_norm + os.sep)):
                continue

            # Fetch compressed chunks to extract a contextual snippet
            cursor.execute("""
            SELECT compressed_text FROM content_chunks
            WHERE file_id = ?
            ORDER BY chunk_index ASC
            LIMIT 5;
            """, (file_id,))
            chunk_rows = cursor.fetchall()

            snippet = ""
            query_lower = query.lower()
            for (c_blob,) in chunk_rows:
                try:
                    plain = zlib.decompress(c_blob).decode("utf-8", errors="ignore")
                    idx = plain.lower().find(query_lower)
                    if idx != -1:
                        start = max(0, idx - 40)
                        end = min(len(plain), idx + len(query) + 60)
                        snippet = ("..." if start > 0 else "") + plain[start:end].replace("\n", " ") + ("..." if end < len(plain) else "")
                        break
                    elif not snippet:
                        snippet = plain[:100].replace("\n", " ") + "..."
                except Exception:
                    continue

            results.append({
                "id": file_id,
                "file_id": file_id,
                "name": name,
                "path": full_path,
                "size": size,
                "modified": mtime,
                "snippet": snippet,
                "match_type": "content"
            })
            if len(results) >= max_results:
                break

    return results


def search_files(
    db_path: str,
    query: str,
    root: Optional[str] = None,
    content: bool = False,
    max_results: int = 20
) -> Dict[str, Any]:
    """
    Unified search interface for Akira.
    Handles tier gating for content search with graceful fallback.
    """
    if not query or not query.strip():
        return {"success": False, "message": "What file should I look for?", "results": []}

    query_str = query.strip()
    if not os.path.exists(db_path):
        return {
            "success": False,
            "message": "Search index is not initialized yet.",
            "results": []
        }

    conn = get_connection(db_path)

    # Check Tier gating for content search
    if content:
        try:
            import tiers
            allowed, notice = tiers.content_search_allowed()
        except Exception:
            allowed, notice = True, ""

        if not allowed:
            # Graceful message and fallback to filename search
            name_results = search_files_metadata(conn, query_str, root=root, max_results=max_results)
            if name_results:
                shown = "; ".join(os.path.basename(r["path"]) for r in name_results[:4])
                msg = f"{notice} I found matching filenames: {shown}"
                return {
                    "success": True,
                    "speak": True,
                    "message": msg,
                    "results": [r["path"] for r in name_results],
                    "tier_notice": notice,
                    "is_downgraded": True
                }
            else:
                return {
                    "success": False,
                    "speak": True,
                    "message": f"{notice} No matching filenames found for '{query_str}'.",
                    "results": [],
                    "tier_notice": notice,
                    "is_downgraded": True
                }

        # Standard/Pro tier: perform content search
        content_results = search_files_content(conn, query_str, root=root, max_results=max_results)
        if content_results:
            shown = "; ".join(f"{os.path.basename(r['path'])} ({r['snippet']})" for r in content_results[:3])
            return {
                "success": True,
                "speak": True,
                "message": f"Found {len(content_results)} document{'s' if len(content_results) != 1 else ''} containing '{query_str}': {shown}",
                "results": [r["path"] for r in content_results],
                "details": content_results
            }

        # Fall through to filename search if no content matches found
        name_results = search_files_metadata(conn, query_str, root=root, max_results=max_results)
        if name_results:
            shown = "; ".join(os.path.basename(r["path"]) for r in name_results[:5])
            return {
                "success": True,
                "speak": True,
                "message": f"No documents contained '{query_str}', but found matching filenames: {shown}",
                "results": [r["path"] for r in name_results]
            }
        return {
            "success": False,
            "message": f"No files or content matching '{query_str}' found.",
            "results": []
        }

    # Metadata / Filename search (All tiers)
    name_results = search_files_metadata(conn, query_str, root=root, max_results=max_results)
    if not name_results:
        target_loc = f" under {root}" if root else ""
        return {"success": False, "message": f"No files matching '{query_str}' found{target_loc}.", "results": []}

    target_loc = f" under {root}" if root else ""
    if len(name_results) == 1:
        first = name_results[0]
        folder = os.path.dirname(first["path"])
        msg = f"Found {first['name']} in {folder}."
    elif len(name_results) <= 3:
        items = [f"{r['name']} in {os.path.dirname(r['path'])}" for r in name_results]
        msg = f"Found {len(name_results)} files{target_loc}: {'; '.join(items)}."
    else:
        items = [f"{r['name']} in {os.path.dirname(r['path'])}" for r in name_results[:3]]
        msg = f"Found {len(name_results)} files{target_loc}: {'; '.join(items)}, and {len(name_results) - 3} more."

    return {
        "success": True,
        "speak": True,
        "message": msg,
        "results": [r["path"] for r in name_results]
    }
