# ProseCast

A multi-voice audiobook narration app that parses books and plays them back with distinct voices for narration and dialogue.

## Last Session (2026-06-10)

**Project hygiene pass** (no pipeline behavior changes):
- **Git initialized** — `.gitignore` excludes `.venv`, `output/`, `books/` (copyrighted EPUBs), `.env`, `__pycache__`. GitHub remote: pending (`Koontzie/prosecast` planned).
- **Stray root `ir_generator.py` removed** — was an accidental paste from another project's terminal session (preserved in git history at the initial commit).
- **`requirements.txt` added** — note: `ebooklib`/`beautifulsoup4`/`lxml` were never imported (EPUB parsing is stdlib) and are dropped. `SETUP.sh` rewritten: venv-aware, installs from requirements.txt.
- **Corrections journal** — `server.py` now appends every manual correction to `output/{slug}_corrections.jsonl` (append-only; events: `speaker_correction`, `merge_next`, `character_deleted`). This is the raw labeled data for the attribution training flywheel. Never rewrite this file.
- **Golden-file tests** — `tests/test_attribution.py` runs the built-in sample through `build_ir` and asserts 0 unresolved + exact speaker set. Run `.venv/bin/pytest tests/ -v` after touching any attribution layer. Requires spaCy + `en_core_web_sm` (skips otherwise).
- **STATUS.md added** per the cross-project STATUS protocol.

Planned next (agreed with Tyler, not yet built): per-book `library/` restructure of `output/`, pipeline-in-UI processing jobs, cast review screen (merge/ignore noisy characters), per-chapter narrator dropdown, m4b chapterized export.

## Previous Session (2026-05-28)

### What's working end-to-end

**Pipeline:** EPUB/TXT → IR (rule-based + LLM attribution) → tag pass → TTS → WAV. `main.py` CLI handles all steps; `--narrator` for POV, `--llm` for the LLM pass, `--tag` for tagging, `--use-existing-ir` to skip rebuild.

**Tagging pipeline** (`prosecast/tag_generator.py`), implemented and smoke-tested:
- `--tag` flag adds actor-facing emotion/tone tags to every IR block after attribution
- `--retag` forces re-tagging of blocks that already have tags
- `--tag-model mistral:7b` selects the Ollama model (default: mistral:7b on Gideon)
- `--tag-dialogue-only` tags only dialogue blocks (skips narration — faster for validation runs)
- Schema: `{action, emotion, intensity, pace, tag_method}` — see Tag Schema section
- Zero-error rate on sample book (51/51); prompt enforces "to VERB" constraint via validation
- Failures logged to `/tmp/prosecast-tag-failures.json`
- Gideon connectivity checked at startup; graceful skip if unreachable

**Tag mapper** (`prosecast/tag_mapper.py`): translates abstract IR tags to engine-specific parameters at render time. ElevenLabs (stability/style), Orpheus (inline tags), Chatterbox (exaggeration/speed) all wired. say/gtts/stub/piper return `{}` — no tag support.

**Web UI** (`server.py` + `static/index.html`), all verified working:
- Book list sidebar, chapter list with titles and 1-based numbering
- Playback: play/pause/seek, timeline-synced speaker display, `✎` edit icon always visible next to speaker name
- Block text display above scrubber — shows text for **all** block types (narration and dialogue), 3-line clamp, clickable to open inline correction
- Inline correction popup: character datalist (speaking chars only, NARRATOR always first), free-type for new names, merge-next button, saves via PATCH endpoint
- Unresolved panel (right drawer): opens from chapter badge, bulk review of unresolved blocks
- Voices panel (right drawer): one row per speaking character, voice dropdown, preview button, ✕ delete (reassigns all blocks to NARRATOR, shows inline count confirmation)
- Voice map persisted to `{slug}_voice_map.json`, loaded by `main.py` before rendering

**ElevenLabs TTS** (`ELEVENLABS_API_KEY` in `.env`) verified working:
- Auto-detected as highest-priority engine when key is present
- Connection check hits `/v1/voices` on startup
- Voice auto-assignment: NARRATOR→Sarah, characters round-robin Daniel/Aria/Charlie/Matilda
- MP3→WAV decode via `miniaudio` (no ffmpeg needed)
- `output/el_test.wav` — 2-block test file with NARRATOR and Darcy voices, confirmed audible
- Partial render limited by free-tier character quota (402 on blocks beyond budget); add credits to test at full scale

