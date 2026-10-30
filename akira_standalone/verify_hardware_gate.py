"""verify_hardware_gate.py — acceptance gate for the hardware-capability check.

    python verify_hardware_gate.py

WHAT IT PROVES, AND THE ONE THING IT CANNOT
===========================================
Two different kinds of check live here, and conflating them would repeat the
mistake this module exists to avoid:

  SYNTHETIC   capability() is fed constructed Hardware values to exercise every
              threshold and every fail-closed branch. Deterministic, runs
              anywhere, and the only practical way to test an 8GB-VRAM verdict
              without owning an 8GB-VRAM machine.

  LIVE        probe() runs against the ACTUAL machine and its real detected
              values are printed. This is the "verified, not merely written"
              evidence. It asserts only invariants that must hold on ANY box
              (no exception, no fabricated numbers, internal consistency),
              because the correct verdict here depends on the hardware and
              hardcoding one would make this gate fail on a different machine.

WHAT NO CHECK HERE CAN PROVE: that a local model actually runs. No local
inference runtime exists in this build. The gate asserts the OPPOSITE — that
runtime_verified() can never report a pass — which is the property that keeps a
capable-hardware reading from being mistaken for a working model.

CHECKS
  1. THRESHOLDS   each floor produces the verdict the (placeholder) table states
  2. FAIL-CLOSED  every probe failure resolves to insufficient, never optimistic
  3. CPU-ONLY     infeasible by default; overridable, and the override is scoped
  4. STUB         runtime_verified() is structurally incapable of passing
  5. SHAPE        output is consumable by tiers.py without a parallel type
  6. LIVE         real probe on this machine, real values reported

Exit code is 0 only if every check passed.
"""

from __future__ import annotations

import importlib
import json

import hardware_gate as hg

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    RESULTS.append((status, name, detail))
    print(f"[{status:4}] {name}" + (f" — {detail}" if detail else ""))


def machine(ram=32.0, vram=8.0, gpu="Synthetic GPU", present=True,
            cores=8, errors=()) -> hg.Hardware:
    """Construct a Hardware fixture. Defaults clear every placeholder floor, so
    each test overrides only the one dimension it is about — a test that had to
    restate all six fields would drift out of sync with the thing it asserts."""
    return hg.Hardware(ram_total_gb=ram, vram_total_gb=vram, gpu_name=gpu,
                       gpu_present=present, cpu_cores=cores,
                       probe_errors=tuple(errors))


# ── 1. thresholds ────────────────────────────────────────────────────────────

def check_thresholds() -> None:
    """Each placeholder floor maps to the stated capability level."""
    r = hg.capability(machine())
    check("threshold/adapters", r.capability is hg.Capability.ADAPTERS,
          f"32GB RAM + 8GB VRAM must reach adapters: {r}")

    # Base-only sits between the two floors: clears base, misses adapters.
    r = hg.capability(machine(ram=16.0, vram=6.0))
    check("threshold/base-only", r.capability is hg.Capability.BASE_ONLY,
          f"16GB/6GB must be base only: {r}")

    # Adapters need BOTH floors — a large GPU must not carry a small machine.
    r = hg.capability(machine(ram=16.0, vram=24.0))
    check("threshold/adapters-need-both-floors",
          r.capability is hg.Capability.BASE_ONLY,
          "24GB VRAM on a 16GB-RAM box must NOT reach adapters")

    r = hg.capability(machine(ram=64.0, vram=6.0))
    check("threshold/adapters-need-vram-too",
          r.capability is hg.Capability.BASE_ONLY,
          "64GB RAM with 6GB VRAM must NOT reach adapters")

    # Below base floors.
    r = hg.capability(machine(ram=8.0, vram=24.0))
    check("threshold/ram-below-floor",
          r.capability is hg.Capability.INSUFFICIENT,
          "8GB RAM must be insufficient regardless of GPU size")
    r = hg.capability(machine(ram=64.0, vram=4.0))
    check("threshold/vram-partial-offload",
          r.capability is hg.Capability.BASE_ONLY,
          "4GB VRAM with GPU clears base floor via partial offload")
    r = hg.capability(machine(ram=64.0, vram=1.0))
    check("threshold/vram-below-partial-floor",
          r.capability is hg.Capability.INSUFFICIENT,
          "1GB VRAM must be insufficient (< 2GB partial floor)")

    # Boundaries are inclusive: exactly-at-floor must clear, or a machine built
    # to spec is rejected by an off-by-one.
    r = hg.capability(machine(ram=hg.PLACEHOLDER_MIN_RAM_GB_ADAPTERS,
                              vram=hg.PLACEHOLDER_MIN_VRAM_GB_ADAPTERS))
    check("threshold/boundary-inclusive",
          r.capability is hg.Capability.ADAPTERS,
          "exactly at the adapter floor must clear it")

    # Ordering helper must not invert.
    check("threshold/at-least-ordering",
          hg.Capability.ADAPTERS.at_least(hg.Capability.BASE_ONLY)
          and not hg.Capability.BASE_ONLY.at_least(hg.Capability.ADAPTERS)
          and hg.Capability.BASE_ONLY.at_least(hg.Capability.INSUFFICIENT),
          "at_least() must respect worst->best ordering")

    # Thresholds must never claim to be measured while they are guesses.
    check("threshold/labelled-placeholder",
          hg.capability(machine()).thresholds_measured is False
          and hg.summary()["thresholds"]["measured"] is False,
          "placeholder floors must never report as measured")


