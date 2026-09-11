"""
akira.py — Akira's ears and orchestration loop.
Handles wake word detection, VAD, recording, transcription, and action execution.
"""

import os
import re
import time
import torch
import pyaudio
import tempfile
import winsound
import threading
import collections
import numpy as np
import openwakeword
import claude_handler
import llm_json
import action_guard
import action_router
import tiers
import reliability
import hardware_gate
import background_tasks
import system_control
import atexit
import office_control
import obsidian_context
from groq import Groq
import socket
import subprocess
import sys
import soundfile as sf
import executor
from executor import execute, get_all_tabs, get_pc_context
from openwakeword import Model as WakeModel

# ── Session Action History & Pinned Session Tracking ──────────────────────────
_session_action_history: collections.deque = collections.deque(maxlen=8)
_active_session_id: str | None = None

def _record_session_action(action: str, parameter: str, result: object) -> None:
    """Append a concise summary of a completed action + outcome to session history."""
    if not action:
        return
    res_str = ""
    if isinstance(result, dict):
        res_str = result.get("detail") or result.get("message") or ("ok" if result.get("success") else "failed")
    elif isinstance(result, str):
        res_str = result.strip()
    elif result is not None:
        res_str = str(result)
    if len(res_str) > 120:
        res_str = res_str[:117] + "..."

    entry = {
        "action": action,
        "parameter": parameter[:80] if parameter else "",
        "result": res_str,
        "timestamp": time.time(),
    }
    _session_action_history.append(entry)

def _reset_session_action_history() -> None:
    """Clear session action history."""
    _session_action_history.clear()

def _end_session() -> None:
    """Clean up state at the end of a session."""
    global _active_session_id, _pending_blocked_action
    _reset_session_action_history()
    _pending_blocked_action = None
    if _active_session_id:
        try:
            import model_pool
            model_pool.get_pool().reset_session_pin(_active_session_id)
        except Exception:
            pass
        _active_session_id = None


# ── Init ──────────────────────────────────────────────────────────────────────

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
openwakeword.utils.download_models()

# ── Multi-Action Chain Throttling & Pacing ───────────────────────────────────
AKIRA_CHAIN_STAGGER_MS = int(os.environ.get("AKIRA_CHAIN_STAGGER_MS", "300"))
AKIRA_CHAIN_MAX_SAFE_LENGTH = int(os.environ.get("AKIRA_CHAIN_MAX_SAFE_LENGTH", "8"))
AKIRA_CHAIN_PACING_INTERVAL = int(os.environ.get("AKIRA_CHAIN_PACING_INTERVAL", "5"))
AKIRA_CHAIN_PACING_PAUSE_S = float(os.environ.get("AKIRA_CHAIN_PACING_PAUSE_S", "1.0"))

# ── Avatar Process & IPC ───────────────────────────────────────────────────────

_avatar_proc: subprocess.Popen | None = None
_avatar_sock: socket.socket | None = None

def _init_avatar() -> None:
    global _avatar_proc, _avatar_sock
    try:
        _avatar_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except Exception as e:
        print(f"[avatar] socket init failed: {e}")
        _avatar_sock = None

    avatar_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatar_ui.py")
    if os.path.exists(avatar_script):
        try:
            # sys.executable ensures the avatar launches in the active environment (where PyQt6 is installed)
            _avatar_proc = subprocess.Popen([sys.executable, avatar_script])
            print(f"[avatar] launched avatar UI (PID {_avatar_proc.pid})")
        except Exception as e:
            print(f"[avatar] failed to launch avatar: {e}")
    else:
        print(f"[avatar] avatar script not found at {avatar_script}")

def _notify_avatar(msg: str) -> None:
    """Send an event trigger to the avatar UI via UDP datagram."""
    global _avatar_sock
    if not _avatar_sock:
        return
    try:
        _avatar_sock.sendto(msg.encode("utf-8"), ("127.0.0.1", 55555))
    except Exception:
        pass

def _cleanup_avatar() -> None:
    """Cleanly shut down the avatar UI process on exit."""
    global _avatar_proc, _avatar_sock
    if _avatar_sock:
        try:
            _avatar_sock.sendto(b"SLEEP_START", ("127.0.0.1", 55555))
        except Exception:
            pass
    if _avatar_proc and _avatar_proc.poll() is None:
        try:
            print("[avatar] shutting down avatar UI...")
            _avatar_proc.terminate()
            try:
                _avatar_proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                _avatar_proc.kill()
        except Exception as e:
            print(f"[avatar] cleanup exception: {e}")

atexit.register(_cleanup_avatar)

# Score above which "Akira" counts as heard. Defined here because the startup
# banner reports it — set AKIRA_WAKE_DEBUG=1 to print live scores and tune it.
WAKE_THRESHOLD = float(os.getenv("AKIRA_WAKE_THRESHOLD", "0.2"))
WAKE_DEBUG     = os.getenv("AKIRA_WAKE_DEBUG", "") not in ("", "0", "false")

# Resolve the wake model next to THIS file, not against the current working
# directory — launching from a shortcut or any other folder otherwise fails.
_WAKE_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "akira.onnx")
oww_model = None
_WAKE_KEY = None
if os.path.isfile(_WAKE_MODEL):
    try:
        oww_model = WakeModel(wakeword_models=[_WAKE_MODEL], inference_framework="onnx")
        _WAKE_KEY = next(iter(oww_model.models.keys()), None)
    except Exception as e:
        print(f"[akira] Wake model load warning: {e}")
else:
    try:
        oww_model = WakeModel()
        _WAKE_KEY = next(iter(oww_model.models.keys()), None)
        print(f"[akira] Custom model akira.onnx not found — loaded openwakeword default model: {_WAKE_KEY}")
    except Exception as e:
        print(f"[akira] Voice wake model (akira.onnx) not found. VAD speech-detection active (listening for speech).")

if _WAKE_KEY:
    print(f"[wake] model '{_WAKE_KEY}' loaded, threshold {WAKE_THRESHOLD}")

# Resolved tier config, printed once at startup. The five layers are independent
# env vars, so the effective configuration is not readable from any single one —
# without this banner, diagnosing "why is delete_files not being offered" means
# guessing which of five variables is set to what.
#
# warnings() reports cross-tier combinations that are broken or untested. They
# are printed, never enforced: mixing tiers is an explicit requirement, and a
# maintainer testing a specific pairing must be able to run it.
_tier_config = tiers.summary()
print(f"[tiers] {_tier_config['plans']}")
print(f"[tiers] head={_tier_config['head']}")
print(f"[tiers] servant={_tier_config['servant']}")
print(f"[tiers] gated={_tier_config['servant_gated']}")
print(f"[tiers] reliability={_tier_config['reliability']}")
for _w in _tier_config["warnings"]:
    print(f"[tiers] WARNING: {_w}")

# Detected local-inference hardware, printed once alongside the tier banner and
# for the same reason: when local models are eventually wired up, "why is it not
# using the local model" will be answered by RAM/VRAM/GPU facts that are
# otherwise invisible. Printing the real measured numbers at boot means the
# answer is already in the log rather than requiring a repro.
#
# can_serve_local is always False in this build (no local inference runtime
# exists) and the banner says so explicitly, so an operator reading capable
# hardware here does not conclude a local model is running.
_hw_config = hardware_gate.summary()
print(f"[hardware] capability={_hw_config['capability']} "
      f"detected={_hw_config['detected']}")
print(f"[hardware] local_serving={_hw_config['can_serve_local']} "
      f"({_hw_config['runtime']})")
if not _hw_config["thresholds"]["measured"]:
    print("[hardware] NOTE: capability thresholds are placeholder estimates, "
          "not measured against a real local model")
for _e in _hw_config["probe_errors"]:
    print(f"[hardware] PROBE: {_e}")

mic = pyaudio.PyAudio()
stream = mic.open(format=pyaudio.paInt16, channels=1, rate=16000,
                  input=True, frames_per_buffer=1280)

try:
    vad_model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-vad", model="silero_vad", force_reload=False
    )
