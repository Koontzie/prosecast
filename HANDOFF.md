# ProseCast — Session Handoff (2026-09-05)

For the next Claude/CC session: read this + `STATUS.md`, then pick up at
**"Where to start"**. Supersedes the 09-04 handoff.

Repo: `Koontzie/prosecast`, branch `main`, clean and pushed through
**`1eadf2e`**. **201 tests pass** on the Mac (`.venv/bin/pytest tests/ -q`),
with spaCy and tesseract both installed. Both are gated, so a leaner box skips
rather than fails: without spaCy the 4 attribution tests collapse to a single
module-level skip, and without tesseract 6 OCR tests skip (4 in `test_ocr.py`,
2 in `test_ingest.py`). A box with neither therefore shows **191 passed,
7 skipped** — that is healthy, not a regression.

---

## Where the project stands

The original goal is **met**: EPUB, TXT and PDF — novels, rulebooks, plays and
now scans — all narrate end-to-end with multi-voice casting, whole-book
resumable renders and word-accurate read-along. Phase E ("UI-first") is making
it usable by someone who isn't Tyler, and **ingest is finished**: there is no
terminal step left between a file and a book.

| Phase | What | State |
|---|---|---|
| A–D | Chatterbox backend, cast screen, safe whole-book render, read-along | ✓ shipped |
| E1 | Full-page reader view | ✓ shipped 09-03 |
| E4.1–E4.3 | `config.json`, `/setup/status` probes, Setup page, EL affiliate compliance | ✓ shipped 09-03 |
| E2.1 | Upload-as-a-job (two-step API) + mode guess | ✓ shipped 09-04 |
| E2.2 | PDF ingest on PyMuPDF (chapter detection, generic watermark filter) | ✓ shipped 09-04 |
| E2.3 | Ingest wizard — mode picker + PDF chapter-split review | ✓ shipped 09-04 |
| E2.4 | OCR for scanned PDFs | ✓ shipped 09-04 |
| **E3** | **Pipeline-in-UI (AI passes + auto-align as jobs)** | **not started — wants the Mac** |
| **E5** | **README / install story / philosophy page** | **not started — unlocks publish** |

Specs for both: **`docs/ROADMAP_PHASE_E_UI.md`**. Post-publish ideas (including
Tyler's "show the images already in the book", with its cost ladder) live in
that doc's parking lot.

---

## What happened on 09-04/05 (four chapters, all pushed)

1. **`d9ef948` E2.1 rebuilt from spec.** The 09-04 morning Cowork session built
   it in a cloud container and never committed it; the container was gone by the
   afternoon. Rebuilt and shipped *with* the UI half so `/books/upload`'s
   breaking change never left `+ Add Book` broken. **The lesson, since it nearly
   cost a day: work in a container is not work until it is on the Mac and
   committed. Commit as you go.**
2. **`bae3215` Two bugs an external review (Codex) found.** `/timeline` lost its
   `speaker` field in `30740dc` (2026-08-04) while `text` was being
   un-truncated, so for a month every line in the reader rendered as NARRATOR
   while the audio played the right voices. And `esc()` escapes `& < > "` but
   the Voices/Cast panels interpolate names into *single-quoted* inline
   handlers, so a character called O'Brien made the preview and delete buttons
   inert — verified dead in Chromium, not theorised.
3. **`577837f` E2.3 wizard.** Mode cards, editable title, PDF chapter review,
   progress card, errors in the modal.
4. **`507fbe0` E2.4 OCR.** Scans are read rather than refused.

---

## Where to start

Two candidates, in either order. **E5 is the one that unlocks other things.**

1. **E5 — README + install story.** The last piece before the repo can go
   public, which in turn is what Tyler is waiting on to finish the **ElevenLabs
   affiliate application** (he deliberately deferred it until there is a public
   repo to point at). Mostly writing. Include: the hardware ladder, the
   config.json story, what actually has to be installed (ffmpeg required;
   tesseract only for scans; poppler no longer needed at all), and the EL
   disclosure + trademark attribution verbatim.
   **Do the git-history audit in the same chapter** — see "Before the repo goes
   public" below.
2. **E3 — pipeline in the UI.** The AI attribution passes and `align_words.py`
   become jobs with a second worker, so a user never opens a terminal.
   **This one belongs in Claude Code on the Mac**: it needs Gideon reachable
   (Tailscale), and a Cowork container cannot get there.

Still open from earlier phases: the **rulebook overnight render**, the **C4
voice-ref mirror**, the **Voices tab** (`docs/CC_BRIEF_voices_tab.md`), and
**auditioning the 20 LibriVox US voices** in `librivox_voices/`.

---

## Known-real, not yet fixed (from the 09-04 Codex review)

All six findings were checked against the code; these four survived and are
worth doing in roughly this order. None is urgent.

* **ElevenLabs never receives the emotion tags.** `tag_mapper` supports EL, but
  `synthesize()` calls `_synthesize_elevenlabs(text, voice_cfg, out_path)`
  without `tags`. Phase 4c work — the expressive-delivery feature is
  disconnected on the premium engine.
* **A correction made during a render can be silently overwritten.** The queue
  loads one IR snapshot per job and `renderer.save_ir()` writes that snapshot
  back after every block, while PATCH endpoints read-modify-write independently.
  Atomic writes fixed torn reads, not stale writes. **The surgical fix is to
  have the render worker re-read and merge only the fields it owns
  (`audioVariants`, `cacheKey`) instead of writing the whole document** — not
  the full repository-with-locking refactor Codex proposed.
* **Audio is keyed by list position, not `segmentId`.** `merge_next` shifts
  every following block, so the timeline and the word aligner then read
  `block_{i}.wav` files that belong to different blocks.
* **The render cache key ignores tags, model and backend** (`text + voice_cfg +
  engine` only), so re-tagging a block replays the old audio.
  **Do this one together with the `segmentId` change** — both alter how audio
  files are identified, and each costs a full re-render of the library. Pay
  that once, deliberately.

Also true and cheap: **`CLAUDE.md` is badly stale** (still says Phase 4b is
next, predates the Chatterbox decision). A fresh Claude Code session reads it
*first*, so it is a live trap, not a tidiness issue.

---

## Before the repo goes public

Going public exposes the whole git history, not just the current tree. One
confirmed instance: the old `HANDOFF.md` at `13877b2` contains Tyler's Gideon
Tailscale IP in the command examples. Today's file no longer does, but history
keeps it. The same question applies to whether `config.json`, `.env` or any
copyrighted EPUB in `books/` was ever committed *before* the `.gitignore` rules
landed — they are ignored now, which says nothing about the first commits.
Fifteen minutes of `git log --all --diff-filter=A --name-only`, cheap before,
annoying after.

---

## Key facts (hard-won — do not relearn)

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

**Atomic IR writes (new, 09-03).** Every `ir.json` write goes through
`lib.write_json_atomic()` (temp + `os.replace`). This closed a real torn-read
race in the render queue AND a crash-mid-write hole that could have destroyed
Tyler's attribution labor. Never write `ir.json` with a plain `open(..,'w')`.

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

**Two headless UI checks live in the repo** (not collected by pytest; they need
`pip install playwright && playwright install chromium`):
`tests/ui/check_timeline_and_names.py` and `tests/ui/check_ingest_wizard.py`.
Run them after touching `static/index.html`. They caught three bugs before Tyler
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
