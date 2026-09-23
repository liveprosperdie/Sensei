"""tests/test_live_pc_execution.py — Live End-to-End Execution Test on PC.

Goes beyond envelope synthesis:
1. Speech API Ingestion
2. Context Delta Filtering
3. Groq Direct JSON Envelope Generation
4. GuardRules Static & Cryptographic Token Validation
5. LIVE PC EXECUTION via executor.execute(action, param, guard_token=token)

Covers:
- OS Lag & Performance Diagnostics (CPU, RAM, Top Processes, non-destructive)
- Excel File Generation & Cell Population (office_control)
- Word / Docx Document Generation (office_control)
- Google Workspace (Calendar / Mail)
- Spotify & Audio Control
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

os.environ.setdefault("GROQ_ROUTER_MODEL", "qwen/qwen3.8-27b")

import guard_rules
import session_context_cache
import tiered_classifier
import executor


TEST_FLOWS = [
    {
        "id": "FLOW-01",
        "category": "OS Lag & Performance Diagnostics",
        "utterance": "Why is my PC lagging? Check what's slowing it down",
        "description": "Checks system performance, CPU, RAM, disk, and heaviest processes non-destructively without private context leakage.",
        "execute_live": True,
    },
    {
        "id": "FLOW-02",
        "category": "Excel Generation & Live Population",
        "utterance": "Spin up a new blank excel sheet and write John into cell A1 and 95 into B1",
        "description": "Generates a real Excel workbook and populates cells via COM automation.",
        "execute_live": True,
    },
    {
        "id": "FLOW-03",
        "category": "Word Document Generation",
        "utterance": "Create a Word document and write a quick summary of renewable energy",
        "description": "Creates a real Word document and inserts text via COM automation.",
        "execute_live": True,
    },
    {
        "id": "FLOW-04",
        "category": "Workspace & Calendar",
        "utterance": "Turn the volume up, then check my calendar for today",
        "description": "Compound action adjusting volume and querying calendar agenda.",
        "execute_live": True,
    },
    {
        "id": "FLOW-05",
        "category": "Spotify & System Control",
        "utterance": "Mute the audio right now and then pull up Spotify to play some lofi beats",
        "description": "Mutes system audio and initiates Spotify playback.",
        "execute_live": True,
    }
]


def run_live_execution_suite():
    print("=" * 85)
    print("AKIRA LIVE PC EXECUTION & FLOW PIPELINE AUDIT")
    print("=" * 85)
    print(f"Router Model: {os.environ.get('GROQ_ROUTER_MODEL')}")
    print("Regex fast-paths: REMOVED (All speech routed to Groq)")
    print("Adapter synthesis: BYPASSED (Groq emits direct action JSON envelope)")
    print("Pipeline Flow: Speech -> Delta Context -> Groq -> GuardToken -> executor.execute()")
    print("=" * 85)

    suite_results = []
    cache = session_context_cache.get_cache()

    for flow in TEST_FLOWS:
        print(f"\n[{flow['id']}] {flow['category']}")
        print(f"  Utterance: {flow['utterance']!r}")

        # 1. Delta context
        t0 = time.perf_counter()
        delta = {"active_window": "Antigravity IDE", "status": "testing_flow"}
        delta_ctx = cache.format_delta_context(delta)
        c_ctx_ms = round((time.perf_counter() - t0) * 1000, 2)

        # 2. Groq Direct JSON synthesis
        t1 = time.perf_counter()
        envelope = tiered_classifier.classify_and_synthesize(flow["utterance"], delta_context=delta_ctx)
        groq_latency_ms = round((time.perf_counter() - t1) * 1000, 2)

        if envelope.get("escalate"):
            print(f"  [ERROR] Groq router escalated: {envelope.get('reason')}")
            flow_res = {
                "id": flow["id"],
                "category": flow["category"],
                "status": "FAIL",
                "error": envelope.get("reason"),
                "groq_ms": groq_latency_ms
            }
            suite_results.append(flow_res)
            continue

        mode = envelope.get("mode")
        actions = envelope.get("actions", [])
        spoken = envelope.get("response", "")
        print(f"  -> Groq Emitted ({groq_latency_ms}ms): mode={mode}, actions={len(actions)}")
        print(f"     Spoken Voice: {spoken!r}")

        execution_logs = []
        all_actions_ok = True

        # 3. Live Execution through GuardToken and executor.execute()
        if flow["execute_live"] and actions:
            print("  -> Advancing into Live PC Execution Flow...")
            for idx, act_step in enumerate(actions, 1):
                act_name = act_step.get("action")
                param = act_step.get("parameter", "")

                t_exec_start = time.perf_counter()
                # Static check & GuardToken issuance
                verdict = guard_rules.validate(act_name, param)
                if verdict.decision == guard_rules.BLOCK:
                    print(f"     Step {idx}: Guard BLOCK on {act_name!r}: {verdict.reasons}")
                    all_actions_ok = False
                    execution_logs.append({
                        "step": idx,
                        "action": act_name,
                        "parameter": param,
                        "status": "GUARD_BLOCKED",
                        "reasons": verdict.reasons
                    })
                    continue

                token = verdict.token
                # LIVE EXECUTION on PC
                try:
                    exec_output = executor.execute(act_name, param, guard_token=token)
                    exec_time_ms = round((time.perf_counter() - t_exec_start) * 1000, 2)

                    # Normalize output string
                    if isinstance(exec_output, dict):
                        out_summary = exec_output.get("message") or ("Success" if exec_output.get("success") else "Failed")
                    else:
                        out_summary = str(exec_output)[:120]

                    print(f"     Step {idx} [{act_name}] ({exec_time_ms}ms) -> Result: {out_summary!r}")
                    execution_logs.append({
                        "step": idx,
                        "action": act_name,
                        "parameter": param,
                        "status": "EXECUTED",
                        "output": exec_output,
                        "exec_ms": exec_time_ms
                    })
                except Exception as e:
                    exec_time_ms = round((time.perf_counter() - t_exec_start) * 1000, 2)
                    print(f"     Step {idx} [{act_name}] ({exec_time_ms}ms) -> Exception: {e!r}")
                    execution_logs.append({
                        "step": idx,
                        "action": act_name,
                        "parameter": param,
                        "status": "EXCEPTION",
                        "error": str(e),
                        "exec_ms": exec_time_ms
                    })

        total_turn_ms = round(c_ctx_ms + groq_latency_ms + sum(l.get("exec_ms", 0) for l in execution_logs), 2)
        print(f"  Total Flow Latency: {total_turn_ms}ms | Verdict: {'[PASS]' if all_actions_ok else '[FAIL]'}")

        flow_res = {
            "id": flow["id"],
            "category": flow["category"],
            "utterance": flow["utterance"],
            "status": "PASS" if all_actions_ok else "FAIL",
            "mode": mode,
            "actions_emitted": actions,
            "spoken_response": spoken,
            "groq_ms": groq_latency_ms,
            "total_ms": total_turn_ms,
            "execution_steps": execution_logs
        }
        suite_results.append(flow_res)

    results_path = ROOT_DIR / "tests" / "live_pc_execution_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(suite_results, f, indent=2)
    print(f"\nDetailed Live Execution report saved to: {results_path}")


if __name__ == "__main__":
    run_live_execution_suite()
