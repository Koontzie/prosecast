# ProseCast — Session Handoff (2026-09-06)

For the next Claude/CC session: read this + `STATUS.md`, then pick up at
**"Where to start"**. Supersedes the 09-05 handoffs.

Repo: `Koontzie/prosecast`, branch `main`. **The history was rewritten on
2026-09-05** (`git filter-repo`, home-network host / NAS user / Mac path /
gmail author scrubbed) and force-pushed; every commit hash from before this
session changed, so hashes quoted in older STATUS entries no longer resolve.
**CLAIY's clone must be re-cloned, not pulled.** Tests on the Mac: **245 passed,
1 skipped** (231 before E6, 197 before E3) — the skip is `en_core_web_sm`
missing from the venv; `bash SETUP.sh` installs and verifies it, after which the
number is 249. Without tesseract a further 6 skip. Skips are healthy, not
regressions. There are now **four** `tests/ui/` checks, and Playwright +
chromium are installed in the Mac venv.

---

## Where the project stands

The original goal is **met** and the repo is **publishable**: EPUB, TXT and PDF
(novels, rulebooks, plays, scans) narrate end-to-end with multi-voice casting,
whole-book resumable renders and word-accurate read-along — **every step in the
UI**. Phase E ("UI-first") is complete as of E3 on 2026-09-05, and since E6 on
2026-09-06 the first run walks a stranger to the sound of a voice without a
README. **E3 is pushed; E6's commits are local — Tyler reviews and pushes.**

| Phase | What | State |
|---|---|---|
| A–D | Chatterbox backend, cast screen, safe whole-book render, read-along | ✓ shipped |
| E1 | Full-page reader view | ✓ 09-03 |
| E4.1–E4.3 | `config.json`, `/setup/status` probes, Setup page, EL affiliate compliance | ✓ 09-03 |
| E2.1–E2.4 | Upload-as-job, PDF ingest on PyMuPDF, ingest wizard, OCR for scans | ✓ 09-04 |
| **E5** | README, `SETUP.sh`, `docs/PHILOSOPHY.md`, history scrub, `CLAUDE.md` refresh | **✓ 09-05** |
| **E3** | **Pipeline-in-UI: AI pass + align as jobs on a second worker, Pipeline card** | **✓ 09-05** |
| **E6** | **First-run wizard: engine → probe → optional brains → hears the sample book** | **✓ 09-06 (local commits)** |

Specs: `docs/ROADMAP_PHASE_E_UI.md`. The public-facing story is now
`README.md` and `docs/PHILOSOPHY.md`; keep them true when things change.

---

## What happened on 09-05 (one long chapter, all committed; push pending Tyler)

1. **History audit and rewrite.** Clean of secrets and copyrighted files; not
   clean of the Tailscale IP (1,564×), the NAS `user@host` pair (121×),
   the Mac home path (54×), gmail author (21 commits). Current tree scrubbed
   with a placeholder table, then Tyler ran `filter-repo` + mailmap from a real
   terminal, Codex's `refs/codex/*` deleted, `gc --prune=now`, force-push.
   `backup_library.sh` now reads its target from `.backup/dest`.
2. **README** with banner (rendered from the On Air theme tokens —
   `docs/assets/prosecast-banner.png`), ladder, three install paths, "How this
   was built", Ko-fi, and the ElevenLabs affiliate link with its disclosure.
3. **PHILOSOPHY.md** — the voice-actor answer and the cast exchange as a
   direction. Tyler-edited; approved.
4. **SETUP.sh** verifies every step; **CLAUDE.md** is no longer a trap;
   **poppler row** removed from Setup; **`--llm-model`** now defaults to config.
5. **`docs/CC_BRIEF_pipeline_in_ui.md`** — E3, ready to run.

---

## Where to start

**The plan Tyler approved, in order:** publish → ElevenLabs application → E3 →
cast exchange design → the four findings below. The first three are done, and
E6 (the first-run wizard, 09-06) is done on top of them; **the cast exchange is
next**. Of the four findings, **the render worker's
whole-document write is now the one to do first** — E3 guards around it with a
blunt 409, and that guard can be relaxed the moment the merge fix lands.

