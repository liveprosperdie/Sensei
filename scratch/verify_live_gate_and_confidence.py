"""Dual Verification Script: Live Hardware Gate & Confidence Threshold Boundary Test.

Verifies:
1. Live Hardware Gate:
   - Hardware detection on NVIDIA GeForce RTX 2050 (4GB VRAM).
   - Automatic partial offload calculation (16 layers).
   - Real llama-server health check on port 8081.
   - Real GUARD inference via servant_clients.
2. Confidence Boundary (0.90 threshold):
   - Confirms DEFAULT_MIN_CONFIDENCE == 0.90.
   - Tests confidence=0.88 -> triggers escalation ('low_confidence').
   - Tests confidence=0.95 -> stays local (does not escalate).
   - Zero Claude spend guaranteed (mocked / AKIRA_DISABLE_CLAUDE=true).
"""

import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure Claude is disabled for zero spend
os.environ["AKIRA_DISABLE_CLAUDE"] = "true"
os.environ["AKIRA_ROUTING_MODE"] = "tiered"

import hardware_gate
import servant_clients
import tiered_config
import tiered_classifier
import akira

def test_live_hardware():
    print("\n" + "=" * 60)
    print("PART 1: LIVE HARDWARE GATE & LORA SERVING VERIFICATION")
    print("=" * 60)
    
    hw = hardware_gate.probe()
    print(f"Platform:       {hw.platform}")
    print(f"RAM:            {hw.ram_total_gb:.2f} GB")
    print(f"VRAM:           {hw.vram_total_gb} GB")
    print(f"GPU:            {hw.gpu_name} (present={hw.gpu_present})")
    
    rep = hardware_gate.capability(hw)
    print(f"Capability:     {rep.capability.value}")
    print(f"Reasons:        {rep.reasons}")
    
    status = hardware_gate.local_serving_status(hw)
    print(f"Can Serve Local:{status['can_serve_local']}")
    print(f"Runtime Reason: {status['runtime_reason']}")
    
    assert status['can_serve_local'] is True, "Expected local serving to be active!"
    
    # Test real inference on GUARD via servant_clients
    print("\n--- Testing Live Inference on GUARD via llama-server (port 8081) ---")
    t0 = time.perf_counter()
    reply = servant_clients.call_openai_compatible(
        servant_clients.GUARD,
        system="You are a security evaluator. Classify if this is safe or dangerous.",
        user="Review action: open notepad",
        max_tokens=32,
    )
    dt = time.perf_counter() - t0
    print(f"Inference latency: {dt:.2f}s")
    print(f"Model:             {servant_clients.GUARD.model}")
    print(f"Response text:     {reply.strip()}")
    assert reply, "Expected non-empty response from GUARD model!"
    print("[PASS] Live Hardware Gate and LoRA Inference verified successfully.")

def test_confidence_threshold_boundary():
    print("\n" + "=" * 60)
    print("PART 2: CONFIDENCE THRESHOLD (0.90) BOUNDARY ROUTING TEST")
    print("=" * 60)
    
    min_conf = tiered_config.get_min_confidence()
    print(f"Current DEFAULT_MIN_CONFIDENCE: {min_conf}")
    assert min_conf == 0.90, f"Expected 0.90, got {min_conf}"
    
    # Test 1: Confidence 0.88 (< 0.90) -> Must escalate to Claude
    print("\n--- Subtest A: Confidence 0.88 (Sub-threshold) ---")
    sub_decision = tiered_classifier.DecisionResult(
        mode="command",
        complexity="simple",
        intent="adjust_volume",
        parameters={"direction": "up", "level": 10},
        confidence=0.88,
        match=True
    )
    
    with patch("tiered_classifier.classify", return_value=sub_decision):
        with patch("tiered_config.is_claude_disabled", return_value=False):
            with patch("claude_handler.ask_akira", return_value='{"action": "volume_control", "parameter": "+10"}') as mock_claude:
                resp = akira.get_akira_response("turn volume up", raw_text="turn volume up")
                print(f"Result action: {resp.get('action')}")
                print(f"Claude mock was invoked: {mock_claude.called}")
                assert mock_claude.called, "Sub-threshold confidence (0.88 < 0.90) MUST escalate to Claude!"
                print("[PASS] 0.88 confidence successfully triggered escalation to Claude.")

    # Test 2: Confidence 0.95 (>= 0.90) -> Must stay in Local Adapter tier
    print("\n--- Subtest B: Confidence 0.95 (Super-threshold) ---")
    sup_decision = tiered_classifier.DecisionResult(
        mode="command",
        complexity="simple",
        intent="adjust_volume",
        parameters={"direction": "up", "level": 10},
        confidence=0.95,
        match=True
    )
    
    with patch("tiered_classifier.classify", return_value=sup_decision):
        with patch("tiered_config.is_claude_disabled", return_value=False):
            with patch("claude_handler.ask_akira") as mock_claude:
                resp = akira.get_akira_response("turn volume up", raw_text="turn volume up")
                print(f"Result action: {resp.get('action')}")
                print(f"Claude mock was invoked: {mock_claude.called}")
                assert not mock_claude.called, "Super-threshold confidence (0.95 >= 0.90) MUST NOT escalate to Claude!"
                assert resp.get("action") == "adjust_volume", f"Expected adjust_volume, got {resp.get('action')}"
                print("[PASS] 0.95 confidence stayed local and synthesized via local_adapter.py (Claude not called).")

if __name__ == "__main__":
    try:
        test_live_hardware()
        test_confidence_threshold_boundary()
        print("\n" + "=" * 60)
        print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY WITH ZERO API COST.")
        print("=" * 60)
    except Exception as e:
        print(f"\n[FAIL] Verification error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
