"""Memory Compaction Job.

Runs periodically to delete raw daily logs older than 30 days.
It uses SERVANT_MECH to extract any major life events or permanent preferences
from the old logs before deleting them, and appends them to the core profile.
"""

import os
import datetime
import glob
import servant_clients

MEMORY_DIR = os.path.join(os.path.dirname(__file__), "memory")
LOGS_DIR = os.path.join(MEMORY_DIR, "logs")
CORE_PROFILE = os.path.join(MEMORY_DIR, "core_profile.md")
MAX_AGE_DAYS = 30

COMPACTION_SYSTEM = (
    "You are a memory compaction agent. You are given a daily activity log for a user. "
    "Your job is to extract ONLY major life events, important milestones, or new permanent "
    "preferences that should be remembered forever. "
    "Ignore routine tasks, meetings, daily chores, and mundane actions. "
    "Output your findings as a short bulleted markdown list. If there is nothing of long-term "
    "importance, output exactly 'NONE'."
)

def _append_to_core(text: str):
    if text.strip() == "NONE":
        return
    try:
        with open(CORE_PROFILE, "a", encoding="utf-8") as f:
            f.write(f"\n{text.strip()}\n")
    except Exception as e:
        print(f"[memory_compaction] Failed to write to core profile: {e}")

def run_compaction():
    print("[memory_compaction] Starting memory compaction job...")
    if not os.path.exists(LOGS_DIR):
        print("[memory_compaction] No logs directory found.")
        return

    now = datetime.datetime.now()
    cutoff_date = now - datetime.timedelta(days=MAX_AGE_DAYS)
    
    log_files = glob.glob(os.path.join(LOGS_DIR, "*.md"))
    deleted_count = 0
    
    for file_path in log_files:
        filename = os.path.basename(file_path)
        date_str = filename.replace(".md", "")
        
        try:
            log_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
            
        if log_date < cutoff_date:
            print(f"[memory_compaction] Compacting and deleting old log: {filename}")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Ask servant model to extract big events
                payload = servant_clients.call_openai_compatible(
                    servant_clients.SERVANT_MECH,
                    system=COMPACTION_SYSTEM,
                    user=content,
                    max_tokens=300,
                    timeout=30.0,
                    label="compaction"
                ).strip()
                
                _append_to_core(payload)
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                print(f"[memory_compaction] Error processing {filename}: {e}")
                
    print(f"[memory_compaction] Job complete. Compacted {deleted_count} logs.")

if __name__ == "__main__":
    run_compaction()
