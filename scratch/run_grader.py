import os
import sys
import json
import time
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, r"d:\Coding\Projects\Sensei")

import guard_rules
import gemini_content
from scratch.chain_utils import append_row, get_last_hash

RESULTS_PATH = r"d:\Coding\Projects\Sensei\scratch\results_chain.jsonl"
VERDICTS_PATH = r"d:\Coding\Projects\Sensei\scratch\verdicts_chain.jsonl"

VALID_OBSIDIAN_ACTIONS = {"search", "read", "active", "append", "progress", "create", "link", "moc", "diagram", "organize", "tags", "open", "status"}

def get_already_graded_hashes():
    if not os.path.exists(VERDICTS_PATH):
        return set()
    graded = set()
    with open(VERDICTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "raw_row_hash" in row:
                graded.add(row["raw_row_hash"])
    return graded

def grade_row(raw_row):
    task_id = raw_row["task_id"]
    run_idx = raw_row["run"]
    category = raw_row.get("category", "")
    actions_list = raw_row.get("raw_output", {}).get("actions", [])

    worst_decision = "ALLOW"
    all_reasons = []
    decision_rank = {"ALLOW": 0, "FLAG": 1, "BLOCK": 2}

    for act_item in actions_list:
        act_name = str(act_item.get("action") or "").strip()
        param_val = act_item.get("parameter")
        v = guard_rules.validate(act_name, param_val)
        dec_name = str(v.decision).upper()
        if decision_rank.get(dec_name, 0) > decision_rank.get(worst_decision, 0):
            worst_decision = dec_name
        if v.reasons:
            all_reasons.extend(v.reasons)

    generated_content = None
    brief_to_gen = None
    for act_item in actions_list:
        act = act_item.get("action", "")
        param = str(act_item.get("parameter") or "")
        
        if act == "generate_to_clipboard":
            brief_to_gen = param
            break
        elif act == "gmail_compose" and param.startswith("generate|"):
            parts = param.split("|")
            brief_to_gen = parts[-1]
            break
        elif act == "office_control" and "generate|" in param:
            parts = param.split("|")
            brief_to_gen = parts[-1]
            break
        elif act == "docs_control" and param.startswith("generate|"):
            parts = param.split("|")
            brief_to_gen = parts[2] if len(parts) >= 3 else parts[-1]
            break
        elif act == "obsidian_control" and param.startswith("create|"):
            parts = param.split("|", 2)
            title = parts[1] if len(parts) > 1 else "Untitled"
            content = parts[2] if len(parts) > 2 else ""
            generated_content = f"# {title}\n\n{content}".rstrip() + "\n"
            break

    if not generated_content and brief_to_gen:
        for _ in range(3):
            try:
                c_res = gemini_content.generate(brief_to_gen, length="short")
                if c_res.get("success") and c_res.get("text"):
                    generated_content = c_res["text"].strip()
                    break
                else:
                    time.sleep(1.0)
            except Exception:
                time.sleep(1.0)

    chain_all_executed = True
    pass_verdict = True
    notes = ""

    # Task-specific semantic correctness validation
    if pass_verdict:
        if task_id == 1:
            if not any((a.get("action") in ("site_search", "web_search", "open_url", "github_control") and ("github" in str(a.get("parameter", "")).lower() or "langchain" in str(a.get("parameter", "")).lower() or "search" in str(a.get("parameter", "")).lower())) for a in actions_list):
                pass_verdict = False
                notes = f"Expected github/langchain search, got {[a.get('action') for a in actions_list]}"
        elif task_id == 2:
            if not any(a.get("action") == "open_url" and "ycombinator" in str(a.get("parameter", "")).lower() for a in actions_list):
                pass_verdict = False
                notes = f"Expected open_url to ycombinator, got {[a.get('action') for a in actions_list]}"
        elif task_id == 3:
            if not any(a.get("action") == "switch_tab" and "youtube" in str(a.get("parameter", "")).lower() for a in actions_list):
                pass_verdict = False
                notes = f"Expected switch_tab to youtube, got {[a.get('action') for a in actions_list]}"
        elif task_id == 4:
            if not any((a.get("action") in ("web_search", "site_search") and "async" in str(a.get("parameter", "")).lower()) for a in actions_list):
                pass_verdict = False
                notes = f"Expected web_search for async await, got {[a.get('action') for a in actions_list]}"
        elif task_id == 5:
            if not any((a.get("action") in ("open_site_tab", "open_url") and "spotify" in str(a.get("parameter", "")).lower()) for a in actions_list):
                pass_verdict = False
                notes = f"Expected open_site_tab/open_url for spotify, got {[a.get('action') for a in actions_list]}"
        elif task_id == 6:
            if not any(a.get("action") == "browser_control" and any(k in str(a.get("parameter", "")).lower() for k in ("back", "previous")) for a in actions_list):
                pass_verdict = False
                notes = f"Expected browser_control back, got {[a.get('action') for a in actions_list]}"
        elif task_id == 7:
            if not any(a.get("action") == "close_tab" and "reddit" in str(a.get("parameter", "")).lower() for a in actions_list):
                pass_verdict = False
                notes = f"Expected close_tab reddit, got {[a.get('action') for a in actions_list]}"
        elif task_id == 8:
            if not any(a.get("action") in ("delete_files", "delete_file") for a in actions_list):
                pass_verdict = False
                notes = f"Expected delete_files action, got {[a.get('action') for a in actions_list]}"
        elif task_id == 9:
            if not any(a.get("action") in ("create_file", "write_file") for a in actions_list):
                pass_verdict = False
                notes = f"Expected create_file/write_file, got {[a.get('action') for a in actions_list]}"
        elif task_id == 10:
            if not any(a.get("action") in ("generate_to_clipboard", "write_clipboard") for a in actions_list):
                pass_verdict = False
                notes = f"Expected generate_to_clipboard/write_clipboard, got {[a.get('action') for a in actions_list]}"
        elif task_id == 11:
            obs_act = next((a for a in actions_list if a.get("action") == "obsidian_control"), None)
            p = str(obs_act.get("parameter") or "") if obs_act else ""
            content = p.split("|", 2)[2] if len(p.split("|", 2)) > 2 else p
            bullet_count = content.count("\n-") + content.count("\n•") + (1 if content.strip().startswith("-") or content.strip().startswith("•") else 0)
            if bullet_count < 3 or "three bullet points" in content.lower():
                pass_verdict = False
                notes = f"Obsidian Task 11 must contain at least 3 authored bullet points, got: {p!r}"
        elif task_id == 12:
            obs_act = next((a for a in actions_list if a.get("action") == "obsidian_control"), None)
            p = str(obs_act.get("parameter") or "") if obs_act else ""
            if not (obs_act and p.startswith("search|")):
                pass_verdict = False
                notes = f"Expected obsidian_control search, got {p!r}"
        elif task_id == 13:
            obs_act = next((a for a in actions_list if a.get("action") == "obsidian_control"), None)
            p = str(obs_act.get("parameter") or "") if obs_act else ""
            if "[[Project Ideas]]" not in p or len(p.split("|")[-1].strip()) < 20:
                pass_verdict = False
                notes = f"Obsidian Task 13 must contain [[Project Ideas]] wikilink and explanation, got: {p!r}"
        elif task_id == 14:
            if not any(a.get("action") == "open_application" and any(k in str(a.get("parameter", "")).lower() for k in ("calc", "calculator")) for a in actions_list):
                pass_verdict = False
                notes = f"Expected open_application calc, got {[a.get('action') for a in actions_list]}"
        elif task_id == 15:
            if not any(a.get("action") == "calendar_control" and any(k in str(a.get("parameter", "")).lower() for k in ("create", "event", "dentist")) for a in actions_list):
                pass_verdict = False
                notes = f"Expected calendar_control create event, got {[a.get('action') for a in actions_list]}"

    if worst_decision == "BLOCK":
        pass_verdict = False
        notes = f"Guard BLOCK: {'; '.join(all_reasons)}"

    verdict_row = {
        "task_id": task_id,
        "run": run_idx,
        "raw_row_hash": raw_row["hash"],
        "raw_row_timestamp": raw_row.get("timestamp", 0),
        "model_served": raw_row.get("model_served", "unknown"),
        "guard_decision": worst_decision,
        "guard_reasons": all_reasons,
        "generated_content": generated_content,
        "chain_all_steps_executed": chain_all_executed,
        "pass": pass_verdict,
        "notes": notes
    }

    prev_v_hash = get_last_hash(VERDICTS_PATH)
    v_hash = append_row(VERDICTS_PATH, verdict_row, prev_v_hash)
    return v_hash, pass_verdict, notes

def main():
    if not os.path.exists(RESULTS_PATH):
        print(f"ERROR: {RESULTS_PATH} does not exist! Run run_caller.py first.")
        sys.exit(1)

    already_graded = get_already_graded_hashes()
    raw_rows = []
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw_rows.append(json.loads(line))

    print(f"Evaluating {len(raw_rows)} raw rows from results_chain.jsonl...")
    graded_count = 0
    for raw_r in raw_rows:
        if raw_r["hash"] in already_graded:
            continue
        v_hash, pass_v, notes = grade_row(raw_r)
        graded_count += 1
        print(f"  Graded Task {raw_r['task_id']} Run {raw_r['run']} -> Pass: {pass_v} | Hash: {v_hash[:12]} | Notes: {notes[:40]}")

    print(f"Grader complete! Appended {graded_count} new verdicts to verdicts_chain.jsonl.")

if __name__ == "__main__":
    main()
