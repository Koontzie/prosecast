# ProseCast

A multi-voice audiobook app: parses a book (EPUB/TXT/PDF, scans via OCR),
works out who is speaking, lets the user cast a voice per character, renders
with local TTS (Chatterbox first; `say`/piper/ElevenLabs also wired), and plays
it back with inline correction and word-level read-along. Local-first: the book
never leaves the machine.

## Read first, every session

1. **`HANDOFF.md`** — where the project stands, what is real and unfixed, and
   the hard-won facts. Supersedes anything below that contradicts it.
2. **`STATUS.md`** — the running log, newest entry at the top; update it at
   chapter-close (single-writer).
3. **`docs/ROADMAP_PHASE_E_UI.md`** — the current phase's spec and parking lot.

The rest of this file is the standing technical reference (architecture,
attribution layers, tag schema, engine notes). It is accurate for what it
covers but does not track session state — HANDOFF and STATUS do.

## Three working rules (each learned the expensive way — see HANDOFF)

1. **Commit to the Mac as you go.** Work that exists only in a cloud container
   is not work; a whole feature was lost that way on 2026-09-04.
2. **Never hand-write a UI fixture or mock.** `tests/fixtures/*.json` come from
   the live endpoints via `scripts/refresh_ui_fixtures.py`, and tests fail if
   they drift.
3. **After touching `static/index.html`, run all four checks in `tests/ui/`.**
   They need Playwright — installed in the Mac venv now, not in the device VM.

Also: every `ir.json` write goes through `lib.write_json_atomic()`; all book
paths go through `prosecast/library.py`; `corrections.jsonl` is append-only;
never rename WAVs on the Chatterbox server; never emit `speed` to Chatterbox.

## Where it stands (2026-09-06)

Phase E is complete. Any format in from the UI, casting, safe whole-book
renders, reader view, Setup page with probes, `config.json`, README + install
story + `docs/PHILOSOPHY.md`, and — as of E3 — the AI attribution pass and
word alignment as jobs behind buttons on a Pipeline card. **Nothing in the
product requires a terminal any more.** As of **E6 (09-06)** the first run
opens a **four-step wizard that ends by reading you the sample book** —
`POST /books/sample` plus `#firstrun-modal-overlay`; the Setup page is
unchanged apart from a ↻ Run setup again button. It fires while **no engine
has been chosen** (`voice_engine.source == "default"` or the value is still
`auto`), not on a missing `config.json` — `SETUP.sh` writes one, and since
E6.8 `config.example.json` leaves `tts_engine` on `auto`. Git history was rewritten on
2026-09-05 to scrub the home-network host (commit hashes quoted in older
STATUS/HANDOFF entries predate the rewrite). **Next: the cast exchange** (see
PHILOSOPHY.md) and the four HANDOFF findings; then cover art and in-book
images (roadmap parking lot).

## Architecture

```
EPUB/TXT/PDF → ingest.py (book_parser / pdf_ingest / ocr / play_parser)
            → ir_generator.py (+ scene_attributor / llm_attributor, cast_profiler, tag_generator)
            → renderer.py + tts_engine.py (tag_mapper at render time)
            → library/<slug>/renders/  → word_aligner.py → m4b_export.py
```

`server.py` (FastAPI) + `static/index.html` (single-file UI, On Air skin default)
sit on top; `main.py` is the CLI over the same modules. `prosecast/config.py`
resolves *defaults < config.json < env vars*; `setup_probe.py` backs the Setup
page. `preflight.py` guards GPU co-residency before renders.

### Core Files

