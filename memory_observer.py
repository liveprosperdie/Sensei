import threading
import json
import servant_clients
import memory_control
import llm_json

_OBSERVER_PROMPT = """You are a background memory observer. Your job is to extract important information from the user's message.

RULES:
1. If the user states a permanent preference, identity fact, or boundary, output exactly this JSON:
{"type": "core", "content": "The fact..."}

2. If the user mentions a notable daily event or task, or explicitly says "remember this", output exactly this JSON:
{"type": "log", "content": "The event..."}

3. If the user is just chatting, asking a question, or giving a normal command (e.g. "search the web", "open youtube", "how are you"), output exactly:
NONE

You MUST output ONLY the JSON object or NONE. No prose, no thinking."""

def _observe_turn_blocking(user_text: str):
    """Synchronous background thread payload."""
    if not user_text or not user_text.strip():
        return
        
    try:
        # We use the GUARD adapter since it's already a fast local Llama 3.2 8B model.
        result = servant_clients.call_openai_compatible(
            tier=servant_clients.GUARD,
            system=_OBSERVER_PROMPT,
            prompt=user_text,
            temperature=0.0,  # Zero for extraction
            max_tokens=150
        )
        
        text = result.strip()
        if not text or text.upper() == "NONE":
            return
            
        # Parse it
        parsed, truncated = llm_json._repair(text)
        if truncated:
            return
            
        data = json.loads(parsed)
        mem_type = data.get("type")
        content = data.get("content")
        
        if mem_type and content:
            # We reuse memory_control.save_memory because it handles the file IO
            memory_control.save_memory(data)
            print(f"[memory_observer] Extracted {mem_type} memory: {content}")
            
    except Exception as e:
        print(f"[memory_observer] extraction failed silently: {e}")

def observe_turn_async(user_text: str):
    """Spawns a background thread to observe the turn without blocking the main loop."""
    t = threading.Thread(target=_observe_turn_blocking, args=(user_text,), daemon=True)
    t.start()
