import time
import pyaudio
import winsound
import numpy as np
import openwakeword
from openwakeword import Model as WakeModel

openwakeword.utils.download_models()
oww_model = WakeModel(wakeword_models=["sensei.onnx"], inference_framework="onnx")

mic = pyaudio.PyAudio()
stream = mic.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1280)
last_activation_time=0.0
COOLDOWN_TIME=1.0
print("Listening for 'Sensei'...")
while True:
    audio_chunk = stream.read(1280, exception_on_overflow=False)
    audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
    prediction = oww_model.predict(audio_np)
    score = list(prediction.values())[0]
    current_time=time.time()
    print(score)
    if score > 0.2 and (current_time-last_activation_time)>COOLDOWN_TIME:
        print("Wake word detected!")
        winsound.Beep(1000, 200)
        last_activation_time=time.time()
