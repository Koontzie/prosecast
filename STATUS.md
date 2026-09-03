# PROSECAST — STATUS

**Status:** ACTIVE — **Phase E (UI-first): E1 reader view + E4.1/E4.2 config +
Setup probes shipped 2026-09-03.** Core goal met (EPUB + PDF, novels + plays).
Next: Tyler runs tests + `/setup/status`, commits; then E4.3 Setup page → E2
ingest wizard per `docs/ROADMAP_PHASE_E_UI.md`. Rulebook render + C4 still open.
**Updated:** 2026-09-03

## Session 2026-09-03 (Cowork) — Phase E kickoff: reader view + roadmap

**Direction (Tyler):** the original goal is done; the next phase is making
ProseCast usable by someone who isn't Tyler — everything through the UI
(upload is EPUB-only; PDFs/plays/LLM passes/align are terminal) and a
setup walkthrough for non-Python users. Install story decided: **public
repo + great README + in-app Setup page** (not docker). Later-date ideas
(character art from the text, AnimaForge-style expressive sprite-swap
portraits in the player, eventual scene video) parked as Phase G "Stage"
in the roadmap doc.

- **E1 Reader view SHIPPED** (`static/index.html`, +~300 lines, zero server
  changes, no test impact): playing a chapter opens a full-page reader in the
  main area — whole chapter as paragraphs, dialogue labelled, narration
  unlabelled, current paragraph lit + auto-centred, past dimmed, sentence
  click-to-seek, "↓ back to the voice" pill when you scroll away (auto-follow
  pauses 8 s), Prev/Next across *rendered* chapters, chapter end auto-plays
  the next rendered chapter, A−/A+ (persisted), Space / ←→ 10 s / Esc.
  `☰ Chapters` or Esc collapses to the list (playing row still highlighted);
  `⤢ reader` in the player bar re-opens. Both skins.
- **How it's built:** `<section id="reader-view">` is a *sibling* of `#main` in
  the same grid cell; `body.reader-open` swaps `display`. The chapter-list DOM
  (and the render-progress polling that writes into it) is untouched. Reuses
  `readerParaInner()` + the popup's seek logic (now `seekToSentence(el)`).
- **Verified** headless Chromium vs a mocked API in both skins: open/collapse/
  re-open, sentence seek + past shading, scroll pill, nav enable state,
  auto-advance, font steps, Esc, book-switch closes reader. No console errors.
  Gotcha found on the way: Chromium can't seek a WAV unless the server sends
  `Accept-Ranges` (FastAPI's FileResponse does; my mock didn't).
  Backup: `.backup/index_pre-reader_2026-09-03.html`.
- **`docs/ROADMAP_PHASE_E_UI.md`** (new): verified state + build-ready specs.
  E1 reader (done) · E2 ingest wizard (any format + mode picker: novel /
  single narrator / play; PDF chapter detection via outline → printed TOC →
  heuristic, with a **review step** because `pdf_to_txt.py` needs a hand
  TOC today and carries a Carl-specific regex; scan → tesseract) · E3
  pipeline-in-UI (AI pass + auto-align as jobs on a second worker) · E4
  config.json + `/setup/status` probes + Setup page (hardware ladder, EL
  BYOK card from `docs/elevenlabs-setup.md`) · E5 README/install story.
  Suggested order: commit → E4.1/E4.2 probes first (every other step
  consumes them for honest disabled-button states) → E2 → E3 → E4.3 → E5.
- **Not committed:** working tree still carries 08-30/08-31/09-02 changes +
  today's index.html + the new doc. Commit before starting E2.

## Session 2026-09-03 pt2 (Cowork) — E4.1/E4.2: config.json + Setup probes

- **`prosecast/config.py`** (new): one config layer, three tiers — defaults <
  `config.json` (repo root, **gitignored**) < env vars. Same env names as
  before (`PROSECAST_TTS_ENGINE`, `CHATTERBOX_URL`, `PROSECAST_OLLAMA_URL`,
  `PROSECAST_WHISPER_URL/_MODEL`, `ELEVENLABS_API_KEY`, `COMFYUI_URL`,
  `COMFY_RECLAIM_BELOW_GB`, new `PROSECAST_OLLAMA_MODEL`), so nothing anyone
  runs today changes. `get/source/public/set_many/shadowed_by_env`; secrets
  masked on read and a round-tripped mask never overwrites the real key;
  `config.example.json` tracked.
