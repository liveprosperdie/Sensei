"""
tests/test_audio_pipeline.py
Unit tests verifying voice isolation, noise filtering, bandpass filtering, and transcription cleanup.
"""

import os
import sys
import unittest
import numpy as np
import torch
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import audio_pipeline


class TestAudioPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _jit_path = os.path.expanduser(r"~/.cache/torch/hub/snakers4_silero-vad_master/src/silero_vad/data/silero_vad.jit")
        if os.path.exists(_jit_path):
            cls.vad_model = torch.jit.load(_jit_path)
        else:
            cls.vad_model, _ = torch.hub.load("snakers4/silero-vad", "silero_vad")

    def test_bandpass_filter_attenuates_low_and_high_noise(self):
        """Bandpass filter removes 40Hz electrical/fan rumble and 7900Hz high hiss while preserving 1kHz voice."""
        fs = 16000
        t = np.linspace(0, 0.5, int(0.5 * fs), endpoint=False)
        
        # 40Hz noise (should be strongly attenuated by 80Hz highpass)
        rumble_40hz = np.sin(2 * np.pi * 40 * t).astype(np.float32)
        filtered_rumble = audio_pipeline.apply_voice_bandpass(rumble_40hz)
        rumble_energy_before = np.sqrt(np.mean(rumble_40hz ** 2))
        rumble_energy_after = np.sqrt(np.mean(filtered_rumble ** 2))
        self.assertLess(rumble_energy_after, rumble_energy_before * 0.25, "40Hz rumble should be attenuated by >12dB")

        # 1000Hz speech formant (should be preserved with minimal loss)
        voice_1khz = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        filtered_voice = audio_pipeline.apply_voice_bandpass(voice_1khz)
        voice_energy_before = np.sqrt(np.mean(voice_1khz ** 2))
        voice_energy_after = np.sqrt(np.mean(filtered_voice ** 2))
        self.assertAlmostEqual(voice_energy_after, voice_energy_before, delta=0.08, msg="1kHz voice should pass unattenuated")

    def test_voice_boundary_trimming_drops_ambient_noise(self):
        """Trimming algorithm isolates voice region and strips leading/trailing ambient noise."""
        fs = 16000
        # 0.8s noise + 1.2s voice + 1.0s noise
        n_lead = np.random.randn(int(0.8 * fs)).astype(np.float32) * 0.01
        
        t_v = np.linspace(0, 1.2, int(1.2 * fs), endpoint=False)
        voice = (0.3 * np.sin(2 * np.pi * 200 * t_v) + 0.2 * np.sin(2 * np.pi * 400 * t_v)).astype(np.float32)
        
        n_trail = np.random.randn(int(1.0 * fs)).astype(np.float32) * 0.01
        
        full_audio = np.concatenate([n_lead, voice, n_trail])
        confs = audio_pipeline.compute_vad_confidences(full_audio, self.vad_model, fs=fs)
        
        trimmed, info = audio_pipeline.trim_to_voice(full_audio, confs, fs=fs, pad_ms=100)
        self.assertIsNotNone(trimmed)
        self.assertLess(len(trimmed), len(full_audio), "Trimmed audio should be shorter than full audio")
        # Assert leading noise was dropped (start_s should be around ~0.7-0.9s)
        self.assertGreater(info["start_s"], 0.65, "Leading ambient noise should be stripped")
        self.assertGreater(info["duration_s"], 0.4, "Voice segment should be extracted")

    def test_clean_transcription_text(self):
        """Whisper bracketed hallucinations and generic loop artifacts are cleanly stripped."""
        raw_text = "[Music] open Google Chrome and play music [Applause]"
        cleaned = audio_pipeline.clean_transcription_text(raw_text)
        self.assertEqual(cleaned, "open Google Chrome and play music")

        hallucination = "Thank you for watching."
        self.assertEqual(audio_pipeline.clean_transcription_text(hallucination), "")


if __name__ == "__main__":
    unittest.main()
