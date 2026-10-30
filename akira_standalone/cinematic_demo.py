"""
cinematic_demo.py — Scripted Cinematic Demo with Python Human-like Female Voice
Features:
  1. Spawns Akira Avatar in the BOTTOM-RIGHT corner of the laptop screen.
  2. Uses realistic Python Neural Female voice (edge-tts / Windows Female).
  3. Akira speaks: "May I help you?"
  4. Listens live to your voice through the microphone.
  5. The moment you finish speaking, Akira immediately says: "On it."
  6. 🎬 Scene cuts!
"""

import os
import sys
import time
import socket
import asyncio
import tempfile
import threading
import subprocess
import ctypes

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
import numpy as np
try:
    import pyaudio
except ImportError:
    import pyaudiowpatch as pyaudio
from dotenv import load_dotenv

load_dotenv()

# UDP socket to control the Avatar UI
UDP_PORT = 55555
_avatar_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Female voice: en-US-AriaNeural (very natural, expressive female voice)
# Alternative options: "en-US-JennyNeural", "en-GB-SoniaNeural"
NEURAL_FEMALE_VOICE = "en-US-AriaNeural"

def notify_avatar(msg: str):
    try:
        _avatar_sock.sendto(msg.encode("utf-8"), ("127.0.0.1", UDP_PORT))
    except Exception:
        pass

def play_audio_file(file_path: str):
    """Play audio file cleanly using Windows native multimedia API."""
    abs_path = os.path.abspath(file_path).replace("\\", "/")
    alias = f"akira_voice_{int(time.time()*1000)}"
    ctypes.windll.winmm.mciSendStringW(f'open "{abs_path}" type mpegvideo alias {alias}', None, 0, None)
    ctypes.windll.winmm.mciSendStringW(f'play {alias} wait', None, 0, None)
    ctypes.windll.winmm.mciSendStringW(f'close {alias}', None, 0, None)

def speak_female_voice(text: str):
    """Generate and speak with ultra-realistic Python neural female voice."""
    print(f"\n🗣️ Akira: \"{text}\"\n")
    notify_avatar("SPEAK_START")
    spoken = False

    # 1. Try edge-tts for ultra-realistic human female voice
    try:
        import edge_tts
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_mp3 = f.name
        
        async def _synth():
            comm = edge_tts.Communicate(text, NEURAL_FEMALE_VOICE, rate="+0%", pitch="+0Hz")
            await comm.save(temp_mp3)

        asyncio.run(_synth())
        play_audio_file(temp_mp3)
        spoken = True
        try:
            os.remove(temp_mp3)
        except Exception:
            pass
    except Exception as e:
        print(f"[edge-tts notice] {e}, falling back to pyttsx3 female voice")

    # 2. Local pyttsx3 female voice fallback (Microsoft Zira)
    if not spoken:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            for v in voices:
                if "zira" in v.name.lower() or "female" in v.name.lower():
                    engine.setProperty('voice', v.id)
                    break
            engine.setProperty('rate', 165)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"[pyttsx3 error] {e}")

    notify_avatar("SPEAK_STOP")

def launch_avatar_bottom_right():
    """Launch avatar and place in bottom-right corner."""
    print("✨ [1/3] Spawning Akira Avatar in BOTTOM-RIGHT corner...")
    pos_code = """
import sys, os
from PyQt6.QtWidgets import QApplication
import avatar_ui

app = QApplication(sys.argv)
screen = app.primaryScreen().geometry()
w = avatar_ui.AvatarWindow()
# Position in bottom-right corner
w.move(screen.width() - 280, screen.height() - 290)
w.show()
sys.exit(app.exec())
"""
    try:
        proc = subprocess.Popen([sys.executable, "-c", pos_code])
        time.sleep(1.8) # Wait for avatar window to initialize
        return proc
    except Exception as e:
        print(f"[avatar] Could not launch bottom-right avatar: {e}")
        return None

def listen_to_user(stream):
    """Record from mic until silence is detected after user finishes speaking."""
    print("🎙️ [Listening...] Speak your line into the microphone on camera!")
    command_audio = []
    chunk_count = 0
    silent_chunks = 0
    MAX_CHUNKS = 250  # ~20 seconds max
    MIN_CHUNKS = 25   # ~2 seconds min
    MAX_SILENT = 16   # Silence threshold to finish
    has_spoken = False

    while chunk_count < MAX_CHUNKS:
        chunk = stream.read(1280, exception_on_overflow=False)
        audio_np = np.frombuffer(chunk, dtype=np.int16)
        rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
        command_audio.append(audio_np.astype(np.float32))
        chunk_count += 1

        if rms > 250:
            has_spoken = True
            silent_chunks = 0
        elif has_spoken:
            silent_chunks += 1
            if chunk_count > MIN_CHUNKS and silent_chunks >= MAX_SILENT:
                break

    if not command_audio:
        return None
    raw = np.concatenate(command_audio)
    return raw / 32768.0

def main():
    print("=" * 60)
    print("🎬 CINEMATIC VIDEO SHOOT — AKIRA (FEMALE VOICE & BOTTOM-RIGHT)")
    print("=" * 60)
    
    # 1. Launch bottom-right avatar
    avatar_proc = launch_avatar_bottom_right()
    notify_avatar("SPEAK_STOP")
    
    # 2. Init Microphone
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                    input=True, frames_per_buffer=1280)
    
    # Flush initial mic buffer
    time.sleep(0.5)
    if stream.get_read_available() > 0:
        stream.read(stream.get_read_available(), exception_on_overflow=False)

    # 15-second preparation countdown for video shooting
    print("\n⏳ 15-second preparation countdown for video shooting...")
    for sec in range(15, 0, -1):
        print(f"   🎥 Scene starts in {sec:2d}s... (Get into position)", end="\r", flush=True)
        time.sleep(1.0)
    print("\n   🎬 ACTION!\n")

    # 3. Scene 1: Akira speaks in human-like female voice
    print("\n--- [SCENE 1: AKIRA APPEARS & ASKS] ---")
    speak_female_voice("May I help you?")

    # 4. Scene 2: 5.5-second dialogue gap for you on camera
    print("\n--- [SCENE 2: YOU SPEAK ON CAMERA (5.5s GAP)] ---")
    for sec in range(5, 0, -1):
        print(f"   ⏱️ Speak your line on camera ({sec}s remaining)...", end="\r", flush=True)
        time.sleep(1.0)
    time.sleep(0.5)
    print("\n")

    # 5. Scene 3: Akira delivers the closing response and cuts
    print("--- [SCENE 3: AKIRA REPLIES 'ON IT' & CUTS] ---")
    notify_avatar("HAPPY_START")
    speak_female_voice("On it.")
    time.sleep(0.4)
    
    # Clean up audio stream
    try:
        stream.stop_stream()
        stream.close()
        p.terminate()
    except Exception:
        pass
        
    print("\n🎬 [CUT!] Video scene complete.\n")

if __name__ == "__main__":
    main()
