# CC BRIEF — E6: the first-run wizard (setup as steps, ending in sound)

**Written 2026-09-06 for an autonomous Claude Code run in `~/dev/prosecast`, on the Mac.**
**This brief has 7 steps (0–6). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

---

## Mission

Today a new user's first run lands on the Setup page: a probe table with an intro paragraph,
four engine cards and a save button. It is honest and complete, and it is still a table. Nobody
hears anything until they find "+ Add Book" on their own.

Build a **stepped first-run wizard** that shows one decision at a time and **ends with the
user hearing a voice**: pick an engine → prove it works → (optionally) add the AI services →
render one chapter of the built-in sample book and play it. The Setup page stays exactly what
it is — the power-user probe table — and gains one button: **↻ Run setup again**.

Done means: delete `config.json`, start the server, and a person who has never seen ProseCast
is listening to the sample book on `say` within five minutes without reading the README.

Decisions already made by Tyler (do not re-open): overlay on first run + relaunch button, NOT
a rewrite of the Setup page; one skippable probe-only step for Ollama / whisper / ElevenLabs;
the last step renders and plays the sample book.

Do NOT `git push` (Tyler reviews and pushes). Do NOT spend money (an ElevenLabs render of the
sample book costs credits — the wizard's final step must warn and require a click if the
chosen engine is `elevenlabs`).

---

## Guardrails (read before touching anything)

- **GREEN (do autonomously):** edit `server.py`, `static/index.html`, `README.md`,
  `CLAUDE.md`; add `tests/test_sample_book.py`, `tests/ui/check_first_run.py`, a fixture via
  `scripts/refresh_ui_fixtures.py`; update `STATUS.md` and `HANDOFF.md` at chapter-close;
  LOCAL `git commit`s as you go (no push).
- **YELLOW (do carefully, exactly as written):** Step 5 moves Tyler's real `config.json`
  aside to simulate a first run. `cp config.json config.json.e6bak` FIRST, and the step is not
  finished until `diff config.json config.json.e6bak` is empty and the backup is deleted.
- **RED (never):** modify or delete anything under `library/**` by hand (the sample book is
  created and re-created only through the endpoint you build); render any book other than
  `sample_book` during this brief; write `ir.json` with a plain `open(..., "w")`
  (`lib.write_json_atomic`, always — `tests/test_pipeline.py` enforces it); hand-write
  anything in `tests/fixtures/`; put a real host/IP/user in a tracked file (the history was
  rewritten to remove them — placeholders are `GIDEON_HOST`, `192.168.1.50`, `/Users/YOUR_USER`);
  `git push`.
- **Working tree:** expected clean at `main`, **6 commits ahead of origin** (E3, unpushed —
  that is normal). `git status -sb` first; if there are modified files, STOP and write what
  you found to `STATUS.md`.

## Smallest healthy-loop check (verify this before walking away)

After **Step 1**, `.venv/bin/pytest tests/ -q` must show the baseline **plus** your new
`test_sample_book.py` tests. Baseline on this Mac: **231 passed, 1 skipped** (235 / 0 if
`bash SETUP.sh` has been run; 6 more skip without tesseract — skips are healthy). If `server.py`
imports and the count went up, the loop is healthy. If it went down, you have STOPPED there.

---

## Step 0 — Orient (read, don't write)

Read, in this order: `CLAUDE.md`, `HANDOFF.md` → "Key facts" (especially *Config*, *Setup
probes*, *The upload contract*, *The wizard*), `docs/ROADMAP_PHASE_E_UI.md` → E4.3. Then in code:

- `server.py`: `POST /books/upload` (~293) + `_run_ingest_job` (~356) + `POST /books/ingest`
  (~384) — **the ingest-as-job pattern to reuse** for the sample book; `GET /setup/status`
  (~1439) and `PUT /config` (~1425); `POST /render/{slug}/{chapter}` (~1617) and
  `/render_status/{job_id}` (~1643).
- `prosecast/setup_probe.py`: `probe_voice_engine` — the `say` / `piper` / `chatterbox` /
  `elevenlabs` / `stub` branches and what each row's `fix` sentence says. `status()` returns
  `{ready, rows, os, config_exists, shadowed_by_env}`.
- `prosecast/book_parser.py`: `write_sample_book(path)` + `SAMPLE_TEXT` — the built-in sample.
  It is currently reachable only from `main.py --sample`. `library/` and `books/` are
  gitignored, so **a fresh clone has no sample book until something writes it.**
