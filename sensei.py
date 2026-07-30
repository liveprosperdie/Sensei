"""
sensei.py — Akira's ears and orchestration loop.
Handles wake word detection, VAD, recording, transcription, and action execution.
"""

import os
import re
import time
import json
import torch
import pyaudio
import tempfile
import winsound
import threading
import numpy as np
import openwakeword
import claude_handler
import action_guard
import system_control
import office_control
from groq import Groq
import soundfile as sf
from executor import execute, get_all_tabs, get_pc_context
from openwakeword import Model as WakeModel

# ── Init ──────────────────────────────────────────────────────────────────────

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
openwakeword.utils.download_models()

# Score above which "Sensei" counts as heard. Defined here because the startup
# banner reports it — set SENSEI_WAKE_DEBUG=1 to print live scores and tune it.
WAKE_THRESHOLD = float(os.getenv("SENSEI_WAKE_THRESHOLD", "0.2"))
WAKE_DEBUG     = os.getenv("SENSEI_WAKE_DEBUG", "") not in ("", "0", "false")

# Resolve the wake model next to THIS file, not against the current working
# directory — launching from a shortcut or any other folder otherwise fails.
_WAKE_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "sensei.onnx")
if not os.path.isfile(_WAKE_MODEL):
    raise SystemExit(
        f"Wake model not found: {_WAKE_MODEL}\n"
        "sensei.onnx is gitignored, so a fresh clone won't have it — copy your "
        "trained model into the project folder."
    )
oww_model = WakeModel(wakeword_models=[_WAKE_MODEL], inference_framework="onnx")

# openwakeword's predict() returns {model_label: score} for EVERY loaded model.
# Reading position [0] out of that dict assumed one model and a stable order;
# after an openwakeword upgrade it can silently return a different label's
# score, so the wake word never fires and nothing is logged. Bind the real key
# once, here, and fail loudly if it can't be determined.
_WAKE_KEY = next(iter(oww_model.models.keys()), None)
if _WAKE_KEY is None:
    raise SystemExit(f"Wake model {_WAKE_MODEL} loaded no usable model.")
print(f"[wake] model '{_WAKE_KEY}' loaded, threshold {WAKE_THRESHOLD}")

mic = pyaudio.PyAudio()
stream = mic.open(format=pyaudio.paInt16, channels=1, rate=16000,
                  input=True, frames_per_buffer=1280)

vad_model, _ = torch.hub.load(
    repo_or_dir="snakers4/silero-vad", model="silero_vad", force_reload=False
)

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

# VAD barge-in state
akira_speaking  = False
user_speaking   = threading.Event()
vad_buffer_lock = threading.Lock()
vad_audio_buffer: list[np.ndarray] = []