- **Wired:** `tts_engine.CHATTERBOX_BASE_URL`, EL key + auto-detect,
  `preflight.COMFY_BASE_URL` + reclaim threshold, `llm_attributor`/
  `tag_generator.OLLAMA_BASE`, `word_aligner.WHISPER_*`, and the server's
  engine choice all read config. **Defaults are now localhost everywhere**
  (the Gideon IPs that were hard-coded in tts_engine/preflight are gone) —
  Tyler's `config.json` carries them instead (written this session,
  chmod 600). No ComfyUI URL = VRAM check skipped silently, not warned.
- **`PROSECAST_TTS_ENGINE=chatterbox` is no longer required** to start the
  server — `config.json` pins `tts_engine: chatterbox`. Env var still wins
  if set. `tts_engine: auto` is reported amber by the probes on purpose.
- **`prosecast/setup_probe.py`** (new) + **`GET /setup/status`**: rows for
  voice engine (per engine: chatterbox reachable/turbo/cpu, EL key valid +
  credits left, say/piper present), Ollama (+ is the model pulled → `ollama
  pull …` fix), whisper (optional), ffmpeg (required) / pdftotext /
  tesseract with per-OS install lines, GPU headroom via ComfyUI. Each row =
  `{ok, state: ok|warn|missing|off, detail, fix, optional}`; `ready` = all
  required rows ok. Reads config at call time → save-then-reprobe works
  without restart (render/LLM modules pick up new URLs on restart).
- **`GET /config` / `PUT /config`**: PUT validates (engine names, http URLs),
  merges into config.json, and drops the cached engine + voice list like
  `/engine_status/recheck`.
- **Tests:** `tests/test_setup.py`, 21 new (precedence, masking, every probe
  branch, endpoint wiring + cache drop). `test_preflight.py` fixture now
  sets a ComfyUI URL (headroom check is skipped without one). **134 pass /
  1 skip** in the cloud container, with AND without the env var.
- **Two bugs Tyler's Mac run surfaced (both fixed):** (1) the suite depended
  on the developer's real `config.json` — `tests/conftest.py` (new) now
  points every test at an empty tmp config (autouse), so the suite is
  hermetic again; (2) `test_queue_position_reported` hit a torn read of
  `ir.json` — the render worker rewrote it non-atomically while the second
  POST read it. That was also a crash-mid-write data-loss hole on Tyler's
  labor. **`lib.write_json_atomic()`** (tmp + `os.replace`) now backs every
  ir.json write: renderer, `save_ir`, and all 7 sites in server.py.
- **Not done yet (E4.3):** the Setup *page* in index.html. Backend is
  complete; the UI reads `/setup/status` and PUTs `/config`.

## NEXT (updated 2026-09-03)
1. **Tyler:** `.venv/bin/pytest tests/ -q` (expect 134 pass) → restart the
   server *without* the env var → `curl localhost:8000/setup/status | python3
   -m json.tool` — every Gideon row should be green from config.json alone.
   Commit + push.
2. **E4.3 Setup page** in index.html (reads `/setup/status`, PUTs `/config`,
   engine picker + EL card from `docs/elevenlabs-setup.md`, amber header chip
   until the engine row is green) → **E2** starting with `.txt` upload as a
   job.
4. Still open from before: rulebook overnight render, C4 voice-ref mirror,
   Voices tab (`docs/CC_BRIEF_voices_tab.md`), audition + upload the 20
   LibriVox US voices.


## Session 2026-09-02 (Cowork) — Preflight GPU headroom check

**The bug it exists to prevent:** every voice preview in every book failed with
`500 {"detail":"TTS engine failed to synthesize audio for chunk 1."}` while
`/api/model-info` reported `{"loaded": true, "device": "cuda"}` and `/system_stats`
showed **0.0 GB of 25.3 GB free**. ComfyUI had been holding a Wan2.2 video model
resident since its last job on 2026-08-06 — 27 days — because it never unloads on
its own. `loaded` means "was loaded once", not "can allocate". Reproduced with a
bare curl straight to `:8101/tts`, so it was never a ProseCast fault.
`POST /free` on ComfyUI reclaimed 9.9 GB and synthesis went 500 -> 200 instantly.

- **`preflight.py` check 6 — GPU headroom** (chatterbox only, runs after the
  turbo check). Reads free VRAM from ComfyUI's `/system_stats` (device-level, so
  it sees every process). Below `COMFY_RECLAIM_BELOW_GB` (4.0) it POSTs ComfyUI's
  `/free` — **but only if `/queue` reports idle**, never out from under a running
  job. Aborts below `MIN_FREE_VRAM_GB` (1.5) with the diagnosis in the message;
  warns in the tight band. A failed probe warns and passes: a missing ComfyUI is
  not a reason to block a Chatterbox render. `COMFYUI_URL` overrides the host.
