# AKIRA: Product & Integration Briefing
**The Autonomous Desktop AI Operator — Native Integrations, Real-Time Voice & Safety Architecture**  
*Document Version: 2.1 | Date: September 2026 | Confidential — For Investors & Partners*

---

## Executive Overview: The Native OS Operating Intelligence

Akira is an **autonomous desktop AI operator** engineered to execute real knowledge work directly on the user's computer. 

Instead of confining users to a browser chat window, Akira lives inside the operating system—controlling Microsoft Office via native Win32 COM, maintaining personal knowledge graphs via Obsidian, driving isolated web sessions via Selenium, and listening with zero-latency local voice recognition. It bridges high-level intelligence with deterministic desktop execution.

```
                                  AKIRA OPERATING CORE
                                            │
        ┌───────────────────────────────────┼───────────────────────────────────┐
        ▼                                   ▼                                   ▼
 🎙️ LOW-LATENCY VOICE               🖥️ NATIVE OS & OFFICE                🛡️ FAIL-CLOSED GUARD
 • Offline ONNX Wake Word           • Win32 COM Excel, Word, PPT         • Static Syntax Check (<1ms)
 • Silero VAD Barge-In (<50ms)      • Obsidian REST Knowledge Graph      • Parameter Arity Validation
 • Pitch & Speed Calibrated TTS     • Selenium Browser Automation        • Trust Streaks (reliability.py)
```

---

## Section 1: What Akira Does Right Now (V1 Production Core)

Akira V1 is a live, working production codebase comprising 67 tested modules:

### 1. Native Win32 COM Office Automation
- **Microsoft Excel:** Programmatic cell-by-cell manipulation, dynamic formula injection (`=SUM`, `=VLOOKUP`, `=IRR`), automated cell formatting and palette styling, and live embedded chart generation.
- **Microsoft Word:** Automated document creation, structured heading styling, table inserts, and executive memo formatting.
- **Microsoft PowerPoint:** Complete slide deck generation, layout orchestration, bullet formatting, and speaker notes.

### 2. Obsidian "Second Brain" Graph Integration
- **Local REST API Architecture:** Communicates directly with local Obsidian vaults over encrypted localhost endpoints with zero external data exposure.
- **Knowledge Graph Synthesis:** Generates interconnected markdown notes, bi-directional backlinks (`[[Topic]]`), and hierarchical tags.
- **Contextual Recall:** Retrieves historical meeting notes, research snippets, and project specs into the live agent context.

### 3. Sub-100ms Voice & Real-Time Interruption Engine
- **Zero-Cloud Wake:** On-device ONNX engine (`akira.onnx`) triggers instantly without internet reliance.
- **Silero VAD Barge-In:** Interruption detector halts agent speech in under 50ms upon user voice input.
- **Hierarchical Tri-Tier Routing:**
  - *Pattern Pre-Router (`gemini_head.py`):* Executes desktop and hardware commands in **<0.1ms** at **$0 cost**.
  - *Groq / Gemini 2.0 Flash:* Rapid intent classification and tool dispatch in **~200ms**.
  - *Claude 3.5 Sonnet / Qwen-72B:* Deep multi-step analytical reasoning on-demand.

### 4. Fail-Closed Dual-Layer Safety Guard
- **Deterministic Static Floor (`guard_rules.py`):** Pre-validates action names, parameter arity, and destructive commands in **<1ms** before any LLM is called.
- **Fail-Closed Guarantee:** If connectivity or verification fails, execution automatically blocks and prompts the user.
- **Earned Autonomy Ledger (`reliability.py`):** Tracks verified human-supervised executions before auto-approving routine actions.

### 5. Native OS Hardware & Web Automation
- **Web Automation (`executor.py`):** Pre-warmed Selenium Chrome instances with isolated profile directories for form fills, research, and authenticated workflows.
- **Visual & Media Engine (`image_flow.py`):** Interleaved image search, thumbnail picker, and download engine that filters web clutter.
- **System Control:** Win32 control over volume, display brightness, process termination, hardware specs, and file directories.

---

## Section 2: Akira V2 — Dedicated High-Value Operational Modes

Akira V2 transforms the desktop operator into two purpose-built vertical engines:

```
                                  AKIRA V2 ENGINE
                                         │
              ┌──────────────────────────┴──────────────────────────┐
              ▼                                                     ▼
     📚 AKIRA SCHOLAR                                     💼 AKIRA OPERATOR
     • 5-Level Adaptive Feynman Engine                     • "Devil's Advocate" Idea Reviewer
     • Dynamic Diagram & Mermaid Visualizer                • Win32 Excel Financial Modeling
     • Active Quizzing & Obsidian Flashcards               • Guarded Email Triage & Dispatch
     • Topic Weakness Ledger                               • SaaS MVP Scaffolder
```

### Mode A: Akira Scholar ("The 10x Adaptive Super-Tutor")
*Target: University students, STEM researchers, and competitive exam test-takers.*

1. **5-Level Adaptive Feynman Engine:**
   - Cuts 30-minute video lectures into 90-second conceptual mastery.
   - Automatically adapts across 5 cognitive levels:
     - *Level 1 (ELI5):* Intuitive real-world analogies.
     - *Level 2 (Undergrad):* Core equations, mechanics, and definitions.
     - *Level 3 (Exam/AP/GRE):* Deep heuristics, edge cases, and problem-solving drills.
     - *Level 4 (Expert):* First-principles proofs, research papers, and architectural trade-offs.
     - *Level 5 (Socratic):* Guided interactive questioning.
