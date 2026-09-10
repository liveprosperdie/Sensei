import os
import sys
import json
import time
import re
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, r"d:\Coding\Projects\Sensei")

import model_pool
import text_mode
import gemini_head
import guard_rules
import gemini_content

TASKS = [
    # Chains (multi-step, must execute ALL steps in order)
    (1, "Open notepad, write a short paragraph about climate change, then open spotify and play lo-fi music", "chain"),
    (2, "Search reddit for r/programming, then open notepad and write down 3 things I should look into there", "chain"),
    (3, "Write a note in obsidian about today's meeting, then send an email to sarah summarizing it", "chain"),
    (4, "Open word, write a one-paragraph report on renewable energy, then copy the report to the clipboard as well", "chain"),
    (5, "Close spotify, open chrome, search netflix for stranger things, then pause", "chain"),

    # Google Workspace (real generated content required, not literal echo)
    (6, "Write an email to marcus about the budget meeting, mention it's moved to Thursday", "workspace"),
    (7, "Draft an email to the whole team announcing the product launch date", "workspace"),
    (8, "Create a calendar event for a dentist appointment next Tuesday at 3pm", "workspace"),
    (9, "Write an email to hr requesting time off next week, keep it professional", "workspace"),
    (10, "Reply to sarah's email agreeing to the proposal, add one clarifying question", "workspace"),

    # Complex Obsidian tasks
    (11, "Create a note in obsidian titled 'Project Ideas' and write three bullet points of ideas about a mobile app", "obsidian"),
    (12, "Add a new section to my existing obsidian daily note summarizing what I did today", "obsidian"),
    (13, "Create an obsidian note that links to my 'Project Ideas' note and explains why I'm revisiting it", "obsidian"),
    (14, "Search my obsidian vault for notes about 'budget' and summarize what you find", "obsidian"),
    (15, "Create a note in obsidian with a markdown table comparing three phone models", "obsidian"),

    # Site-specific / ambiguous phrasing (tests literal-echo and misrouting)
    (16, "search netflix for the office", "ambiguous"),
    (17, "look up python tutorials on youtube", "ambiguous"),
    (18, "write me a note on stoicism", "ambiguous"),
    (19, "open word and write a report about quantum computing", "ambiguous"),
    (20, "stop, open spotify instead", "ambiguous"),
]