- **`prosecast/ingest.py`** — `prepare(path)` (format gate, mode guess, scan report, PDF chapter detection) and `run(...)` (the ingest job: extract → chapters → attribute). Runs on its own thread, never the render queue.
- **`prosecast/book_parser.py`** — EPUB (stdlib spine-based) and TXT → chapters.
- **`prosecast/pdf_ingest.py`** — PDFs on PyMuPDF: bookmarks → printed TOC → heading sizes → fixed split; generic watermark/running-head filter; `reflow()`.
- **`prosecast/ocr.py`** — scanned PDFs: PyMuPDF rasterizes, tesseract reads, output reflowed. Cached at `books/<stem>_ocr.txt`.
- **`prosecast/play_parser.py`** — script-format (play) mode.
- **`prosecast/ir_generator.py`** — the 6-layer rule-based attribution pipeline → IR JSON (below).
- **`prosecast/scene_attributor.py`** / **`llm_attributor.py`** — the Ollama passes: scene-batched (v2, preferred) and per-block (v1).
- **`prosecast/cast_profiler.py`** — gender/age/voice hints per character for blind casting.
- **`prosecast/tag_generator.py`** / **`tag_mapper.py`** — emotion/tone tags on every block; mapped to engine parameters at render time.
- **`prosecast/pipeline.py`** — the AI pass and word alignment as callable jobs with progress callbacks; `server.py` runs them on a second worker (`/pipeline/{slug}`), never the render queue. Render and AI pass refuse to overlap on one book.
- **`prosecast/renderer.py`** — the render queue: one at a time, resumable, per-block cache, atomic IR writes.
- **`prosecast/tts_engine.py`** — backends: `chatterbox` (primary), `elevenlabs`, `piper`, `say`, `gtts`, `stub`.
- **`prosecast/word_aligner.py`** — word timings via an OpenAI-compatible `/v1/audio/transcriptions` server (faster-whisper / Speaches).
- **`prosecast/m4b_export.py`** — chapterized `.m4b` via ffmpeg.
- **`prosecast/library.py`** — the only place book paths are built: `library/<slug>/{ir.json, voice_map.json, corrections.jsonl, renders/, exports/}`.
- **`prosecast/config.py`**, **`setup_probe.py`**, **`preflight.py`** — config, Setup-page probes, GPU preflight.

### CLI

The UI is the primary surface; the CLI drives the same modules. Nothing is CLI-only since E3:

```bash
bash SETUP.sh                                           # venv, deps, spaCy model (verified), config.json, tools, smoke test
.venv/bin/uvicorn server:app --port 8000                # the app; first run opens the setup wizard
.venv/bin/python main.py "<book title>" --use-existing-ir --llm-scene   # AI attribution pass — also available in the UI (E3)
.venv/bin/python scripts/align_words.py <slug>          # word timings after a render — also available in the UI (E3)
.venv/bin/python main.py --sample --tts stub            # silent smoke test
.venv/bin/pytest tests/ -q                              # ~245 tests; spaCy/tesseract-gated ones skip cleanly
```

## IR Attribution Pipeline (ir_generator.py)

Six layers, each filling gaps left by the previous:

| Layer | Name | Method | Confidence |
|-------|------|---------|------------|
| 0 | Segmentation | Split on `"..."` quotes | — |
| 1 | Explicit tag | `"said X"` / `"X said"` regex (postfix + prefix + context scan) | 0.82–0.93 |
| 2 | spaCy NER | PERSON entities in ±2 narration blocks | 0.70 |
| 3 | Alias collapse | `"Mr. Bennet"` / `"Bennet"` → same character | — |
| 4 | Alternating | Flip from last speaker in 2-person exchange; seeded from previous chapter | 0.50 |
| 5 | Mark unresolved | `speaker=UNKNOWN, confidence=0.0` | 0.0 |
| 5.5 | Narrator POV | `"I said/asked"` → `--narrator` character | 0.85 |

### Key implementation details

- Possessives stripped from NER: `"Hew's"` → `"Hew"` before adding to character set
- Lowercase word filter: rejects `"Darcy at"` / `"Jane warmly"` from being treated as names
- `PREFIX_RE` matches trailing `.!?` so `"Logan said."` correctly attributes the preceding line
- Chapter tail speakers (last 3 confident dialogue blocks) are carried into the next chapter to seed the alternating heuristic across chapter boundaries
- `--narrator NAME` resolves all first-person `"I said/asked"` unresolved blocks to the POV character

## Attribution Benchmarks

| Book | Dialogue blocks | After rules | After LLM | Final unresolved |
|------|----------------|-------------|-----------|-----------------|
| Sample (P&P excerpt) | 26 | 0 (100%) | — | 0 |
| Carousel b8 Ch17-30 | 959 | 103 (89.3%) | not run | 103 |
| A Parade of Horribles (--narrator Carl) | 3,890 | 388 (90.0%) | 6 (99.8%) | **6** |

**Phase 2 complete.** The full attribution pipeline (rule-based + LLM) achieves 99.8% on a 100-chapter LitRPG novel. The LLM pass resolved 382/388 blocks the heuristics missed (avg confidence 0.811). The 6 remaining unresolved blocks are reserved for the correction UI.

## Test Books

