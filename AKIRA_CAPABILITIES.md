# Akira: System Capabilities & Tier Directory

**Akira** is an advanced desktop AI companion and voice-driven operating system orchestrator built into the **Akira** platform. Akira interacts naturally through voice and an animated desktop avatar HUD, executing commands and multi-step workflows across Windows, desktop applications, web platforms, note vaults, and development environments.

This document details what Akira can do across the **3 main tiers (Free, Standard, Pro)**, along with the **Beta Tier** as a dedicated preview testing tier running on free API quota.

---

## Quick Tier Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       👑 PRO TIER (FLAGSHIP AUTONOMOUS SUITE)                │
│  • True Non-Blocking Async Multi-Tasking • Full Codebase Architectural Ingestion│
│  • Complete Obsidian Knowledge Vault     • Multimodal Word AI + Auto-Image Pass│
│  • Generative AI Docs, Sheets & Slides  • Self-Governing Reliability Protocol │
│  • AI Email Composition & Deep Ingestion• High-Throughput Dedicated Compute    │
├─────────────────────────────────────────────────────────────────────────────┤
│                     ⚡ STANDARD TIER (INTERACTIVE POWERHOUSE)                │
│  • Microsoft Office COM Suite (Full Word, Excel, PowerPoint & Teams Control) │
│  • Complete Google Workspace Suite (Gmail, Calendar, Docs, Sheets, Slides)   │
│  • GitHub & VS Code Workspace Automation • Interactive Spoken Confirmation   │
│  • Manual Email Drafting in Browser      • Gated Destructive System Ops [C]  │
├─────────────────────────────────────────────────────────────────────────────┤
│                    🌱 FREE TIER (EVERYDAY VOICE ASSISTANT)                  │
│  • Zero-Cost Daily Desktop Companion   • Offline Wake Word & Barge-In VAD   │
│  • Animated Desktop Avatar HUD         • Native Windows & App Window Control│
│  • Performance Telemetry Dashboard     • Safe Web Browsing & DOM Automation │
│  • Media Hub (Spotify, Netflix, YouTube)• Visual Image Picker & Wallpaper Set│
├─────────────────────────────────────────────────────────────────────────────┤
│                    🧪 BETA TIER (EARLY TESTER PREVIEW TIER)                 │
│  • Full Free Tier Feature Foundation   • Desktop & Office Read/Inspect UI   │
│  • Zero-Cost Free API Quota Operation  • Early Access Feature Feedback Loop  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Free Tier (The Zero-Cost Everyday Voice Assistant)

*The snappy, privacy-conscious daily desktop companion for system inspection, media playback, safe web browsing, and personal productivity with zero API cost.*

### What Akira Can Do on Free Tier

#### Voice & Desktop Avatar HUD
* **Offline Wake Word**: Detects `"Akira"` in real-time with zero cloud dependency and minimal CPU overhead.
* **Full Barge-In Support**: Interrupt Akira mid-sentence to issue a new command.
* **Natural Voice Output**: Speaks responses and reads long content aloud in comfortable chunks.
* **Animated Desktop Avatar HUD**: Translucent floating companion reflecting listening, speaking, thinking, and sleep states.

#### Windows Controls & System Telemetry
* **App & Window Control**: Launch applications by name (`open_application`), maximize, minimize, or switch active windows (`maximize_window`, `minimize_window`, `switch_window`).
* **Volume & Brightness**: Adjust audio volume (`adjust_volume`: absolute, relative, mute, unmute) and screen brightness (`adjust_brightness`).
* **Instant Screenshots**: Full-screen capture saved directly to `Pictures/Screenshots` (`screenshot`).
* **Telemetry Dashboard (`performance_stats`)**: Live CPU, RAM, and Disk metrics with an interactive visual HTML dashboard.
* **Settings & System Tools**: Jump directly to Wi-Fi, Bluetooth, Display, Sound, Storage, and Windows Update pages (`open_settings`); launch Task Manager, Control Panel, and Device Manager (`open_system_tool`).
* **Hardware Radios**: Verified on/off toggling for Wi-Fi (`toggle_wifi`) and Bluetooth (`toggle_bluetooth`).
* **Screen Lock**: Instantly lock the desktop screen (`lock_pc` / `lock_screen`).
* **Temp Cleanup Preview**: Read-only scan of temporary files and disk space (`preview_temp_cleanup`).

