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


def run_actions(response):
    """Execute one action or a list of actions. Returns a list of result strings.
    If any result needs click-confirmation, that's signaled via global pending state
    set here directly (mirrors how handle_response sets pending_action elsewhere)."""
    global pending_action, pending_parameter, pending_execute
    results = []
    steps = response.get("actions", [])
    if not steps and response.get("action"):
        steps = [{"action": response["action"], "parameter": response.get("parameter")}]
    for step in steps:
        result = execute(step["action"], step.get("parameter"))
        if isinstance(result, dict) and result.get("needs_click_confirmation"):
            pending_action = "click_confirmed"
            pending_parameter = result["retry_parameter"]
            pending_execute = result["_execute"]
            results.append(f"Are you sure you want to click '{result['element_text']}'?")
        else:
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
    global pending_action, pending_parameter

    if pending_action is not None:
        confirmed = claude_handler.ask_confirmation(text)
        if confirmed:
            actions = pending_action if isinstance(pending_action, list) else [{"action": pending_action, "parameter": pending_parameter}]
            pending_action = None
            pending_parameter = None
            run_actions({"actions": actions})
            speak_and_wait("Done.")
            return None
        else:
            pending_action = None
            pending_parameter = None

    raw = claude_handler.ask_akira(text).replace("```json", "").replace("```", "").strip()
    if not raw:
        return {"mode": "conversation", "response": "Sorry, having trouble connecting right now.", "end_session": False}
    return json.loads(raw)

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