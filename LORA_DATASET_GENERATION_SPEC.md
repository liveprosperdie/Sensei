# LoRA Dataset Generation Specification (Akira / Sensei)

This specification defines the input-output contract, prompt templates, taxonomy of actions, and generation strategies needed to synthesize **5,000 – 6,000 high-quality training pairs** to fine-tune the local LoRA adapter (`SERVANT_MECH` / `akira_mech.gguf`) on **Llama-3-8B-Instruct**.

---

## 1. Why 5,000 – 6,000 Examples is the Sweet Spot

For LoRA fine-tuning on an 8B parameter model (e.g., Llama-3-8B at Rank $r=16$ or $r=32$, $\alpha=32$):
* **< 1,500 examples:** Model struggles with edge-case parameter extraction and occasionally outputs malformed JSON.
* **3,000 – 6,000 examples:** **The golden ratio.** Rigid JSON schema compliance, strong parameter extraction across diverse natural phrasing, and zero catastrophic forgetting of base model English fluency.
* **> 15,000 examples:** High risk of overfitting to synthetic phrasing templates and degrading general conversation.

---

## 2. Model Prompt Format (Llama-3-Instruct Wire Format)

Every training example should be formatted using the official Llama-3-Instruct template:

```
<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are Akira, an autonomous desktop voice assistant.
Your job is to analyze the user's spoken instruction and desktop context, then output a STRICT JSON action envelope.
Follow these rules:
1. Output valid JSON and NOTHING ELSE. No markdown fences, no thought tags, no introductory prose.
2. Output keys: "mode", "action", "parameter", "actions", "response", "confirmation_required", "confirmation_message", "end_session".
3. If an action is destructive (shutdown, close unsaved app, delete), set "confirmation_required": true and write a clear "confirmation_message".
4. If the user's intent is ambiguous or unresolvable, set "action": "NO_MATCH" and ask for clarification in "response".<|eot_id|><|start_header_id|>user<|end_header_id|>

<untrusted_external_context>
[FOCUSED APP] {{focused_app}}
[ACTIVE WINDOW] {{active_window}}
[OPEN TABS] {{open_tabs}}
</untrusted_external_context>

User: {{user_utterance}}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

{{target_json}}<|eot_id|>
```

---

## 3. The Target Output JSON Schema

Every assistant turn must output this exact structure:

```json
{
  "mode": "command",
  "action": "adjust_volume",
  "parameter": "+10",
  "actions": [
    {
      "action": "adjust_volume",
      "parameter": "+10"
    }
  ],
  "response": "Turning the volume up.",
  "confirmation_required": false,
  "confirmation_message": null,
  "end_session": false
}
```

### Schema Rules:
* `mode`: `"command"` for OS actions, `"conversation"` for conversational queries.
* `action`: Canonical action name (must exist in executor).
* `parameter`: String or null. If multiple parameters, delimited as defined by the tool (e.g. `"list|today"`, `"pause"`, `"+10"`).
* `actions`: List of one or more execution steps `[{"action": "...", "parameter": "..."}]`.
* `response`: Short, warm, natural spoken feedback to be voiced via TTS (1 sentence max).
* `confirmation_required`: `true` for destructive actions; `false` otherwise.
* `confirmation_message`: Warm confirmation question if `confirmation_required` is `true`, otherwise `null`.
* `end_session`: `true` if the utterance ends the conversation (e.g., *"bye"*, *"mute and close"*), `false` to keep listening.

---

## 4. Complete Action & Intent Taxonomy for Dataset Generation

The dataset should cover all routine actions, multi-step chains, deictic references, and negative/escalation cases.

### Category 1: Audio & System Control (15% ~ 800 examples)
| Intent / Action | Parameter Syntax | Example Utterances | Confirmation? |
| :--- | :--- | :--- | :---: |
| `adjust_volume` | `"+10"`, `"-10"`, `"+20"`, `"-15"`, `"50"`, `"mute"`, `"unmute"` | "volume up", "louder please", "turn it down a notch", "make it 40%", "mute the pc", "unmute audio" | No |
| `performance_stats` | `null` | "how is my pc doing", "check cpu usage", "performance stats", "how much ram is free" | No |
| `toggle_wifi` | `"on"`, `"off"` | "turn wifi off", "enable wifi", "disconnect from wifi" | No |
| `toggle_bluetooth` | `"on"`, `"off"` | "turn bluetooth on", "disable bluetooth" | No |
| `clear_temp_files` | `null` | "clean my temp files", "clear windows cache", "delete temporary junk" | **Yes** |
| `shutdown_pc` | `null` | "turn off my computer", "shutdown the pc", "power down" | **Yes** |
| `restart_pc` | `null` | "restart my computer", "reboot the pc" | **Yes** |
| `sleep_pc` | `null` | "put the pc to sleep", "sleep mode" | **Yes** |
| `lock_pc` | `null` | "lock the screen", "lock my workstation" | No |

