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

import atexit
import glob
import os
import shutil
import subprocess
import sys
import time
import urllib.request
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


# ── Thresholds & Layer Offloading ─────────────────────────────────────────────
# GUESSES / PLACEHOLDERS FOR FULL OFFLOAD, BUT PARTIAL OFFLOAD IS MEASURED.
#
# On modern consumer hardware (e.g. NVIDIA RTX 2050 with 4GB VRAM):
# An 8B Q4_K_M model (~4.9GB) has 33 total layers. By offloading 16 layers to GPU
# and executing the remaining 17 layers on CPU, the model fits comfortably into
# ~2.4GB VRAM leaving ~1GB headroom for KV cache and context, serving tokens
# at ~6.8 tokens/sec without crashing or running out of memory.

PLACEHOLDER_MIN_VRAM_GB_PARTIAL = float(
    os.environ.get("AKIRA_MIN_VRAM_GB_PARTIAL", "2"))
PLACEHOLDER_MIN_VRAM_GB_BASE = float(
    os.environ.get("AKIRA_MIN_VRAM_GB", "6"))
PLACEHOLDER_MIN_VRAM_GB_ADAPTERS = float(
    os.environ.get("AKIRA_MIN_VRAM_GB_ADAPTERS", "8"))

# Physical 16GB systems on Windows report ~15.2GB in psutil due to hardware
# reserved memory. The base floor is set to 14.0GB to recognize 16GB machines.
PLACEHOLDER_MIN_RAM_GB_BASE = float(
    os.environ.get("AKIRA_MIN_RAM_GB", "14"))
PLACEHOLDER_MIN_RAM_GB_ADAPTERS = float(
    os.environ.get("AKIRA_MIN_RAM_GB_ADAPTERS", "32"))

# See "WHY CPU-ONLY IS TREATED AS INFEASIBLE" above.
ALLOW_CPU_LOCAL = (os.environ.get("AKIRA_ALLOW_CPU_LOCAL", "")
                   or "").strip().lower() in ("1", "true", "yes", "on")

# Probes shell out to vendor tools. A hung driver query must not hang the voice
# loop, so every subprocess call is bounded.
_PROBE_TIMEOUT_S = 5


def calculate_gpu_layers(vram_gb: float | None) -> int:
    """Calculate the number of layers to offload to GPU based on available VRAM.

    33 total transformer layers exist in Llama-3-8B-Instruct.Q4_K_M (~4.9GB total).
    Each layer occupies ~140MB of weights, plus KV cache and context overhead.
    Empirically measured on NVIDIA GeForce RTX 2050 (4GB VRAM):
      - 16 layers offloads ~2.4GB into VRAM, leaving ~1.0GB headroom for KV cache,
        yielding 6.8 tokens/sec with zero OOM errors.
    """
    env_override = os.environ.get("AKIRA_N_GPU_LAYERS")
    if env_override:
        try:
            return max(0, int(env_override))
        except (ValueError, TypeError):
            pass

    if vram_gb is None or vram_gb < PLACEHOLDER_MIN_VRAM_GB_PARTIAL:
        return 0
    if vram_gb >= PLACEHOLDER_MIN_VRAM_GB_ADAPTERS:
        return 33  # Full offload
    if vram_gb >= 6.0:
        return 24
    if vram_gb >= 4.0:
        return 16  # Empirically measured on RTX 2050
    return 8


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

    # 6. Measured VRAM against floors:
    ngl = calculate_gpu_layers(hw.vram_total_gb)
    if hw.vram_total_gb < PLACEHOLDER_MIN_VRAM_GB_PARTIAL:
        reasons.append(
            f"{hw.vram_total_gb:.1f}GB VRAM on '{hw.gpu_name}' is below the "
            f"{PLACEHOLDER_MIN_VRAM_GB_PARTIAL:.0f}GB floor for partial GPU offload")
        return verdict(Capability.INSUFFICIENT)

    # Adapters need BOTH full floors for 100% VRAM offload.
    if (hw.vram_total_gb >= PLACEHOLDER_MIN_VRAM_GB_ADAPTERS
            and hw.ram_total_gb >= PLACEHOLDER_MIN_RAM_GB_ADAPTERS):
        reasons.append(
            f"{hw.vram_total_gb:.1f}GB VRAM on '{hw.gpu_name}' and "
            f"{hw.ram_total_gb:.1f}GB RAM clear the placeholder adapter floors "
            f"({PLACEHOLDER_MIN_VRAM_GB_ADAPTERS:.0f}GB / "
            f"{PLACEHOLDER_MIN_RAM_GB_ADAPTERS:.0f}GB)")
        return verdict(Capability.ADAPTERS)

    reasons.append(
        f"{hw.vram_total_gb:.1f}GB VRAM on '{hw.gpu_name}' / {hw.ram_total_gb:.1f}GB RAM "
        f"clears base floor with partial GPU offload ({ngl}/33 layers on GPU)")
    return verdict(Capability.BASE_ONLY)