#### Web Browsing & DOM Automation
* **Smart Navigation**: Google search with automatic cookie-banner dismissal (`web_search`), direct URL navigation (`open_url`), and browser history control (`browser_control`: back, forward, reload).
* **Tab Management**: Open new tabs (`new_tab`), open specific sites in dedicated tabs (`open_site_tab`), switch tabs (`switch_tab`), list open tabs (`list_tabs`), and close tabs (`close_tab`).
* **Bookmark Page**: Bookmark active browser pages (`bookmark_page`).
* **Universal Site Search**: Search on YouTube, Reddit, Wikipedia, GitHub, etc., by driving the site's own search bar (`site_search`).
* **Intelligent DOM Interaction**: Semantic element detection to click buttons/links (`click`), fill input forms (`fill`), and scroll pages (`scroll`).

#### Entertainment, Media & Shopping
* **Spotify (`spotify_control`)**: Play songs/artists/playlists, pause, resume, next/previous track, seek, volume, lyrics view, and mood presets (*calm, focus, upbeat, gym*).
* **YouTube (`youtube_control`)**: Playback, speed (0.5x–2.0x), fullscreen, captions, sleep timer, likes, and comments.
* **Netflix (`netflix_control`)**: Search and play titles, seek to exact timestamps, skip intro, episode switching, subtitles, audio tracks, and profile switching.
* **Amazon & Flipkart (`amazon_control`, `flipkart_control`)**: Search products, read top result cards with pricing, select items, and pick size/color variants.
* **Google Meet (`meet_control`)**: Join calls via link or code, toggle mic and camera, raise/lower hand, open chat, and leave meetings.

#### Files, Wallpaper & Memory
* **File Exploration**: Open folders by alias (`open_folder`: Downloads, Desktop, Documents, etc.) and list folder contents aloud (`list_folder`).
* **Chunked File Reading**: Read text, code, PDF, and Word documents in chunks with pause/continue prompts (`read_file`, `read_more`, `stop_reading`).
* **Safe File Operations**: Search files (`search_file`), summarize files in 4–5 sentences (`summarize_file`), copy files (`copy_files`), compress to `.zip` (`compress_files`), and extract archives (`extract_files`).
* **Visual Image Picker & Wallpaper**: Search safe web images (`search_image`), open a visual thumbnail picker in your browser, download the chosen photo (`download_image`), and set it as your desktop wallpaper (`set_wallpaper`).
* **Clipboard & Memory**: Read clipboard text (`read_clipboard`), write clipboard text (`write_clipboard`), search daily memory logs (`search_memory`), and delete today's daily log (`forget_today`).

#### 🔒 Free Tier Boundaries
* **Gated / Destructive Actions `[C]`**: Disabled (file deletions, overwrites, power commands, system cleanups).
* **Office & Workspace Automation**: Disabled (Microsoft Office COM suite, Google Workspace, GitHub repo actions).
* **Obsidian Knowledge Vault**: Disabled (entire vault integration is Pro-exclusive).
* **Background Task Queue**: Disabled (long multi-minute tasks cannot run in the background).

---

## 2. Standard Tier (The Interactive Powerhouse & Workspace Suite)

*Unlocks full interactive mastery over system power, files, Microsoft Office COM automation, Google Workspace interactive CRUD, and GitHub with spoken safety confirmation. AI-generated content creation is reserved for Pro.*

### What Akira Can Do on Standard Tier (Includes All Free Tier Features Plus:)

#### Gated System Maintenance & Power (Spoken Confirmation Required `[C]`)
* **Power Controls**: Shut down (`shutdown_pc`), restart (`restart_pc`), sleep (`sleep_pc`), hibernate (`hibernate_pc`), or sign out (`sign_out`).
* **System Cleanup**: Clear Windows Temp and Prefetch folders (`clear_temp_files`), empty the Recycle Bin (`empty_recycle_bin`), clear browser caches (`clear_browser_cache`), and run Windows Disk Cleanup (`run_disk_cleanup`).
* **Process Termination**: Force-close single apps or all open applications (`close_application`).

