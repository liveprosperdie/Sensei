# Akira (Sensei) — Complete Architecture, System Working & Master Function Directory

> **Document Version:** 2.0 (Master Unified Dossier)  
> **Target Audience:** Claude, Core Engineering, Co-Founders, Technical Auditors  
> **Repository:** `liveprosperdie/Sensei` (Branch: `main`)  
> **Runtime Environment:** Windows 10/11 x64, Python 3.11+, PyTorch (Silero VAD), ONNX Runtime, FastAPI, Redis, pywin32 (COM Dispatch), Selenium.

---

## Table of Contents
1. [Executive Architecture Manifesto & Core Philosophy](#1-executive-architecture-manifesto--core-philosophy)
2. [Master System Topology & Dataflow](#2-master-system-topology--dataflow)
3. [Voice Pipeline & Orchestration Engine (`akira.py`, `audio_pipeline.py`, `speech_head.py`, `avatar_ui.py`)](#3-voice-pipeline--orchestration-engine)
4. [Cognitive Routing & Multi-Tier Hierarchy (`tiered_classifier.py`, `action_router.py`, `tiers.py`, `model_pool.py`, `hardware_gate.py`)](#4-cognitive-routing--multi-tier-hierarchy)
5. [Defense-in-Depth Safety & Cryptographic Guard (`guard.py`, `action_guard.py`, `guard_rules.py`, `security_guard.py`)](#5-defense-in-depth-safety--cryptographic-guard)
6. [Desktop & OS Execution Engine (`executor.py`, `office_control.py`, `obsidian_control.py`, `system_control.py`)](#6-desktop--os-execution-engine)
7. [FTS5 File Index & Zero-Leak Search Engine (`file_index/`)](#7-fts5-file-index--zero-leak-search-engine)
8. [DPAPI Encrypted Procedural Memory (`procedural_memory/`)](#8-dpapi-encrypted-procedural-memory)
9. [Thin Server Gateway & Quota Fallback (`gateway_server/`)](#9-thin-server-gateway--quota-fallback)
10. [Adaptive Teaching Mode & Feynman Studio (`teaching/`)](#10-adaptive-teaching-mode--feynman-studio)
11. [Context Optimization & Reliability Ledger (`session_context_cache.py`, `reliability.py`)](#11-context-optimization--reliability-ledger)
12. [Master Function & API Directory (Exhaustive Index)](#12-master-function--api-directory-exhaustive-index)
13. [Forward Roadmap: Phase 5 Repo-Explain, Business Mode & Air-Gapped Edge](#13-forward-roadmap)

---

## 1. Executive Architecture Manifesto & Core Philosophy

**Akira** is an autonomous desktop operating companion built specifically for Windows. Unlike conversational web wrappers, Akira has:
- **Direct Physical Hands**: Deep Win32 COM hooks for Microsoft Office (Word, Excel, PowerPoint), local Obsidian vault integration, Google Workspace, and low-level Windows APIs.
- **Continuous Voice Presence**: Always-listening on-device wake-word detection (`akira.onnx`), local neural voice activity detection (Silero VAD), fast Whisper STT, and neural TTS feedback with dynamic avatar sprite cues.
- **Cryptographic Guardrails**: Zero unchecked system execution. Every action requires an anti-tamper HMAC-SHA256 `GuardToken`. Destructive operations require spoken human confirmation (`"yes"`, `"proceed"`).
- **Procedural Muscle Memory**: Multi-step workflows are scrubbed of PII and cached in DPAPI-encrypted SQLite for instant, zero-cost, offline execution.
- **Zero-Claude Free-API Mode**: Complete operational independence from Anthropic using Groq Cloud (Llama 3.3 70B, GPT-OSS 120B) and Google Gemini (2.0/1.5 Flash) via `AKIRA_DISABLE_CLAUDE=true`.
- **Specialized High-Value Domain Modes**:
  - **Teaching Mode**: Local adaptive tutor with JIT syllabus and lesson drafting, 100MB PDF/DOCX textbook ingestion, Mermaid architectural diagrams, automated remedial lessons, and a **Feynman Technique Voice Studio** with thinking pause buffers and distraction detection.
  - **Business Mode (Upcoming)**: Autonomous `.xlsx` financial modeling, cross-document report synthesis into Word/PowerPoint, and 60-second morning audio executive briefings.

---

## 2. Master System Topology & Dataflow

```
                             ┌───────────────────────────────────────┐
                             │       Microphone / User Audio         │
                             └───────────────────┬───────────────────┘
                                                 │
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │     On-Device Wake-Word Engine        │
                             │  (akira.onnx ~14KB via openWakeWord)  │
                             └───────────────────┬───────────────────┘
                                                 │ "Akira" detected
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │          Silero VAD + PyAudio         │
                             │  Continuous voice speech chunking     │
                             └───────────────────┬───────────────────┘
                                                 │ Audio frames
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │       Whisper STT (Local / API)       │
                             │     Transcribes user command text     │
                             └───────────────────┬───────────────────┘
                                                 │ User Query
                                                 ▼
                             ┌───────────────────────────────────────┐
                             │     LAYER 0: Reflex Intent Engine     │
                             │   tiered_classifier.py (<0.1ms, 0tok) │
                             └───────┬───────────────────────┬───────┘
                     Pattern matched │                       │ Complex / NL
                                     │                       ▼
                                     │       ┌───────────────────────────────┐
                                     │       │ LAYER 1: Dual-Brain Routing   │
                                     │       │ Groq 70B / Gemini / Claude    │
                                     │       └───────────────┬───────────────┘
                                     │                       │ Planned action
                                     ▼                       ▼
                             ┌───────────────────────────────────────┐
                             │      LAYER 2: Safety & Interceptors   │
                             │  action_guard.py & guard_rules.py     │
                             │  • HMAC-SHA256 GuardToken issue       │
                             │  • Spoken Confirmation Gate           │
                             │  • <untrusted_external_context> wrap  │
                             └───────────────────┬───────────────────┘
                                                 │ Verified GuardToken
                                                 ▼
         ┌───────────────────────────────────────┴───────────────────────────────────────┐
         │                                                                               │
         ▼                                                                               ▼
┌─────────────────────────────────┐                             ┌─────────────────────────────────┐
│  LAYER 3: OS & App Execution    │                             │  LAYER 4: Domain Mode Engine    │
│  executor.py                    │                             │  teaching/ & business/          │
│  • Win32 COM: Word, Excel, PPT  │                             │  • 100MB Textbook Parser        │
│  • Obsidian Local REST API      │                             │  • JIT Lessons & Quizzes        │
│  • Google Workspace (Gmail/Cal) │                             │  • Feynman Voice Studio (4s buf)│
│  • Selenium Web Automation      │                             │  • Offline Mermaid Diagrams     │
│  • System controls (Vol/Win)    │                             │  • Adaptive Remediation Loop    │
└────────────────┬────────────────┘                             └────────────────┬────────────────┘
                 │                                                               │
                 ▼                                                               ▼
┌─────────────────────────────────┐                             ┌─────────────────────────────────┐
│  LAYER 5: Procedural Memory     │                             │  LAYER 6: Thin Server Gateway   │
│  procedural_memory/             │                             │  gateway_server/                │
│  • DPAPI-encrypted SQLite       │                             │  • JWT Auth & Quota Tracking    │
│  • PII & Deictic Scrubber       │                             │  • Zero-Content Logging         │
│  • Shadow Mode Recorder         │                             │  • Seamless Groq Fallback       │
│  • Zero-token instant replay    │                             │  • Non-BYOK Security            │
└─────────────────────────────────┘                             └─────────────────────────────────┘
```

---

## 3. Voice Pipeline & Orchestration Engine

### Core Modules: `akira.py`, `audio_pipeline.py`, `speech_head.py`, `avatar_ui.py`

#### Architectural Working:
1. **Wake-Word Detection**: Akira runs a continuous background loop inspecting PyAudio input chunks (16kHz mono) through the bundled `akira.onnx` model using `openwakeword.Model`. When the prediction confidence breaches threshold (`0.5`), the wake state trips.
2. **Silero VAD Chunking**: Once awake, the stream shifts to `audio_pipeline.py`, where Silero VAD evaluates probabilities per frame. A speech segment is actively recorded until silence exceeds the trailing pause threshold.
3. **Transcription & Audio Feedback**: Audio is transcribed via Whisper. Akira plays an immediate subtle acknowledgment tone (`winsound`), updates the companion sprite in `avatar_ui.py` to "thinking", and passes text to the cognitive router.
4. **Speech Output Queue**: Responses generated by Akira pass to `speech_head.py`, which generates neural audio via Edge-TTS (or offline PyTTSx3) and streams audio smoothly to the user while animating the avatar to "speaking".

#### Complete Function Index:
* `akira.listen(vad_threshold: float = 0.5) -> str`: Continuously captures microphone input until Silero VAD detects end-of-utterance, transcribes via Whisper, and returns normalized text.
* `akira.speak(text: str, interruptible: bool = True) -> None`: Queues and executes neural speech synthesis through `speech_head.py`.
* `akira._record_session_action(action: str, parameter: str, result: object) -> None`: Records completed action metadata into an in-memory deque (max 8) for immediate context recall.
* `akira._reset_session_action_history() -> None`: Clears in-memory session history when switching topics or resting.
* `akira.run_akira() -> None`: Master execution loop. Initializes audio streams, loads ONNX models, and manages turn transitions.
* `audio_pipeline.create_audio_stream(rate: int = 16000, chunk: int = 512) -> pyaudio.Stream`: Configures low-latency PCM audio stream.
* `audio_pipeline.vad_collector(stream, model, threshold: float = 0.5)`: Yields speech frame buffers based on neural probability.
* `speech_head.speak_edge(text: str, voice: str = "en-US-AriaNeural") -> None`: Synthesizes audio using Microsoft Edge neural TTS.
* `speech_head.speak_pyttsx3(text: str) -> None`: Offline TTS fallback when internet connectivity is unavailable.
* `avatar_ui.update_state(state: str) -> None`: Updates desktop sprite animation (`"idle"`, `"listening"`, `"thinking"`, `"speaking"`).

---

## 4. Cognitive Routing & Multi-Tier Hierarchy

### Core Modules: `tiered_classifier.py`, `action_router.py`, `tiers.py`, `model_pool.py`, `hardware_gate.py`

#### Architectural Working:
Akira classifies user intent across 3 distinct tiers to deliver instantaneous responses and control operational costs:
- **Tier 0 (Reflex Regex)**: Evaluated in `<0.1ms` at 0 token cost. Matches deterministic desktop commands (volume, media, window focus, study room launch).
- **Tier 1 (Free Cloud AI)**: Utilizes Groq Cloud (`llama-3.3-70b-versatile`, `gpt-oss-120b`) and Google Gemini (`gemini-2.0-flash`) for multi-step task planning, lesson generation, and intent classification.
- **Tier 2 (Frontier AI)**: Claude 3.5 Sonnet / Opus routed through the Thin Server Gateway for deep reasoning and code generation.
- **Zero-Claude Mode (`AKIRA_DISABLE_CLAUDE=true`)**: Hard kill-switch for all Anthropic calls. Redirects all requests strictly to free-tier Groq and Gemini endpoints.
- **Hardware Gate**: Probes physical system specifications (GPU, dedicated VRAM, system RAM) via WMI and PyTorch CUDA. Categorizes the machine into `INFEASIBLE`, `BASE_ONLY`, or `BASE_AND_ADAPTERS` for running local models.

#### Complete Function Index:
* `tiered_classifier.classify_reflex(text: str) -> Optional[RoutingDecision]`: Matches user utterance against regex dispatch table. Returns Tier 0 routing decision if matched.
* `tiered_classifier.classify_intent_tier1(text: str, context: dict) -> dict`: Sends text to Groq/Gemini to extract action name, target, and parameters.
* `tiered_classifier.wrap_untrusted(text: str, source_type: str = "web") -> str`: Sanitizes external content and wraps it in `<untrusted_external_context>` XML tags.
* `action_router.route_action(user_text: str, session_context: dict) -> dict`: Central routing hub. Checks Tier 0, then procedural memory cache, then Tier 1/2 models.
* `tiers.get_tier_spec(layer_name: str) -> Union[HeadSpec, ServantSpec, GuardMode]`: Resolves declarative tier configurations based on environment variables.
* `model_pool.get_best_available_model(task_type: str = "general") -> ModelClient`: Returns highest priority model client taking `AKIRA_DISABLE_CLAUDE` into account.
* `hardware_gate.capability() -> HardwareCapability`: Probes hardware RAM and VRAM, returning capability level.
* `hardware_gate.local_serving_status() -> dict`: Combines hardware measurement with runtime verification to report local model feasibility.

---

## 5. Defense-in-Depth Safety & Cryptographic Guard

### Core Modules: `guard.py`, `action_guard.py`, `guard_rules.py`, `security_guard.py`

#### Architectural Working:
1. **Pre-Execution Guard Inspection**: Every proposed action (e.g. `delete_file`, `send_email`, `execute_shell`) is sent to `action_guard.py` prior to reaching `executor.py`.
2. **HMAC-SHA256 Token Issuance**: If the action complies with safety rules, the guard signs a tamper-proof `GuardToken` containing the action, target, risk level, and timestamp.
3. **Execution-Time Verification**: `executor.py` validates the HMAC signature. If an action arrives without a valid token or with a tampered token, execution raises `GuardBypassError`.
4. **Spoken Confirmation Gate**: For actions tagged `HIGH_RISK`, execution halts. Akira asks the user for explicit verbal confirmation (`"Are you sure you want to delete report.docx?"`) and only proceeds upon detecting `"yes"` or `"proceed"`.
5. **Codebase Protection**: A deterministic rule prevents the assistant from touching, deleting, or overwriting its own repository files.

#### Complete Function Index:
* `guard.issue_guard_token(action: str, target: str, risk_level: str) -> str`: Generates HMAC-SHA256 token encoding action metadata and timestamp.
* `guard.verify_guard_token(token: str, action: str, target: str, max_age_secs: int = 30) -> bool`: Verifies signature authenticity and freshness.
* `action_guard.review_action(action: str, params: dict, context: dict) -> GuardVerdict`: Classifies risk (`SAFE`, `LOW`, `MEDIUM`, `HIGH`) and issues token or flags violation.
* `guard_rules.check_action_risk(action: str, params: dict) -> Tuple[str, Optional[str]]`: Evaluates rule engine against known high-risk verbs.
* `guard_rules.is_confirmation_granted(user_response: str) -> bool`: Analyzes spoken user feedback for affirmative intent (`"yes"`, `"proceed"`, `"confirm"`).
* `security_guard.protect_codebase(file_path: str, operation: str) -> bool`: Prevents destructive modifications targeting the active Akira workspace.

---

## 6. Desktop & OS Execution Engine

### Core Modules: `executor.py`, `office_control.py`, `obsidian_control.py`, `system_control.py`, `browser_setup.py`

#### Architectural Working:
`executor.py` (6,495 lines) is the execution engine for all Windows desktop operations:
- **Win32 COM Automation**: Direct COM dispatch for Word (`winword.exe`), Excel (`excel.exe`), and PowerPoint (`powerpnt.exe`). Can create, edit, format, read, and export documents without third-party dependencies.
- **Obsidian Vault Control**: Uses the Obsidian Local REST API to read daily notes, append meeting notes, perform vault searches, and resolve backlinks.
- **System Controls**: Adjusts master system volume, toggles mutes, adjusts screen brightness, manages processes via `psutil`, and handles window geometry via `pygetwindow` and `win32gui`.
- **Browser Automation**: Launches and operates Selenium WebDriver instances across Chrome, Brave, Edge, and Firefox for authenticated web tasks.

#### Complete Function Index:
* `executor.execute(action: str, parameter: str, token: str) -> dict`: Master dispatch function. Verifies `GuardToken` and executes corresponding driver call.
* `executor.open_app(app_name: str) -> dict`: Resolves executable path via `URI_MAP` or `MANUAL_MAP` and spawns process.
* `executor.close_app(app_name: str) -> dict`: Locates process by name and terminates cleanly.
* `executor.open_site(name_or_url: str) -> dict`: Maps human site name to URL and opens in default browser.
* `executor.get_pc_context() -> dict`: Scans foreground window title, running process summaries, and active screen resolution.
* `executor.take_screenshot(filename: Optional[str] = None) -> str`: Captures desktop screenshot via `PIL.ImageGrab` and saves to `%USERPROFILE%\Pictures\Screenshots`.
* `office_control.create_word_document(title: str, sections: list[dict], save_path: str) -> bool`: Creates structured Word document with styled headers and paragraphs.
* `office_control.create_excel_sheet(sheet_name: str, headers: list[str], rows: list[list], save_path: str) -> bool`: Creates formatted Excel spreadsheet.
* `office_control.create_powerpoint_presentation(title: str, slides_data: list[dict], save_path: str) -> bool`: Creates PowerPoint presentation with title and content slides.
* `obsidian_control.append_to_daily_note(vault_url: str, api_key: str, text: str) -> bool`: Appends timestamped bullet point to Obsidian daily note.
* `obsidian_control.search_vault(vault_url: str, api_key: str, query: str) -> list[dict]`: Searches notes in Obsidian vault via REST API.
* `system_control.set_volume(level: int) -> None`: Sets Windows master volume (0-100) via `pycaw`.
* `system_control.adjust_brightness(delta: int) -> None`: Modifies screen brightness via WMI.

---

## 7. FTS5 File Index & Zero-Leak Search Engine

### Core Module: `file_index/` (`search.py`, `scanner.py`, `watcher.py`, `db.py`, `config.py`)

#### Architectural Working:
Maintains a local SQLite FTS5 full-text search index over user documents:
- **Crawler & Scanner**: Walks specified directories, records metadata, and extracts document text (DOCX, PDF, TXT, MD).
- **Background Watcher**: Uses Windows file notifications to update the database when files are added, modified, or deleted.
- **Zero-Leak Privacy**: Evaluates every document against `SENSITIVE_PATTERNS` (`.env`, `credentials.json`, `id_rsa`, `.pem`, `.kdbx`). Sensitive documents and directories (`.ssh`, `.aws`) are completely filtered and excluded from search results.

#### Complete Function Index:
* `file_index.search.is_sensitive_file(name: str, full_path: str = "") -> bool`: Detects private keys, certificates, or credentials. Returns `True` to block leakage.
* `file_index.search._sanitize_fts5_query(query: str) -> str`: Cleans search string for SQLite FTS5 operators and configures prefix matching.
* `file_index.search.search_files_metadata(conn, query: str, root: Optional[str], max_results: int = 20) -> list[dict]`: Searches files by name using FTS5 with LIKE fallback.
* `file_index.search.search_files_content(conn, query: str, root: Optional[str], max_results: int = 20) -> list[dict]`: Searches document contents using full-text index chunks.
* `file_index.scanner.scan_directory(path: str, conn) -> int`: Traverses folder and records new/updated file records.
* `file_index.watcher.start_watcher(paths: list[str]) -> None`: Spawns file system watcher daemon to record real-time file updates.

---

## 8. DPAPI Encrypted Procedural Memory

### Core Module: `procedural_memory/` (`store.py`, `crypto.py`, `scrubber.py`, `shadow.py`, `pipeline.py`)

#### Architectural Working:
1. **Windows DPAPI Security**: Master encryption key is derived using Windows DPAPI (`win32crypt.CryptProtectData`). Data can only be decrypted by the same Windows user account on that physical machine.
2. **PII & Deictic Scrubbing**: Replaces concrete paths, timestamps, names, and deictic references (`"this spreadsheet"`) with reusable parameter slots (`{PATH_PARAM_0}`, `{TARGET_SHEET}`).
3. **Shadow Mode Recording**: Runs in background during standard operation. When a multi-step workflow succeeds and verifies 100% guard chain parity, it is packaged as a reusable procedural macro.
4. **Instant Replay**: When the user requests a known task, Akira retrieves the plan from SQLite, substitutes dynamic parameters, and executes the procedure at 0 token cost and sub-second speed.

#### Complete Function Index:
* `procedural_memory.crypto.get_dpapi_master_key() -> bytes`: Generates or retrieves local persistent symmetric key secured by Windows DPAPI.
* `procedural_memory.crypto.encrypt_procedure(payload: str) -> str`: Encrypts serialized procedure JSON using Fernet.
* `procedural_memory.crypto.decrypt_procedure(ciphertext: str) -> str`: Decrypts stored procedural payload.
* `procedural_memory.scrubber.scrub_workflow_intent(user_prompt: str) -> Tuple[str, dict]`: Cleans concrete paths and pronouns, returning parameterized template and slot values.
* `procedural_memory.shadow.record_execution_step(session_id: str, action: str, params: dict, success: bool) -> None`: Appends execution step to shadow buffer.
* `procedural_memory.shadow.finalize_procedure_if_valid(session_id: str) -> Optional[str]`: Validates guard parity and saves procedure into SQLite store.
* `procedural_memory.store.save_procedure(intent_hash: str, encrypted_data: str) -> None`: Inserts encrypted procedure record into database.
* `procedural_memory.store.find_procedure(intent_hash: str) -> Optional[dict]`: Retrieves procedure record by intent signature.

---

## 9. Thin Server Gateway & Quota Fallback

### Core Module: `gateway_server/` (`main.py`, `auth.py`, `quota.py`, `subscriptions.py`)

#### Architectural Working:
- **Thin Proxy Architecture**: Handles cloud authentication, daily quotas, and model fallback without exposing master API keys to the client desktop.
- **Zero-Content Logging**: Guarantees that user prompts, audio, and completions pass ephemerally in-memory and are never written to server logs or databases.
- **Quota & Automatic Groq Fallback**: Standard tier users receive 30 Claude turns/day; Pro users receive 53 turns/day. Once Claude quota is reached, `/v1/route` automatically routes requests to Groq Cloud free tier (up to 250 fallback turns/day) instead of hard-stopping the user.
- **Authoritative Daily Resets**: All Redis quota counters atomically expire at `00:00 UTC`.

#### Complete Function Index:
* `gateway_server.auth.exchange_code_for_token(code: str, nonce: str) -> dict`: Exchanges single-use auth code for signed HS256 JWT access token.
* `gateway_server.auth.verify_jwt_token(token: str) -> dict`: Validates JWT claims, signature, and expiration.
* `gateway_server.quota.check_and_increment_quota(redis_client, user_id: str, tier: str) -> Tuple[bool, str]`: Validates available turns; shifts to Groq fallback when Claude limit is reached.
* `gateway_server.quota.record_usage(redis_client, user_id: str, is_claude: bool) -> dict`: Increments atomic daily Redis usage counters.
* `gateway_server.upstream.forward_to_claude(prompt: str, model: str) -> str`: Streams prompt to Anthropic Claude upstream.
* `gateway_server.upstream.forward_to_groq(prompt: str, model: str) -> str`: Streams prompt to Groq Cloud upstream.

---

## 10. Adaptive Teaching Mode & Feynman Studio

### Core Module: `teaching/` (`server.py`, `pipeline.py`, `heuristics.py`, `schema.py`, `sources.py`, `static/app.js`)

#### Architectural Working:
Teaching Mode is a full-featured local adaptive learning environment:
1. **Strict File-Contract Architecture**: The AI generates only Markdown and JSON sidecars stored under `%LOCALAPPDATA%\Akira\teaching_workspace\<slug>\`. The UI is deterministic and never communicates with an LLM directly.
2. **100 MB / 800-Page Document Ingestion**: Ingests textbooks, lecture slides, and notes (PDF via `pypdf`, DOCX, TXT, MD) up to 100 MB with local-only or cloud-allowed privacy toggles.
3. **Just-In-Time Generation**: Generates syllabus on topic creation, and drafts lessons, quizzes, and diagrams just-in-time as the student progresses.
4. **Adaptive Remediation**: Quizzes tag questions with sub-concept tags (`concept_tag`). Scoring under 70% automatically triggers `insert_remedial_lesson` targeting the specific missed concept.
5. **The Feynman Technique Voice Studio**:
   - Students explain what they learned in their own words.
   - Built with a **4.0-second pause buffer** allowing students to pause and think without cutoffs.
   - Includes real-time audio waveform visualizers, ambient distraction detection, transcript evaluation, mastery scoring (0-100), strength highlights, and misconception clarification flags.
6. **Local Vendored Mermaid.js Diagrams**: Renders interactive architectural diagrams with dual-pane synchronized scrolling against source document excerpts (`<!-- source-ref -->`).

#### Complete Function Index:
* `teaching.server.create_app(token: str, port: int) -> FastAPI`: Initializes local study room server with strict CSP and loopback binding.
* `teaching.server.run(open_browser: bool = True, port: int = 0) -> str`: Starts Uvicorn server and launches browser with `#t=token` URL authentication.
* `teaching.sources.add_local_file(slug: str, filename: str, data: bytes, allow_cloud: bool) -> dict`: Ingests and chunks documents up to 100 MB.
* `teaching.pipeline.plan_course(topic: str, level: str, sources_summary: str) -> dict`: Uses HEAD model to generate syllabus, lesson outlines, and concept tags.
* `teaching.pipeline.write_lesson(slug: str, lid: str) -> str`: Drafts 450-800 word Markdown lesson with embedded diagram tokens.
* `teaching.pipeline.write_quiz(slug: str, lid: str) -> dict`: Generates multiple-choice quiz questions tagged by sub-concept.
* `teaching.pipeline.evaluate_feynman(slug: str, lid: str, explanation: str) -> dict`: Analyzes spoken student transcript and returns mastery score, strengths, and misconception flags.
* `teaching.pipeline.check_relevance(topic: str, text: str) -> dict`: Detects off-topic speech or distractions during Feynman voice recording.
* `teaching.heuristics.evaluate_quiz(quiz: dict, answers: dict) -> dict`: Grades student quiz submissions locally and records missed concept tags.
* `teaching.heuristics.decide_adaptation(meta: dict, lid: str, quiz_result: dict) -> dict`: Decides next action (`proceed`, `insert_remedial_lesson`, or `adjust_depth`).
* `teaching.schema.validate_plan(raw: dict) -> dict`: Validates syllabus JSON schema from model.
* `teaching.schema.validate_lesson_md(md: str) -> str`: Normalizes Markdown, validates section headers, and strips unsafe tags.
* `teaching.schema.validate_quiz(raw: dict, concepts: list[str]) -> dict`: Validates quiz questions, option counts, and answer keys.

---

## 11. Context Optimization & Reliability Ledger

### Core Modules: `session_context_cache.py`, `reliability.py`

#### Architectural Working:
- **In-Memory Session Context Optimization**: On session turn 1, captures running desktop applications and window states. On subsequent turns (turns 2+), calculates minimal delta diffs, eliminating repetitive tokens and avoiding private document title leaks.
- **20-Run Reliability Ledger**: Manages a per-action-type historical ledger for gated actions. Ensures high-risk operations (e.g. `delete_file`, `shutdown_pc`) must build a verified success streak before unlocking automated execution.

#### Complete Function Index:
* `session_context_cache.get_generalized_applications(open_windows: Optional[list] = None) -> list[str]`: Generates list of running applications while scrubbing confidential document names.
* `session_context_cache.compute_context_delta(previous_state: dict, current_state: dict) -> dict`: Generates minimal diff of changed windows and processes.
* `session_context_cache.reset_cache() -> None`: Clears in-memory session cache.
* `reliability.record_run(action: str, success: bool) -> None`: Records run outcome in the action reliability ledger.
* `reliability.cleared(action: str) -> bool`: Checks if an action type has completed the required reliability protocol threshold (default: 3 runs in dev, 20 in prod).
* `reliability.reset_action(action: str) -> None`: Resets streak counter for an action type upon failure.

---

## 12. Master Function & API Directory (Exhaustive Index)

| Module | Function Signature | Description |
| :--- | :--- | :--- |
| `akira` | `listen(vad_threshold: float = 0.5) -> str` | Captures microphone input, tracks VAD, and transcribes utterance. |
| `akira` | `speak(text: str, interruptible: bool = True) -> None` | Queues and synthesizes spoken voice output. |
| `akira` | `_record_session_action(action, parameter, result) -> None` | Caches last 8 actions into in-memory turn history. |
| `audio_pipeline` | `create_audio_stream(rate: int, chunk: int) -> Stream` | Initializes low-latency PCM audio recording stream. |
| `audio_pipeline` | `vad_collector(stream, model, threshold: float)` | Filters raw audio frames through Silero VAD. |
| `speech_head` | `speak_edge(text: str, voice: str) -> None` | Generates neural speech using Microsoft Edge TTS. |
| `speech_head` | `speak_pyttsx3(text: str) -> None` | Generates speech using offline Windows SAPI5 voice engine. |
| `avatar_ui` | `update_state(state: str) -> None` | Sets desktop companion visual animation state. |
| `tiered_classifier`| `classify_reflex(text: str) -> Optional[RoutingDecision]` | Evaluates regex table for `<0.1ms` Tier 0 reflex matching. |
| `tiered_classifier`| `wrap_untrusted(text: str, source_type: str) -> str` | Wraps untrusted text in anti-injection XML delimiters. |
| `action_router` | `route_action(user_text: str, context: dict) -> dict` | Dispatches query across reflex, memory, and LLM tiers. |
| `model_pool` | `get_best_available_model(task_type: str) -> ModelClient`| Resolves active LLM client with `AKIRA_DISABLE_CLAUDE` gating. |
| `hardware_gate` | `capability() -> HardwareCapability` | Probes system VRAM and RAM for local model suitability. |
| `guard` | `issue_guard_token(action, target, risk_level) -> str` | Issues HMAC-SHA256 signature for inspected action. |
| `guard` | `verify_guard_token(token, action, target) -> bool` | Validates token authenticity, payload matching, and expiration. |
| `action_guard` | `review_action(action: str, params: dict) -> GuardVerdict` | Reviews action against security policies and returns verdict. |
| `guard_rules` | `check_action_risk(action: str, params: dict) -> Tuple` | Flags destructive operations requiring confirmation. |
| `guard_rules` | `is_confirmation_granted(response: str) -> bool` | Validates user affirmative response (`"yes"`, `"proceed"`). |
| `executor` | `execute(action: str, parameter: str, token: str) -> dict`| Validates `GuardToken` and executes desktop action. |
| `executor` | `open_app(app_name: str) -> dict` | Resolves app path and launches process. |
| `executor` | `close_app(app_name: str) -> dict` | Locates and terminates application process. |
| `executor` | `open_site(name_or_url: str) -> dict` | Opens website or URL in default browser. |
| `executor` | `take_screenshot(filename: Optional[str]) -> str` | Captures screen image and returns file path. |
| `office_control` | `create_word_document(title, sections, path) -> bool` | Generates formatted Microsoft Word `.docx` file via COM. |
| `office_control` | `create_excel_sheet(sheet_name, headers, rows, path)` | Generates Microsoft Excel `.xlsx` workbook via COM. |
| `office_control` | `create_powerpoint_presentation(title, slides, path)` | Generates Microsoft PowerPoint `.pptx` presentation via COM. |
| `obsidian_control`| `append_to_daily_note(url, key, text) -> bool` | Appends bullet entry to Obsidian daily note via REST API. |
| `obsidian_control`| `search_vault(url, key, query) -> list[dict]` | Searches local Obsidian markdown files. |
| `file_index.search`| `is_sensitive_file(name: str, path: str) -> bool` | Identifies and filters secrets, keys, and `.env` files. |
| `file_index.search`| `search_files_metadata(conn, query, root, max) -> list` | Performs fast file name lookup using SQLite FTS5. |
| `file_index.search`| `search_files_content(conn, query, root, max) -> list` | Searches inside document bodies using FTS5 content chunks. |
| `procedural_memory`| `get_dpapi_master_key() -> bytes` | Derives DPAPI-protected encryption key. |
| `procedural_memory`| `encrypt_procedure(payload: str) -> str` | Encrypts workflow JSON using Fernet. |
| `procedural_memory`| `scrub_workflow_intent(prompt: str) -> Tuple` | Sanitizes paths and pronouns into generic macro slots. |
| `procedural_memory`| `save_procedure(intent_hash, data) -> None` | Stores encrypted procedure in SQLite database. |
| `procedural_memory`| `find_procedure(intent_hash) -> Optional[dict]` | Retrieves cached procedure for instant zero-token replay. |
| `gateway_server` | `check_and_increment_quota(redis, user_id, tier)` | Verifies daily quota and triggers Groq fallback when needed. |
| `gateway_server` | `exchange_code_for_token(code, nonce) -> dict` | Exchanges single-use auth code for signed HS256 JWT. |
| `teaching.sources` | `add_local_file(slug, filename, data, allow_cloud)` | Ingests and chunks source documents up to 100 MB. |
| `teaching.pipeline`| `plan_course(topic, level, sources) -> dict` | Generates structured syllabus and concept tags. |
| `teaching.pipeline`| `write_lesson(slug: str, lid: str) -> str` | Drafts Markdown lesson with embedded diagram tokens. |
| `teaching.pipeline`| `write_quiz(slug: str, lid: str) -> dict` | Generates multiple-choice quiz questions with concept tags. |
| `teaching.pipeline`| `evaluate_feynman(slug, lid, explanation) -> dict` | Evaluates student explanation; returns score and flags. |
| `teaching.pipeline`| `check_relevance(topic: str, text: str) -> dict` | Filters distractions and off-topic speech in Feynman studio. |
| `teaching.heuristics`| `decide_adaptation(meta, lid, quiz_result) -> dict`| Determines next step (`proceed`, remedial lesson, or depth). |
| `session_context` | `get_generalized_applications() -> list[str]` | Lists active applications without leaking document titles. |
| `reliability` | `cleared(action: str) -> bool` | Checks if action type has cleared 20-run reliability bar. |

---

## 13. Forward Roadmap: What We Are Building Next

### 13.1 Phase 5: Repo-Explain Mode (Local Codebase Tutor)
- **Objective:** Turn any local Git repository or codebase folder into an interactive, step-by-step onboarding curriculum.
- **Architecture:**
  - Ingests repository path, builds AST syntax trees (`ast` for Python, tree-sitter for TypeScript/Go), and analyzes imports/exports.
  - Automatically identifies system architecture, entry points, module boundaries, and dependency flows.
  - Generates interactive Markdown lessons with Mermaid diagrams (`graph TD` for module dependencies, `sequenceDiagram` for request flows).
  - Generates comprehension quizzes testing function contracts, error states, and design patterns.

### 13.2 Business Mode (Executive Operations Suite)
- **Autonomous Financial Modeling & Excel Auditing:**
  - Ingests raw `.xlsx` spreadsheets via Win32 COM.
  - Performs formula validation, calculates variance across fiscal periods, generates pivot tables, and highlights budget anomalies.
- **Cross-Document Report Synthesis:**
  - Ingests disparate research papers, email threads, and contracts.
  - Compiles polished, executive-ready Word briefs (`.docx`) and branded PowerPoint presentations (`.pptx`) with structured charts and citations.
- **60-Second Morning Audio Executive Briefing:**
  - Triggered at system boot or via voice (`"Akira, morning briefing"`).
  - Scans Google Calendar agenda, unread VIP emails, and file modifications from the previous evening.
  - Synthesizes and speaks a 60-second priority roadmap while updating an ambient desktop HUD.

### 13.3 Hardware-Gated Local LLMs (100% Offline Edge Mode)
- Integrates `hardware_gate.py` with a lightweight bundled `llama-server` process.
- When an RTX GPU (4GB+ VRAM) and 16GB+ RAM are detected, Akira spins up quantized small language models (Qwen 2.5 7B, Phi-3 Mini) locally.
- Allows fully air-gapped, zero-network operation for classified, medical, or corporate environments.

### 13.4 Packaged Windows Distribution
- Single-click Windows installer (MSIX / InnoSetup) bundling Python 3.11 embedded runtime, pre-compiled ONNX models, and background tray service.

---
*Created for the Akira (Sensei) repository.*