2. **Dynamic Diagram & Visual Pipeline:**
   - Real-time generation of Mermaid flowcharts, architecture diagrams, and scientific cycles.
   - Leverages `image_flow.py` to pull verified schematics and anatomical illustrations directly into view.
   - LaTeX mathematical and chemical equation rendering.
3. **Active Recall & Obsidian Spaced Repetition:**
   - Interactive oral and terminal quizzes testing comprehension.
   - Automatically compiles flashcards with spaced-repetition tags (`#review/hard`) into local vaults.
   - Maintains a **Weakness Ledger** to revisit forgotten concepts in subsequent sessions.

### Mode B: Akira Operator ("The Executive AI Co-Founder")
*Target: Solopreneurs, agency owners, startups, and SMB executives.*

1. **"Devil's Advocate" Idea Reviewer:**
   - Challenges business concepts like an experienced venture operator: interrogates CAC/LTV, unit economics, market size (TAM), and churn vulnerabilities.
   - Automated generation of Lean Canvas, SWOT matrices, and Porter's Five Forces.
2. **Automated Win32 Excel Financial Modeling:**
   - Constructs complete 3-year cash flow projections, P&L sheets, and break-even tables in Microsoft Excel.
   - Injects dynamic formulas (`=IRR`, `=NPV`, `=SUMPRODUCT`), corporate header palettes, and charts.
   - One-command sensitivity analysis (Bull, Base, Bear scenario tables).
3. **Smart Email Automation & SaaS Scaffolding:**
   - **Triage & Priority Digest:** Reads incoming mail via `gmail_control.py`, prioritizes urgent client threads, and creates digests.
   - **Guard-Gated Send:** Drafts on-brand replies; dispatches only with dual-guard confirmation or earned trust.
   - **SaaS MVP Scaffolder:** Bootstraps full-stack starter templates (landing pages, database schemas, and CRUD API routes) in seconds.

---

## Section 3: Self-Learning Engine, 4-Tier Matrix & Engineering Roadmap

### 1. Autonomous Self-Learning & Memory Engine
- **Continuous Passive User Profiling:** `memory_observer.py` runs in the background, extracting user preferences, communication styles, and operational rules without model retraining.
- **Learning Velocity Ledger:** Remembers which study topics were mastered quickly vs. concepts requiring reinforcement.
- **Business Entity Memory:** Stores active companies, VIP clients, product pricing, and vendor details in local Markdown profiles (`memory/core_profile.md`).
- **Data Sovereignty:** All personal data and knowledge graphs remain 100% on the user's local disk.

### 2. Complete 4-Tier Feature Matrix

| Capability / Feature | Free Tier ($0 Baseline) | Standard Tier | Pro Tier | Beta Tier |
| :--- | :--- | :--- | :--- | :--- |
| **Voice Wake & Barge-In (ONNX + VAD)** | **Full** | **Full** | **Full** | **Experimental Avatars** |
| **System Control (Volume, Brightness, Apps)** | **Full** | **Full** | **Full** | **Full** |
| **Obsidian Second Brain Integration** | **Read & Create** | **Full Graph & Tags** | **Full + Deep Context** | **Full** |
| **Web Search & Image Engine** | **Basic Search** | **Image Flow + Downloader** | **Full Browser Automation** | **Full** |
| **Scholar Mode (Feynman & Quizzes)** | **Basic Explanations** | **5-Level Feynman + Quizzes** | **Full Diagrams & Flashcards**| **Preview Features** |
| **Win32 Office (Excel, Word, PPT)** | *Disabled* | **Word Drafting** | **Full Formulas, Charts, PPT**| **Full** |
| **Operator Mode (Business & Models)** | *Disabled* | **Idea Review** | **Full P&L, SaaS MVP, SWOT** | **Preview Features** |
| **Email Automation (Gmail Triage & Send)** | *Disabled* | **Read & Triage Digest** | **Full Draft & Guarded Send** | **Full** |
| **Advanced Reasoning Models** | **Fast Groq / Flash** | **Flash + Groq (Higher Quota)**| **Claude 3.5 Sonnet / 72B** | **Experimental Local Models** |

### 3. Engineering Delivery Roadmap (ASAP Schedule)

```
Sprint 1 (Days 1–5): MVP Core
├── Global Mode Switcher (Scholar / Operator)
├── 5-Level Adaptive Feynman Engine
├── Mermaid Diagram Generation Pipeline
└── "Devil's Advocate" Idea Reviewer

Sprint 2 (Days 6–10): Deep Desktop Execution
├── Win32 Excel Financial & P&L Models
├── Obsidian Spaced-Repetition Flashcard Generator
├── Email Triage Digest & Guard-Protected Send
└── Image Engine Diagram Visualizer

Sprint 3 (Days 11–15): Intelligence & Packaging
├── Continuous Self-Learning Memory Observer
├── SaaS MVP Scaffolder Boilerplates
├── Tier Quota Enforcement & Key Management
└── Full Production Packaging & Distribution
```

---

## Summary for Investors

Akira combines **deterministic native desktop execution** (Win32 Office, Obsidian, Selenium), **zero-latency real-time voice**, and **fail-closed safety guards** into a single autonomous operator. 

By introducing **Scholar Mode** and **Operator Mode**, Akira captures both viral bottom-up student adoption and high-ARPU business workflow automation with an exceptionally capital-efficient, high-margin software delivery model.