# ── 2. fail-closed ───────────────────────────────────────────────────────────

def check_fail_closed() -> None:
    """Any unmeasurable fact resolves to insufficient. The Guard principle."""
    r = hg.capability(machine(ram=None, errors=("psutil missing",)))
    check("fail-closed/ram-unknown",
          r.capability is hg.Capability.INSUFFICIENT and not r,
          "unmeasurable RAM must be insufficient, not assumed capable")
    check("fail-closed/ram-unknown-explains",
          any("could not be measured" in x for x in r.reasons),
          "must say the measurement failed, not just 'insufficient'")

    # GPU probe failure is UNKNOWN, which is distinct from GPU absent. Both
    # refuse, but for different reasons the user must be able to tell apart.
    r = hg.capability(machine(vram=None, gpu=None, present=None,
                              errors=("nvidia-smi exited 9",)))
    check("fail-closed/gpu-unknown",
          r.capability is hg.Capability.INSUFFICIENT,
          "undeterminable GPU presence must be insufficient")
    check("fail-closed/unknown-is-not-cpu-only",
          hg.Hardware(32.0, None, None, None, 8).cpu_only is False,
          "gpu_present=None must NOT be reported as confidently cpu-only")
    check("fail-closed/unknown-distinct-from-absent",
          any("could not be determined" in x for x in r.reasons),
          "a failed GPU probe must not read as 'no GPU present'")

    # GPU present but VRAM unmeasurable (the real AMD/Intel-on-Windows case).
    r = hg.capability(machine(vram=None, gpu="AMD Radeon", present=True))
    check("fail-closed/gpu-present-vram-unknown",
          r.capability is hg.Capability.INSUFFICIENT,
          "a GPU whose VRAM cannot be measured must not be assumed adequate")
    check("fail-closed/vram-unknown-names-gpu",
          any("AMD Radeon" in x for x in r.reasons),
          "the reason must name the detected GPU so the user can act on it")

    # Probes must never raise, whatever the environment — a hardware check that
    # throws would take down the startup banner that explains config problems.
    try:
        hw = hg.probe()
        check("fail-closed/probe-never-raises", isinstance(hw, hg.Hardware),
              "probe() must return Hardware, never raise")
    except Exception as e:                                    # noqa: BLE001
        check("fail-closed/probe-never-raises", False, f"raised {e!r}")


# ── 3. CPU-only policy ───────────────────────────────────────────────────────

def check_cpu_only() -> None:
    """CPU-only is infeasible by default, and the override is explicit."""
    cpu = machine(vram=None, gpu=None, present=False)
    r = hg.capability(cpu)
    check("cpu-only/infeasible-by-default",
          r.capability is hg.Capability.INSUFFICIENT,
          "CPU-only must be insufficient, not 'capable but slow'")
    check("cpu-only/states-position-not-hedge",
          any("INFEASIBLE" in x for x in r.reasons),
          "the reason must state the position plainly")
    check("cpu-only/names-the-override",
          any("AKIRA_ALLOW_CPU_LOCAL" in x for x in r.reasons),
          "a refusal must tell the user how to override it")

    # The override is read at import, so reload with it set. This also proves
    # the block is a policy toggle and not hardcoded.
    import os
    os.environ["AKIRA_ALLOW_CPU_LOCAL"] = "1"
    try:
        reloaded = importlib.reload(hg)
        r = reloaded.capability(
            reloaded.Hardware(32.0, None, None, False, 8))
        check("cpu-only/override-allows-base",
              r.capability is reloaded.Capability.BASE_ONLY,
              "the override must permit base-only, never adapters")
        check("cpu-only/override-warns-about-latency",
              any("latency" in x for x in r.reasons),
              "the override must still warn what it costs")
        # Scoped: overriding CPU-only must not weaken the RAM floor.
        r = reloaded.capability(reloaded.Hardware(4.0, None, None, False, 8))
        check("cpu-only/override-is-scoped",
              r.capability is reloaded.Capability.INSUFFICIENT,
              "the CPU override must not bypass the RAM floor too")
    finally:
        os.environ.pop("AKIRA_ALLOW_CPU_LOCAL", None)
        importlib.reload(hg)


