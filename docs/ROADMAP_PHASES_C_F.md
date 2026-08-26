# ProseCast — Verified Roadmap: Phases C → F

**Written:** 2026-08-06 (Cowork session, repo review + plan development)
**Companion to:** HANDOFF.md (2026-08-01) and STATUS.md. This doc *verifies* the
handoff against the actual repo/library state and turns the "Open loops" list
into build-ready specs. Single-writer note: this is a new doc — STATUS.md was
not touched.

---

## 1. Verification results (what I checked, 2026-08-06)

Everything in HANDOFF.md checked out, plus four findings the plan below now
accounts for:

**✅ Confirmed as claimed**
- Repo clean; Phase C genuinely unbuilt: `server.py` render endpoints spawn one
  daemon thread per click (no queue, no pre-flight, no book-level resume);
  `main.py generate_audio()` only persists cacheKeys to ir.json **after the
  whole chapter finishes** (a mid-chapter crash re-synths the chapter even
  though the block wavs exist — `scripts/render_chapter_resumable.py` already
  fixed this per-block; the fix just never made it into the server path).
- Brigands: 3 chapter wavs (4/9/17) + 3 word_timings.json, 0 unresolved.
- Test suite green: 74 passed / 1 skipped in a clean cloud container without
  spaCy (the delta to 89 is the spaCy-gated attribution tests, which skip by
  design off-Mac).
- Chatterbox contract, cache-key semantics, voice_meta.json all as documented.

**⚠️ Finding 1 — Parade's voice_map.json is a stale ElevenLabs map (LANDMINE).**
`library/a_parade_of_horribles_generic_/voice_map.json` is
`engine: elevenlabs` with **256 auto-assigned entries** from the pre-Phase-B
era. Two failure modes if untouched:
1. Cast drawer **Save will 400** — `save_voice_map` validates IDs against the
   *chatterbox* pool, and EL IDs like `EXAVITQu4vr4xnSDxMaL` aren't in it.
2. Worse, a render that loads it: bare EL ID strings fall through
   `_voice_id_to_cfg` as chatterbox **clone reference filenames** → every block
   404s on the server → chapter "renders" as silence/skips. This is exactly the
   class of failure Phase C pre-flight exists to catch; it's also a required
   **manual pre-step for Phase D** (archive the file first — see D0).