| Book | Role | Notes |
|------|------|-------|
| A Parade of Horribles | **Primary test book** | Clean EPUB, 115 chapters, 99.8% attribution accuracy. Use this for feature validation. |
| Carousel B8 Ch17-30 | Stress test only | Source is copy-pasted web chapters reformatted as EPUB with minimal structure. Mostly first-person POV (narrator = protagonist, so most dialogue is self-narration). Occasional interlude chapters switch POV. Incomplete book. High unresolved count (103) is expected given the format, not a pipeline failure. |
| Sample (P&P excerpt) | Smoke test | Built-in sample, always 0 unresolved. Use for quick sanity checks. |

## Phase status

Live status lives in `HANDOFF.md` (table at the top) and `STATUS.md`. Summary as of 2026-09-05:

| Phase | What | State |
|---|---|---|
| 1–4a (2026-05/06) | parse → IR → TTS → WAV; LLM pass; web UI playback/correction/casting; emotion tagging | ✓ |
| A–D (2026-07/08) | Chatterbox backend, cast screen, safe whole-book render, word-level read-along | ✓ |
| E1, E2.1–E2.4, E4.1–E4.3 (2026-09-03/04) | reader view; ingest wizard incl. PDF review + OCR; config.json, probes, Setup page | ✓ |
| E5 (2026-09-05) | README, SETUP.sh, PHILOSOPHY.md, pre-publish history scrub | ✓ |
| E3 (2026-09-05) | pipeline-in-UI: AI pass + align as jobs behind buttons, on a second worker | ✓ |
| E6 (2026-09-06) | first-run wizard: engine → probe → optional brains → hears the sample book | ✓ |
| 4b / 4c | tag editing UI; tags actually reaching ElevenLabs | open (4c is one of the Codex findings in HANDOFF) |
| later | cast exchange (PHILOSOPHY.md), cover art + in-book images (roadmap parking lot), Flutter app | direction |

## Known remaining issues

The four real, unfixed findings from the 2026-09-04 external review are in `HANDOFF.md` → "Known-real, not yet fixed". Older, still true:

1. **Noisy character list** — spaCy tags LitRPG skill names as PERSON. The Voices panel delete (reassigns to NARRATOR) is the workaround; a per-book denylist would be the fix.
2. **Alternate spellings** (`Kimberly` / `Kimberley`) are not collapsed — needs Levenshtein ≤ 2 in `build_alias_map()`.
3. **No sentence-boundary awareness in segmentation** — a quote split across a paragraph break can create a false dialogue block.
4. **Multiple first-person POV narrators** — `--narrator` takes one name; agreed direction is a per-chapter narrator dropdown, not automatic detection.

## UI Polish — Future Items

- **Book-flipping loading animation** — replace the plain "Processing…" spinner on the "+ Add Book" button (and any other long-running operations) with a page-flipping book animation. Framer Motion or a pure CSS keyframe sequence. Low priority but on-brand for an audiobook product.

## Future Considerations


- **Comic/manga reader** — OCR on panel images to extract speech bubble text, attribute to visual characters, read via TTS. Potentially a browser extension (hover-to-read bubbles). Separate product surface from the main app, revisit after core product has traction.

