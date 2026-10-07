# Akira (Sensei) — System Overview, Progress & Strategic Roadmap

**Document Version:** 1.0  
**Target Audience:** Core Engineering, Product Strategy, Co-Founder  
**Last Updated:** October 2026  

---

## 1. Executive Summary

**Akira** is an intelligent, voice-first desktop agent and autonomous operating companion built specifically for Windows. Rather than being a simple chatbot, Akira operates as a **layered operating companion**: it hears the user, reasons across tiered AI models, inspects and interacts with the desktop environment (Office, Obsidian, Google Workspace, File System, Web), enforces cryptographic guardrails, and stores verified workflows in an encrypted procedural cache.

Having stabilized the foundational operating system, voice pipeline, and security harness, our primary commercial differentiation shifts to **high-value domain modes**:
1. **Teaching Mode (Adaptive Learning Environment)**: An interactive, locally-rendered personal tutor that dynamically drafts tailored lessons, generates quizzes, evaluates sub-concept comprehension, and inserts remedial lessons on the fly.
2. **Business Mode**: Executive-grade workspace automation, cross-app report synthesis, and document intelligence.

---

## 2. Where We Started & How Far We Have Come

```
Phase 0: Raw Voice Prototype
  • Basic voice loop & direct OS script execution
  • High latency, unbounded API costs, unsafe shell execution
           │
           ▼
Phase 1: Tiered Architecture & Guardrails
  • Tier 0 (Local Regex) + Tier 1 (Free Groq 120B/27B) + Tier 2 (Claude Sonnet/Opus)
  • Cryptographic HMAC GuardTokens & Confirmation Gates for destructive actions
  • Windows COM automation (Word, Excel, PowerPoint) + Google Workspace + Obsidian
           │
           ▼
Phase 2: Thin Server Gateway & Security Hardening
  • Enterprise-grade auth via FastAPI & Redis gateway (JWT session management)
  • Zero-Content Logging guarantee (no user prompts, audio, or clipboard logged on server)
  • Non-BYOK architecture (API keys secured server-side with automatic Groq fallback)
           │
           ▼
Phase 3: Procedural Memory (Phases A & B Completed)
  • Phase A: DPAPI-encrypted SQLite procedural store (`%LOCALAPPDATA%\Akira\procedures.db`)
  • PII & deictic scrubbing, plan hashing, and deterministic parameter extraction
  • Phase B: Non-disruptive shadow mode recorder + 100% Guard Chain parity validation
           │
           ▼
Phase 4 (Current Horizon): Domain Selling Points
  • Teaching Mode: Adaptive learning environment with deterministic file-contract architecture
  • Business Mode: Automated business workflows & cross-tool report synthesis
```

### Major Milestones Completed:
- [x] **Sub-second Reflex Routing**: Instantaneous regex reflex routing for common desktop tasks at 0 tokens and <1ms latency.
- [x] **Dual-Brain Hybrid Routing**: 80%+ of routine natural language queries handled free via Groq 120B/27B; high-reasoning workflows routed to Claude Sonnet/Opus.
- [x] **Layered Defense-in-Depth**:
  - `action_guard.py` & `guard_rules.py` intercept and inspect every generated action before execution.
  - Spoken confirmation gate (`"yes"`, `"proceed"`) required for destructive operations (shutdown, file wipes, bulk sends).
  - External web & email data wrapped in `<untrusted_external_context>` XML defense tags to defeat indirect prompt injections.
- [x] **Production Workspace Automation**:
  - Direct Win32 COM automation of Microsoft Word, Excel, and PowerPoint.
  - Native Obsidian integration via Local REST API with smart note resolution.
  - Google Workspace integration (Gmail, Calendar, Drive, Docs, Sheets, Slides).
- [x] **Lightweight Wake-Word & Self-Contained Deployment**:
  - Bundled custom `akira.onnx` (~14 KB) and `akira.onnx.data` (~200 KB) openWakeWord models directly into repository.
  - Cleaned repository of presentation and non-functional documents for seamless co-founder onboarding (`COFOUNDER_SETUP_GUIDE.md`).

---

## 3. Current Technical Stack