- **6 new tests** in `tests/test_preflight.py` (14 total, all passing): headroom
  OK is silent, full card aborts, reclaim-from-idle-ComfyUI path, busy ComfyUI is
  never freed, tight-but-usable warns only, unavailable stats warn only. The
  `book` fixture now mocks the three GPU probes so the existing 8 stay offline.
- ⚠️ **Open:** ~15.4 GB still held after the reclaim with ComfyUI torch at 0.0 and
  Ollama reporting no resident models. Unattributed — run `nvidia-smi` on Goldeye.
  A long-uptime Chatterbox leak is the leading theory. Restart the container
  before the rulebook render if the number hasn't moved.

## Session 2026-08-31 (Cowork) — American voice bank + Voices tab spec
- **The gap it closes:** the voice bank is VCTK-derived and **VCTK has ~4 American speakers
  out of 110** — which is why every US character kept landing on the same three voices.
- **`scripts/stage_librivox_dialects.py`** (new): builds Chatterbox reference clips from the
  LibriVox "Dialect and Accent" collections Vol 1 + Vol 2 — the only free corpus I found where
  English speakers are **explicitly labelled by US region**, and it is **public domain** (safe
  to ship in an open repo or a voice pack). ffmpeg + stdlib only, no numpy/soundfile, resumable.
  Per track it finds the passage body (RMS segmentation past the spoken LibriVox intro), cuts
  15 s, two-pass linear loudnorm to -20 LUFS, guesses gender from median F0, and scores
  listen-first quality (SNR measured against the *source* track's noise floor, not the clip's).
  On upload it seeds `voice_meta.json` from `MANIFEST.json` — and never overwrites a hand-set
  value.
- **`librivox_voices/` staged: 55 clips — 20 US-region + 35 international.** US coverage:
  NYC, Upstate NY, SE + W-Central Pennsylvania, Great Lakes, Minnesota, Kansas, Midwestern x3,
  Southern Indiana, South Carolina, South Louisiana, Texas / Metro Texas / North Texas, SoCal,
  Pacific NW, "western", Air Force brat. WAVs are gitignored (disposable audition material);
  `MANIFEST.json` + `SOURCES.md` are tracked — they are the provenance record.
- **Verified:** transcribed all 20 US clips with faster-whisper `tiny.en` — every one contains
  passage text, **zero** contain LibriVox boilerplate. That was the real risk in auto-cutting.
- **`docs/voice-sources.md`** (new): vetted source list with SHIP / PRIVATE / NEVER licence
  tiering, the Chatterbox reference-clip recipe (12-15 s, style-match the reference to the
  target, `exaggeration` and `cfg_weight` are coupled, pin a seed per character), and the note
  that CLAUDE.md's "Orpheus for sighs/laughs" tradeoff is stale — Turbo has inline
  paralinguistic tags but ignores `exaggeration`, so it is one or the other, not both.
- **`docs/CC_BRIEF_voices_tab.md`** (new): 8-step brief for the Voices view — notes/gender
  editing, audition + A/B, tags/filter/retire, and a vetted-sources panel. Names the five traps
  in the current code (glyph-suffixed display names, inconsistent overlay keys,
  process-lifetime `_chatterbox_voice_cache`, the `_readme` string key, and `_voice_pool` doing
  double duty for validation *and* auto-assignment — filtering hidden voices there would 400
  every save of a book that already uses one).
- **Nobody has published a Chatterbox voice pack.** Searched HF datasets/models/spaces and
  GitHub — the ecosystem hole is real, and the 20 licence-audited US voices staged here are
  most of a first release. Marketplace seed + launch story for the price of already-done work.
- **NEXT (Tyler, YELLOW):** audition `librivox_voices/*.wav` (start with the top of
  `MANIFEST.json` — sorted best-SNR-first), cull, **rename survivors before upload** (server
  filenames are permanent — AnimaForge and every `voice_map.json` reference them), then
  `python3 scripts/stage_librivox_dialects.py --from-dir librivox_voices --upload-to http://GIDEON_HOST:8101`
  and hit the re-check button in the header.
- Nothing committed to git this session — the working tree still carries the uncommitted
  2026-08-30 changes (`server.py`, `static/index.html`, `prosecast/tts_engine.py`,
  `tests/test_render_queue.py`). Read those before committing on top.

## Session 2026-08-27 (Cowork) — "On Air" UI skin
Direction chosen from lookbook + mockup round: golden-age radio ("On Air"),
modern info presentation. static/index.html gains a pure CSS token layer —
**zero JS/DOM logic changes**, all 103 tests unaffected, server.py untouched
(no /static mount exists, so fonts are embedded as data URIs; file 93KB→190KB).
- `<style id="theme-onair">` override block scoped to `html[data-theme="onair"]`:
  bakelite/walnut grounds, brass accent (replaces purple), signal red = errors
  + future RENDERING plaque, teal = done/connected, amber = needs-you.
  Fonts: Jost (UI), Limelight (wordmark only), IBM Plex Mono (numeric/status).
