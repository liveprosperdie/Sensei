# Akira (Sensei) — Complete System Handout & Engineering Context

> **Document Purpose:** Complete, single-file context handout containing the architectural foundations, production-verified patterns, actual working code snippets, and all latest features (Teaching Mode, Feynman Technique Voice Studio, 100MB Document Pipeline, Procedural Memory, Thin Gateway, and Business Roadmap). Designed for high-fidelity handoff to Claude, engineering co-founders, or core developers.
> **Repository:** `liveprosperdie/Sensei`
> **Active Environment:** Windows 10/11, Python 3.11+, PyTorch (Silero VAD), ONNX Runtime, FastAPI, Redis, Win32 COM.

---

## 1. Executive System Overview

**Akira (Sensei)** is a voice-first, layered desktop operating companion and autonomous cognitive agent built natively for Windows. Rather than being an ephemeral chat web-app, Akira operates as an **operating companion** that:
1. **Listens & Speaks Continuously**: On-device openWakeWord (`akira.onnx`), Silero VAD, Whisper speech-to-text, and Edge-TTS / PyTTSx3 neural voice synthesis.
2. **Operates the Desktop via Native Integrations**: Win32 COM dispatch for Microsoft Word, Excel, and PowerPoint; Obsidian vault integration via Local REST API; Google Workspace; Selenium browser control.
3. **Enforces Cryptographic Safety**: Every OS action requires an HMAC-SHA256 `GuardToken`. Destructive actions trigger a spoken confirmation gate (`"yes"`, `"proceed"`). External web/email data is sealed in `<untrusted_external_context>` XML tags.
4. **Caches Procedural Memory**: Replays multi-step workflows with zero LLM tokens using a local DPAPI-encrypted SQLite store with PII and deictic scrubbing.
5. **Differentiates via High-Value Domain Modes**:
   - **Teaching Mode**: Local adaptive classroom with JIT syllabus drafting, 100MB PDF/DOCX ingestion, Mermaid diagrams, automated remedial lessons, and a **Feynman Technique Voice Studio** with thinking pause buffers and distraction detection.
   - **Business Mode (Upcoming)**: Autonomous Excel financial modeling, cross-document report synthesis, and 60-second morning audio executive briefings.

---

## 2. High-Level Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                        USER DESKTOP & MICROPHONE                       │
│  Wake-Word ("Akira") ──► Silero VAD ──► Whisper STT ──► Spoken Audio   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  LAYER 1: TIERED ROUTING & INTENT                      │
│  • Tier 0 Regex Reflexes (<0.1ms, 0 tokens) via `tiered_classifier.py` │
│  • Tier 1 Head: Free Groq (Llama 3.3 70B, GPT-OSS 120B) & Gemini Flash │
│  • Tier 2 Head: Claude Sonnet/Opus (Server-gated, bypassable in dev)   │
│  • Zero-Claude Mode: `AKIRA_DISABLE_CLAUDE=true` (100% Free APIs)      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  LAYER 2: DEFENSE-IN-DEPTH SAFETY                      │
│  • `action_guard.py` & `guard_rules.py` interceptors                   │
│  • Cryptographic HMAC-SHA256 `GuardToken` (anti-tamper token gates)    │
│  • Spoken Confirmation Gate ("yes"/"proceed") for high-risk actions    │
│  • `<untrusted_external_context>` anti-prompt injection wrappers       │
│  • Codebase Self-Protection against repo file wipes or edits           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  LAYER 3: EXECUTION & WORKSPACE ENGINES                │
│  • Win32 COM: Word, Excel, PowerPoint (`office_control.py`)           │
│  • Obsidian Vault: Local REST API & markdown sync (`obsidian_api.py`)  │
│  • Google Workspace: Gmail, Calendar, Drive, Docs, Sheets, Slides      │
│  • Web Browser: Selenium driver for Chrome / Brave                     │
│  • System Controls: Volume, brightness, window focus, process manager  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
         ┌──────────────────────────┴──────────────────────────┐
         ▼                                                     ▼
