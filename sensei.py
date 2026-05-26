import time
import whisper
import pyaudio
import winsound
import numpy as np
import openwakeword
from openwakeword import Model as WakeModel

whisper_model=whisper.load_model("small")
openwakeword.utils.download_models()
oww_model = WakeModel(wakeword_models=["sensei.onnx"], inference_framework="onnx")

mic = pyaudio.PyAudio()
stream = mic.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1280)
last_activation_time=0.0
COOLDOWN_TIME=3.0
print("Listening for 'Sensei'...")
while True:
    audio_chunk = stream.read(1280, exception_on_overflow=False)
    audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
    prediction = oww_model.predict(audio_np)
    score = list(prediction.values())[0]
    current_time=time.time()
    if score > 0.2 and (current_time-last_activation_time)>COOLDOWN_TIME:
        print("Wake word detected!")
        winsound.Beep(1000, 200)
        last_activation_time=time.time()
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
            continue
        command=np.concatenate(command_audio)
        final_command=command/32768.0
        if np.sqrt(np.mean(command**2)) < 100:
            print("No speech detected, ignoring.")
            continue
        result=whisper_model.transcribe(final_command,fp16=False, language="en")
        text=result["text"].strip()
        print(f"you said {text}")
        last_activation_time=time.time()