| Layer | Technologies & Frameworks | Key Responsibilities |
| :--- | :--- | :--- |
| **Voice & Speech** | Silero VAD (PyTorch hub), openWakeWord (ONNX Runtime), OpenAI Whisper, Edge-TTS, PyTTSx3, PyAudio | Real-time wake-word detection (`"Akira"`), low-latency VAD voice chunking, speech-to-text, and natural neural voice feedback. |
| **Model Routing & AI** | Anthropic Claude (Opus 5, Sonnet 5, Haiku 4.5), Groq Cloud API (Llama 3.3 70B, GPT-OSS 120B), Google Gemini 1.5/2.0 Flash | Tiered cognitive hierarchy: cheap/free models for command translation and intent filtering; state-of-the-art models for complex reasoning. |
| **Safety & Guardrails** | Custom Rule Engine, HMAC-SHA256 Token Gates, XML Context Sanitizers | Cryptographic `GuardToken` pipeline ensuring no action executes without explicit safety classification and anti-tampering verification. |
| **OS & App Automation** | Windows Win32 API (`pywin32`), COM Dispatch, Selenium (Chrome/Brave), Obsidian Local REST API | Native Windows desktop automation, document authoring, file management, and browser automation. |
| **Procedural Memory** | Windows DPAPI (`win32crypt`), Cryptography (`Fernet`), SQLite3 | Local encrypted caching of validated multi-step procedures to eliminate redundant LLM calls and enable offline execution. |
| **Gateway & Auth** | FastAPI, Uvicorn, Redis, Python-JOSE (JWT HS256), Pydantic v2 | Thin cloud proxy managing user subscription tiers, daily quota ceilings, and automatic fallback without exposing master API keys. |
| **Hardware Inspection** | WMI, PyTorch CUDA inspection, psutil | Hardware capability detection (RTX 2050, VRAM, RAM) to gate local LLM serving (`llama-server`). |
| **Desktop UI / Sprites** | Tkinter, Pygame sprite engine, System Tray | Desktop companion sprite animation, listening states, and ambient UI cues. |

---

## 4. Where We Are Heading: The Main Selling Points

While Akira provides general OS assistance, our market differentiation and monetization rest upon **specialized domain execution**:

```
                       ┌───────────────────────────────────┐
                       │       AKIRA OPERATING BASE        │
                       │  Voice + Routing + Guard + Comms  │
                       └─────────────────┬─────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
   ┌───────────────────────────┐                   ┌───────────────────────────┐
   │       TEACHING MODE       │                   │       BUSINESS MODE       │
   │   (Adaptive Learning)     │                   │   (Executive Operations)  │
   │                           │                   │                           │
   │ • File-contract skeleton  │                   │ • Multi-doc report synth  │
   │ • JIT Lesson & Quiz gen   │                   │ • Excel financial model   │
   │ • Sub-concept remediation │                   │ • Cross-app orchestration │
   │ • Mermaid dynamic visuals │                   │ • Meeting prep & briefing │
   │ • "Repo-Explain" course   │                   │ • Autonomous audit trails │
   └───────────────────────────┘                   └───────────────────────────┘
```

---

## 5. Teaching Mode Deep Dive: Architecture & Implementation Strategy

### 5.1 The Core Design Principle
**Models only produce Markdown and small structured JSON sidecars. The UI environment is dumb, deterministic, and reusable.**  
The model never writes UI code, and the UI never directly calls an LLM. All communication happens through a standardized directory contract:

```
Akira_Notes/
  <topic_slug>/
    _topic_meta.json          ← Single source of truth (curriculum, status, revision log)
    lesson_1.md               ← Standard Markdown with {{diagram: ...}} tokens
    lesson_1_quiz.json        ← Structured questions with sub-concept tags
    lesson_1_quiz_result.json ← Student responses, scores, and timestamp
    lesson_1_feynman.json     ← Feynman Technique spoken explanation, mastery score & flags
    diagrams/
      lesson_1_fig1.mmd       ← Pure Mermaid diagram text
```