except Exception:
    import os
    _jit_path = os.path.expanduser(r"~/.cache/torch/hub/snakers4_silero-vad_master/src/silero_vad/data/silero_vad.jit")
    if os.path.exists(_jit_path):
        vad_model = torch.jit.load(_jit_path)
    else:
        raise


# ── Session state ─────────────────────────────────────────────────────────────

COOLDOWN_TIME   = 3.0
SESSION_TIMEOUT = 45  # seconds — enough for natural pauses

last_activation_time = 0.0
session_active       = False
session_start_time   = 0.0

# Pending confirmation state
pending_action    = None   # action name or list of actions
pending_parameter = None
pending_execute   = None   # callable for click confirmation
# The action name a "click_confirmed" pause CAME FROM. pending_action is the
# literal string "click_confirmed" for both self-gating shapes, which erases
# which action is actually about to run — and the guard needs that name to pick
# a rule. Kept as a separate slot rather than overloading pending_action,
# because the confirmation branch dispatches on that exact string.
pending_origin    = None
_pending_blocked_action: dict | None = None

CONFIRMATION_PHRASES = frozenset({
    "do it", "yes", "confirm", "go ahead", "yeah do that", "proceed",
    "do that", "yeah", "yep", "sure", "ok do it", "please do it"
})

# VAD barge-in state
akira_speaking  = False
user_speaking   = threading.Event()
vad_buffer_lock = threading.Lock()
vad_audio_buffer: list[np.ndarray] = []
vad_rem_buffer = np.array([], dtype=np.int16)
_vad_error_warned = False

# Dangerous actions — safety net catches these if Claude forgets to gate them
DANGEROUS_ACTIONS = frozenset({
    "close_application", "shutdown", "restart", "hibernate",
    "edit_file", "uninstall_application",
    "write_file",  # overwrites file content — gated same as edit_file
    "wipe_all_memory",  # deletes all logs and core profile — gated
    # Tier 2 Windows system actions (cleanup + power). Pulled from
    # system_control.TIER2_ACTIONS so the gate list cannot drift from the
    # implementations — a new Tier 2 action is gated the moment it exists.
    *system_control.TIER2_ACTIONS,
    # NOTE: delete_files / move_files / organize_files / organize_folder /
    # bulk_rename_files are NOT pre-gated here. They gate themselves in
    # executor.py with a dry-run + spoken enumeration of the exact files
    # (needs_confirmation plan) — stronger than a bare "are you sure?",
    # and impossible to bypass since the gate lives with the implementation.
})

# Shopping sub-actions that must ALWAYS pause for confirmation, regardless of
# what the LLM sets. Parameter-aware: "search"/"add to cart" stay free-flowing.
RISKY_SHOPPING_PARAMS = frozenset({
    "proceed to checkout", "checkout", "place order",
    "confirm address", "select address", "confirm delivery address", "deliver here",
})

# GitHub sub-actions that change live repo state — always confirmation-gated.
# delete repo carries the same severity as shutdown/delete_files.
RISKY_GITHUB_PARAMS = frozenset({
    "create pull request", "merge pull request",
    "close issue", "close pull request",
    "delete branch", "delete repo", "delete repository",
    "push", "force push",
})

# VS Code sub-actions that can destroy existing file content — always gated.
# open/create/read stay free-flowing (create refuses to clobber by design).
RISKY_VSCODE_PARAMS = frozenset({
    "write file", "edit file",
})

# Calendar sub-actions that destroy data — always gated. list/create/update/
# free stay free-flowing (create and update are additive or reversible).
RISKY_CALENDAR_PARAMS = frozenset({
    "delete",
})

# Workspace file deletes (Drive trash via delete_item) — always gated IN CODE,
# not just the prompt: the slides delete bug happened precisely because no
# code-level gate or implementation existed behind the prompt's promise.
# Gates all three dispatchers so a future docs/sheets delete can't ship ungated.
RISKY_WORKSPACE_PARAMS = frozenset({
    "delete",
})

# Office risk lives in office_control.is_risky_parameter() rather than a list
# mirrored here: it must resolve spoken aliases ("remove slide" -> delete
# slide) before checking, and only office_control owns that alias table.


def _is_dangerous_step(step: dict) -> bool:
    """True if this action step must be confirmation-gated by the safety net."""
    if step.get("action") in DANGEROUS_ACTIONS:
        return True
    param = (step.get("parameter") or "").split("|")[0].strip().lower().replace("_", " ")
    if step.get("action") in ("amazon_control", "flipkart_control"):
        return param in RISKY_SHOPPING_PARAMS
    if step.get("action") == "github_control":
        return param in RISKY_GITHUB_PARAMS
    if step.get("action") == "vscode_control":
        return param in RISKY_VSCODE_PARAMS
    if step.get("action") == "calendar_control":
        return param in RISKY_CALENDAR_PARAMS
    if step.get("action") in ("slides_control", "docs_control", "sheets_control"):
        return param in RISKY_WORKSPACE_PARAMS
    if step.get("action") == "office_control":
        # Delegated because office_control's parameter is "app|sub|args" (the
        # sub-action is field 1, not 0) AND the sub-action may be an alias:
        # "remove slide" and "close document" must gate exactly like
        # "delete slide" and "close". office_control resolves both.
        return office_control.is_risky_parameter(step.get("parameter"))
    return False


# ── Deliberation tier ────────────────────────────────────────────────────────
# "deliberate" is not a real executor action — it is an ABSTAIN signal from the
# router meaning "I'm not confident this maps to one action". It is expanded
# here, BEFORE the safety net, into the concrete steps a proper reasoning pass
# decided on. Expanding it here rather than inside executor is deliberate: every
# planned step then flows through _is_dangerous_step and the existing
# confirmation machinery exactly like a router-emitted step, so the reasoning
# pass cannot route around a single safety guarantee.

_DELIBERATE_MAX_STEPS = 8


def _expand_deliberation(steps: list[dict]) -> tuple[list[dict], str | None]:
    """Replace any deliberate step with the plan it reasons out.

    Returns (steps_to_run, spoken_override). A spoken_override with no steps
    means the pass asked a question or declined instead of acting.
    """
    if not any((s.get("action") or "").strip().lower() == "deliberate"
               for s in steps if isinstance(s, dict)):
        return steps, None

    expanded: list[dict] = []
    spoken: str | None = None
    for step in steps:
        if not isinstance(step, dict):
            continue
        if (step.get("action") or "").strip().lower() != "deliberate":
            expanded.append(step)
            continue

        request = (step.get("parameter") or "").strip()
        print(f"[deliberate] escalated request={request[:160]!r}")
        try:
            ctx = get_pc_context()
            bits = [f"foreground app: {ctx.get('foreground_app') or 'unknown'}"]
            url = ctx.get("current_url")
            if url and url not in ("about:blank", "chrome://newtab/", ""):
                bits.append(f"page open: {url}")
            try:
                import obsidian_context
                if obsidian_context.focus_note:
                    bits.append(f"note open: {obsidian_context.focus_note}")
                focus = obsidian_context.is_focus_mode()
            except Exception:
                focus = False
            plan = claude_handler.deliberate(request, " | ".join(bits),
                                             focus_mode=focus)
        except Exception as e:
            print(f"[deliberate] expansion failed: {e!r}")
            plan = None

        if not plan:
            spoken = ("I thought about that one and couldn't work out what you "
                      "wanted precisely enough to act on it. Can you tell me "
                      "a bit more directly?")
            continue

        if plan.get("ask") and not plan.get("plan"):
            spoken = plan["ask"]
            continue

        for planned in plan["plan"][:_DELIBERATE_MAX_STEPS]:
            if not isinstance(planned, dict):
                continue
            name = (planned.get("action") or "").strip()
            # No recursion: a reasoning pass may not buy itself another one.
            if not name or name.lower() == "deliberate":
                continue
            expanded.append({"action": name,
                             "parameter": planned.get("parameter")})
        if plan.get("summary"):
            spoken = plan["summary"]

    print(f"[deliberate] expanded to {[s.get('action') for s in expanded]}")
    return expanded, spoken


