import threading
import json
import socket
import logging
import servant_clients
import memory_control
import llm_json

_log = logging.getLogger(__name__)

_OBSERVER_PROMPT = """You are a background memory and state observer. Your job is to extract important information or state changes from the user's message.

RULES:
1. If the user states a permanent preference, identity fact, or boundary, output exactly this JSON:
{"type": "core", "content": "The fact..."}

2. If the user mentions a notable daily event or task, or explicitly says "remember this", output exactly this JSON:
{"type": "log", "content": "The event..."}

3. If the user explicitly tells you to go to sleep or take a rest, output exactly this JSON:
{"action": "SLEEP_START"}

4. If the user explicitly tells you to wake up, output exactly this JSON:
{"action": "SLEEP_STOP"}

5. If the user praises, thanks, compliments, or expresses appreciation to you (e.g., "good job", "thank you", "you're the best"), output exactly this JSON:
{"action": "HAPPY_START"}

6. If the user is just chatting, asking a question, or giving a normal command (e.g. "search the web", "open youtube", "how are you"), output exactly this JSON:
{"type": "none"}

You MUST output ONLY the JSON object. No prose, no thinking."""

def _observe_turn_blocking(user_text: str):
    """Synchronous background thread payload."""
    if not user_text or not user_text.strip():
        return
        
    try:
        try:
            import prompt_dump
            prompt_dump.capture_payload("Memory Observer", _OBSERVER_PROMPT, user_text)
        except Exception:
            pass
        # We try local GUARD adapter first; fall back to model_pool on Free tier
        text = None
        try:
            result = servant_clients.call_openai_compatible(
                tier=servant_clients.GUARD,
                system=_OBSERVER_PROMPT,
                user=user_text,
                max_tokens=150,
                label="memory_observer"
            )
            text = result.strip()
        except Exception:
            try:
                import model_pool
                pool = model_pool.get_pool()
                if pool.get_available_endpoints():
                    call_res = pool.call_model(
                        messages=[{"role": "user", "content": user_text}],
                        system=_OBSERVER_PROMPT,
                        json_mode=True,
                        timeout=10.0,
                        max_tokens=150,
                    )
                    text = call_res.text.strip()
            except Exception:
                pass

        if not text:
            return

        # BUG FIX (2026-09): backward-compat with old bare "NONE" responses
        # from cached/stale model outputs that haven't seen the new prompt yet.
        if text.upper().strip('"').strip() == "NONE":
            return

        # BUG FIX (2026-09): use the robust llm_json.parse() pipeline instead
        # of raw _repair() + json.loads(). The old code crashed on trailing
        # whitespace/text after the JSON object (char-54 JSONDecodeError) and
        # on responses with markdown wrappers, self-correcting replies, etc.
        data, info = llm_json.parse(text)
        if data is None:
            _log.warning("[observer] could not parse observer response: %.120s", text)
            return
        if info.get("truncated"):
            _log.warning("[observer] observer response was truncated, skipping")
            return

        # Handle "none" type (new prompt format for Rule 6)
        if data.get("type") == "none":
            return

        # Handle Avatar State
        action = data.get("action")
        if action in ("SLEEP_START", "SLEEP_STOP", "HAPPY_START"):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(action.encode('utf-8'), ("127.0.0.1", 55555))
                print(f"[observer] Triggered avatar {action}")
            except Exception as e:
                print(f"[observer] UDP failed: {e}")
                
        # Handle Memory
        mem_type = data.get("type")
        content = data.get("content")
        
        if mem_type and content:
            # We reuse memory_control.save_memory because it handles the file IO
            memory_control.save_memory(data)
            print(f"[observer] Extracted {mem_type} memory: {content}")
            
    except Exception as e:
        _log.warning("[memory_observer] extraction failed: %s", e)

def observe_turn_async(user_text: str):
    """Spawns a background thread to observe the turn without blocking the main loop."""
    t = threading.Thread(target=_observe_turn_blocking, args=(user_text,), daemon=True)
    t.start()