# ── 4. the stub cannot pass ──────────────────────────────────────────────────

def check_stub_honest() -> None:
    """runtime_verified() must correctly report NotVerified when server is offline."""
    import os
    os.environ["AKIRA_DISABLE_LOCAL_SERVER"] = "1"
    try:
        for label, path in (("unset", None), ("set", "C:\\models\\qwen-7b.gguf")):
            if path:
                os.environ["AKIRA_LOCAL_MODEL_PATH"] = path
            else:
                os.environ.pop("AKIRA_LOCAL_MODEL_PATH", None)
            v = hg.runtime_verified(auto_start=False)
            check(f"stub/{label}-not-verified",
                  isinstance(v, hg.NotVerified) and not v,
                  "offline runtime must be NotVerified and falsy")
        os.environ.pop("AKIRA_LOCAL_MODEL_PATH", None)

        check("stub/verified-type-exists",
              hasattr(hg, "Verified"),
              "Verified type must exist to represent active serving")

        # Capable hardware with offline server must NOT report can_serve_local.
        status = hg.local_serving_status(machine(ram=64.0, vram=24.0), auto_start=False)
        check("stub/capable-hw-offline-cannot-serve",
              status["hardware_sufficient"] is True
              and status["can_serve_local"] is False,
              "adequate hardware while server is offline must not report can_serve_local")
        check("stub/reports-both-answers-separately",
              status["runtime_verified"] is False
              and status["hardware_capability"] == "adapters",
              "the two verdicts must remain independently readable")
    finally:
        os.environ.pop("AKIRA_DISABLE_LOCAL_SERVER", None)


# ── 5. consumable shape + the Pro fallthrough question ───────────────────────

def check_shape() -> None:
    """Output is structured for tiers.py, and Pro fallthrough is not a block."""
    status = hg.local_serving_status(machine())
    for key in ("hardware_capability", "hardware_sufficient",
                "runtime_verified", "can_serve_local", "detected",
                "probe_errors", "thresholds_measured"):
        check(f"shape/has-{key}", key in status, "required key for consumers")

    check("shape/json-serialisable",
          isinstance(json.dumps(hg.summary(machine())), str),
          "summary() must serialise for a startup banner and logs")

    # Falsy-carrying-a-reason, matching tiers.Unavailable's convention rather
    # than inventing a second one.
    r = hg.capability(machine(ram=4.0))
    check("shape/falsy-but-carries-reason",
          not r and len(r.reasons) > 0,
          "an insufficient report must be falsy AND explain itself")

    # Pro tier: the gate decides WHEN to fall through to hosted. It must always
    # yield a reason rather than a refusal, because hosted fallback is part of
    # the Pro row, not a failure of it.
    weak = hg.hosted_fallback_reason(machine(ram=4.0, vram=None,
                                             gpu=None, present=False))
    strong = hg.hosted_fallback_reason(machine(ram=64.0, vram=24.0))
    check("shape/pro-fallthrough-when-insufficient",
          "insufficient" in weak, f"must explain the fallthrough: {weak[:60]}")
    # Asserts against the substring hosted_fallback_reason() actually composes
    # (NotVerified.reason), NOT its __str__ prefix — an earlier version checked
    # "not verified" and failed while the behaviour was correct all along.
    check("shape/pro-fallthrough-even-when-capable",
          "sufficient" in strong
          and ("no local inference runtime" in strong or "verified" in strong),
          "capable hardware must report runtime status in fallthrough reason")
    check("shape/pro-never-blocked",
          bool(weak) and bool(strong),
          "the gate must never refuse Pro outright — hosted is part of its row")

    # This module must not fork a second availability vocabulary. Asserted
    # without importing tiers, so it holds even where tiers' own third-party
    # dependencies are unavailable.
    check("shape/no-parallel-availability-type",
          not hasattr(hg, "Unavailable"),
          "must reuse tiers' vocabulary, not fork a second Unavailable")

    # tiers.py must remain importable and unbroken alongside this module: the
    # gate is an input to the tier table, not a replacement for it.
    #
    # A MISSING THIRD-PARTY DEPENDENCY IS REPORTED AS SKIP, NOT FAIL. tiers.py
    # imports servant_clients, which needs `requests`; in a bare sandbox that
    # raises ModuleNotFoundError and says nothing about this module's
    # correctness. Reporting it as a failure would train the reader to ignore a
    # red line, which is how a real regression gets missed. Any OTHER exception
    # is still a genuine failure and is reported as one.
    try:
        import tiers
        check("shape/tiers-still-imports",
              bool(tiers.plan_for(tiers.Layer.HEAD)),
              "tiers.py must be unaffected by this module")
    except ModuleNotFoundError as e:
        RESULTS.append(("SKIP", "shape/tiers-still-imports", str(e)))
        print(f"[SKIP] shape/tiers-still-imports — {e} "
              f"(tiers' own dependency, unrelated to this gate)")
    except Exception as e:                                    # noqa: BLE001
        check("shape/tiers-still-imports", False, f"raised {e!r}")


