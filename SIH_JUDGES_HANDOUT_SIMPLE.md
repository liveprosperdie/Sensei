# PROJECT AKIRA: VOICE-CONTROLLED DESKTOP ASSISTANT
## Architecture Brief & Technical Handout for Judges

---

<!-- =================================================================================== -->
<!-- PAGE 1: SYSTEM OVERVIEW, COMPLETE FLOW & ROUTING ARCHITECTURE                       -->
<!-- =================================================================================== -->

### 1. System Overview
Project Akira is an open, sovereign desktop voice assistant for Windows. Unlike browser-only chatbots or smart-speaker wrappers that merely answer questions or perform web searches, Akira integrates directly with operating system APIs, file storage, and productivity software. It executes multi-step workflows—such as creating financial spreadsheets with live formulas, organizing loose files into categorized directories, managing browser sessions, and reading documents—entirely through natural voice commands.

Akira is built with a local-first philosophy: repetitive tasks run with zero cloud latency, user file systems are indexed and protected locally, and destructive operations cannot execute without verified human confirmation.

---

### 2. End-to-End Execution Flow (The 5-Phase Pipeline)

Every user utterance flows deterministically through five sequential architectural phases:

```
[User Voice Input]
       │
       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: AUDIO FRONT-END & CONTEXT FILTER                                              │
│ • Silero VAD: Isolates speech frames (32ms), removes ambient room/fan noise            │
│ • Whisper Transcription: Converts voice audio into text tokens                         │
│ • Context Filter: Compresses active desktop state into minimal delta; suppresses       │
│   raw file dumps, credentials, and private history from the router payload             │
└────────────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: TWO-STAGE INTENT ROUTING                                                      │
│ • Local Reflex Fast-Path: Matches single atomic commands in <1ms (0 cloud tokens)      │
│ • Compound Classifier: Routes multi-step, chained commands ("and", "then") to a free   │
│   structured router (Qwen/GPT) to emit a clean action JSON envelope                    │
└────────────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: MULTI-TIER ZERO-TRUST SECURITY GUARD                                          │
│ • Step & Chain Guard: Validates action sequence, bounds execution length               │
│ • Security Boundary: Blocks modifications targeting system files or Akira codebase     │
│   (security_guard.is_codebase_path checks real paths against repository roots)         │
│ • Fail-Closed Model Guard: Independent safety evaluation; generates Ephemeral Token    │
│ • Confirmation Gate: Irreversible operations (delete, bulk move, app close) pause      │
│   for explicit user confirmation ("Yes, go ahead") before running                      │
└────────────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: OS & APPLICATION EXECUTION                                                    │
│ • Microsoft Office: Windows COM automation writes data & formulas directly into Excel  │
│ • Google Workspace: Model Context Protocol (MCP) creates Sheets & Docs on Drive        │
│ • Drive Map Index: Searches 80,000+ files locally in <1ms without disk scanning        │
└────────────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 5: VOICE SYNTHESIS (DETAIL-ON-DEMAND TTS)                                        │
│ • Concise Speech: Speaks 1–2 plain sentences; raw tables/code saved to disk only       │
│ • Detail-on-Demand: Reading documents gives a 2-sentence summary first; detailed        │
│   reading continues in chunks only upon user follow-up                                 │
│ • Session Crypto Vault: Summaries encrypted locally at rest (AES-128-CBC / HMAC-SHA256)│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 3. Audio Processing & Two-Stage Routing

* **Audio Front-End**:
  * Voice Activity Detection (Silero VAD) evaluates incoming microphone audio in real-time.
  * It detects the precise boundary where speech begins and ends, automatically cutting off audio when the user stops speaking and stripping out fan hum, background chatter, and keyboard clicks.
  * Transcribed by an optimized Whisper engine conditioned with desktop-specific vocabulary.

* **Two-Stage Intent Router**:
  * **Stage 1 (Local Pattern Reflex)**: Common, repetitive actions (*volume control, window minimization, pausing playback, screen lock*) bypass external APIs entirely. They execute in **under 1 millisecond using 0 cloud tokens**.
  * **Stage 2 (Structured Language Model Router)**: For natural, compound requests (*"create a weekly budget spreadsheet and save it to my drive"*), a lightweight language model interprets intent and outputs a structured JSON envelope. Strict prompt constraints ensure the router outputs *only* actions, completely preventing conversational filler or step-by-step tutorials on how to build files.

---

<!-- =================================================================================== -->
<!-- PAGE 2: SECURITY GUARDS, FILE MAPS, APPLICATION AUTOMATION & AUDIO DESIGN           -->
<!-- =================================================================================== -->

### 4. Multi-Tier Security & Codebase Protection

Akira implements defense-in-depth to guarantee that automated voice control cannot be hijacked or cause accidental damage:

* **Source Code Protection (`security_guard.py`)**:
  * Akira enforces an unbypassable boundary around its own codebase, virtual environments, and critical Windows directories.
  * Paths are resolved against real filesystem targets: a voice command attempting to delete, overwrite, or organize Akira's source files is intercepted and blocked before execution.
* **Deterministic Guard Rules (`guard_rules.py` & `action_guard.py`)**:
  * Validates action parameters against strict structural schemas.
  * Inspects command chains to prevent dangerous combinations (such as multiple file downloads in a single turn).
* **Fail-Closed Model Guard (`guard.py`)**:
  * An independent secondary evaluation checks hazardous actions before execution.
  * **Fail-closed policy**: If the guard model is unreachable, rate-limited, or returns an ambiguous verdict, it degrades to a `FLAG` rather than silently allowing execution, routing the decision directly to human confirmation.
* **Human Confirmation Gates (`_gated()`)**:
  * Destructive actions (*deleting files, removing folders, closing unsaved applications, bulk file reorganization*) cannot run automatically.
  * Akira speaks a clear confirmation question detailing what will happen. Execution is armed only when the user says *"Yes"*, *"Proceed"*, or *"Go ahead"*.

---

### 5. Local Drive Map Indexing & Secure Storage (`file_index`)

Rather than scanning entire hard drives during a user request—which causes multi-second delays—Akira maintains a fast, offline indexing system:

* **Drive Scanner & Real-Time Watcher**:
  * At startup, the scanner maps connected drives (`C:\`, `D:\`, `E:\`), tracking file paths while automatically skipping private and development folders (`node_modules`, `.git`, `.ssh`, `Windows`, `Program Files`, `.env`).
  * A real-time filesystem watcher updates the index dynamically as files are created, renamed, or deleted.
* **Instant Lookup & Spoken Location**:
  * `lookup_in_drive_map` locates files across 80,000+ indexed paths in **under 1 millisecond**.
  * When searching files, Akira speaks the exact folder location aloud (e.g., *"Found report.docx in D:\Projects\Finance"*), saving the user from having to search manually.
* **Secure Vault Storage**:
  * Drive maps, directory trees, and memory mirrors are stored in a dedicated user vault (`C:\Users\<user>\AppData\Local\Akira\secure_vault`).
  * Drive contents and personal document texts are kept strictly on the local machine and never sent to cloud servers.
* **Live Folder Exclusion**:
  * Users can dynamically exclude sensitive directories by voice (e.g., *"exclude my Tax folder from search"*), immediately purging them from the memory map.

---

### 6. Desktop & Office Automation (COM & MCP)

Akira operates software through verified programmatic protocols rather than fragile mouse clicks:

* **Microsoft Office via Windows COM (`office_control.py`)**:
  * Drives Microsoft Word and Excel directly through Windows COM Automation APIs.
  * Generates clean Excel workbooks, populates cell grids, injects standard uppercase formulas (`=SUM(...)`, `=C2-D2`), bolds header rows, auto-fits columns, and exports directly to `Downloads` with timestamp deduplication.
* **Google Workspace via Model Context Protocol (`sheets_control.py`, `docs_control.py`)**:
  * Connects to Google Drive using the open Model Context Protocol (MCP).
  * Automatically creates, formats, and updates Google Sheets and Google Docs in the user's cloud drive without requiring an open browser window.

---

### 7. Voice Experience: Detail-on-Demand & Encrypted Session Vault

* **Concise Speech (Anti-Monologue)**: Spoken voice responses are kept to 1–2 plain sentences. Raw tabular data, code blocks, and CSV dumps are written to disk and never recited over audio.
* **Executive Summary First**: When reading documents, Akira speaks a 2-sentence executive summary and asks: *"Would you like me to read it in detail?"*
* **Detail-on-Demand (Chunked Reading)**: If the user says *"Yes"*, Akira reads the content in 45–60 second chunks, checking whether to pause or continue after each section.
* **Session Crypto Vault (`session_crypto_logger.py`)**: Summaries of completed actions are encrypted at rest locally using AES-128-CBC and HMAC-SHA256 (Fernet) keys stored in the user's memory vault, providing an auditable record without exposing cleartext interaction logs.