┌──────────────────────────────────┐  ┌──────────────────────────────────┐
│   LAYER 4: PROCEDURAL MEMORY     │  │   LAYER 5: TEACHING MODE ROOM    │
│ • Local DPAPI-encrypted SQLite   │  │ • Local FastAPI / Uvicorn server │
│ • PII & deictic term scrubbing   │  │ • 100MB PDF / DOCX source parser │
│ • Plan hashing & param extractor │  │ • JIT Lesson & Quiz generation   │
│ • Shadow Mode execution recorder │  │ • Adaptive remediation on errors │
│ • Zero-token instant replay      │  │ • Feynman Voice Practice studio  │
│                                  │  │ • Local vendored Mermaid viewer  │
└──────────────────────────────────┘  └──────────────────────────────────┘
```

---

## 3. Real Code: Tiered Cognitive Routing & Zero-Claude Mode

Akira routes all intent hierarchically to minimize latency and eliminate unbounded cloud costs.

### 3.1 Tier 0 Reflex Routing (`tiered_classifier.py` & `action_router.py`)
Common commands (system volume, media controls, study room launcher) resolve instantaneously without LLM calls:

```python
# From tiered_classifier.py
REFLEX_PATTERNS = [
    # Study room launcher (Teaching Mode)
    (re.compile(r"^(open\s+)?(study\s+room|teaching\s+mode)$", re.I), "open_study_room", {}),
    (re.compile(r"^(teach\s+me|study)\s+(?P<topic>.+)$", re.I), "open_study_topic", {"topic": "{topic}"}),
    # System Controls
    (re.compile(r"^(mute|unmute|mute\s+volume)$", re.I), "set_volume", {"action": "mute"}),
    (re.compile(r"^volume\s+(up|down)$", re.I), "adjust_volume", {"direction": "{1}"}),
    (re.compile(r"^what time is it$", re.I), "get_time", {}),
]

def classify_reflex(user_text: str) -> Optional[RoutingDecision]:
    cleaned = user_text.strip().lower()
    for pattern, action_name, param_template in REFLEX_PATTERNS:
        m = pattern.match(cleaned)
        if m:
            params = {k: m.group(v.strip("{}")) if v.startswith("{") else v 
                      for k, v in param_template.items()}
            return RoutingDecision(tier=0, action=action_name, params=params, latency_ms=0.05)
    return None
```

### 3.2 Model Pool & Zero-Claude Mode (`model_pool.py`)
When running in 100% Free API mode (`AKIRA_DISABLE_CLAUDE=true`), Claude calls are strictly rejected and routed through Groq or Gemini:

```python
# From model_pool.py
DISABLE_CLAUDE = os.getenv("AKIRA_DISABLE_CLAUDE", "false").lower() in ("true", "1", "yes")

def get_best_available_model(task_type: str = "general") -> ModelClient:
    if DISABLE_CLAUDE:
        # Strict free-tier routing: Groq Llama 3.3 70B / Gemini Flash only
        if groq_available():
            return GroqClient(model="llama-3.3-70b-versatile")
        elif gemini_available():
            return GeminiClient(model="gemini-2.0-flash")
        raise RuntimeError("No free tier models available and Claude is explicitly disabled.")
    
    # Standard multi-tier routing
    ...
```

---

## 4. Real Code: Cryptographic Guardrails & Safety Pipeline

Akira implements defense-in-depth safety where every generated action must pass an intercepting guard and receive an anti-tamper HMAC token.

### 4.1 HMAC-SHA256 GuardToken Pipeline (`guard.py` & `action_guard.py`)

```python
# From guard.py & action_guard.py
import hmac
import hashlib
import time

GUARD_SECRET = os.getenv("AKIRA_GUARD_SECRET", secrets.token_hex(32)).encode()

