import os
import sys
import json
import time
import re
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, r"d:\Coding\Projects\Sensei")

import gemini_head
import guard_rules
import gemini_content

groq_key = os.environ.get("GROQ_API_KEY", "")
paths = [
    r"d:\Coding\Projects\Sensei\scratch\fallback_api_test_results.json",
    r"C:\Users\shrey pathak\.gemini\antigravity-ide\brain\4dd71589-e988-400e-8a2e-6893daf1fdc9\scratch\fallback_api_test_results.json"
]

with open(paths[0], "r", encoding="utf-8") as f:
    rows = json.load(f)

tasks_dict = {
    11: "Create a note in obsidian titled 'Project Ideas' and write three bullet points of ideas about a mobile app",
    14: "Search my obsidian vault for notes about 'budget' and summarize what you find",
    17: "look up python tutorials on youtube",
    19: "open word and write a report about quantum computing",
    20: "stop, open spotify instead"
}

VALID_OBSIDIAN_ACTIONS = {"search", "read", "active", "append", "progress", "create", "link", "moc", "diagram", "organize", "tags", "open", "status"}

for r in rows:
    tid = r["task_id"]
    run_idx = r["run"]
    
    # Re-run if rate limited (empty actions or rate-limit fail)
    if tid in tasks_dict and (not r["raw_output"]["actions"] or "got []" in r["notes"]):
        prompt = tasks_dict[tid]
        print(f"Re-querying Task {tid} Run {run_idx} against live Groq pool...")
        time.sleep(3.5)
        
        reply = None
        for att in range(5):
            reply = gemini_head._route_via_groq(groq_key, [{"role": "user", "content": prompt}], [], session_id=f"task_{tid}_{run_idx}")
            if reply and reply.text and "rate-limited" not in reply.text and "busy" not in reply.text:
                break
            time.sleep(4.0)

        raw_dict = {}
        raw_text = reply.text if reply else "{}"
        try:
            raw_dict = json.loads(raw_text)
        except Exception:
            raw_dict = {}

        actions_list = raw_dict.get("actions", [])
        if not actions_list and "action" in raw_dict and raw_dict["action"]:
            actions_list = [{"action": raw_dict["action"], "parameter": raw_dict.get("parameter", "")}]

        model_name = getattr(reply, "model", "unknown")

        worst_decision = "ALLOW"
        all_reasons = []
        for act_item in actions_list:
            v = guard_rules.validate(act_item.get("action", ""), act_item.get("parameter"))
            if str(v.decision).upper() == "BLOCK":
                worst_decision = "BLOCK"
            if v.reasons:
                all_reasons.extend(v.reasons)

        r["model_served"] = model_name
        r["raw_output"]["actions"] = actions_list
        r["guard_decision"] = worst_decision
        r["guard_reasons"] = all_reasons

        if tid == 11 and actions_list:
            p = str(actions_list[0].get("parameter", ""))
            parts = p.split("|", 2)
            title = parts[1] if len(parts) > 1 else "Untitled"
            content = parts[2] if len(parts) > 2 else ""
            r["generated_content"] = f"# {title}\n\n{content}".rstrip() + "\n"
        elif tid == 19 and actions_list:
            c_res = gemini_content.generate("one-paragraph report on quantum computing", length="short")
            r["generated_content"] = c_res.get("text", "").strip() if c_res.get("success") else None

        pass_verdict = True
        notes = ""
        if worst_decision == "BLOCK":
            pass_verdict = False
            notes = f"Guard BLOCK: {'; '.join(all_reasons)}"

        for a in actions_list:
            if a.get("action") == "obsidian_control":
                sub_act = str(a.get("parameter", "")).split("|")[0].strip().lower()
                if sub_act not in VALID_OBSIDIAN_ACTIONS:
                    pass_verdict = False
                    notes = f"Invalid obsidian_control sub-action: {sub_act!r} is not supported by obsidian_control"

        if pass_verdict and tid == 11:
            p = str(actions_list[0].get("parameter", "")) if actions_list else ""
            content = p.split("|", 2)[2] if len(p.split("|", 2)) > 2 else p
            bullet_count = content.count("\n-") + content.count("\n•") + (1 if content.strip().startswith("-") or content.strip().startswith("•") else 0)
            if bullet_count < 3 or "three bullet points" in content.lower():
                pass_verdict = False
                notes = f"Obsidian Task 11 must contain at least 3 authored bullet points, got: {p!r}"

        if pass_verdict and tid == 17:
            if not any(("youtube" in str(a.get("parameter", "")).lower() or a.get("action") == "youtube_control") for a in actions_list):
                pass_verdict = False
                notes = f"Expected youtube search, got {[a.get('action') for a in actions_list]}"
        elif pass_verdict and tid == 19:
            if not any(a.get("action") == "office_control" and "word" in str(a.get("parameter", "")).lower() for a in actions_list):
                pass_verdict = False
                notes = f"Expected office_control word, got {[a.get('action') for a in actions_list]}"
        elif pass_verdict and tid == 20:
            if any(a.get("action") == "close_application" for a in actions_list):
                pass_verdict = False
                notes = "Misrouted to close_application instead of open spotify"
            elif not any("spotify" in str(a.get("parameter", "")).lower() for a in actions_list):
                pass_verdict = False
                notes = f"Expected spotify open, got {[a.get('action') for a in actions_list]}"

        r["pass"] = pass_verdict
        r["notes"] = notes
        print(f"    Re-query Result Task {tid} Run {run_idx}: pass={pass_verdict} model={model_name} actions={len(actions_list)}")

# Re-check obsidian_control sub-actions across ALL rows
for r in rows:
    actions_list = r["raw_output"]["actions"]
    if r["pass"]:
        for a in actions_list:
            if a.get("action") == "obsidian_control":
                sub_act = str(a.get("parameter", "")).split("|")[0].strip().lower()
                if sub_act not in VALID_OBSIDIAN_ACTIONS:
                    r["pass"] = False
                    r["notes"] = f"Invalid obsidian_control sub-action: {sub_act!r} is not supported by obsidian_control"
                    print(f"    Task {r['task_id']} Run {r['run']} marked FAIL due to invalid obsidian sub-action: {sub_act!r}")

for p in paths:
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

passed = sum(1 for r in rows if r["pass"])
print(f"\nFinal Clean Dataset: Passed {passed}/{len(rows)} ({(passed/len(rows))*100:.1f}%)")
