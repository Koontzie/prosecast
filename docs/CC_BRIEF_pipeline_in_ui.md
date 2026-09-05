# CC BRIEF — E3: the pipeline in the UI (AI pass + alignment as jobs)

**Written 2026-09-05 for an autonomous Claude Code run in `~/dev/prosecast`, on the Mac, with Gideon reachable over Tailscale.**
**This brief has 8 steps (0–7). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

---

## Mission

After E2, a book gets from file to library without a terminal. Two steps still need one:
the AI attribution pass (`main.py "<title>" --use-existing-ir --llm-scene`) and word-level
read-along timing (`scripts/align_words.py <slug>`). Both are already importable functions
with per-scene / per-chapter checkpointing. Make them **jobs behind buttons**, on a second
worker so they never queue behind a render, with progress the user can watch and a disabled
state that says *why* when the service they need is down.

Spec: `docs/ROADMAP_PHASE_E_UI.md` → **E3**. Done means: a **Pipeline card** on the book page
shows rules ✓ → AI pass → cast → render → align → export, with **▶ Run AI pass** and **Align**
buttons, and the README's "Where the terminal is still needed" section can be deleted.

Do NOT change anything on the Chatterbox or Ollama servers, do NOT touch precious data by
hand, do NOT `git push` (Tyler reviews and pushes).

---

## Guardrails (read before touching anything)

- **GREEN (do autonomously):** edit `server.py`, `static/index.html`,
  `prosecast/scene_attributor.py`, `prosecast/cast_profiler.py`, `prosecast/word_aligner.py`,
  `main.py`; add `prosecast/pipeline.py`; add tests under `tests/`; re-run
  `scripts/refresh_ui_fixtures.py` when you change an endpoint on purpose; update `STATUS.md`
  and `HANDOFF.md` at chapter-close; make LOCAL `git commit`s as you go (no push).
- **YELLOW (ask by stopping):** any change to the render worker's write path
  (`renderer.save_ir` / `_run_one_render_job`) beyond the guard in Step 3. The
  "stale write" finding in HANDOFF is real; this brief *avoids* it rather than fixing it.
- **RED (never):** modify or delete `library/**/ir.json`, `voice_map.json`, or
  `corrections.jsonl` by hand; write `ir.json` with a plain `open(..., "w")` (always
  `lib.write_json_atomic`); hand-write anything in `tests/fixtures/`; start a render on the
  rulebook; spend money; `git push`.
- **Working tree:** clean at `main` when this was written. `git status -sb` first; if it is
  not clean, STOP and write what you found to `STATUS.md`.

## Smallest healthy-loop check (verify this before walking away)

After **Step 1**, `.venv/bin/pytest tests/ -q` must show the same pass count as before you
started plus your new `test_pipeline.py` tests (baseline on this Mac: **197 passed, 1 skipped**
— the skip is `en_core_web_sm` missing; `bash SETUP.sh` fixes it and the number becomes 201).
If the pipeline module imports and the tests are green, the loop is healthy. If `server.py`
won't import, you have STOPPED there.

---

## Step 0 — Orient (read, don't write)

Read, in this order: `CLAUDE.md` (short now), `HANDOFF.md` → "Key facts" and "Known-real, not
yet fixed", `docs/ROADMAP_PHASE_E_UI.md` → E3 and the E2 upload contract. Then in code:

- `server.py`: `_run_ingest_job` (~352) and `POST /books/ingest` (~381) — **this is the pattern
  to copy**: a job dict in `_render_jobs`, a `progress(stage, detail)` closure, a daemon thread,
  polled at `GET /render_status/{job_id}`. `_queue_worker` / `_enqueue_render` (~1549–1610) — the
  render worker you must NOT share. `setup_status()` (~1436).
- `prosecast/scene_attributor.py`: `run_scene_pass(ir_data, model, scope, confidence_threshold,
  checkpoint_path)` (~249). Note the circuit breaker (~301: aborts after repeated Ollama
  failures, progress saved) and that it **checkpoints with a plain `open(..., "w")` (~335)** —
  Step 1 fixes that.
