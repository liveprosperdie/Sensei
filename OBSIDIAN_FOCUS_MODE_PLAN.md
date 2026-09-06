# Akira — Obsidian Focus Mode v1 Implementation Plan

**Document Version:** 1.1  
**Status:** PHASE 1 IMPLEMENTED  
**Last Updated:** August 2, 2026  

> **v1.1 revision note:** Three claims in v1.0 were unverified and two of them were
> wrong. All three were re-checked against the live plugin repo, its README, and its
> GitHub release history on 2026-08-02. See
> **[§0 Verified Corrections](#0-verified-corrections-v11)** for what changed and why.
> Where §0 conflicts with anything later in this document, **§0 wins** — the older
> passages are left in place only so the delta stays auditable.

---

## 0. Verified Corrections (v1.1)

### 0.1 Repo name — CORRECTED

v1.0 cited `covenantlabs/obsidian-local-rest-api`. That org does not own this plugin.

**Verified correct source:** [`coddingtonbear/obsidian-local-rest-api`](https://github.com/coddingtonbear/obsidian-local-rest-api)
(author Adam Coddington; community listing "Local REST API with MCP"). Every
reference in this document, in code comments, and in the SETUP guide now uses that name.

### 0.2 Ports — CORRECTED

v1.0 assumed a single plain-HTTP port `27123`. The plugin's actual defaults:

| Transport | URL | Enabled by default? |
|---|---|---|
| **HTTPS** (self-signed cert) | `https://127.0.0.1:27124` | **Yes — this is the default** |
| HTTP | `http://127.0.0.1:27123` | **No** — opt-in via *Settings → Local REST API → Enable HTTP server* |

Two consequences v1.0 missed entirely:

1. **HTTPS-first, with a self-signed certificate.** A stock `requests` call to
   `https://127.0.0.1:27124` raises `SSLError` until the cert is trusted. The cert is
   downloadable from `https://127.0.0.1:27124/obsidian-local-rest-api.crt`. Akira pins
   that cert as its CA when present and only falls back to unverified localhost TLS
   otherwise.
2. **Authentication is mandatory.** Every endpoint except `GET /` is gated behind
   `Authorization: Bearer <api-key>` (key is in the plugin's settings pane). v1.0's
   endpoint appendix showed no auth header at all, so as written none of its calls
   would have returned anything but `401`.

### 0.3 Version stability — CONFIRMED, AND WORSE THAN REPORTED

> **SUPERSEDED as of 2026-08-02 by [§0.6](#06-version-pinning-no-longer-required-supersedes-03).**
> The analysis below was correct when written, but Obsidian 1.13 has since reached the
> public stable channel, so the pin it recommends is no longer needed. Kept for
> auditing.

The reported 5.0.0/5.0.1 breakage is real, and the *same regression has already
recurred in the current latest release*:

| Version | Released | `minAppVersion` | Installable on stable Obsidian? |
|---|---|---|---|
| **5.1.0** (latest) | 2026-08-01 | **1.13.1** | **NO — Catalyst early-access only** |
| **5.0.3** | 2026-07-30 | 1.8.7 | **YES — recommended pin** |
| 5.0.2 | 2026-07-24 | 1.8.7 | Yes |
| 5.0.1 | 2026-07-24 | **1.13.1** | **NO** |
| 5.0.0 | 2026-07-24 | **1.13.1** | **NO** |
| 4.1.7 | 2026-07-11 | 1.4.0 | Yes — but no MCP, older PATCH engine |

5.0.2's own release notes confirm the history: *"The 5.0.0/5.0.1 releases required
Obsidian 1.13.1, which remains a Catalyst-only early-access release — leaving all
community-directory users pinned to plugin 4.1.7."* 5.1.0 then re-raised
`minAppVersion` to 1.13.1 to adopt Obsidian 1.13's declarative settings framework.

**Decision: pin `5.0.3`.** It is the newest release that is installable on
stable-channel Obsidian, and it carries the Markdown Patch 2.0 engine, the built-in
MCP server, and the `anyOf` heading-target fix. **"Install latest" is explicitly
wrong advice for this plugin** and the SETUP guide says so in a warning box.

Akira enforces this at runtime rather than trusting the docs: `obsidian_api.py`
reads the reported plugin version from `GET /` and warns on a version outside the
known-good range instead of failing an opaque call later.

### 0.6 Version pinning no longer required (supersedes §0.3)

Re-verified 2026-08-02, before building tooling to automate the pin. **The pin is
obsolete — so the tooling was not built.**

`obsidianmd/obsidian-releases/desktop-releases.json` now reports:

```
minimumVersion: 1.1.9
latestVersion:  1.13.4      <- public stable
beta: { latestVersion: 1.13.4 }   <- identical, i.e. no early-access gap
```

Obsidian 1.13 was Catalyst-only when §0.3 was written; it is now the public stable
release. The `beta` block being identical to the top-level one is the tell: there is no
longer any version available to Catalyst users that isn't available to everyone.

Consequences:

- `minAppVersion: 1.13.1` is now satisfiable by **any** user who updates Obsidian, so
  5.1.0 installs normally from the Community plugins browser.
- The entire friction chain this task set out to fix — no version picker in the browser,
  manual release-asset downloads, hand-placing files in `.obsidian/plugins/`, disabling
  the auto-installed latest — **only existed because of the pin.** Removing the pin
  removes all of it. There is nothing left to automate.
- Latest is now the *better* choice, not merely an acceptable one: 5.1.0's notes include
  *"Fixes an issue in which a read immediately following a write could observe stale
  content, by routing vault writes through Obsidian's Vault API"* — precisely the
  read-after-PATCH pattern `obsidian_control.py` uses.

**Rejected, with reasons** (evaluated rather than skipped):

| Option | Verdict |
|---|---|
| Python installer script that fetches release assets from the GitHub API | **Rejected.** Solves a problem that no longer exists, and would leave Akira silently downgrading users away from the stale-read fix. Also a standing maintenance liability: it writes into `.obsidian/plugins/` and fights Obsidian's own updater. |
| Document BRAT for pinning an exact tag | **Rejected.** BRAT is the right tool for pinning, but pinning is the thing that's obsolete. Recommending a second plugin to work around a resolved incompatibility is strictly worse than "update Obsidian, install latest". |
| Combination of both | **Rejected** for the same reason — combining two solutions to a non-problem. |

**Implemented instead:** the requirement inverted from "pin the plugin to an old
version" to "keep Obsidian current, take plugin latest", which is both simpler *and* the
path of least resistance through Obsidian's UI. Setup dropped from four steps to three.
`obsidian_api.py`'s version guard changed from an exact-allowlist (`5.0.2`/`5.0.3`) to a
`MIN_VERSION = "5.0.2"` floor — an allowlist would have warned on every future release
and trained users to ignore the warning. No Phase 1 request/PATCH/auth code was touched.

---

### 0.4 Architecture decision — REST, not MCP

This was the real open question, and the answer is **REST**, decisively. The plugin's
built-in MCP server is genuinely good and the maintainer is right that it obsoletes
third-party Obsidian MCP servers — but it does not fit *Akira's* shape, for four
reasons found by reading the existing code rather than by preference:

1. **Transport mismatch.** `mcp_client.MCPServer` speaks JSON-RPC over **stdio to a
   child process** (`subprocess.Popen`, `stdin.write`/`stdout.readline`). The plugin's
   MCP server is **Streamable HTTP** inside an already-running Obsidian. Akira has no
   HTTP MCP transport, so MCP means either writing one, or shelling out to the
   `mcp-remote` Node bridge — a third moving part, plus `npx`, plus the same
   self-signed-cert problem, to reach a server that also exposes plain REST.
2. **Akira is not a tool-loop agent.** `claude_handler.AKIRA_PROMPT` mandates
   *"Your entire output is exactly ONE JSON object"*, and `executor._ACTION_MAP`
   dispatches `action|parameter` strings deterministically. MCP's value is handing a
   tool catalogue to a model that loops over tool calls. Akira has no such loop;
   adding one to support notes would be a rewrite of the core control flow, not an
   integration.
3. **Safety model would regress.** Every gate in this codebase is *code-level at the
   dispatch layer* — `google_mcp.DENYLIST`, `akira.DANGEROUS_ACTIONS`, the
   `RISKY_*_PARAMS` sets — precisely because of the documented lesson that
   prompt-level-only gates fail. The plugin's MCP surface includes `command_execute`
   (arbitrary command-palette execution), `vault_delete`, and `vault_write` (whole-file
   overwrite). Exposing that catalogue to the model would put destructive vault
   operations behind prompt instructions alone. REST lets Akira expose exactly five
   verbs and never wire the dangerous ones.
4. **Zero new dependencies.** REST needs `requests`, already in `requirements.txt`.
   No `requirements.txt` change is needed for Phase 1 at all.

**However — one genuine v1.0 error that the MCP question surfaced:** v1.0 planned to
*hand-roll* note editing (§1.4: "Parse Markdown heading structure to find insertion
point... Write back to vault"). That is a read-modify-write over the whole file, and it
is both fragile and a lost-update race. The plugin exposes a purpose-built
`PATCH /vault/{path}` instruction engine (Markdown Patch 2.0) that appends under a
named heading server-side, creates the heading if missing
(`Create-Target-If-Missing`), owns whitespace canonicalisation, and supports
`If-Match` optimistic concurrency. **Akira uses that instead of parsing Markdown
itself.** So the corrected approach is "REST, but using the plugin's real capabilities
rather than the naive endpoints v1.0 imagined" — which is where most of the MCP
robustness argument actually lived.

Superseded by this section: §1.2's `GET /vault/search?query=` (real endpoint is
`POST /search/simple/?query=`), §1.4's markdown-parsing write path, and
Appendix C in full.

### 0.5 Corrected endpoint reference

Replaces Appendix C. All calls carry `Authorization: Bearer <api-key>`; base is
`https://127.0.0.1:27124`.

```
GET    /                                 Status + version + auth check (no auth required)
POST   /search/simple/?query=<terms>     Fuzzy search -> [{filename, score, matches[]}]
POST   /search/                          JsonLogic structured search over metadata
GET    /vault/{path}                     Read a note
GET    /vault/{path}/heading/{h}         Read just one heading's content
GET    /active/                          Read the note currently open in Obsidian
PUT    /vault/{path}                     Create / overwrite a note
PATCH  /vault/{path}                     Targeted edit (heading/block/frontmatter)
GET    /tags/                            All vault tags with usage counts
POST   /open/{path}                      Open a note in the Obsidian UI
```

`GET /active/` is the important addition — it answers "which note is the user looking
at right now" directly, which v1.0's §1.1 could only guess at by asking the user.

---

## Executive Summary

This plan extends Akira with voice-driven productivity features in Focus Mode, anchored on Obsidian integration. The system will allow users to naturally update notes, track progress, create linked structures, and improve note quality—all mid-session via voice, without breaking focus.

**Key Design Principle:** Obsidian is the permanent knowledge store; Akira brokers context-aware updates into it. The focus session is the interaction context; Obsidian's vault is the durability layer.

---

## Scope Overview

### In Scope for v1
1. **Voice-driven progress tracking & note updates** — contextual, in-session
2. **Autonomous graphs & linked notes** — wikilinks, backlinks, basic MOCs
3. **Note-quality clarifying questions** — smart, non-intrusive prompting
4. **Creative proposals** — four high-value additions (not required, for approval)

### Out of Scope for v1 (Flagged for Future)
- Plugin management (assumes user installs required plugins themselves)
- Advanced Dataview queries or dynamic note generation
- Conflict resolution for simultaneous edits
- Obsidian sync/cloud integration (assumes local vault)

---

## Part 1: Voice-Driven Progress Tracking & Note Updates

### Problem Statement
Currently, users can open Obsidian and manually type updates. **Goal:** Users say "track progress" or "add what we just discussed to the X note" and Akira understands the session context well enough to find the right note and update it correctly.

### Current Architecture Analysis

**Existing Session Context in Akira:**
- `conversation_history` (list[dict]) in `claude_handler.py` — stores recent exchanges, max 20 entries (10 full exchanges)
- `session_start_time` and `SESSION_TIMEOUT` (45 seconds) in `akira.py` — tracks active session duration
- `_build_session_context()` in `akira.py` — injects PC context (open tabs, active window) at session start

**Existing Note Integration:**
- `docs_control.py` provides Google Docs read/create/append via `google_mcp`
- No Obsidian-specific module exists yet
- Obsidian app path is mapped in `executor.MANUAL_MAP["obsidian"]` — can launch the app

### Proposed Mechanism: Context-Aware Note Discovery & Update

#### 1.1 Session Context Enrichment
**New Module:** `obsidian_context.py`

Extend the session context to include:
- **Active note in Obsidian** — before entering focus mode, user specifies or Akira detects the open note
- **Session topic/focus area** — extracted from first user utterance (e.g., "I'm working on project X")
- **Note references in conversation** — track which notes have been mentioned by the user mid-session

```
Session State Snapshot (at session start):
{
  "focus_note": "2025-01 Project Alpha Roadmap",  # User's main working note
  "session_topic": "Planning Q1 deliverables",
  "mentioned_notes": ["Project Alpha", "Q1 Goals"],  # Extracted from conversation
  "conversation_history": [...],
  "session_start_time": <timestamp>
}
```

#### 1.2 Note Resolution Strategy
**When user says:** "track progress" or "update the note with..."

**Akira's decision tree:**
1. **Explicit reference?** Does the user name a note or topic? → Search Obsidian vault for that note
2. **Implicit reference?** Is there exactly one focus_note in session state? → Use it
3. **Ambiguous?** Multiple plausible notes? → Ask clarifying question (see Part 3)

**Implementation Detail:**
- Obsidian **Local REST API plugin** (required user installation) exposes `PUT/PATCH /vault/{path}` and search endpoints
- Query endpoint: `POST https://127.0.0.1:27124/search/simple/?query=<term>`
  (corrected in §0.5 — the `GET /vault/search` form below never existed)
- Returns list of matching notes with file paths
- Akira picks the most-recently-edited or highest-scoring match

#### 1.3 Session Conversation Summarization & Extraction
**Mechanism:** Before writing to a note, summarize the relevant part of `conversation_history` to extract what should be added.

**Claude prompt injection (in `claude_handler.py` context):**
```
Given the current conversation history, extract the key points from the current focus session 
that should be added to the note titled "[NOTE_NAME]". Focus on progress, decisions, and blockers.
Format as a bullet-pointed summary suitable for Obsidian.
```

**Return format:**
```json
{
  "summary": "- Completed API endpoint auth\n- Blocked on database schema approval\n- Next: Review DB design with team",
  "note_name": "2025-01 Project Alpha",
  "insert_position": "## Progress Log",
  "timestamp": true
}
```

#### 1.4 Obsidian Write Mechanism
**New module method:** `obsidian_update_note(note_name: str, content: str, section: str, prepend: bool) -> dict`

**Via Local REST API — CORRECTED in v1.1 (§0.4):** do NOT read-modify-write. The
read-parse-rewrite loop below is fragile and races against the user editing the same
note in Obsidian. Use the plugin's server-side patch engine instead — one request,
no local Markdown parsing:

```
PATCH /vault/{path}
Authorization: Bearer <api-key>
Content-Type: application/json
Create-Target-If-Missing: true

{"targetType":"heading","target":["Progress Log"],
 "operation":"append","content":"- ..."}
```

<details><summary>Superseded v1.0 approach (kept for auditing)</summary>

- Fetch current note content
- Parse Markdown heading structure to find insertion point (e.g., `## Progress Log`)
- Inject content with timestamp (optional)
- Write back to vault

</details>

**Alternative (if REST API unavailable):**
- Fallback to clipboard: write content to clipboard, open Obsidian, navigate to note (via quick switcher), paste

### Implementation Checklist for Part 1

- [ ] **Create `obsidian_context.py`**
  - Session state enrichment at focus-mode entry
  - Note resolution (explicit → implicit → ambiguous)
  - Mention extraction from conversation

- [ ] **Create `obsidian_control.py`**
  - REST API client for Local REST API plugin
  - `search_notes(query: str) -> list[dict]`
  - `read_note(name: str) -> str`
  - `update_note(name: str, section: str, content: str, prepend: bool, timestamp: bool) -> dict`
  - Fallback clipboard mechanism

- [ ] **Extend `claude_handler.py`**
  - Add prompt injection for session summarization
  - New action type: `obsidian_control|update|<note>|<section>`

- [ ] **Wire into `akira.py`**
  - Capture focus note at session start (via clarifying question or detection)
  - Store in session state
  - Pass to Claude context

- [ ] **Update `executor.py`**
  - Map `obsidian_control` action to new control module

### Plugin Dependency (REQUIRED USER SETUP)
> **Corrected in v1.1 — see [§0](#0-verified-corrections-v11).** The original repo name,
> port, and "install latest" guidance below were all wrong.

**Local REST API with MCP** (https://github.com/coddingtonbear/obsidian-local-rest-api)
- **Install latest** (>= 5.0.2), and keep Obsidian >= 1.13.1. The 5.0.3 pin in §0.3 is
  obsolete now that Obsidian 1.13 is public stable — see §0.6.
- Default endpoint: `https://127.0.0.1:27124` (HTTPS, self-signed cert). Plain HTTP on
  `27123` is opt-in, not default.
- Requires `Authorization: Bearer <api-key>` on every endpoint except `GET /`.
- Provides RESTful access to vault read/write operations, including targeted
  heading-level PATCH.
- **User must install:** Obsidian Settings → Community Plugins → "Local REST API"
- **Safety:** Localhost-only by default; no external network exposure

---

## Part 2: Autonomous Graphs & Linked Notes

### Problem Statement
Akira should be able to create structured relationships between notes—wikilinks, backlinks, MOCs (Maps of Content)—either on request or proactively when patterns emerge.

### Obsidian Graph Capabilities Analysis

**What's automatable in Obsidian:**
- ✅ **Wikilinks** (`[[Note Name]]`) — just text insertion, works instantly
- ✅ **Backlinks** — automatic, emerge when wikilinks exist
- ✅ **Basic MOCs** — hand-crafted index notes with wikilinks
- ✅ **Mermaid diagrams** — embed as code blocks in Markdown
- ✅ **Excalidraw files** — create via REST API if Excalidraw plugin installed
- ✅ **Dataview blocks** — static Dataview queries (limited automation; dynamic queries require plugin)
- ⚠️ **Graph view** — read-only in Obsidian; cannot be scripted

### Proposed Features

#### 2.1 Automatic Backlink Injection
When Akira creates or updates a note, automatically add backlinks to related notes if they exist.

**Example:**
```
User: "Create a note on the new database schema"
Akira: "I'll create that and link it to your existing project notes."

Result:
- New note created: "Database Schema v2"
- Content includes: "Related to: [[Project Alpha]], [[Infrastructure]]"
- These backlinks appear in the graph view automatically
```

**Implementation:**
- After creating/updating a note, scan conversation for topic keywords
- Query vault for existing notes matching those keywords
- Add `Related:` section with `[[Note Name]]` wikilinks

#### 2.2 MOC (Map of Content) Generation
On request or proactively, Akira creates an index note that links to a set of related notes.

**Example:**
```
User: "Create a map for everything related to project alpha"
Akira: Creates "Project Alpha — Index" with:
  ## Overview
  Project Alpha deliverables and tracking.
  
  ## Planning
  [[2025-01 Project Alpha Roadmap]]
  [[Q1 Goals]]
  
  ## Technical
  [[Database Schema v2]]
  [[API Documentation]]
  
  ## Progress
  [[2025-01-15 — Daily Standup]]
```

**When to trigger MOC generation (proactively):**
- User asks: "organize my notes on X"
- User's conversation repeatedly references a cluster of related notes (e.g., 5+ distinct note titles mentioned)
- Session ends and Akira detects a coherent topic worth indexing

**Implementation:**
- Prompt Claude: "Given these notes [list], create a MOC structure with sections"
- Generate Markdown with nested sections and wikilinks
- Create new note via REST API

#### 2.3 Mermaid Diagram Embedding (Lightweight)
For technical or workflow topics, embed a Mermaid diagram in the MOC or related notes.

**Example:**
```
User: "Create a diagram of the project timeline"
Akira: Updates the MOC or "Project Alpha — Overview" with:

​```mermaid
gantt
  title Project Alpha Timeline
  section Phase 1
  Planning :2025-01-15, 30d
  Design :2025-02-15, 20d
  section Phase 2
  Development :2025-03-10, 60d
​```
```

**Constraint:** Mermaid diagrams are static code blocks; Obsidian renders them natively (no plugin required). NOT a full-featured graph, but useful for timelines, flowcharts, and sequences.

#### 2.4 Excalidraw Linking (Optional, Plugin-Dependent)
If user has the Excalidraw plugin installed, Akira can suggest creating a visual diagram file linked from a note.

**Status:** PROPOSED, not v1 commitment (requires additional user plugin + API learning)

### Obsidian Capabilities vs. Automation Reality

| Feature | Automatable | Constraint | Recommendation |
|---------|-------------|------------|-----------------|
| Wikilinks | ✅ Yes | Just text; no validation | v1: Always use |
| Backlinks | ✅ Yes (automatic) | Emerge from wikilinks | v1: Create backlinks via wikilinks |
| Graph view | ❌ No | Read-only; can't script | v1: Skip; user views manually |
| MOCs | ✅ Yes | Hand-crafted structure | v1: Generate on request |
| Mermaid | ✅ Yes | Static code blocks | v1: Embed in MOCs & notes |
| Dataview | ⚠️ Partial | Queries are static text; need plugin for dynamic | v1: Skip; too complex |
| Excalidraw | ⚠️ Partial | Requires plugin; API limited | FUTURE: Post-v1 |

### Implementation Checklist for Part 2

- [ ] **Extend `obsidian_control.py`**
  - `create_backlinks(note_name: str, keywords: list[str]) -> dict`
  - `generate_moc(title: str, note_list: list[str], sections: dict) -> dict`
  - `embed_mermaid(note_name: str, diagram_type: str, data: dict) -> dict`

- [ ] **Extend `claude_handler.py`**
  - New prompt: MOC generation from a set of notes
  - New action: `obsidian_control|create_moc|<title>|<note1>|<note2>...`
  - New action: `obsidian_control|add_diagram|<note>|<type>`

- [ ] **Add graph-intent detection in `akira.py`**
  - Listen for keywords: "map", "structure", "organize", "diagram", "timeline"
  - Trigger MOC/diagram generation on request

- [ ] **Document Obsidian setup**
  - List required plugins: Local REST API (REQUIRED), Mermaid (recommended)
  - Create setup guide in README

### Plugin Dependencies (RECOMMENDED USER SETUP)
- **Local REST API** — required for note I/O
- **Mermaid** — recommended for diagram embedding (usually built-in to Obsidian v1.6+)
- **Excalidraw** — optional; future feature

---

## Part 3: Note-Quality Clarifying Questions

### Problem Statement
Without careful prompting, Akira might add low-value content to notes ("added this to your notes ✓"). The system should ask clarifying questions at strategic moments to improve note quality—but NOT interrupt every action (focus mode is about flow, not friction).

### Decision Framework: When to Ask vs. When to Act

**ASK CLARIFYING QUESTIONS WHEN:**
1. Ambiguous note target (multiple plausible notes exist)
2. Note structure is unclear (no obvious insertion point)
3. User's intent is vague ("add something about productivity" — vague, needs clarification)
4. Note is long/complex (insertion point selection could damage structure)
5. NEW NOTE being created (offer to link to existing notes upfront)

**ACT WITHOUT ASKING WHEN:**
1. Explicit target note named by user
2. Unambiguous insertion point (e.g., "add to my progress log")
3. User's intent is clear (named action: "track progress", "update blockers")
4. Session is actively flowing (avoid interruption during rapid exchanges)
5. Routine/habitual patterns (user has done this before; predict intent)

### Question Types & Timing

#### 3.1 Ambiguity Resolution
```
User: "Add this to my notes"
Akira: (multiple notes with "notes" in title, or no focus_note set)

Question: "Which note should I add this to? I found:
  • Daily Progress Log
  • Project Ideas
  • Research Notes"
```

#### 3.2 Structure Enhancement
```
Akira (updating existing note): "Before I add this, want me to:
  1. Create a new dated section (e.g., '### 2025-01-15')
  2. Link this to related notes you mentioned?"
```

**When to ask:** 2+ related notes exist OR note is unpaginated (no date/section structure yet)

#### 3.3 New Note Linking
```
User: "Create a note on the new database schema"
Akira: "Got it. Found these existing notes that might be related:
  • Infrastructure  
  • Project Alpha
  Want me to link to any of these?"
```

#### 3.4 Summary Confirmation
```
Akira (before updating): "I'll add this to your progress log:
  '- Completed API endpoint auth
   - Blocked on DB schema approval'
  Sound right?"
```

**Triggers:** Long summary (>3 bullet points) OR contains potentially sensitive/critical content

### Implementation: Clarifying Question Orchestration

**New module:** `obsidian_clarify.py`

```python
def should_ask_clarification(context: dict) -> tuple[bool, str]:
    """
    Determine if clarification is needed.
    
    Args:
        context: {
          "action": "update_note",
          "user_input": "add this to my notes",
          "candidate_notes": [...],
          "note_structure": {...},
          "session_flow_rate": int  # messages/min — avoid interrupting rapid exchanges
        }
    
    Returns: (should_ask: bool, question_type: str)
    """
    ...
```

**Heuristics:**
- If `len(candidate_notes) > 1` AND no explicit target → Ask ambiguity question
- If `session_flow_rate > 3` (rapid back-and-forth) → Skip non-critical asks
- If `user_input` is vague (keyword count < 3) → Ask intent clarification
- If `note_structure` lacks date/section structure → Offer structure enhancement

### Integration with Claude

**In `claude_handler.py` action format:**

```json
{
  "mode": "command",
  "action": "obsidian_control",
  "parameter": "update|<note>|<section>",
  "clarifying_question": {
    "type": "ambiguity | structure | linking | summary",
    "question": "Which note...",
    "options": [...]
  },
  "response": "Before I update your notes, just confirming..."
}
```

**Akira response handling:**
- Display question via TTS
- Wait for user clarification input
- Inject answer into action parameter
- Execute update

### Implementation Checklist for Part 3

- [ ] **Create `obsidian_clarify.py`**
  - `should_ask_clarification(context: dict) -> tuple[bool, str]`
  - `generate_question(question_type: str, context: dict) -> str`
  - Session flow rate tracking in `akira.py`

- [ ] **Extend `claude_handler.py`**
  - Add `clarifying_question` field to action JSON
  - Condition: only emit question if `should_ask_clarification() == True`

- [ ] **Update `akira.py`**
  - Handle clarifying questions in the action confirmation loop
  - Re-inject user's answer into action parameter
  - Track message frequency for flow-rate heuristic

- [ ] **Test extensively**
  - Verify interruption doesn't happen during rapid exchanges
  - Verify ambiguous situations DO trigger questions
  - Validate user finds questions helpful, not annoying

---

## Part 4: Creative Proposals (4 High-Value Additions for v1)

These are NOT required commitments—offered for user approval/rejection before implementation begins.

### Proposal A: Session-End Auto-Summary & Auto-Archive
**What it does:**
- When user says "end focus" or session times out, Akira auto-generates a summary of the entire focus session
- Saves summary to a "2025-01 Focus Sessions" note or daily log
- Optionally creates next-session backlog from unfinished tasks

**Example:**
```
User: "I'm done for now"
Akira: "Wrapping up. I'll save a summary to your focus log."

Result added to "2025-01 Focus Sessions":
  ### 2025-01-15 — 14:30–15:45 (1h 15m)
  **Focus Area:** Project Alpha — Database Schema
  **Completed:**
  - Drafted schema v2
  - Code review approved by tech lead
  **Blockers:**
  - Awaiting infrastructure team approval
  **Next:**
  - Set up staging environment
  - Run performance tests
  
  Links to: [[Project Alpha]], [[Database Schema v2]]
```

**Value:** Creates a durable record of what happened when; retroactively useful for weekly reviews or sprint retros. **Type:** Proactive, on-demand.

---

### Proposal B: Smart Weekly Review Note Generation
**What it does:**
- Once per week, Akira proactively creates a "Weekly Review" note aggregating:
  - Summary of all focus sessions from the week
  - Completed vs. blocked tasks (from session summaries)
  - Notes updated this week (from vault search)
  - Emerging themes/patterns in your work

**Example:**
```
## Week of 2025-01-13
**Focus Sessions:** 5 (Total: 7h 20m)
**Primary Area:** Project Alpha (60%), Infrastructure (25%), Learning (15%)
**Top Accomplishments:**
  - Completed database schema design [[Database Schema v2]]
  - Deployed staging environment [[Infrastructure]]
**Patterns:**
  - Blocked on approvals 3x; consider async workflows
  - 80% of focus time was design/architecture; consider expanding dev time
```

**Value:** Enables quick reflection and trend detection without manual effort. **Type:** Autonomous (triggered weekly).

---

### Proposal C: Pomodoro Session ↔ Note Linkage
**What it does:**
- Focus mode can optionally activate a Pomodoro timer (25 min work, 5 min break)
- At session end, automatically tag the created/updated notes with the Pomodoro session ID and duration
- Over time, Akira can tell which notes you were working on during which pomodoros and for how long

**Example:**
```
Session state starts:
  "focus_mode": "active",
  "timer_type": "pomodoro",
  "duration": "25 min",
  "session_id": "pom_20250115_143000"

When user updates "Database Schema v2":
  Note gets metadata tag:
    #pomodoro/pom_20250115_143000 #duration/25m

Later, user asks: "How long did I spend on the database?"
Akira: "You spent about 1 hour 15 minutes across 3 pomodoros 
  on database-related notes this week."
```

**Value:** Gamification + time tracking without friction; helps identify time spent vs. perceived effort. **Type:** Optional integration.

---

### Proposal D: Smart Tag Auto-Generation & Taxonomy Learning
**What it does:**
- As Akira updates notes, it learns your tagging patterns (e.g., `#project/alpha`, `#blocked`, `#waiting-for-approval`)
- When creating new notes, it suggests tags based on content similarity to existing notes
- Gradually builds a personal taxonomy that Akira can query (e.g., "Show me all #blocked items")

**Example:**
```
User creates note: "API endpoint authentication design"
Akira learns (from context): This relates to "Database Schema v2" 
  which is tagged #project/alpha #technical

Akira suggests: "Want me to tag this with #project/alpha and #technical?"
User: "Yes, and add #in-progress"

Over time:
  User's vault develops a stable taxonomy
  Akira can do queries: "What's blocked in project alpha?"
  Returns: All notes tagged #project/alpha #blocked
```

**Value:** Emergent organization without manual curation; enables later Dataview queries. **Type:** Gradual/learning-based.

---

### Proposal Summary

| Proposal | Complexity | Value | User Control | Recommendation |
|----------|-----------|-------|--------------|-----------------|
| A: Session-end summary | Low | High | Manual trigger | **YES, recommend** |
| B: Weekly review auto-gen | Medium | Medium | Autonomous weekly | **CONSIDER; user opt-in** |
| C: Pomodoro linkage | Medium | Medium | Optional integration | **CONSIDER; user opt-in** |
| D: Smart tagging | High | High | Learning-based | **FUTURE; post-v1** |

---

## Technical Architecture Summary

### New Modules to Create

1. **`obsidian_context.py`** — Session state enrichment, note discovery
2. **`obsidian_control.py`** — REST API client, read/write operations
3. **`obsidian_clarify.py`** — Clarifying question logic
4. **`obsidian_pomodoro.py`** (optional) — Timer + note linking

### Modified Modules

1. **`claude_handler.py`**
   - Extend `AKIRA_PROMPT` with Obsidian context
   - Add new action types: `obsidian_control|update|...`, `obsidian_control|create_moc|...`
   - Add clarifying question handling

2. **`akira.py`**
   - Extend session state with `focus_note`, `session_topic`, `mentioned_notes`
   - Integrate clarifying question prompts
   - Track session flow rate (for interruption heuristics)
   - Optional: Pomodoro timer integration

3. **`executor.py`**
   - Map `obsidian_control` actions to `obsidian_control.py` dispatcher

4. **`requirements.txt`**
   - Add: `requests` (for REST API calls, likely already present)
   - No other external dependencies for Local REST API integration

### Data Flow

```
User (voice) 
  ↓
akira.py (VAD, transcription, session state)
  ↓
claude_handler.py (LLM decision + action routing)
  ↓
[Clarifying Question?] → obsidian_clarify.py → [Ask User] → [Inject Answer]
  ↓
executor.py (action dispatch)
  ↓
obsidian_control.py (REST API → Local REST API plugin)
  ↓
Obsidian vault (note creation/update)
  ↓
Graph view updates (automatic via Obsidian's backlink engine)
  ↓
User sees result (next note refresh)
```

---

## Plugin & Setup Dependencies

### REQUIRED (MUST-INSTALL)
- **Local REST API with MCP** (`coddingtonbear/obsidian-local-rest-api`) — **latest, >= 5.0.2** (§0.6)
  - Endpoint: `https://127.0.0.1:27124` (HTTPS default); `http://127.0.0.1:27123` opt-in
  - Auth: `Authorization: Bearer <api-key>` from the plugin's settings pane, read by
    Akira from `OBSIDIAN_API_KEY`
  - Installation: Obsidian Settings → Community Plugins → Search "Local REST API" → Install & Enable
  - Fallback needed: If plugin not running, fail gracefully (suggest enabling)
  - See `SETUP_OBSIDIAN_FOCUS_MODE.md` for the version-pinning warning

### RECOMMENDED (ENHANCE UX)
- **Mermaid** — usually built-in to Obsidian v1.6+; optional upgrade
- **Excalidraw** — future feature; not v1

### DOCUMENTATION REQUIRED
Create a **SETUP_OBSIDIAN_FOCUS_MODE.md** guide covering:
- How to install Local REST API plugin
- How to configure API security (port, optional token)
- How to enable Focus Mode in Akira
- Troubleshooting (e.g., REST API not responding)

---

## Known Unknowns & Open Questions

1. **REST API Plugin Stability**
   - Have you used Local REST API plugin in production before? Any reliability concerns?
   - Fallback strategy if plugin crashes during session?

2. **Note Name Resolution**
   - Should Akira prioritize exact name match or fuzzy match? (e.g., "Project Alpha" vs. "2025-01 Project Alpha Roadmap")
   - How aggressively should it search? (e.g., should "alpha" match "Project Alpha" OR only exact phrases?)

3. **Backlink Density**
   - How many backlinks are helpful without creating noise? (e.g., should every new note link to 5+ existing notes?)
   - Should backlinks be context-aware (e.g., only link if semantic relevance > threshold)?

4. **Clarifying Question Thresholds**
   - Current heuristics (flow rate, ambiguity count) are estimates. Should we tune based on user behavior?
   - Should there be a user setting: "aggressive ask mode" vs. "trust mode"?

5. **Session-End Behavior**
   - Auto-summarize always, or only if user hasn't already written a summary?
   - Should summaries be editable by user before commit? (adds friction; trade-off?)

---

## Implementation Order (Suggested)

### Phase 1 (Foundation — Week 1–2)
1. Create `obsidian_context.py` — session state & note discovery
2. Create `obsidian_control.py` — REST API client & basic operations
3. Wire into `executor.py` and `claude_handler.py`
4. **Test:** Basic note creation & update via voice

### Phase 2 (Refinement — Week 2–3)
1. Create `obsidian_clarify.py` — clarifying question logic
2. Integrate with action confirmation loop in `akira.py`
3. Add MOC generation to `obsidian_control.py`
4. **Test:** Clarifying questions in ambiguous scenarios; MOC generation

### Phase 3 (Polish & Proposals — Week 3–4)
1. Add session-end auto-summary (Proposal A)
2. Evaluate Proposals B, C, D for inclusion
3. Create SETUP guide & documentation
4. **Test:** End-to-end focus sessions; user feedback loop

### Post-v1 (Future)
- Weekly review auto-generation (Proposal B)
- Pomodoro linkage (Proposal C)
- Smart tagging (Proposal D)
- Excalidraw integration
- Multi-user vault sync handling

---

## Success Criteria (How to Know v1 is Working)

✅ User can say "track progress" and Akira adds a summary to the right note  
✅ Ambiguous note targets trigger a helpful clarifying question  
✅ Akira proactively creates wikilinks and backlinks when generating MOCs  
✅ Mermaid diagrams embed in MOCs and render in Obsidian  
✅ Focus session summaries appear in a durable daily/weekly log  
✅ User finds clarifying questions helpful, not annoying (subjective; needs user feedback)  
✅ Zero data loss — all updates successfully reach Obsidian vault  
✅ REST API failures are handled gracefully with clear error messages  

---

## Appendix A: Obsidian Wikilink & MOC Reference

### Wikilink Syntax
```markdown
[[Note Name]]                          # Link to exact note
[[Note Name|Display Text]]             # Link with custom label
[[Note Name#Section]]                  # Link to specific section
[[2025-01 Project Alpha]]              # Link with date prefix
```

### MOC Structure Example
```markdown
# Project Alpha — Index
Overview and structure for Project Alpha deliverables.

## Planning & Roadmap
[[2025-01 Project Alpha Roadmap]]
[[Q1 Goals]]

## Technical Design
[[Database Schema v2]]
[[API Architecture]]

## Progress Tracking
[[2025-01-15 Daily Standup]]
[[Focus Session Logs — January]]

## Related Projects
[[Infrastructure Initiative]]
[[Team Processes]]
```

### Backlinks (Automatic)
When you create `[[Project Alpha]]` in any note, Obsidian automatically lists that reference in "Project Alpha" under its backlinks section. No manual curation needed.

---

## Appendix B: Clarifying Question Examples

### Ambiguity Resolution
```
"I found these potential notes:
  1. Daily Progress Log
  2. Project Alpha — Progress
  3. 2025-01 Weekly Review
Which should I add this to?"
```

### Structure Enhancement
```
"This note doesn't have a clear date structure yet. Want me to:
  1. Create a dated section (### 2025-01-15)
  2. Add this under an existing section
  3. Create a new section like '## Progress'?"
```

### Linking Suggestion
```
"I noticed you mentioned 'Database Schema' and 'Project Alpha' 
in this session. Want me to link this new note to those?"
```

### Intent Clarification
```
"You said 'add something important to my notes'. Could you be more specific?
  • Add today's meeting summary?
  • Track a new blocker?
  • Capture an idea?"
```

---

## Appendix C: REST API Endpoints (Local REST API Plugin)

> **SUPERSEDED — do not implement against this.** None of the endpoints below exist in
> the shape shown (wrong paths, wrong methods, no auth header). Use
> [§0.5](#05-corrected-endpoint-reference) instead. Kept only for delta auditing.

```
GET /vault/search?query=<term>         # Search notes
  Response: [{"name": "...", "path": "...", "modified": ...}]

GET /vault/<filename>                  # Read note content
  Response: {"content": "...", "modified": ...}

POST /vault/<filename>                 # Create/update note
  Body: {"content": "..."}
  Response: {"success": true}

GET /vault/list                        # List all notes
  Response: [{"name": "...", "path": "..."}]
```

---

## Document Status & Next Steps

**Current Status:** COMPLETE PLANNING DOCUMENT  
**Ready For:** User review, clarification on unknowns, approval to proceed to Phase 1 implementation

**For User Approval:**
1. Do you want to proceed with this architecture?
2. Any modifications to the scope or feature set?
3. Approval on the four creative proposals—include all, some, or none in v1?
4. Any known issues with Local REST API plugin you want flagged?

**Once Approved:**
- Lock this plan (no further changes mid-implementation)
- Create tickets/tasks for Phase 1 work
- Begin implementation with fresh session picking up from Phase 1 checklist