# CC BRIEF — E8: the data-safety chapter (corrections survive renders, audio follows its block, the cache key tells the truth)

**Written 2026-09-06 for an autonomous Claude Code run in `~/dev/prosecast`, on the Mac.**
**This brief has 7 steps (0–6). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

**This chapter touches the render path every existing book depends on. The rule for the whole
brief: nothing is regenerated, nothing is deleted, every migration has a `--dry-run` whose
output goes into `STATUS.md` before anything is applied, and the acceptance number for "how
many blocks would re-render" is ZERO.**

---

## Mission

Four findings from the 09-04 review are still open in `HANDOFF.md` → "Known-real, not yet
fixed". Close them without a library re-render:

1. **ElevenLabs never receives the emotion tags.** `synthesize()` calls
   `_synthesize_elevenlabs(text, voice_cfg, out_path)` and drops `tags`; the payload hard-codes
   `voice_settings {stability: 0.5, similarity_boost: 0.75}` while `tag_mapper._map_elevenlabs`
   already computes stability/style from intensity and pace.
2. **A correction made during a render is silently overwritten.** The worker loads one IR
   snapshot per job and `renderer.save_ir()` writes the *whole* snapshot back after every block;
   the PATCH endpoints read-modify-write independently. E3 guards render-vs-AI-pass with a 409;
   the PATCH endpoints (the actual user-correction case) are not guarded at all.
3. **Audio is keyed by list position.** Five readers build `block_{i:04d}.wav` from
   `enumerate(blocks)`; `merge_next` pops a block, so every later block's file is read one slot
   off. Live evidence: `carl_rpg_core_rulebook` ch0 has a merged block whose stored url still
   points at the right file while `/timeline` and the aligner read the wrong one.
4. **The cache key ignores tags and model.** `_cache_key = sha256(text + voice_cfg + engine)`;
   the mapped tag params and the model id are not in it, so a tag edit never re-renders.

Done means: all four have a regression test, the three migrations report zero anomalies on
Tyler's library, the Carl merged block plays the right audio in the reader, and HANDOFF's
findings list shrinks to what is actually still true.

---

## Guardrails (read before touching anything)

- **GREEN (do autonomously):** edit `prosecast/renderer.py`, `prosecast/tts_engine.py`,
  `prosecast/word_aligner.py`, `prosecast/pipeline.py`, `prosecast/library.py`, `server.py`
  (`/timeline`, the render worker, the 409 guard comments), `README.md`,
  `docs/elevenlabs-setup.md`; add `scripts/migrate_block_audio.py`, `scripts/rekey_cache.py`,
  tests under `tests/`; re-run `scripts/refresh_ui_fixtures.py` if `/timeline`'s shape changes
  on purpose (it should not); `STATUS.md` / `HANDOFF.md` at chapter-close; LOCAL commits.
- **YELLOW (do exactly as written, and only after the dry-run is in STATUS):** Step 5 applies
  the two migrations to the real library. Each book's `ir.json` is copied to
  `ir.json.pre-e8` first, every rename is logged to `library/<slug>/e8_rename_log.json`, and
  the apply step refuses to run if its own dry-run reported a single anomaly. If the dry-run
  is not clean, STOP, write the report to `STATUS.md`, and leave the library untouched — Tyler
  decides.
- **RED (never):** delete or overwrite any `.wav`; regenerate any audio (no `POST /render`,
  no `force`, no `synthesize` outside mocked tests); call ElevenLabs with a real key (tests
  mock `urllib.request.urlopen`); write `ir.json` with a plain `open(..., "w")`
  (`lib.write_json_atomic` always — `tests/test_pipeline.py` enforces it); hand-write anything
  in `tests/fixtures/`; touch `corrections.jsonl` or `voice_map.json`; put a real host/IP/user
  in a tracked file (placeholders: `GIDEON_HOST`, `192.168.1.50`, `/Users/YOUR_USER`);
  `git push`.
- **Tests that start a background job must wait for it** (HANDOFF "Key facts", 09-06). The
  render worker is exactly such a job. Every test that enqueues a render joins it before
  returning.
- **Working tree:** expected clean at `main`. `git status -sb` first; if there are modified
  files, STOP and write what you found to `STATUS.md`.
- **Before Step 5, confirm with Tyler in STATUS that the nightly library backup
  (`bolt/backups`) ran after the last real render.** You cannot check that from here — write
  the line "Step 5 waits for Tyler to confirm the backup" and STOP at the end of Step 4 if he
  has not said so in the kickoff prompt.

## Smallest healthy-loop check (verify this before walking away)