- Header toggle chip "skin: on air / classic", persisted in localStorage
  (`prosecast-theme`, default onair); early head script prevents theme flash.
- `.plaque` component (idle/queued/rendering) ships in the CSS, unused until
  the emoji swap below.
- Backup: `.backup/index_pre-onair_2026-08-27.html`; verified via headless
  Chromium screenshots of both skins against mocked /books + /chapters.
- **Follow-up (small):** swap the 5 emoji strings (⏳/⚡/⛔ in render buttons,
  index.html JS ~lines 886-2285) for `.plaque` states — after rulebook render.
- Design references: Claude artifacts "ProseCast Lookbook" + "ProseCast On Air".

## Session 2026-08-30 (Cowork) — Engine status strip + probe hardening
- **The bug it exists for:** the active engine is resolved ONCE at startup and
  cached for the process lifetime. `_chatterbox_reachable()` used a 2s one-shot
  probe — landing mid-synthesis on the shared box it times out, auto-detect
  falls through to macOS `say`, and the UI just quietly offers system voices
  with no indication anything is wrong. Cost an hour to spot.
- **Probe hardened:** 8s timeout, one retry (`prosecast/tts_engine.py`).
- **`GET /engine_status`** — engine, source (override vs auto-detected), live
  model/class + device, voice count, endpoint, and an `ok` flag that is FALSE
  for the `say`/`stub` fallbacks and for a turbo model. **`POST
  /engine_status/recheck`** drops the cached engine + voice list and re-probes
  — no server restart needed.
- **Status strip in the header** (first piece of the approved On Air redesign
  pulled forward): plaque showing the engine, teal/amber/red by state, detail
  line (`ChatterboxTTS · cuda · 3 voices`), and a ↻ re-check button that also
  reloads the open book so the cast drawer picks up the real voice list.
  Styled for both the classic and On Air skins.
- 4 new tests (107 total): say-fallback flagged, chatterbox ok, turbo flagged,
  recheck actually clears caches.
- **Operational note:** always start the server as
  `PROSECAST_TTS_ENGINE=chatterbox .venv/bin/uvicorn server:app` — it skips
  detection entirely AND stops auto-detect from picking the ElevenLabs key
  sitting in .env (paid credits) on any process that loads it.
- **Overnight discipline addendum:** to keep a Mac awake around an ALREADY
  running server, `caffeinate -i -w $(pgrep -f "uvicorn server:app" | head -1)`
  in a second terminal — no restart, releases when the server exits.

## Session 2026-08-28 (Cowork) — Play/script ingestion (multi-voice, zero LLM)
- **`scripts/play_to_ir.py`**: stage/screenplay text -> ProseCast IR directly.
  Acting-edition format (SPEAKER. dialogue / parenthesized stage directions /
  Scene headings -> chapters). Attribution is deterministic: dialogue conf 1.0
  method 'script_format'; directions -> NARRATOR (inline actor parentheticals
  like "(Covering.)" dropped by default); OCR-mangled speaker variants folded
  into the canonical cast by fuzzy match (GNES->AGNES etc.); front matter
  dropped by default. Input = pdftotext output OR OCR text for scans.
- **First play in the library:** She Kills Monsters (Young Adventurers
  Edition) — the uploaded PDF was a pure scan (no text layer), OCR'd at
  300dpi with tesseract in the Cowork container. 16 scenes, 1,435 blocks
  (1,157 dialogue), full 12-character cast + NARRATOR, 0 unresolved,
  ~76k chars (~1.5 h audio). `library/she_kills_monsters/ir.json` is ready
  to cast in the UI; OCR text kept at books/she_kills_monsters_ocr.txt
  (books/ stays gitignored).
- Known v1 limits: dual-speaker labels ("CHUCK & TILLY.") assign to one of
  the pair; OCR scans need the tesseract step outside ProseCast (Phase F
  candidate: accept .pdf uploads, auto-OCR when no text layer).

## Session 2026-08-26 pt2 (Cowork) — Phase C: safe whole-book render
Built to docs/ROADMAP_PHASES_C_F.md spec. Core pipeline semantics untouched
(ir.json, voice_map format, corrections.jsonl all unchanged).
- **C0 `prosecast/preflight.py`** — `preflight(slug, engine)` loud-abort
  checks before any batch render: server reachable (fast timeout), model is
  base-not-turbo, voice_map exists, voice_map engine matches active engine
  (the stale-EL-map landmine), every mapped voice resolvable on the live
  server. Warn-only: unresolved count, already-rendered chapters. 8 mocked
  tests (tests/test_preflight.py).