**Server endpoints:** `/books` (GET + `POST /books/upload`), `/chapters/{slug}`, `/timeline/{slug}/{ch}`, `/ir/{slug}`, `/ir/{slug}/characters`, `/ir/{slug}/cast_candidates`, `/ir/{slug}/unresolved/{ch}`, `PATCH /ir/{slug}/block/{seg_id}`, `POST /ir/{slug}/block/{seg_id}/merge_next`, `DELETE /ir/{slug}/character/{name}`, `/voices`, `/voice_map/{slug}` (GET + POST), `/voice/preview/{voice_name}` (supports `?text=` for actual dialogue preview), `/audio/{file}`, `POST /render/{slug}/{ch}`, `POST /render/{slug}`, `GET /render_status/{job_id}`

### Known issues not yet tackled

1. **Fuzzy name matching** — alias collapse doesn't catch alternate spellings (e.g. `Kimberly` vs `Kimberley`). Needs Levenshtein distance ≤ 2 matching in `build_alias_map()`.
2. **Multiple POV narrators** — some books (and Carousel specifically) shift first-person POV between chapters or scenes. The `--narrator` flag only accepts one name. The IR generator needs chapter-level or scene-level POV detection, and the LLM pass needs context to distinguish which POV character is speaking. Agreed direction (2026-06-10): per-chapter narrator dropdown in the UI rather than automatic detection.

~~3. `--tts` flag missing `elevenlabs` option~~ — fixed; `elevenlabs` is in the choices list.

### IR file state

- Parade IR: lazy-migrated (old `id` → `segmentId`). 255 speaking characters after Vinata deleted during smoke test (1 block reassigned to NARRATOR).
- Sample book: rebuilt fresh this session (Elizabeth was deleted in prior smoke test; IR regenerated with 4 chars: Bingley, Darcy, Elizabeth, Jane).
- Carousel: 47 speaking characters, high unresolved count expected — see Test Books section.

### Next step

**Full validation of tagging pipeline** — Frankenstein in-progress; Yumi and the Nightmare Painter queued. See `test_books/TAGGING_RESULTS.md` once runs complete.

**Chatterbox-Turbo on Gideon** — Tyler is setting up Chatterbox-Turbo on the Gideon server. See "Local TTS Tier — Engine Decision" section for the Orpheus vs Chatterbox tradeoff analysis.

**ElevenLabs full-chapter render** — once account has sufficient credits, render the sample book chapter 1 end-to-end with ElevenLabs and listen for voice consistency across speaker transitions.

## Project Goal

**Phase 1:** Play one chapter with voice switching between narrator and characters. ✓ Done.
**Current focus:** Attribution quality on real EPUBs. Target: <5% unresolved across a full book.

## Architecture

The pipeline is a four-stage process:

```
EPUB/TXT → book_parser.py → ir_generator.py → tts_engine.py → audio_merger.py → WAV
```

### Core Files

- **`prosecast/book_parser.py`** — Parses EPUB (stdlib spine-based, no ebooklib) or TXT into chapters. Skips nav/TOC/cover items automatically.
- **`prosecast/ir_generator.py`** — The core. 6-layer attribution pipeline → structured IR JSON with narration/dialogue blocks, speaker names, confidence scores, and attribution method tags.
- **`prosecast/llm_attributor.py`** — Phase 2 LLM pass. Sends unresolved blocks to Ollama for speaker attribution. Uses localhost:11434 by default.
- **`prosecast/tag_generator.py`** — Phase 4 tagging pass. Sends all blocks to Gideon (mistral:7b at `GIDEON_HOST:11434`) for actor-facing emotion/tone tags. Additive — never modifies attribution fields.
- **`prosecast/tag_mapper.py`** — Translates abstract IR tags to engine-specific render parameters. Pure function: `map_tags(tags, engine_name) → dict`. Called at render time, not at tag time.
- **`prosecast/tts_engine.py`** — Text → audio. Backends: `say` (macOS, local, default), `gtts` (Google TTS, network), `piper` (local, high quality), `stub` (silence, for testing). gTTS output is decoded MP3→WAV via `miniaudio` (no ffmpeg needed).
- **`prosecast/audio_merger.py`** — Merges audio blocks into a final WAV. Uses pydub if available, falls back to pure-Python WAV concat.

### CLI