After **Step 1**, `.venv/bin/pytest tests/ -q` must show the baseline **plus** your new
ElevenLabs tests. Baseline on this Mac: **297 passed, 1 skipped** (skips are healthy). If
`tts_engine.py` imports and the count went up, the loop is healthy. If it went down, you have
STOPPED there.

---

## Step 0 — Orient (read, don't write)

Read `CLAUDE.md`, `HANDOFF.md` → "Known-real, not yet fixed" and "Key facts". Then, in code:

- **Render worker:** `server.py` `_run_one_render_job` (~1628: `ir = _load_ir(ir_path)` once,
  then `render_chapter(book_slug, ch_idx, ir, ir_path=…)` per chapter), `_queue_worker`
  (~1685), `_enqueue_render` (~1707, the 409 vs `ai_pass`), `start_ai_pass` (~1954, the 409 vs
  `render`), `_live_job` (~1804). `prosecast/renderer.py`: `save_ir()` (~97, whole-snapshot
  `write_json_atomic`), called at ~119 (after each synthesized block) and ~137 (after merge);
  `force` clears `cacheKey` at ~91; `block_needs_synthesis` (~45). `prosecast/tts_engine.py`
  `synthesize_segment` (~623–657): the ONLY fields the render path writes on a block are
  `audioVariants.standard.{url,cached}` and `cacheKey`.
- **Competing writers** (all `_load_ir` → mutate → `write_json_atomic`): `PATCH
  /ir/{slug}/block/{segment_id}` (~838, writes speaker/unresolved/attribution/confidence,
  `unresolved_count`, `characters`), `merge_next` (~913), `DELETE …/character` (~970), the
  `/cast/*` endpoints (~1158–1297), and the pipeline worker (`pipeline.py` ~165 plus
  checkpoints in `scene_attributor.py` ~368 and `cast_profiler.py` ~283).
- **Index-keyed audio readers:** `renderer.py` ~104 (`block_{i:04d}.wav`), `server.py`
  `/timeline` ~684, `word_aligner.py` `align_chapter` ~225 and `chapter_blocks_fingerprint`
  ~191 (`glob("block_*.wav")`), `pipeline.py` `chapter_align_state` ~206, `library.py` ~47
  (`chapter_blocks_dir`, docstring ~9), `scripts/render_chapter_resumable.py` ~85 (legacy). The
  merge path in `renderer.py` ~127 reads `audioVariants.standard.url` — **by stored url, not
  index** — which is why merged books still *render* correctly. `segmentId` is generated at
  `ir_generator.py` ~452 (`ch{i+1}_seg_{j+1:04d}`), unique per book, preserved by `merge_next`
  (survivor keeps its id), not stable across re-ingest (a re-ingest rewrites the whole IR
  anyway).
- **Cache key:** `tts_engine.py` `_cache_key` (~619), called at ~636 and mirrored in
  `renderer.block_needs_synthesis`. `map_tags` is applied only inside `synthesize()` (~667).
  ElevenLabs model id is the literal `"eleven_flash_v2_5"` (~348). Chatterbox model identity
  is only ever seen in `test_chatterbox_connection` (~460, `info["type"]`/`class_name`) and
  not retained. `TTSEngine.__init__` (~574) is where new key ingredients get captured.
- **Tests to extend:** `tests/test_render_queue.py`, `tests/test_timeline.py` (pins the
  `/timeline` fixture), `tests/test_word_aligner.py`, `tests/test_pipeline_api.py` (~297–335,
  the two 409 guard tests), `tests/synthetic.py` (IR builders seed `cacheKey: None`).

Write nothing in this step.

---

## Step 1 — ElevenLabs gets its direction (finding 1)

- `synthesize()` passes `tags` to `_synthesize_elevenlabs(text, voice_cfg, out_path, tags=None)`.
- Inside, `voice_settings = {"stability": 0.5, "similarity_boost": 0.75}` becomes the defaults
  **updated by** `map_tags(tags, "elevenlabs")` when tags are present — keep
  `similarity_boost`, let the mapper's `stability`/`style` win. No tags → payload byte-identical
  to today (a test asserts this, so untagged books are unaffected).
- Do NOT change `_cache_key` in this step. Existing ElevenLabs audio stays valid until Step 4
  decides what the key means.