- **Genre-specific attribution tuning** — test attribution pipeline across different book genres (literary fiction, thriller, LitRPG, romance, children's) and tune regex/LLM prompts per genre. Do this testing cycle once the correction UI exists so errors can be fixed interactively rather than by editing JSON.

## Phase 4: Emotion & Tone Tagging Pipeline

**Status: Implemented.** Tag pass runs after attribution, before TTS. Tags are a creative spec — decoupled from audio generation.

### Tag Schema

Every IR block gains a `"tags"` field after the tag pass. Dialogue blocks:

```json
"tags": {
  "action": "to evade direct answer",
  "emotion": "cautious reserve",
  "intensity": 0.3,
  "pace": "measured",
  "tag_method": "gideon-mistral"
}
```

Narration blocks (no `action`):

```json
"tags": {
  "emotion": "contemplative tension",
  "intensity": 0.5,
  "pace": "slow",
  "tag_method": "gideon-mistral"
}
```

Fields:
- `action` — actor-facing actioning verb starting with `"to "`. Stanislavski/Meisner language. NOT an emotion label.
- `emotion` — short descriptive phrase for human readers (2–5 words). Distinct from `action`.
- `intensity` — 0.0 (near-whisper) to 1.0 (maximum force)
- `pace` — one of: `slow` | `measured` | `brisk` | `urgent`
- `tag_method` — provenance string for the training flywheel

### Gideon Dependency

Tag pass requires Gideon (Tyler's home server at `GIDEON_HOST`) running Ollama with `mistral:7b`. Check: `curl http://GIDEON_HOST:11434/api/tags`. Main LLM attribution pass (`--llm`) uses localhost:11434 — these are separate.

Tag pass is gracefully skipped if Gideon is unreachable.

### Tag Mapping Layer (`prosecast/tag_mapper.py`)

`map_tags(tags, engine_name) → dict` — pure function, called at render time.

| Engine | Output |
|--------|--------|
| `elevenlabs` | `voice_settings`: stability/style from intensity; pace adjusts stability |
| `orpheus` | `prefix_tag`: `<laugh>`, `<sigh>`, `<gasp>` etc. mapped from action |
| `chatterbox` | `exaggeration` (0–1) + `speed` multiplier |
| `say`, `gtts`, `piper`, `stub` | `{}` — no tag support |

IR stores abstract tags once. Engine format translates at render time. Swapping engines requires no changes to stored IR.

### Tag Corrections → Training Flywheel

When the tag editing UI (Phase 4b) exists, user tag corrections get logged the same way attribution corrections do. Tag edits train the tagging model alongside the attribution model. The flywheel: more corrections → better fine-tuned local model → fewer corrections needed.

### Local TTS Tier — Engine Decision (Orpheus vs Chatterbox)

**Decided (2026-07/08): Chatterbox, base model, is the primary local engine.** The Setup page and connection check warn loudly on the Turbo variant because it ignores `exaggeration`. The analysis below is kept for the record.


Tyler is standing up Chatterbox-Turbo on the Gideon server. The original CLAUDE.md recommended Orpheus as the local expressive tier. Here's the current tradeoff:

**Orpheus**
- Structured inline tags: `<laugh>`, `<chuckle>`, `<sigh>`, `<cough>`, `<sniffle>`, `<groan>`, `<yawn>`, `<gasp>`
- Predictable: tags directly map to specific nonverbal sounds
- Good fit for audiobooks where occasional emotional cues (sighs, laughs) matter more than full prosodic control
- ~8–12 GB RAM quantized; can run on the Gideon server
- Gap: limited to the 8 supported nonverbal tags — can't shape intensity, pacing, or overall delivery

**Chatterbox-Turbo**
- `exaggeration` parameter (0.0–1.0): amplifies emotional intensity across the whole delivery
- Voice cloning: can generate voices that match a target speaker from a short reference clip
- Broader expressive range than Orpheus for dramatic/high-intensity content
- Gap: no structured tag system — intensity is global, not per-type (can't specify "sigh" vs "laugh")
- API details still stabilizing (speed parameter is a stub in the mapper)

**Recommended path:**
Start with Chatterbox-Turbo for the first real render test, since Tyler is already setting it up. The `exaggeration` ↔ `intensity` mapping is a clean 1:1 relationship, and voice cloning means we can assign distinct character voices without the ElevenLabs credit cost. If the lack of specific nonverbal tags (sighs, laughs) is limiting in practice, layer Orpheus on top for those specific action types.

Long-term: Fish Audio S2's natural-language tag format (`[whisper in small voice]`) is the most powerful approach — watch it for stability before committing.

```
say          — fallback only, no installation required
Chatterbox   — free local tier, exaggeration + voice cloning, primary expressive engine
Orpheus      — secondary local option if structured nonverbal tags (laugh/sigh/gasp) are needed
ElevenLabs   — premium, best quality, costs credits
Fish Audio S2 — watch for future upgrade (natural-language tag format)
```

### TTS Engine Tag Support Summary

| Engine | Tag system | Notes |
|--------|-----------|-------|
| macOS `say` | None | Fallback only |
| Kokoro | None (punctuation-driven prosody) | Good neutral narration, no expressive control |
| Orpheus | Structured: `<laugh>`, `<chuckle>`, `<sigh>`, `<cough>`, `<sniffle>`, `<groan>`, `<yawn>`, `<gasp>` | Predictable nonverbal sounds; ~8–12 GB RAM |
| Chatterbox-Turbo | `exaggeration` (0–1) + speed | Voice cloning, broader range, less structured |
| Bark | Inline cues: `[laughs]`, `[whispers]` | Nonverbal sounds, less predictable |
| Fish Audio S2 | Natural language: `[whisper in small voice]` | Most powerful long-term; watch for maturity |
| ElevenLabs | `voice_settings`: stability, style, similarity_boost | Premium, best quality |

## Future Development

### Actor Companion App (Sister Project)

A separate app built on the same core. Most of the ProseCast stack transfers directly:

- **Shared:** script parsing, character attribution, multi-voice TTS, IR format, correction loop, tagging pipeline
- **New:** line memorization mode, cue detection, scene analysis, beat/objective tagging
- **Scene partner mode:** app reads all other characters with appropriate actioning; actor responds live
- **Coach mode:** flags lines where the actor's chosen action doesn't match the scene objective
- Script analysis uses actioning verbs (Stanislavski/Meisner), not emotion labels — same reason as above
- Same tagging pipeline as ProseCast; different output surface

Build after ProseCast's correction loop and tagging pipeline are stable.

### ProseCast Attribution Model

Long-term goal: replace the Ollama LLM pass with a fine-tuned local model trained specifically on dialogue attribution.

- **Training signal** — every user correction (speaker reassignment, merge, chapter labeling, tag edit) is a labeled example. Opt-in: users choose whether corrections feed the shared model.
- **Why it beats general LLMs** — learns book-specific patterns, genre conventions, and formatting artifacts that general-purpose LLMs handle inconsistently. Smaller, faster, and more accurate for this narrow task.
- **Scale moat** — community corrections compound. The model improves with user base growth in a way competitors can't replicate without the same correction data.
- **Same flywheel applies to emotion tag corrections** — tag edits train the tagging model alongside the attribution model.
- **Path:** community correction pipeline → labeled dataset → fine-tuned model → drop-in replacement for Ollama pass in `llm_attributor.py`
- **Prerequisite:** shared attribution database must exist and have sufficient correction volume before training is meaningful.

### Marketplace & Community Layer

Long-horizon feature. Architecture decisions now must not block it — keep IR exportable, correction data separable from local state.

- **Shared attribution corrections** — corrections (`book_id`, `block_id`, `speaker`) contributed to a shared database. Future users of the same book get pre-computed corrections before the LLM pass. Book identity via ISBN or title+author hash.
- **Completed casts** — a "cast" is a voice map + corrected IR for a specific book. Rateable, downloadable, shareable. Users publish casts so others don't start from scratch.
- **Voice pack marketplace** — creators publish named voice packs (character→voice assignments with previews); users browse and purchase. Engine-agnostic where possible.
- **Coin economy:**
  - *Earned by:* contributing corrections, completing and publishing book casts, rating content, tag editing
  - *Spent on:* premium ElevenLabs generation, voice packs, downloading community casts
  - Premium membership includes a monthly coin allowance
- **Design constraint:** IR format and correction/tag data must remain exportable and human-readable. Do not couple them to a proprietary local schema.

## Competitive Landscape

**ElevenReader** — read-aloud app, one narrator voice, "auto-assign voices" is Alpha and non-functional. Positioned around commuting/productivity. Not solving multi-voice casting.

**ElevenLabs audiobook creator** — single-pass render, no attribution pipeline, no correction loop, no per-character casting UI. Output is a flat audio file.

**The gap ProseCast fills:** Nobody does character attribution at scale, per-character casting, inline correction during playback, emotion tagging, or directorial control over the cast. ProseCast's moat is the correction loop + community data + attribution model, not voice quality. ElevenLabs is the premium TTS backend — we compete on the layer above synthesis.

**Strategic note:** The actor companion app extends this moat into a second market (performing arts) using the same infrastructure.

## Dependencies

`bash SETUP.sh` does all of this and verifies each step. **On Windows it is
`.\SETUP.ps1`** (PowerShell) — same steps, plus `piper-tts` and the six Piper
voice files into the repo root, and it writes `start-prosecast.ps1` as the
double-click entry point. By hand:

```bash
python3 -m venv .venv && source .venv/bin/activate     # Python 3.11+
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -c 'import spacy; spacy.load("en_core_web_sm")' # prove it — a rebuilt venv silently skips the attribution tests without this
cp config.example.json config.json                      # gitignored; the Setup page edits it
# ffmpeg REQUIRED (m4b export, voice-clip prep); tesseract only for scanned PDFs; poppler NOT needed
```

`pydub` is effectively dead on Python 3.13 (`audioop` removed); the merger falls back to pure-WAV concat and works. Always run via `.venv/bin/python` or activate first.

**Cowork device VM:** `/opt/homebrew` is not mounted, so `.venv/bin/python` fails there. Use the VM's own `python3` with `pip install --break-system-packages fastapi httpx python-multipart pytest requests miniaudio pymupdf` and run `python3 -m pytest tests/`. Playwright is only in the cloud container.
