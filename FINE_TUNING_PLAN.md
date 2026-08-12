# Fine-Tuning Method — Per-Function Plan

Grounded in the committed dispatch table, not in an assumed action list. Every
count below was extracted from the repo, not estimated:

```
executor._ACTION_MAP        83 dispatchable actions
guard_rules.ACTION_RULES    83 rules  (perfect 1:1, no phantoms, no gaps)
distinct parameter shapes    5
```

Reproduce with:

```bash
python3 -c "
import ast, collections, verify_guard_coverage as v
disp = set(v.dict_keys('executor','_ACTION_MAP'))
tree = ast.parse(open('guard_rules.py',encoding='utf-8').read())
shapes = collections.defaultdict(list)
for n in ast.walk(tree):
    if isinstance(n, ast.AnnAssign) and getattr(n.target,'id','')=='ACTION_RULES':
        for k, val in zip(n.value.keys, n.value.values):
            shapes[getattr(val,'id',None) or ast.unparse(val)].append(k.value)
print(len(disp), {k: len(vv) for k, vv in shapes.items()})"
```

---

## 0. Corrections to the execution plan as written

These are not stylistic quibbles. Each one changes the budget, the schedule, or
whether a step can run at all.

### 0.1 — The action count is 83, not ~40

The Stage 2 table covers 15 or so actions. The real surface is 83. Planning
against the table under-scopes by roughly 5x.

### 0.2 — Three actions in the plan do not exist

| Plan says | Repo actually has | Shape |
|---|---|---|
| `send_email` | `gmail_compose` | SUB |
| `summarize_document` | `summarize_file` | TEXT |
| `create_document` | `create_file`, `file_to_doc` | TEXT, SUB |

Seeding `send_email` produces data whose `action` value the grammar will reject
outright. Also note there is no `organize_files` two-key form — it is `OPT_TEXT`
(zero or one field), not the `"files|destination"` the plan's prose implies.

### 0.3 — `target_description` / `output_format` / `brevity` are not in the schema

`ROUTING_SCHEMA` (claude_handler.py:1457) is exactly:

```
mode ("command"|"conversation")   required
action, parameter                 single-action form
actions[], pending_actions[]      multi-action form  (_STEP_SCHEMA items)
confirmation_required, confirmation_message
response, end_session
additionalProperties: False
```

`_STEP_SCHEMA` is `{action, parameter, id, depends_on}`, `required: [action]`.
There is no `target_description`, no `output_format`, no `brevity`. Because
`additionalProperties: False` is enforced by `responseJsonSchema`, seed examples
carrying those keys are **rejected by the grammar, not merely ignored**. Every
such example is wasted spend.

The plan's "click must have verbatim `target_description`, not a paraphrase"
rule is still a real and correct rule — it just applies to `parameter`, which is
a single required free-text field.

### 0.4 — The `focus_mode` bug is already fixed structurally; do not buy it again

The plan puts the largest seed (250-300) on `click` citing that bug. But
`claude_handler._action_enum()` now reads action names from `_ACTION_MAP` and
injects them as a hard `enum` into the schema, at three sites (`action`,
`actions[].action`, `pending_actions[].action`). The model **cannot** emit
`focus_mode`. A grammar constraint is absolute; training data can only ever
approximate it. Spending the largest seed budget teaching action names buys
approximately nothing.

Where that budget *should* go: see 0.5.

### 0.5 — The same bug class is still wide open one level down, and this is the real target

`guard_rules.Rule` is explicit that it is **arity only**:

> "Arity only. This is not a type system and must not grow into one."

So for the 27 `SUB`/`SUB_ARGS` actions, the *sub-action vocabulary inside
`parameter`* is unconstrained free text. `obsidian_control|focus|on` is correct;
`obsidian_control|focusmode|on` satisfies the schema, satisfies the arity rule,
and is wrong. The grammar cannot catch it. Nothing catches it before dispatch.

**This is precisely where training data has leverage that structure does not.**
Reallocate the `click` over-budget here.

Two recommendations, in priority order:

1. **Extend the enum approach to sub-actions.** Each controller has a fixed
   sub-action set. Harvesting them into per-action enums would kill this bug
   class the same way it was killed for action names — structurally, permanently,
   with no training data. Cheaper and stronger than any dataset. Do this first.
2. Seed the residual only after (1), for the arg field that genuinely is free
   text.

### 0.6 — Blocker: Steps 2, 3 and 5 cannot execute in this build

The plan's core loop is "fine-tune adapter → run it locally to generate
thousands of outputs → retrain." There is no local inference runtime:

- `tiers.LocalModel.resolve()` returns `Unavailable` on **every** path. Its
  docstring: *"Never available... there is no runtime to hand back."*
- `hardware_gate.runtime_verified()` is documented as an *"HONEST STUB. Always
  NotVerified."* and states *"There is no code path in this module that returns
  'verified' for a model."*