- **Docs, same commit:** delete the sentence added on 09-06 ("ElevenLabs voices sound better,
  but today ProseCast's emotion tags do not reach them…") from `README.md` and
  `docs/elevenlabs-setup.md`, and replace it with one true sentence: tags now set ElevenLabs's
  stability and style per line; audio rendered before this change was not directed, and
  re-rendering it on ElevenLabs costs credits, so it is never done automatically — force a
  chapter when you want it.
- Tests (`tests/test_elevenlabs_tags.py`): mock `urllib.request.urlopen`, capture the JSON
  payload; intensity 0.9/urgent yields lower stability and higher style than intensity 0.2/slow;
  no tags yields exactly today's `voice_settings`; the request never leaves the mock.

**Healthy-loop check here.** `git commit -m "E8.1: tags reach ElevenLabs voice_settings; docs say so"`.

---

## Step 2 — Corrections survive a render (finding 2)

**The surgical fix, not a locking refactor.** In `renderer.py`, `save_ir()` becomes a merge:

1. Re-read `ir.json` from disk (`_load_ir`-equivalent; if the read fails or parses to something
   without `chapters`, fall back to today's whole-snapshot write and log one line — never
   refuse to save the render's progress).
2. For the chapter being rendered, walk the on-disk blocks and the in-memory blocks **by
   `segmentId`**, copying only `audioVariants` and `cacheKey` from memory onto disk. Blocks that
   exist on disk but not in memory (a correction split something — not possible today, but
   cheap to handle) are left alone; blocks in memory but not on disk (a merge absorbed them)
   are dropped — the disk is the truth for structure, memory is the truth for audio.
3. Write the merged on-disk document with `write_json_atomic`. Then **replace the in-memory
   snapshot** with the merged document so the rest of the job renders the current text, not the
   stale one — a merged block's `cacheKey` will mismatch its new text and re-synthesize into
   the same slot, which is what should happen.
4. `force` (~91) clears `cacheKey` in memory only; the merge carries that through naturally.

Tests (`tests/test_render_merge.py`, using the stub engine and a `progress_cb` or a monkeypatched
`synthesize_segment` as the hook between blocks): a `PATCH` that reassigns a speaker between
block 1 and block 2 of a running render is still there when the render finishes, and block 1's
`audioVariants` are too; a `merge_next` during a render leaves the book with N−1 blocks, no
duplicate `segmentId`, and the survivor scheduled for re-synthesis; a corrupted `ir.json` on
disk during a render falls back to the whole write and the job still completes. Every test
joins the worker before returning.

**The 409 guard:** relax the *comment and the message*, not the guard. Render-vs-AI-pass stays
blocked in both directions, because the AI pass and its checkpoints are also whole-document
writers and this step does not make *them* merge. Update the comment at `_enqueue_render` and
the two messages to say why the guard remains (two whole-document writers), and note in
HANDOFF that the PATCH/merge/cast endpoints are now safe during a render. The two tests at
`test_pipeline_api.py` ~297–335 keep passing unchanged.

`git commit -m "E8.2: render worker merges its two fields by segmentId; corrections survive"`.

---

## Step 3 — Audio follows its block (finding 3)

Filenames become `{segmentId}.wav` inside the existing `renders/ch{N}_blocks/` directory
(`library.py` gets `block_audio_path(slug, chapter_index, segment_id)` and the docstring is
corrected). Every reader goes through that one function: `renderer.py` ~104, `/timeline` ~684
(shape unchanged — still emits `block_index` and `segment_id`; the fixture must not drift),
`word_aligner.align_chapter` ~225, `chapter_blocks_fingerprint` ~191 (glob `*.wav` and keep the
sum-of-durations semantics so existing `word_timings.json` files are not marked stale by the
rename), `pipeline.chapter_align_state` ~206, and `scripts/render_chapter_resumable.py` (or
delete that script if nothing references it — check first, and say which in the commit).

**Migration `scripts/migrate_block_audio.py --dry-run` (default) / `--apply`:** for every book
and chapter, the mapping is **`audioVariants.standard.url` → `{segmentId}.wav`**, not
index → id. The stored url is the truth for which file belongs to which block; this is exactly
what makes the Carl merged chapter come out right. Rules: a block whose url is missing or
whose file does not exist is reported, not invented; a file in the directory no block points
at is reported as an orphan and left where it is; two blocks pointing at one file is an
anomaly that stops the apply; an url already in the new form is skipped. Dry-run prints per
book: blocks, files, renames it would do, orphans, anomalies — and a final line
`ANOMALIES: N`. `--apply` refuses unless its own dry-run says `ANOMALIES: 0`, copies `ir.json`
to `ir.json.pre-e8`, writes `e8_rename_log.json` (old → new, per file) *before* the first
rename, renames with `os.replace` on the same filesystem, then rewrites each block's url via
`write_json_atomic`. It never deletes.

Tests (`tests/test_block_audio_paths.py`): render two blocks on the stub engine, merge the
first into… no — `merge_next` the first pair, then assert `/timeline` and `align_chapter` both
resolve the surviving block to its own file and the following block to *its* file; a synthetic
library with the old layout migrates cleanly under dry-run then apply; the orphan and
double-pointer cases are reported and the apply refuses.

`git commit -m "E8.3: audio keyed by segmentId; migration script with dry-run"`.

---

## Step 4 — The cache key tells the truth (finding 4)

`_cache_key(text, voice_cfg, tag_params, model_id)`: the mapped params from
`map_tags(tags, engine)` (an empty dict for engines with no tag support, so `say`/`piper` keys
are unchanged by tags) and a model id captured once in `TTSEngine.__init__` — ElevenLabs's
literal model id, Chatterbox's `info["type"]`/`class_name` from `test_chatterbox_connection`
(retain it on `self.model_id`; fall back to the engine name when unknown), Piper's voice
(already in cfg). `renderer.block_needs_synthesis` computes the key the same way — one function,
two callers.

**Migration `scripts/rekey_cache.py --dry-run` / `--apply`:** for every block that has a
`cacheKey` and whose audio file exists, compute the new key from *current* text, voice config,
tags and model, and write it — **assuming the audio on disk matches**, which is true for
Chatterbox (tags were applied at synthesis, the key just didn't record them) and is the
deliberate decision for ElevenLabs (see Step 1's docs sentence). Report: blocks rekeyed, blocks
skipped (no audio), and — the acceptance number — **blocks that `block_needs_synthesis` would
consider stale after rekey minus before rekey. It must be 0.** If it is not, STOP and put the
list in `STATUS.md`. Same backup/log discipline as Step 3 (`ir.json.pre-e8` is shared; the log
is `e8_rekey_log.json`).

Tests (`tests/test_cache_key.py`): same text + voice with different intensity → different keys;
different Chatterbox model id → different key; `say` key unaffected by tags; a synthetic library
rekeys with zero new stale blocks; a tag edit on one block makes exactly that block stale.

`git commit -m "E8.4: cache key includes tag params and model; rekey script with dry-run"`.

**STOP HERE unless the kickoff prompt says Tyler has confirmed the library backup.**

---

## Step 5 — The real run (YELLOW — follow exactly)

1. `.venv/bin/python scripts/migrate_block_audio.py --dry-run` → paste the per-book summary and
   the `ANOMALIES:` line into `STATUS.md`. Expect the Carl rulebook to show at least one rename
   that is *not* index-aligned (the merged block). Expect the sample book (rendered on `say`
   this morning) to migrate cleanly.
2. Only if `ANOMALIES: 0`: `--apply`. Then `ls library/carl_rpg_core_rulebook/renders/ch0_blocks | head`
   shows `ch1_seg_*.wav` names and `e8_rename_log.json` exists.
3. `.venv/bin/python scripts/rekey_cache.py --dry-run` → paste the summary; the stale-delta line
   must be 0. Only then `--apply`.
4. Start the server (`.venv/bin/uvicorn server:app --port 8000` — Tyler's may already be up;
   if so, restart it so the new code is loaded), open the Carl rulebook in the reader, play
   chapter 1 from the top and listen across the merged block boundary: the words on screen and
   the words in the audio must agree. Then open the Pipeline card: every chapter that had
   `words ✓` still has it (the fingerprint survived the rename). **Render nothing.**
5. `.venv/bin/pytest tests/ -q` and all five `tests/ui/` checks green.

If anything in 1–4 disagrees with expectation, STOP, write it to `STATUS.md`, and leave
`ir.json.pre-e8` and the logs in place — they are the undo.

---

## Step 6 — Chapter-close

- `STATUS.md`: session entry "2026-09-0x (Claude Code, Mac) — E8: data safety" in the house
  style, with the dry-run numbers verbatim and the Carl listening check.
- `HANDOFF.md`: the "Known-real, not yet fixed" list loses all four; add a "Fixed in E8" note
  saying what remains true — render-vs-AI-pass stays a 409 because both are whole-document
  writers; ElevenLabs audio rendered before E8 is undirected until forced. "Key facts" gets
  three lines: audio lives at `{segmentId}.wav` via `lib.block_audio_path`; the render worker
  merges only `audioVariants`/`cacheKey`; the cache key is text + voice + tag params + model.
  Delete the `.pre-e8` backups only when Tyler says so — leave a line telling him they exist.
- `CLAUDE.md` "Known remaining issues" pointer stays true (it points at HANDOFF).
- Commit `E8.5: chapter-close`. `git status -sb` clean, `[ahead N]`. **Do not push.**

END OF BRIEF
