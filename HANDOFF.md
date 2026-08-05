# ProseCast — Session Handoff (2026-08-01)

For the next Claude/CC session: read this + STATUS.md, then pick up at
"Open loops" below. Repo state: clean, all work committed on `main`
(through `58158d0`). **Project is PAUSED** (Tyler → ComfyUI work) at a
deliberately clean stopping point: nothing half-built, 89 tests green.

## Where the project stands

**Brigands & Breadknives is the first book through the ENTIRE flow, and it
passed Tyler's listen.** Attribution (0 unresolved book-wide), character
profiles, gendered casting, chapter renders (4/9/17), whisper-aligned
word-accurate read-along. Phase A closed (07-13), Phase B closed in
practice this week. Phase C (safe whole-book render) is designed, unbuilt —
it is the next build.

## This session's commits (2026-07-31 → 08-01)

* `70448e7` Unresolved drawer: in-drawer 📖 page view (`/ir/{slug}/block/{seg}/context`)
* `6dc87ff` Fix phantom badge counts (PATCH returned book-wide unresolved; UI painted it per-chapter)
* `2eba66b` `PROSECAST_OLLAMA_URL` steers attribution AND tag passes; `--llm` un-nested so it works with `--use-existing-ir`
* `4c16b35` **Scene-batch attributor v2** (`--llm-scene`, `--llm-scope unresolved|low-confidence|all`)
* `e623763` Cast screen: click-to-confirm merge suggestion chips (deterministic token-overlap; dismissals journaled)
* `d7367e3` **Cast profiler** (`--profile-cast`): gender/age/voice hints → `ir.character_profiles`, ♀/♂ chips
* `1cd09f0` `voice_meta.json` overlay (glyphs in dropdowns, per-character gender-sorted options)
* `842dfaa` Main/supporting **tiers** (≥25 lines = main, ★ toggle) + gender-matched **Auto-cast supporting**
* `97ae9f7` Voice previews: click-to-stop toggle (▶/■)
* `a7a9518` Tyler labeled all 34 voices f/m by ear (19 m / 15 f)
* `4236501` **Circuit breaker**: LLM passes abort after 3 consecutive connection failures
* `fbda4ab` Chapter rows: explicit **⚡ Generate** button for un-rendered chapters
* `30740dc`+`02fc172` Read-along: timeline un-truncated; sentence highlight + click-any-sentence-to-seek
* `44f7f35` **Whisper word alignment** (`scripts/align_words.py`): word-accurate karaoke via Gideon :8100
* `b9afa7a` `follow: on/off` pill (persisted) — disables all highlight tracking
* `8bb8664`/`58158d0` STATUS chapter-closes

## Attribution campaign result (the week's headline)

Brigands: 2,149 dialogue blocks. v1 per-block pass resolved 117/119
unresolved (gemma3:12b, median conf 0.95). Scene-batch v2 over 3 runs:
`alternating` 647 → 10, 533 changed + 100 confirmed. Final methods:
postfix 320 / spacy 769 / scene 633 / context 250 / llm-v1 103 / manual 37 /
prefix 27 / alternating 10. **Tyler's ears validated the result.**

## How to run (Tyler's Mac)

```bash
cd ~/dev/prosecast
PROSECAST_TTS_ENGINE=chatterbox .venv/bin/uvicorn server:app --reload
# → http://localhost:8000   (env var REQUIRED — else auto-detect burns EL credits)
```

Per-book flow (mostly buttons now):
1. Ingest EPUB (UI upload) → rule attribution runs automatically.
2. LLM passes (terminal, ~30 min total, Mac must stay awake — use `caffeinate -i`):
   ```bash
   PROSECAST_OLLAMA_URL=http://GIDEON_HOST:11434 .venv/bin/python main.py <Name> \
     --use-existing-ir --llm-scene --llm-scope low-confidence --profile-cast \
     --llm-model gemma3:12b --ir-only
   ```
3. Cast drawer: accept merge chips → Demote all ≤5 → hand-cast mains
   (dropdowns gender-sorted) → **Auto-cast supporting** → Save.
4. Render: **⚡ Generate** per chapter (ONE at a time — GPU is the bottleneck).
5. Align: `PROSECAST_WHISPER_URL=http://GIDEON_HOST:8100 .venv/bin/python scripts/align_words.py <slug>`
6. Listen; read-along via click on the player text bar.

Tests: `.venv/bin/pytest tests/ -v` (89; all offline, Ollama/whisper mocked).

## Open loops (priority order)

1. **Phase C** (~1 session): (a) pre-flight assertions before batch renders —
   Chatterbox model_type == "original" AND every voice_map voice still on the
   server (it's SHARED with AnimaForge; swaps/deletions are the failure
   modes); (b) local mirror of clone reference clips in-repo; (c) book-level
   resume + server-side render queue (click Generate on N chapters, they
   run sequentially). Done = Parade renders overnight unattended.