`SENSEI_LOCAL_ADAPTER_PATH` is a real, reserved config slot — the intended
attachment point — but nothing loads it. So a trained adapter has nowhere to go,
and Step 3's "near-zero marginal cost, since it's local/self-hosted inference
now" has no substrate. **Wiring a runtime is a hard prerequisite, not a
downstream detail.**

### 0.7 — The "near-zero cost" assumption is unverified and may be false

`hardware_gate` declares CPU-only **INFEASIBLE** for a voice assistant (latency,
not capability), and its floors are `PLACEHOLDER_*` — never measured:

```
PLACEHOLDER_MIN_VRAM_GB_BASE      6
PLACEHOLDER_MIN_VRAM_GB_ADAPTERS  8
PLACEHOLDER_MIN_RAM_GB_BASE      16
PLACEHOLDER_MIN_RAM_GB_ADAPTERS  32
```

Note the adapter tier costs +2 GB VRAM / +16 GB RAM over base. Run
`hardware_gate.capability()` on the actual training and inference boxes **before
committing to this pipeline**. If the box is CPU-only or under 8 GB VRAM, Step 3
is infeasible and the economics invert — Gemini-for-inputs stays cheap but
self-generated outputs do not exist.

### 0.8 — Don't write the Step 4 filter; most of it is already committed

| Plan's filter step | Already in repo |
|---|---|
| 4.1 schema validation | `responseJsonSchema` + `ROUTING_SCHEMA`; `llm_json.py` |
| 4.2 rule-based checks | `guard_rules.ACTION_RULES` arity + risky-keyword screen |
| action-name validity | `claude_handler._action_enum()` |
| envelope sanity | `verify_gemini_head._parse` fail-closed suite (60 checks) |

Point the filter at these. A second validator would become the "second taxonomy"
`guard_rules` explicitly exists to prevent.

### 0.9 — The eval harness already exists and disagrees with Step 7

`reliability.py` is a per-action-type ledger: `THRESHOLD=20`, default mode
**consecutive** (any failure resets the streak), deliberately per-action-type
because *"'delete_files has proven itself' says nothing about shutdown_pc."*

So the holdout must be **stratified per action type**, not a flat 15-20% slice of
a mixed pool. A flat slice leaves most of the 83 actions with too few holdout
examples to ever clear a 20-run consecutive gate. Also note the module is honest
that consecutive-vs-cumulative was *unresolvable from the code* and both are
implemented — fix `RELIABILITY_MODE` deliberately before generating eval data
against it.

---

## 1. The restructure: seed by shape, not by action

`guard_rules.py` states the key fact directly:

> "80 actions collapse to five shapes"

Actual distribution:

| Shape | Arity | Actions | What the model must actually learn |
|---|---|---|---|
| `SUB` | 1-2 | **26** | Pick correct sub-action from a fixed vocab; when to add arg |
| `TEXT` | 1 | **23** | Extract one verbatim span; never paraphrase |
| `IGNORED` | 0 | **22** | Emit **no** parameter at all |
| `OPT_TEXT` | 0-1 | **11** | Decide whether the field belongs at all |
| `SUB_ARGS` | 1-3 | **1** | `office_control` only: `app\|sub\|args` |

Per-action seeding at 200 avg = **~16,600 Claude examples**. But an action's
identity is already free (enum-constrained), and its parameter *structure* is one
of five. What varies per action is only **lexical**: which utterances map to it.
That is cheap Gemini work, not Claude work.

### Budget comparison

| | Claude examples | vs. plan |
|---|---|---|
| Per-action (plan as written) | ~16,600 | — |
| Shape-anchored (this doc) | **~1,650** | **~10x less** |

Shape-anchored breakdown:

| Bucket | Claude seeds | Rationale |
|---|---|---|
| `SUB` shape + sub-action vocab | 400 | Highest risk (0.5); unconstrained vocab |
| `TEXT` verbatim-extraction | 300 | Anti-paraphrase is the whole skill |
| `OPT_TEXT` omit-vs-include | 200 | Half must omit the field entirely |
| `IGNORED` no-parameter | 100 | Only lesson: emit nothing |
| `SUB_ARGS` (`office_control`) | 150 | Sole 3-field shape, delegated risk |
| Envelope: `actions` vs `pending_actions`, `depends_on` chains, `mode`, confirmation | 500 | Structurally unique; the demo centerpiece |
| **Claude total** | **~1,650** | |
| Lexical coverage, ~10/action × 83 | ~830 **Gemini** | Cheap; inputs only |

The plan's own instinct — "use Gemini free tier for input diversity, it's easy
and doesn't need Claude quality" — is right, and applies to far more of the
surface than it claims.

### Keep JSONL files per **shape**, plus a metadata tag per action

