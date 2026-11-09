# Akira — Local-First Voice & Desktop AI Assistant (Standalone)

> **A 100% free-to-run, local-first Windows voice and desktop automation assistant.**  
> Built with a 3-tier hybrid brain (0ms deterministic reflexes + free Groq API + local Ollama Servant/Guard), strict static & semantic safety verification, and a **100% Non-Destructive "Lead-to-Last-Step" Handoff** guarantee.

---

## 1. Core Philosophy & Architecture

Akira is engineered around three non-negotiable pillars:

1. **100% Free & Local-First (`AKIRA_DISABLE_CLAUDE=true`)**:
   - Runs at **$0 cost** using a tiered routing pipeline:
     - **Tier 0 (Deterministic Reflexes, `<1 ms`)**: Instant regex & structural routing in `tiered_classifier.py` for high-frequency OS, browser, media, and file commands.
     - **Tier 1/2 (Free Cloud + Local Servant)**: Routes through the free Groq API (`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `openai/gpt-oss-120b`) and local Ollama (`llama3:8b`) for mechanical JSON tasks, summarization, and multi-step planning.
     - **Zero Paid API Lock-In**: Paid Anthropic Claude calls are disabled by default (`AKIRA_DISABLE_CLAUDE=true`).
2. **100% Non-Destructive "Lead-to-Last-Step" Handoff**:
   - Akira **never** deletes files, folders, Git branches, GitHub repositories, slides, or calendar events, and **never** empties the Recycle Bin, wipes temp folders, or powers off your PC.
   - Instead, when asked to perform any destructive action, Akira **navigates you to the final step** (for example, opening Windows File Explorer with the exact target file highlighted via `explorer.exe /select,<path>`, or opening the GitHub repository's Danger Zone / branches page) and says:  
     *"I've highlighted/opened `<target>` for you — now you can delete it yourself."*
3. **Defense-in-Depth Guard (`guard_rules.py` + `security_guard.py` + `guard.py`)**:
   - Every dispatchable action (`94` actions) is statically and semantically verified before execution:
     - Strict pipe-delimited parameter arity and shape enforcement across all 94 actions.
     - Hard blocks on null bytes (`\x00`), control characters, path bombs, Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1–9`, `LPT1–9`), and dangerous URI schemes (`javascript:`, `data:`, `file:`, `vbscript:`, `chrome:`, `edge:`).
     - Unconditional self-modification protection (`security_guard.py` blocks any write, move, edit, copy, or delete targeting Akira's own codebase).

---

## 2. Everything Akira Can Do Today (Current Capabilities)

### A. Intelligent File & Folder Navigation (`executor.py`, `file_index/`)
- **Natural Spoken Folder Resolution (`open_folder`, `list_folder`)**:
  - Understands natural phrasing (`"please open my downloads folder"`, `"go to the desktop directory"`, `"show me screenshots"`, `"appdata"`, `"c drive"`, `"d drive"`).
  - Automatically resolves Windows OneDrive folder redirection (`~/OneDrive/Desktop`, `~/OneDrive/Documents`, `~/OneDrive/Pictures`) and reuses existing File Explorer windows via COM (`Shell.Application`) to prevent window spam.
- **Fast Local File Search & Indexing (`search_file`, `manage_index_scope`, `index_stats`)**:
  - Background SQLite FTS + drive-map scanner (`file_index/`) finds files and folders across drives in milliseconds.
- **File Operations (`open_file`, `create_file`, `read_file`, `read_more`, `stop_reading`, `write_file`, `edit_file`, `summarize_file`, `file_to_doc`)**:
  - Opens files with their default OS app, reads long documents in voice-friendly chunks (`chunked_read.py`), creates/edits text & code files, and converts local files into formatted documents.
- **Batch File Management (`copy_files`, `move_files`, `organize_files`, `organize_folder`, `bulk_rename_files`, `compress_files`, `extract_files`)**:
  - Categorizes messy folders into clean subfolders (`Images`, `Documents`, `Videos`, `Audio`, `Archives`), batch-renames files, and zips/unzips archives.
- **Non-Destructive File Deletion Handoff (`delete_files`)**:
  - Resolves exact file/folder targets and opens Windows Explorer with the item selected (`explorer.exe /select,<path>`) so you can press Delete yourself.

### B. Fluent Browser & Web Navigation (`executor.py`, `structural_ui.py`)
- **Zero-Duplicate Tab Navigation (`open_site_tab`, `open_url`, `new_tab`, `list_tabs`, `switch_tab`, `close_tab`, `bookmark_page`)**:
  - Resolves 60+ spoken site names (`youtube`, `github`, `arxiv.org`, `huggingface.co`, `chatgpt`, `scholar.google.com`, etc.) without `.com.com` bugs.
  - Switches to an already-open tab if the site is already loaded instead of opening duplicate tabs.
  - Auto-recovers from ChromeDriver version mismatches via Selenium 4 `SeleniumManager` and gracefully falls back to the system default browser if CDP is offline.
- **Context-Aware Search & DOM Interaction (`web_search`, `site_search`, `click`, `fill`, `scroll`, `browser_control`)**:
  - Searches Google or drives any website's native search input directly via injected DOM heuristics (`_SEARCH_INPUT_JS`).
  - Clicks buttons/links, fills forms (`fill|field|text|submit`), scrolls pages, and controls browser history/zoom/downloads.

### C. Site-Specific Controllers
- **YouTube (`youtube_control`)**: Search videos, play/pause, mute, seek forward/backward, adjust playback speed, toggle fullscreen/theater mode, skip ads, and open channels/subscriptions.
- **Netflix (`netflix_control`)**: Search titles, play/pause, skip intro, next episode, fullscreen, and audio/subtitle controls.
- **Spotify (`spotify_control`)**: Play songs/artists/playlists, pause/resume, next/previous track, shuffle, repeat, and like tracks.
- **Google Meet (`meet_control`)**: Toggle microphone/camera, raise hand, toggle captions, open chat, and leave call.
- **Amazon & Flipkart (`amazon_control`, `flipkart_control`)**: Search products, filter/sort results, open product pages, add to cart, and view cart (checkout/order placement is safety-gated).
- **GitHub (`github_control`)**:
  - Search user or public repositories, open repos, read READMEs, browse files/issues/PRs, star/unstar, fork, clone repos locally, and create issues/PRs via REST API or browser.
  - **Non-Destructive Handoff**: `delete branch` opens `/branches` and `delete repo` opens `/settings#danger-zone` for manual confirmation.

### D. Developer & Second-Brain Workflows (`vscode_control`, `obsidian_control`, `repo_notes.py`)
- **VS Code Automation (`vscode_control`)**: Open projects/files in VS Code, create/edit files, search across workspace, and run safe terminal commands.
- **Obsidian Vault & Knowledge Graph (`obsidian_control`)**:
  - Create, append, read, search, and link Markdown notes in your Obsidian vault.
  - **Automated Repo-to-Obsidian Documentation Pipeline (`repo_notes.py`)**: Clones or inspects a codebase, summarizes source files in batches on the local Servant/Groq tier, plans a connected note outline with Mermaid architecture diagrams, and writes grounded, cross-linked Markdown notes into Obsidian.

### E. Microsoft Office Native COM Control (`office_control.py`)
- **Microsoft Word**: Create documents, write/append paragraphs, insert headings/tables/page breaks, format fonts/alignment, find-and-replace, export to PDF, and AI-draft structured reports.
- **Microsoft Excel**: Create workbooks, write cell ranges/rows, apply formulas (`SUM`, `AVERAGE`, `VLOOKUP`), format headers/columns, sort/filter tables, and create charts.
- **Microsoft PowerPoint**: Create decks, add/edit slides, insert titles/bullets/speaker notes, start/stop slide shows, navigate slides, and **non-destructively jump to a target slide** when asked to delete a slide.

### F. Google Workspace Integration (`calendar_control.py`, `docs_control.py`, `sheets_control.py`, `slides_control.py`, `gmail_control.py`)
- **Google Calendar**: List today's/upcoming agenda, check free/busy windows, create/update events, and open Google Calendar in your browser for manual event deletion.
- **Google Docs, Sheets & Slides**: Create, read, and update cloud documents, spreadsheets, and slide decks; opens presentations in the browser for manual deletion.
- **Gmail (`gmail_control`, `gmail_compose`)**: Read/search inbox threads and compose rich email drafts (**draft-only by design** — Akira never auto-sends emails without your manual click).

### G. Windows System, Window & Media Control (`system_control.py`, `native_ui.py`)
- **Application & Window Management (`open_application`, `close_application`, `switch_window`, `maximize_window`, `minimize_window`)**:
  - Launches desktop apps, switches focus between open windows, snaps/maximizes/minimizes windows, and protects system-critical Windows processes (`explorer.exe`, `lsass.exe`, `csrss.exe`, `dwm.exe`) from termination.
- **System Settings & Hardware Controls (`adjust_volume`, `adjust_brightness`, `toggle_wifi`, `toggle_bluetooth`, `open_settings`, `open_system_tool`, `performance_stats`, `screenshot`, `set_wallpaper`)**:
  - Controls system audio via PyCAW, adjusts screen brightness, opens Windows Settings pages (`ms-settings:`), reports live CPU/RAM/disk/battery stats, takes screenshots, and searches/downloads/sets desktop wallpapers.
- **Clipboard & Drafting (`read_clipboard`, `write_clipboard`, `speak_clipboard`, `generate_to_clipboard`)**:
  - Reads clipboard text aloud, copies generated content directly to the clipboard, and summarizes copied text.
- **Non-Destructive System Handoffs (`clear_temp_files`, `empty_recycle_bin`, `shutdown_pc`, `restart_pc`, `hibernate_pc`, `sign_out`)**:
  - Opens `%TEMP%` or `shell:RecycleBinFolder` in File Explorer, or provides the exact `Win + X` shortcut for power actions instead of killing your active session.

### H. Encrypted Procedural Memory (`procedural_memory/`)
- Learns recurring user workflows in an encrypted local SQLite store (`procedures.db`), scrubbing PII/secrets before storage (`scrubber.py`) and promoting proven routines only after repeated successful executions.

---

## 3. Everything We Wish Akira To Do (Future Roadmap & Vision)

1. **Ultra-Low-Latency Next-Gen Local Brain (`<20 ms` JEV Guard + Multi-LoRA Sub-2B Servant)**:
   - **Joint Embedding / Cross-Encoder Verifier (JEV) Guard**: Replace autoregressive LLM guard passes with an INT8 ONNX Cross-Encoder / Energy-Based Verifier (`<10–15 ms` on CPU) that scores `(user_intent, tool_call, screen_context)` in a single forward pass.
   - **Single-Base Multi-LoRA Servant (`1.5B–2B` Qwen/Llama or `BitNet b1.58 2B4T`)**: Keep a single `<1.2 GB` model resident in RAM with hot-swappable LoRA adapters (`adapter_router`, `adapter_servant`, `adapter_guard`) and pre-compiled **XGrammar / GBNF** state machines for guaranteed 100% valid JSON emission in `<150 ms`.
2. **Universal Visual GUI Grounding (OmniParser / Vision-Action Fallback)**:
   - Detect and interact with custom-rendered UI elements in apps without DOM or UIAutomation trees (Figma, Blender, custom Electron/Canvas apps).
3. **Interactive "Ghost Cursor" Visual Handoff Overlay**:
   - Highlight the exact button on screen with a translucent ring during non-destructive handoffs so the user sees where to click immediately.
4. **Proactive Workflow Autopilot & Morning Briefings**:
   - Proactively suggest learned routines from `procedural_memory` based on time of day and active project context.
5. **Cross-Application DAG Pipelines with Live Progress HUD**:
   - Execute multi-app data pipelines (PDF -> Excel chart -> PowerPoint slide -> Obsidian note) with a live visual step tracker and instant rollback.
6. **100% Local Neural Voice Pipeline (Parakeet / Moonshine STT + Kokoro-82M / Piper TTS)**:
   - Sub-50ms offline speech recognition and natural neural voice synthesis with real-time mid-sentence barge-in.
7. **One-Click Installer & Built-In `akira --doctor` Self-Healer**:
   - Single-binary Windows installer with automatic hardware profiling, model pulling, mic fallback, and isolated browser profile setup.
8. **Sandboxed Community Plugin & MCP SDK**:
   - Plug-and-play tool manifests that automatically inherit Akira's `guard_rules.py` static validation and non-destructive handoff guarantees.

---

## 4. Quick Start

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Add your free GROQ_API_KEY in .env

# 4. Verify guard coverage (94 actions)
python verify_guard_coverage.py

# 5. Launch Akira
python akira.py
# Or keyboard-only text mode:
python text_mode.py
```