- **C1 `prosecast/renderer.py`** — render_chapter_resumable.py's proven loop
  extracted as the single render core: IR saved after every new block,
  continue-on-block-failure, throughput report, merge-what-rendered.
  `main.py generate_audio` is now a thin wrapper; the mid-chapter-crash
  cache-loss gap on the server path is closed.
- **C2 server queue** — thread-per-click replaced with one global FIFO worker
  (GPU constraint enforced structurally). Enqueue returns job_id immediately;
  preflight runs at dequeue per job; a failed/aborted job never kills the
  jobs behind it. `/render_status` keeps its shape + `queue_position`; new
  `GET /render_queue`; advisory `library/<slug>/render_state.json` snapshot.
  A jobs-lock guards status serialization vs worker mutation (caught as a
  real race by the test suite). UI: buttons show ⏳ Queued #N / Rendering…,
  book header button becomes "⚡ Render remaining (N)" when partially
  rendered, preflight aborts surface as ⛔ with the reason in the tooltip.
- **C3 resume semantics** — chapter done = wav exists AND no block needs
  re-synthesis under current engine+voice cacheKeys; done chapters skip,
  `?force=true` (and `--force`) re-renders. 6 queue tests
  (tests/test_render_queue.py): sequencing/no-overlap, skip, force,
  preflight abort, engine mismatch, render_state.
- **C5 CLI `scripts/render_book.py`** — preflight → loop → summary; defaults
  to chatterbox (never auto-detect), KeyboardInterrupt-safe, re-run = resume.
- **Not built:** C4 voice-ref mirror (needs the openapi.json download-route
  checkpoint against the live server first — trailing item, unchanged).

## NEXT (updated 2026-08-26)
1. **Smoke test** (Tyler, ~10 min): restart uvicorn (no --reload) → break
   voice_map on purpose → watch ⛔ preflight abort → restore → queue renders.
