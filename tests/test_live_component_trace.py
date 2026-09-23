"""tests/test_live_component_trace.py — Detailed Component-by-Component Latency & Output Trace.

Tests live execution across all components:
1. Speech API (transcription text ingestion)
2. Session Context Cache (delta context filtering)
3. Groq Direct Action Router (direct JSON output with hardcoded personality & schema, 0 regex)
4. Guard Rules & Action Guard (safety, arity, and enum validation)
5. Executor Action Dispatch (final envelope ready for execution)
"""

import os
import sys
import time
import json
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

# Ensure required env vars
os.environ.setdefault("GROQ_ROUTER_MODEL", "qwen/qwen3.8-27b")

import session_context_cache
import tiered_classifier
import guard_rules
import action_guard


TEST_CASES = [
    {
        "id": "TC-01",
        "name": "Compound Multi-Action (Volume + Calendar)",
        "speech_text": "Turn the volume up, then check my calendar for today",
        "expected_action_count": 2,
        "expected_actions": ["adjust_volume", "calendar_control"],
        "setup_context": None,
    },
    {
        "id": "TC-02",
        "name": "Chained Multi-Action (Mute + App + Spotify)",
        "speech_text": "Mute the audio right now and then pull up Spotify to play some lofi beats",
        "expected_action_count": 3,
        "expected_actions": ["adjust_volume", "open_application", "spotify_control"],
        "setup_context": None,
    },
    {
        "id": "TC-03",
        "name": "Context-Dependent Clipboard Copy (Last Assistant Response)",
        "speech_text": "Sensei, copy this information into my clipboard that you provided in the last response.",
        "expected_action_count": 1,
        "expected_actions": ["write_clipboard"],
        "setup_context": {
            "last_response": "The quarterly project deadline is set for Friday at 5:00 PM."
        },
    },
    {
        "id": "TC-04",
        "name": "In-App Automation (Excel Blank Sheet + Cell Writes)",
        "speech_text": "Spin up a new blank excel sheet and write John into cell A1 and 95 into B1",
        "expected_action_count": 3,
        "expected_actions": ["office_control", "office_control", "office_control"],
        "setup_context": None,
    },
    {
        "id": "TC-05",
        "name": "Conversational & Personality Test (Voice TTS Format)",
        "speech_text": "Who are you and what can you help me with?",
        "expected_action_count": 0,
        "expected_actions": [],
        "setup_context": None,
    }
]


def run_component_trace():
    print("=" * 80)
    print("AKIRA COMPONENT-BY-COMPONENT LIVE LATENCY & OUTPUT AUDIT (NO REGEX)")
    print("=" * 80)
    print(f"Router Model: {os.environ.get('GROQ_ROUTER_MODEL')}")
    print("Regex fast-paths: REMOVED (All commands routed directly to Groq JSON engine)")
    print("Adapter synthesis: BYPASSED (Groq emits direct action JSON envelope)")
    print("=" * 80)

    trace_results = []

    for tc in TEST_CASES:
        print(f"\n[{tc['id']}] Running: {tc['name']}")
        print(f"  Speech API Utterance: {tc['speech_text']!r}")

        # Setup context if needed
        cache = session_context_cache.get_cache()
        if tc["setup_context"]:
            if "last_response" in tc["setup_context"]:
                session_context_cache.set_last_assistant_response(tc["setup_context"]["last_response"])
                print(f"  Preset [LAST ASSISTANT RESPONSE]: {tc['setup_context']['last_response']!r}")

        # ── COMPONENT 1: Speech API Ingestion ────────────────────────────────
        t0 = time.perf_counter()
        raw_speech_text = tc["speech_text"].strip()
        c1_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        print(f"  -> [Component 1: Speech API] Text Ingested in {c1_latency_ms}ms")

        # ── COMPONENT 2: Session Context Cache (Delta Filtering) ─────────────
        t1 = time.perf_counter()
        delta = {"active_window": "VS Code", "current_tab": "GitHub Sensei Repo"}
        delta_context = cache.format_delta_context(delta)
        c2_latency_ms = round((time.perf_counter() - t1) * 1000, 2)
        print(f"  -> [Component 2: Context Filter] Delta context formatted in {c2_latency_ms}ms ({len(delta_context)} chars)")

        # ── COMPONENT 3: Groq Router (Direct Action JSON + Personality) ──────
        t2 = time.perf_counter()
        raw_envelope = tiered_classifier._call_groq_router(raw_speech_text, delta_context=delta_context)
        c3_latency_ms = round((time.perf_counter() - t2) * 1000, 2)
        print(f"  -> [Component 3: Groq Router] Response generated in {c3_latency_ms}ms")
        print(f"     Raw Groq JSON Output:\n     {json.dumps(raw_envelope, indent=2)}")

        # ── COMPONENT 4: Guard Rules & Action Guard Validation ───────────────
        t3 = time.perf_counter()
        validated_envelope = tiered_classifier._validate_groq_envelope(raw_envelope)
        c4_latency_ms = round((time.perf_counter() - t3) * 1000, 2)
        guard_status = "PASSED" if not validated_envelope.get("escalate") else f"FAILED ({validated_envelope.get('reason')})"
        print(f"  -> [Component 4: Guard Validation] Completed in {c4_latency_ms}ms | Status: {guard_status}")

        # ── COMPONENT 5: Executor Dispatch Envelope ──────────────────────────
        t4 = time.perf_counter()
        mode = validated_envelope.get("mode")
        actions = validated_envelope.get("actions", [])
        spoken_response = validated_envelope.get("response", "")
        c5_latency_ms = round((time.perf_counter() - t4) * 1000, 2)
        total_latency_ms = round(c1_latency_ms + c2_latency_ms + c3_latency_ms + c4_latency_ms + c5_latency_ms, 2)

        print(f"  -> [Component 5: Executor Ready] Mode: {mode} | Actions: {len(actions)} | Spoken TTS: {spoken_response!r}")
        print(f"  Total End-to-End Latency: {total_latency_ms}ms")

        # Verify expectations
        act_names = [a.get("action") for a in actions]
        pass_action_count = len(actions) == tc["expected_action_count"]
        pass_actions = all(exp in act_names for exp in tc["expected_actions"]) if tc["expected_actions"] else (len(actions) == 0)
        overall_pass = pass_action_count and pass_actions and (guard_status == "PASSED")

        result_item = {
            "id": tc["id"],
            "name": tc["name"],
            "speech_text": tc["speech_text"],
            "overall_pass": overall_pass,
            "components": {
                "c1_speech_ingest_ms": c1_latency_ms,
                "c2_context_filter_ms": c2_latency_ms,
                "c3_groq_router_ms": c3_latency_ms,
                "c4_guard_validation_ms": c4_latency_ms,
                "c5_executor_dispatch_ms": c5_latency_ms,
                "total_e2e_ms": total_latency_ms,
            },
            "output": {
                "mode": mode,
                "actions": actions,
                "spoken_response": spoken_response,
                "guard_status": guard_status
            }
        }
        trace_results.append(result_item)
        print(f"  TEST VERDICT: {'[PASS]' if overall_pass else '[FAIL]'}")

    out_file = ROOT_DIR / "tests" / "component_trace_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(trace_results, f, indent=2)
    print(f"\nFull trace saved to: {out_file}")


if __name__ == "__main__":
    run_component_trace()
