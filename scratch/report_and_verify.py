import os
import sys
import json

sys.path.insert(0, r"d:\Coding\Projects\Sensei")

RESULTS_PATH = r"d:\Coding\Projects\Sensei\scratch\results_chain.jsonl"
VERDICTS_PATH = r"d:\Coding\Projects\Sensei\scratch\verdicts_chain.jsonl"

from scratch.chain_utils import verify_chain

def compute_latest_tally():
    if not os.path.exists(VERDICTS_PATH):
        print("verdicts_chain.jsonl does not exist.")
        return 0, 0, 0.0

    verdicts_by_key = {}
    with open(VERDICTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            key = (row["task_id"], row["run"])
            verdicts_by_key[key] = row

    total = len(verdicts_by_key)
    passes = sum(1 for r in verdicts_by_key.values() if r.get("pass"))
    pct = (passes / total * 100.0) if total > 0 else 0.0
    return passes, total, pct, verdicts_by_key

def main():
    print("--- CHAIN VERIFICATION RESULTS ---")
    res_v = verify_chain(RESULTS_PATH)
    print(f"results_chain verification: {res_v}")

    ver_v = verify_chain(VERDICTS_PATH)
    print(f"verdicts_chain verification: {ver_v}")

    print("\n--- PROGRAMMATIC BENCHMARK SCORE TALLY ---")
    passes, total, pct, verdicts_by_key = compute_latest_tally()
    print(f"Latest verdicts per (task_id, run): {passes}/{total} passed ({pct:.1f}%)")

    print("\nFailing runs summary:")
    for (tid, ridx), r in sorted(verdicts_by_key.items()):
        if not r.get("pass"):
            print(f"  Task {tid} Run {ridx} -> Pass: False | Notes: {r.get('notes')}")

if __name__ == "__main__":
    main()