2. **Rulebook overnight:** `caffeinate -i .venv/bin/python
   scripts/render_book.py carl` (~30 h audio remaining ≈ 12-20 h GPU at
   Brigands' measured rate — may take two nights; re-run = resume).
3. **C4 mirror** then **Phase D (Parade)** per roadmap — D0 archive stale EL
   map, D1 LLM passes, D2 cast, D3 overnight, D4 align+export, D5 listen.

## Session 2026-08-26 (Cowork) — PDF -> audiobook (single-narrator mode)
- **PDF ingestion path built** (rulebooks/nonfiction, one narrator, no
  attribution needed): `scripts/pdf_to_txt.py` (pdftotext + cleanup: strips
  watermark/page numbers/TOC leaders/running heads/divider-art garble,
  reflows paragraphs, splits inline bullet runs, drops table/stat-block
  paragraphs, neutralizes body lines that would false-trigger book_parser's
  CHAPTER_RE) + per-book TOC json (`scripts/toc_carl_core.json`, 1-based
  PDF page starts). Output is a normal ProseCast TXT with 'Chapter N: Title'
  delimiters.
- **`scripts/flatten_to_narrator.py`**: post-IR pass — forces every block to
  NARRATOR, then merges consecutive blocks into ~900-char narration chunks
  (rulebook scare-quotes otherwise shred narration into one-word dialogue
  blocks -> choppy TTS). Backs up ir.json to ir.json.pre-flatten. --no-merge
  to skip merging. Core pipeline untouched.
- **First PDF book live:** Dungeon Crawler Carl RPG Core Rulebook (650 pp ->
  1.97M chars, 11 chapters, ~2.5k table paragraphs dropped; books/ is
  gitignored so the TXT stays local). Chapter 1 rendered on Chatterbox
  (original model, restarted on Goldeye after 3 weeks down) and passed
  Tyler's listen test. Remaining chapters render on demand; M4B export
  already handles partial books.
- Known rough edges (acceptable for v1): two-column stat-heavy pages
  (chs 8-10 source pages) can interleave order; digit-ratio table filter is
  heuristic. Revisit only if the listen suffers.


## Session 2026-08-01 (Cowork) — Brigands end-to-end + read-along
- **Brigands is fully end-to-end:** attributed (0 unresolved, alternating
  647→10), profiled, cast (mains by hand + gender-matched Auto-cast),
  chapters 4/9/17 rendered + Tyler listen: PASSES. First book through the
  whole flow.
- **⚡ Generate buttons:** un-rendered chapters get an explicit labeled
  render button (the old tiny ↺ was invisible-in-plain-sight). One render
  at a time — GPU is the bottleneck; render queue is a Phase C item.
- **Read-along built in three steps:** (1) /timeline un-truncated (120-char
  cap froze display on long blocks); (2) sentence-level estimated highlight
  + click-any-sentence-to-seek; (3) THE REAL FIX — word-accurate timings
  via faster-whisper forced alignment (Gideon :8100, OpenAI-compatible
  /v1/audio/transcriptions). scripts/align_words.py <slug> after rendering;
  sidecar word_timings.json per chapter; staleness fingerprint; UI shows
  exact 3-word karaoke when aligned, sentence estimate otherwise;
  'follow: on/off' pill (persisted) disables highlighting entirely.
  Whisper words are matched back to OUR text — mistranscription can only
  cost timing, never corrupt text. PROSECAST_WHISPER_URL /
  PROSECAST_WHISPER_MODEL config.
- Sequence per book is now: render (Chatterbox) → align (whisper) → listen.
- Suite at 89 tests, all offline.

## NEXT (resume here)
1. **Phase C** (~1 session): pre-flight assertions (Chatterbox model ==
   'original' + every voice_map voice still on server — shared-server
   insurance), local mirror of reference clips, book-level resume + render
   queue. Done = Parade renders overnight unattended.
2. **Parade run** (Phase D): scene+profile passes → cast via UI → overnight
   render → align → M4B → phone listen-through. Closes the PRD.
3. **Sampling pass:** Frankenstein / Moby Dick / Carousel, 2-3 chapters each.
4. **Pipeline-in-UI:** upload → auto attribution/profile with progress bar;
   Ollama/whisper URLs as settings; auto-align after render.
5. Parked small items: highlight-window tuning (wait for a second listener),
   corrections-replay eval harness, voice_meta → AnimaForge, provenance-aware
   prompting before any scope=all pass, dropdown-order preference.

## Session 2026-07-31 (Cowork)
- **Brigands dogfood fixes:** unresolved drawer got an in-drawer page view
  (📖 → `GET /ir/{slug}/block/{seg}/context?radius=N`, full surrounding IR
  blocks, "show more" widens to ±30). Fixed phantom badge counts (PATCH
  returned book-wide unresolved_count; UI painted it on the chapter badge —
  response now carries chapter_unresolved_count).
- **Attribution reality-check (Brigands):** 2,149 dialogue / 119 unresolved
  (5.5%); 647 blocks (30%) are `alternating` at conf 0.5 — the real
  specificity risk. **The v1 --llm pass had never run** (it was also nested so
  `--use-existing-ir --llm` silently skipped it — fixed).
- **One Ollama endpoint config:** `PROSECAST_OLLAMA_URL` steers attribution
  AND tag passes; default localhost:11434 (average-user setup), Tyler exports
  `http://GIDEON_HOST:11434` for Gideon.
- **Scene-batch attributor v2 built** (`prosecast/scene_attributor.py`,
  `--llm-scene` + `--llm-scope unresolved|low-confidence|all`): one call per
  scene chunk (≤15 targets), model sees whole conversations, tolerates qwen3
  <think> output, per-scene IR checkpointing. Tiebreaker enforced in every
  scope: manual + prefix/postfix tags + conf≥0.95 are never overwritten.
  Research grounding: NAACL 2025 (Deezer) — LLMs are now SOTA for literary
  quotation attribution. Model rec: gemma3:12b (already on Gideon, coexists
  with Chatterbox; llama3.1:8b is two generations stale, don't pull it).
- **Attribution campaign COMPLETE on Brigands (2026-08-01).** v1 per-block
  pass: 117/119 unresolved resolved (gemma3:12b, median conf 0.95). Scene
  pass (3 runs incl. one Tailscale-outage resume): `alternating` 647 → 10,
  533 changed + 100 confirmed, 633 blocks now `llm_scene_gemma3`, book at
  ZERO unresolved. Final methods: postfix 320 / spacy 769 / context 250 /
  scene 633 / llm-v1 103 / manual 37 / prefix 27 / alternating 10.
- **Also shipped this session:** merge-suggestion chips (deterministic
  token-overlap nominations, click-to-confirm via journaled /cast/merge,
  dismissals journaled); cast profiler (`--profile-cast`: gender/age/voice
  hints, title layer free + LLM layer, → ir.character_profiles, ♀/♂ chips);
  voice_meta.json (Tyler labeled all 34 voices f/m by ear; glyphs + per-
  character gender-sorted dropdowns); main/supporting tiers (≥25 lines =
  main, ★ toggle, journaled) + gender-matched "Auto-cast supporting";
  click-to-stop voice previews (▶/■); circuit breaker on LLM passes (abort
  after 3 consecutive connection failures — field lesson: Mac left the
  tailnet mid-run and burned hours in 180s timeouts).
- 82 tests pass (was 24); suite runs fully offline (Ollama mocked).
- **NEXT:** (1) `--profile-cast` run on Brigands (NOT yet run — chips empty
  until it is). (2) Cast drawer: cast mains by hand, Auto-cast supporting,
  Save; fix 'Annoyed' (2 lines, ch38) + bulk-demote ≤5 junk. (3) Render 2-3
  chapters, Tyler listens — ears are the final auditor on the ~10 remaining
  coin-flips and the whole attribution push. (4) Parked ideas: provenance-
  aware prompting before any scope=all run; shared voice_meta for
  AnimaForge; label new server voices in the filename at upload time.

## Session 2026-07-22
- Gideon rebooted (Tyler shutdown); all 13 services verified back, Chatterbox base
  model survived restart, no reload needed. Smoke render confirmed end-to-end.
- **Phase A fully CLOSED:** Tyler approved the full sample-chapter listen
  ("does the job"); Robert.wav retired as narrator material.
- **Voice audition:** 33 predefined server voices rendered through
  `scripts/audition_voices.py` → `output/audition/NN_*.wav` + manifest. Tyler's picks:
  narrator=bright-light-1, cast=bright-toronto-1 / clear-jersey-1 / deep-sydney-1.
- **Voice map now supports predefined voices:** `"predefined:<file>"` string prefix
  or dict pass-through (tts_engine); sample_book/voice_map.json uses the new cast;
  chapter re-rendered multi-voice. 15/15 tests pass.
- **Parade cast-noise data** (grounds Phase B design): 256 speakers, top 15 carry
  61% of 3,885 dialogue blocks; 177 speakers have ≤5 blocks (spaCy NER noise +
  walk-ons). Bulk "demote under N blocks" collapses 256 → ~40 in one action.
- **Agreed test scope:** 2–3 chapters per library book (not whole books) for the
  multi-genre validation pass; whole-book render is Parade-only, Phase C/D.

## Where it's at
**Phase A listen test DONE — Chatterbox quality PASSES** (2026-07-13, Tyler's ears).
Findings from a controlled A/B session against the live server (base model was
already loaded — YELLOW item 1 resolved):
- **speed_factor = echo.** The server implements it as a post-process time-stretch
  that smears audio into reverb. Only the speed≠1.0 renders echoed. `speed` is now
  REMOVED from `_map_chatterbox` and a regression test guards it (`test_map_tags_never_emits_speed`).
- **exaggeration 1.0 = trailing mouth-noise artifact.** Mapper now compresses
  intensity into exaggeration [0.20, 0.85] (0.85 angry / 0.55 neutral / 0.35 calm).
  Verified by ear: emotion clearly audible, no echo, no artifacts. Note: higher
  exaggeration natively speeds delivery slightly (generation-time, acceptable).
- **cfg_weight is a stability knob, not a pace knob.** Swept 0.25→0.9; the 0.5
  default beat every deviation (both directions read as faster/more robotic).
  Not emitted; `pace` is unmapped for chatterbox — text/punctuation carries pacing.
- **Robert.wav reference is weak** (fast, monotone) — clone inherits the clip's
  character. Gianna.wav renders sounded good. Voice quality = reference-clip
  quality; the voice pool needs better clips before casting a book.
- 13/13 chatterbox tests pass (updated for the new mapping).

Prior context (2026-07-10): chatterbox backend wired in tts_engine.py; contract in
docs/chatterbox-contract.md; PRD.md phases A→D unchanged.

## Where it was (2026-07-10)
**Chatterbox backend is wired** (CC brief 2026-07-10). The `chatterbox` engine now
exists in `prosecast/tts_engine.py` — no longer just the tag_mapper half:
- `_synthesize_chatterbox()` POSTs to the devnen server `/tts` in clone mode with a
  per-character reference clip, driving `exaggeration`/`cfg_weight`/`speed_factor` from
  `map_tags(tags, "chatterbox")`. Non-200s print the server body (no silent swallow).
- `test_chatterbox_connection()` GETs `/api/model-info` and prints `Connection OK ✓`, plus
  a **LOUD Turbo guard** — the server currently has the *turbo* model loaded, which IGNORES
  exaggeration/cfg, so emotion tags won't affect delivery until Tyler switches to base.
- `CHATTERBOX_VOICES` pool + `VoiceAssigner` branch (narrator=slot 0, round-robin), pool
  repopulated live from `/get_reference_files` at construction; static fallback otherwise.
- Auto-detect priority: ElevenLabs (if key) > chatterbox (if server answers) > piper/say/gtts.
- `tag_mapper._map_chatterbox` finished: emotion-arousal table nudges exaggeration/speed
  (high-arousal up, low-arousal down); `speed` renamed to `speed_factor` at the payload edge.
- Real server contract captured in **`docs/chatterbox-contract.md`** (built from the live
  `/openapi.json` — not the mapper's old assumptions).
- Smoke CLI: **`scripts/chatterbox_smoke.py`** (renders one line to `output/chatterbox_smoke.wav`).
- Tests: **`tests/test_chatterbox.py`** — 12 offline/mocked tests (mapper bounds, pool
  assignment, payload shape incl. the speed→speed_factor rename, Turbo guard). All green;
  no network, no precious data touched.

Prior context: **PRD.md** defines the dogfood MVP (Tyler listens to Parade end-to-end,
multi-voice, on phone). Phases: A) Chatterbox backend + listen test (THE GATE) → B) cast
review screen → C) resumable full-book render → D) listen-through.