2. **Parade / Phase D:** scene+profile passes → cast via UI → overnight
   render → align → M4B export (built) → Tyler listens on phone. Closes the PRD.
3. **Sampling pass:** Frankenstein / Moby Dick / Carousel, 2-3 chapters each.
   Frankenstein has IR but NO voice_map and needs the LLM passes first.
4. **Pipeline-in-UI:** upload → attribution/profile auto-run with a progress
   card (job-runner pattern already exists for renders); Ollama/whisper URLs
   → settings; auto-align chained after each render.
5. Parked: highlight-window tuning (wait for a second listener's opinion);
   corrections-replay eval harness; voice_meta shared with AnimaForge;
   provenance-aware prompting REQUIRED before any `--llm-scope all` run;
   alphabetical-dropdown preference option.

## Key technical facts (hard-won this week — do not relearn)

* **Ollama config:** one env var for both LLM passes: `PROSECAST_OLLAMA_URL`
  (default localhost — the average-user tier). gemma3:12b is the workhorse:
  already on Gideon, coexists with resident Chatterbox, no `<think>` output.
  qwen3 models emit `<think>` — both scene + profile parsers strip it, but
  v1 (`--llm`) does NOT (num_predict 64 would truncate; use scene pass).
* **Scene pass mechanics:** one call per scene chunk (≤15 targets); scope
  draws the AI's jurisdiction (unresolved / low-confidence [<0.6, i.e. the
  alternating band] / all). PROTECTED always: manual, prefix/postfix tags,
  conf ≥0.95. Accepted blocks aren't re-targeted → re-runs resume free.
  Circuit breaker: 3 consecutive connection failures → abort, progress saved.
* **Passes are NETWORK calls:** Mac → Tailscale → Gideon. Walking away with
  the laptop = outage (learned the hard way; breaker added). `caffeinate -i`.
* **Whisper alignment:** OpenAI-compatible `POST /v1/audio/transcriptions`
  on :8100 (verified via openapi.json). Whisper words are sequence-matched
  to OUR text — mistranscription only costs timing, never corrupts text.
  Sidecar `word_timings.json` per chapter blocks dir; staleness fingerprint
  (total wav duration) auto-invalidates after re-renders → re-run align.
  Model default `Systran/faster-whisper-small` (env `PROSECAST_WHISPER_MODEL`).
* **Voice labels** live in `voice_meta.json` (repo root, keyed by display
  name/clone stem). NEVER rename wavs on the Chatterbox server — shared with
  AnimaForge + voice_maps reference filenames. New server voices: put the
  gender in the filename at upload time.
* **"Auto" voice for chatterbox round-robins CLONE REFS only (2 voices) —
  effectively broken.** Auto-cast supporting (cast drawer) is the real auto:
  materializes gender-matched predefined picks into voice_map at Save.
* Renders: one at a time (GPU-bound; parallel jobs just interleave slower).
  Blocks cache by text+voice+engine — re-attribution after render re-synths
  only changed blocks; interrupted renders resume cheap.
* Prior facts still true: never emit speed/speed_factor to Chatterbox;
  exaggeration [0.20,0.85]; cfg_weight stays 0.5; `predefined:<file>` vs
  bare-filename voice map strings; Chatterbox :8101; ~24s per audio-minute.

## Cowork-session gotchas (if next session is Cowork)

* Repo mounts at `/sessions/<id>/mnt/prosecast` (device_bash, NO network).
  Edit flow: device_stage_files → edit in container → device_commit_files.
  Cloud container: `pip install --break-system-packages fastapi httpx
  python-multipart pytest requests miniaudio` then `PROSECAST_TTS_ENGINE=chatterbox
  python3 -m pytest tests/`.
* Git stale locks persist: `mv` locks into `.git/_to_delete/` (rm fails on
  the mount), commit, mv again; use `GIT_OPTIONAL_LOCKS=0 git status`.
  Commits DO land despite unlink warnings.
* Cloud/VM can't reach Gideon (Tailscale) — live LLM/whisper/render runs are
  Tyler-side only; everything else is mockable offline.

## Protocol reminders

* **PUSH TO GITHUB** — this session's ~18 commits are local-only until Tyler
  runs `git push` (canonical repo is GitHub; CLAIY/Mac sync through it).
* STATUS.md updated at pause (single-writer); run gideon-infra
  `scripts/status_rollup.py` if the DASHBOARD needs refreshing.
* corrections.jsonl is append-only flywheel data — never rewrite. It now
  also carries merge-dismissals and tier changes (all labeled training data).
* Nightly library backup to Bolt at 21:30 covers ir/voice_map/corrections.
