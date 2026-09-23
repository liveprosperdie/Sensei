# Akira (Sensei) — Co-Founder Setup & Testing Guide

This guide walks you through setting up and running the Akira voice assistant on your local Windows PC.

---

## 1. Quick Architecture Overview

Akira is a voice-controlled, local-first Windows desktop assistant:
- **Speech Pipeline:** Silero VAD $\to$ openWakeWord $\to$ OpenAI Whisper STT $\to$ Edge-TTS / PyTTSx3.
- **Two-Stage Intent Router:**
  - **Tier 1:** Local regex reflex (<1ms, 0 tokens, handles routine app launches, volume, time).
  - **Tier 2:** Dual-Brain Router (Free Groq 120B/27B models for free execution $\to$ Claude Sonnet 5 for complex reasoning).
  - **Procedural Memory:** Caches confirmed multi-step workflows locally with DPAPI encryption (`%LOCALAPPDATA%\Akira`).
- **Security & Guard Rails:** Every command passes through `action_guard`, `guard_rules`, and cryptographic `GuardToken` verification before `executor.py` can touch any Windows API or COM interface.
- **Destructive Commands:** Protected by an audible Confirmation Gate (`"yes / proceed / go ahead"`).

---

## 2. Prerequisites

1. **Operating System:** Windows 10 or 11 (64-bit).
2. **Python:** Python 3.10, 3.11, or 3.12 (64-bit). Make sure "Add Python to PATH" was checked during installation.
3. **Hardware:** Working microphone and speakers/headphones.
4. **Desktop Apps (Optional, for Office/Browser tools):**
   - Google Chrome or Brave Browser.
   - Microsoft Office (Word, Excel, PowerPoint) installed locally for desktop COM control.

---

## 3. Step-by-Step Setup

### Step 3.1: Create a Virtual Environment

Open PowerShell in the project directory:

```powershell
# Create virtual environment
python -m venv sensei_env

# Activate virtual environment
.\sensei_env\Scripts\activate

# Upgrade pip, setuptools, and wheel
python -m pip install --upgrade pip setuptools wheel
```

### Step 3.2: Install Dependencies

All required libraries are pinned in `requirements.txt`:

```powershell
pip install -r requirements.txt
```

> [!TIP]
> **Windows COM Fix:** If you encounter COM or Win32 errors on first run, register the pywin32 extensions by running:
> ```powershell
> python .\sensei_env\Scripts\pywin32_postinstall.py -install
> ```

---

## 4. Environment Variables (`.env`)