## Next step
**Phase B cast screen is BUILT (2026-07-22, commit 0bd6c23) — needs Tyler's first real
workout on Parade.** Run the server with the free tier pinned:
`PROSECAST_TTS_ENGINE=chatterbox .venv/bin/uvicorn server:app --reload`
then open Parade → 🎭 Cast. Suggested flow: demote-all-≤5 (kills ~177 noise entries),
merge obvious aliases, cast the top ~15 from the audition voices, save, render 2–3
chapters. All demotes/merges journal to corrections.jsonl (flywheel data).

Then: **multi-genre sampling pass** — 2–3 chapters each from Frankenstein, Moby Dick,
Brigands, Carousel through the same cast-then-render flow.

(Voice pool note: 33 usable predefined server voices now; clone refs still just
Gianna/Robert. VCTK staging only if predefined set proves insufficient.)

**Shared-server heads-up (2026-07-13):** the Chatterbox instance on Gideon :8101 is
also used by AnimaForge dev. Hazards: model swaps (base↔turbo) kill emotion tags
mid-render; reference-clip deletions break voice maps; VRAM contention. Agreed
mitigations (not yet built): pre-flight assertions in the render path (model type
== original + all voice_map references still on server), local mirror of reference
clips in-repo. Fold into Phase C hardening.

