import time
import subprocess
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCHED_FILES = [
    ".vscode",
    ".gitignore",
    "OBSIDIAN_FOCUS_MODE_PLAN.md",
    "SETUP_OBSIDIAN_FOCUS_MODE.md",
    "action_guard.py",
    "action_router.py",
    "avatar_ui.py",
    "background_tasks.py",
    "calendar_control.py",
    "chunked_read.py",
    "claude_handler.py",
    "doc_image_plan.py",
    "docs_control.py",
    "dom_extract.py",
    "element_matcher.py",
    "executor.py",
    "gemini_content.py",
    "gemini_head.py",
    "gemini_quota.py",
    "gmail_control.py",
    "google_mcp.py",
    "guard.py",
    "guard_rules.py",
    "hardware_gate.py",
    "image_flow.py",
    "llm_json.py",
    "mcp_client.py",
    "memory_compaction.py",
    "memory_control.py",
    "memory_observer.py",
    "native_ui.py",
    "netflix_selector_diagnostic.py",
    "obsidian_api.py",
    "obsidian_context.py",
    "obsidian_control.py",
    "office_control.py",
    "reliability.py",
    "repo_notes.py",
    "requirements.txt",
    "sensei.py",
    "servant_clients.py",
    "sheets_control.py",
    "slides_control.py",
    "structural_ui.py",
    "system_control.py",
    "tiers.py",
    "verify_gemini_head.py",
    "verify_guard_coverage.py",
    "verify_guard_wiring.py",
    "verify_hardware_gate.py",
    "verify_router.py",
    "verify_servant_tier.py",
    "verify_tiers.py"
]
LINE_THRESHOLD = 15  # commits once changes cross this, tune as you like
DEBOUNCE_SECONDS = 5  # waits this long after last edit before checking, avoids mid-save races

def get_line_delta():
    result = subprocess.run(
        ["git", "diff", "--numstat"] + WATCHED_FILES,
        capture_output=True, text=True
    )
    total = 0
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            total += int(parts[0]) + int(parts[1])
    return total

def commit_if_threshold_met():
    delta = get_line_delta()
    if delta >= LINE_THRESHOLD:
        subprocess.run(["git", "add"] + WATCHED_FILES)
        msg = f"wip: auto-checkpoint {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", msg])

        current_branch = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True
        ).stdout.strip()

        push_result = subprocess.run(["git", "push"], capture_output=True, text=True)
        if push_result.returncode != 0:
            print(f"[auto-commit] {delta} lines changed, committed locally, PUSH FAILED: {push_result.stderr.strip()}")
            return

        print(f"[auto-commit] {delta} lines changed, committed and pushed to {current_branch}.")

        if current_branch != "main":
            subprocess.run(["git", "checkout", "main"], capture_output=True, text=True)
            subprocess.run(["git", "pull"], capture_output=True, text=True)
            merge_result = subprocess.run(["git", "merge", current_branch], capture_output=True, text=True)
            if merge_result.returncode != 0:
                print(f"[auto-commit] MERGE INTO MAIN FAILED, left on main with conflict — resolve manually: {merge_result.stderr.strip()}")
                return
            main_push = subprocess.run(["git", "push"], capture_output=True, text=True)
            if main_push.returncode != 0:
                print(f"[auto-commit] merged to main locally but PUSH FAILED: {main_push.stderr.strip()}")
            else:
                print(f"[auto-commit] merged {current_branch} into main and pushed.")
            subprocess.run(["git", "checkout", current_branch], capture_output=True, text=True)

class Handler(FileSystemEventHandler):
    def __init__(self):
        self.last_event = 0

    def on_modified(self, event):
        if event.is_directory:
            return
            
        src = event.src_path.replace('\\', '/')
        is_watched = any(src.endswith('/' + f) or src == f or ('/' + f + '/') in src or src.startswith(f + '/') for f in WATCHED_FILES)
        
        if is_watched:
            now = time.time()
            self.last_event = now
            time.sleep(DEBOUNCE_SECONDS)
            if self.last_event == now:  # no newer edit came in during the wait
                commit_if_threshold_met()

if __name__ == "__main__":
    path = "."
    handler = Handler()
    observer = Observer()
    observer.schedule(handler, path, recursive=True)
    observer.start()
    print(f"Watching {WATCHED_FILES} — auto-commit every {LINE_THRESHOLD}+ lines changed.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()