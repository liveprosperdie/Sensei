"""calibrate_mic.py — Interactive Microphone & Background Music Energy Calibrator.

Usage:
    python calibrate_mic.py

Measures ambient noise (room acoustics, background music, fan noise) and compares
it against spoken voice energy to calculate and persist the optimal MIC_ENERGY_THRESHOLD.
"""

from __future__ import annotations

import os
import sys
import time
import numpy as np
import pyaudio


def measure_rms_segment(stream, duration_s: float, chunk_size: int = 1280) -> tuple[float, float, list[float]]:
    """Record audio for duration_s and return (avg_rms, max_rms, list_of_rms)."""
    num_chunks = int(duration_s * 16000 / chunk_size)
    rms_values = []

    for _ in range(num_chunks):
        try:
            chunk = stream.read(chunk_size, exception_on_overflow=False)
            audio_np = np.frombuffer(chunk, dtype=np.int16)
            rms = float(np.sqrt(np.mean(audio_np.astype(np.float32) ** 2)))
            rms_values.append(rms)
        except Exception:
            continue

    if not rms_values:
        return 0.0, 0.0, []

    return float(np.mean(rms_values)), float(np.max(rms_values)), rms_values


def update_env_file(key: str, value: str) -> None:
    """Safely update or append a key=value pair in .env."""
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".env"))
    lines = []
    found = False

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}=") or line.strip().startswith(f"export {key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def main():
    print("=" * 70)
    print("   AKIRA MICROPHONE & BACKGROUND MUSIC CALIBRATION TOOL")
    print("=" * 70)
    print("This tool measures background noise (fans, music) and your speaking voice")
    print("to calculate the exact energy threshold needed so Akira never cuts you off\n")

    p = pyaudio.PyAudio()
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=1280,
        )
    except Exception as e:
        print(f"[ERROR] Could not open microphone stream: {e}")
        p.terminate()
        return

    try:
        # Step 1: Ambient / Background Music
        print("\n[STEP 1 / 2] Measuring Ambient Background Level...")
        print(" -> Play your normal background music / let room ambient run.")
        print(" -> Please STAY SILENT for 3 seconds...")
        for i in range(3, 0, -1):
            print(f"    Starting in {i}...", end="\r", flush=True)
            time.sleep(1.0)
        print("    Recording ambient sound now...                    ")

        amb_avg, amb_max, _ = measure_rms_segment(stream, duration_s=3.0)
        print(f" -> Ambient / Music: Avg RMS = {amb_avg:.1f} | Peak RMS = {amb_max:.1f}")

        # Step 2: Voice Level
        print("\n[STEP 2 / 2] Measuring Your Speaking Voice...")
        print(" -> Keep your background music playing.")
        print(" -> Speak a normal command out loud (e.g. 'Akira, close Brave and open YouTube').")
        for i in range(3, 0, -1):
            print(f"    Starting in {i}...", end="\r", flush=True)
            time.sleep(1.0)
        print("    Speak NOW! (listening for 4 seconds)...           ")

        voice_avg, voice_max, _ = measure_rms_segment(stream, duration_s=4.0)
        print(f" -> Voice + Music:   Avg RMS = {voice_avg:.1f} | Peak RMS = {voice_max:.1f}")

        # Calculation
        # The threshold should sit comfortably above the ambient background peak,
        # but safely below normal voice amplitude.
        margin = max((voice_max - amb_max) * 0.35, 30.0)
        recommended_threshold = round(max(amb_max + 25.0, amb_avg * 1.5 + 30.0, 90.0))

        if voice_max < amb_max:
            print("\n[WARNING] Your voice peak was lower than background music!")
            print("Please speak closer to the mic or lower the background speaker volume.")
            recommended_threshold = max(round(amb_max + 40.0), 120)

        print("\n" + "-" * 70)
        print(f"CALIBRATION RESULTS:")
        print(f" * Ambient / Background Noise Peak: {amb_max:.1f}")
        print(f" * Your Voice Peak:                 {voice_max:.1f}")
        print(f" * Recommended MIC_ENERGY_THRESHOLD: {recommended_threshold}")
        print("-" * 70)

        update_env_file("MIC_ENERGY_THRESHOLD", str(recommended_threshold))
        print(f"[OK] Saved MIC_ENERGY_THRESHOLD={recommended_threshold} into .env successfully.")
        print("Akira will now use this threshold for instant, accurate voice isolation.\n")

    finally:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        p.terminate()


if __name__ == "__main__":
    main()