- `prosecast/cast_profiler.py`: `run_profile_pass(ir_data, model, confidence_threshold,
  reprofile, checkpoint_path)` (~178).
- `prosecast/word_aligner.py`: `align_chapter(book_slug, chapter_index, ...)` (~201),
  `chapter_blocks_fingerprint` (~191), `STALE_TOLERANCE_SECS`; and `scripts/align_words.py`
  `_needs_alignment` (~33) — the staleness rule the UI will show.
- `main.py` ~290–310: how the CLI calls the scene pass today, including the **plain
  `json.dump` write of `ir.json` afterward** — Step 1 fixes that too.
- `prosecast/setup_probe.py`: `probe_ollama` / `probe_whisper` — the buttons' enabled state
  comes from these, not from a fresh probe you write.
- `static/index.html`: `pollIngest` (~3585) and `pollRenderStatus` (~3720) — reuse one; the
  book header's render/export buttons (~1750) — the Pipeline card goes beside them.

### Four traps in this specific code

1. **Two writers, one `ir.json`.** The render worker loads an IR snapshot and writes the whole
   document back after every block. If an AI pass writes `ir.json` while a render of the same
   book is running, one of them silently loses. E3 does not fix that (it's a HANDOFF finding
   with its own plan); E3 **refuses the overlap** — Step 3.
2. **`run_scene_pass` mutates `ir_data` in place and returns it.** Reload from disk after the
   job; do not keep the pre-pass dict around and write *that*.
3. **The LLM model name.** `main.py` now defaults `--llm-model` to `config.get("ollama_model")`
   (fixed 2026-09-05). The job must do the same — never hard-code `llama3.2`.
4. **Alignment needs the block WAVs, which `renders/chN_blocks/` holds only after a Chatterbox
   render.** A chapter rendered on `say` has no per-block files to align; `align_chapter`
   must report "nothing to align" for it, not crash, and the UI must not offer the button.

---

## Step 1 — `prosecast/pipeline.py`: the job functions, no HTTP yet

Create `prosecast/pipeline.py` with two functions that the server will wrap:

```python
def run_ai_pass(slug: str, *, scope: str, model: str | None, profile: bool,
                on_progress: Callable[[str, str, int, int], None]) -> dict
def run_align(slug: str, chapters: list[int] | None, *, force: bool,
              on_progress: Callable[[str, str, int, int], None]) -> dict
```

`on_progress(stage, detail, done, total)`. Stages for the AI pass: `loading → attributing
(scenes done/total) → profiling (characters done/total) → saving → done`; for align:
`aligning (chapters done/total) → done`.

- Add an optional `on_progress` parameter to `run_scene_pass` and `run_profile_pass` (default
  `None`, called per scene / per character). Keep their signatures otherwise unchanged so
  `main.py` still works.
- Replace the plain-`open` checkpoint write in `run_scene_pass` (~335) and the `json.dump` in
  `main.py` (~305) with `lib.write_json_atomic`. That is the RED rule; it has been violated in
  these two places since before the rule existed.
- `run_ai_pass` returns `{"targets": n, "resolved": n, "unresolved_after": n, "aborted": bool,
  "abort_reason": str | None}` — the breaker's abort must surface as data, not a log line.
- `run_align` skips chapters whose timings are fresh unless `force`, reports skipped ones,
  and returns `{"aligned": [...], "skipped_fresh": [...], "no_blocks": [...]}`.
- Write `library/<slug>/pipeline_state.json` (advisory, like `render_state.json`) via
  `write_json_atomic` at each stage change: `{job_id, kind, stage, detail, done, total,
  started, updated, result?}`.