---

### Category 2: Media & Playback (20% ~ 1,100 examples)
| Intent / Action | Parameter Syntax | Example Utterances | Notes |
| :--- | :--- | :--- | :--- |
| `spotify_control` | `"pause"` | "pause spotify", "stop the music", "hold the music" | Routine |
| `spotify_control` | `"resume"` | "resume spotify", "continue playing", "unpause music" | Routine |
| `spotify_control` | `"next_track"` | "skip song", "next track", "skip this" | Routine |
| `spotify_control` | `"previous_track"` | "previous song", "go back a track", "replay last song" | Routine |
| `spotify_control` | `"play|<query>"` | "play Starboy on spotify", "put on some lofi beats", "play Hans Zimmer" | Contextual search |
| `youtube_control` | `"pause"` | "pause youtube", "pause video", "stop video" | Routine |
| `youtube_control` | `"resume"` | "resume youtube", "play video", "unpause video" | Routine |
| `youtube_control` | `"seek +10"`, `"seek -15"` | "skip forward 10 seconds", "rewind 15 seconds", "jump ahead" | Relative seeking |
| `youtube_control` | `"like"` | "like this video", "thumbs up the video" | In-browser UI |
| `youtube_control` | `"subscribe"` | "subscribe to this channel" | In-browser UI |
| `youtube_control` | `"volume 80"` | "set youtube volume to 80" | Player volume |

---

### Category 3: Application & Window Management (20% ~ 1,100 examples)
| Intent / Action | Parameter Syntax | Example Utterances | Notes |
| :--- | :--- | :--- | :--- |
| `open_application` | `"<app_name>"` | "open spotify", "launch chrome", "start notepad", "fire up vs code", "open calculator" | Target normalization |
| `close_application` | `"<app_name>"` or `""` | "close this window", "exit discord", "close excel", "kill task manager" | Unsaved apps trigger confirmation |
| `minimize_window` | `""` | "minimize this window", "minimize", "hide window" | Foreground focus |
| `maximize_window` | `""` | "maximize window", "make it full screen", "maximize" | Foreground focus |
| `switch_window` | `"<app_name>"` | "switch to discord", "bring up chrome", "focus notepad", "switch back to vs code" | Window title matching |

---

### Category 4: Browser Navigation & Tabs (15% ~ 800 examples)
| Intent / Action | Parameter Syntax | Example Utterances | Notes |
| :--- | :--- | :--- | :--- |
| `list_tabs` | `""` | "what tabs are open", "list my tabs", "show open browser tabs" | Reads active tabs |
| `switch_tab` | `"<title_or_index>"` | "switch to github tab", "go to the youtube tab", "switch to tab 3" | Title fuzzy match |
| `close_tab` | `""` or `"<title>"` | "close this tab", "close the current tab", "close reddit tab" | Active tab drop |
| `new_tab` | `""` | "open a new tab", "new tab please", "create empty tab" | Browser shortcut |
| `web_search` | `"<query>"` | "search for latest nvidia drivers on google", "look up weather in tokyo", "google rust vs go" | Parameter extraction |

---

### Category 5: Productivity & Clipboard (10% ~ 550 examples)
| Intent / Action | Parameter Syntax | Example Utterances | Notes |
| :--- | :--- | :--- | :--- |
| `read_clipboard` | `""` | "read my clipboard", "what did i just copy", "what's on clipboard" | Reads clipboard |
| `write_clipboard` | `"<text>"` | "copy hello world to clipboard", "put this text in clipboard" | Sets clipboard |
| `calendar_control` | `"list|today"`, `"list|tomorrow"` | "what is on my calendar today", "check my schedule", "what meetings do i have" | Calendar read |
| `get_current_time` | `""` | "what time is it", "tell me the time", "current time" | Clock check |

---

### Category 6: Multi-Step Sequential Chains (10% ~ 550 examples)
Utterances that contain 2 or 3 independent sequential actions:

* **Example 1:** *"Open notepad and open chrome"*
  ```json
  {
    "mode": "command",
    "action": "open_application",
    "parameter": "notepad",
    "actions": [
      {"action": "open_application", "parameter": "notepad"},
      {"action": "open_application", "parameter": "chrome"}
    ],
    "response": "Opening Notepad, and opening chrome.",
    "confirmation_required": false,
    "confirmation_message": null,
    "end_session": false
  }
  ```
* **Example 2:** *"Pause music, turn the volume up, and open calculator"*
  ```json
  {
    "mode": "command",
    "action": "spotify_control",
    "parameter": "pause",
    "actions": [
      {"action": "spotify_control", "parameter": "pause"},
      {"action": "adjust_volume", "parameter": "+10"},
      {"action": "open_application", "parameter": "calculator"}
    ],
    "response": "Pausing Spotify, turning the volume up, and opening calculator.",
    "confirmation_required": false,
    "confirmation_message": null,
    "end_session": false
  }
  ```