Never commit your `.env` file to Git. A template has been provided in [`.env.example`](file:///.env.example).

Create your local `.env`:

```powershell
copy .env.example .env
```

Open `.env` in your editor and add your API keys:

| Environment Variable | Required? | Where to get it / Description |
| :--- | :--- | :--- |
| `ANTHROPIC_API_KEY` | **Yes** (for Claude router) | Get from [Anthropic Console](https://console.anthropic.com/). Used for Sonnet 5 routing & Opus reasoning. |
| `GROQ_API_KEY` | **Yes** (for Free Brain router) | Get a free API key from [Groq Console](https://console.groq.com/). Used for sub-second free routing. |
| `SPEECH_API_KEY` | Optional | Secondary Groq key for Whisper/Speech fallback (can be the same as `GROQ_API_KEY`). |
| `AKIRA_DISABLE_CLAUDE` | Optional (`false`) | Set to `true` to test 100% free mode with zero Anthropic API spend. |
| `AKIRA_PROCEDURAL_MEMORY_MODE` | Optional (`shadow`) | `shadow` (default, evaluates replay eligibility in background) or `replay`. |
| `SPOTIFY_CLIENT_ID` / `SECRET` | Optional | From [Spotify Developer Dashboard](https://developer.spotify.com/) for playback control. |
| `GITHUB_TOKEN` | Optional | GitHub Personal Access Token for repo search and issue management. |
| `OBSIDIAN_API_KEY` | Optional | From the Obsidian Local REST API community plugin. |

---

## 5. Checklist of Ignored Files (`.gitignore`) to Collect

Because the repository enforces strict safety and data-minimization, sensitive files, large binaries, and driver executables are excluded by `.gitignore`. Here is what you need to collect or know about:

### 1. Web Drivers (`chromedriver.exe`)
- **What it is:** Required for browser automation (Selenium).
- **Where to get it:** Download the matching version of ChromeDriver for your installed Chrome browser from [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/).
- **Where to put it:** Place `chromedriver.exe` directly in the project root directory. (The codebase also supports automatic resolution via `webdriver-manager`).

### 2. Custom Wake Word Models (`akira.onnx`, `akira.onnx.data`)
- **What it is:** OpenWakeWord custom model files trained for the wake phrase *"Akira"*.
- **Where to get it:** Ask the team for the pinned `akira.onnx` and `akira.onnx.data` binary files, or let openWakeWord use its built-in pre-trained models.
- **Where to put it:** Place directly in the project root.

### 3. Local GGUF LLMs (`Akira/*.gguf`)
- **What it is:** Optional local LoRA adapters and 8B quantization models (`Llama-3-8B-Instruct.Q4_K_M.gguf`, `akira_mech.gguf`, etc.).
- **Do you need this?** **NO for API testing.** The assistant defaults to cloud API routing (Groq + Claude). You only need GGUF models if you are running `hardware_gate.py` with a local `llama-server`.

### 4. Google Workspace Credentials (`credentials.json`, `token.json`)
- **What it is:** Google OAuth client secrets for managing Google Docs, Calendar, Drive, and Sheets.
- **Where to get it:** Download `credentials.json` from the Google Cloud Console (OAuth 2.0 Client IDs for Desktop App).
- **Where to put it:** Place `credentials.json` in the root folder. On first use, Google will prompt you to authenticate in your browser and save `token.json`.

### 5. Procedural Memory Store & Session Keys
- **What it is:** `procedures.db` and `.procedures.key`.
- **Action required:** **None.** These are automatically created on first boot under `%LOCALAPPDATA%\Akira\` and encrypted using your Windows user login credentials via DPAPI.

---

## 6. How to Run Akira

### Option A: Text Mode (Quickest for Testing Intent Routing & Tools)
Run the interactive CLI without needing mic audio or wake word:
```powershell
python text_mode.py
```
Type commands such as:
- `open notepad`
- `volume up`
- `what's on my screen?`
- `create a word document about machine learning`

### Option B: Full Voice Mode (Live Mic, Wake Word & TTS)
Run the full desktop assistant:
```powershell
python akira.py
```
1. Say **"Akira"** (or watch for the avatar listening cue).
2. Speak your command (e.g. *"Open settings and turn volume to 50%"*).
3. For gated commands (e.g. *"Shutdown the PC"* or *"Delete files"*), say **"yes"** or **"go ahead"** when prompted.

---

## 7. Running Verification & Test Suites

To verify that all components, security guards, and procedural memory layers are operating properly:

```powershell
# Run procedural memory foundation & shadow tests (17 tests)
python -m unittest tests/test_procedural_memory.py

# Run guard-chain parity integration tests (3 tests)
python -m unittest tests/test_guard_chain_parity.py

# Run tiered routing & classifier tests
python -m unittest tests/test_tiered_routing.py
```

---

## 8. Common Troubleshooting

1. **PyAudio / Microphone Issues:**
   - Ensure microphone access is allowed in Windows Settings: **Settings > Privacy & security > Microphone > Let desktop apps access your microphone**.
   - If PyAudio fails to initialize, run `python calibrate_mic.py` to test your default recording device.
2. **Missing COM Interfaces:**
   - Make sure desktop Microsoft Word or Excel is installed and activated. Web-only Office 365 does not expose Win32 COM interfaces.
3. **Claude Disabled / Free Brain Only:**
   - If you want to test without consuming Anthropic credits, set `AKIRA_DISABLE_CLAUDE=true` in your `.env`. Akira will route commands entirely through Groq's high-speed open-source models.