```bash
python main.py --sample --tts say                        # built-in sample, local voices
python main.py --book book.epub --ir-only                # IR only, no audio
python main.py --book book.epub --narrator "Carl"        # set POV character for "I said" lines
python main.py --book book.epub --tts say                # render chapter 0
python main.py --book book.epub --all-chapters --tts say # render entire book

# Tagging (Phase 4)
python main.py --sample --tag --ir-only                  # smoke test: tag the sample book
python main.py --book book.epub --ir-only --tag          # build IR + tag all blocks
python main.py --book book.epub --use-existing-ir --tag  # tag existing IR without rebuilding
python main.py --book book.epub --use-existing-ir --retag  # force re-tag already-tagged blocks
python main.py --book book.epub --ir-only --tag --tag-dialogue-only  # dialogue only (faster)
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

## Phase Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Parse book → IR → TTS → WAV, voice switching | ✓ Done |
| 2 | LLM attribution pass for unresolved blocks | ✓ Done |
| 3a | Playback UI — load WAV, play, show current speaker | ✓ Done (web UI) |
| 3b | Correction UI — review unresolved blocks, assign speaker | ✓ Done (web UI) |
| 3c | Voice assignment — map characters to TTS voices before render | ✓ Done (web UI) |
| 4a | Emotion/tone tagging pipeline | ✓ Done (tag_generator.py + tag_mapper.py) |
| 4b | Tag editing UI — per-block tag review and correction | Next |
| 4c | Tag-aware TTS render — use tags to shape ElevenLabs/Orpheus delivery | Next |
| 5 | Flutter mobile app | Future |

## Phase 3 Plan

### 3a — Playback UI
- Load a rendered WAV file
- Play/pause/seek
- Highlight current speaker name as audio progresses (requires a speaker timeline derived from the IR block timings)

### 3b — Correction UI
- Load an IR JSON, filter to `unresolved=True` blocks
- Show dialogue line + surrounding context
- Dropdown / text input to assign a character name
- Save corrected IR back to disk; re-render affected audio blocks only

### 3c — Voice Assignment
- Show character list extracted from IR
- Let user assign a TTS voice (say voice name, gTTS accent, piper model) to each character
- Persist as a `voice_map.json` alongside the IR
- `tts_engine.py` reads `voice_map.json` if present, falls back to auto-assignment

### 4 — Flutter Mobile App
- Targets iOS/Android
- Loads rendered WAV (or streams block-by-block)
- Embeds the correction UI for on-device editing
- Syncs IR + audio to device

## Phase 3 Design Requirements

1. **MULTIPLE POV NARRATORS** — Some books have multiple first-person POV characters. Currently all are collapsed into NARRATOR. The system needs to detect POV shifts (chapter-level or scene-level) and attribute first-person narration to the correct POV character. The `--narrator` flag currently accepts one name — extend to support multiple POV characters, each associated with specific chapters or scene markers. The LLM pass should use surrounding context to determine which POV character is narrating when ambiguous.

2. **INLINE CORRECTION UI** — User should be able to flag a speaker mid-playback ("this voice is wrong") and immediately reassign it. The correction writes back to the IR and re-renders only that block. Do not require stopping playback.

3. **DIALOGUE STABILITY** — Investigate whether the alternating heuristic is flipping speakers too aggressively in fast back-and-forth exchanges. In a 2-person conversation, once two speakers are established, the heuristic should hold them stable rather than reassigning on every low-confidence line.

4. **SHARED ATTRIBUTION DATABASE** — When a user corrects an unresolved block, that correction (`book_id`, `block_id`, `speaker`) gets contributed to a shared database. Future users of the same book load pre-computed corrections before running the LLM pass. Book identified by ISBN or title+author hash.

## Known Remaining Issues

1. **Noisy character list** — spaCy tags game skill names (e.g. `"Gut Instinct"`, `"Dark Knight"`) as PERSON entities in LitRPG books. A per-book character allowlist/denylist would help.
2. **Kimberly / Kimberley duplicates** — alias collapse doesn't catch alternate spellings. Needs fuzzy matching (Levenshtein distance ≤ 2).
3. **No sentence-boundary awareness in segmentation** — A quote split across a paragraph break can create false dialogue blocks.
4. **Speaker timeline not yet computed** — Playback UI needs per-block start/end timestamps; currently only block order is known. Requires timing the TTS output during render.
5. **Chapter indexing mismatch** — the `--chapter` flag uses internal IR index (0-based, includes front matter like Dedication, Epigraph, Definition) rather than the book's chapter numbers. Phase 3 UI needs to display the actual chapter title and let users select by name, not index number. The IR already has the `title` field on each chapter — just needs to be surfaced.

## UI Polish — Future Items

- **Book-flipping loading animation** — replace the plain "Processing…" spinner on the "+ Add Book" button (and any other long-running operations) with a page-flipping book animation. Framer Motion or a pure CSS keyframe sequence. Low priority but on-brand for an audiobook product.

## Future Considerations

- **PDF support** — PDF text extraction is messier than EPUB. Requires handling scrambled text layers, multi-column layouts, and header/footer bleed. Lower priority than EPUB but needed eventually.

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

```bash
# create venv first
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
# ffmpeg optional — needed only if pydub MP3 merging is required
# Note: ebooklib/beautifulsoup4/lxml are NOT needed — EPUB parsing is stdlib
```

**Note:** `pip` / `python` resolve to the venv. Always run via `.venv/bin/python` or activate first.