---

### Category 7: Deictic & Context-Dependent References (5% ~ 300 examples)
Utterances where the user refers to pronouns (*"it"*, *"this"*, *"that"*), resolved via the desktop context:

* **Context:** `[FOCUSED APP] Spotify | [ACTIVE WINDOW] Spotify Free`
  * **User:** *"Close it"*
  * **Target:** `action="close_application"`, `parameter="spotify"`
* **Context:** `[CURRENT PAGE] https://www.youtube.com/watch?v=xyz`
  * **User:** *"Pause it"*
  * **Target:** `action="youtube_control"`, `parameter="pause"`
* **Context:** `[FOCUSED APP] Excel.exe | [ACTIVE WINDOW] Q3_Financials.xlsx`
  * **User:** *"Kill this window"*
  * **Target:** `action="close_application"`, `parameter="excel"`, `confirmation_required=true`, `confirmation_message="Close Excel? You might have unsaved spreadsheet changes."`

---

### Category 8: Negatives & Escalation Turns (5% ~ 300 examples)
Utterances that the local LoRA **must not** guess and should gracefully refuse or pass to Claude:

* **User:** *"Can you explain quantum computing in detail?"*
  ```json
  {
    "mode": "conversation",
    "action": "NO_MATCH",
    "parameter": null,
    "actions": [],
    "response": "That's a deep topic that needs full reasoning. Let me connect to Claude to break that down for you.",
    "confirmation_required": false,
    "confirmation_message": null,
    "end_session": false
  }
  ```
* **User:** *"Delete all files in my downloads older than 3 weeks"*
  *(Complex file organization requires Claude)*
  ```json
  {
    "mode": "command",
    "action": "NO_MATCH",
    "parameter": null,
    "actions": [],
    "response": "File filtering by age requires full analysis. Handing this off to Claude.",
    "confirmation_required": false,
    "confirmation_message": null,
    "end_session": false
  }
  ```

---

## 5. Recommended Dataset Mix (Total: 5,500 Examples)

```
┌────────────────────────────────────────────────────────┬─────────┐
│ Category                                               │ Count   │
├────────────────────────────────────────────────────────┼─────────┤
│ Media & Playback (Spotify / YouTube)                   │ 1,100   │
│ App & Window Management (Open, Close, Min, Max, Switch)│ 1,100   │
│ Browser Tabs & Web Search                              │ 800     │
│ Audio, Volume & Power/System Controls                  │ 800     │
│ Productivity, Clipboard & Calendar                     │ 550     │
│ Multi-Step Chains (2-3 actions)                        │ 550     │
│ Deictic Pronoun Context Resolution ("pause it", etc.)  │ 300     │
│ Negative & Cloud Escalation Turns                      │ 300     │
├────────────────────────────────────────────────────────┼─────────┤
│ TOTAL                                                  │ 5,500   │
└────────────────────────────────────────────────────────┴─────────┘
```

---

## 6. Synthetic Generation Strategy (Prompting an LLM to generate the 5k rows)

To generate these 5,500 examples cheaply and quickly (using GPT-4o, Claude 3.5 Sonnet, or a local pipeline):

### Synthetic Variation Vectors:
1. **Slang & Colloquialisms:**
   * *"Crank it up"*, *"blast the audio"*, *"nuke discord"*, *"fire up chrome"*, *"hush"*, *"kill the tunes"*.
2. **Politeness & Filler Words:**
   * *"Hey Akira could you please..."*, *"Uh Akira, can you maybe..."*, *"Do me a favor and..."*.
3. **Punctuation & Whisper Casing:**
   * Whisper frequently outputs lowercase or missing periods (e.g. `"open notepad and then chrome"`). Ensure ~40% of examples lack punctuation and formal capitalization.
4. **App Name Synonyms:**
   * Chrome, Google Chrome, browser, web browser.
   * VS Code, Visual Studio Code, code editor.
   * Explorer, File Explorer, folder window.
5. **Output Format:**
   Save into standard JSONL format (`train.jsonl` and `val.jsonl` at a 90/10 split):
   ```json
   {"text": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n...<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n...<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n...<|eot_id|>"}
   ```

---

## 7. Next Steps for LoRA Training

1. Use this spec with an generation script (or LLM batch API) to produce `train.jsonl` (5,000 rows) and `val.jsonl` (500 rows).
2. Train with **Unsloth** or **HuggingFace TRL (SFTTrainer)**:
   * Base Model: `unsloth/llama-3-8b-Instruct-bnb-4bit`
   * Target Modules: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`
   * LoRA Rank $r=16$, $\alpha=32$
   * Epochs: 2
   * Learning Rate: $2 \times 10^{-4}$
3. Export to GGUF (`akira_mech.gguf`) and place into `Akira/`.
4. Run `llama-server` on port 8081 with `-ngl 16` on your RTX 2050. The model will serve local commands in under 200ms at $0.00 cost.
