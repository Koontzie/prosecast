# ProseCast — Phase E: UI-first ("everything through the UI")

**Written:** 2026-09-03 (Cowork session). Companion to `ROADMAP_PHASES_C_F.md`,
`PRODUCT_NOTES.md` and `STATUS.md`. Same rules as the C→F doc: each step is
verified against the repo as it stands today and written so a CC session can
build it without re-deriving the plan.

**Direction (Tyler, 2026-09-03):** the core goal is met — EPUBs and PDFs, novels
and plays, all narrate. The next phase is making the thing *usable by someone
who isn't Tyler*: every step reachable from the UI, and setup walkthrough-able
without touching Python. Install story decided: **public repo + a great README
+ an in-app Setup page** (not a docker bundle).

---

## 0. Verified state (what I checked, 2026-09-03)

- **Upload is EPUB-only.** `POST /books/upload` (server.py:279) 400s on any
  other extension and runs `parse_book → build_ir` synchronously in the request.
  `main.py --book` accepts `.epub` or `.txt`, so TXT is already parseable — the
  UI just refuses it.
- **PDF ingestion is NOT a wiring job.** `scripts/pdf_to_txt.py` needs a
  hand-written `toc.json` (1-based PDF page per chapter) and carries a
  hard-coded Carl watermark regex. "Upload a PDF" therefore needs a
  chapter-detection step *and* a human review step — see E2.
- **Plays** go `pdftotext`/OCR text → `scripts/play_to_ir.py <txt> <title> <out>`
  straight to IR (no book_parser). Scanned PDFs need tesseract outside the app.
- **Terminal-only steps that remain:** LLM attribution/profile passes
  (`main.py --use-existing-ir --llm-scene --profile-cast …`), whisper alignment
  (`scripts/align_words.py`), the PDF/play scripts above, and every URL/key via
  env vars (`PROSECAST_TTS_ENGINE`, `PROSECAST_OLLAMA_URL`,
  `PROSECAST_WHISPER_URL/_MODEL`, `ELEVENLABS_API_KEY`, `COMFYUI_URL`,
  `COMFY_RECLAIM_BELOW_GB`, `MIN_FREE_VRAM_GB`).
- **Engines in `tts_engine.py`:** chatterbox, elevenlabs, piper, say, gtts, stub.
  Auto-detect order is EL-key > chatterbox > piper/say/gtts — which is why the
  env var is REQUIRED today (a bare launch with a key in `.env` burns EL credits).
- **Job pattern exists:** the Phase C single-worker FIFO render queue
  (`/render`, `/render_status`, `/render_queue`, `render_state.json`). E2/E3
  reuse it rather than inventing a second one.
- **Working tree:** uncommitted changes from 08-30/08-31/09-02 (engine strip,
  voices staging, GPU preflight) plus today's `static/index.html`. Commit before
  E2 so the diffs stay readable.
- **UI:** `static/index.html` (3,034 lines, single file, no build step, fonts
  inlined). `#main` holds the chapter list AND the render-progress DOM that the
  polling code writes into — anything that replaces `#main`'s innerHTML while
  a render is running breaks progress. E1 respected that (see below).

---

## E1. Reader view — SHIPPED 2026-09-03

**What:** playing a chapter now opens a full-page reader in the main area: the
whole chapter as paragraphs (speaker labels on dialogue only, narration
unlabelled), current paragraph lit and auto-centred, past paragraphs dimmed,
sentence click-to-seek, "↓ back to the voice" pill when the listener scrolls
away (auto-follow pauses 8 s), `Prev`/`Next` across *rendered* chapters, chapter
end auto-plays the next rendered chapter, `A−`/`A+` (persisted
`pc_reader_fs`), Space / ← → (10 s) / Esc. `☰ Chapters` or Esc collapses back
to the list (playing row still highlighted); `⤢ reader` in the player bar
re-opens it. Both skins styled.

**How:** `<section id="reader-view">` is a *sibling* of `#main` in the same
grid cell; `body.reader-open` swaps their `display`. The chapter-list DOM is
untouched, so render polling keeps working underneath. Reuses
`readerParaInner()` (so `.reader-para`/`.rs`/`.now-w` CSS and the On Air
overrides carry over) and the popup's seek logic, now shared as
`seekToSentence(el)`. Hooks: `playChapter()` → `openReaderView()`;
`loadBook()` → `closeReaderView(true)`; `timeupdate` → `updateReaderView(t)`;
`ended` → `readerGo(1)` when the reader is open. ~300 lines, zero server
changes, 0 test impact (no test touches index.html).