# Dangerous actions — safety net catches these if Claude forgets to gate them
DANGEROUS_ACTIONS = frozenset({
    "close_application", "shutdown", "restart", "hibernate",
    "edit_file", "uninstall_application",
    "write_file",  # overwrites file content — gated same as edit_file
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

# Boot fingerprint — makes stale-process / wrong-file issues instantly visible
print(f"[BOOT] sensei: {os.path.abspath(__file__)}")
print(f"[BOOT] claude_handler: {claude_handler.__file__}")
print(f"[BOOT] prompt has github_control: "
      f"{'github_control' in getattr(claude_handler, 'AKIRA_PROMPT', '')}")

print("Listening for 'Sensei'...")


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
    if pre_audio is None and np.sqrt(np.mean(raw ** 2)) < 100:
        print("[record] too quiet")
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
        available = stream.get_read_available()
        if available > 0:
            stream.read(available, exception_on_overflow=False)


# ── VAD barge-in listener ─────────────────────────────────────────────────────

def _vad_listener() -> None:
    """Daemon thread: runs VAD while Akira is speaking to detect barge-in."""
    while True:
        if akira_speaking:
            chunk = stream.read(512, exception_on_overflow=False)
            audio_np = np.frombuffer(chunk, dtype=np.int16)
            audio_f  = torch.FloatTensor(audio_np.astype(np.float32) / 32768.0)
            confidence = vad_model(audio_f, 16000).item()
            if confidence > 0.5:
                user_speaking.set()
                with vad_buffer_lock:
                    vad_audio_buffer.append(audio_np.astype(np.float32))
        else:
            time.sleep(0.01)


vad_thread = threading.Thread(target=_vad_listener, daemon=True)
vad_thread.start()


def speak_and_wait(text: str) -> None:
    """Speak text while VAD listens for barge-in. Blocks until done."""
    global akira_speaking
    akira_speaking = True
    thread = claude_handler.speak_async(text)
    thread.join()
    akira_speaking = False
    user_speaking.clear()


# ── Action execution ───────────────────────────────────────────────────────��──

def run_actions(response: dict, step_results: dict | None = None) -> list:
    """
    Execute one or many actions with dependency graph support.
    - id / depends_on for chaining
    - {{stepX.result}} substitution
    - click confirmation pause
    - failure tracking per step id
    """
    global pending_action, pending_parameter, pending_execute

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

    for step in steps:
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

        try:
            result = execute(step["action"], parameter)
        except Exception as e:
            print(f"[run_actions] EXCEPTION in execute: {e!r}")
            result = f"Something went wrong running {step['action']}: {e}"

        # click confirmation — pause chain
        if isinstance(result, dict) and result.get("needs_click_confirmation"):
            pending_action    = "click_confirmed"
            pending_parameter = result["retry_parameter"]
            pending_execute   = result["_execute"]
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
            print(f"[run_actions] gated plan from {step['action']}: {result['confirm_message'][:80]!r}")
            results.append(result["confirm_message"])
            if step_id:
                step_results[step_id] = None
                failed_ids.add(step_id)
            break

        if step_id:
            step_results[step_id] = result

        # AUDIT FIX: dict failures ({"success": False}) never entered
        # failed_ids — depends_on only skipped on string failures, so e.g.
        # a failed download_image still let set_wallpaper run on garbage.
        failed = (isinstance(result, str) and result.startswith(FAILURE_PREFIXES)) or \
                 (isinstance(result, dict) and result.get("success") is False)
        if failed and step_id:
            failed_ids.add(step_id)

        results.append(result)

    return results


# ── Response handling ────────────────────────────────���───────────────��────────

def handle_response(response: dict) -> bool:
    """
    Process a parsed Akira response dict.
    Returns True to keep session alive, False to end it.
    """
    global session_start_time, pending_action, pending_parameter

    mode = response.get("mode")

    if mode == "command":
        actions_to_run = response.get("actions", [])
        if response.get("action"):
            actions_to_run = [{"action": response["action"], "parameter": response.get("parameter")}]

        # safety net: catch dangerous actions Claude forgot to gate
        # (includes risky shopping steps like checkout / place order / address)
        unsafe = [a for a in actions_to_run if _is_dangerous_step(a)]
        safe   = [a for a in actions_to_run if not _is_dangerous_step(a)]

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

    if response.get("end_session"):
        flush_stream()
        claude_handler.clear_history()
        return False

    flush_stream()
    time.sleep(0.4)
    session_start_time = time.time()
    return True


# ── LLM query ─────────────────────────────────────────────────────────────────

def get_akira_response(text: str) -> dict | None:
    """
    Get Akira's response for user text.
    Handles pending confirmation state before calling the LLM.
    Returns parsed dict or None (when confirmation was handled inline).
    """
    global pending_action, pending_parameter, pending_execute

    # handle pending confirmation
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
                try:
                    exec_result = pending_execute()
                    # gated file-op closures return {"success", "message"} —
                    # speak the real outcome instead of a generic "Done."
                    if isinstance(exec_result, dict) and exec_result.get("message"):
                        speak_text = exec_result["message"]
                    else:
                        speak_text = "Done."
                    try:
                        claude_handler.record_action_results([exec_result if isinstance(exec_result, dict) else speak_text])
                    except Exception as e:
                        print(f"[v0] record_action_results failed: {e}")
                except Exception as e:
                    speak_text = f"Couldn't do that: {e}"
            else:
                actions = (
                    pending_action if isinstance(pending_action, list)
                    else [{"action": pending_action, "parameter": pending_parameter}]
                )
                confirm_results = run_actions({"actions": actions})
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
                # record confirmed-action outcomes in history too — this path
                # previously skipped it, so after "delete my meeting" + "yes"
                # the next turn had no idea the delete ever happened
                if confirm_results:
                    try:
                        claude_handler.record_action_results(confirm_results)
                    except Exception as e:
                        print(f"[v0] record_action_results failed: {e}")
            pending_action = pending_parameter = pending_execute = None
            speak_and_wait(speak_text)
            return None
        else:
            pending_action = pending_parameter = pending_execute = None
            # fall through to normal LLM call (user said something else)

    try:
        raw = claude_handler.ask_akira(text).replace("```json", "").replace("```", "").strip()
        if not raw:
            return {"mode": "conversation",
                    "response": "Having trouble connecting right now.", "end_session": False}
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[get_akira_response] JSONDecodeError: {e!r} | raw: {raw!r}")
        return {"mode": "conversation",
                "response": "Something went wrong on my end. Say that again.", "end_session": False}
    except Exception as e:
        print(f"[get_akira_response] unexpected error: {e!r}")
        return {"mode": "conversation",
                "response": "Something went wrong. Try again.", "end_session": False}


def _build_session_context() -> str:
    """Build a one-time context string injected at session start."""
    try:
        tabs = get_all_tabs()
        ctx  = get_pc_context()
        tabs_str    = ", ".join(f"{t['title']}" for t in tabs[:6]) or "none"
        windows_str = ", ".join(ctx["open_windows"][:5]) or "none"
        url_str     = ctx.get("current_url") or "none"
        return (
            f"[SESSION START] Open tabs: {tabs_str} | "
            f"Current page: {url_str} | "
            f"Windows: {windows_str}\n\n"
        )
    except Exception:
        return ""


# ── Main loop ─────────────────────────────────────────────────────────────────

def _process_command(text: str, inject_context: bool = False) -> bool:
    """
    Transcribe → LLM → execute → speak.
    Returns True to keep session alive, False to end it.
    inject_context: True on the first command of a new session.
    """
    if not text:
        print("[v0] empty transcription, staying alive")
        return True

    if inject_context:
        print("[v0] building session context (browser)...")
        text = _build_session_context() + text
        print("[v0] session context done")

    print("[v0] calling LLM...")
    response = get_akira_response(text)
    print("[v0] LLM returned")
    if response is None:
        return True  # confirmation was handled inline, stay alive

    print(response)
    return handle_response(response)


while True:
    try:
        current_time = time.time()

        # ── Active session ────────────────────────────────────────────
        if session_active and (current_time - session_start_time) < SESSION_TIMEOUT:

            with vad_buffer_lock:
                if user_speaking.is_set() and vad_audio_buffer:
                    pre_audio = np.concatenate(vad_audio_buffer)
                    vad_audio_buffer.clear()
                    user_speaking.clear()
                else:
                    pre_audio = None
                    vad_audio_buffer.clear()

            audio = record_command(pre_audio=pre_audio)
            if audio is None:
                session_active = False
                oww_model.reset()
                continue

            text = transcribe_command(audio)
            session_active = _process_command(text)
            if session_active:
                print("[session] continuing")
            else:
                oww_model.reset()

        # ── Idle — listening for wake word ────────────────────────────
        else:
            session_active = False
            chunk    = stream.read(1280, exception_on_overflow=False)
            audio_np = np.frombuffer(chunk, dtype=np.int16)
            # Look the score up by the model's real key. Positional access
            # returned whichever model the dict happened to order first.
            scores   = oww_model.predict(audio_np)
            score    = scores.get(_WAKE_KEY, 0.0)

            if WAKE_DEBUG:
                # Peak amplitude proves the mic is actually delivering audio —
                # a flat 0 here means the input device is wrong or muted, which
                # looks identical to "wake word not working" from the outside.
                peak = int(np.abs(audio_np).max()) if audio_np.size else 0
                print(f"[wake] score={score:.3f} peak={peak:5d} "
                      f"keys={list(scores)}")

            current_time = time.time()
            if score > WAKE_THRESHOLD and (current_time - last_activation_time) > COOLDOWN_TIME:
                print("Wake word detected!")
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
                    oww_model.reset()

    except KeyboardInterrupt:
        print("\nShutting down Sensei.")
        break
    except Exception as e:
        # outer safety net — log and continue, never crash the main loop
        print(f"[main loop] unhandled exception: {e!r}")
        time.sleep(1.0)
        continue