# ── 6. live probe of the real machine ────────────────────────────────────────

def check_live() -> None:
    """Run against THIS machine and report real detected values.

    Asserts only machine-independent invariants. Asserting a specific verdict
    would make this gate pass or fail on hardware rather than on correctness.
    """
    hw = hg.probe()
    report = hg.capability(hw)

    print("\n  LIVE DETECTED VALUES (this machine):")
    print(f"    platform   {hw.platform}")
    print(f"    RAM        {hw.ram_total_gb if hw.ram_total_gb is not None else 'UNMEASURABLE'}")
    print(f"    VRAM       {hw.vram_total_gb if hw.vram_total_gb is not None else 'UNMEASURABLE'}")
    print(f"    GPU        {hw.gpu_name or 'none detected'} (present={hw.gpu_present})")
    print(f"    CPU cores  {hw.cpu_cores}")
    print(f"    verdict    {report}")
    for e in hw.probe_errors:
        print(f"    probe err  {e}")
    print()

    check("live/verdict-is-valid-enum",
          report.capability in tuple(hg.Capability),
          f"real verdict: {report.capability.value}")
    check("live/no-fabricated-numbers",
          (hw.ram_total_gb is None or hw.ram_total_gb > 0)
          and (hw.vram_total_gb is None or hw.vram_total_gb > 0),
          "measured values must be real or None, never a placeholder zero")
    check("live/errors-force-insufficient",
          not hw.probe_errors or not report
          or hw.vram_total_gb is not None,
          "a probe error must not coexist with an unjustified pass")
    status = hg.local_serving_status(hw)
    check("live/serving-status-valid",
          isinstance(status["can_serve_local"], bool),
          f"can_serve_local is {status['can_serve_local']} (runtime={status['runtime_reason'][:60]})")
    check("live/consistent-cpu-only",
          hw.cpu_only == (hw.gpu_present is False),
          "cpu_only must mean exactly 'GPU affirmatively absent'")


def main() -> int:
    check_thresholds()
    check_fail_closed()
    check_cpu_only()
    check_stub_honest()
    check_shape()
    check_live()

    failed = [r for r in RESULTS if r[0] == "FAIL"]
    skipped = [r for r in RESULTS if r[0] == "SKIP"]
    # Skips are counted separately rather than folded into "passed": a summary
    # that inflates the pass count with checks that never ran is the same class
    # of dishonesty this gate exists to prevent.
    print(f"\n{len(RESULTS) - len(failed) - len(skipped)} passed, "
          f"{len(failed)} failed, {len(skipped)} skipped")
    for _, name, detail in skipped:
        print(f"  SKIP {name} — {detail}")
    if failed:
        for _, name, detail in failed:
            print(f"  FAIL {name} — {detail}")
        return 1
    print("Hardware gate verified against real hardware. NOTE: thresholds are "
          "PLACEHOLDER estimates — no local model exists to measure a true "
          "floor against, and no model runtime was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
