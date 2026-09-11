import os
import sys
import json
import time
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, r"d:\Coding\Projects\Sensei")

from scratch.run_caller import TASKS, call_task

def main():
    if len(sys.argv) < 3:
        print("Usage: python scratch/retry_task.py <task_id> <run>")
        sys.exit(1)

    task_id = int(sys.argv[1])
    run_idx = int(sys.argv[2])

    task_tuple = next((t for t in TASKS if t[0] == task_id), None)
    if not task_tuple:
        print(f"ERROR: Task {task_id} not found in TASKS")
        sys.exit(1)

    prompt = task_tuple[1]
    category = task_tuple[2]

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("ERROR: GROQ_API_KEY is not set!")
        sys.exit(1)

    print(f"Retrying Task {task_id} (Run {run_idx}) live...")
    new_hash = call_task(task_id, prompt, category, run_idx, groq_key)
    print(f"Appended new raw row to results_chain.jsonl with hash: {new_hash}")

if __name__ == "__main__":
    main()