def issue_guard_token(action: str, target: str, risk_level: str) -> str:
    timestamp = str(int(time.time()))
    payload = f"{action}:{target}:{risk_level}:{timestamp}".encode()
    sig = hmac.new(GUARD_SECRET, payload, hashlib.sha256).hexdigest()
    return f"{action}:{timestamp}:{sig}"

def verify_guard_token(token: str, action: str, target: str, max_age_secs: int = 30) -> bool:
    try:
        parts = token.split(":")
        tok_action, timestamp_str, sig = parts[0], parts[1], parts[2]
        if tok_action != action:
            return False
        timestamp = int(timestamp_str)
        if abs(time.time() - timestamp) > max_age_secs:
            return False  # Expired token
        
        # Verify HMAC against risk level
        for risk in ("safe", "low", "medium", "high"):
            payload = f"{action}:{target}:{risk}:{timestamp_str}".encode()
            expected = hmac.new(GUARD_SECRET, payload, hashlib.sha256).hexdigest()
            if hmac.compare_digest(sig, expected):
                return True
        return False
    except Exception:
        return False
```

### 4.2 Spoken Confirmation Gate (`guard_rules.py`)

```python
# From guard_rules.py
HIGH_RISK_ACTIONS = {
    "system_shutdown": "Shut down the computer",
    "delete_file": "Permanently delete file {path}",
    "send_bulk_email": "Send email to {recipient_count} recipients",
    "wipe_directory": "Clear directory {dir}",
}

def check_action_risk(action: str, params: dict) -> Tuple[str, Optional[str]]:
    if action in HIGH_RISK_ACTIONS:
        prompt = HIGH_RISK_ACTIONS[action].format(**params)
        return "CONFIRMATION_REQUIRED", f"Akira needs confirmation: Are you sure you want to {prompt}?"
    return "SAFE", None
```

### 4.3 XML Untrusted Context Defense (`tiered_classifier.py`)
All external web content, emails, or student documents are enclosed in strict containment delimiters to neutralize prompt injection:

```python
def wrap_untrusted(content: str, source_type: str = "web") -> str:
    sanitized = content.replace("</untrusted_external_context>", "[ESCAPED_TAG]")
    return f'<untrusted_external_context type="{source_type}">\n{sanitized}\n</untrusted_external_context>'
```

---

## 5. Real Code: Desktop & OS Automation Suite

### 5.1 Microsoft Office Win32 COM Automation (`office_control.py`)
Direct Windows COM interface for Word, Excel, and PowerPoint without third-party dependencies:

```python
# From office_control.py
import win32com.client

def create_word_document(title: str, sections: list[dict], save_path: str):
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Add()
        # Title
        p_title = doc.Paragraphs.Add()
        p_title.Range.Text = title
        p_title.Range.Font.Size = 22
        p_title.Range.Font.Bold = True
        p_title.Range.InsertParagraphAfter()
        
        # Sections
        for sec in sections:
            p_head = doc.Paragraphs.Add()
            p_head.Range.Text = sec["heading"]
            p_head.Range.Font.Size = 14
            p_head.Range.Font.Bold = True
            p_head.Range.InsertParagraphAfter()
            
            p_body = doc.Paragraphs.Add()
            p_body.Range.Text = sec["content"]
            p_body.Range.Font.Size = 11
            p_body.Range.InsertParagraphAfter()
            
        doc.SaveAs2(save_path)
    finally:
        doc.Close()
        word.Quit()
```

### 5.2 Obsidian Vault Local REST API (`obsidian_control.py`)

```python
# From obsidian_control.py
import requests

def append_to_daily_note(vault_url: str, api_key: str, text: str) -> bool:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "text/markdown"
    }
    r = requests.post(f"{vault_url}/periodic/daily/", data=f"\n- {text}", headers=headers, verify=False)
    return r.status_code in (200, 204)
