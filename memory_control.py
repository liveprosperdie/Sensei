import os
import datetime
import glob
import re

MEMORY_DIR = os.path.join(os.path.dirname(__file__), "memory")
LOGS_DIR = os.path.join(MEMORY_DIR, "logs")

def _ensure_dirs():
    os.makedirs(LOGS_DIR, exist_ok=True)

def _today_log_path() -> str:
    _ensure_dirs()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOGS_DIR, f"{today}.md")

def log_action(text: str) -> None:
    """Silently logs an action to today's rolling log."""
    try:
        path = _today_log_path()
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- **{timestamp}**: {text}\n")
    except Exception as e:
        print(f"[memory_control] failed to log action: {e}")

def save_memory(parameter) -> dict:
    """Autonomously saves memory to either core profile (forever) or daily log (30 days)."""
    import json
    
    if not parameter:
        return {"success": False, "message": "Nothing to remember."}
        
    try:
        # Check if parameter is a JSON dict (e.g. {"type": "core", "content": "..."})
        if isinstance(parameter, str):
            try:
                data = json.loads(parameter)
            except json.JSONDecodeError:
                data = {"type": "log", "content": parameter}
        else:
            data = parameter
            
        mem_type = data.get("type", "log")
        content = data.get("content", str(data))
        
        if mem_type == "core":
            core_path = os.path.join(MEMORY_DIR, "core_profile.md")
            with open(core_path, "a", encoding="utf-8") as f:
                f.write(f"\n- {content}\n")
            msg = "Saved to core memory."
        else:
            log_action(content)
            msg = "Saved to daily memory."
            
        return {"success": True, "speak": False, "message": msg}
    except Exception as e:
        return {"success": False, "message": f"Failed to save memory: {e}"}

def search_memory(query: str) -> dict:
    """Searches past daily logs for the query."""
    if not query:
        return {"success": False, "message": "You must provide a search query."}
    
    _ensure_dirs()
    log_files = sorted(glob.glob(os.path.join(LOGS_DIR, "*.md")), reverse=True)
    
    hits = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    
    for file_path in log_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                if pattern.search(content):
                    date_str = os.path.basename(file_path).replace(".md", "")
                    hits.append(f"--- LOG: {date_str} ---\n{content.strip()}")
        except Exception:
            continue
            
    if not hits:
        return {"success": True, "speak": True, "message": f"I couldn't find anything matching '{query}' in your past memory logs."}
    
    # Return the last 3 days of hits to avoid blowing up the context window
    combined = "\n\n".join(hits[:3])
    msg = f"I found some matches in your memory logs:\n\n{combined}"
    return {"success": True, "speak": True, "message": msg}

def forget_today() -> dict:
    """Deletes today's log file."""
    path = _today_log_path()
    if os.path.exists(path):
        os.remove(path)
        return {"success": True, "speak": True, "message": "I have deleted all memory logs for today."}
    return {"success": True, "speak": True, "message": "There were no memory logs saved for today."}

def wipe_all_memory() -> dict:
    """Deletes all daily logs and resets the core profile."""
    try:
        log_files = glob.glob(os.path.join(LOGS_DIR, "*.md"))
        for f in log_files:
            os.remove(f)
            
        core = os.path.join(MEMORY_DIR, "core_profile.md")
        if os.path.exists(core):
            with open(core, "w", encoding="utf-8") as f:
                f.write("# Akira Core Profile\n*Memory wiped.*\n")
                
        return {"success": True, "speak": True, "message": "I have completely wiped my memory logs and core profile."}
    except Exception as e:
        return {"success": False, "message": f"Failed to wipe memory: {e}"}
