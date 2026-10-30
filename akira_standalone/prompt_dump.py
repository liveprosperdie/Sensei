"""prompt_dump.py — Diagnostic capture hook for Akira system prompts and payloads.

Enabled ONLY when AKIRA_DEBUG_DUMP_PROMPTS=true is set in the environment or .env.
Otherwise completely dormant (no-op).
"""

from __future__ import annotations

import os
import json
import datetime as dt

_HOOK_ENABLED = os.environ.get("AKIRA_DEBUG_DUMP_PROMPTS", "").strip().lower() in ("1", "true", "yes")

def is_enabled() -> bool:
    return os.environ.get("AKIRA_DEBUG_DUMP_PROMPTS", "").strip().lower() in ("1", "true", "yes")

def capture_payload(role: str, system_prompt: str | list | dict,
                    messages: list | dict | str | None = None,
                    extra: dict | None = None) -> None:
    """Diagnostic hook: records wire payload if AKIRA_DEBUG_DUMP_PROMPTS is active."""
    if not is_enabled():
        return

    dump_path = os.path.join(os.path.dirname(__file__), "akira_system_prompts_dump.md")
    timestamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    entry = [
        f"\n\n## [DEBUG HOOK CAPTURE] {role} — {timestamp}\n",
        f"- **Role**: `{role}`\n",
    ]
    if extra:
        for k, v in extra.items():
            entry.append(f"- **{k}**: {v}\n")

    entry.append("\n### System Prompt / Instructions:\n```text\n")
    if isinstance(system_prompt, str):
        entry.append(system_prompt)
    else:
        entry.append(json.dumps(system_prompt, indent=2, ensure_ascii=False))
    entry.append("\n```\n")

    if messages is not None:
        entry.append("\n### Messages / Payload:\n```json\n")
        if isinstance(messages, (dict, list)):
            entry.append(json.dumps(messages, indent=2, ensure_ascii=False))
        else:
            entry.append(str(messages))
        entry.append("\n```\n")

    try:
        with open(dump_path, "a", encoding="utf-8") as f:
            f.write("".join(entry))
        print(f"[prompt_dump] Captured payload for {role} to {dump_path}")
    except Exception as e:
        print(f"[prompt_dump] Error writing debug dump: {e}")