**Tests (`tests/test_pipeline.py`):** with Ollama and whisper mocked (patch `_call_ollama` /
`transcribe_wav`), assert: progress callbacks fire with the right shape; abort → `aborted:
True` with reason; align skips fresh timings and reports `no_blocks` for a `say`-rendered
chapter; **both writes are atomic** (patch `write_json_atomic` and assert it was called;
assert no `open(..., "w")` on the IR path — a `monkeypatch` on `builtins.open` that fails on
write mode for that path is the cheap way).

Commit: `E3.1: pipeline.py — AI pass and align as callable jobs with progress`.

---

## Step 2 — Server: a second worker and three endpoints

- A **`pipeline` worker**: its own FIFO queue and daemon thread, same shape as
  `_queue_worker`, jobs stored in the same `_render_jobs` table (so `GET /render_status/{id}`
  serves them with `kind: "ai_pass"` / `kind: "align"`, `stage`, `detail`, `done`, `total`).
  One pipeline job at a time; a second request for the same slug while one is queued or
  running returns the existing `job_id` rather than a duplicate.
- `POST /pipeline/{slug}/ai_pass` body `{scope: "unresolved"|"low-confidence"|"all",
  profile: bool = true}` → `{job_id}`. Model comes from config. **Refuse with 409 and the
  probe's `fix` text when `probe_ollama()` is not ok** — the button is disabled in the UI,
  but the server is the one that must not silently do nothing.
- `POST /pipeline/{slug}/align` body `{chapters: [int] | null, force: bool}` → `{job_id}`.
  409 with the whisper probe's `fix` when whisper is down.
- `GET /pipeline/{slug}` → `{ai_pass: {last_run, unresolved, ...from pipeline_state},
  align: {per_chapter: [{index, state: "fresh"|"stale"|"none"|"no_blocks"}]}, ollama_ok,
  whisper_ok, running_job_id}`. This is what the card renders from — one call.
- After a chapter render finishes on the render worker, **enqueue an align job for that
  chapter automatically if `probe_whisper()` is ok** (spec: "auto-chained"). Enqueue, don't
  run inline — the render worker must not call whisper.

**Tests (`tests/test_pipeline_api.py`, `TestClient`, probes patched):** 409 when Ollama is
down and the body carries the fix text; enqueue returns a job id and `/render_status` shows
`kind: ai_pass`; duplicate request returns the same id; `GET /pipeline/{slug}` shape; align
auto-chains after a render only when `whisper_ok`.

Then **`python scripts/refresh_ui_fixtures.py`** and commit the new
`tests/fixtures/pipeline_*.json` it produces — never write them by hand.

Commit: `E3.2: pipeline worker + /pipeline endpoints; align auto-chains after render`.

---

## Step 3 — The overlap guard (the trap that loses corrections)

In `_enqueue_render`: if a pipeline job for the same slug is queued or running, return 409
`"An AI pass is running on this book — render when it finishes."` In the pipeline enqueue: if
a render for the same slug is queued or running, 409 `"A render is running on this book — the
AI pass would fight it for ir.json. Try again when the render finishes."`

This is deliberately blunt. The proper fix (render worker merges only the fields it owns) is
in HANDOFF as its own item; do not attempt it here.

Test both directions. Commit: `E3.3: render and AI pass refuse to overlap on one book`.

---

## Step 4 — The Pipeline card (`static/index.html`)

On the book page, beside the render/export buttons, a card with six stages in a row:
**Rules ✓ → AI pass → Cast → Render → Align → Export**. Each stage is a plaque in the existing
teal/amber/red language (`suPlaque` is the pattern).

- **AI pass**: shows `unresolved` count and last run. Button **▶ Run AI pass** with a scope
  selector (unresolved / low-confidence / all; *all* shows the provenance warning from the CLI
  help text). Disabled with the reason inline when `ollama_ok` is false: *"Ollama isn't
  reachable — open Setup"* with a link that opens the Setup view. While running: progress bar
  from `done/total`, stage text ("attributing · scene 41 of 120"). Abort → amber plaque with
  the reason from the job result, not an alert.
