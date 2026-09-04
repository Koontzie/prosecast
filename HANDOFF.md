# ProseCast — Session Handoff (2026-09-04)

For the next Claude/CC session: read this + `STATUS.md`, then pick up at
**"Where to start"**. This supersedes the 2026-08-01 handoff (that one is
still accurate about the attribution campaign; everything operational in it
about how to run the server is now stale — see "Key facts" below).

Repo: `Koontzie/prosecast`, branch `main`. **176 tests pass** on the Mac
(`.venv/bin/pytest tests/ -q`); without spaCy the attribution module skips as
one entry, so a container sees 172 + 1 skip.

---

## Where the project stands

The original goal is **met**: EPUB and PDF, novels and plays, all narrate
end-to-end with multi-voice casting, whole-book resumable renders, and
word-accurate read-along. Phase E ("UI-first") is making it usable by
someone who isn't Tyler.

| Phase | What | State |
|---|---|---|
| A–D | Chatterbox backend, cast screen, safe whole-book render, read-along | ✓ shipped |
| E1 | Full-page reader view (expanded player) | ✓ shipped 09-03 |
| E4.1/E4.2 | `config.json` layer + `/setup/status` probes | ✓ shipped 09-03 |
| E4.3 | Setup page in the UI + ElevenLabs affiliate compliance | ✓ shipped 09-03 |
| E2.2 | PDF ingest on PyMuPDF (chapter detection, generic watermark filter) | ✓ shipped 09-04 |
| E2.1 | Upload-as-a-job (two-step API) + mode guess, with a UI bridge | ✓ shipped 09-04 |
| E2.3 | Ingest wizard UI (mode picker + PDF chapter-split review) | not started — the server is waiting for it |
| E2.4 | OCR for scanned PDFs | not started |
| E3 | Pipeline-in-UI (AI pass + auto-align as jobs) | not started |
| E5 | README / install story / philosophy page | not started |

Full specs for everything unbuilt: **`docs/ROADMAP_PHASE_E_UI.md`**.

---

## E2.1: rebuilt 09-04, and what that means

The 09-04 morning Cowork session built E2.1 in its own cloud container and never
committed it to the Mac. That container was gone by the afternoon and the code
with it — confirmed against the repo, not assumed. It has been **rebuilt from
the spec** (`docs/ROADMAP_PHASE_E_UI.md` §E2.0/E2.1) and shipped together with
the UI bridge, so the breaking change to `/books/upload` never had a window in
which `+ Add Book` was broken. Details in `STATUS.md`, 2026-09-04 pt2.

**The lesson, since it nearly cost a day twice over:** work done in a cloud
container is not work until it is on the Mac and committed. Commit as you go.

Two behaviour changes came along with the lift, both deliberate:
`flatten_to_narrator.py --no-merge` now actually works (the old argument check
rejected any second argument, so the documented flag could never be passed), and
both lifted scripts write through `lib.write_json_atomic()`. The IR each
produces is otherwise byte-identical to `13877b2` — verified on five real books
before anything else was built on top.

---

## How to run (Tyler's Mac)

```bash
cd ~/dev/prosecast
.venv/bin/uvicorn server:app          # → http://localhost:8000
```

**The `PROSECAST_TTS_ENGINE=chatterbox` prefix is no longer needed** — as of
E4.1, `config.json` (repo root, gitignored) pins the engine and every
service URL. Env vars still override it if set.

Per-book flow today:

1. **Ingest** — the UI now takes `.epub`, `.txt` and `.pdf` (mode is guessed:
   EPUB → novel, `SPEAKER.` labels → play, otherwise single narrator; the
   choice is stated under the book list, and re-adding the file is how you
   change it until the E2.3 picker exists). The CLI paths still work:
   * PDF → `.venv/bin/python scripts/pdf_to_txt.py book.pdf --list` to see the
     detected chapter split, then `book.pdf out.txt` to extract; then
     `main.py --book out.txt --ir-only`; then
     `scripts/flatten_to_narrator.py <slug>` for single-narrator books.
   * Play → OCR/pdftotext to text, then
     `scripts/play_to_ir.py play.txt "Title" library/<slug>/ir.json`.
2. **LLM passes** (terminal, ~30 min, Mac must stay awake — `caffeinate -i`):
   ```bash
   .venv/bin/python main.py <Name> --use-existing-ir --llm-scene \
     --llm-scope low-confidence --profile-cast --llm-model gemma3:12b --ir-only
   ```
   (Ollama URL now comes from `config.json`; no env var needed.)
3. **Cast drawer** — merge chips → Demote all ≤5 → hand-cast mains →
   Auto-cast supporting → Save.
4. **Render** — ⚡ Generate per chapter, or "Render remaining (N)".
5. **Align** — `.venv/bin/python scripts/align_words.py <slug>`.
6. **Listen** — press ▶ and the full-page reader opens.

---

## Where to start

1. **E2.3 — the ingest wizard.** Everything it needs now exists server-side:
   `POST /books/upload` returns `guess_mode`, `guess_reason`, and for PDFs a
   `detection` block (`source`, human-readable `note`, per-chapter `skip`), and
   `POST /books/ingest` takes `mode`, `title` and a reviewed `chapters` list.
   The wizard is: file picker → mode cards (Novel / Single narrator / Play,
   pre-selected by the guess, with the reason shown) → for PDFs, the detected
   split as an editable checklist → progress card (poll `stage`/`detail`) →
   open the book. It replaces the bridge in `static/index.html`'s
   `epubFileInput` change handler — that handler is ~50 lines and is the only
   thing to rewrite.
2. **E2.4 OCR** — tesseract IS installed on the Mac
   (`/opt/homebrew/bin/tesseract`), so the scanned-play path can run
   locally. `pdf_ingest.scan_report()` already flags scans.
3. **E3 pipeline-in-UI**, then **E5 README**.

Still open from earlier phases: the **rulebook overnight render**, the **C4
voice-ref mirror**, the **Voices tab** (`docs/CC_BRIEF_voices_tab.md`), and
**auditioning the 20 LibriVox US voices** in `librivox_voices/`.

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
keep_tables?}` returns a `job_id` polled at `/render_status/{job_id}`
(`kind: "ingest"`, `stage`, `detail`; stages `extracting → chapters →
attributing → done`). Ingest runs on its **own daemon thread, not the render
queue** — it is CPU-bound and GPU-free, and a new upload must never sit behind
an overnight render. Uploads are held in an in-memory dict (last 40), so an
`upload_id` does not survive a server restart: the UI's answer to a 404 there is
"add the file again", not a retry. Scans are refused at `/books/ingest` with the
OCR message rather than failing as a job.

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
* Container test setup:
  `pip install --break-system-packages fastapi httpx python-multipart pytest requests miniaudio pymupdf`
  then `python3 -m pytest tests/`. spaCy is absent, so 1 test skips.
* UI changes are verifiable headless: there is a mock-API + Playwright
  pattern that screenshots both skins and asserts behavior with no server.

## Protocol reminders

* `STATUS.md` is single-writer, updated at chapter-close. GitHub is canonical
  — **push**; CLAIY and the Mac sync through it.
* Back up before long runs: `./scripts/backup_library.sh` (nightly 21:30 to
  Bolt covers ir/voice_map/corrections).
* `renders/` is disposable; everything else in a book dir is Tyler's labor.