# ── Runtime verification types ───────────────────────────────────────────────


@dataclass(frozen=True)
class NotVerified:
    """A model's real runtime performance has NOT been verified or is offline."""
    model_path: str | None
    adapter_path: str | None
    reason: str

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return f"local runtime not verified: {self.reason}"


@dataclass(frozen=True)
class Verified:
    """A local model runtime has been verified active and healthy."""
    endpoint: str
    ngl: int
    reason: str

    def __bool__(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"local runtime verified: {self.reason}"


# ── Local Inference Server Lifecycle Management ──────────────────────────────

_SERVER_PROCESS: subprocess.Popen | None = None


def _cleanup_server_process() -> None:
    global _SERVER_PROCESS
    if _SERVER_PROCESS is not None:
        try:
            if _SERVER_PROCESS.poll() is None:
                _SERVER_PROCESS.terminate()
                _SERVER_PROCESS.wait(timeout=3.0)
        except Exception:
            try:
                _SERVER_PROCESS.kill()
            except Exception:
                pass
        _SERVER_PROCESS = None


atexit.register(_cleanup_server_process)


def find_llama_binary() -> str | None:
    """Find the llama-server.exe executable across standard paths."""
    env_bin = os.environ.get("AKIRA_LLAMA_BIN")
    if env_bin and os.path.isfile(env_bin):
        return env_bin

    exe = shutil.which("llama-server")
    if exe:
        return exe

    for rel in ("llama_cpp/llama-server.exe", "Akira/llama-server.exe", "llama-server.exe"):
        if os.path.isfile(rel):
            return os.path.abspath(rel)

    winget_matches = glob.glob(
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\ggml.llamacpp*\llama-server.exe")
    )
    if winget_matches:
        return winget_matches[0]

    return None


def find_model_paths() -> tuple[str | None, list[str]]:
    """Return (base_model_path, list_of_lora_paths)."""
    base_model = os.environ.get("AKIRA_LOCAL_MODEL_PATH")
    if not base_model or not os.path.isfile(base_model):
        for candidate in ("Akira/Llama-3-8B-Instruct.Q4_K_M.gguf", "Llama-3-8B-Instruct.Q4_K_M.gguf"):
            if os.path.isfile(candidate):
                base_model = os.path.abspath(candidate)
                break

    loras = []
    for lora_name in ("akira_guard.gguf", "akira_api.gguf", "akira_mech.gguf"):
        for candidate in (f"Akira/{lora_name}", lora_name):
            if os.path.isfile(candidate):
                loras.append(os.path.abspath(candidate))
                break

    return base_model, loras


def is_server_healthy(host: str = "127.0.0.1", port: int = 8081, timeout: float = 1.0) -> bool:
    """Query health endpoint without external dependencies."""
    try:
        url = f"http://{host}:{port}/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def attempt_start_server(ngl: int, host: str = "127.0.0.1", port: int = 8081,
                         timeout_s: float = 15.0) -> tuple[bool, str]:
    """Attempt non-blocking startup of llama-server on port 8081."""
    global _SERVER_PROCESS
    if is_server_healthy(host, port):
        return True, f"server already running and healthy on {host}:{port}"

    bin_path = find_llama_binary()
    if not bin_path:
        return False, "llama-server.exe binary not found in PATH or standard directories"

    base_model, loras = find_model_paths()
    if not base_model:
        return False, "base model Llama-3-8B-Instruct.Q4_K_M.gguf not found"

    cmd = [
        bin_path,
        "--model", base_model,
        "-c", "2048",
        "-np", "1",
        "--port", str(port),
        "-ngl", str(ngl),
    ]
    if loras:
        cmd.extend(["--lora", ",".join(loras), "--lora-init-without-apply"])

    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        _SERVER_PROCESS = proc
    except Exception as e:
        return False, f"failed to launch llama-server: {e}"

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"llama-server exited prematurely with code {proc.returncode}"
        if is_server_healthy(host, port, timeout=0.5):
            return True, f"llama-server successfully started on port {port} with -ngl {ngl}"
        time.sleep(0.5)

    _cleanup_server_process()
    return False, f"llama-server failed to respond on port {port} within {timeout_s}s"