def _confirmation_prompt(unsafe: list[dict]) -> str:
    """Confirmation wording for the safety net's own fallback.

    Only used when the LLM failed to supply a confirmation_message. For
    clear_temp_files the generic "are you sure?" is not good enough — the user
    must hear WHICH folders are about to be emptied, so the read-only preview
    is used to name them (and their real size) before anything is deleted.
    """
    if any(a.get("action") == "clear_temp_files" for a in unsafe):
        try:
            preview = system_control.preview_temp_cleanup()
            if preview.get("success"):
                return (preview["message"] +
                        " Nothing in your documents, photos, or downloads is touched. Go ahead?")
        except Exception as e:
            print(f"[handle_response] temp preview failed: {e}")
        return ("This clears only your Windows temp and prefetch folders — "
                "nothing in your documents, photos, or downloads. Go ahead?")
    return "Just confirming before I do that."


FAILURE_PREFIXES = (
    "I couldn't find", "Couldn't click", "Couldn't find",
    "Skipped", "Something went wrong", "Unknown action",
)

# Boot fingerprint — makes stale-process / wrong-file / wrong-BRANCH issues
# instantly visible. The git line matters most: a bug report is unreadable
# without knowing which commit was actually running.
print(f"[BOOT] akira: {os.path.abspath(__file__)}")
print(f"[BOOT] claude_handler: {claude_handler.__file__}")
print(f"[BOOT] prompt has github_control: "
      f"{'github_control' in getattr(claude_handler, 'AKIRA_PROMPT', '')}")


def _git_fingerprint() -> str:
    """branch @ short-sha (+dirty) of the checkout actually being run."""
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    def _git(*args: str) -> str:
        return subprocess.check_output(("git", "-C", here) + args,
                                       stderr=subprocess.DEVNULL,
                                       text=True, timeout=5).strip()
    try:
        stamp = f"{_git('rev-parse', '--abbrev-ref', 'HEAD')} @ {_git('rev-parse', '--short', 'HEAD')}"
        return stamp + (" +uncommitted-changes" if _git("status", "--porcelain") else "")
    except Exception as e:
        return f"unknown ({e.__class__.__name__})"


print(f"[BOOT] git: {_git_fingerprint()}")
# All four, not just the brain: the point of this line is diagnosing a bug
# report, and "which model answered" now has four possible answers depending on
# which path the user hit. Same '?' default as before so a future rename prints
# a visible gap next to the name that moved instead of crashing the boot.
print("[BOOT] models: " + "  ".join(
    f"{name.split('_')[0].lower()}={getattr(claude_handler, name, '?')}"
    for name in ("BRAIN_MODEL", "ROUTING_MODEL", "DRAFT_MODEL", "HAIKU_MODEL")))
# Feature fingerprints: proves at a glance whether the running code has the
# features a bug report is about, instead of guessing from the branch name.
try:
    import chunked_read as _cr
    import obsidian_control as _oc
    print(f"[BOOT] features: focus_mode={hasattr(claude_handler, 'FOCUS_MODE_PROMPT')} "
          f"organize={hasattr(_oc, '_do_organize')} "
          f"chunked_read={_cr.SPOKEN_CHUNK_CHARS}ch "
          f"deliberate={hasattr(claude_handler, 'deliberate')} "
          f"by_type_parsing={hasattr(claude_handler, 'response_text')}")
except Exception as e:
    print(f"[BOOT] features: check failed ({e.__class__.__name__})")

print("Listening for 'Akira'...")


# ── Audio utilities ───────────────────────────────────────────────────────────

def record_command(pre_audio: np.ndarray | None = None) -> np.ndarray | None:
    """
    Record until silence or MAX_CHUNKS. Returns normalised float32 audio or None.
    pre_audio: VAD-captured audio from during Akira's speech (barge-in buffer).
    """
    command_audio = [pre_audio] if pre_audio is not None else []
    chunk_count   = 1 if pre_audio is not None else 0
    silent_chunks = 15
    MAX_CHUNKS    = 200
    MIN_CHUNKS    = 48
    MAX_SILENT    = 15

    while chunk_count < MAX_CHUNKS:
        chunk = stream.read(1280, exception_on_overflow=False)
        audio_np = np.frombuffer(chunk, dtype=np.int16)
        rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
        command_audio.append(audio_np.astype(np.float32))
        chunk_count += 1
        if chunk_count > MIN_CHUNKS:
            silent_chunks = silent_chunks + 1 if rms < 150 else 0
            if silent_chunks >= MAX_SILENT:
                break

    if not command_audio:
        print("[record] no audio captured")
        return None

    raw = np.concatenate(command_audio)
    normalised = raw / 32768.0
    energy = float(np.sqrt(np.mean(raw ** 2)))
    if pre_audio is None and energy < 100:
        print(f"[record] too quiet (rms={energy:.1f})")
        return None
    if pre_audio is not None and energy < 70:
        print(f"[record] too quiet even with pre_audio (rms={energy:.1f})")
        return None
    return normalised