#### Gated File & Disk Operations (Spoken Confirmation Required `[C]`)
* **File Overwriting & Editing**: Overwrite existing files (`write_file`) or execute targeted find-and-replace text edits (`edit_file`).
* **Safe Movement & Deletion**: Move files/folders (`move_files`) or delete them (`delete_files`) with mandatory spoken enumeration before deletion.
* **Folder Organization & Renaming**: Automatically sort messy folders into category subfolders (`organize_folder`, `organize_files`) or bulk-rename files sequentially (`bulk_rename_files`).
* **Memory Reset**: Wipe all historical memory logs and reset the core profile (`wipe_all_memory`).

#### Microsoft Office Suite Automation via Win32 COM (`office_control`)
* **Microsoft Word**: Create (`new`), open (`open`), read document text (`read`), dictate text at cursor (`insert`), apply full formatting (fonts, sizes, colors, highlights, lists), and format all headings by document style.
* **Microsoft Excel**: Create workbooks (`new`), open (`open`), read exact cell values/ranges aloud (`read`), write data (`write`), format cells, inject live formulas (`formula`: `=SUM(...)`, `=AVERAGE(...)`), and generate native charts (`chart`: bar, line, pie, radar).
* **Microsoft PowerPoint**: Create presentations (`new`), open (`open`), navigate slides (`next`, `prev`, `first`, `last`), start/end slideshow, insert new slides with layouts (`new_slide`), set titles and body content, and delete slides (`delete_slide` `[C]`).
* **Microsoft Teams**: Launch and bring Teams to focus (`open`, `focus`).

#### Google Workspace Suite via MCP & Web Automation
* **Gmail (`gmail_control`, `gmail_compose`)**: Search emails by query filter (`search`), read message threads (`read`), check unread counts (`unread`), list mailbox labels (`labels`), and draft emails with user-dictated text into the browser compose window (`gmail_compose|draft`).
* **Google Calendar (`calendar_control`)**: List upcoming events (`list`), find open time slots (`free`), create events with natural date/time parsing (`create`), update event details (`update`), and delete events (`delete` `[C]`).
* **Google Docs (`docs_control`)**: Create documents with user-dictated content (`create`), read document text (`read`), and append text to existing documents (`append`).
* **Google Sheets (`sheets_control`)**: Create spreadsheets with user-provided data (`create`), read cell ranges (`read`), and write/update values (`write`).
* **Google Slides (`slides_control`)**: Create presentations with user-authored slides (`create`), read slide content (`read`), update existing slides (`update`), and delete presentations (`delete` `[C]`).

#### GitHub & Developer Workflow
* **Repository Browsing (`github_control`)**: Search repos with star metrics, open repositories, browse directory trees and code files, view issues, view pull requests, and summarize READMEs.
* **Git Actions**: Star/unstar/fork repositories, and clone repositories locally via Git (`clone repo`).
* **Issue & PR Management**: Create issues, create pull requests (`create pull request` `[C]`), merge PRs (`merge pull request` `[C]`), close issues/PRs (`[C]`), delete branches (`[C]`), and delete repositories (`delete repo` `[C]`).
* **VS Code Automation (`vscode_control`)**: Open project folders, open specific code files, search files, create files, and edit code inside VS Code (`write file` `[C]`, `edit file` `[C]`).

#### eCommerce Checkout Progression
* Add items to cart, view cart, proceed to checkout (`[C]`), and confirm delivery address (`[C]`) on Amazon and Flipkart (halts before payment).

#### 🔒 Standard Tier Boundaries
* **AI-Generated Content**: Disabled — `generate` sub-actions in Google Docs, Sheets, Slides, Gmail, and Word require Pro. Standard users create content with their own text.
* **Obsidian Knowledge Vault**: Disabled — entire vault integration (search, read, create, append, link, organize, focus mode) is Pro-exclusive.
* **Background Multi-Task Queue**: Runs inline/blocking only (multi-minute deep ingestion tasks cannot be offloaded to daemon threads).
* **Autonomous High-Reasoning Passes**: Requires step-by-step user guidance (no autonomous repo architecture synthesis).

---

## 3. 👑 Pro Tier (The Flagship Autonomous AI Suite)

*The apex tier of Akira. Built for power users and engineers who demand true agentic autonomy, non-blocking asynchronous multi-tasking, deep architectural comprehension, multimodal document synthesis, AI-powered content generation, and self-governing reliability.*

### What Akira Can Do on Pro Tier (Includes All Standard Tier Features Plus:)

