"""procedural_memory/store.py — Encrypted cache store with in-memory index.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet

from .config import (
    EXPIRY_DAYS,
    MAX_STORE_ENTRIES,
    SUCCESS_THRESHOLD,
    get_db_path,
    get_key_path,
)
from .crypto import get_or_create_cipher
from .schema import StoredProcedure, compute_plan_hash, normalize_trigger

logger = logging.getLogger("akira.procedural_memory.store")


class ProceduralStore:
    """Encrypted local procedural memory store.
    
    Treats disk file as a cache: falls open gracefully to empty store on any decryption/parse error.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        key_path: Optional[str] = None,
        cipher: Optional[Fernet] = None,
    ):
        self.db_path = db_path or get_db_path()
        self.key_path = key_path or get_key_path()
        self._cipher = cipher
        self._by_id: Dict[str, StoredProcedure] = {}
        self._by_norm_trigger: Dict[str, StoredProcedure] = {}
        self._learning_enabled: bool = True
        self.load()

    def _get_cipher(self) -> Fernet:
        if self._cipher is None:
            self._cipher = get_or_create_cipher(self.key_path)
        return self._cipher

    @property
    def learning_enabled(self) -> bool:
        return self._learning_enabled

    @learning_enabled.setter
    def learning_enabled(self, enabled: bool) -> None:
        self._learning_enabled = bool(enabled)
        try:
            self.save()
        except Exception as e:
            logger.warning("[store] Failed to save learning flag: %s", e)

    def load(self) -> None:
        """Load and decrypt the store. If corrupted or missing, start fresh."""
        self._by_id.clear()
        self._by_norm_trigger.clear()

        if not os.path.exists(self.db_path):
            return

        try:
            with open(self.db_path, "rb") as f:
                encrypted_blob = f.read()

            if not encrypted_blob:
                return

            cipher = self._get_cipher()
            decrypted_bytes = cipher.decrypt(encrypted_blob)
            data = json.loads(decrypted_bytes.decode("utf-8"))

            self._learning_enabled = bool(data.get("learning_enabled", True))
            procedures_list = data.get("procedures", [])

            now = time.time()
            expiry_seconds = EXPIRY_DAYS * 86400

            for item in procedures_list:
                try:
                    proc = StoredProcedure.from_dict(item)
                    # Purge stale procedures unused for > EXPIRY_DAYS
                    if (now - proc.last_used_at) > expiry_seconds:
                        continue
                    self._by_id[proc.id] = proc
                    self._by_norm_trigger[proc.normalized_trigger] = proc
                except Exception as item_err:
                    logger.warning("[store] Skipping malformed procedure entry: %s", item_err)

        except Exception as e:
            # Fall open to Tier 2: rename corrupted store aside and start with empty cache
            logger.warning("[store] Could not decrypt/load %s: %s — rotating aside", self.db_path, e)
            try:
                corrupt_path = f"{self.db_path}.corrupted.{int(time.time())}"
                if os.path.exists(self.db_path):
                    os.rename(self.db_path, corrupt_path)
                    logger.info("[store] Corrupted store moved to %s", corrupt_path)
            except Exception as rename_err:
                logger.error("[store] Failed to rename corrupted store: %s", rename_err)

            self._by_id.clear()
            self._by_norm_trigger.clear()

    def save(self) -> None:
        """Serialize, encrypt, and atomically write store to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        # Enforce LRU cap if exceeded
        if len(self._by_id) > MAX_STORE_ENTRIES:
            sorted_procs = sorted(self._by_id.values(), key=lambda p: p.last_used_at)
            excess = len(self._by_id) - MAX_STORE_ENTRIES
            for p in sorted_procs[:excess]:
                self.delete(p.id)

        data = {
            "version": 1,
            "updated_at": time.time(),
            "learning_enabled": self._learning_enabled,
            "procedures": [p.to_dict() for p in self._by_id.values()],
        }

        try:
            payload = json.dumps(data, indent=2).encode("utf-8")
            cipher = self._get_cipher()
            encrypted = cipher.encrypt(payload)

            tmp_path = f"{self.db_path}.tmp"
            with open(tmp_path, "wb") as f:
                f.write(encrypted)
            os.replace(tmp_path, self.db_path)
        except Exception as e:
            logger.error("[store] Failed to save encrypted store: %s", e)
            raise

    def find_by_id(self, plan_id: str) -> Optional[StoredProcedure]:
        return self._by_id.get(plan_id)

    def find_by_normalized_trigger(self, norm_trigger: str) -> Optional[StoredProcedure]:
        return self._by_norm_trigger.get(norm_trigger)

    def upsert(self, procedure: StoredProcedure) -> None:
        """Insert or update procedure in-memory and persist atomically."""
        self._by_id[procedure.id] = procedure
        self._by_norm_trigger[procedure.normalized_trigger] = procedure
        self.save()

    def delete(self, plan_id: str) -> bool:
        proc = self._by_id.pop(plan_id, None)
        if proc:
            self._by_norm_trigger.pop(proc.normalized_trigger, None)
            try:
                self.save()
            except Exception:
                pass
            return True
        return False

    def clear_all(self) -> None:
        """Wipe all procedures (used for Confirmation-Gated clear all and wipe_all_memory)."""
        self._by_id.clear()
        self._by_norm_trigger.clear()
        try:
            self.save()
        except Exception:
            pass

    def count(self) -> int:
        return len(self._by_id)

    def record_derivation(self, procedure: StoredProcedure) -> StoredProcedure:
        """Update procedure on fresh Tier-2 derivation.
        
        Q1 Rule:
        - If existing procedure has identical plan hash, increment success_count.
        - If new derivation differs, replace stored plan and reset count to 1!
        """
        existing = self.find_by_normalized_trigger(procedure.normalized_trigger)
        if existing is None:
            procedure.success_count = 1
            procedure.failure_count = 0
            procedure.last_used_at = time.time()
            self.upsert(procedure)
            return procedure

        if existing.plan_hash == procedure.plan_hash:
            existing.success_count += 1
            existing.last_used_at = time.time()
            existing.origin_brain = procedure.origin_brain
            self.upsert(existing)
            return existing
        else:
            # Divergence: replace stored plan and reset count to 1
            procedure.success_count = 1
            procedure.failure_count = 0
            procedure.last_used_at = time.time()
            self.delete(existing.id)
            self.upsert(procedure)
            return procedure

    def record_correction(self, plan_id: str) -> bool:
        """Count user correction as a failure. Demote or purge procedure."""
        proc = self.find_by_id(plan_id)
        if not proc:
            return False
        proc.failure_count += 1
        proc.success_count = max(0, proc.success_count - 1)
        if proc.failure_count >= 2 or proc.success_count <= 0:
            logger.info("[store] Purging procedure %s due to correction/failure", plan_id)
            self.delete(plan_id)
        else:
            self.upsert(proc)
        return True

    def purge_by_path(self, target_path: str) -> int:
        """Purge any stored procedure referencing target_path (normalized)."""
        if not target_path:
            return 0
        norm_target = os.path.normcase(os.path.realpath(target_path))
        purged = 0
        to_delete = []

        for p in self._by_id.values():
            touches_path = False
            for step in p.actions:
                param = str(step.get("parameter") or "")
                parts = param.split("|")
                for part in parts:
                    clean_p = part.strip().strip("'\"")
                    if (":\\" in clean_p) or (":/" in clean_p):
                        try:
                            norm_p = os.path.normcase(os.path.realpath(clean_p))
                            if norm_p == norm_target or norm_p.startswith(norm_target + os.sep):
                                touches_path = True
                                break
                        except Exception:
                            pass
                if touches_path:
                    break
            if touches_path:
                to_delete.append(p.id)

        for pid in to_delete:
            self.delete(pid)
            purged += 1

        return purged
