import time
import json
import torch
import whisper
import pyaudio
import winsound
import numpy as np
import openwakeword
import claude_handler
from executor import execute
from openwakeword import Model as WakeModel

device = "cuda" if torch.cuda.is_available() else "cpu"
whisper_model = whisper.load_model("base", device=device)
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
print("Listening for 'Sensei'...")


def record_command():
    command_audio = []
    chunk_count = 0
    silent_chunks = 15
    MAX_CHUNKS = 200
    MIN_CHUNKS = 60
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
    if np.sqrt(np.mean(command ** 2)) < 100:
        print("record_command: no audio or too quiet")
        return None
    return final_command


def transcribe_command(final_command):
    result = whisper_model.transcribe(final_command, fp16=False, language="en")
    return result["text"].strip()


def flush_stream():
    available = stream.get_read_available()
    if available > 0:
        stream.read(available, exception_on_overflow=False)


def handle_response(response):
    """Process a parsed Akira response. Returns True if session should continue, False if it should end."""
    global session_start_time, pending_action, pending_parameter

    if response["mode"] == "command":
        if response["end_session"]:
            execute(response["action"], response["parameter"])
            claude_handler.speak(response["response"])
            claude_handler.clear_history()
            return False
        if response["confirmation_required"]:
            pending_action = response["action"]
            pending_parameter = response["parameter"]
            claude_handler.speak(response["confirmation_message"] + " Say yes to confirm.")
        else:
            execute(response["action"], response["parameter"])
            claude_handler.speak(response["response"])
        flush_stream()
        time.sleep(0.5)
        session_start_time = time.time()
        return True

    elif response["mode"] == "conversation":
        if response["end_session"]:
            claude_handler.speak(response["response"])
            claude_handler.clear_history()
            return False
        claude_handler.speak(response["response"])
        flush_stream()
        time.sleep(0.5)
        session_start_time = time.time()
        return True

    return False


def get_akira_response(text):
    global pending_action, pending_parameter

    if pending_action is not None:
        if any(word in text.lower() for word in ["yes", "yeah", "yep", "do it", "confirm", "sure"]):
            response = {
                "mode": "command",
                "action": pending_action,
                "parameter": pending_parameter,
                "confirmation_required": False,
                "confirmation_message": None,
                "response": "Done.",
                "end_session": False
            }
            pending_action = None
            pending_parameter = None
            return response
        else:
            pending_action = None
            pending_parameter = None

    raw = claude_handler.ask_akira(text).replace("```json", "").replace("```", "").strip()
    if not raw:
        return None
    return json.loads(raw)


while True:
    current_time = time.time()
    if session_active and (current_time - session_start_time) < SESSION_TIMEOUT:
        r = record_command()
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
                oww_model.reset()