#### 🚀 1. True Non-Blocking Async Multi-Tasking Daemon
* **Zero Dead Air**: Heavy, compute-intensive operations (codebase analysis, vault structuring, document generation, multi-repo cloning) are dispatched to background daemon threads (`background_tasks.py`).
* **Parallel Conversational Flow**: You can continue issuing commands, browsing, or asking questions seamlessly while Akira executes long-running operations in the background.
* **Thread-Safe Spoken Announcements**: Once background tasks complete, Akira automatically announces the finished artifacts cleanly through the main audio loop without interrupting active speech.
* **Live Task Monitoring (`background_status`)**: Real-time voice query status (*"How's that repo analysis going?"*, *"Is my document ready?"*).

#### 🧠 2. Deep GitHub Codebase Architectural Ingestion (`repo notes`)
* **Full-Repository Ingestion**: Clones and analyzes entire production codebases in the background.
* **Intelligent File Filtering**: Automatically strips locks, vendor trees, and build artifacts (`node_modules`, `dist`, `.git`, lockfiles).
* **Multi-Stage Code Synthesis**:
  1. Identifies entry points and high-level architectural patterns.
  2. Batches source files through high-speed mechanical summarization.
  3. Synthesizes an architectural blueprint and outline (`plan_repo_outline`).
  4. Generates an entire, deeply interconnected technical documentation vault into Obsidian (`write_note_bodies`) with wikilinks and component diagrams.

#### 🗂️ 3. Complete Obsidian Knowledge Vault Integration (`obsidian_control`)
* **Note Management**: Search notes (`search`), read specific note sections/headings (`read`), view active note (`active`), create clobber-proof notes (`create`), and open notes in Obsidian (`open`).
* **Vault Structuring**:
  * `progress`: Logs timestamped progress bullets under `# Progress Log`.
  * `append`: Adds text under any named heading.
  * `link`: Injects `[[wikilinks]]` under `# Related` to dynamically build knowledge graphs.
  * `moc`: Generates Map of Content index notes.
  * `diagram`: Injects native Mermaid flowchart diagrams.
  * `tags`: Lists vault tags with item counts.
* **Focus Mode**: Toggle deep-work Focus Mode on/off (`focus on`, `focus off`) and perform single-target note filing.
* **Autonomous Vault Architect (`organize`)**: Hands raw unstructured notes, meeting transcripts, or clipboard dumps to the deep reasoning pass. Automatically plans multi-note graphs, authors note bodies, injects contextual `[[wikilinks]]`, builds MOC index notes, and injects native Mermaid diagrams without requiring manual prompts.

#### 🎨 4. Generative AI Content Creation Suite
* **AI-Generated Google Docs (`docs_control|generate`)**: Provide a title and a brief — Gemini drafts the entire document body as clean, formatted plain text.
* **AI-Generated Google Sheets (`sheets_control|generate`)**: Describe the dataset you need — Gemini composes structured spreadsheet data with headers and formulas.
* **AI-Generated Google Slides (`slides_control|generate`)**: Give a topic and optional slide count — Gemini produces complete multi-slide presentation decks with titles and body content.
* **AI-Generated Email Drafting (`gmail_compose|generate`)**: Describe the email you want — Gemini writes the body, fills the compose window for your review. Never auto-sends.
* **Multimodal Word AI Drafting (`office_control|word|generate`)**: Generates complete, multi-page professional Word documents with hierarchical styling (Heading 1/2, bullet lists, executive summaries), plus an automated visual research pass that scans every section, queries image search engines, downloads relevant assets, and embeds them directly under their corresponding headers.

#### 📑 5. File-to-Document Generative Ingestion (`file_to_doc`)
* **Massive File Ingestion**: Ingests massive local files (PDFs, research papers, local code repositories, transcripts).
* **Structured Workspace Synthesis**: Extracts core themes and automatically structures and formats clean, production-ready Google Docs.

#### 🛡️ 6. Self-Governing Reliability-Streak Autonomous Trust Protocol (`reliability.py`)
* **Supervised Confirmation Streaks**: Tracks consecutive successful human confirmations per action type to build a trust ledger (`action_reliability.json`).
* **Autonomous Execution**: Unlocks safe, unattended execution for routine tasks once a 3-time supervised confirmation streak is cleared.
* **Automatic Demotion**: Any failure immediately resets the streak to 0, demoting the action back to probation to protect the user.

