# AKIRA (SENSEI) — COMPLETE MASTER CONTEXT & HANDOUT FOR NEXT CHAT

> **Generated**: September 18, 2026  
> **Repository**: `D:\Coding\Projects\Sensei`  
> **Primary Purpose**: Immediate, zero-loss continuation of the Akira desktop AI companion in a new chat session.

---

## 1. PROJECT OVERVIEW & CORE ARCHITECTURE

**Akira (Sensei)** is an ultra-fast, voice-first desktop companion for Windows engineered for the **Smart India Hackathon (SIH)**. It executes real OS actions, system controls, browser automation, Office generation, and audio playback with zero paid LLM cost under normal operation.

### Key Architectural Layers:
1. **Tiered Intent Routing & Classifier (`tiered_classifier.py`)**:
   - **Primary Brain**: `openai/gpt-oss-120b` running on Groq (fast, high-capacity, free tier router).
   - **Schema**: Returns single-step or multi-step action envelopes in strict JSON (`mode: "command"`, `actions: [...]`, `pending_actions: [...]`, `confirmation_required: bool`, `response: "..."`).
   - **Context Delta**: Injects only current open windows, browser tabs, and last assistant response to preserve token budget.
2. **Deterministic Guard & Security Engine (`guard.py`, `guard_rules.py`, `security_guard.py`)**:
   - Cryptographically signs and validates action payloads before execution.
   - Protects against codebase self-modification (`akira.py`, `executor.py`, etc.).
   - Gates destructive commands (e.g., `close_application`, `delete_files`, `shutdown_pc`) into `pending_actions` requiring explicit spoken user confirmation.
3. **OS Live Execution Engine (`executor.py`)**:
   - CDP-driven headless/headed Chrome browser automation (pre-warmed for instant execution).
   - Tab switching, YouTube player controls (`youtube_control`), site search (`amazon`, `flipkart`, `github`), and media control.
   - System controls (volume, brightness, task manager, window minimize/maximize, screenshot).
4. **Voice & Audio Pipeline (`akira.py`, `audio_pipeline.py`, `calibrate_mic.py`)**:
   - **Wake Word**: OpenWakeWord listening for `"Akira"`.
   - **Voice Activity Detection**: Silero VAD (PyTorch JIT) for real-time speech boundary tracking.
   - **Speech-to-Text**: Groq Whisper (`whisper-large-v3-turbo`).
   - **Text-to-Speech**: ElevenLabs neural TTS / SAPI5 fallback with instant acoustic barge-in interruption.

---

## 2. DETAILED BREAKDOWN OF WORK COMPLETED IN THIS CHAT

### A. Audio Listening, Silence Timer & Cutoff Fixes
* **The Problem**: Akira was cutting off user speech prematurely (~550ms), mangling phonemes (e.g. hearing *"Close Brave"* as *"brief"* or *"brevo"*), and then hanging for 12 seconds after speech before starting execution.
* **Root Causes Found**:
  1. `silence_cutoff_ms` was set too short (550ms), triggering on natural breathing pauses between words.
  2. A soft noise gate in `audio_pipeline.py` multiplied non-speech frames by `0.15` (-16.5 dB), obliterating soft consonants like "Cl-" and "-ve".
  3. Pre-roll buffer was only 6 frames (192ms) and boundary padding was only 120ms, clipping word edges.
  4. The silence check required `(conf < 0.35) and (chunk_rms < energy_threshold * 0.85)`. When background music or room noise had RMS > 100, the energy condition stayed false, preventing the silence counter from ever incrementing. Akira hung until the 12-second hard safety timeout expired.
* **The Fixes Applied**:
  - **Exact 1.2-Second Post-Speech Countdown Timer**: In `audio_pipeline.py` and `akira.py`, silence is now determined by Silero VAD voice absence (`conf < 0.30`). The moment you stop speaking, an exact 1.2s timer (~37 frames @ 32ms) counts down. If you do not resume speaking within 1.2s, recording ends immediately and execution starts.
  - **Natural Inter-Word Pause Protection**: Pauses of 300ms–600ms between clauses or words do not reset the command.
  - **Removed Destructive Noise Gate**: Non-speech pause audio is no longer attenuated by 85%, leaving natural spectral waveforms intact for Whisper.
  - **Expanded Voice Padding**: Pre-roll buffer widened to `384ms` (12 frames) and boundary padding to `250ms`, ensuring opening consonants ("Cl-") and closing consonants ("-ve") are completely preserved.

### B. Removed Whisper Prompt Hallucination ("Clear speech only.")
* **The Problem**: Whisper frequently outputted `"Clear speech only."` in logs when the user never said it.
* **Root Cause**: `akira.py` passed `prompt="Voice assistant command. Clear speech only."` to Groq Whisper. On quiet or silent frames, Whisper regurgitated this directive sentence verbatim.
* **The Fix**:
  - Replaced the prompt with clean named-entity keywords: `prompt="Akira, Spotify, YouTube, Brave, Chrome, Excel, Word, PowerPoint, Windows."`.
  - Added artifact rejection in `clean_transcription_text()` in `audio_pipeline.py` to drop `"clear speech only"` and `"clear response"` if ever generated.

### C. Created Interactive Mic Calibrator (`calibrate_mic.py`)
* Created `calibrate_mic.py` in the workspace root.
* Measures ambient room noise and background music for 3 seconds, prompts the user to speak a command for 4 seconds, computes the optimal `MIC_ENERGY_THRESHOLD`, and automatically writes it to `.env`.
* Allows speech onset detection in `audio_pipeline.py` to adapt cleanly to background music.

