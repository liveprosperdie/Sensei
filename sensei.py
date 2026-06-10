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


def handle_response(response):
    """Process a parsed Akira response. Returns True if session should continue, False if it should end."""
    global session_start_time, pending_action, pending_parameter,akira_speaking

    if response["mode"] == "command":
        if response["end_session"]:
            execute(response["action"], response["parameter"])
            akira_speaking = True
            claude_handler.speak(response["response"])
            akira_speaking = False
            user_speaking.clear()
            claude_handler.clear_history()
            return False
        if response["confirmation_required"]:
            pending_action = response["action"]
            pending_parameter = response["parameter"]
            akira_speaking = True
            claude_handler.speak(response["response"])
            akira_speaking = False
            user_speaking.clear()
        else:
            execute(response["action"], response["parameter"])
            akira_speaking = True
            claude_handler.speak(response["response"])
            akira_speaking = False
            user_speaking.clear()
        flush_stream()
        time.sleep(0.5)
        session_start_time = time.time()
        return True

    elif response["mode"] == "conversation":
        if response["end_session"]:
            akira_speaking = True
            claude_handler.speak(response["response"])
            akira_speaking = False
            user_speaking.clear()
            claude_handler.clear_history()
            return False
        akira_speaking = True
        claude_handler.speak(response["response"])
        akira_speaking = False
        user_speaking.clear()
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
        print(f"DEBUG: user_speaking={user_speaking.is_set()}, buffer_len={len(vad_audio_buffer)}, pre_audio={'yes' if pre_audio is not None else 'no'}")
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
                oww_model.reset()