#### ⚡ 7. High-Throughput Dedicated Compute & Hosted Acceleration
* **High Daily Token Allowances**: Priority Anthropic Claude Sonnet/Opus head model with high daily budget allowances (default $25.00/day).
* **Hosted Servant Fallback**: High-speed hosted servant acceleration (Qwen2.5-72B-Instruct on Together/Fireworks) for rapid code reductions and sub-task drafting.

---

## 4. 🧪 Beta Tier (Early Tester Preview Tier)

*A lightweight trial and evaluation tier designed for early testers running on free API quota. It provides the full everyday Free tier foundation along with safe, read-only inspection previews of Office and Developer tools — keeping tester environments completely quota-safe and non-destructive. Google Workspace and Gmail are excluded from Beta.*

### What Akira Can Do on Beta Tier

#### 1. Full Free Tier Capabilities (Standard Baseline)
* All core voice features (wake word, barge-in VAD, animated desktop avatar HUD).
* Native Windows & app window management, volume, brightness, screenshots, and telemetry dashboard.
* Complete web browsing, tab management, DOM interaction (clicking, typing, scrolling), and site search.
* Full media control for Spotify, Netflix, YouTube, Google Meet, and shopping search.
* File exploration, chunked reading, safe file operations, wallpapers, and clipboard/memory controls.

#### 2. Safe Read & Inspect Previews (Quota-Safe Exploration)
* **Office Inspection Previews**: Launch Word/Excel/PowerPoint, open documents, read text/ranges aloud, and navigate slide decks (`open`, `read`, `nav`).
* **Developer Workspace Previews**: Browse GitHub repositories, read READMEs, view issues & PRs (`github_control`), and open projects & view files in VS Code (`vscode_control|open folder`, `open file`, `read file`).

#### 🔒 Beta Tier Boundaries
* **Google Workspace & Gmail**: Excluded from Beta (Gmail, Docs, Sheets, Slides, Calendar are Standard/Pro only).
* **Destructive Operations & Overwrites**: Disabled — `write_file`, `edit_file`, deletions, power operations, and repo management are kept in Standard/Pro.
* **Write & Clobber Actions**: File modifications, code editing, and PR merging are reserved for paid tiers to preserve free API quota.
* **Autonomous High-Compute Pro Features**: Gated to Pro (no background async queue daemon, no autonomous multi-note Obsidian architect, no hosted 72B servant fallback).
* **Full Pro Generative AI Suite**: `generate` sub-actions in Docs/Sheets/Slides/Gmail/Word remain reserved for Pro.

---

## Tier Feature Comparison Matrix

| Capability / Feature Area | Free Tier | Standard Tier | 👑 Pro Tier | 🧪 Beta Tier (Tester Preview) |
| :--- | :---: | :---: | :---: | :---: |
| **Tier Positioning** | Zero-Cost Everyday Assistant | Interactive Workspace Powerhouse | **Flagship Autonomous AI Suite** | Early Tester Preview Tier |
| **Voice Loop & Barge-In VAD** | ✅ Full Support | ✅ Full Support | ✅ **Priority Performance** | ✅ Full Support |
| **Desktop Avatar HUD** | ✅ Full Support | ✅ Full Support | ✅ Full Support | ✅ Full Support |
| **Safe OS Controls & Telemetry** | ✅ Full Support | ✅ Full Support | ✅ Full Support | ✅ Full Support |
| **Web Browsing & DOM Click/Fill** | ✅ Full Support | ✅ Full Support | ✅ Full Support | ✅ Full Support |
| **Media (Spotify, Netflix, YouTube)** | ✅ Full Support | ✅ Full Support | ✅ Full Support | ✅ Full Support |
| **Safe File Read / Search / Zip** | ✅ Full Support | ✅ Full Support | ✅ Full Support | ✅ Full Support |
| **Microsoft Office COM Suite** | ❌ Blocked | ✅ Full CRUD | ✅ **Full CRUD + AI Generate** | 🔍 **Read & Inspect Preview** |
| **Google Workspace (Docs, Sheets, Slides, Cal)** | ❌ Blocked | ✅ Interactive CRUD | ✅ **+ AI-Generated Content** | ❌ **Excluded from Beta** |
| **Gmail (Search, Read & Compose)** | ❌ Blocked | ✅ Search, Read & Manual Draft | ✅ **+ AI Email Composition** | ❌ **Excluded from Beta** |
| **GitHub & VS Code (Browse & Inspect)** | ❌ Blocked | ✅ Full Control | ✅ **+ Deep Codebase Ingestion** | 🔍 **Browse & Read Preview** |
| **Destructive Actions `[C]` (Deletions, Power)** | ❌ Blocked | ✅ Spoken Confirmation | ✅ **Reliability Streaks** | ❌ Blocked (Safe Only) |
| **File Overwriting & Editing `[C]`** | ❌ Blocked | ✅ Spoken Confirmation | ✅ **Reliability Streaks** | ❌ Blocked (Safe Only) |
| **Obsidian Knowledge Vault** | ❌ Blocked | ❌ Blocked | ✅ **Full Vault + Autonomous Architect** | ❌ Blocked (Pro Only) |
| **Async Multi-Task Background Queue** | ❌ Blocked | ❌ Inline Only | ✅ **Unconstrained Multi-Tasking** | ❌ Blocked |
| **Repo Notes & File-to-Doc** | ❌ Blocked | ❌ Blocked | ✅ **Full Autonomous Ingestion** | ❌ Blocked |
| **Hosted Servant Acceleration** | ❌ Blocked | ❌ Blocked | ✅ **Together/Fireworks 72B** | ❌ Blocked |