**⚠️ Finding 2 — Parade attribution is NOT at Brigands standard yet** (handoff
implied this; now quantified): 115 chapters, 3,890 dialogue blocks, 5 unresolved
(fine) but **808 `alternating` + 813 blocks under conf 0.6**, 382 blocks from
the old `llm_llama3.2` pass, and **0 character profiles**. The D1 scene +
profile passes are real work (~same scale as Brigands' campaign), not a
formality.

**⚠️ Finding 3 — Moby Dick has no IR at all** (`library/moby_dick.../` has
neither ir.json nor voice_map). The sampling pass for it starts at EPUB ingest,
not at the LLM passes. Frankenstein: IR ✓, 137 unresolved, 365 blocks already
tagged, no voice_map (matches handoff). Carousel: IR ✓, 103 unresolved, no
voice_map.

**📌 Finding 4 — 4 commits still local-only** (`22eaa9c…e16d485`: HANDOFF
edits, StageForge naming, license). `main` is ahead of `origin/main` by 4.
Everything else from the big session was pushed. Run `git push` at next
convenience — CLAIY syncs through GitHub.

---

## 2. Phase C — Safe whole-book render (~1 session)

**Done means:** Parade-scale books render overnight, unattended, and every
known failure mode either aborts loudly *before* synthesis starts or is
survived and resumed. Nothing in this phase touches ir.json semantics,
voice_map format, or corrections.jsonl.

### C0. Pre-flight module — `prosecast/preflight.py`
One function, `preflight(book_slug, engine) -> PreflightReport`, run before ANY
batch render (server queue + CLI). Checks, in order, all **loud-abort on fail**:

1. **Server reachable** — GET `/api/model-info` (fast timeout; off-Tailscale
   fails in seconds, not 15s-per-block).
2. **Model is base, not turbo** — assert `"turbo" not in (type + class_name)`
   (same predicate as the existing Turbo guard; on turbo, exaggeration/cfg are
   silently ignored → a whole overnight render with flat delivery).
3. **voice_map.json exists** — refuse batch renders without one. (The "Auto"
   round-robin for chatterbox uses 2 clone refs — effectively broken; a
   mapless overnight render is never what Tyler wants.)
4. **voice_map engine matches active engine** — catches Finding 1 exactly.
   Suggest the fix in the error text ("archive this voice_map and re-cast via
   the cast drawer").
5. **Every voice resolvable on the server** — `predefined:<file>` entries ∈
   GET `/get_predefined_voices`; bare filenames ∈ GET `/get_reference_files`.
   This is the shared-with-AnimaForge insurance (swaps/deletions).
6. **Warn-only:** unresolved count > 0 (renders as narrator — informational),
   and chapters already rendered (will be skipped).

Wire-up: called at the top of the queue worker per job (server) and as
`--preflight` in the CLI runner. Add mocked tests (reachable/turbo/missing
voice/engine-mismatch each produce the right abort).

### C1. Unify the render core (per-block resume everywhere)
Extract `render_chapter_resumable.py`'s loop into `prosecast/renderer.py`
(`render_chapter(slug, ch, engine, save_every_block=True)`), and make BOTH
`main.py generate_audio` and the server job use it. Key behaviors, all already
proven in the script: IR saved after every newly-rendered block (the resume
point), continue-on-block-failure, throughput report (s render / min audio),
merge whatever rendered. This closes the "interrupted server render loses its
cache metadata" gap for free.

### C2. Server-side render queue (one GPU, one worker)
Replace thread-per-request with a single global worker thread + FIFO queue:
- `POST /render/{slug}/{ch}` and `POST /render/{slug}` **enqueue** and return
  `job_id` immediately; clicking ⚡ Generate on N chapters = N queued jobs
  running strictly sequentially (the GPU constraint, enforced structurally).
- Preflight runs once per job at dequeue time; a mid-night server hiccup on
  job 3 doesn't kill jobs 4–10 (continue-on-chapter-failure, error recorded).
- `GET /render_status/{job_id}` unchanged shape + add `queue_position`;
  new `GET /render_queue` for the UI (pending / running / done / failed list).
- Persist a lightweight `library/<slug>/render_state.json` (queue snapshot +
  per-chapter outcome). It's advisory/disposable like renders/ — real resume
  comes from cacheKeys — but it lets a restarted server show what happened.
- UI: chapter rows show queued/running state; a "Render remaining N chapters"
  button on the book row.

### C3. Book-level resume semantics
"Chapter done" = `renders/ch{N}.wav` exists AND no block in the chapter needs
re-synthesis (cacheKey check — already what `synthesize_segment` does
per-block, so a "done" chapter costs one fast pass of cache hits, ~free).
`POST /render/{slug}` therefore just enqueues all chapters; the renderer
skips the finished ones. Add `?force=true` to re-render regardless.

### C4. Local mirror of clone reference clips
- New repo dir `voice_refs/` (gitignored size permitting — clips are small
  wavs; if kept out of git, they're covered by the nightly Bolt backup rule
  instead — decide when you see total size).
- `scripts/mirror_voice_refs.py`: pull every file listed by
  `/get_reference_files` to `voice_refs/`.
  **Checkpoint before building:** confirm the devnen server actually exposes a
  download route — check `curl -s http://GIDEON_HOST:8101/openapi.json | python3 -m json.tool | grep -i -A2 'reference\|download\|audio/'`.
  Look for a GET that serves reference audio. If none exists, fall back to
  `scp NAS_USER@GIDEON_HOST:<chatterbox reference dir>/*.wav voice_refs/`
  (find the host path via the container's volume mount — one-time lookup).
- Restore path = the server's `POST /upload_reference` (YELLOW/write —
  Tyler-run only, never from automation).

### C5. Overnight-run discipline (docs + guardrails, not code)
- **Run the batch WITHOUT `--reload`.** Dev reload watches .py files; any code
  edit (or editor save) mid-render kills the worker thread and the whole
  night's queue. A plain `uvicorn server:app` (no --reload) for render nights,
  or use the CLI runner below.
- CLI equivalent for max robustness: `scripts/render_book.py <slug>` =
  preflight → loop chapters via renderer → summary (skips done chapters, so
  re-running after any failure is the whole recovery story).
- Chapter-close checklist baked into docs: `caffeinate -i` if the Mac drives
  it; verify first 2–3 chapters are audible + note the s/min throughput before
  walking away; no 30B/32B/SDXL jobs on Gideon during the run.

**Tests to add:** preflight matrix (mocked), queue sequencing (two jobs never
overlap), done-chapter skip, force re-render, engine-mismatch abort. Keep the
suite fully offline.

---

## 3. Phase D — Parade end-to-end (closes the PRD)

Runbook, in order. Steps D1–D2 are attended (~1 evening); D3 is overnight;
D4–D5 are the next day.

**D0. Prep (5 min).**
- ⚠️ Archive the stale map (don't delete — it's history, and rm-on-mount fails
  in Cowork anyway): `mv library/a_parade_of_horribles_generic_/voice_map.json library/a_parade_of_horribles_generic_/voice_map.elevenlabs.2026-07.bak`
- `git push` the 4 local commits.
- Verify Chatterbox model is base (`curl -s http://GIDEON_HOST:8101/api/model-info | grep -i type`) — expect no "turbo".

**D1. LLM passes (~45–60 min, Mac awake + on Tailscale, `caffeinate -i`).**
```
PROSECAST_OLLAMA_URL=http://GIDEON_HOST:11434 .venv/bin/python main.py Parade \
  --use-existing-ir --llm-scene --llm-scope low-confidence --profile-cast \
  --llm-model gemma3:12b --ir-only
```
Scale note: ~813 low-conf targets (vs Brigands' 647) + first-ever profile pass
on ~40 post-demote characters. Circuit breaker + per-scene checkpointing mean
a dropped run resumes free — just re-run the same command.
Verify after: unresolved ≈ 0–10, `alternating` collapsed (Brigands went
647→10), `ir.character_profiles` populated, ♀/♂ chips visible in cast drawer.

**D2. Cast via UI (~15–30 min — the Phase B target).**
Accept merge chips → Demote all ≤5 (256 speakers → ~40; top 15 carry 61% of
lines) → check ★ tiers → hand-cast mains from gender-sorted dropdowns →
Auto-cast supporting → Save. Save now succeeds because D0 archived the EL map.

**D3. Overnight render (Phase C machinery's first real workout).**
Preflight passes → "Render remaining chapters" (or `scripts/render_book.py`).
Budget check: at the measured ~24s render per audio-minute, a ~12h audiobook
≈ 5h of GPU time — comfortably overnight, even ×1.5.
**Healthy-loop check before walking away:** first 2 chapters audible, distinct
voices, throughput in the expected band. Server running without --reload.

**D4. Align + export.**
`PROSECAST_WHISPER_URL=http://GIDEON_HOST:8100 .venv/bin/python scripts/align_words.py a_parade_of_horribles_generic_`
(all rendered chapters, staleness-aware, ~cheap) → POST /export → M4B → phone.

**D5. The listen-through.** Corrections inline as he goes (flywheel). Output =
findings list appended to STATUS.md: voice stability, attribution misses,
whether the 382 old `llm_llama3.2` blocks and ~10 surviving coin-flips are
audible problems. That list is the real next roadmap — per the PRD, this
closes the MVP.

---

## 4. Phase E — Multi-genre sampling pass (validation breadth)

2–3 chapters each, using the now-buttonized flow. Corrected starting points:
- **Frankenstein:** IR ✓ (137 unresolved, 19th-c. dialogue = the stress test
  for the scene pass). Needs: scene+profile passes → cast → render ch. picks.
  Already tagged (365 blocks) from the old tagging validation — a bonus A/B:
  does tagged delivery audibly differ on base model?
- **Carousel:** IR ✓ (103 unresolved). Same flow. Multi-POV — per-chapter
  narrator remains a known, deliberately-cut gap; note findings, don't build.
- **Moby Dick:** **no IR — start at EPUB upload**, then the standard passes.
  Whale-taxonomy chapters will stress spaCy NER noise → good demote-≤5 data.

Each book: STATUS one-liner with what broke. This is where "works for
Brigands/Parade" becomes "works for books."

---

## 5. Phase F — Pipeline-in-UI (the two remaining terminal steps)

Ordered by leverage, reusing the Phase C job-runner pattern:
1. **Auto-align after render** — chain align_chapter into the render worker
   when `PROSECAST_WHISPER_URL` is set (it's cheap and idempotent). Kills one
   terminal step with ~20 lines.
2. **Attribution/profile jobs in UI** — upload → rule pass (already auto) →
   progress card for scene+profile passes (same queue, LLM jobs are
   GPU-light so they can interleave with... actually NO: gemma3:12b and a
   render's Chatterbox coexist, but keep it simple — same single queue,
   strictly sequential; a book's passes just become queued jobs).
3. **Settings drawer** — Ollama URL, whisper URL, model names (env vars stay
   as overrides; settings.json as the persisted layer). This is also the
   missing-service UX home: "Ollama isn't reachable — here's what that means"
   (PRODUCT_NOTES gap #3).
4. Then and only then: the productization polish run (install story, README)
   per docs/PRODUCT_NOTES.md.

**Still parked (unchanged):** tag/delivery editor → prototype in StageForge
first (shared tag-schema contract stands); highlight-window tuning (needs a
second listener); corrections-replay eval harness; provenance-aware prompting
REQUIRED before any `--llm-scope all`; alphabetical-dropdown option.

---

## 6. Risk register (new items found this review)

| Risk | Phase | Mitigation |
|---|---|---|
| Stale EL voice_map renders garbage via clone-filename fallthrough | C/D | Preflight check #4; D0 archives Parade's map |
| `--reload` dev server kills overnight worker on any .py touch | C | Render nights run without --reload, or CLI runner |
| Mid-chapter crash loses cache metadata (server path) | C | C1 per-block IR save (proven in resumable script) |
| Reference-clip download route may not exist on devnen server | C4 | Checkpoint openapi.json first; scp fallback |
| Parade scene pass is Brigands-scale, not a quick re-run | D1 | Budget a real session; breaker + checkpoints make it resumable |
| Moby Dick assumed further along than it is | E | Starts at ingest; budget accordingly |
| AnimaForge swaps model/voices mid-render | C/D | Preflight at dequeue time per job, not just once per night |

## 7. Suggested session sequence

1. **Next build session → Phase C** (C0–C3 are the core; C4 can trail).
   Smallest healthy-loop check: queue 2 short Brigands chapters with a
   deliberately-broken voice_map and watch preflight abort loudly, then fix
   and watch them render sequentially.
2. **Next Tyler-attended evening → D0–D2**, then fire D3 at bedtime.
3. **Next day → D4–D5** (the phone listen is the PRD finish line 🎉).
4. Then E and F as appetite dictates — E is low-executive-load button work,
   good for tired evenings; F is a clean solo build session.