```

---

## 6. Real Code: Procedural Memory (Phases A & B)

Procedural memory caches verified multi-step macros locally, enabling offline, zero-token replay.

### 6.1 DPAPI Encryption (`procedural_memory/crypto.py`)

```python
# From procedural_memory/crypto.py
import win32crypt  # Windows Data Protection API (DPAPI)
from cryptography.fernet import Fernet
import base64

def get_dpapi_master_key() -> bytes:
    # Encrypts a persistent symmetric key using user's Windows login credentials
    key_file = os.path.expandvars(r"%LOCALAPPDATA%\Akira\proc_key.dat")
    if os.path.exists(key_file):
        encrypted = open(key_file, "rb").read()
        return win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1]
    raw_key = Fernet.generate_key()
    encrypted = win32crypt.CryptProtectData(raw_key, "Akira Proc Key", None, None, None, 0)
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    open(key_file, "wb").write(encrypted)
    return raw_key

def encrypt_procedure(payload: str) -> str:
    key = get_dpapi_master_key()
    f = Fernet(key)
    return f.encrypt(payload.encode()).decode()

def decrypt_procedure(ciphertext: str) -> str:
    key = get_dpapi_master_key()
    f = Fernet(key)
    return f.decrypt(ciphertext.encode()).decode()
```

### 6.2 PII & Deictic Scrubbing (`procedural_memory/scrubber.py`)
Removes concrete filenames, dates, and deictic references (`"this spreadsheet"`) to store generic parameterized templates:

```python
# From procedural_memory/scrubber.py
import re

DEICTIC_RE = re.compile(r"\b(this|that|these|those|current)\s+(file|folder|note|doc|sheet)\b", re.I)
PATH_RE = re.compile(r"[A-Za-z]:\\[\w\s\\.-]+|/[\w\s/.-]+")

def scrub_workflow_intent(user_prompt: str) -> Tuple[str, dict]:
    params = {}
    # Extract file paths into slots
    def _path_sub(m):
        idx = len(params)
        slot = f"{{PATH_PARAM_{idx}}}"
        params[slot] = m.group(0)
        return slot
    
    scrubbed = PATH_RE.sub(_path_sub, user_prompt)
    scrubbed = DEICTIC_RE.sub(r"{TARGET_\2}", scrubbed)
    return scrubbed, params
```

---

## 7. Real Code: Thin Server Gateway & Security Contract

### 7.1 Zero-Content Logging Guarantee (`gateway_server/main.py`)
The gateway never writes prompts, audio, or completions to disks or logs. Only integer quota counters are maintained in Redis:

```python
# From gateway_server/quota.py
def record_usage(redis_client, user_id: str, is_claude: bool) -> dict:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    key = f"akira:user:{user_id}:quota_{'claude' if is_claude else 'groq'}:{today}"
    current = redis_client.incr(key)
    if current == 1:
        redis_client.expire(key, 86400 * 2)  # 48 hr TTL
    return {"user_id": user_id, "count": current, "date": today}
```

### 7.2 Non-BYOK Architecture & Seamless Groq Fallback
Standard users get 30 Claude turns/day, Pro users get 53 turns/day. When Claude caps are reached, the gateway **automatically shifts** the user to free Groq API for up to 250 fallback turns rather than terminating the session.

---

## 8. Real Code & Architecture: Adaptive Teaching Mode

Teaching Mode is Akira's core educational differentiator: a zero-cloud-leak, adaptive classroom with multi-modal source reading, Mermaid visual diagrams, quizzes, and the Feynman technique.

### 8.1 The Strict File-Contract Architecture (`teaching/schema.py`)
The AI model produces **only Markdown and structured JSON sidecars**. The UI is deterministic and never communicates with an LLM directly:

```
Akira_Notes/
  <topic_slug>/
    _topic_meta.json          ← Source of truth (curriculum, adaptation log, status)
    lesson_1.md               ← Clean Markdown with {{diagram: ...}} and <!-- source-ref -->
    lesson_1_quiz.json        ← Questions with sub-concept tags (concept_tag)
    lesson_1_quiz_result.json ← Student submissions, scores, and timestamps
    lesson_1_feynman.json     ← Spoken Feynman explanation, transcript & evaluation
    diagrams/
      lesson_1_fig1.mmd       ← Pure Mermaid diagram text
    sources/
      src_1.json              ← Extracted text chunks from user-uploaded PDFs/docs