- `static/index.html`: `loadSetupChip()` (~2420) — the line
  `if (!st.config_exists && !isSetupOpen()) openSetupView();` **is the first-run hook you are
  replacing**; `renderSetup()` (~2502) — the engine cards and `suPickEngine`, `suValue`,
  `setupDirty`, the save path; `openIngestWizard` / `closeIngestWizard` (~3573) — the modal
  pattern (`.modal-overlay.hidden`, footer reset on open); `pollRenderStatus` — reuse it.
- `tests/ui/check_ingest_wizard.py` + `scripts/refresh_ui_fixtures.py` — the headless-check
  pattern: real fixtures generated from real endpoints, a tiny HTTP server, Playwright, both
  skins. `tests/test_ingest.py` fails if a fixture drifts from its endpoint. Copy this shape.

Write nothing in this step.

---

## Step 1 — Server: the sample book as an endpoint

Add **`POST /books/sample`** to `server.py`:

- If `library/sample_book/ir.json` already exists → `200 {slug: "sample_book", exists: true,
  chapters: N}`. No work, no job. Idempotent.
- Otherwise: `write_sample_book(BOOKS_DIR / "sample_book.txt")`, then run the **same ingest
  job path** `/books/ingest` uses (own daemon thread, not the render queue), mode `novel`,
  rules-only attribution (no LLM — the wizard must work on rung 1 with nothing but `say`).
  Return `{slug: "sample_book", exists: false, job_id}`; the job is polled at
  `/render_status/{job_id}` with `kind: "ingest"` like any upload.
- Do not add a new job table, a new poller, or a new thread model. If `_run_ingest_job` needs
  a small refactor to accept a local path instead of an `upload_id` entry, do that refactor
  (it is GREEN) and keep `/books/ingest` behaviour byte-identical.

Tests → `tests/test_sample_book.py` (use the same temp-library fixture the other tests use):
first call creates + returns a job_id; the job finishes with `ir.json` present and ≥ 2
chapters; second call returns `exists: true` with no job; `ir.json` was written atomically
(reuse the `open`-spy pattern from `test_pipeline.py`).

Then: `.venv/bin/python scripts/refresh_ui_fixtures.py` so a **`tests/fixtures/sample_book.json`**
exists for the UI check, plus **`setup_status_firstrun.json`** (probe output with no config —
`PROSECAST_CONFIG` pointed at a missing file, engine `auto`) if the script does not already
produce a first-run shape. Add the drift assertion for each new fixture the way
`test_ingest.py` does it.

**Healthy-loop check here.** `git commit -m "E6.1: POST /books/sample — the built-in sample as an ingest job"`.

---

## Step 2 — UI: the wizard overlay

One new `.modal-overlay` (`#firstrun-modal-overlay`), same open/close/reset discipline as the
ingest wizard. A stepper header (1 · 2 · 3 · 4), one step visible at a time, **Back / Continue**
footer, and a quiet **"Skip — take me to Setup"** link on every step (the wizard must never
trap someone; skipping opens the existing Setup page). **Esc = the same skip.** Both skins;
On Air uses the existing tokens, nothing new.

Wire it: in `loadSetupChip()`, replace the first-run `openSetupView()` with
`openFirstRun()`. Add **`↻ Run setup again`** next to `#su-reprobe` on the Setup page; it
opens the same overlay at step 1 with the current config pre-filled.

**Step 1 — "How should ProseCast speak?"**
The four engine cards, reused (extract the card builder out of `renderSetup()` into a
function both callers use — do not duplicate the markup). Pre-select the OS default
(`say` on Darwin, `piper` elsewhere — the server already reports `st.os`). Picking
`chatterbox` reveals the URL field; picking `elevenlabs` reveals the key field **and the
existing disclosure block verbatim** (it is a compliance requirement — same words as the
Setup page and README, not a paraphrase). Continue = `PUT /config` with just the keys this
step owns, then advance. `auto` is not offered.

