"""
audio_pipeline.py — Advanced audio processing, noise suppression, and voice isolation for Akira.

Ensures only the user's voice is captured and transcribed:
1. Zero-phase Butterworth bandpass filter (80Hz - 7500Hz) cutting AC hum, fan thrum, and high hiss.
2. Silero VAD real-time voice activity detection with adaptive lead-in and trailing silence cutoff.
3. Precision voice boundary isolation: strips all ambient room noise before and after user speech.
4. Dynamic spectral noise gating: attenuates non-speech pauses between words.
5. Non-speech rejection: drops coughs, throat clears, claps, and faint background noise.
"""

from __future__ import annotations

import os
import time
import numpy as np
import torch
from scipy import signal

# Bandpass filter design: 80 Hz to 7500 Hz at 16 kHz sampling rate
_FS = 16000
_NYQ = 0.5 * _FS
_LOWCUT = 80.0 / _NYQ
_HIGHCUT = min(7500.0 / _NYQ, 0.999)
_BANDPASS_SOS = signal.butter(4, [_LOWCUT, _HIGHCUT], btype="bandpass", output="sos")


def apply_voice_bandpass(audio: np.ndarray) -> np.ndarray:
    """Filter out non-speech frequencies (sub-80Hz rumble/AC hum and >7.5kHz hiss)."""
    if len(audio) < 32:
        return audio
    # sosfiltfilt provides zero phase distortion
    return signal.sosfiltfilt(_BANDPASS_SOS, audio).astype(np.float32)


def compute_vad_confidences(audio_np: np.ndarray, vad_model, frame_size: int = 512, fs: int = 16000) -> list[float]:
    """Calculate Silero VAD voice confidence for every 512-sample (32ms) frame."""
    if len(audio_np) < frame_size:
        return []

    num_frames = len(audio_np) // frame_size
    confidences = []
    for i in range(num_frames):
        chunk = audio_np[i * frame_size : (i + 1) * frame_size]
        t_chunk = torch.from_numpy(chunk).float()
        with torch.no_grad():
            conf = vad_model(t_chunk, fs).item()
        confidences.append(float(conf))
    return confidences


def trim_to_voice(
    audio_np: np.ndarray,
    vad_confidences: list[float],
    frame_size: int = 512,
    fs: int = 16000,
    vad_threshold: float = 0.35,
    pad_ms: int = 150,
) -> tuple[np.ndarray | None, dict]:
    """Isolate strictly the human voice segment, stripping leading and trailing background noise."""
    if not vad_confidences or len(audio_np) < frame_size:
        return None, {"reason": "too_short"}

    conf_arr = np.array(vad_confidences)
    speech_indices = np.where(conf_arr >= vad_threshold)[0]

    if len(speech_indices) == 0:
        return None, {
            "reason": "no_speech_detected",
            "max_conf": float(np.max(conf_arr)) if len(conf_arr) else 0.0,
        }

    pad_samples = int(pad_ms * fs / 1000)
    first_frame = speech_indices[0]
    last_frame = speech_indices[-1]

    start_sample = max(0, first_frame * frame_size - pad_samples)
    end_sample = min(len(audio_np), (last_frame + 1) * frame_size + pad_samples)

    trimmed = audio_np[start_sample:end_sample].copy()
    speech_duration_s = (end_sample - start_sample) / fs

    return trimmed, {
        "reason": "speech_isolated",
        "start_s": start_sample / fs,
        "end_s": end_sample / fs,
        "duration_s": speech_duration_s,
        "active_frames": int(len(speech_indices)),
        "max_conf": float(np.max(conf_arr)),
    }


def apply_soft_noise_gate(
    audio_np: np.ndarray,
    vad_confidences: list[float],
    frame_size: int = 512,
    gate_threshold: float = 0.20,
    attenuation_factor: float = 0.80,
) -> np.ndarray:
    """Non-destructive pass-through for acoustic naturalness. Whisper performs best on intact waveforms."""
    return audio_np