- **If Tyler has not yet flipped the repo public:** nothing for a session to
  do first — he flips it, submits the application with the URL, and tests the
  README on the gaming laptop (rungs 1–2). Anything the laptop test turns up
  is a README/SETUP fix, small and Cowork-able.
- **ElevenLabs affiliate** is approved and the link is in the README, the app
  and `docs/elevenlabs-setup.md`, each with the disclosure beside it. Nothing
  to do unless a new surface (the launch video, the website) shows the link —
  then the same disclosure + attribution rules apply.
- **E3 is done** (09-05, Claude Code on the Mac, verified against Gideon —
  see the STATUS entry for the numbers). What is left of it is Tyler's to
  check: the card against a **large** book (Parade, 115 chapters — the sample
  book has one scene and cannot exercise a long run), whether a pass that runs
  for tens of minutes wants a **cancel** button, and the overlap guard's
  wording in practice.
- **E6 is done** (09-06, Claude Code on the Mac — see the STATUS entry). The
  first run opens a wizard that ends by playing the sample book: 15.7 s from
  the button to audio, on `say`, on a library that had never existed. What is
  left of it is Tyler's: the wizard on a **non-Mac** (Piper), the **ElevenLabs**
  path end to end (its two-click cost warning was checked; no credit was spent),
  and the one real gap — **`SETUP.sh` writes a `config.json`, so on the
  documented install path the wizard never fires by itself**. ↻ Run setup again
  is the way in and the README says so, but if the wizard is meant to greet
  every new user, `SETUP.sh` should stop writing that file (or write it without
  a `tts_engine`). `SETUP.sh` was outside the brief's green list, so it was left
  alone.
- **Cast exchange** — a design session, not a build. PHILOSOPHY.md's
  "Sharing casts and voices" section is the spec-of-record for what it must
  be; the one code prerequisite it names is re-keying shared corrections by a
  text hash rather than segment number.

Still open from earlier phases: the **rulebook overnight render**, the **C4
voice-ref mirror**, the **Voices tab** (`docs/CC_BRIEF_voices_tab.md`),
**auditioning the 20 LibriVox US voices**, and **a real scanned PDF end to end**.

---

## Known-real, not yet fixed (from the 09-04 Codex review)

All six findings were checked against the code; these four survived and are
worth doing in roughly this order. None is urgent. **E3's brief deliberately
guards around the second one rather than fixing it.**

* **ElevenLabs never receives the emotion tags.** `tag_mapper` supports EL, but
  `synthesize()` calls `_synthesize_elevenlabs(text, voice_cfg, out_path)`
  without `tags`. Phase 4c work.
* **A correction made during a render can be silently overwritten.** The queue
  loads one IR snapshot per job and `renderer.save_ir()` writes that snapshot
  back after every block, while PATCH endpoints read-modify-write independently.
  **The surgical fix is to have the render worker re-read and merge only the
  fields it owns (`audioVariants`, `cacheKey`)** — not a repository-with-locking
  refactor. Until then, E3 makes render and AI pass refuse to overlap on a book.
* **Audio is keyed by list position, not `segmentId`.** `merge_next` shifts
  every following block, so the timeline and the aligner read `block_{i}.wav`
  files that belong to different blocks.
* **The render cache key ignores tags, model and backend.** Do this together
  with the `segmentId` change — both alter how audio files are identified, and
  each costs a full re-render of the library. Pay that once.

Fixed 09-05 in E3: the plain-`open` writes of `ir.json` are gone.
`scene_attributor.run_scene_pass`'s checkpoint, `cast_profiler`'s checkpoint
and **all five** of `main.py`'s writes now go through `lib.write_json_atomic`,
and `tests/test_pipeline.py` fails if a plain write of `ir.json` comes back.

---
## Key facts (hard-won — do not relearn)

**Placeholders (09-05).** Tracked files say `GIDEON_HOST`, `NAS_USER`,
`/Users/YOUR_USER`, `192.168.1.50`. The real values live only in `config.json`
(gitignored) and `.backup/dest` (gitignored). Never put the real host back into
a tracked file — the history was rewritten specifically to remove it.