**Verified:** headless Chromium against a mock API (range-capable — Chromium
can't seek a WAV from a server without `Accept-Ranges`; FastAPI's FileResponse
has it) in both skins: open/collapse/re-open, sentence seek + past shading,
scroll-away pill, Prev/Next enable state, auto-advance, font steps, Esc,
book-switch closes reader. No console errors. Backup:
`.backup/index_pre-reader_2026-09-03.html`.

**Small follow-ups (not blocking):**
- Remember the last listened chapter + position per book (`localStorage` is
  enough for one listener; a server-side `progress.json` if this is ever
  multi-device).
- Sleep timer / playback speed (`audioEl.playbackRate` is free; the highlight
  math already uses `currentTime`, so it stays in sync).
- The reader is where the later "Stage" ideas plug in (section 7): each
  `.rv-para` already carries `data-i`, the speaker, and the block index.

---

## E2. Ingest wizard — any format, with a mode picker (~2 sessions)

**Done means:** `+ Add Book` accepts `.epub`, `.txt`, `.pdf` (text-layer *or*
scanned), and a play in any of those; the user picks a **mode**, reviews the
chapter split for PDFs, and never opens a terminal. Every existing script
becomes a function call behind an endpoint; the scripts stay as thin CLIs.

### E2.0 Mode picker (UI + contract)
After the file is chosen, a modal asks one question — *"How should this be
read?"* — with three cards:
1. **Novel / story** — many voices; rules + local AI figure out who speaks.
   (today's EPUB path: `parse_book → build_ir`, then E3's passes)
2. **Single narrator** — rulebooks, non-fiction, anything where one voice reads
   everything and tables/stat blocks are skipped. (`flatten_to_narrator`)
3. **Play / script** — `SPEAKER.` lines, stage directions read by the narrator.
   (`play_to_ir`)
Default guessed from the file: `.epub` → Novel; PDF with `SPEAKER.`-style
lines in the first pages → Play; otherwise Single narrator. Mode saved into
`ir.json` as `ingest.mode` (new, additive field) so re-ingest and the E3
pipeline know what to run.

### E2.1 Server: `POST /books/upload` becomes a job
- Accept `.epub/.txt/.pdf`; reject the rest with the reason in `detail`.
- Save to `books/`, then **enqueue** `ingest` on the existing worker (it is a
  GPU-free job, but sequential keeps the code simple — a second lightweight
  worker is fine if ingest ever blocks a render for long). Return `job_id`;
  UI polls `/render_status/{job_id}` (rename in docs to job_status — same
  shape).
- Stage names for progress: `extracting` → `chapters` → `attributing` →
  `done`, with counts.

