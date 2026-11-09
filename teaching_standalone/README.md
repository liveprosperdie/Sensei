# Akira Study Room (Teaching Mode) — Open-Source Adaptive AI Tutor & Feynman Studio

> **An open-source, private, adaptive web learning environment and personal AI tutor.**  
> Turn any topic, university syllabus, or 100 MB PDF textbook into an interactive, step-by-step curriculum with synchronized source citations, offline Mermaid diagrams, adaptive quizzes, on-demand read-aloud, and a voice-buffered Feynman Technique studio.

---

## 1. Core Philosophy & Architecture

**Akira Study Room** is a standalone FastAPI web application (`teaching/`) completely decoupled from OS hooks, desktop automation, or always-on microphones so it can run safely on any laptop, Docker container, or public cloud server with zero security or data-privacy risks.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                   Browser UI (Offline-First HTML/CSS/JS)                   │
│  • Dual-Pane Synchronized Lesson (55%) + Source Textbook Viewer (45%)      │
│  • On-Demand "Read Aloud" with Sentence Highlighting & Citation Scroll     │
│  • Vendored Offline Mermaid.js Diagram Renderer (Strict CSP: 'self')       │
│  • Feynman Technique Studio (4.0s Thinking Pause Buffer + Mastery Card)    │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │ REST API (CSRF + Origin + Auth Gated)
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                 FastAPI Teaching Server (teaching/server.py)               │
│  • Multi-Tenant PBKDF2-HMAC-SHA256 Auth + 1-Click Instant Demo Mode        │
│  • Zero-Binary Source Ingestion (100 MB PDF/MD/TXT/Code -> Sanitized Text) │
│  • Server-Side Quiz Grading & Heuristic Remediation Engine (heuristics.py) │
│  • Free Cloud + Local LLM Fallback Chain (Groq / Gemini / Cerebras / Ollama│
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                 Deterministic Workspace Storage (workspace.py)             │
│  <workspace>/users/<user_id>/<topic_slug>/                                 │
│    ├── _topic_meta.json          (Curriculum, depth, adaptation history)   │
│    ├── lesson_1.md               (Markdown lesson + <!-- source-ref -->)   │
│    ├── lesson_1_quiz.json        (5 MCQs with concept_tag metadata)        │
│    ├── lesson_1_quiz_result.json (Server-graded score & missed concepts)   │
│    ├── lesson_1_feynman.json     (Transcript, mastery score & flags)       │
│    ├── diagrams/*.mmd            (Validated Mermaid diagram definitions)   │
│    └── sources/*.json            (Scrubbed text chunks; zero raw binaries) │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Everything Teaching Mode Can Do Today (Current Capabilities)

### A. Adaptive Curriculum & Lesson Generation (`pipeline.py`, `schema.py`)
- **Structured Multi-Lesson Roadmaps**:
  - Generates a 3-to-8 lesson progressive curriculum tailored to your chosen starting depth (`Beginner`, `Intermediate`, `Advanced`) and learning goal.
  - Enforces strict sequential mastery: future lessons remain locked until the current lesson's quiz or Feynman check is completed.
- **Grounded Markdown Lessons with Inline Diagrams & Citations**:
  - Every lesson is minimum 120+ words of clear, structured Markdown containing inline `{{diagram: ...}}` blocks and `<!-- source-ref: src_1#chunk_3 -->` citation anchors that link directly to your uploaded textbook or documentation.

### B. 100 MB Source Ingestion with Zero-Binary Privacy (`sources.py`)
- **Multi-Format Source Grounding**:
  - Upload PDFs (up to **100 MB**), Markdown, plain text, or source code files (`.py`, `.js`, `.ts`, `.rs`, `.go`, `.java`, `.cpp`, `.c`), or ingest approved academic/documentation URLs (`arxiv.org`, `wikipedia.org`, `docs.python.org`, `developer.mozilla.org`, `github.com`, etc.).
- **Zero-Binary Disk Storage & Secret Scrubbing**:
  - Raw uploaded PDF binaries are **never** written to disk—only extracted, chunked, secret-scrubbed plain text is saved inside `sources/src_N.json`.
- **Private / Local-Only Source Lock (`private=True`)**:
  - Mark sensitive documents as **Local Only**: `pipeline.py` enforces that private sources are never transmitted to any cloud API and are processed exclusively by your local model (`Ollama` / `vLLM`).

### C. Dual-Pane Synchronized Reader & On-Demand "Read Aloud" (`static/app.js`)
- **Dual-Pane Split View (55% Lesson / 45% Original Source)**:
  - Read the AI-synthesized lesson on the left while viewing the exact source textbook chunks on the right, with bidirectional click-to-scroll citation highlighting.
- **On-Demand "Read Aloud" (No Voice Automation Required)**:
  - Click **"Read aloud"** on any lesson whenever you want it spoken:
    - Uses browser-native `window.speechSynthesis` (zero cost, zero server latency, 100% offline-capable).
    - Highlights the currently spoken paragraph in real time (`.reading` CSS state) and automatically scrolls the matching textbook citation into view in the right-hand pane.
    - Includes Play, Pause/Resume, Stop, and Speed (`0.8x` – `1.5x`) controls.

### D. Server-Side Graded Quizzes & Automatic Remediation (`heuristics.py`)
- **Leak-Proof Server-Side Grading**:
  - Public quiz endpoints (`schema.public_quiz_view`) strip `correct_option_id` and `explanation` before sending questions to the browser so answers can never be inspected in DevTools before submission.
- **Concept-Tagged Adaptive Remediation Loop**:
  - Every quiz question carries a `concept_tag`.
  - **Score `>= 80%`**: Unlocks the next lesson and offers to step up difficulty depth.
  - **Score `50% – 79%`**: Flags the specific missed `concept_tag`s for targeted review.
  - **Score `< 50%` (or repeated misses on a concept)**: Automatically injects a custom **Remedial Lesson** (`remedial_for`) focused exclusively on the missed sub-concepts before moving forward (capped to prevent infinite loops).
- **"Too Advanced" Prerequisite Insertion**:
  - Clicking **"Too Hard / Need Basics"** dynamically inserts a foundational **Prerequisite Lesson** ahead of the current lesson and lowers the explanation depth.

### E. The Feynman Technique Voice & Text Studio (`server.py`, `static/app.js`)
- **Explain It in Your Own Words**:
  - After reading a lesson, teach the concept back in plain language (via microphone or keyboard).
- **4.0-Second Thinking Pause Buffer**:
  - Built-in speech-pause tolerance (`4000 ms`) lets you pause and think mid-sentence without the recorder cutting you off prematurely.
- **Distraction & Relevance Filter**:
  - Detects when background conversation or off-topic speech pollutes the transcript and asks you to retry cleanly without penalizing your mastery record.
- **Structured Mastery Scorecard**:
  - Evaluates your explanation on a **0–100% Mastery Score**, listing:
    - **What You Nailed** (verified conceptual strengths),
    - **Gaps & Misconceptions** (precise corrections referenced back to the lesson), and
    - **Follow-Up Socratic Prompt** to close the final gap.

### F. Offline Mermaid Diagrams & Hardened Web Security
- **Vendored Mermaid.js (`static/vendor/mermaid.min.js`)**:
  - Renders flowcharts, sequence diagrams, state diagrams, and class diagrams 100% locally in the browser with sanitizer guards (`schema.validate_mermaid`) that block script/HTML injection.
- **Strict Security Headers & Multi-Tenant Isolation (`auth.py`, `server.py`)**:
  - Enforces `Content-Security-Policy: default-src 'self'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, PBKDF2-HMAC-SHA256 password hashing, per-user workspace isolation (`users/<user_id>/`), and 1-click **Instant Demo Mode**.

---

## 3. Everything We Wish Teaching Mode To Do (Future Roadmap & Vision)

Below is the roadmap of features we are designing and building next for **Akira Study Room**:

1. **Multiplayer Collaborative Study Rooms & Peer Feynman Battles**:
   - Real-time WebSocket rooms where 2–5 friends study the same textbook chapter together, take synchronized quizzes, and play **Peer Feynman Mode** (one student explains the concept, the other students + AI score the explanation and ask Socratic follow-ups).
2. **Interactive Live Code Sandbox & Executable Math Canvas (Pyodide / WebAssembly)**:
   - Embed zero-server, in-browser executable Python / JavaScript cells (via Pyodide) and interactive Desmos/GeoGebra-style math sliders directly inside technical lessons so students can tweak hyperparameters, run algorithms, and visualize matrix transformations live.
3. **Socratic Live Whiteboard ("Draw-While-Speaking" Tutor)**:
   - Upgrade "Read Aloud" into a synchronized **Live Canvas Walkthrough** where Akira progressively draws and highlights nodes on the Mermaid/Excalidraw diagram in sync with each spoken sentence, just like a human professor at a whiteboard.
4. **Automatic Spaced-Repetition (FSRS) Flashcard & Anki Deck Export**:
   - Every missed quiz `concept_tag` and Feynman misconception automatically generates a Q&A card scheduled via the **Free Spaced Repetition Scheduler (FSRS)** algorithm, with 1-click `.apkg` export to **Anki** or **Obsidian Spaced Repetition**.
5. **YouTube Lecture, Podcast & Timestamped Audio Ingestion**:
   - Paste any YouTube lecture or MIT OpenCourseWare playlist URL to automatically ingest transcripts, align lessons to exact video timestamps (`<!-- video-ref: 14:22 -->`), and jump the embedded video player to the exact moment a concept is derived.
6. **OCR + Formula Extraction for Scanned PDFs & Handwritten Notes**:
   - Integrate lightweight local OCR / math-to-LaTeX extraction so scanned textbooks, photographed whiteboard lectures, and handwritten iPad PDFs ingest as cleanly as native digital PDFs.
7. **Cross-Course Personal Knowledge Graph & Mastery Radar**:
   - A global visual skill tree connecting every `concept_tag` you have mastered across all courses (e.g., seeing how *Eigenvalues* in your Linear Algebra room connects to *PCA* in your Machine Learning room and *Markov Chains* in Probability).
8. **1-Click Community Course Sharing & University LMS / Notion / Obsidian Sync**:
   - Export any completed Study Room as a shareable static link or `.akira-course` bundle so teachers and creators can publish interactive courses, and sync personal study notes directly into Obsidian or Notion.

---

## 4. Quick Start (Run Locally in 60 Seconds)

### Prerequisites
- Python 3.10+
- A free API key from [Groq](https://console.groq.com/keys) or [Google AI Studio](https://aistudio.google.com/) (or local [Ollama](https://ollama.com/))

### Local Installation
```bash
# 1. Navigate to the standalone teaching app
cd teaching_standalone   # (or remain in repo root)

# 2. Install lightweight web dependencies
pip install -r requirements.txt

# 3. Configure your free API key
cp .env.example .env
# Edit .env and set GROQ_API_KEY=your_free_groq_key

# 4. Run the 27-test verification suite
python -m unittest tests.test_teaching_mode -v

# 5. Start the Study Room Web App
python -m teaching --public --host 127.0.0.1 --port 8787
```
Then open **`http://127.0.0.1:8787`** in your browser.

### Docker & One-Click Cloud Deployment
```bash
# Run with Docker Compose
docker compose up --build -d
# Open http://localhost:8080
```
Cloud manifests are pre-configured for **Render** (`render.yaml`), **Railway** (`railway.json`), and **Fly.io** (`fly.toml`).
