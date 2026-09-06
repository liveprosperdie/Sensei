"""Hardware-capability gate for local model inference.

WHAT THIS IS
============
Answers ONE question about the machine Akira is running on right now: does this
box have the physical resources to run a local model at all, and if so, at which
capability level (base model only, or base + fine-tuned LoRA adapters).

It is a real, working check. RAM, VRAM, GPU presence and CPU-only detection are
all properties of the hardware and do not depend on any model file existing, so
they are measurable today and this module measures them.

WHAT THIS DELIBERATELY IS NOT
=============================
This does NOT answer "will model X actually run acceptably on this machine".
That question requires a local inference runtime and a fine-tuned adapter, and
neither exists in this build. Conflating the two would produce the exact failure
this codebase keeps refusing to ship: a gate that reports a pass because the
hardware looked fine, while the thing it supposedly cleared was never run.

So the two live in separate functions with separate return types:

    capability()        REAL. Measured hardware facts + a capability verdict.
    runtime_verified()  HONEST STUB. Always NotVerified — no runtime exists.

A caller that needs to know "can we actually serve a local request" must consult
BOTH, and `local_serving_status()` composes them so no call site has to remember
that. There is no code path in this module that returns "verified" for a model.

WHY THE THRESHOLDS ARE LABELLED PLACEHOLDERS
============================================
The resource floors below are named PLACEHOLDER_* on purpose. No local model or
adapter exists in this project yet, so no floor has been MEASURED — these are
reasoned estimates from published quantised-model footprints, not numbers
observed on Akira's own workload. Presenting them as measured would be false
precision that outlives the guess: someone would later tune behaviour against a
number nobody ever validated.

Every threshold is env-overridable so the floors can be corrected from a real
measurement without a code change, and `capability()` reports
`thresholds_measured=False` so a consumer can tell the verdict rests on
estimates.

WHY CPU-ONLY IS TREATED AS INFEASIBLE, NOT "SLOW"
=================================================
Stated plainly because the brief asks for a position rather than a hedge:
CPU-only is reported as INFEASIBLE for local inference.

The reasoning is specific to this product, not a general claim about CPU
inference. Akira is a VOICE assistant. The model sits directly in the latency
path between "user stopped speaking" and "Akira starts replying". CPU-only
inference on a 7B-class quantised model runs at roughly single-digit tokens per
second on typical consumer hardware, which puts even a short spoken reply tens
of seconds away. At that latency a voice turn is not a slow conversation, it is
a broken feature — the user has already repeated themselves or given up. A
background batch job can absorb that cost; a spoken turn cannot.

The counter-argument, fairly stated: for a long-running background task where
nobody is waiting on the reply, CPU-only inference would be genuinely usable,
and treating it as infeasible loses that. That is a real cost of this choice,
which is why AKIRA_ALLOW_CPU_LOCAL=1 exists to override it. The default stays
infeasible because the default path is the voice path.

FAIL-CLOSED, SAME AS GUARD
==========================
If a hardware probe itself fails — no psutil, nvidia-smi missing, WMI permission
error, a driver that returns garbage — the result is INSUFFICIENT with the probe
error recorded, never an optimistic assumption. A gate that guesses "probably
capable" when it could not measure is worse than no gate: it produces a failure
at model-load time, far from the missing probe that caused it.

RELATIONSHIP TO tiers.py
========================
This module knows nothing about tiers, exactly as reliability.py knows nothing
about tiers. It reports hardware facts; tiers.py decides what they mean for a
plan. That separation is what keeps the Pro fallthrough decision (below) from
being reimplemented here in a second, divergent form.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum

# ── Capability levels ────────────────────────────────────────────────────────


class Capability(str, Enum):
    """What local work this machine can support.

    Ordered worst -> best. `at_least()` relies on that ordering rather than
    callers comparing enum members by hand, which is how a "is this good enough"
    check silently inverts.
    """
    INSUFFICIENT = "insufficient"   # cannot run a local model at all
    BASE_ONLY = "base_only"         # base local model, no adapters
    ADAPTERS = "adapters"           # base + fine-tuned LoRA adapters

    def at_least(self, other: "Capability") -> bool:
        order = (Capability.INSUFFICIENT, Capability.BASE_ONLY,
                 Capability.ADAPTERS)
        return order.index(self) >= order.index(other)


# ── Placeholder thresholds ───────────────────────────────────────────────────
# GUESSES, NOT MEASUREMENTS. See module docstring. Named PLACEHOLDER_* so no
# reader mistakes them for validated figures, and env-overridable so a real
# measurement replaces them without touching this file.
#
# Reasoning behind each estimate, so the next person can argue with it:
#
# VRAM 6 GB base   — a 7B-class model at 4-bit quantisation occupies ~4-4.5 GB
#                    of weights, plus KV cache and context. 6 GB is the first
#                    common consumer VRAM size that fits that with headroom.
# VRAM 8 GB adapt. — LoRA adapters add their own weights and, more importantly,
#                    adapter-swapping wants room for more than one resident at a
#                    time. 8 GB is the next standard tier up.
# RAM 16 GB        — the model is not the only thing on this machine. Akira
#                    already holds Whisper, Silero VAD and openWakeWord
#                    resident, and it runs alongside whatever the user is
#                    actually doing. 8 GB total would mean competing with the
#                    user's own applications for memory.
# RAM 32 GB adapt. — same logic, one tier up, matching the VRAM step.

PLACEHOLDER_MIN_VRAM_GB_BASE = float(
    os.environ.get("AKIRA_MIN_VRAM_GB", "6"))
PLACEHOLDER_MIN_VRAM_GB_ADAPTERS = float(
    os.environ.get("AKIRA_MIN_VRAM_GB_ADAPTERS", "8"))
PLACEHOLDER_MIN_RAM_GB_BASE = float(
    os.environ.get("AKIRA_MIN_RAM_GB", "16"))
PLACEHOLDER_MIN_RAM_GB_ADAPTERS = float(
    os.environ.get("AKIRA_MIN_RAM_GB_ADAPTERS", "32"))

# See "WHY CPU-ONLY IS TREATED AS INFEASIBLE" above.
ALLOW_CPU_LOCAL = (os.environ.get("AKIRA_ALLOW_CPU_LOCAL", "")
                   or "").strip().lower() in ("1", "true", "yes", "on")

# Probes shell out to vendor tools. A hung driver query must not hang the voice
# loop, so every subprocess call is bounded.
_PROBE_TIMEOUT_S = 5


# ── Measured facts ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Hardware:
    """What was actually measured. Every field distinguishes 'measured zero'
    from 'could not measure' by using None for the latter — collapsing those
    into 0.0 would make an unreadable GPU indistinguishable from no GPU, and
    those need different remedies from the user.
    """
    ram_total_gb: float | None
    vram_total_gb: float | None
    gpu_name: str | None
    gpu_present: bool | None      # None = could not determine
    cpu_cores: int | None
    platform: str = field(default_factory=lambda: sys.platform)

    # Probe failures, human-readable. Non-empty means at least one fact below
    # is unknown, which forces the fail-closed path in capability().
    probe_errors: tuple[str, ...] = ()

    @property
    def cpu_only(self) -> bool:
        """True only when a GPU was AFFIRMATIVELY determined absent.

        `gpu_present is None` (probe failed) is NOT cpu_only — it is unknown,
        and unknown must not be reported as a confident hardware shape.
        """
        return self.gpu_present is False


@dataclass(frozen=True)
class CapabilityReport:
    """The gate's real output: a verdict plus the evidence behind it.

    Carries `thresholds_measured` so a consumer can see the verdict rests on
    placeholder floors, and `reasons` so a refusal can be explained to a user
    instead of being a bare boolean.
    """
    capability: Capability
    hardware: Hardware
    reasons: tuple[str, ...]
    thresholds_measured: bool = False

    def __bool__(self) -> bool:
        """Truthy when the machine can run SOMETHING locally.

        Matches the Unavailable/spec convention in tiers.py, where falsy means
        'cannot serve' and the object still carries the reason why.
        """
        return self.capability is not Capability.INSUFFICIENT

    def __str__(self) -> str:
        hw = self.hardware
        bits = [
            f"RAM {hw.ram_total_gb:.1f}GB" if hw.ram_total_gb
            else "RAM unknown",
            f"VRAM {hw.vram_total_gb:.1f}GB" if hw.vram_total_gb
            else ("no GPU" if hw.cpu_only else "VRAM unknown"),
        ]
        return (f"{self.capability.value} ({', '.join(bits)})"
                + (" [placeholder thresholds]"
                   if not self.thresholds_measured else ""))


# ── Probes ───────────────────────────────────────────────────────────────────
# Each probe returns (value, error). Never raises: a probe that throws would
# take down the startup banner that exists to explain configuration problems.


def _probe_ram() -> tuple[float | None, str | None]:
    """Total physical RAM in GB via psutil.

    psutil is already a hard dependency (requirements.txt, used by
    system_control.py and executor.py) so this is not a new import burden. It is
    still guarded, because this module must stay importable on a machine where
    the dependency install partially failed — that is exactly when a diagnostic
    banner is most needed.
    """
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3), None
    except ImportError:
        return None, ("psutil is not installed, so total RAM cannot be "
                      "measured (it is in requirements.txt — the install may "
                      "have failed)")
    except OSError as e:
        return None, f"RAM probe failed: {e}"


def _probe_cpu_cores() -> tuple[int | None, str | None]:
    """Logical core count. os.cpu_count() needs no third-party dependency, so
    this survives a missing psutil and is worth reporting on its own."""
    try:
        return os.cpu_count(), None
    except OSError as e:
        return None, f"CPU probe failed: {e}"


def _probe_nvidia() -> tuple[float | None, str | None, str | None]:
    """NVIDIA VRAM via nvidia-smi -> (vram_gb, gpu_name, error).

    nvidia-smi rather than pynvml/torch deliberately: it ships with every NVIDIA
    driver, so it needs no new Python dependency and no CUDA toolchain. torch is
    imported by akira.py but is the wrong probe here — torch.cuda reports what
    THAT torch build was compiled to see, so a CPU-only wheel reports no GPU on
    a machine that has one, which is a false negative from the tool rather than
    a fact about the hardware.

    Absence of nvidia-smi is NOT an error. It is the normal state of an AMD,
    Intel or GPU-less machine, and reporting it as a probe failure would push
    every such machine down the fail-closed unknown path instead of the correct
    "no NVIDIA GPU" answer.
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, None, None

    try:
        out = subprocess.run(
            [exe, "--query-gpu=memory.total,name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S,
            check=False)
    except (OSError, subprocess.SubprocessError) as e:
        # Present but unusable — a real failure, unlike simple absence. Driver
        # mismatch and permission errors land here.
        return None, None, f"nvidia-smi present but failed: {e}"

    if out.returncode != 0:
        return None, None, (f"nvidia-smi exited {out.returncode}: "
                            f"{(out.stderr or '').strip()[:120]}")

    # Multi-GPU: take the LARGEST single GPU, not the sum. A model must fit in
    # one device's memory; two 4 GB cards are not one 8 GB card, and summing
    # them would manufacture capability that does not exist.
    best_mib, best_name = 0.0, None
    for line in (out.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            mib = float(parts[0])
        except ValueError:
            continue
        if mib > best_mib:
            best_mib, best_name = mib, parts[1]

    if not best_mib:
        return None, None, ("nvidia-smi returned no parseable GPU memory: "
                            f"{(out.stdout or '').strip()[:120]}")
    return best_mib / 1024.0, best_name, None


def _probe_windows_gpu() -> tuple[str | None, str | None]:
    """Non-NVIDIA GPU presence on Windows -> (gpu_name, error).

    Answers only "is there a display adapter at all", which is what separates
    cpu_only from "has a GPU this build cannot size". It deliberately does not
    try to read VRAM: the WMI AdapterRAM field is a well-known liar, capped at
    4 GB by its uint32 type and often reporting shared system memory on
    integrated graphics. A wrong VRAM number is worse than no number here,
    because the whole point of the gate is that the number is trustworthy.

    PowerShell rather than the `wmi` package because it needs no dependency;
    this codebase already uses subprocess for Windows shell-outs elsewhere.
    """
    if not sys.platform.startswith("win"):
        return None, None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S,
            check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"Windows GPU probe failed: {e}"
    if out.returncode != 0:
        return None, (f"Windows GPU probe exited {out.returncode}: "
                      f"{(out.stderr or '').strip()[:120]}")
    names = [n.strip() for n in (out.stdout or "").splitlines() if n.strip()]
    return (names[0] if names else None), None


def probe() -> Hardware:
    """Run every probe and collect facts plus failures. Never raises."""
    errors: list[str] = []

    ram, err = _probe_ram()
    if err:
        errors.append(err)
    cores, err = _probe_cpu_cores()
    if err:
        errors.append(err)

    vram, gpu_name, err = _probe_nvidia()
    if err:
        errors.append(err)

    gpu_present: bool | None
    if vram:
        gpu_present = True
    elif err:
        # A GPU query that FAILED tells us nothing about whether a GPU exists.
        # Unknown, not absent — see Hardware.cpu_only.
        gpu_present = None
    else:
        # No NVIDIA GPU. On Windows, check for any other display adapter before
        # concluding CPU-only, so an AMD card is not misreported as no GPU.
        win_gpu, win_err = _probe_windows_gpu()
        if win_err:
            errors.append(win_err)
            gpu_present = None
        elif win_gpu:
            gpu_present, gpu_name = True, win_gpu
            errors.append(
                f"GPU '{win_gpu}' detected but its VRAM cannot be measured "
                f"(non-NVIDIA; WMI AdapterRAM is unreliable). Treated as "
                f"unknown VRAM rather than assuming a usable amount.")
        else:
            gpu_present = False

    return Hardware(ram_total_gb=ram, vram_total_gb=vram, gpu_name=gpu_name,
                    gpu_present=gpu_present, cpu_cores=cores,
                    probe_errors=tuple(errors))


# ── The real gate ────────────────────────────────────────────────────────────


def capability(hw: Hardware | None = None) -> CapabilityReport:
    """Can THIS machine run a local model, and at what level?

    Real, measurable, and independent of any model file existing. Evaluated in
    fail-closed order: unknowns and hard blocks first, so no later branch can
    hand out capability the earlier ones ruled out.
    """
    hw = hw if hw is not None else probe()
    reasons: list[str] = []

    def verdict(cap: Capability) -> CapabilityReport:
        return CapabilityReport(cap, hw, tuple(reasons))

    # 1. Could not measure RAM -> insufficient. Fail closed.
    if hw.ram_total_gb is None:
        reasons.append(
            "total RAM could not be measured, so local capability cannot be "
            "established. Treated as insufficient rather than assumed capable, "
            f"because a wrong optimistic answer fails at model load instead of "
            f"here. Detail: {'; '.join(hw.probe_errors) or 'unknown'}")
        return verdict(Capability.INSUFFICIENT)

    # 2. RAM floor. Checked before GPU because it gates every path — a machine
    #    under the RAM floor cannot run local inference even with a large GPU,
    #    since weights are staged through system memory and Akira's own audio
    #    stack is already resident.
    if hw.ram_total_gb < PLACEHOLDER_MIN_RAM_GB_BASE:
        reasons.append(
            f"{hw.ram_total_gb:.1f}GB RAM is below the "
            f"{PLACEHOLDER_MIN_RAM_GB_BASE:.0f}GB placeholder floor for any "
            f"local model")
        return verdict(Capability.INSUFFICIENT)

    # 3. GPU presence unknown -> insufficient. Same fail-closed rule as RAM.
    if hw.gpu_present is None:
        reasons.append(
            "GPU presence could not be determined, so local capability cannot "
            "be established. Fail-closed to insufficient. Detail: "
            f"{'; '.join(hw.probe_errors) or 'unknown'}")
        return verdict(Capability.INSUFFICIENT)

    # 4. CPU-only. The position argued in the module docstring, not a hedge.
    if hw.cpu_only:
        if not ALLOW_CPU_LOCAL:
            reasons.append(
                f"no GPU detected ({hw.cpu_cores or '?'} CPU cores). CPU-only "
                f"is treated as INFEASIBLE for local inference, not merely "
                f"slow: this model sits in the latency path of a spoken reply, "
                f"and single-digit tokens/sec makes a voice turn unusable "
                f"rather than sluggish. Set AKIRA_ALLOW_CPU_LOCAL=1 to "
                f"override for non-interactive or benchmarking use.")
            return verdict(Capability.INSUFFICIENT)
        reasons.append(
            "no GPU detected, but AKIRA_ALLOW_CPU_LOCAL=1 overrides the "
            "CPU-only block. Expect latency unsuitable for interactive voice; "
            "base model only, since adapter swapping on CPU compounds it.")
        return verdict(Capability.BASE_ONLY)

    # 5. GPU present but VRAM unmeasurable (non-NVIDIA). Fail closed: the
    #    adapter floor is a VRAM floor, and an unmeasured GPU cannot clear it.
    if hw.vram_total_gb is None:
        reasons.append(
            f"GPU '{hw.gpu_name or 'unknown'}' is present but its VRAM could "
            f"not be measured, so it cannot be checked against the "
            f"{PLACEHOLDER_MIN_VRAM_GB_BASE:.0f}GB floor. Fail-closed to "
            f"insufficient — VRAM support beyond NVIDIA needs a probe that "
            f"does not exist yet.")
        return verdict(Capability.INSUFFICIENT)

    # 6. Measured VRAM against the placeholder floors.
    if hw.vram_total_gb < PLACEHOLDER_MIN_VRAM_GB_BASE:
        reasons.append(
            f"{hw.vram_total_gb:.1f}GB VRAM on '{hw.gpu_name}' is below the "
            f"{PLACEHOLDER_MIN_VRAM_GB_BASE:.0f}GB placeholder floor for a "
            f"base local model")
        return verdict(Capability.INSUFFICIENT)

    # Adapters need BOTH floors. A big GPU on a 16GB machine gets base only.
    if (hw.vram_total_gb >= PLACEHOLDER_MIN_VRAM_GB_ADAPTERS
            and hw.ram_total_gb >= PLACEHOLDER_MIN_RAM_GB_ADAPTERS):
        reasons.append(
            f"{hw.vram_total_gb:.1f}GB VRAM on '{hw.gpu_name}' and "
            f"{hw.ram_total_gb:.1f}GB RAM clear the placeholder adapter floors "
            f"({PLACEHOLDER_MIN_VRAM_GB_ADAPTERS:.0f}GB / "
            f"{PLACEHOLDER_MIN_RAM_GB_ADAPTERS:.0f}GB)")
        return verdict(Capability.ADAPTERS)

    reasons.append(
        f"{hw.vram_total_gb:.1f}GB VRAM / {hw.ram_total_gb:.1f}GB RAM clears "
        f"the base floor but not the placeholder adapter floors "
        f"({PLACEHOLDER_MIN_VRAM_GB_ADAPTERS:.0f}GB VRAM + "
        f"{PLACEHOLDER_MIN_RAM_GB_ADAPTERS:.0f}GB RAM)")
    return verdict(Capability.BASE_ONLY)


# ── The honest stub ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NotVerified:
    """A model's real runtime performance has NOT been verified.

    The only type runtime_verified() can return. There is deliberately no
    Verified counterpart in this module: adding one would create a code path
    that could report a model as checked, and nothing in this build is capable
    of actually checking one. When a runtime lands, the type it returns should
    be added then — with the code that earns it.

    Falsy, matching tiers.Unavailable, so `if not runtime_verified(...)` reads
    correctly and callers cannot accidentally treat it as a pass.
    """
    model_path: str | None
    adapter_path: str | None
    reason: str

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return f"local runtime not verified: {self.reason}"


def runtime_verified(model_path: str | None = None,
                     adapter_path: str | None = None) -> NotVerified:
    """Does a specific local model/adapter actually run acceptably here?

    ALWAYS NotVerified. This cannot be answered for real, because answering it
    requires loading the model and timing it, and no local inference runtime
    exists in this build.

    This is kept separate from capability() rather than folded into one
    pass/fail because the two are different claims. capability() says "this
    hardware is the right shape". This says "the model was loaded and measured
    on it". Hardware being adequate is not evidence that a model ran, and a
    single merged verdict would silently promote the first into the second — a
    machine with a 24GB GPU would report "gate passed" having never executed a
    single token.
    """
    model_path = model_path or (
        os.environ.get("AKIRA_LOCAL_MODEL_PATH") or "").strip() or None
    adapter_path = adapter_path or (
        os.environ.get("AKIRA_LOCAL_ADAPTER_PATH") or "").strip() or None

    # The reason distinguishes the two real cases, mirroring
    # tiers.LocalModel.resolve(), so a maintainer who HAS set a path is told the
    # runtime is missing rather than suspecting their path is wrong.
    if model_path:
        detail = (f"a model path is set ({model_path}) but no local inference "
                  f"runtime is wired into this build, so it has never been "
                  f"loaded or timed")
    else:
        detail = ("no model is configured (AKIRA_LOCAL_MODEL_PATH unset) and "
                  "no local inference runtime is wired into this build")
    return NotVerified(model_path, adapter_path, detail)


# ── Composition: what a call site actually needs ─────────────────────────────


def local_serving_status(hw: Hardware | None = None) -> dict:
    """Both answers together, in the shape tiers.py can consume directly.

    Deliberately a plain dict rather than a new dataclass: tiers.py builds its
    own typed specs from availability inputs, and adding a competing type would
    invite a parallel availability system of the kind this project already has
    one too many of.

    `can_serve_local` is ALWAYS False today, and that is correct rather than a
    bug: serving needs adequate hardware AND a verified runtime, and the second
    can never be true in this build. Hardware capability is reported separately
    and truthfully alongside it, so a capable machine is recognised as capable
    without that being mistaken for a working local model.
    """
    report = capability(hw)
    runtime = runtime_verified()
    return {
        "hardware_capability": report.capability.value,
        "hardware_sufficient": bool(report),
        "hardware_reasons": list(report.reasons),
        "thresholds_measured": report.thresholds_measured,
        "runtime_verified": False,          # never True in this build
        "runtime_reason": runtime.reason,
        "can_serve_local": bool(report) and bool(runtime),   # always False
        "detected": {
            "ram_gb": report.hardware.ram_total_gb,
            "vram_gb": report.hardware.vram_total_gb,
            "gpu": report.hardware.gpu_name,
            "gpu_present": report.hardware.gpu_present,
            "cpu_cores": report.hardware.cpu_cores,
            "platform": report.hardware.platform,
        },
        "probe_errors": list(report.hardware.probe_errors),
    }


def hosted_fallback_reason(hw: Hardware | None = None) -> str:
    """Why a Pro-tier request must go to hosted inference right now.

    WHAT THE GATE'S JOB IS AT PRO TIER — confirmed explicitly, since the brief
    asks: at Pro this gate decides WHEN to fall through to hosted
    (Together/Fireworks). It does NOT and must not block Pro from using hosted
    fallback. Pro's table row is "local fine-tuned + hosted fallback when local
    hardware is insufficient", so hosted is a first-class part of the Pro row,
    not a failure state. A gate that refused Pro because local was unavailable
    would break the tier it is meant to serve.

    Today this always returns a reason, because runtime_verified() is always
    NotVerified — so every Pro request falls through to hosted regardless of how
    capable the hardware is. That is the honest current state, not a
    misconfiguration.
    """
    report = capability(hw)
    if not report:
        return (f"local hardware is insufficient ({report}) — "
                f"{report.reasons[0] if report.reasons else 'no detail'}")
    return (f"local hardware is sufficient ({report}) but "
            f"{runtime_verified().reason}")


def summary(hw: Hardware | None = None) -> dict:
    """Startup-banner view, matching tiers.summary()'s role."""
    status = local_serving_status(hw)
    return {
        "capability": status["hardware_capability"],
        "detected": status["detected"],
        "can_serve_local": status["can_serve_local"],
        "runtime": status["runtime_reason"],
        "thresholds": {
            "measured": False,   # placeholders — see module docstring
            "min_ram_gb": PLACEHOLDER_MIN_RAM_GB_BASE,
            "min_vram_gb": PLACEHOLDER_MIN_VRAM_GB_BASE,
            "min_ram_gb_adapters": PLACEHOLDER_MIN_RAM_GB_ADAPTERS,
            "min_vram_gb_adapters": PLACEHOLDER_MIN_VRAM_GB_ADAPTERS,
        },
        "probe_errors": status["probe_errors"],
    }


if __name__ == "__main__":
    # Live probe of the real machine. This is the "verified, not just written"
    # path — it reports actual detected values from whatever box it runs on.
    import json
    print(json.dumps(summary(), indent=2))
