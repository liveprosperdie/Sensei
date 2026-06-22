import os
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
from groq import Groq
import soundfile as sf
from executor import execute
from openwakeword import Model as WakeModel


groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
openwakeword.utils.download_models()
oww_model = WakeModel(wakeword_models=["sensei.onnx"], inference_framework="onnx")

mic = pyaudio.PyAudio()
stream = mic.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1280)
last_activation_time = 0.0
COOLDOWN_TIME = 3.0
session_active = False
SESSION_TIMEOUT = 20
session_start_time = 0.0
pending_action = None
pending_parameter = None
pending_execute = None
akira_speaking = False
user_speaking = threading.Event()
vad_model, _ = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False)
vad_audio_buffer = []
vad_buffer_lock = threading.Lock()
print("Listening for 'Sensei'...")


def record_command(pre_audio=None):
    command_audio = [pre_audio] if pre_audio is not None else []
    chunk_count = 1 if pre_audio is not None else 0
    silent_chunks = 15
    MAX_CHUNKS = 200
    MIN_CHUNKS = 48
    MAX_SILENT = 15
    while chunk_count < MAX_CHUNKS:
        audio_chunk = stream.read(1280, exception_on_overflow=False)
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
        rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
        command_audio.append(audio_np.astype(np.float32))
        chunk_count += 1
        if chunk_count > MIN_CHUNKS:
            if rms < 150:
                silent_chunks += 1
            else:
                silent_chunks = 0
            if silent_chunks >= MAX_SILENT:
                break
    if len(command_audio) == 0:
        print("record_command: no audio or too quiet")
        return None
    command = np.concatenate(command_audio)
    final_command = command / 32768.0
    if pre_audio is None and np.sqrt(np.mean(command ** 2)) < 100:
        print("record_command: no audio or too quiet")
        return None
    return final_command


def transcribe_command(final_command):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name
    sf.write(temp_path, final_command, 16000)
    with open(temp_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=f,
            language="en"
        )
    os.remove(temp_path)
    return result.text.strip()


def flush_stream():
    if not user_speaking.is_set():
        available = stream.get_read_available()
        if available > 0:
            stream.read(available, exception_on_overflow=False)


def vad_listener():
    global vad_audio_buffer
    while True:
        if akira_speaking:
            audio_chunk = stream.read(512, exception_on_overflow=False)
            audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
            audio_float = torch.FloatTensor(audio_np.astype(np.float32) / 32768.0)
            confidence = vad_model(audio_float, 16000).item()
            if confidence > 0.5:
                user_speaking.set()
                with vad_buffer_lock:
                    vad_audio_buffer.append(audio_np.astype(np.float32))
        else:
            time.sleep(0.01)


def speak_and_wait(text):
    """Sets akira_speaking before speech starts (so VAD listens during it),
    runs speak() in a thread, and blocks here until it's done before returning."""
    global akira_speaking
    akira_speaking = True
    thread = claude_handler.speak_async(text)
    thread.join()
    akira_speaking = False
    user_speaking.clear()


def run_actions(response, step_results=None):
    """Execute one action or a list of actions with full chain/dependency support.

    Supports:
    - id/depends_on dependency graph
    - {{stepX.result}} substitution before each step runs
    - per-step result storage
    - dependent steps halt on failed dependency
    - independent steps never blocked by each other
    - click confirmation pause via existing pending state
    """
    global pending_action, pending_parameter, pending_execute

    if step_results is None:
        step_results = {}

    results = []
    steps = response.get("actions", [])
    if not steps and response.get("action"):
        steps = [{"action": response["action"], "parameter": response.get("parameter")}]

    failed_ids = set()

    for step in steps:
        step_id = step.get("id")
        depends_on = step.get("depends_on")

        # dependency check — skip if dependency failed
        if depends_on and depends_on in failed_ids:
            msg = f"Skipped {step.get('action')} because {depends_on} failed."
            print(f"[DEBUG] run_actions: {msg}")
            results.append(msg)
            if step_id:
                failed_ids.add(step_id)
            continue

        # {{stepX.result}} substitution
        parameter = step.get("parameter")
        if parameter and isinstance(parameter, str) and "{{" in parameter:
            import re
            def substitute(match):
                ref_id = match.group(1)
                return str(step_results.get(ref_id, match.group(0)))
            parameter = re.sub(r"\{\{(\w+)\.result\}\}", substitute, parameter)
            print(f"[DEBUG] run_actions: substituted parameter={parameter!r}")

        print(f"[DEBUG] run_actions: executing action={step['action']} parameter={parameter!r} id={step_id}")

        try:
            result = execute(step["action"], parameter)
        except Exception as e:
            print(f"[DEBUG] run_actions: EXCEPTION in execute: {e!r}")
            result = f"Something went wrong running {step['action']}: {e}"

        # click confirmation — pause chain, store state
        if isinstance(result, dict) and result.get("needs_click_confirmation"):
            pending_action = "click_confirmed"
            pending_parameter = result["retry_parameter"]
            pending_execute = result["_execute"]
            msg = f"Are you sure you want to click '{result['element_text']}'?"
            results.append(msg)
            # store partial results so chain can resume later if needed
            if step_id:
                step_results[step_id] = None
                failed_ids.add(step_id)
            break

        # store result by id for downstream substitution
        if step_id:
            step_results[step_id] = result

        # track failures for dependent steps
        if isinstance(result, str) and (
            result.startswith("Couldn't") or
            result.startswith("I couldn't") or
            result.startswith("Something went wrong") or
            result.startswith("Skipped")
        ):
            if step_id:
                failed_ids.add(step_id)

        results.append(result)

    return results