**Step 2 — "Can it speak?"**
Call `/setup/status` and show only two rows from it: `voice_engine` and `tool_ffmpeg`,
rendered with their own `detail` and `fix` sentences (the probe's words, never yours). A
**Check again** button. Continue is disabled until `voice_engine.ok`; the disabled reason is
the row's `fix`. Show a "the full list is on the Setup page" link for the curious.

**Step 3 — "Optional: give it a brain" (skippable)**
Three groups with a one-line pitch each and a URL/model/key field: Ollama (who's speaking in
hard scenes), whisper (words light up as they're read), ElevenLabs key (a few premium
voices). **Skip** is the primary button if all three are absent; **Save & check** probes and
paints the three rows green/amber inline, then Continue. Nothing here blocks progress.

**Step 4 — "Hear it."**
One button: **▶ Read me the sample**. On click, in order, with a single progress sentence
driven by the job's `stage`/`detail` (`preparing the sample book… → reading it… → rendering
chapter 1 · 12 of 31 blocks…`): `POST /books/sample` → poll ingest if a job came back →
`POST /render/sample_book/0` → poll → refresh the book list → open the book → play chapter 0
→ close the wizard. **If the engine is `elevenlabs`, the button first says what it will cost
in plain words ("about N characters of your ElevenLabs credits") and needs a second click.**
If anything fails, the sentence turns into the error and offers **Try again** and **Open
Setup** — never a silent stop (PRODUCT_NOTES' named failure).

Keep the JS state in one object (`fr = {step, engine, …}`); reset it on open. Reuse
`fetchJSON`, `pollRenderStatus`, `esc`. The `.hidden` rule lesson from E2.3 applies: check
that every step section is actually hidden in both skins, not just the overlay.

`git commit -m "E6.2: first-run wizard overlay — engine, probe, optional brains, hear the sample"`.

---

## Step 3 — Headless check: `tests/ui/check_first_run.py`

Same shape as `check_ingest_wizard.py`: fixtures only, tiny HTTP server, Playwright, **both
skins**, a `check()` per assertion, exit 1 on any failure, screenshots `firstrun_*.png` (they
are gitignored). Mock the API from the generated fixtures (`setup_status_firstrun.json`,
`pipeline_offline.json`/`pipeline_ready.json` as needed, `sample_book.json`) — no
hand-written response bodies.

Assert at least: the overlay opens when `config_exists` is false and NOT when true; step 1
pre-selects `say` when `os: "Darwin"` and `piper` otherwise; the ElevenLabs disclosure text
appears only when that card is picked; step 2 Continue is disabled with the row's `fix` text
while `voice_engine.ok` is false and enabled when the "ready" fixture is served; step 3 Skip
advances; step 4 button issues `POST /books/sample` then `POST /render/sample_book/0`
(intercept and record the request order); Esc / Skip lands on `#setup-view`; `↻ Run setup
again` on the Setup page re-opens the overlay at step 1; every non-current step is hidden in
both skins.

Run all four `tests/ui/` checks — the three existing ones must still pass. `git commit -m
"E6.3: headless first-run check, both skins"`.

---

## Step 4 — Docs (the README is a contract)

- `README.md`: wherever it says the first run "lands on Setup" / "opens the Setup page", it
  now says the first run **opens a short setup wizard that ends by reading you the sample
  book**, and that the Setup page (⚙) is where every service is listed. Rung 1's "within ten
  minutes" sentence can now point at the wizard.
- `CLAUDE.md` line ~86 (`# the app; first run lands on Setup`) — same correction.
- `HANDOFF.md` → "Key facts": add a short **"The first-run wizard (new, 09-06)"** paragraph:
  the hook in `loadSetupChip`, the shared engine-card builder, `POST /books/sample` being the
  only way the sample book is created, and that the wizard is fixture-checked not
  pytest-checked.

`git commit -m "E6.4: docs — first run is a wizard that ends in sound"`.

---

## Step 5 — The real run (YELLOW — follow exactly)

```
cp config.json config.json.e6bak          # Tyler's real Gideon URLs live here
mv config.json /tmp/prosecast_config_aside.json
.venv/bin/uvicorn server:app --port 8000
```
Open `http://127.0.0.1:8000` in a browser (Playwright headed, or tell Tyler to). Walk the
wizard as a stranger on rung 1: `say` → Check → Skip → ▶ Read me the sample. Record in
`STATUS.md`: seconds from click to first audio, whether the progress sentence ever went blank,
and anything you had to already know to get through. Then **Run setup again** from the Setup
page and confirm it re-opens pre-filled.

Then, and only then:
```
mv /tmp/prosecast_config_aside.json config.json
diff config.json config.json.e6bak && rm config.json.e6bak && echo RESTORED
```
If the diff is not empty, STOP: restore from the `.e6bak`, write what happened to `STATUS.md`.
Do not run the wizard against Chatterbox on Gideon unless Tyler is present — a stray render is
harmless but the GPU may be busy with something of his.

---

## Step 6 — Chapter-close

- `STATUS.md`: new session entry "2026-09-06 (Claude Code, Mac) — E6: the first-run wizard"
  in the house style (Shipped / The real run / Things only the real run showed / Still Tyler's
  to verify), and update the header status line + `Updated:` date. Test counts before/after.
- `HANDOFF.md`: phase table gets an **E6** row; "Where to start" now says the wizard is done
  and the cast exchange design is next; leave the four findings untouched.
- Final `.venv/bin/pytest tests/ -q` and all four `tests/ui/` checks green.
- `git commit -m "E6.5: chapter-close — STATUS/HANDOFF for the first-run wizard"`.
- `git status -sb` must be clean and read `[ahead N]`. **Do not push.**

END OF BRIEF
