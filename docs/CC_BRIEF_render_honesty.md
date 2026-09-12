# CC BRIEF — E12: render honesty (a finished render never promises more than it delivers)

**Written 2026-09-12 for an autonomous Claude Code run in `~/dev/prosecast`, on the Mac.**
**This brief has 5 steps (0–4). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

**Scope discipline: this chapter changes reporting only. It does not fix the correction race,
it does not change audio identity, it does not touch the cache key. Those are E8 and they run
after this. If you find yourself editing `_cache_key` or `merge_next`, you have left the chapter.**

---

## PRECONDITION — do this before Step 0

`git status --short` must be clean. At the time of writing it is not:

```
 M STATUS.md
 M server.py
 M static/index.html
 M tests/fixtures/books_library.json
?? tests/ui/check_library_board.py
```

That is an unfinished library-board chapter from another session, and it has `server.py` open —
the same file this brief edits. Commit or stash it first. **Do not discard it, and do not commit
it as part of this chapter.** If the tree is still dirty when you start, STOP and say so.

---

## Mission

A render job can finish, report `done`, and paint "✓ Rendered" over audio that is missing
passages or is silently the wrong take. Close that. Nothing else.

The gap, precisely:

- `prosecast/renderer.py` ~113 increments `report["failed"]` per block and logs it.
- `server.py` `_run_one_render_job` ~2220 sets `done_with_errors` from **chapter-level
  exceptions only** (`c.get("error")`). `report["failed"]` never reaches job status.
- `static/index.html` `pollRenderStatus` ~5695 resolves `done` and `done_with_errors`
  identically, so all three render call sites treat both as success.

There are **two distinct failure outcomes** and the current code distinguishes neither:

1. **Missing** — a block that never had audio fails. It has no usable
   `audioVariants.standard.url`, the merge loop at ~127 skips it, and the chapter WAV is
   short by that passage. A listener hears a jump.
2. **Stale** — a block that already had audio fails while re-rendering. Its old url still
   exists on disk, so the merge loop at ~127 **accepts it**. The chapter WAV is full length
   and contains the wrong take: old text, old voice, or old direction. A listener hears
   something plausible and wrong. This is the worse case and it is currently invisible.

Done means: the API reports both cases structurally, the UI refuses to say "Rendered" when
either happened and says which, a retry completes the chapter, and there are tests for all of it.

---

## Guardrails (read before touching anything)

- **GREEN (do autonomously):** edit `prosecast/renderer.py` (the per-block loop, the report
  dict, the merge loop), `server.py` (`_run_one_render_job` status logic, `chapter_results`
  projection), `static/index.html` (`pollRenderStatus` and the three render call sites); add
  tests under `tests/`; add `tests/ui/check_render_incomplete.py`; `STATUS.md` / `HANDOFF.md`
  at chapter-close; LOCAL commits.
- **YELLOW (ask first):** any change to the shape of an existing `/render_status` field that
  the UI fixtures pin. **Adding** fields is green; renaming or retyping one is not. If
  `scripts/refresh_ui_fixtures.py` output changes for any reason other than your new fields,
  STOP.
- **RED (never):** run a real render or real synthesis (every test mocks
  `TTSEngine.synthesize_segment` or `synthesize`); call Chatterbox, ElevenLabs or Ollama;
  delete or overwrite any `.wav` outside a `tmp_path`; touch a real book under `library/`;
  touch `corrections.jsonl` or `voice_map.json`; modify or revert the other session's
  uncommitted work listed in the precondition; edit `_cache_key`, `merge_next`, or the
  `block_{i:04d}.wav` naming (that is E8); `git push`.

---

## Smallest healthy-loop check (verify this before walking away)

Before Step 1, run `.venv/bin/pytest tests/ -q` and **write the baseline count into
`STATUS.md`**. Do not assume the E8-era figure of 297 passed / 1 skipped; E9 through E11
shipped since. After Step 1 the count must be baseline **plus** your new renderer tests, with
nothing newly failing. If the count went down, you have STOPPED there.

---

## Step 0 — Orient (read, don't write)

Read `CLAUDE.md` and `HANDOFF.md` → "Known-real, not yet fixed". Then, in code:

- **Renderer:** `prosecast/renderer.py` — the report dict (~80), the per-block loop (~104),
  the failure branch (~113), the merge loop (~127, reads `audioVariants.standard.url`).
- **Worker:** `server.py` `_run_one_render_job` (~2180) — per-chapter `chapter_results`
  projection (~2194, currently the tuple `chapter_index, skipped, rendered, cached, failed,
  audio_seconds`), the exception path (~2214), the status decision (~2220).
- **Status endpoint:** `get_render_status` (~2310) returns the job dict wholesale, so any
  field you add to `chapter_results` is served with no endpoint change.
- **UI:** `pollRenderStatus` (~5691). Call sites: first-run wizard (~4036), single chapter
  (~5957, the one that paints `✓ Rendered` at ~5983), render-all (~6026), pipeline (~6314),
  export (~6409). Export reuses the same poller — **do not change export's behavior**, it has
  no block concept.