### 5.2 The 5 UI Views (Local Web View)
1. **Topic Dashboard**: Tracks all active and completed subjects, shows course progress percentage, and presents "Continue" or "New Topic" prompts.
2. **Interactive Lesson Reader**: Renders Markdown with clean typography, automatically substitutes `{{diagram: ...}}` tokens with rendered Mermaid diagrams/SVGs, and presents paginated chunk reading.
3. **Interactive Quiz Engine**: Reads quiz JSON, presents multiple-choice questions, grades answers locally, reveals explanations, and writes the quiz result file.
4. **Feynman Technique Studio**: Students explain what they learned in their own natural words. Voice-driven with a 4.0s thinking buffer, real-life distraction detector, mastery scoring, and Akira's misconception/gap clarification flags.
5. **Adaptive Progress & History Timeline**: Visually displays the `revision_log`, proving to the student that the curriculum actively adapted to their quiz performance (e.g., *"Inserted Remedial Lesson: Service Discovery — triggered by 50% score on Lesson 2"*).

### 5.3 The Adaptation Feedback Loop
```
Student submits quiz → writes lesson_N_quiz_result.json
       │
       ▼
Client computes score & extracts missed `concept_tag`s
       │
       ▼
Lightweight BRAIN "Plan Check" Call
   Input: Current `_topic_meta.json` + Quiz result summary
   Output: One of:
     1. "proceed"                (Standard path — common case)
     2. "insert_remedial_lesson" (Targeted lesson on missed sub-concept)
     3. "adjust_depth"           (Increase or decrease difficulty)
       │
       ▼
_topic_meta.json updated (revision_log appended)
       │
       ▼
Next lesson generated JIT (Just-In-Time)
```

### 5.4 Teaching Mode Roadmap Status
- [x] **Phase 1: Static Skeleton & File Contract**: Finalized JSON/Markdown contracts, local path isolation (`%LOCALAPPDATA%\Akira\teaching_workspace`), and atomic schema writers.
- [x] **Phase 2: Live Generation & Dynamic Quizzing**: Dual-tiered LLM pipeline (HEAD for syllabus, Worker for JIT lesson/quiz drafting), calibration feedback loop, local grading engine.
- [x] **Phase 3: Adaptive Remediation**: Local heuristic grading engine, dynamic remedial lesson injection on sub-concept failure, and visible adaptation timeline.
- [x] **Phase 4: Visual Diagramming & Dual-Pane Source Viewer**:
  - Vendored local Mermaid.js renderer for dynamic architectural diagrams.
  - Dual-pane split UI (55% lesson, 45% source document viewer).
  - Multi-format source ingestion (PDF, DOCX, TXT, MD, and approved web pages).
  - Bidirectional synchronized scrolling with excerpt highlights (`<!-- source-ref -->`).
  - Strict security harness (ephemeral loopback binding, URL-fragment `#t=token` auth, secret scrubbing, SSRF-safe scraper).
  - Voice integration: 0-token `<0.1ms` reflex (`"open study room"`, `"teach me [topic]"`, `"study [topic]"`) registered in `tiered_classifier.py`, `executor.py`, `guard_rules.py`, and `action_router.py`.
- [ ] **Phase 5: Repo-Explain Mode (Local Codebase Tutor)**: Turn any local Git repository or code folder into a structured, step-by-step adaptive curriculum using the same file-contract architecture.

---

## 6. Business Mode & Future Horizons (Upcoming)

Following the Teaching Mode rollout, **Business Mode** leverages Akira's Win32 COM, browser, and email capabilities to automate executive workflows:
- **Financial & Excel Analysis**: Ingests raw `.xlsx` sheets, runs formula validation, builds summary pivot tables, and highlights variance trends.
- **Deck & Report Generation**: Automatically transforms research briefs into structured PowerPoint (`.pptx`) presentations and formatted Word reports.
- **Morning Executive Briefings**: Scans calendar events, unread priority emails, and local file updates to give a 60-second synthesized audio + visual agenda.

---

## 7. Current Project Health & Summary

- **Repository Status**: Main branch augmented with production-grade `teaching/` package and voice triggers.
- **Dependencies**: Fully pinned in `requirements.txt`.
- **Security Posture**: Zero plaintext credentials, DPAPI local encryption active, ephemeral localhost session tokens, 100% Guard coverage.
- **Current Milestone**: Teaching Mode core & voice launcher complete. Ready for Phase 5 (Repo-Explain Mode) or Business Mode exploration.

