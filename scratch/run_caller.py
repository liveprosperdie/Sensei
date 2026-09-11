import os
import sys
import json
import time
import re
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, r"d:\Coding\Projects\Sensei")

import gemini_head
from scratch.chain_utils import append_row, get_last_hash

TASKS = [
    (1, "Open notepad, write a short paragraph about climate change, then open spotify and play lo-fi music", "chain"),
    (2, "Search reddit for r/programming, then open notepad and write down 3 things I should look into there", "chain"),
    (3, "Write a note in obsidian about today's meeting, then send an email to sarah summarizing it", "chain"),
    (4, "Open word, write a one-paragraph report on renewable energy, then copy the report to the clipboard as well", "chain"),
    (5, "Close spotify, open chrome, search netflix for stranger things, then pause", "chain"),

    (6, "Write an email to marcus about the budget meeting, mention it's moved to Thursday", "workspace"),
    (7, "Draft an email to the whole team announcing the product launch date", "workspace"),
    (8, "Create a calendar event for a dentist appointment next Tuesday at 3pm", "workspace"),
    (9, "Write an email to hr requesting time off next week, keep it professional", "workspace"),
    (10, "Reply to sarah's email agreeing to the proposal, add one clarifying question", "workspace"),

    (11, "Create a note in obsidian titled 'Project Ideas' and write three bullet points of ideas about a mobile app", "obsidian"),
    (12, "Add a new section to my existing obsidian daily note summarizing what I did today", "obsidian"),
    (13, "Create an obsidian note that links to my 'Project Ideas' note and explains why I'm revisiting it", "obsidian"),
    (14, "Search my obsidian vault for notes about 'budget' and summarize what you find", "obsidian"),
    (15, "Create a note in obsidian with a markdown table comparing three phone models", "obsidian"),

    (16, "search netflix for the office", "ambiguous"),
    (17, "look up python tutorials on youtube", "ambiguous"),
    (18, "write me a note on stoicism", "ambiguous"),
    (19, "open word and write a report about quantum computing", "ambiguous"),
    (20, "stop, open spotify instead", "ambiguous"),
]

RESULTS_PATH = r"d:\Coding\Projects\Sensei\scratch\results_chain.jsonl"

def call_task(task_id, prompt, category, run_idx, groq_key):
    print(f"--> Calling Task {task_id} (Run {run_idx}/2): '{prompt[:50]}...'")
    reply = None
    max_retries = 15
    for attempt in range(max_retries):
        messages = [{"role": "user", "content": prompt}]
        reply = gemini_head._route_via_groq(groq_key, messages, [], session_id=f"task_{task_id}_{run_idx}")
        
        if reply and reply.text and ("rate-limited" in reply.text.lower() or "busy" in reply.text.lower() or not reply.text.strip()):
            wait_m = re.search(r'wait (\d+(?:\.\d+)?)', reply.text)
            w_sec = float(wait_m.group(1)) if wait_m else 6.0
            print(f"    [Rate limit] Pausing {w_sec + 3.0:.1f}s before retry (attempt {attempt+1}/{max_retries})...")
            time.sleep(w_sec + 3.0)
            continue
        elif reply and reply.text and reply.text.strip():
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

    actions_list = []
    if "actions" in raw_dict and isinstance(raw_dict["actions"], list):
        actions_list = raw_dict["actions"]
    elif "action" in raw_dict and raw_dict["action"]:
        actions_list = [{"action": raw_dict.get("action"), "parameter": raw_dict.get("parameter", "")}]

    actions_payload = [
        {"action": str(a.get("action", "")), "parameter": str(a.get("parameter", "")) if a.get("parameter") is not None else ""}
        for a in actions_list
    ]

    model_name = getattr(reply, 'model', 'unknown') if reply else 'unknown'

    row = {
        "task_id": task_id,
        "run": run_idx,
        "category": category,
        "prompt": prompt,
        "model_served": model_name,
        "raw_output": {
            "actions": actions_payload
        }
    }
    
    prev_h = get_last_hash(RESULTS_PATH)
    h = append_row(RESULTS_PATH, row, prev_h)
    print(f"    Recorded raw output | Model: {model_name} | Actions: {len(actions_payload)} | Hash: {h[:12]}")
    return h

def main():
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("ERROR: GROQ_API_KEY is not set!")
        sys.exit(1)

    print("Starting run_caller.py across all 40 (task_id, run) pairs...")
    for task_id, prompt, category in TASKS:
        for run_idx in (1, 2):
            call_task(task_id, prompt, category, run_idx, groq_key)
            time.sleep(3.0) # Pace calls to respect Groq RPM limits

    print("Caller completed all 40 runs!")

if __name__ == "__main__":
    main()