---

## Action Catalog by Tier

> **Note**: Actions marked with **`[C]`** are **Gated** (require explicit user confirmation before executing on Standard tier, and are governed by reliability streaks on Pro tier).

### System & OS Control
* `open_application` — Free, Standard, Pro, Beta
* `close_application` **`[C]`** — Standard, Pro
* `maximize_window` / `minimize_window` / `switch_window` — Free, Standard, Pro, Beta
* `adjust_volume` (absolute, relative, mute, unmute) — Free, Standard, Pro, Beta
* `adjust_brightness` — Free, Standard, Pro, Beta
* `screenshot` — Free, Standard, Pro, Beta
* `lock_pc` — Free, Standard, Pro, Beta
* `performance_stats` (live CPU, RAM, Disk telemetry dashboard) — Free, Standard, Pro, Beta
* `open_settings` (Wi-Fi, Bluetooth, Display, Sound, etc.) — Free, Standard, Pro, Beta
* `open_system_tool` (Task Manager, Control Panel, Device Manager) — Free, Standard, Pro, Beta
* `toggle_wifi` / `toggle_bluetooth` — Free, Standard, Pro, Beta
* `preview_temp_cleanup` — Free, Standard, Pro, Beta
* `clear_temp_files` **`[C]`** — Standard, Pro
* `empty_recycle_bin` **`[C]`** — Standard, Pro
* `clear_browser_cache` **`[C]`** — Standard, Pro
* `run_disk_cleanup` **`[C]`** — Standard, Pro
* `shutdown_pc` **`[C]`** / `restart_pc` **`[C]`** / `sleep_pc` **`[C]`** / `hibernate_pc` **`[C]`** / `sign_out` **`[C]`** — Standard, Pro

### Files & Folders
* `open_folder` / `list_folder` / `search_file` / `open_file` — Free, Standard, Pro, Beta
* `read_file` / `read_more` / `stop_reading` / `summarize_file` — Free, Standard, Pro, Beta
* `create_file` (clobber-proof) — Free, Standard, Pro, Beta
* `copy_files` / `compress_files` / `extract_files` — Free, Standard, Pro, Beta
* `write_file` **`[C]`** (overwrite) / `edit_file` **`[C]`** (find/replace) — Standard, Pro
* `move_files` **`[C]`** / `delete_files` **`[C]`** — Standard, Pro
* `organize_folder` **`[C]`** / `bulk_rename_files` **`[C]`** — Standard, Pro
* `file_to_doc` (deep file ingestion to Google Docs) — 👑 Pro Exclusive

### Web Browsing & DOM
* `web_search` / `open_url` / `site_search` / `browser_control` — Free, Standard, Pro, Beta
* `new_tab` / `open_site_tab` / `switch_tab` / `close_tab` / `list_tabs` / `bookmark_page` — Free, Standard, Pro, Beta
* `click` (semantic DOM matching) / `fill` / `scroll` — Free, Standard, Pro, Beta