### D. Fixed YouTube & Browser Tab Reuse
* **The Problem**: Every YouTube or named-site command spawned a brand-new browser tab via `Target.createTarget`. If YouTube was already open, Akira opened duplicate tabs.
* **Root Cause**: `open_site_tab` in `executor.py` unconditionally invoked `Target.createTarget`.
* **The Fix**:
  - In `executor.py` (`open_site_tab`): Inspects all open tabs in `browser.window_handles`. If an open tab matches the requested site (e.g. YouTube, Amazon, Netflix, GitHub), Akira switches to that existing tab, updates `browser._akira_tab` and `browser._youtube_target_tab`, and does NOT create a new tab.
  - In `tiered_classifier.py` (`_build_router_system_prompt`): Ported strict tab rules from `claude_handler.py`. Instructs the Groq router to emit `switch_tab` or direct controllers (`youtube_control`), and never open a new tab unless explicitly asked.
  - **Note on `(23) XYZ Studio`**: Clarified that this was not hardcoded in the codebase; it was the live window title of an open browser window / YouTube tab on the user's PC captured by `get_pc_context()`.

### E. Suppressed Spoken `'unsupported_intent'`
* **The Problem**: Akira's TTS spoke aloud: `Voice: 'unsupported_intent'`.
* **Root Cause**: In multi-step turns, `claude_handler.synthesize_action_reply()` called `_synthesize_on_servant`, which queried the local `akira-mech` model (llama-server on port 8081). Because `akira-mech` was trained for intent classification, it outputted its label `"unsupported_intent"`, which got spoken.
* **The Fix**: In `claude_handler.py` and `akira.py`, filtered out `"unsupported_intent"`, `"no_match"`, and `"(noted)"`, falling back to the router's natural conversational response.

### F. Pending Actions & Schema Integrity
* Verified and aligned `guard_action_envelope()` in `akira.py` and `_validate_groq_envelope()` in `tiered_classifier.py` so `pending_actions` are never stripped or renamed.

---

## 3. VERIFIED FILE MODIFICATIONS & LOCATIONS

| File | Status | Key Changes Made |
| :--- | :--- | :--- |
| [akira.py](file:///d:/Coding/Projects/Sensei/akira.py) | **Modified** | Replaced Whisper prompt with keyword hints; set `silence_cutoff_ms=1200`; filtered out `unsupported_intent` in `synthesize_action_reply`; updated session follow-up timer. |
| [audio_pipeline.py](file:///d:/Coding/Projects/Sensei/audio_pipeline.py) | **Modified** | Exact 1.2s post-speech silence timer via Silero VAD; removed destructive 85% noise gate; 250ms voice padding; 384ms pre-roll; hallucination filters. |
| [calibrate_mic.py](file:///d:/Coding/Projects/Sensei/calibrate_mic.py) | **New** | Interactive CLI tool to calibrate background music vs speech energy and save `MIC_ENERGY_THRESHOLD` to `.env`. |
| [executor.py](file:///d:/Coding/Projects/Sensei/executor.py) | **Modified** | `open_site_tab()` checks open window handles and switches to existing YouTube/Amazon/named tabs instead of creating duplicate tabs. |
| [tiered_classifier.py](file:///d:/Coding/Projects/Sensei/tiered_classifier.py) | **Modified** | Added Rule 7 to router prompt for strict browser tab reuse and tab switching; primary model set to `openai/gpt-oss-120b`. |
| [claude_handler.py](file:///d:/Coding/Projects/Sensei/claude_handler.py) | **Modified** | `synthesize_action_reply()` discards classification tokens (`unsupported_intent`, `no_match`). |
| [tests/test_audio_and_tab_fixes.py](file:///d:/Coding/Projects/Sensei/tests/test_audio_and_tab_fixes.py) | **New** | Unit test suite covering prompt hallucination removal, tab reuse, and intent token filtering (4/4 PASSED). |

---

## 4. CURRENT TEST STATUS & VERIFICATION

All tests pass 100%:
1. `python -m unittest tests/test_audio_pipeline.py` $\rightarrow$ **3/3 OK** (0.438s)
2. `python -m unittest tests/test_audio_and_tab_fixes.py` $\rightarrow$ **4/4 OK** (1.241s)
3. `.\sensei_env\Scripts\python.exe -m unittest tests/test_option_a_routing.py` $\rightarrow$ **17/17 OK** (0.023s)

---

## 5. WHAT IS LEFT TO DO & NEXT STEPS

When you open the new chat, here is the immediate checklist:

1. **Live Audio Calibration**:
   - Run `python calibrate_mic.py` with your normal room/music volume to tune `MIC_ENERGY_THRESHOLD`.
2. **Live Voice Verification with `python akira.py`**:
   - Test speech cutoff: Speak *"Close Brave and open YouTube"* $\rightarrow$ verify it waits ~1.2s after you stop speaking and executes cleanly.
   - Test tab reuse: Say *"Open YouTube"* then *"Search Team Impella on YouTube"* $\rightarrow$ verify it reuses the same YouTube tab.
   - Test background music: Verify Akira doesn't cut off or hallucinate when background music is playing.
3. **SIH Demo / Presentation Polish**:
   - Ensure latency logs remain punchy and live telemetry banners are clean.
   - Run full end-to-end multi-app workflow demo (Spotify + YouTube + Office Excel/Word + Calendar).

---

## 6. QUICK COMMANDS FOR THE NEW CHAT

```powershell
# 1. Activate environment
.\sensei_env\Scripts\Activate.ps1

# 2. (Optional) Run microphone calibrator
python calibrate_mic.py

# 3. Run unit tests to verify system integrity
python -m unittest tests/test_audio_and_tab_fixes.py tests/test_audio_pipeline.py

# 4. Launch Akira
python akira.py
```
