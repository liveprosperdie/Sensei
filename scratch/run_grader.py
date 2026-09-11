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

    if category == "chain":
        if task_id in (1, 2):
            chain_all_executed = False
            pass_verdict = False
            notes = "FAIL: window_typing is not implemented; text routed to generate_to_clipboard instead of typing into Notepad. Notepad was opened blank."
        elif task_id == 3:
            has_obsidian = any(a.get("action") == "obsidian_control" for a in actions_list)
            has_email = any(a.get("action") == "gmail_compose" for a in actions_list)
            chain_all_executed = (len(actions_list) >= 2 and has_obsidian and has_email)
            if not chain_all_executed:
                pass_verdict = False
                notes = f"Chain incomplete: expected obsidian + email, got {len(actions_list)} steps"
        elif task_id == 4:
            has_word = any("word" in str(a.get("parameter", "")).lower() or a.get("action") == "office_control" for a in actions_list)
            has_clip = any(a.get("action") in ("generate_to_clipboard", "write_clipboard") for a in actions_list)
            chain_all_executed = (len(actions_list) >= 2 and has_word and has_clip)
            if not chain_all_executed:
                pass_verdict = False
                notes = f"Chain incomplete: expected word + clipboard, got {len(actions_list)} steps"
        elif task_id == 5:
            has_close_spot = any(a.get("action") == "close_application" and "spotify" in str(a.get("parameter", "")).lower() for a in actions_list)
            has_chrome = any("chrome" in str(a.get("parameter", "")).lower() for a in actions_list)
            has_netflix = any("netflix" in a.get("action", "") or "netflix" in str(a.get("parameter", "")).lower() for a in actions_list)
            chain_all_executed = (len(actions_list) >= 3 and has_close_spot and has_chrome and has_netflix)
            if not chain_all_executed:
                pass_verdict = False
                notes = f"Chain incomplete: expected close spotify + chrome + netflix, got {len(actions_list)} steps"

    if task_id in (6, 7, 9, 10):
        for a in actions_list:
            if a.get("action") == "gmail_compose":
                p = str(a.get("parameter") or "")
                if p.startswith("draft|") and any(phrase in p for phrase in ("about the budget meeting", "announcing the product launch date", "requesting time off next week")):
                    pass_verdict = False
                    notes = "Literal echo detected in draft parameter"

    for a in actions_list:
        if a.get("action") == "obsidian_control":
            sub_act = str(a.get("parameter", "")).split("|")[0].strip().lower()
            if sub_act not in VALID_OBSIDIAN_ACTIONS:
                pass_verdict = False
                notes = f"Invalid obsidian_control sub-action: {sub_act!r} is not supported by obsidian_control"

    if pass_verdict:
        if task_id == 11:
            obs_act = next((a for a in actions_list if a.get("action") == "obsidian_control"), None)
            p = str(obs_act.get("parameter") or "") if obs_act else ""
            content = p.split("|", 2)[2] if len(p.split("|", 2)) > 2 else p
            bullet_count = content.count("\n-") + content.count("\n•") + (1 if content.strip().startswith("-") or content.strip().startswith("•") else 0)
            if bullet_count < 3 or "three bullet points" in content.lower():
                pass_verdict = False
                notes = f"Obsidian Task 11 must contain at least 3 authored bullet points, got: {p!r}"
        elif task_id == 13:
            obs_act = next((a for a in actions_list if a.get("action") == "obsidian_control"), None)
            p = str(obs_act.get("parameter") or "") if obs_act else ""
            if "[[Project Ideas]]" not in p or len(p.split("|")[-1].strip()) < 30:
                pass_verdict = False
                notes = f"Obsidian Task 13 must contain [[Project Ideas]] wikilink and explanation, got: {p!r}"
        elif task_id == 15:
            obs_act = next((a for a in actions_list if a.get("action") == "obsidian_control"), None)
            p = str(obs_act.get("parameter") or "") if obs_act else ""
            if "|" not in p or "---" not in p:
                pass_verdict = False
                notes = f"Obsidian Task 15 must author an actual markdown table, got: {p!r}"
        elif task_id == 16:
            if not any(a.get("action") == "netflix_control" and "the office" in str(a.get("parameter", "")).lower() for a in actions_list):
                pass_verdict = False
                notes = f"Expected netflix_control search, got {[a.get('action') for a in actions_list]}"
        elif task_id == 17:
            if not any(("youtube" in str(a.get("parameter", "")).lower() or a.get("action") == "youtube_control") for a in actions_list):
                pass_verdict = False
                notes = f"Expected youtube search, got {[a.get('action') for a in actions_list]}"
        elif task_id == 18:
            obs_act = next((a for a in actions_list if a.get("action") == "obsidian_control"), None)
            p = str(obs_act.get("parameter") or "") if obs_act else ""
            if "stoicism" in p.lower() and len(p.split("|")[-1].strip()) < 20:
                pass_verdict = False
                notes = "Task 18 stoicism note is too brief or echo"
        elif task_id == 19:
            if not any(a.get("action") == "office_control" and "word" in str(a.get("parameter", "")).lower() for a in actions_list):
                pass_verdict = False
                notes = f"Expected office_control word, got {[a.get('action') for a in actions_list]}"
        elif task_id == 20:
            if any(a.get("action") == "close_application" for a in actions_list):
                pass_verdict = False
                notes = "Misrouted to close_application instead of open spotify"
            elif not any("spotify" in str(a.get("parameter", "")).lower() for a in actions_list):
                pass_verdict = False
                notes = f"Expected spotify open, got {[a.get('action') for a in actions_list]}"

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