def run_benchmark():
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("ERROR: GROQ_API_KEY is not set!")
        sys.exit(1)

    all_results = []
    print(f"Starting 20-task benchmark (40 runs total) against live fallback model pool...")

    for task_id, prompt, category in TASKS:
        for run_idx in (1, 2):
            print(f"\n--> Running Task {task_id} (Run {run_idx}/2): '{prompt[:55]}...'")

            # Route call with automatic rate limit backoff retry
            reply = None
            max_retries = 12
            for attempt in range(max_retries):
                messages = [{"role": "user", "content": prompt}]
                reply = gemini_head._route_via_groq(groq_key, messages, [], session_id=f"task_{task_id}_{run_idx}")
                
                # Check if rate limited refusal was returned or empty reply
                if reply and ("rate-limited" in reply.text.lower() or "busy" in reply.text.lower() or not reply.text.strip()):
                    wait_m = re.search(r'wait (\d+(?:\.\d+)?)', reply.text)
                    w_sec = float(wait_m.group(1)) if wait_m else 4.0
                    print(f"    [Rate limit wait] Pausing {w_sec + 2.0:.1f}s before retry (attempt {attempt+1}/{max_retries})...")
                    time.sleep(w_sec + 2.0)
                    continue
                elif reply and reply.text.strip():
                    break
                else:
                    print(f"    [Retry wait] Pausing 4.0s before retry (attempt {attempt+1}/{max_retries})...")
                    time.sleep(4.0)

            raw_dict = {}
            raw_text = reply.text if reply else "{}"
            try:
                raw_dict = json.loads(raw_text)
            except Exception:
                raw_dict = {"mode": "error", "raw_text": raw_text}

            # Extract actions
            actions_list = []
            if "actions" in raw_dict and isinstance(raw_dict["actions"], list):
                actions_list = raw_dict["actions"]
            elif "action" in raw_dict and raw_dict["action"]:
                actions_list = [{"action": raw_dict.get("action"), "parameter": raw_dict.get("parameter", "")}]

            # Evaluate through Guard
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

            # Generate real content if this task involved two-stage content generation
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
                    # SINGLE-STAGE: obsidian_control writes parameter directly to vault note.
                    # Exactly as constructed by obsidian_control._do_create():
                    parts = param.split("|", 2)
                    title = parts[1] if len(parts) > 1 else "Untitled"
                    content = parts[2] if len(parts) > 2 else ""
                    generated_content = f"# {title}\n\n{content}".rstrip() + "\n"
                    break

            # If task was a two-stage generation task (Workspace/Office/Clipboard), generate content via gemini_content:
            if not generated_content and brief_to_gen:
                for gen_att in range(3):
                    try:
                        c_res = gemini_content.generate(brief_to_gen, length="short")
                        if c_res.get("success") and c_res.get("text"):
                            generated_content = c_res["text"].strip()
                            break
                        else:
                            time.sleep(1.5)
                    except Exception as ge:
                        time.sleep(1.5)

            # Verification of criteria
            chain_all_executed = True
            pass_verdict = True
            notes = ""

            if category == "chain":
                if task_id in (1, 2):
                    # ACCURACY CHECK: window_typing is NOT built.
                    # The assistant opens Notepad but copies text to clipboard instead of typing into Notepad.
                    # Notepad remains empty. This is a genuine gap / failure.
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

            # Anti-echo check across workspace/content tasks
            if task_id in (6, 7, 9, 10):
                for a in actions_list:
                    if a.get("action") == "gmail_compose":
                        p = str(a.get("parameter") or "")
                        if p.startswith("draft|") and any(phrase in p for phrase in ("about the budget meeting", "announcing the product launch date", "requesting time off next week")):
                            pass_verdict = False
                            notes = "Literal echo detected in draft parameter"

            # Obsidian Sub-Action & Content Integrity Checks
            VALID_OBSIDIAN_ACTIONS = {"search", "read", "active", "append", "progress", "create", "link", "moc", "diagram", "organize", "tags", "open", "status"}
            for a in actions_list:
                if a.get("action") == "obsidian_control":
                    sub_act = str(a.get("parameter", "")).split("|")[0].strip().lower()
                    if sub_act not in VALID_OBSIDIAN_ACTIONS:
                        pass_verdict = False
                        notes = f"Invalid obsidian_control sub-action: {sub_act!r} is not supported by obsidian_control"

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

            # Specific misrouting checks
            if task_id == 16:
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

            model_name = getattr(reply, 'model', 'unknown')

            actions_payload = [
                {"action": str(a.get("action", "")), "parameter": str(a.get("parameter", "")) if a.get("parameter") is not None else ""}
                for a in actions_list
            ]

            row = {
                "task_id": task_id,
                "run": run_idx,
                "model_served": model_name,
                "raw_output": {
                    "actions": actions_payload
                },
                "guard_decision": worst_decision,
                "guard_reasons": all_reasons,
                "generated_content": generated_content,
                "chain_all_steps_executed": chain_all_executed,
                "pass": pass_verdict,
                "notes": notes if not pass_verdict else ""
            }
            all_results.append(row)
            print(f"    Verdict: {'PASS' if pass_verdict else 'FAIL'} | Model: {model_name} | Guard: {worst_decision} | Actions: {len(actions_list)}")

            # Pause between runs to respect RPM
            time.sleep(2.0)

    # Save to both target scratch locations
    out_paths = [
        r"d:\Coding\Projects\Sensei\scratch\fallback_api_test_results.json",
        r"C:\Users\shrey pathak\.gemini\antigravity-ide\brain\4dd71589-e988-400e-8a2e-6893daf1fdc9\scratch\fallback_api_test_results.json"
    ]
    for p in out_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(all_results)} results to {p}")

    total_runs = len(all_results)
    passed_runs = sum(1 for r in all_results if r["pass"])
    print(f"\nBenchmark Complete! Passed: {passed_runs}/{total_runs} ({(passed_runs/total_runs)*100:.1f}%)")

if __name__ == "__main__":
    run_benchmark()
