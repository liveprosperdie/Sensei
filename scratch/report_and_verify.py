import os
import sys
import json

sys.path.insert(0, r"d:\Coding\Projects\Sensei")

RESULTS_PATH = r"d:\Coding\Projects\Sensei\scratch\results_chain.jsonl"
VERDICTS_PATH = r"d:\Coding\Projects\Sensei\scratch\verdicts_chain.jsonl"

from scratch.chain_utils import verify_chain

def load_rows(path):
    rows = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line.strip()))
    return rows

def main():
    print("================================================================================")
    print("PART 4 — HASH-CHAIN VERIFICATION & 15-TASK (30-RUN) PRE-TEST TALLY")
    print("================================================================================")
    
    res_ok, res_count, res_err = verify_chain(RESULTS_PATH)
    print(f"\n1. results_chain.jsonl: Valid={res_ok} | Rows={res_count} | Error={res_err}")

    ver_ok, ver_count, ver_err = verify_chain(VERDICTS_PATH)
    print(f"2. verdicts_chain.jsonl: Valid={ver_ok} | Rows={ver_count} | Error={ver_err}")

    results = load_rows(RESULTS_PATH)
    verdicts = load_rows(VERDICTS_PATH)

    # Current test pass is the last 30 rows (tasks 1-15, runs 1-2)
    audit_results = results[-30:] if len(results) >= 30 else results
    audit_verdicts = verdicts[-30:] if len(verdicts) >= 30 else verdicts

    print("\n--- 15-TASK (30-RUN) TEST PASS DETAILS ---")
    print(f"{'Task':<5} | {'Run':<4} | {'Model':<20} | {'Action':<22} | {'Guard':<6} | {'Pass':<5} | {'Notes'}")
    print("-" * 95)

    passes = 0
    total = len(audit_verdicts)

    for i, (r_row, v_row) in enumerate(zip(audit_results, audit_verdicts)):
        tid = r_row.get("task_id")
        run_idx = r_row.get("run")
        model = r_row.get("model_served", "unknown")
        actions = r_row.get("raw_output", {}).get("actions", [])
        act_str = actions[0].get("action", "none") if actions else "none"
        if len(actions) > 1:
            act_str += f" (+{len(actions)-1})"
        
        guard_dec = v_row.get("guard_decision", "ALLOW")
        is_pass = v_row.get("pass", False)
        if is_pass:
            passes += 1
        notes = v_row.get("notes", "")

        print(f"{tid:<5} | {run_idx:<4} | {model:<20} | {act_str:<22} | {guard_dec:<6} | {str(is_pass):<5} | {notes[:30]}")

    pct = (passes / total * 100.0) if total > 0 else 0.0
    print("-" * 95)
    print(f"TOTAL PRE-TEST AUDIT PASS SCORE: {passes}/{total} passed ({pct:.1f}%)")
    print("================================================================================")

if __name__ == "__main__":
    main()