The plan says one file per task category. Make the file boundary the *shape*
(that is what the adapter learns) and keep the action name as a metadata tag (for
balanced sampling and per-action drift detection). One file per action would give
83 files, most nearly identical, and would hide shape-level drift — the thing
that actually breaks.

```jsonl
{"shape":"SUB","action":"obsidian_control","variant":"sub+arg","input":"...","output":{...}}
```

---

## 2. Per-function method

The "each function" ask, organized by shape since that is what training acts on.

### 2.1 `IGNORED` — 22 actions, zero-parameter

`background_status, bookmark_page, clear_temp_files, empty_recycle_bin,
hibernate, hibernate_pc, list_tabs, lock_pc, lock_screen, performance_stats,
preview_temp_cleanup, read_clipboard, read_more, restart, restart_pc,
run_disk_cleanup, screenshot, shutdown, shutdown_pc, sign_out, sleep_pc,
stop_reading`

- **Only failure mode**: hallucinating a parameter. `Rule(0,0)` rejects it, so
  the guard catches it — but a rejected action is still a failed turn.
- **Method**: 100 Claude seeds total (not per action) proving "no parameter";
  ~10 Gemini utterance variants per action for lexical coverage.
- **Note the alias pairs** (`hibernate`/`hibernate_pc`, `restart`/`restart_pc`,
  `shutdown`/`shutdown_pc`, `lock_screen`/`lock_pc`). These are legacy aliases
  onto `system_control` with identical behavior. **Pick one per pair for training
  and hold the alias out** — otherwise you teach an arbitrary coin-flip and pay
  for the confusion in eval noise forever.
- `screen=False` here: no risky-keyword screen runs, since there is no text.
  Destructive members (`shutdown_pc`, `empty_recycle_bin`) are gated by
  confirmation/reliability, **not** by parameter screening. Seed the *envelope*
  (§2.6), not the parameter.

### 2.2 `TEXT` — 23 actions, one required verbatim field

`adjust_brightness, adjust_volume, click, close_application, create_file,
delete_files, download_image, open_application, open_file, open_folder,
open_settings, open_site_tab, open_system_tool, open_url, read_file, search_file,
search_image, set_wallpaper, summarize_file, switch_tab, switch_window,
web_search, write_clipboard`

- **The one lesson**: copy the span **verbatim**. Paraphrase is the documented
  `click` failure and `element_matcher.py` matches on the literal string.