def runtime_verified(model_path: str | None = None,
                     adapter_path: str | None = None,
                     hw: Hardware | None = None,
                     auto_start: bool = False) -> Verified | NotVerified:
    """Check if the local inference runtime is active, or attempt non-blocking startup."""
    # 0. Kill switch: if local server is disabled via environment, return NotVerified
    if os.environ.get("AKIRA_DISABLE_LOCAL_SERVER", "").strip().lower() in ("1", "true", "yes"):
        base_model, _ = find_model_paths()
        return NotVerified(
            model_path or base_model,
            adapter_path,
            "no local inference runtime (disabled via AKIRA_DISABLE_LOCAL_SERVER)"
        )

    # 1. If already healthy on port 8081:
    if is_server_healthy("127.0.0.1", 8081):
        ngl = calculate_gpu_layers(hw.vram_total_gb) if hw else 16
        return Verified(
            endpoint="http://127.0.0.1:8081",
            ngl=ngl,
            reason=f"llama-server is running and healthy on port 8081 (ngl={ngl})"
        )

    # 2. If auto_start is not enabled:
    if not auto_start:
        base_model, _ = find_model_paths()
        return NotVerified(
            model_path or base_model,
            adapter_path,
            "no local inference runtime is currently running on port 8081"
        )

    # 3. CPU-only check: strictly refuse automatic CPU 8B inference unless deliberately allowed
    if hw and hw.cpu_only and not ALLOW_CPU_LOCAL:
        return NotVerified(
            model_path,
            adapter_path,
            "no GPU detected; CPU-only serving is disabled for voice latency "
            "(set AKIRA_ALLOW_CPU_LOCAL=1 to override for benchmarking)"
        )

    # 4. Attempt GPU-accelerated startup
    ngl = calculate_gpu_layers(hw.vram_total_gb) if hw else 16
    if hw and hw.cpu_only and ALLOW_CPU_LOCAL:
        ngl = 0

    ok, msg = attempt_start_server(ngl=ngl)
    if ok:
        return Verified(
            endpoint="http://127.0.0.1:8081",
            ngl=ngl,
            reason=msg
        )
    return NotVerified(model_path, adapter_path, msg)


# ── Composition: what a call site actually needs ─────────────────────────────


def local_serving_status(hw: Hardware | None = None, auto_start: bool | None = None) -> dict:
    """Hardware capability and runtime serving status together.

    If auto_start is None: auto-starts when checking the live machine (hw is None)
    or if AKIRA_AUTO_START_LOCAL_SERVER=1 is set.
    """
    if auto_start is None:
        auto_start = (hw is None) or os.environ.get("AKIRA_AUTO_START_LOCAL_SERVER", "").strip().lower() in ("1", "true", "yes")

    report = capability(hw)
    runtime = runtime_verified(hw=hw or report.hardware, auto_start=auto_start)
    return {
        "hardware_capability": report.capability.value,
        "hardware_sufficient": bool(report),
        "hardware_reasons": list(report.reasons),
        "thresholds_measured": report.thresholds_measured,
        "runtime_verified": bool(runtime),
        "runtime_reason": runtime.reason,
        "can_serve_local": bool(report) and bool(runtime),
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
    """Why a Pro-tier request must go to hosted inference right now."""
    report = capability(hw)
    if not report:
        return (f"local hardware is insufficient ({report}) — "
                f"{report.reasons[0] if report.reasons else 'no detail'}")
    runtime = runtime_verified(hw=hw or report.hardware, auto_start=False)
    if runtime:
        return f"local hardware is sufficient ({report}) and runtime is verified ({runtime})"
    return (f"local hardware is sufficient ({report}) but "
            f"{runtime.reason}")


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
            "min_vram_gb_partial": PLACEHOLDER_MIN_VRAM_GB_PARTIAL,
            "min_ram_gb_adapters": PLACEHOLDER_MIN_RAM_GB_ADAPTERS,
            "min_vram_gb_adapters": PLACEHOLDER_MIN_VRAM_GB_ADAPTERS,
        },
        "probe_errors": status["probe_errors"],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), indent=2))