def handle_response(response):
    global session_start_time, pending_action, pending_parameter, akira_speaking

    DANGEROUS_ACTIONS = {
        "close_application", "shutdown", "restart", "hibernate",
        "delete_files", "move_files", "edit_file", "uninstall_application"
    }

    if response["mode"] == "command":
        # Safety net — never run dangerous actions without confirmation
        if response.get("actions") or response.get("action"):
            actions_to_check = response.get("actions", [])
            if response.get("action"):
                actions_to_check = [{"action": response["action"], "parameter": response.get("parameter")}]
            unsafe = [a for a in actions_to_check if a["action"] in DANGEROUS_ACTIONS]
            safe = [a for a in actions_to_check if a["action"] not in DANGEROUS_ACTIONS]
            if unsafe and not response.get("confirmation_required"):
                response["confirmation_required"] = True
                response["pending_actions"] = unsafe
                response["actions"] = safe
                response.pop("action", None)
                response.pop("parameter", None)
                response["confirmation_message"] = "Just confirming before I do that."
            if safe and not response.get("confirmation_required"):
                run_results = run_actions({"actions": safe})
            elif not unsafe:
                run_results = run_actions(response)
            else:
                run_results = []

            # click_element can discover risk only after matching — if it did,
            # override whatever Akira originally planned to say with the real question.
            if pending_action == "click" and pending_parameter and run_results:
                response["response"] = run_results[-1]
            elif run_results and any(isinstance(r, str) and r.startswith("I couldn't find") for r in run_results):
                response["response"] = run_results[-1]
            elif run_results and any(isinstance(r, str) and r.startswith("Couldn't click") for r in run_results):
                response["response"] = run_results[-1]

        if response.get("confirmation_required") and response.get("pending_actions"):
            pending_action = response["pending_actions"]
            pending_parameter = None
        elif response.get("confirmation_required") and response.get("action"):
            pending_action = response["action"]
            pending_parameter = response.get("parameter")

        speak_and_wait(response["response"])

        if response.get("end_session"):
            flush_stream()
            claude_handler.clear_history()
            return False

        flush_stream()
        time.sleep(0.5)
        session_start_time = time.time()
        return True

    elif response["mode"] == "conversation":
        if response["end_session"]:
            speak_and_wait(response["response"])
            claude_handler.clear_history()
            return False
        speak_and_wait(response["response"])
        flush_stream()
        time.sleep(0.5)
        session_start_time = time.time()
        return True

    return False


def get_akira_response(text):
    global pending_action, pending_parameter, pending_execute

    if pending_action is not None:
        confirmed = claude_handler.ask_confirmation(text)
        if confirmed:
            if pending_action == "click_confirmed" and pending_execute is not None:
                try:
                    pending_execute()
                    speak_text = "Done."
                except Exception as e:
                    print(f"[DEBUG] get_akira_response: EXCEPTION in pending_execute: {e!r}")
                    speak_text = f"Couldn't click that: {e}"
                pending_action = None
                pending_parameter = None
                pending_execute = None
                speak_and_wait(speak_text)
                return None
            else:
                actions = pending_action if isinstance(pending_action, list) else [{"action": pending_action, "parameter": pending_parameter}]
                pending_action = None
                pending_parameter = None
                pending_execute = None
                run_actions({"actions": actions})
                speak_and_wait("Done.")
                return None
        else:
            pending_action = None
            pending_parameter = None
            pending_execute = None

    try:
        raw = claude_handler.ask_akira(text).replace("```json", "").replace("```", "").strip()
        if not raw:
            return {"mode": "conversation", "response": "Sorry, having trouble connecting right now.", "end_session": False}
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[DEBUG] get_akira_response: JSONDecodeError: {e!r} | raw was: {raw!r}")
        return {"mode": "conversation", "response": "Something went wrong on my end. Say that again.", "end_session": False}

vad_thread = threading.Thread(target=vad_listener, daemon=True)
vad_thread.start()

while True:
    current_time = time.time()
    if session_active and (current_time - session_start_time) < SESSION_TIMEOUT:
        with vad_buffer_lock:
            if user_speaking.is_set() and len(vad_audio_buffer) > 0:
                pre_audio = np.concatenate(vad_audio_buffer)
                vad_audio_buffer.clear()
                user_speaking.clear()
            else:
                pre_audio = None
                vad_audio_buffer.clear()
        r = record_command(pre_audio=pre_audio)
        if r is None:
            session_active = False
            oww_model.reset()
            continue
        text = transcribe_command(r)
        if not text:
            continue
        response = get_akira_response(text)
        if not response:
            continue
        print(response)
        session_active = handle_response(response)
        if session_active:
            print("session continuing")
        else:
            oww_model.reset()
    else:
        session_active = False
        audio_chunk = stream.read(1280, exception_on_overflow=False)
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
        prediction = oww_model.predict(audio_np)
        score = list(prediction.values())[0]
        current_time = time.time()
        if score > 0.2 and (current_time - last_activation_time) > COOLDOWN_TIME:
            print("Wake word detected!")
            winsound.Beep(1000, 200)
            last_activation_time = time.time()
            r = record_command()
            if r is None:
                continue
            text = transcribe_command(r)
            if not text:
                continue
            response = get_akira_response(text)
            if not response:
                continue
            print(response)
            session_active = handle_response(response)
            if session_active:
                last_activation_time = time.time()
                session_start_time = time.time()
                oww_model.reset()