### Media, Entertainment & Shopping
* `spotify_control` (playback, volume, lyrics, mood presets) — Free, Standard, Pro, Beta
* `youtube_control` (playback, speed, fullscreen, sleep timer, likes) — Free, Standard, Pro, Beta
* `netflix_control` (search, play, seek, skip intro, subtitles, profiles) — Free, Standard, Pro, Beta
* `meet_control` (join, mute, camera, raise hand, leave) — Free, Standard, Pro, Beta
* `amazon_control` / `flipkart_control` (search, variants, cart) — Free, Standard, Pro, Beta
* `amazon_control` / `flipkart_control` (checkout **`[C]`**, address confirmation **`[C]`**) — Standard, Pro

### Desktop Customization, Clipboard & Memory
* `search_image` / `download_image` / `set_wallpaper` — Free, Standard, Pro, Beta
* `read_clipboard` / `write_clipboard` — Free, Standard, Pro, Beta
* `search_memory` / `forget_today` — Free, Standard, Pro, Beta
* `wipe_all_memory` **`[C]`** — Standard, Pro
* `background_status` (poll active background jobs) — 👑 Pro Exclusive

### Microsoft Office Suite (`office_control`)
* **Word** (`open`, `read`) — Standard, Pro, Beta (Preview)
* **Word** (`new`, `insert`, `format`, `save_as` **`[C]`**, `close` **`[C]`**) — Standard, Pro
* **Word** (`generate` — AI drafting + auto-images) — 👑 Pro Exclusive
* **Excel** (`open`, `read`) — Standard, Pro, Beta (Preview)
* **Excel** (`new`, `write`, `format`, `formula`, `chart`, `save_as` **`[C]`**, `close` **`[C]`**) — Standard, Pro
* **PowerPoint** (`open`, `read`, `nav`) — Standard, Pro, Beta (Preview)
* **PowerPoint** (`new`, `new_slide`, `delete_slide` **`[C]`**, `close` **`[C]`**) — Standard, Pro
* **Teams** (`open`, `focus`) — Standard, Pro, Beta (Preview)

### Obsidian Vault (`obsidian_control`) — 👑 Pro Exclusive
* `search` / `read` / `active` / `open` / `tags` — 👑 Pro Exclusive
* `create` / `append` / `progress` / `link` / `moc` / `diagram` — 👑 Pro Exclusive
* `focus` (`on`, `off`) — 👑 Pro Exclusive
* `organize` (deep reasoning multi-note graph structuring) — 👑 Pro Exclusive

### Google Workspace
* **Gmail** (`search`, `read`, `unread`, `labels`) — Standard, Pro
* **Gmail** (`gmail_compose|draft` — user-dictated email text) — Standard, Pro
* **Gmail** (`gmail_compose|generate` — AI email composition) — 👑 Pro Exclusive
* **Calendar** (`list`, `free`, `create`, `update`) — Standard, Pro
* **Calendar** (`delete` **`[C]`**) — Standard, Pro
* **Docs** (`create`, `read`, `append`) — Standard, Pro
* **Docs** (`generate` — AI-authored content) — 👑 Pro Exclusive
* **Sheets** (`create`, `read`, `write`) — Standard, Pro
* **Sheets** (`generate` — AI-composed datasets) — 👑 Pro Exclusive
* **Slides** (`create`, `read`, `update`) — Standard, Pro
* **Slides** (`generate` — AI multi-slide decks) — 👑 Pro Exclusive
* **Slides** (`delete` **`[C]`**) — Standard, Pro

### GitHub & VS Code
* **GitHub** (`search`, `open`, `file`, `issues`, `prs`, `readme`) — Standard, Pro, Beta (Preview)
* **GitHub** (`star`, `fork`, `clone`, `create PR` **`[C]`**, `merge PR` **`[C]`**, `close issue` **`[C]`**, `delete branch` **`[C]`**, `delete repo` **`[C]`**) — Standard, Pro
* **GitHub** (`repo notes` — background codebase architecture ingestion) — 👑 Pro Exclusive
* **VS Code** (`open folder`, `open file`, `read file`, `search file`) — Standard, Pro, Beta (Preview)
* **VS Code** (`create file`, `write file` **`[C]`**, `edit file` **`[C]`**) — Standard, Pro
