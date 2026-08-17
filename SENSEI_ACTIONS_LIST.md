# Sensei Action & Function Directory

Sensei has over 80+ unique actions built-in, many of which are multi-layered tools for specific platforms. Below is the complete catalog of everything Sensei can currently execute.

> [!NOTE]
> Actions marked with **[C]** are **Gated**. They require explicit user confirmation before executing, and on the Pro tier, they are subject to the reliability gate.

## System & OS Control
*   `open_application` / `close_application` **[C]**
*   `maximize_window` / `minimize_window` / `switch_window`
*   `adjust_volume` (absolute, relative, mute, unmute)
*   `adjust_brightness`
*   `screenshot`
*   `lock_pc`
*   `performance_stats` (CPU, memory, disk usage)

## Windows Settings & Maintenance
*   `open_settings` (Direct links to Wi-Fi, Bluetooth, Display, Sound, etc.)
*   `open_system_tool` (Task Manager, Control Panel, Device Manager)
*   `toggle_wifi` / `toggle_bluetooth`
*   `clear_temp_files` **[C]**
*   `empty_recycle_bin` **[C]**
*   `clear_browser_cache` **[C]**
*   `run_disk_cleanup` **[C]**
*   `shutdown_pc` **[C]** / `restart_pc` **[C]** / `sleep_pc` **[C]** / `hibernate_pc` **[C]** / `sign_out` **[C]**

## Files & Folders
*   **Navigation & Read:** `open_folder`, `list_folder`, `search_file`, `open_file`
*   **Ingestion:** `read_file`, `summarize_file`, `file_to_doc` (extracts local file to Google Docs)
*   **Write & Modify:** `create_file`, `write_file` **[C]**, `edit_file` **[C]**
*   **Management:** `copy_files`, `move_files` **[C]**, `delete_files` **[C]**
*   **Bulk Ops:** `compress_files`, `extract_files`, `organize_folder` **[C]**, `bulk_rename_files` **[C]**

## Browser & Web Automation
*   **Navigation:** `web_search`, `open_url`, `site_search`, `browser_control` (back/forward/reload)
*   **Tabs:** `new_tab`, `open_site_tab`, `switch_tab`, `close_tab`, `list_tabs`
*   **Native DOM:** `click`, `fill`, `scroll` (Handled by the Servant_Mech tier)

## Images & Wallpaper
*   `search_image` (Queries safe image APIs and opens a local picker)
*   `download_image` (Downloads the user's picked result)
*   `set_wallpaper` (Sets a local or downloaded image as desktop background)

## Clipboard & Background
*   `read_clipboard` / `write_clipboard`
*   `background_status` (Checks the status of long-running operations)

## Memory & Identity
*   `search_memory` (Searches daily rolling logs for specific facts or events)
*   `forget_today` (Deletes the current day's log file)
*   `wipe_all_memory` **[C]** (Deletes all memory logs and the core profile)

---

# Platform-Specific Controllers

Sensei has dedicated controller tools that interact with complex web applications and desktop software using native APIs or highly specialized DOM routines, rather than generic clicks.

## Obsidian (`obsidian_control`)
*   `organize`: Hands raw content to a reasoning pass to structure into the vault.
*   `focus`: Turns Focus Mode ON or OFF.
*   `append` / `progress`: Adds text under headings or timestamped progress logs.
*   `create`: Creates new notes (additive only, never overwrites).
*   `link` / `moc`: Injects wikilinks or creates Map of Content index notes.
*   `read` / `search` / `active` / `open` / `tags`
*   `diagram`: Embeds mermaid code blocks natively.

## Microsoft Office (`office_control`)
*   **Word:** open, new, read, insert (dictation), generate (AI drafting with images), save, save as **[C]**, close **[C]**. Full formatting control (bold, italic, font, align, bullets, heading styles).
*   **Excel:** open, new, read (speaks cells), write, format (color, number formats), formula, chart (inserts native charts), save, save as **[C]**, close **[C]**.
*   **PowerPoint:** open, new, presentation navigation, start/end slideshow, new slide, set title/content, delete slide **[C]**, save as **[C]**.
*   **Teams:** open, focus (No automation interface exists for messaging).

## Google Workspace
*   **Gmail:** `gmail_control` (search, read, unread, labels), `gmail_compose` (drafts or AI-generates emails in the browser for user review).
*   **Calendar (`calendar_control`):** list, free (find slots), create, get, update, delete **[C]**.
*   **Docs (`docs_control`):** create, generate (AI writer), read, append.
*   **Sheets (`sheets_control`):** create, generate, read, write.
*   **Slides (`slides_control`):** create, generate, read, update, delete **[C]**.

## GitHub (`github_control`)
*   **Browse:** search repos, open repo, view file, view issues, view PRs, read readme.
*   **Actions:** star, unstar, fork, clone repo (local git clone), create issue, repo notes (background architecture summarization).
*   **State Changes (Gated):** create PR **[C]**, merge PR **[C]**, close issue **[C]**, close PR **[C]**, delete branch **[C]**, delete repo **[C]**.

## VS Code (`vscode_control`)
*   `open folder` / `open file` / `create file` / `read file` / `write file` / `edit file` / `search file`

## Spotify (`spotify_control`)
*   **Playback:** play, pause, resume, next_track, previous_track, seek, skip.
*   **Volume:** set_volume, get_volume, mute, unmute.
*   **UI & Library:** show_lyrics, show_library, show_liked, show_playlist, open_playlist, play_mood, shuffle, repeat.
*   **Device:** transfer, devices, now_playing.

## Entertainment & Shopping
*   **Netflix (`netflix_control`):** search, play, pause, volume, seek, skip, playback speed, fullscreen, episodes, subtitle, audio, switch profile.
*   **Amazon (`amazon_control`):** search, select result, select variant, quantity, add to cart, view cart, proceed to checkout, confirm address.
*   **Flipkart (`flipkart_control`):** search, select result, select variant, add to cart, view cart, proceed to checkout, confirm address.

## Google Meet (`meet_control`)
*   join, mute, unmute, camera off, camera on, leave, raise hand, lower hand, chat, state.