def transcribe_command(audio: np.ndarray) -> str:
    """Write audio to temp file and transcribe via Groq Whisper."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name
    sf.write(temp_path, audio, 16000)
    try:
        with open(temp_path, "rb") as f:
            result = groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo", file=f, language="en"
            )
        return result.text.strip()
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass


def flush_stream() -> None:
    if not user_speaking.is_set():
        try:
            available = stream.get_read_available()
            if available > 0:
                stream.read(available, exception_on_overflow=False)
        except Exception:
            pass


# ── VAD barge-in listener ─────────────────────────────────────────────────────

def _vad_listener() -> None:
    """Daemon thread: runs VAD while Akira is speaking to detect barge-in.
    
    Acoustic Echo Cancellation (AEC) & Multi-Frame Confirmation:
    Akira must NOT hear or act on its own voice output. Single 32ms frames can
    experience acoustic micro-fluctuations or boundary clicks. To guarantee 0
    false positives, genuine user barge-in requires persistence across at least
    3 consecutive speech frames (~96ms). On confirmation, Akira's speech is
    instantly halted and all buffered user speech frames are retained.
    """
    consecutive_user_frames = 0
    pending_user_chunks: list[np.ndarray] = []

    while True:
        if akira_speaking:
            chunk = stream.read(512, exception_on_overflow=False)
            audio_np = np.frombuffer(chunk, dtype=np.int16)
            audio_f  = torch.FloatTensor(audio_np.astype(np.float32) / 32768.0)
            confidence = vad_model(audio_f, 16000).item()
            if confidence > 0.4:
                audio_f_np = audio_np.astype(np.float32) / 32768.0
                if claude_handler.is_speaker_echo(audio_f_np):
                    # Pure speaker bleed from Akira's own voice — reset counter and discard
                    consecutive_user_frames = 0
                    pending_user_chunks.clear()
                    continue

                # Potential user speech detected
                consecutive_user_frames += 1
                pending_user_chunks.append(audio_np.astype(np.float32))

                # Multi-frame confirmation: require 4 consecutive speech frames (~128ms)
                if consecutive_user_frames >= 4:
                    if not user_speaking.is_set():
                        print("[barge-in] User interruption confirmed (4-frame debounce). Halting Akira's speech...")
                        claude_handler.stop_speaking()
                        user_speaking.set()
                    with vad_buffer_lock:
                        if pending_user_chunks:
                            vad_audio_buffer.extend(pending_user_chunks)
                            pending_user_chunks.clear()
            else:
                consecutive_user_frames = 0
                pending_user_chunks.clear()
        else:
            consecutive_user_frames = 0
            pending_user_chunks.clear()
            time.sleep(0.01)


vad_thread = threading.Thread(target=_vad_listener, daemon=True)
vad_thread.start()


def speak_and_wait(text: str) -> None:
    """Speak text while VAD listens for barge-in. Blocks until done or interrupted."""
    global akira_speaking
    akira_speaking = True
    _notify_avatar("SPEAK_START")
    thread = claude_handler.speak_async(text)
    thread.join()
    akira_speaking = False
    _notify_avatar("SPEAK_STOP")
    # Clean up audio stream:
    # If genuine user barge-in occurred, PRESERVE the user's audio in vad_audio_buffer
    # so the command can be transcribed and acted on immediately!
    # If no barge-in occurred (Akira spoke to completion), clear any residual speaker bleed
    # and flush the mic stream.
    if not user_speaking.is_set():
        with vad_buffer_lock:
            vad_audio_buffer.clear()
        flush_stream()
    else:
        print("[barge-in] Retaining user interruption audio in buffer for immediate execution.")


def _announce_background() -> bool:
    """Speak any finished-background-task lines. Returns True if it spoke.

    MAIN THREAD ONLY. Worker threads must never call speak themselves:
    akira_speaking is a plain global shared with the VAD listener, and two TTS
    streams at once would both overlap audio and corrupt the barge-in state.
    Workers queue a line here instead, and this drains it at a safe moment.
    """
    if not background_tasks.has_announcements():
        return False
    spoke = False
    for line in background_tasks.take_announcements():
        print(f"[background] announcing: {line[:100]!r}")
        speak_and_wait(line)
        spoke = True
        # Put the outcome in the LLM's history too, so the next turn can answer
        # "what did you call those notes?" instead of having no idea the work
        # ever happened — the completion never went through run_actions.
        try:
            claude_handler.record_action_results([line])
        except Exception as e:
            print(f"[background] history record failed: {e}")
    return spoke


# ── Action execution ───────────────────────────────────────────────────────��──

def _guard_refusal_text(action: str, outcome) -> str:
    """Spoken text for a step the guard stopped BEFORE it ran.

    Worded so the failure scan in handle_response sees it as a failure: a
    refusal that read as success would let the LLM's pre-baked "doing it now"
    text be spoken over an action that never happened.
    """
    why = "; ".join(outcome.verdict.reasons) or "it looked unsafe"
    return f"I didn't run {action.replace('_', ' ')} — {why}."


def _guard_flag_pending(action: str, outcome, confirmed: bool = False) -> str:
    """Handle a guard flag that arrived on a step which ALREADY ran.

    If confirmed=True: the user explicitly confirmed this action before execution.
    The response must reflect reality ("Done, though flagged for your awareness"),
    never claiming "I've stopped" when the action definitively succeeded.
    """
    why = "; ".join(outcome.verdict.reasons) or "it may not have been safe"
    verb = action.replace("_", " ")
    if confirmed:
        print(f"[guard] FLAG on confirmed {action}: {why}")
        return f"Done, though flagged for your awareness: {why}."
    if outcome.blocked:
        print(f"[guard] BLOCK arrived after {action} executed: {why}")
        return (f"Heads up — I already ran {verb}, but on review it shouldn't "
                f"have gone through: {why}. I've stopped there.")
    print(f"[guard] FLAG arrived after {action} executed: {why}")
    return (f"I ran {verb}, but worth flagging: {why}. "
            "I've stopped there rather than carrying on.")


def _guard_gated(actions: list[dict]) -> tuple[list[dict], list[str]]:
    """Guard gated steps BEFORE their confirmation is spoken.

    The rule that does NOT change: a gated action still never skips
    confirmation, whatever the guard says. Clearing the guard does not grant
    permission — it only earns the step the right to be OFFERED. So an ALLOW
    changes nothing observable; only a BLOCK does, by dropping the step so the
    user is never asked to approve something malformed. Asking for consent to a
    broken step would launder a bug into approval — the same reasoning
    guard_rules uses for static BLOCK.

    A FLAG is deliberately NOT filtered: flag means "a human should decide", and
    the confirmation prompt this sits in front of IS that human deciding.

    THE TIER GATE RUNS FIRST, BEFORE THE GUARD
    ------------------------------------------
    tiers.gated_available() answers "may this action be OFFERED at all on the
    current config" — Gated is off entirely on Free, and on Pro each action type
    must have cleared the reliability bar. That is a config question with a
    local answer, so it is settled before spending a guard API call on a step
    that cannot be offered regardless of the verdict.

    Ordering matters for a second reason: the guard's job is judging THIS
    step's shape, while the tier's job is judging whether the capability is
    available. Letting a guard ALLOW precede a tier refusal would produce a log
    line saying an action was approved immediately before it was withheld, which
    reads as a contradiction to anyone debugging it.

    A tier refusal is spoken, not silent, for the same reason a guard BLOCK is:
    the user asked for something and must hear why it is not happening.

    Returns (steps_still_offered, spoken_notes).
    """
    kept: list[dict] = []
    notes: list[str] = []
    for step in actions:
        if not isinstance(step, dict):
            continue

        action = str(step.get("action") or "").strip()

        # supervised=True is a statement of fact about this function, not a
        # convenience: everything kept here goes on to the confirmation prompt
        # (see the docstring above — clearing the guard "only earns the step the
        # right to be OFFERED"). Nothing reaches execution from here without a
        # human yes, which is exactly the condition the probation provision
        # requires. Passing False would reinstate the deadlock documented in
        # tiers.gated_available: an unproven action would be dropped before it
        # could ever record the runs the bar demands.
        unavailable = tiers.gated_available(action, supervised=True)
        if unavailable is not None:
            print(f"[tier] not offering {action}: {unavailable.reason}")
            notes.append(f"I can't do {action.replace('_', ' ')} right now — "
                         f"{unavailable.reason}")
            continue

        # Offered, but not yet proven. Say so at the prompt rather than letting
        # the difference be silent — the user is being asked to supervise
        # precisely because the action has no track record yet.
        if tiers.on_probation(action):
            left = reliability.remaining(action)
            print(f"[tier] {action} on probation: {left} clean run(s) to go")
            notes.append(
                f"Heads up: {action.replace('_', ' ')} hasn't cleared the "
                f"{reliability.THRESHOLD}-run reliability protocol yet "
                f"({left} to go), so I'll keep asking you to confirm it.")

        # execute=no-op: this is a validation pass only. Nothing may run before
        # the user has confirmed, so the callable must be inert by construction
        # rather than by the router happening not to call it.
        outcome = action_router.run_guarded(step, lambda: None)
        if outcome.blocked:
            why = "; ".join(outcome.verdict.reasons) or "it looked malformed"
            name = str(step.get("action") or "that").replace("_", " ")
            print(f"[guard] gated BLOCK, not offering {name}: {why}")
            notes.append(f"I'm not going to offer {name} — {why}.")
            continue
        if outcome.flagged:
            print(f"[guard] gated FLAG on {step.get('action')}: "
                  f"{'; '.join(outcome.verdict.reasons)}")
        kept.append(step)
    return kept, notes


def run_actions(response: dict, step_results: dict | None = None,
                confirmed: bool = False) -> list:
    """
    Execute one or many actions with dependency graph support.
    - id / depends_on for chaining
    - {{stepX.result}} substitution
    - click confirmation pause
    - failure tracking per step id
    """
    global pending_action, pending_parameter, pending_execute, pending_origin

    if step_results is None:
        step_results = {}

    steps = response.get("actions", [])
    if not steps and response.get("action"):
        steps = [{"action": response["action"], "parameter": response.get("parameter")}]

    # HARD RULE (code, not convention): no download_image in the same chain
    # as search_image, and at most one download_image per chain. The LLM is
    # told this in AKIRA_PROMPT; action_guard makes it impossible regardless.
    steps, guard_notes = action_guard.sanitize_actions(steps)

    results    = list(guard_notes)
    failed_ids = set()

    # Step ids whose result a LATER step consumes, either through depends_on or a
    # {{stepX.result}} substitution. Backgrounding replaces a step's real result
    # with an acknowledgement, so backgrounding one of these would feed the next
    # step "I'll get started on that" instead of the value it needs. Chained
    # steps therefore stay inline no matter what the background table says.
    consumed: set = set()
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("depends_on"):
            consumed.add(s["depends_on"])
        raw_param = s.get("parameter")
        if isinstance(raw_param, str):
            consumed.update(re.findall(r"\{\{(\w+)\.result\}\}", raw_param))

    import model_pool
    for idx, step in enumerate(steps):
        # Mandatory stagger and pacing between consecutive sub-actions
        model_pool.throttle_chain_step(
            idx, len(steps),
            stagger_ms=AKIRA_CHAIN_STAGGER_MS,
            max_safe_length=AKIRA_CHAIN_MAX_SAFE_LENGTH,
            pacing_interval=AKIRA_CHAIN_PACING_INTERVAL,
            pacing_pause_s=AKIRA_CHAIN_PACING_PAUSE_S,
        )

        step_id    = step.get("id")
        depends_on = step.get("depends_on")

        if depends_on and depends_on in failed_ids:
            msg = f"Skipped {step.get('action')} because {depends_on} failed."
            print(f"[run_actions] {msg}")
            results.append(msg)
            if step_id:
                failed_ids.add(step_id)
            continue

        # {{stepX.result}} substitution
        parameter = step.get("parameter")
        if parameter and isinstance(parameter, str) and "{{" in parameter:
            def _sub(m):
                r = step_results.get(m.group(1), m.group(0))
                # dict results: prefer machine field "path" (download_image ->
                # set_wallpaper needs a real path, not the spoken "Image saved
                # to ..." sentence), fall back to message, never the repr —
                # str(dict) produced garbage params like "{'success': True...}"
                if isinstance(r, dict):
                    return str(r.get("path") or r.get("message", ""))
                return str(r)
            parameter = re.sub(r"\{\{(\w+)\.result\}\}", _sub, parameter)
            print(f"[run_actions] substituted parameter={parameter!r}")

        print(f"[run_actions] {step['action']} | {parameter!r} | id={step_id}")

        # Slow, artifact-producing work runs in the background so the session
        # keeps going. Decided by background_tasks' table, NOT by anything here —
        # one place owns that list. This sits below the confirmation machinery on
        # purpose: gated steps never reach run_actions until the user has said
        # yes, so backgrounding can never be used to skip a confirmation.
        bg_label = background_tasks.should_background(step["action"], parameter)
        if bg_label and step_id in consumed:
            print(f"[run_actions] not backgrounding {step['action']}: "
                  f"step {step_id} feeds a later step")
            bg_label = None
        if bg_label:
            if tiers.plan_for(tiers.Layer.SERVANT) != tiers.PRO:
                print(f"[run_actions] refusing background task {step['action']}: not on PRO tier")
                result = {"success": False, "speak": True, "message": "Background tasks are only available on the Pro tier."}
                if step_id:
                    step_results[step_id] = result
                results.append(result)
                continue

            result = background_tasks.start(
                bg_label,
                # bound now, not at call time — the loop variables move on
                lambda a=step["action"], p=parameter: execute(a, p))
            if step_id:
                step_results[step_id] = result
            results.append(result)
            continue

        # GUARD + EXECUTE, timed by the step's tier (action_router).
        # For Tier A / A-adjacent rollback-safe steps the guard runs on a worker
        # thread WHILE this executes, so the cost is max(guard, execute) rather
        # than the sum. For everything else the guard runs first and blocking.
        # The router owns that decision; run_actions only reacts to the outcome.
        #
        # Gated steps never reach here un-confirmed — handle_response routes them
        # into pending_actions above — so this is not the gated guard seam. That
        # one lives in _guard_gated(), called before the confirmation is spoken.
        guard_step = {"action": step["action"], "parameter": parameter}
        outcome = action_router.run_guarded(
            guard_step, lambda a=step["action"], p=parameter: execute(a, p),
            confirmed=confirmed)
        result = outcome.result

        if not outcome.executed:
            # Serial path refused before running. Nothing happened, so this is a
            # clean failure: report it and let depends_on skip the rest.
            result = _guard_refusal_text(step["action"], outcome)
            _pending_blocked_action = {"action": step["action"], "parameter": parameter}
            if step_id:
                step_results[step_id] = None
                failed_ids.add(step_id)
            results.append(result)
            continue

        # NOTE ON ORDER: the mid-flight guard flag is handled AFTER the two
        # confirmation-pause branches below, not before them. A self-gating
        # action (delete_files, move_files, organize_*) returns
        # needs_confirmation INSTEAD of acting, and those same actions are
        # FLAG-prone. Checking the flag first would break the chain and discard
        # the spoken enumeration the user needs to answer — turning a working
        # confirmation into silence. Since nothing has actually happened in that
        # case, the existing pause is both safe and strictly more useful.

        # click confirmation — pause chain
        if isinstance(result, dict) and result.get("needs_click_confirmation"):
            pending_action    = "click_confirmed"
            pending_parameter = result["retry_parameter"]
            pending_execute   = result["_execute"]
            pending_origin    = step["action"]
            msg = f"Are you sure you want to click '{result['element_text']}'?"
            results.append(msg)
            if step_id:
                step_results[step_id] = None
                failed_ids.add(step_id)
            break

        # generic gated plan (file ops etc.) — executor already resolved the
        # exact targets and built the spoken enumeration; pause the chain and
        # run its _execute only after a spoken yes (same machinery as click)
        if isinstance(result, dict) and result.get("needs_confirmation") and result.get("_execute"):
            pending_action    = "click_confirmed"
            pending_parameter = result["confirm_message"]
            pending_execute   = result["_execute"]
            pending_origin    = step["action"]
            print(f"[run_actions] gated plan from {step['action']}: {result['confirm_message'][:80]!r}")
            results.append(result["confirm_message"])
            if step_id:
                step_results[step_id] = None
                failed_ids.add(step_id)
            break

        if step_id:
            step_results[step_id] = result

        # Mid-flight guard flag: the step already ran and did NOT pause for
        # confirmation, so this is the genuine race outcome. Reuses the existing
        # pending_action machinery rather than adding a fourth state — see
        # _guard_flag_pending for why, and for the rollback limitation.
        # step_results is populated above first, so a later step that already
        # consumed this value is unaffected by the halt.
        if not outcome.verdict.allowed:
            msg = _guard_flag_pending(step["action"], outcome, confirmed=confirmed)
            if not confirmed:
                _pending_blocked_action = {"action": step["action"], "parameter": parameter}
                results.append(msg)
                break
            else:
                results.append(msg)

        # AUDIT FIX: dict failures ({"success": False}) never entered
        # failed_ids — depends_on only skipped on string failures, so e.g.
        # a failed download_image still let set_wallpaper run on garbage.
        failed = (isinstance(result, str) and result.startswith(FAILURE_PREFIXES)) or \
                 (isinstance(result, dict) and result.get("success") is False)
        if failed and step_id:
            failed_ids.add(step_id)

        # RELIABILITY LEDGER — the only place a run is recorded.
        #
        # Placed HERE, at the bottom of the loop, because this is the first point
        # where the outcome is actually known and the step actually ran. Every
        # earlier exit path is deliberately NOT recorded, and each omission is a
        # correctness requirement rather than an oversight:
        #
        #   * outcome.executed == False   — the guard refused before running.
        #     Nothing executed, so there is no reliability evidence either way.
        #     Recording it as a failure would let a strict guard permanently
        #     suppress an action that has never once misbehaved.
        #   * needs_click_confirmation / needs_confirmation — the action returned
        #     a PLAN instead of acting. Recording a success here would credit a
        #     streak for work that never happened, which is precisely how a
        #     destructive action could unlock without ever having run correctly.
        #   * backgrounded steps — they return an acknowledgement, not a result,
        #     so their true outcome is not observable from this frame at all.
        #
        # `confirmed` scoping: only confirmed gated executions count toward the
        # Gated unlock bar. An unconfirmed pass never reaches this line, so no
        # extra condition is needed — but the ledger is written for ALL tiers,
        # not just Pro, so that history accumulates BEFORE an operator switches
        # to Pro. Otherwise flipping to Pro would reset every action to 20 runs
        # remaining and look like the gate was broken.
        #
        # Guarded because a ledger write must never take down a completed action:
        # the action already happened, and a disk error here is not the user's
        # problem. A dropped record only makes the action MORE gated, which is
        # the safe direction.
        if confirmed and step["action"]:
            try:
                reliability.record(step["action"], success=not failed)
            except Exception as e:
                print(f"[reliability] failed to record {step['action']}: {e!r}")

        results.append(result)

        # Record action in ongoing session action tracker
        try:
            _record_session_action(step.get("action", ""), str(parameter or ""), result)
        except Exception as _act_err:
            print(f"[run_actions] failed to record session action: {_act_err}")


    return results


# ── Response handling ────────────────────────────────���───────────────��────────

def handle_response(response: dict, user_text: str = "") -> bool:
    """
    Process a parsed Akira response dict.
    Returns True to keep session alive, False to end it.
    """
    global session_start_time, pending_action, pending_parameter

    mode = response.get("mode")
    tone = (response.get("tone") or "neutral").lower()

    # Detect user appreciation or praise
    user_appreciation = False
    if user_text:
        lowered = user_text.lower()
        praise_patterns = [
            r"\bthanks?\b",
            r"\bthank you\b",
            r"\bgreat job\b",
            r"\bgreat work\b",
            r"\bgood job\b",
            r"\bgood work\b",
            r"\bawesome\b",
            r"\bappreciate it\b",
            r"\byou(?:'re| are) the best\b",
            r"\byou rock\b",
            r"\bperfect\b",
        ]
        if any(re.search(pat, lowered) for pat in praise_patterns):
            user_appreciation = True

    if user_appreciation or tone in ("happy", "excited"):
        _notify_avatar("HAPPY_START")
    elif tone == "calm":
        _notify_avatar("CALM_START")

    if mode == "command":
        actions_to_run = response.get("actions", [])
        if response.get("action"):
            actions_to_run = [{"action": response["action"], "parameter": response.get("parameter")}]

        # Deliberation tier: swap any "deliberate" abstain signal for the plan a
        # real reasoning pass produced. Done HERE, above the safety net, so
        # planned steps are gated identically to router-emitted ones.
        actions_to_run, deliberated_speech = _expand_deliberation(actions_to_run)
        if deliberated_speech:
            # The reasoning pass speaks for itself — its summary/question always
            # beats the router's placeholder "Let me think about that one."
            response["response"] = deliberated_speech
        # An empty plan is a valid outcome (it asked a question or declined):
        # nothing runs, and the summary/question falls through to the single
        # speak_and_wait at the end of this function.
        if not actions_to_run and not response.get("response"):
            response["response"] = "I didn't catch an action to run for that request. Could you rephrase?"

        response["actions"] = actions_to_run
        response.pop("action", None)
        response.pop("parameter", None)

        # safety net: catch dangerous actions Claude forgot to gate
        # (includes risky shopping steps like checkout / place order / address)
        unsafe = [a for a in actions_to_run if _is_dangerous_step(a)]
        safe   = [a for a in actions_to_run if not _is_dangerous_step(a)]

        # GATED GUARD SEAM — serial and blocking, before confirmation is built.
        # Placed here, above BOTH confirmation branches, so it applies whether
        # the safety net caught the step or the LLM gated it itself. The guard
        # can only REMOVE a malformed step from the offer; it can never approve
        # one into running, so the confirmation flow's behaviour is unchanged.
        guard_notes_gated: list[str] = []
        if unsafe:
            unsafe, guard_notes_gated = _guard_gated(unsafe)
            if not unsafe:
                # Every gated step was refused on shape. There is nothing left to
                # confirm, so do not ask a question with no action behind it.
                response.pop("confirmation_required", None)
                response.pop("pending_actions", None)
                response["actions"] = safe

        if unsafe and not response.get("confirmation_required"):
            print(f"[handle_response] safety net caught: {[a['action'] for a in unsafe]}")
            response["confirmation_required"] = True
            response["pending_actions"]       = unsafe
            response["actions"]               = safe
            response.pop("action", None)
            response.pop("parameter", None)
            response["confirmation_message"]  = _confirmation_prompt(unsafe)
            # speak the question, not the LLM's premature "doing it now" text
            response["response"] = response["confirmation_message"]
        elif unsafe:
            # LLM set confirmation_required itself — make sure the unsafe steps
            # land in pending, NOT in the executed-now list.
            response["pending_actions"] = unsafe
            response["actions"]         = safe
            response.pop("action", None)
            response.pop("parameter", None)

        run_results = []
        if response.get("confirmation_required"):
            # NOTHING executes until the user confirms. Previously the
            # `elif not unsafe` branch ran non-dangerous actions immediately
            # even when confirmation_required was True (checkout bypass bug).
            pass
        else:
            run_results = run_actions(response if not response.get("pending_actions") else {"actions": safe})

        # Post-execution speech override. Failures take absolute precedence:
        # the old reversed-loop-with-break let a later speak:True result mask
        # an earlier failure, so the LLM's pre-baked "Adding it now..." text
        # was spoken over a failed calendar add. Scan ALL results instead.
        failures   = []
        spoken_info = None   # last speak:True message wins, as before
        unverified  = False  # dict results with no "success" key at all
        for r in run_results:
            if isinstance(r, str) and r.startswith(FAILURE_PREFIXES):
                failures.append(r)
            elif isinstance(r, dict):
                if r.get("success") is False:
                    # click-validation failures carry "reason", not "message"
                    failures.append(r.get("message") or r.get("reason") or "That didn't work.")
                elif "success" not in r:
                    unverified = True
                elif r.get("speak") and r.get("message"):
                    spoken_info = r["message"]
        if failures:
            parts = list(failures)
            if spoken_info:
                parts.append(spoken_info)          # keep data from steps that DID work
            if len(run_results) > len(failures):
                parts.append("The other steps went through.")
            response["response"] = " ".join(parts)
        elif spoken_info:
            print(f"[run_actions] speaking informational result: {spoken_info[:80]!r}")
            response["response"] = spoken_info
        elif unverified:
            # can't confirm the outcome — don't let pre-baked text claim success
            response["response"] = "I ran that, but I couldn't verify it completed."

        # A gated step the guard refused on shape must be SAID, not dropped in
        # silence — otherwise the user hears a confirmation for two steps when
        # three were planned and has no idea the third was discarded. Prepended
        # so the refusal precedes whatever question or outcome follows it.
        if guard_notes_gated:
            response["response"] = " ".join(
                [*guard_notes_gated, response.get("response", "")]).strip()

        # feed execution outcomes back into LLM history — without this the
        # next turn can't see what list_folder/read_clipboard/delete_files
        # actually returned and it asks the user for data it already has
        if run_results:
            try:
                claude_handler.record_action_results(run_results)
            except Exception as e:
                print(f"[v0] record_action_results failed: {e}")

            # same-turn synthesis for workspace reads (speak_summary=True):
            # the raw API dump is now in history, so ask the LLM to answer the
            # user's request from it NOW instead of speaking the routing call's
            # pre-baked "let me check your inbox" and going silent. Must run
            # AFTER record_action_results (synthesis reads it from history)
            # and takes precedence over the "speak" override above because raw
            # dumps are not speakable. Failure keeps the existing response.
            if any(isinstance(r, dict) and r.get("speak_summary") for r in run_results):
                summary = claude_handler.synthesize_action_reply()
                if summary:
                    response["response"] = summary

        # click confirmation discovered at runtime
        if pending_action == "click_confirmed" and run_results:
            response["response"] = run_results[-1]

        # store pending dangerous actions
        if response.get("confirmation_required"):
            if response.get("pending_actions"):
                pending_action    = response["pending_actions"]
                pending_parameter = None
            elif response.get("action"):
                pending_action    = response["action"]
                pending_parameter = response.get("parameter")

    print("[v0] speaking response...")
    speak_and_wait(response.get("response", ""))
    print("[v0] done speaking")

    # A task that finished WHILE this turn was being processed couldn't be spoken
    # then — the main thread was busy. Now is the first safe moment.
    _announce_background()

    if response.get("end_session"):
        flush_stream()
        claude_handler.clear_history()
        # drop the focus note / mentioned notes with the conversation history,
        # so the next session doesn't inherit a stale note target
        obsidian_context.reset()
        _notify_avatar("SLEEP_START")
        return False

    flush_stream()
    time.sleep(0.4)
    session_start_time = time.time()
    # feeds the flow-rate heuristic that suppresses clarifying questions
    # during a rapid back-and-forth (obsidian_context.should_ask_clarification)
    obsidian_context.record_turn(session_start_time)
    return True


# ── LLM query ─────────────────────────────────────────────────────────────────

def get_akira_response(text: str, session_id: str | None = None) -> dict | None:
    """
    Get Akira's response for user text.
    Handles pending confirmation state before calling the LLM.
    Returns parsed dict or None (when confirmation was handled inline).
    """
    global pending_action, pending_parameter, pending_execute, pending_origin, _pending_blocked_action

    cleaned_input = re.sub(r"[^\w\s]", "", text.lower()).strip()
    is_short_confirmation = cleaned_input in CONFIRMATION_PHRASES or any(
        cleaned_input == phrase or cleaned_input.startswith(f"{phrase} ")
        for phrase in ("do it", "confirm", "proceed", "go ahead", "do that")
    )

    # 1. Handle confirmation of a previously blocked action (Bug 2)
    if _pending_blocked_action is not None and is_short_confirmation:
        blocked = dict(_pending_blocked_action)
        _pending_blocked_action = None
        print(f"[confirmation] Retrying previously blocked action: {blocked}")
        confirm_results = run_actions({"actions": [blocked]}, confirmed=True)
        speak_text = "Done."
        for r in reversed(confirm_results):
            if isinstance(r, str) and r.startswith(FAILURE_PREFIXES):
                speak_text = r
                break
            if isinstance(r, dict) and r.get("success") is False:
                speak_text = r.get("message", "That didn't work.")
                break
            if isinstance(r, dict) and r.get("success") is True and r.get("message"):
                speak_text = r["message"]
                break
            if isinstance(r, str):
                speak_text = r
                break
        speak_and_wait(speak_text)
        try:
            claude_handler.record_action_results(confirm_results)
        except Exception as e:
            print(f"[v0] record_action_results failed: {e}")
        return None
    elif _pending_blocked_action is not None and not is_short_confirmation:
        _pending_blocked_action = None

    # 2. handle existing pending confirmation
    if pending_action is not None:
        if pending_action == "click_confirmed":
            pending_desc = f"clicking '{pending_parameter}'"
        elif isinstance(pending_action, list):
            pending_desc = ", ".join(
                f"{a.get('action')} {a.get('parameter') or ''}".strip()
                for a in pending_action)
        else:
            pending_desc = f"{pending_action} {pending_parameter or ''}".strip()

        confirmed = claude_handler.ask_confirmation(text, pending_desc)
        if confirmed:
            if pending_action == "click_confirmed" and pending_execute is not None:
                origin = pending_origin or "click_confirmed"
                try:
                    outcome = action_router.run_guarded(
                        {"action": origin, "parameter": pending_parameter},
                        pending_execute, confirmed=True)
                    if not outcome.executed:
                        speak_text = _guard_refusal_text(origin, outcome)
                        exec_result = speak_text
                    else:
                        exec_result = outcome.result
                        if isinstance(exec_result, dict) and exec_result.get("message"):
                            speak_text = exec_result["message"]
                        else:
                            speak_text = "Done."
                        if not outcome.verdict.allowed:
                            speak_text = _guard_flag_pending(origin, outcome, confirmed=True)

                    if outcome.executed and origin:
                        _failed = (
                            (isinstance(exec_result, str)
                             and exec_result.startswith(FAILURE_PREFIXES))
                            or (isinstance(exec_result, dict)
                                and exec_result.get("success") is False)
                        )
                        try:
                            reliability.record(origin, success=not _failed)
                        except Exception as e:
                            print(f"[reliability] failed to record {origin}: {e!r}")

                    try:
                        claude_handler.record_action_results([exec_result if isinstance(exec_result, dict) else speak_text])
                    except Exception as e:
                        print(f"[v0] record_action_results failed: {e}")
                    if "_record_session_action" in globals():
                        try:
                            _record_session_action(str(origin), str(pending_parameter or ""), exec_result)
                        except Exception:
                            pass
                except Exception as e:
                    speak_text = f"Couldn't do that: {e}"
            else:
                actions = (
                    pending_action if isinstance(pending_action, list)
                    else [{"action": pending_action, "parameter": pending_parameter}]
                )
                confirm_results = run_actions({"actions": actions},
                                              confirmed=True)
                speak_text = "Done."
                for r in reversed(confirm_results):
                    if isinstance(r, str) and r.startswith(FAILURE_PREFIXES):
                        speak_text = r
                        break
                    if isinstance(r, dict) and r.get("success") is False:
                        speak_text = r.get("message", "That didn't work.")
                        break
                    if isinstance(r, dict) and r.get("success") is True and r.get("message"):
                        speak_text = r["message"]
                        break
                    if isinstance(r, str) and r.startswith("Done, though flagged for your awareness"):
                        speak_text = r
                        break
                if confirm_results:
                    try:
                        claude_handler.record_action_results(confirm_results)
                    except Exception as e:
                        print(f"[v0] record_action_results failed: {e}")
            pending_action = pending_parameter = pending_execute = None
            pending_origin = None
            speak_and_wait(speak_text)
            return None
        else:
            pending_action = pending_parameter = pending_execute = None
            pending_origin = None
            # fall through to normal LLM call (user said something else)

    # Non-blocking async browser pre-warm during LLM routing if browser intent detected
    if any(k in cleaned_input for k in ("search", "google", "reddit", "youtube", "netflix", "site", "tab", "browse", "url", "http", "look up", "chrome", "brave", "edge", "spotify")):
        try:
            executor.warmup_browser()
        except Exception:
            pass

    try:
        raw = claude_handler.ask_akira(text, session_id=session_id)
        if not (raw or "").strip():
            return {"mode": "conversation",
                    "response": "Having trouble connecting right now.", "end_session": False}
        # Tolerant parse: the model emits raw newlines and bare quotes inside
        # string values, and a long parameter can end the reply mid-string.
        # llm_json repairs the first and REPORTS the second.
        response, info = llm_json.parse(raw)
        if response is None:
            print(f"[get_akira_response] unparseable reply: {raw[:400]!r}")
            return {"mode": "conversation",
                    "response": "Something went wrong on my end. Say that again.",
                    "end_session": False}
        if info["truncated"]:
            # A cut-off string means the last value is INCOMPLETE. Acting on it
            # would type half a paragraph into the user's document, so refuse
            # and say why instead of silently doing something wrong.
            print("[get_akira_response] reply was truncated mid-string — "
                  "refusing to execute the actions in it")
            return {"mode": "conversation",
                    "response": "That answer came back cut off, so I didn't run it. "
                                "If you want long content written, ask me to generate "
                                "it and I'll write it properly.",
                    "end_session": False}
        return response
    except Exception as e:
        print(f"[get_akira_response] unexpected error: {e!r}")
        return {"mode": "conversation",
                "response": "Something went wrong. Try again.", "end_session": False}


def _build_session_context() -> str:
    """Build a concise context string injected into every turn of an active session."""
    try:
        tabs = get_all_tabs()
        ctx  = get_pc_context()
        tabs_str    = ", ".join(f"{t['title']}" for t in tabs[:8] if t.get("title")) or "none"
        windows_str = ", ".join(ctx.get("open_windows", [])[:5]) or "none"
        url_str     = ctx.get("current_url") or "none"
        note_str = obsidian_context.session_line() if "obsidian_context" in globals() else ""

        # Concise action history of recent actions this session
        action_lines = []
        hist = globals().get("_session_action_history")
        if hist:
            for i, act in enumerate(hist, 1):
                param_part = f" | {act['parameter']}" if act.get('parameter') else ""
                res_part = f" -> {act['result']}" if act.get('result') else ""
                action_lines.append(f"{i}. {act.get('action', '')}{param_part}{res_part}")

        actions_block = ""
        if action_lines:
            actions_block = "[RECENT ACTIONS THIS SESSION]\n" + "\n".join(action_lines) + "\n\n"

        tabs_block = f"[CURRENT BROWSER TABS]\n{tabs_str}\n\n"

        raw_ctx = (
            f"Focused app: {ctx.get('foreground_app', 'unknown')} | "
            f"Current page: {url_str} | "
            f"Windows: {windows_str}"
            + (f" | {note_str}" if note_str else "")
        )

        return (
            "[SESSION START]\n"
            f"{actions_block}"
            "<untrusted_external_context>\n"
            f"{tabs_block}"
            "[PC STATE]\n"
            f"{raw_ctx}\n"
            "</untrusted_external_context>\n\n"
        )
    except Exception as e:
        print(f"[v0] session context error: {e}")
        return ""


# ── Main loop ─────────────────────────────────────────────────────────────────

def _process_command(text: str, inject_context: bool = False) -> bool:
    """
    Transcribe → LLM → execute → speak.
    Returns True to keep session alive, False to end it.
    inject_context: True on the first command of a new session.
    """
    global _active_session_id
    if not text:
        print("[v0] empty transcription, staying alive")
        return True

    if inject_context or not _active_session_id:
        _end_session()
        _active_session_id = f"session_{int(time.time())}"
        obsidian_context.reset()

    print("[v0] building session context (browser)...")
    context_prefix = _build_session_context()
    if context_prefix:
        text = context_prefix + text
    print("[v0] session context done")

    print("[v0] calling LLM...")
    import memory_observer
    memory_observer.observe_turn_async(text)

    response = get_akira_response(text, session_id=_active_session_id)
    print("[v0] LLM returned")
    if response is None:
        return True  # confirmation was handled inline, stay alive

    print(response)
    alive = handle_response(response, user_text=text)
    if not alive:
        _end_session()
    return alive


if __name__ == "__main__":
    _init_avatar()
    # Note: Browser is NOT pre-warmed on startup to keep cold-start lightweight and instant.
    # Browser launches/attaches lazily on the first browser action.
    try:
        import file_index
        file_index.init_file_index(background=True)
    except Exception as _idx_err:
        print(f"[file_index] Background init warning: {_idx_err}")
    while True:
        try:
            current_time = time.time()

            # ── Active session ────────────────────────────────────────────
            if session_active and (current_time - session_start_time) < SESSION_TIMEOUT:

                with vad_buffer_lock:
                    if user_speaking.is_set() and vad_audio_buffer:
                        pre_audio = np.concatenate(vad_audio_buffer)
                        vad_audio_buffer.clear()
                    else:
                        pre_audio = None
                        vad_audio_buffer.clear()
                    user_speaking.clear()

                print("[v0] recording command (session follow-up)...")
                audio = record_command(pre_audio=pre_audio)
                if audio is None:
                    print("[v0] session follow-up audio too quiet or timed out, closing session")
                    session_active = False
                    _end_session()
                    if oww_model:
                        oww_model.reset()
                    continue

                print("[v0] transcribing (session follow-up)...")
                text = transcribe_command(audio)
                print(f"[v0] heard (session follow-up): {text!r}")

                # ── Phantom-command guard ─────────────────────────────────
                # Reject empty strings or pure filler/noise sounds that Whisper
                # occasionally hallucinates on ambient noise or breath sounds.
                # Explicitly protect valid confirmation/cancellation tokens
                # ("yes", "no", "yeah", "yep", "ok", etc.) from being dropped.
                _CONFIRMATION_WORDS = frozenset({
                    "yes", "no", "yeah", "yep", "yup", "nah", "nope",
                    "ok", "okay", "sure", "cancel", "stop", "proceed",
                    "confirm", "do it", "dont", "don't", "nevermind", "go ahead",
                })
                _PURE_NOISE_WORDS = frozenset({
                    "", "um", "uh", "hmm", "hm", "oh", "ah",
                    "mhm", "huh", "mmm", "ooh", "aah",
                })
                text_stripped = (text or "").strip()
                cleaned_word = text_stripped.lower().rstrip(".,!?;:")
                words = [w.strip(".,!?;:") for w in text_stripped.lower().split()]

                is_confirmation = (
                    cleaned_word in _CONFIRMATION_WORDS
                    or any(w in _CONFIRMATION_WORDS for w in words)
                )
                is_noise = False
                if not is_confirmation:
                    if len(text_stripped) < 2 or all(w in _PURE_NOISE_WORDS for w in words):
                        is_noise = True

                if is_noise:
                    print(f"[v0] rejected phantom/noise transcription: {text!r}")
                    continue

                session_active = _process_command(text)
                if session_active:
                    print("[session] continuing")
                else:
                    _end_session()
                    if oww_model:
                        oww_model.reset()

            # ── Idle — listening for wake word ────────────────────────────
            else:
                if session_active:
                    _end_session()
                session_active = False

                # Interrupt-on-completion. This branch polls every ~80ms, so a task
                # that finishes while Akira is idle gets announced essentially the
                # moment it finishes, with no wake word needed.
                #
                # Idle is the ONLY point where speaking unprompted is safe: during a
                # turn the mic is actively recording, so speaking there would put
                # Akira's own voice into the transcription. Anything that completes
                # mid-turn is announced by handle_response instead.
                if background_tasks.has_announcements() and not user_speaking.is_set():
                    if _announce_background():
                        # Akira's own voice just went into an open mic. Drop it and
                        # reset the detector so it cannot self-trigger the wake word.
                        flush_stream()
                        if oww_model:
                            oww_model.reset()
                        last_activation_time = time.time()
                        continue

                chunk    = stream.read(1280, exception_on_overflow=False)
                audio_np = np.frombuffer(chunk, dtype=np.int16)
                # Look the score up by the model's real key. Positional access
                # returned whichever model the dict happened to order first.
                scores   = oww_model.predict(audio_np) if oww_model else {}
                score    = scores.get(_WAKE_KEY, 0.0) if _WAKE_KEY else 0.0

                if WAKE_DEBUG:
                    # Peak amplitude proves the mic is actually delivering audio —
                    # a flat 0 here means the input device is wrong or muted, which
                    # looks identical to "wake word not working" from the outside.
                    peak = int(np.abs(audio_np).max()) if audio_np.size else 0
                    print(f"[wake] score={score:.3f} peak={peak:5d} "
                          f"keys={list(scores)}")

                current_time = time.time()
                triggered = score > WAKE_THRESHOLD and (current_time - last_activation_time) > COOLDOWN_TIME

                # If no custom wake model exists, fallback to VAD speech activity trigger
                if not triggered and oww_model is None and (current_time - last_activation_time) > COOLDOWN_TIME:
                    if vad_model is not None and len(audio_np) > 0:
                        vad_combined = np.concatenate([vad_rem_buffer, audio_np]) if len(vad_rem_buffer) > 0 else audio_np
                        # Silero VAD strictly requires exactly 512 samples at 16kHz
                        while len(vad_combined) >= 512:
                            sub_chunk = vad_combined[:512]
                            vad_combined = vad_combined[512:]
                            try:
                                audio_f = torch.from_numpy(sub_chunk).float() / 32768.0
                                with torch.no_grad():
                                    vad_conf = vad_model(audio_f, 16000).item()
                                if vad_conf > 0.6:
                                    if claude_handler.is_speaker_echo(audio_f.numpy()):
                                        continue
                                    triggered = True
                                    print("[voice] Speech detected!")
                                    break
                            except Exception as _vad_err:
                                if not _vad_error_warned:
                                    print(f"[vad] Inference warning (skipping frame): {_vad_err}")
                                    _vad_error_warned = True
                                break
                        vad_rem_buffer = vad_combined if not triggered else np.array([], dtype=np.int16)

                if triggered:
                    vad_rem_buffer = np.array([], dtype=np.int16)
                    print("Wake word detected!")
                    _notify_avatar("WAKE_START")
                    winsound.Beep(1000, 200)
                    last_activation_time = current_time

                    print("[v0] recording command...")
                    audio = record_command()
                    if audio is None:
                        print("[v0] record returned None (too quiet), back to idle")
                        continue

                    print("[v0] transcribing...")
                    text = transcribe_command(audio)
                    print(f"[v0] heard: {text!r}")
                    session_active = _process_command(text, inject_context=True)

                    if session_active:
                        last_activation_time = time.time()
                        session_start_time   = time.time()
                        if oww_model:
                            oww_model.reset()

        except KeyboardInterrupt:
            print("\nShutting down Akira.")
            _cleanup_avatar()
            break
        except Exception as e:
            # outer safety net — log and continue, never crash the main loop
            print(f"[main loop] unhandled exception: {e!r}")
            time.sleep(1.0)
            continue

    _cleanup_avatar()