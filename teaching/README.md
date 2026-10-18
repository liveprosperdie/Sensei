# Akira Study Room — Open-Source Adaptive AI Tutor & Feynman Studio

> **An open-source, private, adaptive learning environment and personal AI tutor.**  
> Turn any topic or 100MB textbook into an interactive, step-by-step curriculum with diagrams, quizzes, and a voice-buffered Feynman Technique studio.

---

## 1. What Makes This Different?

Most AI educational tools are either simple question-answering bots or rigid static flashcard apps. **Study Room** is designed from the ground up as a **complete, self-contained educational operating room**:

1. **Zero Security / Data Concerns**:
   - Completely decoupled from invasive OS hooks, system controls, or dangerous shell automation.
   - Safe to run on any machine (Windows, macOS, Linux, or cloud containers).
   - **Zero-Storage Privacy**: When you upload a 100MB PDF textbook or research paper, the original binary is never saved to disk—only extracted, sanitized text excerpts are cached in your local workspace.
   - **Zero-Cloud Leak Mode**: Source documents can be marked as "Local Only", ensuring excerpts are never sent to external cloud APIs.

2. **On-Demand "Read Aloud" (Zero Voice Automation Hurdles)**:
   - Does not require always-on microphones, wake-word listeners, or complex audio pipelines.
   - When you want to listen, click **"Read aloud"** in any lesson: it speaks paragraphs sequentially, highlights the active sentence with `.reading`, and automatically scrolls matching source document citations into view.
   - Uses browser-native speech synthesis (`window.speechSynthesis`) for zero-latency, private, unmetered voice playback.

3. **The Feynman Technique Voice Studio**:
   - The ultimate test of true mastery: students explain what they learned in their own words.
   - **4.0-Second Thinking Pause Buffer**: You can pause mid-thought without the microphone abruptly cutting you off.
   - **Distraction & Off-Topic Filter**: Flags when real-world background noise or off-topic speech interferes.
   - **Mastery Analytics**: Generates a 0–100% mastery score, strength callouts, and clarification flags for subtle misconceptions.

4. **Adaptive Remediation Feedback Loop**:
   - Quizzes tag questions with sub-concept tags (`concept_tag`).
   - If a student scores below 70% or misses specific foundational concepts, Akira automatically updates the roadmap and inserts a targeted **Remedial Lesson** before moving forward.

5. **Offline Mermaid Diagrams & Dual-Pane Source Viewer**:
   - Generates architectural diagrams, flowcharts, and sequence maps rendered locally via vendored Mermaid.js.
   - Dual-pane split view (55% lesson, 45% original textbook/source) with bidirectional synchronized scrolling.

---

## 2. Quickstart: Running as a Standalone Web App

### Prerequisites
- Python 3.10+
- A free API key from [Groq](https://console.groq.com/) or [Google AI Studio](https://aistudio.google.com/) (or local Ollama / vLLM).

### Installation
```bash
# 1. Clone the repository
git clone https://github.com/liveprosperdie/Sensei.git
cd Sensei/teaching

# 2. Install lightweight dependencies (under 30 seconds)
pip install -r requirements.txt

# 3. Configure your free API keys in a .env file (or set environment variables)
echo GROQ_API_KEY=your_groq_api_key > .env
# or: echo GEMINI_API_KEY=your_gemini_key >> .env

# 4. Launch the Study Room web app
python -m teaching
```

Your browser will automatically open to `http://127.0.0.1:8765`.

---

## 3. Architecture & File Contracts

Models only output Markdown and structured JSON sidecars. The UI is deterministic, offline-first, and never speaks directly to third-party endpoints.

```
<teaching_workspace>/
  <topic_slug>/
    _topic_meta.json          # Single source of truth (curriculum, roadmap, adaptation log)
    lesson_1.md               # Lesson Markdown with {{diagram: ...}} & <!-- source-ref -->
    lesson_1_quiz.json        # Multiple-choice questions with sub-concept tags
    lesson_1_quiz_result.json # Student answers, scores, and timestamps
    lesson_1_feynman.json     # Feynman voice transcript, mastery score & flags
    diagrams/
      lesson_1_fig1.mmd       # Pure Mermaid diagram text
    sources/
      src_1.json              # Extracted text chunks from user-uploaded PDFs/docs
```

---

## 4. Supported Free & Local AI Providers

Study Room uses a resilient fallback chain across free API providers:

- **Groq Cloud (Free Tier)**: `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `openai/gpt-oss-20b`
- **Google Gemini (Free Tier)**: `gemini-2.0-flash`, `gemini-1.5-flash`
- **Cerebras (Free Tier)**: `gpt-oss-120b`
- **Local Models (100% Private)**: Set `TEACH_LOCAL_URL=http://localhost:11434/v1` for Ollama or LM Studio.

---

## 5. Security & Privacy Guarantees

- **No Remote Fonts/Scripts**: All assets (CSS, JS, fonts, Mermaid renderer) are vendored locally in `teaching/static/vendor/`.
- **Content Security Policy (CSP)**: `default-src 'self'` with zero inline scripts or framing.
- **Session Tokens**: Authentication uses an ephemeral `#t=token` URL anchor that is never transmitted in HTTP query parameters or server logs.
- **SSRF Defense**: External web source ingestion is restricted strictly to an approved list of academic and official documentation domains.
