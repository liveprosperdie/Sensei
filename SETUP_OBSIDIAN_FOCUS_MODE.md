# Setup — Obsidian Focus Mode

Connects Akira to your Obsidian vault so you can say *"track our progress on Project
Alpha"* and have it land in the right note, under the right heading, without touching
the keyboard.

Takes about three minutes. There are two steps, and Step 2 is the one people get wrong.

---

## Step 1 — Install the plugin

Make sure Obsidian itself is up to date first: **Settings → General → Check for
updates**. You want **1.13.1 or newer** (current stable is 1.13.4). This is the only
version requirement, and updating Obsidian normally satisfies it.

Then: **Settings → Community plugins → Browse → search "Local REST API"**
(full name: *Local REST API with MCP*, by Adam Coddington).

Install it and **enable** it. **Take the latest version** — the browser gives you latest
by default, which is what you want.

> Repo, if you want to read the source:
> [`coddingtonbear/obsidian-local-rest-api`](https://github.com/coddingtonbear/obsidian-local-rest-api)

**If the plugin refuses to load and says it needs a newer Obsidian:** your Obsidian is
older than 1.13.1. Update Obsidian — don't downgrade the plugin.

<details>
<summary>Historical note: this guide used to tell you to pin 5.0.3. That is no longer necessary.</summary>

Plugin releases 5.0.0, 5.0.1, and 5.1.0 set `minAppVersion: 1.13.1`. For a while
Obsidian 1.13 was Catalyst-only early access, so those releases genuinely would not load
for most people, and the setup guide pinned 5.0.3 (`minAppVersion: 1.8.7`) with a manual
install procedure.

Obsidian 1.13 has since shipped to the public stable channel — `desktop-releases.json`
now reports `latestVersion: 1.13.4` with an identical `beta` block, i.e. no early-access
gap. So the requirement is satisfiable by anyone who updates Obsidian, and the manual
pin, the folder-dragging, and the whole version-picker problem are all moot.

Latest is now also the *better* choice: 5.1.0 fixes a bug where a read immediately after
a write could return stale content, which is exactly the read-after-write pattern Sensei
uses for note updates.

</details>

---

## Step 2 — Copy the API key

Open **Settings → Local REST API**. The top of the pane shows an **API Key** — copy it.

Add it to your `.env` next to `GROQ_API_KEY`:

```
OBSIDIAN_API_KEY=paste-the-key-here
```

> **Every endpoint except the health check requires this key.** If it is missing or
> wrong, nothing works and Akira will tell you so explicitly ("Obsidian rejected the API
> key...") rather than failing silently.

### About the HTTPS certificate

The plugin serves **HTTPS on port 27124 by default**, using a **self-signed**
certificate. That is expected, and Sensei handles it: on first connection it fetches the
plugin's own certificate and pins it as the trusted CA, so the connection is verified
rather than blindly trusted.

You do **not** need to enable the plain-HTTP server, and you should not — leaving it off
keeps your vault contents off unencrypted loopback. Everything is bound to `127.0.0.1`,
so nothing is reachable from your network either way.

If you have moved the port or are deliberately using HTTP, override the base URL:

```
OBSIDIAN_API_URL=http://127.0.0.1:27123
```

---

## Step 3 — Check it

Start Sensei with Obsidian running and say:

> "Is Obsidian connected?"

You should hear a confirmation with the port. If not, the message tells you which of the
three things is wrong — Obsidian closed, plugin disabled, or bad key.

---

## What you can say

| Say this | What happens |
|---|---|
| "Track our progress on Project Alpha" | Timestamped entry under that note's **Progress Log** |
| "Add that to my blockers" | Appends under the **Blockers** heading |
| "What's in my Q1 Goals note?" | Reads it back |
| "Which note am I looking at?" | Reports the note open in Obsidian |
| "Make a note called Meeting Notes" | Creates a new note |
| "Link this to Database Schema" | Adds `[[wikilinks]]` under **Related** |
| "Organize my notes on auth" | Builds a Map of Content index note |
| "Add a diagram of the flow" | Embeds a Mermaid block |
| "Find my notes about caching" | Searches the vault |
| "Open Project Alpha" | Opens it in the Obsidian UI |

Note names are spoken, not typed — "project alpha" finds `Project Alpha.md` anywhere in
the vault, including in subfolders. No extension, no path.

If a session starts with a note already open in Obsidian, that note becomes the default
target, so "add this to my notes" just works without a follow-up question.

---

## What it will not do

**Every write is additive.** There is deliberately no delete, no rename, and no
overwrite-an-existing-note action wired up:

- `create` **refuses** to overwrite a note that already exists — it tells you to append
  instead.
- Edits use the plugin's server-side heading patch, so Akira never rewrites a whole
  file. Your other headings cannot be clobbered by a bad edit, and it does not fight
  you if you are editing the same note in Obsidian at the same time.
- The plugin's ability to run arbitrary Obsidian commands is **not** exposed.

Destructive operations stay in your hands, in Obsidian.

Graph view is read-only in Obsidian, so nothing here "edits the graph" — it writes
`[[wikilinks]]`, and Obsidian derives the backlinks and graph edges from those
automatically. Same result, correct mechanism.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| "I can't reach Obsidian's REST API" | Obsidian is closed, or the plugin is disabled |
| "Obsidian rejected the API key" | `OBSIDIAN_API_KEY` is stale or wrong — re-copy from the settings pane |
| "I need an Obsidian API key first" | `OBSIDIAN_API_KEY` is not set at all |
| Plugin won't load / "requires newer version" | Your Obsidian is older than 1.13.1 — update Obsidian (Step 1) |
| Version warning on startup | Plugin is older than the tested minimum (5.0.2) — update it |
| Wrong note got the update | Say the note name explicitly; a note open in Obsidian is the default target |

Akira relays these once and stops. It will **not** silently reroute your notes into a
Google Doc or a local file if the vault is unreachable — the vault is the only correct
destination, so a failure is reported rather than worked around.