**The first-run wizard (new, 09-06).** `#firstrun-modal-overlay` in
`static/index.html`. The hook is one line in `loadSetupChip()`: no
`config.json` → `openFirstRun()` instead of the old `openSetupView()`. Four
steps — engine, "can it speak?", optional brains, hear it — and the last one
calls **`POST /books/sample`**, which is the ONLY way the sample book is ever
created (`library/` and `books/` are gitignored, so a fresh clone has none);
it is idempotent and runs the same ingest job `/books/ingest` runs, on its own
thread. The engine cards, the field each reveals and the **ElevenLabs
disclosure** come from shared builders (`engineCardsHTML`, `engineFieldsHTML`,
`elDisclosureHTML`) that the Setup page and the wizard both call — the
disclosure is a compliance requirement and a second copy would drift into a
paraphrase. The Setup page is otherwise untouched and gained one button,
**↻ Run setup again**. Every step section carries its own `.fr-hidden` rule
(the `.hidden` trap below, again). The wizard is **fixture-checked, not
pytest-checked**: `tests/ui/check_first_run.py` drives it in both skins from
generated fixtures; `tests/test_sample_book.py` covers the endpoint and fails
if a fixture drifts. **Known gap:** `SETUP.sh` writes a `config.json`, so
after the documented install the wizard does not open by itself — ↻ Run setup
again is the way in, and whether SETUP.sh should stop doing that is Tyler's
call.

**The README is a contract (09-05).** It promises: ffmpeg required, tesseract
scans-only, poppler not needed, Python 3.11+, `SETUP.sh` verifies each step,
first run lands on Setup, `main.py --llm-model` defaults to the configured
model. If code changes make any of those false, change the README in the same
commit.

**Config (new, 09-03).** `prosecast/config.py` resolves *defaults <
`config.json` < env vars*. `config.json` is gitignored and holds Tyler's
Gideon URLs (chatterbox 8101, ollama 11434, whisper 8100, comfyui 8188).
**The hard-coded Gideon IPs that used to be defaults in `tts_engine.py` and
`preflight.py` are gone — defaults are localhost everywhere now.** If
`config.json` is deleted, ProseCast will look for Chatterbox on localhost
and report "not responding"; copy `config.example.json` and re-add the IPs.
`PUT /config` drops the cached engine, same as `/engine_status/recheck`.

**Setup probes.** `GET /setup/status` returns one row per service
(`{ok, state, detail, fix, optional}`) and is what the ⚙ Setup page renders.
Probes run in parallel. `ready` = all non-optional rows ok. Reads config at
call time, so save-then-reprobe works without a restart — but the render and
LLM modules resolve their URLs at import, so *those* pick up a changed URL on
the next server start.

**PDFs (new, 09-04).** `prosecast/pdf_ingest.py` on **PyMuPDF**, not
pdftotext. Chapter detection: bookmarks → printed contents page → font-size
headings → fixed page split, each labelled with its `source` so the UI can
say how much to trust it. Watermarks/running heads/page numbers are removed
**generically** — "a line that repeats on ≥35% of sampled pages in the
top/bottom 12% zone, or ≥60% anywhere if short" — no per-book regex. Verified
on the real Carl rulebook: 650pp, 15 bookmarks, and it caught the Renegade
watermark *including its per-page date stamp* (digits normalise to `#`).
**Open question for the review screen:** the hand-written
`scripts/toc_carl_core.json` starts "Gamemastering the Dungeon" at p236; the
PDF's own bookmark puts "Chapter 5: Running the Game" at p251. The bookmark
is probably right and the hand TOC split mid-chapter — Tyler decides on the
review screen, the code should not.

