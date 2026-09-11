import os
import json
import time
import hashlib

def get_last_hash(path):
    if not os.path.exists(path):
        return "0" * 64
    last_hash = "0" * 64
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "hash" in row:
                last_hash = row["hash"]
    return last_hash

def append_row(path, row, prev_hash=None):
    if prev_hash is None:
        prev_hash = get_last_hash(path)
    row = dict(row)
    row["prev_hash"] = prev_hash
    row["timestamp"] = time.time()
    payload = json.dumps({k: v for k, v in row.items()}, sort_keys=True).encode()
    row["hash"] = hashlib.sha256(prev_hash.encode() + payload).hexdigest()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row["hash"]

def verify_chain(path):
    prev = "0" * 64
    count = 0
    if not os.path.exists(path):
        return False, 0, None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            h = row.pop("hash", None)
            if h is None:
                return False, count, row
            expected_payload = json.dumps({k: v for k, v in row.items()}, sort_keys=True).encode()
            expected = hashlib.sha256(prev.encode() + expected_payload).hexdigest()
            if h != expected:
                return False, count, row
            prev = h
            count += 1
    return True, count, None