- **Method**: 300 Claude seeds concentrated on adversarial verbatim cases —
  quoted labels, casing, punctuation, trailing words ("click the *big blue* Sign
  in button"), spans that look like they want normalizing but must not be.
- **Negative seeds matter more than positive here.** Include pairs where the
  paraphrase is tempting and wrong, with the correct verbatim output.
- **`delete_files` is the strictest action in the codebase** (prompt: *"never
  send vague targets like 'everything'"*). Seed refusal-to-vague explicitly. Its
  confirmation enumeration is built **by the executor** — so
  `confirmation_required` must **not** be set for it (§2.6). Getting this
  backwards is a double-confirmation bug.
- Split `adjust_volume`/`adjust_brightness` out for numeric/relative parsing
  ("turn it down a bit" → what value?). Different skill from span extraction;
  mixing them blurs both.

### 2.3 `OPT_TEXT` — 11 actions, zero-or-one field

`clear_browser_cache, close_tab, list_folder, maximize_window, minimize_window,
new_tab, organize_files, organize_folder, scroll, toggle_bluetooth, toggle_wifi`

- **The one lesson**: whether the field belongs at all. "close the tab" (omit) vs
  "close the billing tab" (include). Omission is a *decision*, and the failure is
  inventing a plausible default.
- **Method**: 200 Claude seeds, deliberately **~50/50 omit vs include**. An
  unbalanced set teaches a prior, not a decision.
- `toggle_wifi`/`toggle_bluetooth` take optional `on`/`off`; absent means
  *toggle*. Seed all three (on / off / bare) or the model will guess.
- `organize_files`/`organize_folder` need the **spoken-preview phrasing** baked
  into `response` — executor enumerates the plan before moving anything.

### 2.4 `SUB` — 26 actions, `"sub"` or `"sub|arg"` — **highest priority**

`amazon_control, browser_control, bulk_rename_files, calendar_control,
compress_files, copy_files, docs_control, edit_file, extract_files, file_to_doc,
fill, flipkart_control, github_control, gmail_compose, gmail_control,
meet_control, move_files, netflix_control, obsidian_control, sheets_control,
site_search, slides_control, spotify_control, vscode_control, write_file,
youtube_control`

Largest bucket **and** the one place the grammar cannot help (§0.5).

- **Do §0.5 recommendation 1 first.** Harvest each controller's real sub-action
  vocabulary and constrain it. Every sub-action fixed by an enum is a sub-action
  you never need to train, forever.
- **Method for the residual**: 400 Claude seeds split across
  (a) sub-action selection where names are near-synonyms, and
  (b) the `sub` vs `sub|arg` arity decision.
- **Sub-vocab must be harvested from each controller module, never hand-typed** —
  the same anti-drift discipline `_action_enum()` and `TIER1_ACTIONS` already
  follow. A hand-typed list is a third taxonomy.
- `fill` is `SUB` = `"target|value"`, **not** two schema keys. The plan's
  "two-key structure" framing produces malformed output.
- `gmail_compose` is the highest-blast-radius member. The plan's instinct
  (manual review, not sample-judge) is right — apply it here, not to a
  nonexistent `send_email`.
- `copy_files`/`move_files`/`bulk_rename_files`/`compress_files`/`extract_files`
  are `[C]` file actions: executor builds the enumeration, so do **not** set
  `confirmation_required`.

### 2.5 `SUB_ARGS` — `office_control` only, `"app|sub|args"`

- Sole 3-field shape; `office_control._HANDLERS` = `{word, excel, ...}`.
- Risk classification is **delegated** to `office_control.is_risky_parameter`
  (field 1 is the sub-action) rather than duplicated — seeds must respect that
  ordering exactly.
- **Method**: 150 Claude seeds spanning each `app`, with correct field ordering.
  Cheap to get wrong and invisible until dispatch.

### 2.6 The envelope — structurally unique, highest demo value

Not an action; the wrapper every action ships inside. The plan's "Section 6.5
three clarification states" does not match the repo. The real mechanism:

- `actions[]` — run now.
- `pending_actions[]` — do **not** run until user confirms.
- `confirmation_required` + `confirmation_message`.
- **Always-pending set** (from the prompt): `close_application, shutdown,
  restart, hibernate, delete_files, move_files, edit_file, write_file,
  calendar_control|delete`.
- **The trap**: for `[C]` file actions the executor builds the spoken
  enumeration itself, so you send the action directly and must **not** set
  `confirmation_required`. Same-looking situation, opposite correct output.
- If nothing needs confirmation, **omit `pending_actions` entirely** —
  `additionalProperties: False` plus the prompt's note about "its own freedom to
  omit" means an empty array is not equivalent.
- `depends_on` + `id` on `_STEP_SCHEMA` carry multi-step chains (search →
  summarize → doc). This is the genuinely novel capability and deserves the
  largest single slice of the 500 envelope seeds.
- `mode: "conversation"` vs `"command"`, and `end_session`.

**Critical fail-closed constraint** (from `verify_gemini_head.py`):
`{"mode":"command","actions":[]}` is indistinguishable from a correct decision to
do nothing. Never emit it. Seed the refusal path as
`mode:"conversation"` + non-empty `response` + no actions.

---

## 3. Corrected sequencing

1. **Measure the hardware.** `hardware_gate.capability()` on training and
   inference boxes. If CPU-only or <8 GB VRAM, stop and re-plan — Step 3 is
   infeasible (§0.7).
2. **Wire a local inference runtime** behind `SENSEI_LOCAL_ADAPTER_PATH`, or
   accept that the self-expansion loop cannot run (§0.6). Hard prerequisite.
3. **Constrain sub-action vocabularies** (§0.5). Removes a bug class for free and
   shrinks the largest seed bucket before you pay for it.
4. **Fix `RELIABILITY_MODE`** deliberately (§0.9) — it changes what "passing"
   means and therefore what eval data you need.
5. **Stratified holdout, per action type, reserved before any training.**
6. Seed **envelope + `SUB`** first — highest structural risk and the demo
   centerpiece. Then `TEXT`, then `OPT_TEXT`, then `IGNORED`.
7. Gemini for input diversity; existing gates for filtering (§0.8); Claude judge
   on sample only.
8. **Stop after one or two self-improvement rounds.** The plan is right that more
   reinforces bias. Dedup by embedding similarity is the load-bearing check —
   collapse, not malformation, is the real self-generation failure mode.

---

## 4. Honest status

- Counts, shapes, schema, always-pending set, gate semantics: **read from the
  committed code**, reproducible via the snippet at the top.
- Budget numbers (1,650 vs 16,600): **arithmetic on those counts**, not measured
  training outcomes. No adapter has been trained; no loss curve exists.
- Whether shape-anchored seeding actually matches per-action seeding in accuracy
  is **an untested hypothesis**. It follows from the enum constraint plus the
  5-shape collapse, but the honest test is: train both on one bucket
  (`OPT_TEXT`, 11 actions, cheapest) and compare against the stratified holdout
  before committing the full budget.
- Everything in §0.6/§0.7 is a **blocker**, not a caveat. Steps 2, 3 and 5 of the
  plan cannot run today.