**The upload contract (new, 09-04).** Two steps, on purpose: `POST
/books/upload` saves the file and returns `{upload_id, format, title, slug,
guess_mode, guess_reason, modes, is_scan, scan, detection}` **without
ingesting**; `POST /books/ingest {upload_id, mode?, title?, chapters?,
keep_tables?, ocr?}` returns a `job_id` polled at `/render_status/{job_id}`
(`kind: "ingest"`, `stage`, `detail`; stages `extracting → chapters →
attributing → done`). Ingest runs on its **own daemon thread, not the render
queue** — it is CPU-bound and GPU-free, and a new upload must never sit behind
an overnight render. Uploads are held in an in-memory dict (last 40), so an
`upload_id` does not survive a server restart: the UI's answer to a 404 there is
"add the file again", not a retry. A scan is refused at `/books/ingest` only if
`ocr` was not asked for, or if tesseract is missing — in which case the refusal
carries the install line.

**The wizard (new, 09-04).** `+ Add Book` takes `.epub/.txt/.pdf` and opens one
modal: editable title, three mode cards pre-selected by the server's guess with
the guess's *reason* shown, and for PDFs the detected split as a tick-list. Two
things a rewrite must preserve. The chapter review states **where the split came
from** (`detection.note`) and **how far to trust it** in words per source —
bookmarks "usually right", printed TOC "page numbers are estimated", headings
"look for anything that is not really a chapter", fallback "just a fixed page
split". And the reviewed list is what `/books/ingest` actually receives; it is
not decoration. The E2.1 bridge is gone.

**OCR (new, 09-04).** `prosecast/ocr.py`. **PyMuPDF rasterizes
(`get_pixmap(dpi=300)`), not `pdftoppm`** — the roadmap called for poppler, E2.2
had just removed that dependency, so this deliberately does not bring it back.
tesseract is the only external binary. **OCR text goes through
`pdf_ingest.reflow()` before `book_parser` sees it**: tesseract breaks lines
where the *image* did, and left alone every one becomes a TTS block boundary and
the narration stutters mid-sentence. Chapter headings survive reflow and are
picked up as chapter titles rather than read aloud. Cached at
`books/<stem>_ocr.txt`, reused unless the PDF is newer. A scan that OCRs to
almost nothing raises rather than producing an empty book.

**The pipeline worker (new, 09-05).** `prosecast/pipeline.py` holds
`run_ai_pass` / `run_align` as callable jobs with an
`on_progress(stage, detail, done, total)` callback; `server.py` runs them on a
**second worker** with its own queue — `POST /pipeline/{slug}/ai_pass`,
`POST /pipeline/{slug}/align`, `GET /pipeline/{slug}` (one call, everything the
card draws). Jobs share the `_render_jobs` table so `/render_status/{id}`
serves them with `kind: ai_pass | align`, and the UI reuses `pollRenderStatus`.
**Never put an LLM or whisper job on the render queue** — that queue is
one-at-a-time because there is one GPU, and a 40-minute attribution pass must
not sit in front of an overnight render. Both POSTs **409 with the Setup
probe's own `fix` text** when their service is down. An aborted pass is a job
that is *done* with a reason, not a failed one: the breaker only fires after
everything decided so far is checkpointed. Advisory
`library/<slug>/pipeline_state.json`, keyed by job kind.

**The overlap guard is blunt on purpose (new, 09-05).** A render under a queued
or running AI pass is 409, and an AI pass under a render is 409, per book, both
directions. It exists because of the "correction lost during a render" finding
above: the render worker writes the whole IR document back from a snapshot, and
the AI pass read-modify-writes the same file. **When the render worker is fixed
to merge only `audioVariants` and `cacheKey`, delete the guard** — it is two
`_live_job()` checks in `server.py`, one in `_enqueue_render` and one in
`start_ai_pass`. **Alignment is deliberately exempt** in both directions: it
writes only `renders/chN_blocks/word_timings.json`, which nothing else touches,
and the auto-chain runs it *during* a render by design.

**`no_blocks` is a real alignment state (new, 09-05).** Per chapter, alignment
is `fresh` / `stale` / `none` / `no_blocks`. The last one means there are no
per-block wavs — a chapter rendered on `say`, or not rendered at all. Whisper
has nothing to hear, so the UI shows **no chip and no button** rather than one
that would fail. Anything that lists "chapters needing alignment" must exclude
it. The auto-chain fires after every chapter that renders *without error*, not
only one that synthesized new audio — an all-cache render of a never-aligned
chapter still needs timings, and `run_align` skips the ones already fresh.