Note for yourself and confirm in code: on failure `synthesize_segment` does **not** write
`cacheKey`, so a failed block stays cache-miss and a plain re-render retries exactly the
blocks that failed. You are not building retry. You are testing that it already works.

Write nothing in this step.

---

## Step 1 — The renderer says which kind of failure (finding, renderer side)

In the per-block loop, capture the block's pre-existing audio state **before** calling
`synthesize_segment`:

```python
prior = block.get("audioVariants", {}).get("standard", {}).get("url")
had_prior = bool(prior and Path(prior).exists())
```

On failure, record a structured entry instead of only a counter:

```python
report["failed_blocks"].append({
    "index": i,
    "segment_id": block.get("segmentId"),
    "kind": "stale" if had_prior else "missing",
})
```

Keep `report["failed"]` as the count (existing callers read it). Add to the report dict:
`"failed_blocks": []`, `"stale_blocks": 0`, `"missing_blocks": 0`, filled from the list.

In the merge loop at ~127, a block whose segment id is in `failed_blocks` with kind `stale`
is still merged — do not change that, a short chapter is not better than a stale one — but
the report must carry it. The point of this chapter is that the report stops lying, not that
the audio changes.

**Tests** (new, in `tests/test_render_queue.py` or a new `tests/test_render_report.py`), all
with mocked synthesis and a `tmp_path` book from `tests/synthetic.py`:

1. One block of five fails on a first render → `failed == 1`, one `missing` entry, chapter
   WAV is shorter than the all-success case.
2. Every block fails on a first render → `failed == 5`, five `missing`, no chapter WAV or an
   empty one (assert whichever the code actually does, and say which in `STATUS.md`).
3. A block with existing on-disk audio fails while re-rendering → `failed == 1`, one **stale**
   entry, chapter WAV is full length and contains the old take.
4. Retry: re-run the render with synthesis no longer failing → `failed == 0` and the
   previously failed blocks are now `rendered`, not `cached`.

Run the suite. Baseline plus four. **Commit `E12.1: the renderer reports both failure kinds`.**

---

## Step 2 — Job status honors block failures (API side)

In `_run_one_render_job`:

- Extend the `chapter_results` projection to carry `failed_blocks`, `stale_blocks`,
  `missing_blocks` alongside the existing keys.
- Change the status decision so block failures count:

```python
errors = [c for c in job["chapter_results"] if c.get("error")]
incomplete = [c for c in job["chapter_results"] if c.get("failed")]
job["status"] = "done" if not (errors or incomplete) else "done_with_errors"
```

- Set `job["error"]` to a sentence that names both kinds when present, e.g.
  `"2 chapter(s) failed; 7 block(s) missing, 3 block(s) stale — see chapter_results"`.
  A job with only stale blocks must still say so.

Do not add a new status string. `done_with_errors` already exists and already means this;
the bug was that nothing set it.

**Tests** in `tests/test_render_queue.py`: a job whose only problem is block failures ends
`done_with_errors`; a fully clean job still ends `done`; the summary sentence distinguishes
missing from stale.

Run the suite. **Commit `E12.2: block failures reach job status`.**

---

## Step 3 — The UI stops saying "Rendered" (user side)

`pollRenderStatus` keeps resolving on `done_with_errors`. Do **not** convert it to a reject:
partial audio exists, and the callers' refresh-and-repaint work must still run. Branch after
the resolve instead.

At the single-chapter site (~5957) and the render-all site (~6026):

- If `s.status === 'done_with_errors'`, do the normal refresh, then paint an incomplete state
  rather than `✓ Rendered` — a distinct class and label (`⚠ Incomplete`), and a `title`
  summarising counts, naming stale separately from missing, with a plain-language line for
  stale: audio exists but is an older take.
- The button must stay actionable so a retry is one click. Do not graduate it to the compact
  `↺` "done" affordance on an incomplete render.
- Leave the first-run wizard (~4036) and the export site (~6409) alone unless the wizard
  paints a success string on `done_with_errors`; if it does, give it the same treatment, and
  nothing more.

Add `tests/ui/check_render_incomplete.py` following the shape of the existing headless checks.
**`tests/ui/check_library_board.py` is another session's untracked file — leave it exactly as
it is.** Note in `STATUS.md` that the repo now has seven headless UI checks, and reconcile the
count with `HANDOFF.md` ~588 (six) and `CLAUDE.md` (which still implies four).

Run the suite plus your UI check. **Commit `E12.3: the UI reports incomplete renders`.**

---

## Step 4 — Chapter-close

- `STATUS.md`: session entry "2026-09-12 (Claude Code, Mac) — E12: render honesty" in the
  house style. Include the recorded test baseline, the final count, and what test 2 actually
  asserted about an all-failed chapter.
- `HANDOFF.md`: add a "Fixed in E12" note. State plainly what is **not** fixed: stale audio
  is now reported but still merged, and the correction race and audio identity remain open
  as E8.
- `docs/CC_BRIEF_data_safety.md` (E8): add one line under Mission noting E12 shipped first
  and that E8's findings list should be re-verified against current code before running.
  Change nothing else in that brief.
- Commit `E12.4: chapter-close`. `git status -sb` clean except the other session's work if it
  was stashed rather than committed. `[ahead N]`. **Do not push.**

END OF BRIEF
