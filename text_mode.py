import os
import sys
import time
from dotenv import load_dotenv

if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

import types

# Gating rules definition for pure text mode (no microphone/PyAudio/PyQt6 required)
DANGEROUS_ACTIONS = frozenset({
    "delete_files", "shutdown_pc", "restart_pc", "restart",
    "kill_process", "empty_recycle_bin", "uninstall_application",
    "restore_files", "set_volume",
})
RISKY_SHOPPING_PARAMS = frozenset({
    "proceed to checkout", "checkout", "place order",
    "confirm address", "select address", "confirm delivery address", "deliver here",
})
RISKY_GITHUB_PARAMS = frozenset({
    "create pull request", "merge pull request",
    "close issue", "close pull request",
    "delete branch", "delete repo", "delete repository",
    "push", "force push",
})
RISKY_VSCODE_PARAMS = frozenset({"write file", "edit file"})
RISKY_CALENDAR_PARAMS = frozenset({"delete"})
RISKY_WORKSPACE_PARAMS = frozenset({"delete"})

def _is_dangerous_step(step: dict) -> bool:
    """True if this action step must be confirmation-gated by the safety net."""
    action = step.get("action")
    if action in DANGEROUS_ACTIONS:
        return True
    param = (step.get("parameter") or "").split("|")[0].strip().lower().replace("_", " ")
    if action in ("amazon_control", "flipkart_control"):
        return param in RISKY_SHOPPING_PARAMS
    if action == "github_control":
        return param in RISKY_GITHUB_PARAMS
    if action == "vscode_control":
        return param in RISKY_VSCODE_PARAMS
    if action == "calendar_control":
        return param in RISKY_CALENDAR_PARAMS
    if action in ("slides_control", "docs_control", "sheets_control"):
        return param in RISKY_WORKSPACE_PARAMS
    if action == "office_control":
        try:
            import office_control
            return office_control.is_risky_parameter(step.get("parameter"))
        except Exception:
            return True
    return False

# Register in sys.modules["akira"] if akira is not loaded, so action_router & guard_rules find it
if "akira" not in sys.modules:
    _akira_stub = types.ModuleType("akira")
    _akira_stub._is_dangerous_step = _is_dangerous_step
    sys.modules["akira"] = _akira_stub

try:
    import claude_handler
    import llm_json
    import action_router
    import executor
    import tiers
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

def main():
    print("=========================================================")
    print(" 🤖 AKIRA TEXT BENCHMARK & INTERACTION CLI (OPTIMIZED)")
    print("=========================================================")
    print(" * Head Router: OpenRouter High-Speed Endpoint")
    print(" * Local Engines: Guard (LoRA 0), API (LoRA 1), Mech (LoRA 2) on port 8081")
    print(" Type your command and press Enter (or 'quit' to exit).\n")

    try:
        summary = tiers.summary()
        print(f" [Tiers] Head: {summary['head']}")
        print(f" [Tiers] Servant: {summary['servant']}\n")
    except Exception:
        pass

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("Exiting Akira CLI.")
                break

            print("\n🤔 [1/3] Routing intent...")
            start_time = time.time()
            
            try:
                raw_reply = claude_handler.ask_akira(user_input, skip_context=True)
            except TypeError:
                raw_reply = claude_handler.ask_akira(user_input)
            if not (raw_reply or "").strip():
                print("❌ Empty response from Head router.")
                continue

            response_json, info = llm_json.parse(raw_reply)
            elapsed_head = (time.time() - start_time) * 1000
            
            if not response_json:
                print(f"❌ Failed to parse router output: {raw_reply[:200]}")
                continue

            mode = response_json.get("mode")
            print(f"⚡ [2/3] Mode: {mode.upper()} ({elapsed_head:.1f}ms)")

            if mode == "conversation":
                reply_text = response_json.get("response", "")
                print(f"\n🗣️ Akira: {reply_text}")

            elif mode == "command":
                # Support both single-action and multi-action JSON formats
                actions = []
                if response_json.get("action"):
                    actions.append({
                        "action": response_json.get("action"),
                        "parameter": response_json.get("parameter")
                    })
                if response_json.get("actions"):
                    actions.extend(response_json.get("actions"))

                print(f"📋 Actions Identified ({len(actions)}): {actions}")
                
                reply_spoken = response_json.get("response")
                if reply_spoken:
                    print(f"🗣️ Akira: {reply_spoken}")

                for act in actions:
                    action_name = act.get("action")
                    try:
                        from gemini_head import ACTION_ALIASES
                        action_name = ACTION_ALIASES.get(action_name, action_name)
                    except Exception:
                        pass
                    param = act.get("parameter")
                    print(f"\n🛡️ [3/3] Screening '{action_name}' through Local Guard...")

                    guard_start = time.time()
                    step_obj = {"action": action_name, "parameter": param}

                    # Capture action/param in closure
                    def make_exec(a, p):
                        return lambda: executor.execute(a, p)
                    _exec = make_exec(action_name, param)

                    outcome = action_router.run_guarded(step_obj, _exec)
                    guard_elapsed = (time.time() - guard_start) * 1000

                    verdict_str = outcome.verdict.decision.upper()
                    print(f"   Verdict: {verdict_str} ({guard_elapsed:.1f}ms)")
                    if outcome.verdict.reasons:
                        print(f"   Reasons: {'; '.join(outcome.verdict.reasons)}")

                    if outcome.executed:
                        print(f"✅ Executed {action_name} successfully!")
                        if outcome.result:
                            print(f"   Result: {outcome.result}")

                    elif outcome.verdict.decision == "block":
                        print(f"🚫 Action BLOCKED by Guard — not running.")

                    else:
                        # FLAG: gated or dangerous step. Always ask user confirmation.
                        reasons_str = '; '.join(outcome.verdict.reasons) if outcome.verdict.reasons else "Guard flagged this action."
                        router_conf_msg = response_json.get("confirmation_message")
                        prompt_msg = router_conf_msg or f"Guard flagged: {reasons_str}"
                        print(f"\n❓ Confirmation Required: {prompt_msg}")
                        confirm_input = input("   Approve execution? [y/N]: ").strip().lower()
                        if confirm_input in ("y", "yes"):
                            print(f"🚀 Executing confirmed action '{action_name}'...")
                            confirm_outcome = action_router.run_guarded(step_obj, _exec, confirmed=True)
                            if confirm_outcome.executed:
                                print(f"✅ Done!")
                                if confirm_outcome.result:
                                    print(f"   Result: {confirm_outcome.result}")
                            else:
                                print(f"🚫 Guard blocked even after confirmation.")
                        else:
                            print("   Action cancelled.")

        except KeyboardInterrupt:
            print("\nExiting Akira CLI.")
            break
        except Exception as e:
            print(f"\n❌ Error during execution: {e}")

if __name__ == "__main__":
    main()
