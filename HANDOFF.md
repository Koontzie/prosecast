# ProseCast — Session Handoff (2026-07-22)

**For the next Claude/CC session: read this + STATUS.md, then pick up below.**
Repo state: clean, all work committed on `main` (through `de3a857`).

## Where the project stands

**Phase A (Chatterbox engine + listen gate): CLOSED. Quality approved by Tyler.**
**Phase B (cast review screen): BUILT + first round of real-use fixes in. Currently being dogfooded.**

Pipeline is end-to-end healthy: EPUB → IR (99.8% attribution on Parade) → emotion
tags (Gideon mistral:7b) → Chatterbox multi-voice render (~2.5× realtime) → M4B.

## This session's commits (2026-07-22)

- `6dc1f73` Phase A closed; 33-voice audition; Tyler's picks cast on sample book
- `0bd6c23` Phase B cast screen: `/cast` (ranked), `/cast/demote` (bulk + ≤N),
  `/cast/merge`, chatterbox voices in `/voices`+preview, 🎭 drawer UI
- `d5a9eca` Fixes from Tyler's first cast session: NARRATOR as merge target,
  per-character context expander (`/character/{name}/lines`), unsaved voice
  picks survive merges/demotes
- `de3a857` Render jobs pin the active engine — was auto-detecting ElevenLabs
  (credit burn) despite the UI running chatterbox

## How to run (Tyler's Mac)

```bash
cd ~/dev/prosecast
PROSECAST_TTS_ENGINE=chatterbox .venv/bin/uvicorn server:app --reload
# → http://localhost:8000
```
The env var is REQUIRED for free-tier dogfooding: without it, auto-detect sees
ELEVENLABS_API_KEY in .env and every preview/render costs credits.

Tests: `.venv/bin/pytest tests/ -v` (24 tests; cast endpoints need fastapi+httpx+python-multipart).

## Open loops (in priority order)

1. **Tyler is mid-dogfood on the cast screen.** Parade (256 chars) felt too heavy
   to groom in one sitting; he's trying a smaller book first (Frankenstein or
   Brigands are the sane ones). Expect more UX feedback — treat it like the
   d5a9eca round: small, fast fixes.
2. **Multi-genre sampling pass (agreed scope):** 2–3 chapters per book — Parade,
   Frankenstein, Moby Dick, Brigands, Carousel. Flow per book: cast screen trim →
   assign voices → render chapters (`scripts/render_chapter_resumable.py <slug> <ch>`)
   → Tyler spot-listens. NOT whole books; whole-book render is Parade-only (Phase C/D).
3. **Phase C hardening (unbuilt, designed):** pre-flight assertions before batch
   renders — model type == "original" AND all voice_map reference files still on
   server (the Chatterbox instance is SHARED with AnimaForge dev; model swaps and
   reference deletions are the failure modes). Plus local mirror of reference clips.
4. **Incremental re-render works** (block cacheKey = text+voice+engine; fix a line
   → regen chapter → only that block synthesizes). Possible polish: auto-regen
   after correction, "N rendered / M cached" in render_status.
5. Later/parked: tag editing UI (4b), per-chapter narrator dropdown (Carousel),
   fuzzy alias matching (cast-screen merge covers it manually), VCTK clone clips
   (33 predefined voices probably suffice).

## Key technical facts (hard-won this month — do not relearn)

- **NEVER emit `speed`/`speed_factor` to Chatterbox** — server time-stretch =
  echo/reverb. Regression test guards it (`test_map_tags_never_emits_speed`).
- **exaggeration band [0.20, 0.85]** — 1.0 adds trailing mouth-noise artifacts.
  Higher exaggeration natively speeds delivery slightly (fine).
- **cfg_weight: leave at server default 0.5** — swept 0.25–0.9 by ear; every
  deviation sounded worse. It is not a pace knob. `pace` is unmapped for chatterbox.
- **Voice map strings:** `"predefined:<file>.wav"` = server built-in voice;
  bare filename = clone reference. Dict entries pass through as raw engine cfg.
- **Clone quality = reference-clip quality** (Robert.wav is fast/monotone — retired).
- Chatterbox server: `http://GIDEON_HOST:8101` (base model survives reboots);
  tag pass: Gideon Ollama `:11434` mistral:7b; LLM attribution: localhost:11434.
- Render throughput ≈ 24s per audio-minute (2.5× realtime) → Parade overnight, easily.

## Cowork-session gotchas (if next session is Cowork, not CC-on-Mac)

- Repo in sandbox: `/sessions/<session>/mnt/prosecast`. The `.venv` is macOS-only —
  use system `python3` (deps present incl. spaCy? no — spaCy tests skip; fastapi/
  httpx/python-multipart need `pip install --break-system-packages`).
- Background processes (`nohup`) DIE when a bash call returns. For long renders
  use `scripts/render_chapter_resumable.py` in ≤40s slices — it saves cacheKeys
  after every block and resumes exactly where it stopped.
- Git in the mounted repo throws stale-lock errors (`index.lock`/`HEAD.lock`,
  "Operation not permitted"): call the cowork file-delete permission tool, then
  `find .git -maxdepth 2 -name "*.lock" -delete` and retry. Commits do land.
- `library/` is gitignored (precious data; nightly rsync backup to Bolt at 21:30
  via scripts/backup_library.sh). corrections.jsonl is append-only — NEVER rewrite.

## Protocol reminders

- Update STATUS.md at chapter-close (single-writer; run scripts/status_rollup.py
  in gideon-infra afterward if the DASHBOARD needs it).
- `animaforge/briefs/` is a pattern library for CC briefs — the memory-shim brief
  is close to copy-adapt (Tyler, 2026-07-13).
- Run `.venv/bin/pytest tests/ -v` after touching attribution or chatterbox layers.