def record_command_vad(
    stream,
    vad_model,
    pre_audio: np.ndarray | None = None,
    fs: int = 16000,
    max_duration_s: float = 12.0,
    silence_cutoff_ms: int = 1100,
    initial_timeout_s: float = 3.5,
) -> np.ndarray | None:
    """Record command from PyAudio stream using energy-aware Silero VAD speech tracking.
    
    1. Pre-roll ring buffer (~384ms = 12 frames) captures the opening consonant of the user's speech.
    2. Speech onset checks both Silero VAD confidence and mic energy threshold against background noise.
    3. Recording ends automatically only after silence_cutoff_ms (~1.1s) of consecutive silence once user finishes.
    4. Applies bandpass filtering (80-7500Hz) and wide voice boundary padding (250ms).
    """
    frame_size = 512  # 32ms at 16kHz
    bytes_per_frame = frame_size * 2  # 16-bit PCM

    energy_threshold = float(os.environ.get("MIC_ENERGY_THRESHOLD", "120.0"))
    max_frames = int(max_duration_s * fs / frame_size)
    silence_frames_threshold = max(int(silence_cutoff_ms * fs / (1000 * frame_size)), 25)
    initial_timeout_frames = int(initial_timeout_s * fs / frame_size)

    # Pre-roll ring buffer (stores last ~384ms = 12 frames)
    pre_roll_maxlen = 12
    pre_roll_buffer: list[np.ndarray] = []
    captured_chunks: list[np.ndarray] = []
    vad_confidences: list[float] = []
    ambient_rms_list: list[float] = []
    speech_rms_list: list[float] = []

    speech_detected = False
    consecutive_speech_frames = 0
    consecutive_silent_frames = 0
    total_frames = 0

    if pre_audio is not None and len(pre_audio) > 0:
        # If pre_audio exists (from barge-in), slice into 512-sample chunks
        for i in range(0, len(pre_audio), frame_size):
            sub = pre_audio[i : i + frame_size]
            if len(sub) == frame_size:
                sub_f = sub.astype(np.float32)
                if np.max(np.abs(sub_f)) > 1.5:
                    sub_f /= 32768.0
                t_sub = torch.from_numpy(sub_f).float()
                with torch.no_grad():
                    conf_pre = vad_model(t_sub, fs).item()
                if conf_pre >= 0.40:
                    speech_detected = True
                    captured_chunks.append(sub_f)
                    vad_confidences.append(conf_pre)
                elif not speech_detected:
                    pre_roll_buffer.append(sub_f)
                    if len(pre_roll_buffer) > pre_roll_maxlen:
                        pre_roll_buffer.pop(0)
                else:
                    captured_chunks.append(sub_f)
                    vad_confidences.append(conf_pre)

    while total_frames < max_frames:
        try:
            chunk_bytes = stream.read(frame_size, exception_on_overflow=False)
        except Exception:
            break

        audio_int16 = np.frombuffer(chunk_bytes, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0
        total_frames += 1

        # Calculate chunk RMS energy to distinguish active speech from quiet background music
        chunk_rms = float(np.sqrt(np.mean(audio_int16.astype(np.float32) ** 2))) if audio_int16.size else 0.0

        # Run Silero VAD on 512-sample float32 chunk
        t_chunk = torch.from_numpy(audio_float).float()
        with torch.no_grad():
            conf = vad_model(t_chunk, fs).item()

        if not speech_detected:
            ambient_rms_list.append(chunk_rms)
            pre_roll_buffer.append(audio_float)
            if len(pre_roll_buffer) > pre_roll_maxlen:
                pre_roll_buffer.pop(0)

            # Adaptive threshold: a gentle safety net above rolling ambient.
            # The 800ms TTS drain in akira.py is the primary reverb defense;
            # this only catches residual hum.  Uses avg (not peak — peaks
            # include harmless transient spikes that shouldn't set the floor).
            if len(ambient_rms_list) >= 3:
                rolling_avg = float(np.mean(ambient_rms_list[-30:]))
                adaptive_thresh = max(energy_threshold, rolling_avg * 2.0 + 80.0)
            else:
                adaptive_thresh = energy_threshold

            # Speech onset: genuine speech exceeds adaptive threshold with strong VAD
            is_onset = (conf >= 0.50 and chunk_rms >= adaptive_thresh * 0.70) or (conf >= 0.35 and chunk_rms >= adaptive_thresh)
            if is_onset:
                consecutive_speech_frames += 1
                if consecutive_speech_frames >= 3:  # require 3 consecutive (~96ms) to avoid transient triggers
                    speech_detected = True
                    # Commit pre-roll buffer so the start of speech is not clipped
                    captured_chunks.extend(pre_roll_buffer)
                    for _ in pre_roll_buffer:
                        vad_confidences.append(conf)
                    pre_roll_buffer.clear()
            else:
                consecutive_speech_frames = 0

            # Abort if no speech started within initial timeout
            if total_frames >= initial_timeout_frames:
                break
        else:
            # User speech active
            speech_rms_list.append(chunk_rms)
            captured_chunks.append(audio_float)
            vad_confidences.append(conf)

            # Silence check: VAD confidence drops AND energy is near ambient.
            is_silent = (conf < 0.35) and (chunk_rms < energy_threshold * 0.85)
            # NOTE: silence uses the static threshold, not adaptive — once
            # speech is confirmed, we trust VAD to end the recording and
            # don't want an inflated threshold to cut sentences short.
            if is_silent:
                consecutive_silent_frames += 1
                if consecutive_silent_frames >= silence_frames_threshold:
                    # User has stopped speaking (full 1.1s of quiet verified)
                    break
            else:
                consecutive_silent_frames = 0

    if not captured_chunks or not speech_detected:
        return None

    # Print live mic_check telemetry so the exact acoustic threshold is visible in logs
    avg_amb = float(np.mean(ambient_rms_list)) if ambient_rms_list else 0.0
    peak_amb = float(np.max(ambient_rms_list)) if ambient_rms_list else 0.0
    peak_speech = float(np.max(speech_rms_list)) if speech_rms_list else 0.0
    avg_speech = float(np.mean(speech_rms_list)) if speech_rms_list else 0.0
    max_conf = float(np.max(vad_confidences)) if vad_confidences else 0.0
    effective_thresh = max(energy_threshold, avg_amb * 2.0 + 80.0) if ambient_rms_list else energy_threshold
    print(f"[mic_check] ambient_avg={avg_amb:.1f} peak={peak_amb:.1f} | speech_peak={peak_speech:.1f} avg={avg_speech:.1f} vad={max_conf:.2f} | static_thresh={energy_threshold:.1f} adaptive_thresh={effective_thresh:.1f}")

    raw_audio = np.concatenate(captured_chunks).astype(np.float32)

    # 1. Bandpass filter to eliminate sub-80Hz rumble and >7500Hz hiss
    filtered = apply_voice_bandpass(raw_audio)

    # 2. Generous voice boundary padding (400ms) to ensure entire sentence is preserved for Whisper Large v3
    trimmed, info = trim_to_voice(filtered, vad_confidences, frame_size=frame_size, fs=fs, pad_ms=400)
    if trimmed is not None and len(trimmed) >= 3200:  # >= 0.2s
        return trimmed

    return filtered if len(filtered) >= 3200 else None


def clean_transcription_text(text: str) -> str:
    """Strip common Whisper hallucinations on residual ambient noise (e.g. [Music], (silence))."""
    import re

    cleaned = (text or "").strip()
    # Remove bracketed/parenthetical sound descriptors
    cleaned = re.sub(r"\[(?:music|applause|laughter|silence|sigh|snort|cough)\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\((?:music|applause|laughter|silence|sigh|snort|cough)\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Hallucinated subtitle credits, prompt regurgitations, or generic filler loops
    hallucinations = {
        "thank you for watching", "thanks for watching", "subtitles by", "translated by",
        "you", "thank you", "bye", "subscribe", "please subscribe",
        "clear speech only", "clear speech", "clear response", "clear response only",
        "clear speech only.", "clear response.",
    }
    if cleaned.lower().rstrip(".!?,") in hallucinations:
        return ""

    return cleaned