### E2.2 PDF text + chapter detection — `prosecast/pdf_ingest.py`
Lift the guts of `scripts/pdf_to_txt.py` into a module with **no** book-specific
regexes (the Carl watermark line becomes a generic "line repeated on >60% of
pages" running-head filter, which is what it really is). Then chapter split,
in order of trust:
1. **PDF outline/bookmarks** (`pdftotext` doesn't give them; use `pypdf`
   `reader.outline` — new dependency, pure Python — or `pdfinfo`/`mutool`
   if present). Most published PDFs and every KDP/Renegade-style rulebook have
   them. This alone covers the Carl case with zero hand-written TOC.
2. **Printed TOC page** — leader lines (`.....` + page number) in the first
   ~15 pages; already regex'd as `LEADER_RE`.
3. **Heading heuristic** — CAPS lines / large-gap lines at page tops.
4. **Fallback:** one chapter per N pages, clearly labelled as such.
Output: `{"chapters":[{"page":..,"title":..}], "source":"outline|toc|heuristic|fallback"}`
— the same shape `toc.json` has today, so `pdf_to_txt.py` keeps working as the
CLI over the same function.

### E2.3 Chapter-split review (UI)
For PDFs the wizard shows the detected split as an editable list (title, start
page, [skip]) with the detection source stated in words ("found 11 bookmarks in
the PDF"). Confirm → ingest continues. **This is the step that makes PDF upload
honest** — the heuristics will be wrong sometimes, and the fix is 10 seconds of
editing rather than a bad audiobook.

### E2.4 Scans → OCR — `prosecast/ocr.py`
If `pdftotext` yields < ~200 chars/page on average, it's a scan. Offer OCR in
the wizard: `tesseract` if installed (probe with `which`; say *how* to install
it on macOS/Linux/Windows in the same dialog), else stop with a clear "this PDF
is a scan and OCR isn't installed" message. 300 dpi via `pdftoppm` → tesseract
per page, progress by page, cached under `books/<stem>_ocr.txt` exactly as
today. Long — runs as the ingest job's first stage.

### E2.5 Wire the three modes
- Novel: existing path.
- Single narrator: `parse_book(txt)` → `build_ir` → `flatten_to_narrator()`
  (merge ~900-char chunks, backup `ir.json.pre-flatten` as today).
- Play: `play_to_ir()` with `--running-head` auto-detected (same repeated-line
  filter as E2.2) and the dual-speaker limit (`CHUCK & TILLY.`) documented in
  the wizard's fine print.

### E2.6 Tests
Mocked, offline: extension gate; mode → correct function called; outline
detection on a 3-page synthetic PDF built with `reportlab`/`fpdf` in the test
(or a checked-in 20 KB fixture); scan detection threshold; OCR path when
`tesseract` is absent returns the friendly error, never a traceback.

**Gotchas to surface in the brief:** `BOOKS_DIR` slug derivation (`.stem` →
title → 30-char slug) collides for two files with the same stem — add a
`-2` suffix rather than overwrite; `books/` is gitignored (keep it that way);
never run ingest inside the request thread again — Parade-sized EPUBs already
take long enough to trip proxies.

---

## E3. Pipeline in the UI (~1 session)

**Done means:** after ingest, a **Pipeline card** on the book page shows the
stages with buttons and progress, and the two remaining terminal steps are gone.

| Stage | Today | In UI |
|---|---|---|
| Rule attribution | automatic at ingest | unchanged, shown as ✓ |
| LLM scene pass + cast profile | `main.py … --llm-scene --profile-cast` | **▶ Run AI pass** button → job; scope selector (unresolved / low-confidence / all) with the provenance warning on *all*; progress = scenes done / total; circuit-breaker abort surfaces as amber "Ollama stopped answering after 3 tries" |
| Cast | drawer | unchanged |
| Render | queue | unchanged |
| Whisper alignment | `scripts/align_words.py` | **auto-chained** after every chapter render when the whisper URL probes OK; manual "Align" button otherwise; stale-fingerprint state shown per chapter |
| Export M4B | button | unchanged |

Implementation notes: the scene attributor and profiler are already
prompt→JSON functions with per-scene checkpointing — the job is a thin wrapper
that calls them with a progress callback. Run **LLM jobs on a second worker**
(`pipeline`), not the render worker: gemma3:12b coexists with resident
Chatterbox (STATUS 07-31), and a 40-minute attribution pass must not block a
render. State snapshot `library/<slug>/pipeline_state.json` (advisory, like
`render_state.json`). Tests: job enqueues, progress shape, breaker → failed job
with message, align chained only when `whisper_ok`.

**The soft spot:** an "AI pass" that silently does nothing because Ollama is
unreachable is the exact failure PRODUCT_NOTES names. The button must be
*disabled with the reason* when the Setup probe (E4) says Ollama is down.

---

## E4. Settings + Setup page (~1–2 sessions)

**Done means:** a new **Setup** view (header link, and the landing view on first
run) that probes every service, says in plain words what's missing and how to
fix it, and lets the user set URLs/keys/engine without env vars. Env vars keep
working as overrides.

### E4.1 Config — `prosecast/config.py`
One file, `config.json` at repo root (gitignored; `config.example.json`
tracked), read once, env vars override. Keys: `tts_engine`, `chatterbox_url`,
`ollama_url`, `ollama_model`, `whisper_url`, `whisper_model`,
`elevenlabs_api_key`, `comfyui_url`, `gpu_reclaim_below_gb`. `GET/PUT /config`
(key masked on read). **Default `tts_engine` becomes explicit, never
`auto`** — auto-detect stays as a *button* ("detect for me") that reports what
it found, so the EL-credit landmine is gone for good.

### E4.2 Probes — extend `/engine_status` into `GET /setup/status`
One call, one object, each entry `{ok, detail, fix}`:
- **Voice engine** — what's selected; for Chatterbox: reachable, model base vs
  turbo, voice count (existing `/engine_status` logic); for `say`/`piper`: is
  the binary/model present; for ElevenLabs: key present + `/v1/user` answers,
  remaining credits.
- **Ollama** — reachable, model list, whether the configured model is pulled
  (offer `ollama pull <model>` as the fix text).
- **Whisper** — reachable (optional: "read-along will be sentence-level
  without it").
- **ffmpeg / pdftotext / tesseract** — `which` probes with per-OS install lines.
- **GPU headroom** — the preflight check-6 logic, informational.
`fix` is a sentence a stranger can act on, not an exception string.

### E4.3 Setup view (UI)
A checklist rendered from `/setup/status`, teal/amber/red plaques matching the
engine strip, each row expandable to its fix text and the relevant field
(URL, key box). Sections in this order — the *hardware ladder* from
PRODUCT_NOTES, top to bottom:
1. **Voices** — pick a tier: *built-in system voices* (`say` on macOS, `piper`
   elsewhere; no GPU, works today), *Chatterbox on this machine / on another
   machine (URL)*, *ElevenLabs (your own account)*. The EL card carries the
   "honest part" and cost table from `docs/elevenlabs-setup.md` verbatim and
   the affiliate link with the disclosure sentence already written there.
2. **Who's speaking (AI)** — Ollama URL + model; "skip this and rules-only
   attribution still works (~95% of lines)".
3. **Read-along timing** — whisper URL; optional.
4. **Tools** — ffmpeg, pdftotext, tesseract.
5. **Your library** — where books live, backup script pointer.
First run (no `config.json`) lands here with a one-paragraph explainer; the
header shows an amber "Setup" chip until the voice engine row is green.

### E4.4 Tests
Config precedence (env > file > default), key masking, each probe's ok/fail
branch mocked, `tts_engine=auto` never chosen silently.

**Watch out for:** the engine is resolved once per process and cached
(08-30 note) — a settings change must call the same cache-drop path as
`/engine_status/recheck`. And `.env` with `ELEVENLABS_API_KEY` must migrate
into `config.json` on first run with a visible note, or the two will disagree.

---

## E5. README + install story (~1 session, mostly writing)

Target reader: someone who runs Ollama and has never opened this repo.
- **README.md rewrite:** what it is in one paragraph (local-first, your book
  never leaves your machine), a 90-second demo GIF/clip of E1's reader, the
  hardware ladder table, then *three* install paths: (a) macOS system voices
  only (`SETUP.sh` + `say` — zero extra services, the "does it work at all"
  path), (b) + Chatterbox server (link to the devnen server's own install
  docs; which model to load and why base-not-turbo), (c) + Ollama (`ollama pull
  gemma3:12b`) + faster-whisper. Each path ends with "open Setup and watch the
  rows turn green".
- `SETUP.sh` grows a `--check` that runs the same probes as E4.2 from the
  shell (share the code).
- **Philosophy page** (`docs/PHILOSOPHY.md`, linked from README): the three
  voice-actor planks from PRODUCT_NOTES and the licence tiering from
  `docs/voice-sources.md`. The provenance audit of the 33 predefined voices is
  the one prerequisite with real downside if skipped — do it before the repo
  goes public, not after.
- Windows: `say` doesn't exist; `piper` is the no-GPU engine there. Say so.
- **ElevenLabs affiliate compliance (required, not optional):** wherever the README
  or the launch video/description mentions ElevenLabs or carries the link
  (`https://try.elevenlabs.io/dmylr2z8w3w9`), it must sit next to the disclosure
  ("ProseCast is an independent affiliate of ElevenLabs and may receive
  compensation for referrals") and the page must carry the trademark attribution
  sentence. Both are spelled out in `docs/elevenlabs-setup.md` → "Affiliate
  program compliance". No logo, no "partner" wording, no self-referral.

---

## 6. Order and smallest first steps

E1 ✓ → **commit the tree** → E4.1+E4.2 (config + probes; the backend that
both E2 and E3 need to report "why is this button disabled") → E2 → E3 → E4.3
→ E5. Rationale: the Setup probes are the one piece every other step
consumes; doing them second means E2/E3 ship with honest error states from day
one instead of retrofitting them.

Smallest verifiable first step for each:
- E4: `GET /setup/status` returning the existing engine probe + `which ffmpeg`
  — 30 lines, one test. Then grow rows.
- E2: accept `.txt` in `/books/upload` (three-line change, `parse_book` already
  handles it) and turn the upload into a job. PDF comes after.
- E3: "Align" button per chapter that runs `align_words` as a job. Then the AI
  pass.

Chapter-close for each session: STATUS entry, tests green, `git push`.

---

## 7. Parking lot — Phase G "Stage" (later; ideas from 2026-09-03)

Not now. Written down so they aren't lost, with the hook each one needs.
- **Character art from the text.** `ir.character_profiles` (E3's profiler)
  already extracts gender/age/voice hints; extend the profile prompt to
  capture stated physical description, then render a portrait per main
  character (ComfyUI is on Goldeye; SDXL + 32B don't co-reside — schedule
  around Chatterbox like the GPU preflight does). Portraits show in the cast
  drawer first (useful on its own), then in the reader.
- **Expressive sprite-swap portraits in the reader** (the AnimaForge idea): a
  small set of pre-generated states per character (neutral / happy / angry /
  sad / surprised, plus "speaking"), swapped by the block's IR tags —
  confirm `/timeline` carries `tags` (it returns speaker/text/start/duration
  today; add tags if not). Rule: change expression only on tag *transitions*,
  never per block, or it flickers. The reader's `.rv-para` already knows its
  speaker and block index, so a portrait rail beside `.rv-page` is a CSS
  column, not a rewrite.
- **Scene video.** The fast video-gen repos change monthly; treat as "a
  ComfyUI workflow per scene" behind the same portrait rail when the time
  comes. Keep the IR as the contract; nothing in E1–E5 should assume it.