**Atomic IR writes (new, 09-03, completed 09-05).** Every `ir.json` write goes through
`lib.write_json_atomic()` (temp + `os.replace`). This closed a real torn-read
race in the render queue AND a crash-mid-write hole that could have destroyed
Tyler's attribution labor. Never write `ir.json` with a plain `open(..,'w')`.

**The card's `.hidden` trap, again (09-05).** `.hidden` still has no global CSS
rule in `static/index.html` — it is scoped to the modals. The Pipeline card uses
its own `.pipe-hidden { display: none !important; }`. Anything new that hides an
element must bring its own rule or reuse that one; "hidden" elements that
render anyway is a bug this repo has shipped before.

**Hermetic tests.** `tests/conftest.py` points every test at an empty tmp
`config.json` (autouse). Without it the suite depends on the developer's real
config — which is exactly how `test_default_is_localhost` failed on the Mac
and passed in a container.

**ElevenLabs affiliate — compliance is not optional.** Link:
`https://try.elevenlabs.io/dmylr2z8w3w9` (`EL_SIGNUP_URL` in
`static/index.html`). Wherever the app, docs, README or launch video shows
the link or the name, it must carry the disclosure ("ProseCast is an
independent affiliate of ElevenLabs and may receive compensation for
referrals") next to the link, and the verbatim trademark attribution
(`EL_ATTRIBUTION`). No logo, no nav use, no "partner" wording, **no
self-referrals**. Full rules: `docs/elevenlabs-setup.md` → "Affiliate program
compliance".

**UI fixtures are generated, never hand-written (new, 09-04).** This is the
rule that exists because breaking it cost a month: the 09-03 reader view was
"verified headless" against a hand-written mock that still contained the
`speaker` field the server had already stopped sending. So
`tests/fixtures/*.json` are produced from the live endpoints by
**`scripts/refresh_ui_fixtures.py`**, and `test_timeline.py` / `test_ingest.py`
fail if a fixture drifts from its endpoint. Change an endpoint on purpose →
re-run the script; never edit the JSON by hand. Machine-dependent fields
(`ocr_available`, `ocr_hint`) are pinned to `"MACHINE"` on both sides.
`tests/synthetic.py` holds the sample novel/play/rulebook text and the PDF/scan
builders that the tests *and* the generator share.

**Four headless UI checks live in the repo** (not collected by pytest; they need
`pip install playwright && playwright install chromium`):
`tests/ui/check_timeline_and_names.py`, `tests/ui/check_ingest_wizard.py`,
`tests/ui/check_pipeline_card.py` and `tests/ui/check_first_run.py`. Run all four after touching
`static/index.html` — Playwright and chromium are installed in the Mac venv now,
so `.venv/bin/python tests/ui/check_*.py` works without the container. They caught three bugs before Tyler
saw them, including a `.hidden` class that had no CSS rule outside
`.modal-overlay`, so every "hidden" section of the wizard was rendering anyway.

**On Air is the DEFAULT skin.** `localStorage['prosecast-theme'] || 'onair'`,
read by an inline script at parse time. Setting `data-theme` after load does
nothing — this repo claimed "verified in both skins" more than once while
running On Air twice each time. To test classic, `page.add_init_script` the
localStorage value *before* navigation, and assert which theme actually applied.

**Reader view architecture.** `#reader-view` and `#setup-view` are *siblings*
of `#main` in the same CSS grid cell; `body.reader-open` / `body.setup-open`
swap which is displayed. The chapter-list DOM (and the render-progress
polling that writes into it) is never destroyed. Any new full-page view
should follow the same pattern.

**Still true from before:** never emit `speed`/`speed_factor` to Chatterbox;
exaggeration clamps to [0.20, 0.85]; `cfg_weight` stays 0.5; voice-map strings
are `predefined:<file>` or a bare clone filename; **never rename WAVs on the
Chatterbox server** (shared with AnimaForge, and voice maps reference
filenames); renders are one-at-a-time (GPU-bound); blocks cache by
text+voice+engine, so re-attribution re-synthesizes only changed blocks;
`corrections.jsonl` is append-only flywheel data.

**Environment notes.** `pydub` is effectively dead on Python 3.13 (`audioop`
removed) — the merger falls back to pure-WAV concat and works fine; fix
belongs in the E5 install story. Goldeye still holds ~15 GB of unattributed
VRAM (leading theory: long-uptime Chatterbox leak) — check `nvidia-smi`
before the rulebook overnight render. Chatterbox now reports **40** predefined
voices (was 34).

---

## Cowork-session gotchas

* **(09-05) `sed -i` on a mounted file drops the executable bit** — `backup_library.sh`
  went 755→644 and was committed that way. `git diff --summary` before committing
  anything touched with sed; `chmod 755` it back.
* **(09-05) `device_commit_files` can report success on an existing tracked file
  while the repo never sees the change.** Edit tracked files through the device
  shell (python/sed heredoc); keep the commit tool for *new* files and binaries.
* **(09-05) A paste-together block must contain no placeholders.** A
  `cd <wherever…>` line was pasted verbatim, `cd` failed, and the next two lines
  renamed the `prosecast/` package and cloned the repo into its place. Anything
  with a fill-in goes in its own checkpoint block.
* **(09-05) Delete permission can be requested** (`device_request_delete_permission`)
  — with it granted, `git commit` cleans its own locks and the lockjunk dance
  below is unnecessary.
* The repo mounts read/write; `device_bash` runs on the Mac. **Cloud
  containers cannot reach Gideon (Tailscale)** — live LLM/whisper/render runs
  are Mac-side only; everything else mocks offline.
* Git stale locks: a zero-byte `.git/index.lock` older than a few minutes
  with no `git` process running is safe to `rm`. It happens after Cowork
  sessions touch the repo.
* **The Cowork device shell is its own Linux VM, not Tyler's terminal.** The
  repo is mounted, but `/opt/homebrew` is not, so `.venv/bin/python` (a symlink
  into homebrew) fails with "No such file or directory" and `.venv/bin/pytest`
  looks broken. Install the deps into that VM's own `python3` and run
  `python3 -m pytest tests/` there — same result, and spaCy can be added with
  `pip install --break-system-packages spacy && python3 -m spacy download
  en_core_web_sm` to match the Mac exactly.
* **Deletes are blocked in that VM**, which is why stale `.git/index.lock`
  files pile up and `git commit` fails with "Unable to create index.lock: File
  exists". `rm` won't work and `mv` to `/tmp` won't either (cross-device move =
  unlink). What does work is renaming it inside the repo:
  `mv .git/index.lock .git/lockjunk.N` immediately before the git write. Clean
  the junk up from a real terminal afterwards: `rm -f .git/lockjunk.* \
  .git/index.lock.stale .git/objects/*/tmp_obj_*`.
