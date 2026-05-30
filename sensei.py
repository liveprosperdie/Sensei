import os
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
last_activation_time=0.0
COOLDOWN_TIME=3.0
session_active = False
SESSION_TIMEOUT = 20
print("Listening for 'Sensei'...")
session_start_time = 0


def record_command():
    command_audio=[]
    chunk_count=0
    silent_chunks=15
    MAX_CHUNKS=200
    MIN_CHUNKS=60
    MAX_SILENT=15
    while chunk_count < MAX_CHUNKS:
        audio_chunk = stream.read(1280, exception_on_overflow=False)
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
        rms = np.sqrt(np.mean(audio_np.astype(np.float32)**2))
        command_audio.append(audio_np.astype(np.float32))
        chunk_count+=1
        if chunk_count>MIN_CHUNKS: 
            if rms<150:
                silent_chunks+=1
            else:
                silent_chunks=0
            if silent_chunks >= MAX_SILENT:
                break
    if len(command_audio) == 0:
        print("record_command: no audio or too quiet")
        return None
    command=np.concatenate(command_audio)
    final_command=command/32768.0 
    if np.sqrt(np.mean(command**2)) < 100:
        print("record_command: no audio or too quiet")
        return None
    return final_command


def transcribe_command(final_command):
    result=whisper_model.transcribe(final_command,fp16=False, language="en")
    text=result["text"].strip()
    return text


def flush_stream():
    available = stream.get_read_available()
    if available > 0:
        stream.read(available, exception_on_overflow=False)


while True:
    current_time=time.time()
    if session_active and (current_time-session_start_time)<SESSION_TIMEOUT:
        r=record_command()
        if r is None:
            session_active=False
            oww_model.reset()
            continue
        final_command=r
        text=transcribe_command(final_command)
        if not text:
            continue
        result=claude_handler.ask_akira(text).replace("```json","").replace("```","").strip()
        if not result:
            continue
        response=json.loads(result)
        print (response)
        if response["mode"]=="command":
            if response["end_session"]:
                execute(response["action"], response["parameter"]) 
                claude_handler.speak(response["response"])
                claude_handler.clear_history()
                session_active=False
                oww_model.reset()
                continue
            if response["confirmation_required"]:
                claude_handler.speak(response["confirmation_message"])
                flush_stream()
                time.sleep(0.5)
                session_start_time = time.time()
            else:
                execute(response["action"], response["parameter"])
                claude_handler.speak(response["response"])
                flush_stream()
                time.sleep(0.5)
                session_start_time = time.time()
        elif response["mode"]=="conversation":
            if response["end_session"]:
                claude_handler.speak(response["response"])
                claude_handler.clear_history()
                session_active=False
                oww_model.reset()
                continue
            claude_handler.speak(response["response"])
            flush_stream()
            time.sleep(0.5)
            session_start_time = time.time()
        print("session continuing")
        session_active=True
        continue
    else:
        session_active=False
        audio_chunk = stream.read(1280, exception_on_overflow=False)
        audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
        prediction = oww_model.predict(audio_np)
        score = list(prediction.values())[0]
        current_time=time.time()
        if score > 0.2 and (current_time-last_activation_time)>COOLDOWN_TIME:
            print("Wake word detected!")
            winsound.Beep(1000, 200)
            last_activation_time=time.time()
            r=record_command()
            if r is None:
                continue
            final_command=r
            text=transcribe_command(final_command)
            if not text:
                continue
            result=claude_handler.ask_akira(text).replace("```json","").replace("```","").strip()
            if not result:
                continue
            response=json.loads(result)
            print (response)
            if response["mode"]=="command":
                if response["end_session"]:
                    execute(response["action"], response["parameter"]) 
                    claude_handler.speak(response["response"])
                    claude_handler.clear_history()
                    session_active=False
                    oww_model.reset()
                    continue
                if response["confirmation_required"]:
                    claude_handler.speak(response["confirmation_message"])
                    flush_stream()
                    time.sleep(0.5)
                    session_start_time = time.time()
                else:
                    execute(response["action"], response["parameter"])
                    claude_handler.speak(response["response"])
                    flush_stream()
                    time.sleep(0.5)
                    session_start_time = time.time()
                print(response)
            elif response["mode"]=="conversation":
                if response["end_session"]:
                    claude_handler.speak(response["response"])
                    claude_handler.clear_history()
                    session_active=False
                    oww_model.reset()
                    continue
                claude_handler.speak(response["response"])
                flush_stream()
                time.sleep(0.5)
                session_start_time = time.time()
            session_active=True
            last_activation_time=time.time()
            oww_model.reset()