```

### 8.2 100 MB Document Ingestion Pipeline (`teaching/sources.py`)
Recently upgraded to support full engineering textbooks (e.g., Boylestad's *Electronic Devices and Circuit Theory*):

```python
# From teaching/sources.py & config.py
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_PAGES_PER_FILE = 800

def add_local_file(slug: str, filename: str, data: bytes, allow_cloud: bool) -> dict:
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise SourceError(f"file is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext == ".pdf":
        pages = _extract_pdf(data)  # pypdf extraction capped at MAX_PAGES_PER_FILE
    elif ext == ".docx":
        pages = _extract_docx(data)
    elif ext in (".txt", ".md"):
        pages = _extract_text(data)
    else:
        raise SourceError("Unsupported file type")
    
    sid = _next_src_id(slug)
    workspace.write_json(slug, f"sources/{sid}.json", {
        "id": sid, "name": filename, "type": ext.lstrip("."),
        "allow_cloud": allow_cloud, "pages": pages
    })
    return {"id": sid, "name": filename, "page_count": len(pages)}
```

### 8.3 Adaptive Remediation Feedback Loop (`teaching/heuristics.py`)
When a student takes a quiz, Akira grades it locally and checks for concept failure:

```python
# From teaching/heuristics.py
def decide_adaptation(meta: dict, current_lid: str, quiz_result: dict) -> dict:
    score = quiz_result["score"]  # 0.0 - 1.0
    missed_concepts = quiz_result.get("missed_concept_tags", [])
    
    if score >= 0.70:
        return {"action": "proceed", "reason": "Passed quiz successfully"}
    
    if missed_concepts:
        primary_weakness = missed_concepts[0]
        return {
            "action": "insert_remedial_lesson",
            "concept": primary_weakness,
            "title": f"Targeted Review: {primary_weakness.replace('_', ' ').title()}",
            "reason": f"Scored {int(score*100)}% on {current_lid}; missed '{primary_weakness}'"
        }
    
    return {"action": "adjust_depth", "direction": "easier"}
```

---

## 9. Real Code: The Feynman Technique Voice Studio

The Feynman Studio allows students to lock in what they learned by speaking explanations aloud in their own words.

### 9.1 Frontend Audio Visualizer & 4.0s Thinking Buffer (`teaching/static/app.js`)
Handles real-time speech transcription, dynamic waveform rendering, and a **4.0-second silence buffer** so students can pause to think without speech recognition cutting off:

```javascript
// From teaching/static/app.js
let pauseTimer = null;
const THINK_BUFFER_MS = 4000; // 4.0 seconds tolerance for thought pauses

recognition.onresult = (e) => {
  clearTimeout(pauseTimer);
  let transcriptChunk = '';
  for (let i = e.resultIndex; i < e.results.length; ++i) {
    transcriptChunk += e.results[i][0].transcript;
  }
  inputArea.value += transcriptChunk;
  
  // Distraction / Relevance Check
  checkRelevanceInBackground(transcriptChunk);
  
  // Set buffer timer before finalizing speech turn
  pauseTimer = setTimeout(() => {
    updateMicStatus('Listening paused — waiting for your thought...');
  }, THINK_BUFFER_MS);
};
```

### 9.2 Backend Feynman Evaluation Engine (`teaching/pipeline.py`)
Evaluates the student's spoken transcript against lesson concepts, generating mastery scoring, strength callouts, and clarification flags for misconceptions:

```python
# From teaching/pipeline.py
FEYNMAN_SYSTEM = """You are Akira, an encouraging, master-level tutor applying the Feynman Technique.
The student has just studied a lesson and explained what they understood in their own words.
Analyze their explanation against the lesson reference.
Return JSON:
{
  "mastery_score": 0.0 to 1.0,
  "mastery_level": "Developing|Proficient|Mastered",
  "strengths": ["Clear explanation of X", "..."],
  "flags": [
    {"concept": "...", "severity": "omission|misconception", "note": "constructive clarification"}
  ],
  "verdict": "warm, encouraging 2-sentence summary",
  "spoken_feedback": "conversational summary for Akira's voice output"
}"""

def evaluate_feynman(slug: str, lid: str, explanation: str) -> dict:
    meta = workspace.load_meta(slug)
    lesson = _lesson_by_id(meta, lid)
    lesson_text = workspace.read_text(slug, f"{lid}.md") or ""
    
    prompt = (
        f"Topic: {meta['topic']}\nLesson: {lesson['title']}\n"
        f"Key Concepts: {', '.join(lesson['key_concepts'])}\n\n"
        f"Student's Explanation:\n\"{explanation}\"\n\n"
        f"Lesson Reference:\n{lesson_text[:2000]}"
    )
    # Evaluated via Free Tier LLM (Groq / Gemini)
    res = llm.free(FEYNMAN_SYSTEM, prompt, max_tokens=1000)
    workspace.write_json(slug, f"{lid}_feynman.json", {
        "lesson_id": lid, "transcript": explanation, "evaluation": res
    })
    return res
```

---

## 10. The Strategic Roadmap: What We Are Building Next

### 10.1 Phase 5: Repo-Explain Mode (Local Codebase Tutor)
- **Concept:** Ingest local Git repositories or code folders and turn them into an interactive course.
- **Mechanism:**
  1. AST parsing (`ast` module for Python, tree-sitter for JS/TS/Go).
  2. Directory tree extraction and dependency graph building.
  3. Automatic generation of architecture diagrams (Mermaid `graph TD`), data-flow traces, and interactive code quizzes.
  4. Onboards junior developers or co-founders onto complex codebases in 30 minutes.

### 10.2 Business Mode (Executive Operations Suite)
- **Autonomous Financial & Excel Modeling:**
  - Automated formula audits, variance calculation, and pivot table synthesis on `.xlsx` files via Win32 COM.
- **Cross-Document Report Synthesis:**
  - Ingests multiple contracts, research papers, and spreadsheets to generate formatted Word executive summaries and PowerPoint briefing decks.
- **60-Second Morning Audio Executive Briefing:**
  - Scans Google Calendar, unread VIP emails, and file modifications on system startup.
  - Generates and speaks a 60-second synthesized priority brief while updating a desktop HUD.

### 10.3 Hardware-Gated Local LLMs (100% Offline Air-Gapped)
- Leveraging [hardware_gate.py](file:///d:/Coding/Projects/Sensei/hardware_gate.py) to probe system VRAM (e.g. RTX 2050/3060/4090) and RAM.
- Automatically launch local quantized models (Qwen 2.5 7B, Phi-3 Mini) via `llama-server` for complete air-gapped privacy.

### 10.4 Single-Click Windows Distribution
- Windows MSIX / InnoSetup installer bundling the virtual environment, pre-compiled ONNX models, and desktop system tray daemon.

---

## 11. Current Repository Verification Status

| Component | Status | Verification Detail |
| :--- | :--- | :--- |
| **Teaching Server** | Operational | Running on `http://127.0.0.1:8765`, 100 MB upload limit active. |
| **Unit Test Suite** | 100% Passing | All 28 test suites in `tests/` pass cleanly. |
| **Git Synchronization** | Up to Date | Commits pushed to `origin/main` on `liveprosperdie/Sensei`. |
| **Model Gating** | Zero Claude | Running strictly on Groq and Gemini free tier (`AKIRA_DISABLE_CLAUDE=true`). |

---
*Created for the Akira (Sensei) repository.*