* Device-VM test setup:
  `pip install --break-system-packages fastapi httpx python-multipart pytest requests miniaudio pymupdf`
  then `python3 -m pytest tests/`. **tesseract 4.1.1 is already there**, so the
  OCR tests run for real; add spaCy with `pip install --break-system-packages
  spacy && python3 -m spacy download en_core_web_sm` to match the Mac exactly
  (201 pass with both).
* **Playwright is NOT in the device VM** — it is in the cloud container. To run
  the `tests/ui/` checks, stage `static/index.html`, `tests/fixtures/*.json` and
  the check script into the container, reproduce the repo layout
  (`<root>/static`, `<root>/tests/ui`, `<root>/tests/fixtures`), and run there.
* Cleaning the lock junk afterwards, from a real terminal — note the `find`
  form, because zsh aborts the whole command when an `rm` glob matches nothing:
  `find .git \( -name '*.junk*' -o -name '*.lock.*' -o -name 'tmp_obj_*' \) -delete`

## Protocol reminders

* `STATUS.md` is single-writer, updated at chapter-close. GitHub is canonical
  — **push**; CLAIY and the Mac sync through it.
* Back up before long runs: `./scripts/backup_library.sh` (nightly 21:30 to
  Bolt covers ir/voice_map/corrections).
* `renders/` is disposable; everything else in a book dir is Tyler's labor.