## Blocked on
Nothing.
(Aside: LLM pass for Yumi/Frankenstein IR still needs Ollama reachable — llm_attributor
defaults to localhost:11434.)

## Backup (2026-06-12)
- **Where:** `NAS_USER@GIDEON_HOST:/mnt/bolt/backups/prosecast/library/` (ZFS dataset `bolt/backups`, owned by NAS_USER)
- **What:** ir.json + voice_map.json + corrections.jsonl per book; renders/ and exports/ excluded (disposable). No `--delete` — local mistakes can't propagate.
- **Re-run:** `./scripts/backup_library.sh` (works from Mac or a Cowork session; log in `.backup/last_backup.log`)
- **Nightly:** `scripts/com.prosecast.backup.plist` → 21:30 daily once installed (see Next step)
- **Auth:** dedicated key `.backup/prosecast_backup_ed25519` (gitignored), registered in NAS_USER's SSH keys as "prosecast-backup (Cowork session key)" — delete that line in TrueNAS UI to revoke
- Initial backup verified 2026-06-12: 61/61 files, checksum-clean, IR readable from server

## Notes
- **Pattern library (Tyler, 2026-07-13):** treat `animaforge/briefs/` as a reusable
  pattern library when writing CC briefs for this project — the **memory-shim brief**
  especially is close to copy-adapt.
- Run tests after touching attribution layers: `.venv/bin/pytest tests/ -v` (needs spaCy + en_core_web_sm; skips otherwise)
- All book paths via `prosecast/library.py` — `library/<slug>/{ir.json, voice_map.json, corrections.jsonl, renders/}`
- corrections.jsonl is append-only training flywheel data — never rewrite
- renders/ is disposable; everything else in a book dir is Tyler's labor — back it up
- Build queue: cast review screen, pipeline-in-UI jobs, per-chapter narrator dropdown
- Backup gap CLOSED — see Backup section above.
- **Money model shift (2026-07-10):** ProseCast follows the AnimaForge model — free local
  Chatterbox tier is complete; ElevenLabs is optional, **bring-your-own-key** (affiliate, no
  markup, user pays EL directly). No ProseCast-run premium/payment economy near-term; the
  marketplace/royalty/coin research is moonshot-only. Reframed in PRD.md + market-research doc;
  new user guide at `docs/elevenlabs-setup.md`.
