# PROSECAST — STATUS

**Status:** ACTIVE — Phase C shipped 2026-08-26 (same day as PDF ingestion).
Suite at 103 tests. Next: Tyler's smoke test, then overnight rulebook render;
C4 voice-ref mirror and Phase D still open.
**Updated:** 2026-08-27

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
