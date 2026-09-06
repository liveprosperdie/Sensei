# Akira Low-Latency Voice Engine Setup Guide

This branch (`feature/voice-engine`) contains the optimized, sub-second Text-to-Speech (TTS) voice pipeline for Akira.

## Quick Installation (Minimal Effort)

To install all required voice dependencies in one step:

```bash
pip install -r requirements.txt
```

### Voice Architecture & Features

1. **Primary Neural Engine (Default - Ultra Low Latency ~1.2s)**:
   - Powered by `edge-tts` (`en-US-AvaNeural`) with `sounddevice` and `soundfile` streaming playback.
   - Provides natural, high-quality female voice synthesis without GPU overhead.

2. **On-Device Local Inference (Kokoro 82M Option)**:
   - Pre-wired support for `kokoro-onnx` / `kokoro` for fully offline, private local speech synthesis.

3. **Instant Local Fallback (0ms Latency)**:
   - Built-in fallback to Windows native SAPI5 (`pyttsx3`) if offline or network unreachable.

## Testing the Voice Engine

Run the standalone voice verification script:

```bash
python -c "import claude_handler; claude_handler.speak('Hello! Akira low latency voice engine is active.')"
```
