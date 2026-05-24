import sounddevice as sd
import soundfile as sf
import os

os.makedirs("samples", exist_ok=True)

for i in range(20):
    input(f"Press Enter to record sample {i+1}/20, then say 'Sensei' clearly...")
    audio = sd.rec(int(2 * 16000), samplerate=16000, channels=1, dtype='int16')
    sd.wait()
    sf.write(f"samples/sensei_{i+1}.wav", audio, 16000)
    print(f"Sample {i+1} saved.")

print("All samples recorded!")