- **Align**: per-chapter state chips (fresh / stale / none / no blocks) in the chapter list,
  and one **Align** button on the card that aligns everything stale-or-none. Disabled with
  reason when whisper is down; hidden entirely for chapters with `no_blocks`. When auto-chain
  is on, the card says so ("aligns automatically after each render").
- Reuse `pollRenderStatus`; do not add a third poller.
- Both skins. **Remember the On Air trap** (HANDOFF): to test classic, set
  `localStorage['prosecast-theme']` via `add_init_script` before navigation.

Then add **`tests/ui/check_pipeline_card.py`**, modelled on `check_ingest_wizard.py`, driven
by the fixtures from Step 2: disabled-with-reason states, running state, abort state, both
skins, no page errors. Run all three `tests/ui/` checks (Playwright is installed on this Mac?
If not: `pip install playwright && playwright install chromium` in the venv).

Commit: `E3.4: Pipeline card — AI pass and align buttons with honest disabled states`.

---

## Step 5 — Run it for real, once, on the sample book

This is the step a container cannot do and the reason this brief is on the Mac.

1. `curl -s http://$(python3 -c 'import json;print(json.load(open("config.json"))["ollama_url"].split("//")[1])')/api/tags | head -c 300` — Ollama answers and lists `gemma3:12b`.
2. Start the server, open the sample book (or `brigands___breadknives`, which has real
   unresolved lines — **not** the rulebook, **not** Parade), click **▶ Run AI pass** with scope
   *unresolved*, watch the progress bar move, and confirm the unresolved count on the chapter
   badge drops when it finishes.
3. Render one short chapter on Chatterbox, confirm an align job appears automatically and the
   chapter's chip turns *fresh*; open the reader and confirm words light up individually.
4. Kill Ollama's reachability (wrong port in Setup, save) and confirm the button disables with
   the reason and `POST` returns 409. Put it back.

Write what you saw — numbers, timings, anything surprising — into `STATUS.md`. If step 2 or 3
did not behave, STOP there and record it; do not paper over it in the UI.

---

## Step 6 — Retire the terminal instructions

- `README.md`: delete the **"Where the terminal is still needed"** section; remove the "Two
  steps … are still terminal commands" sentence from the status box; in Rung 3, replace the
  "how you know it worked" with the Pipeline card's green states.
- `CLAUDE.md` → CLI section: the two commands stay (they still work) but are labelled
  "also available in the UI (E3)". Phase table: E3 → ✓.
- `docs/ROADMAP_PHASE_E_UI.md` → E3: add an "As built" paragraph at the top of the section,
  the way E2.4 has one, noting any deviation from the spec (there will be at least one: the
  overlap guard).

Commit: `E3.5: docs — the terminal is optional now`.

---

## Step 7 — Chapter-close handoff

1. `.venv/bin/pytest tests/ -q` green; all three `tests/ui/` checks green.
2. `STATUS.md`: new entry at the top, `Session 2026-MM-DD (Claude Code) — E3: pipeline in the
   UI`, in the house style (what shipped, what the real run showed, what is still Tyler's to
   verify). Status line at the top → next is the cast exchange or the HANDOFF findings, per
   Tyler.
3. `HANDOFF.md`: update the phase table (E3 ✓), the "Where to start" section, and add to "Key
   facts": the pipeline worker, the overlap guard and why it is blunt, the atomic-write fix in
   `run_scene_pass`, the `no_blocks` align state.
4. `git status -sb` clean, all commits local. **Do not push** — Tyler reviews and pushes.
5. Print the STATUS entry to the console as your last output.

## What you are explicitly NOT doing (leave for Tyler / later)

- Fixing the render worker's whole-document write (HANDOFF finding). E3 guards; it does not fix.
- Re-keying audio by `segmentId` or adding tags/model to the cache key (HANDOFF; both together, once).
- Wiring emotion tags into the ElevenLabs call (Phase 4c).
- The Voices tab (`docs/CC_BRIEF_voices_tab.md`), the rulebook overnight render, cover art.
- Anything to do with the cast exchange — that is a design session, not a build.

END OF BRIEF
