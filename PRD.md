# ProseCast — Dogfood MVP PRD

**Version:** 1.0 (2026-07-03)
**Scope decision:** Dogfood MVP. The first user is Tyler, not a customer.
**Supersedes nothing** — CLAUDE.md remains the technical reference; this doc defines *what ships next and why*.

## The MVP in one sentence

> Tyler listens to **A Parade of Horribles**, start to finish, multi-voice with distinct character voices, on his phone — and it's good enough that he doesn't switch back to a single-voice reader.

Everything below is scoped to that sentence. If a feature doesn't move a full-book listen closer, it's cut (see Cut List).

## Success criteria

1. Full book (115 chapters) rendered at zero marginal cost (no ElevenLabs credits).
2. Cast is coherent: narrator + a small set of distinct, stable character voices. No voice flips mid-conversation that break immersion.
3. M4B on the phone with correct chapter markers (export already works — this is the delivery vehicle).
4. Corrections made while listening land in `corrections.jsonl` (flywheel data keeps accumulating).

## What already exists (do not rebuild)

- Attribution pipeline: 99.8% on Parade (rules + LLM pass). ✅
- Tagging pipeline: validated, zero-error on Frankenstein; `tag_mapper.py` translates tags per engine. ✅
- Web UI: playback, inline correction, unresolved drawer, voices panel, upload. ✅
- Per-book `library/` layout, corrections journal, golden tests, nightly Bolt backup. ✅
- M4B export with chapters (skips unrendered chapters gracefully). ✅
- ElevenLabs backend (premium tier, quota-limited). ✅

## The gap

Four things stand between the current repo and the MVP sentence:

**1. No free render tier.** `tts_engine.py` supports elevenlabs/say/gtts/piper/stub. Chatterbox is mapped in `tag_mapper.py` but has **no backend in the engine**. A 115-chapter book on ElevenLabs is a credit bill; on `say` it's not worth listening to. Chatterbox-Turbo is already running on Gideon (`GIDEON_HOST:8101`) — it just isn't wired in.

**2. Cast is unusably noisy at book scale.** Parade has ~255 "speaking characters" (spaCy tags LitRPG skill names as people). Casting voices one-by-one through the current voices panel doesn't scale. Need a cast review screen: rank by line count, merge duplicates, bulk-reassign noise to NARRATOR, cast only the top N.

**3. No full-book render job.** Rendering 115 chapters is a multi-hour batch. It must be resumable (skip chapters whose WAV exists), report progress, and survive interruption — an overnight job Tyler can walk away from.

**4. Unknown: does Chatterbox actually sound good?** Everything above assumes yes. That's why Phase A is a listen test, not a build-out.

## Phases (each is a small, testable prototype)

### Phase A — Chatterbox backend + listen test *(the gate)*
- Add `chatterbox` backend to `tts_engine.py`: POST to Gideon `:8101`, apply `map_tags(tags, "chatterbox")` (exaggeration + speed), voice reference clip per character (cloning = free distinct voices).
- Startup health check like the ElevenLabs one; graceful fail off-Tailscale.
- Render **one chapter** of the sample book, then one of Parade. Listen.
- **Gate:** if Chatterbox quality is unacceptable for hours of listening, stop and rethink (Orpheus, or budget real ElevenLabs credits) *before* building the cast screen around cloning.
- Also measure: seconds of render time per minute of audio → decides whether full-book render is "overnight" or "over a weekend."

### Phase B — Cast review screen
- New drawer/page: characters ranked by dialogue block count.
- Actions: **merge** (Kimberly→Kimberley, aliases), **demote to NARRATOR** (bulk, for skill-name noise), **cast** (assign voice / reference clip, preview with a real line from the book).
- Merges and demotions append to `corrections.jsonl` (they're labeled data too).
- Target workflow: Parade's 255 → a cast of ~10–15 in under 15 minutes.

### Phase C — Full-book render job
- `POST /render/{slug}` hardened: per-chapter, **skip existing WAVs**, progress via existing `/render_status`, continue-on-chapter-failure (log and move on).
- CLI equivalent for overnight runs from the Mac.
- Then: render Parade → export M4B → phone.

### Phase D — The listen-through
- Tyler listens to the whole book. Corrections via the existing inline UI as he goes.
- Output: a short findings list appended to STATUS.md — voice stability issues, attribution misses the benchmarks didn't catch, whether tags audibly help. That list is the *real* next roadmap.

## Cut list (explicitly not MVP)

- Per-chapter narrator dropdown — Carousel-only problem; Parade is single-POV (`--narrator Carl`). Next after MVP.
- Tag editing UI (Phase 4b) — tags render read-only for now.
- Pipeline-in-UI processing jobs — CLI IR build is fine for one user.
- Fuzzy alias matching (Levenshtein) — the merge action in Phase B covers it manually.
- Orpheus, Fish Audio — only if the Phase A gate fails.
- Marketplace, shared corrections DB, coin economy, Flutter app, actor companion — post-MVP vision (see CLAUDE.md). Only constraint honored now: IR and corrections stay exportable/human-readable.

## Risks and gotchas

- **Chatterbox API surface is still stabilizing** — the `speed` param is a stub in the mapper. Verify the actual endpoint contract on Gideon before building; don't trust the mapper's assumptions.
- **VRAM:** Chatterbox (~4.7 GB) + mistral:7b coexist fine (Voice-mode budget). Do **not** run a 32B or an SDXL job during a book render.
- **Off-Tailscale = silent-ish failure.** Render jobs must fail loud and early with a health check, not 15s-timeout per block.
- **Long batch discipline:** before walking away from a full-book render, verify the first 2–3 chapters produced audible WAVs (the smallest healthy-loop check).
- **renders/ is disposable, everything else is precious** — resumability must never touch ir.json/voice_map/corrections.

## Sequence summary

A (engine + listen gate) → B (cast screen) → C (book render + M4B) → D (listen-through → findings). Each phase ends with a STATUS.md chapter-close.
