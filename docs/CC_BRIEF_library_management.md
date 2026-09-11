# CC BRIEF — E11: the shelf chapter (hide a book, remove a book, rename it — and never touch ir.json)

**Written 2026-09-11 for an autonomous Claude Code run in `~/dev/prosecast`, on the Mac.**
**This brief has 8 steps (0–7). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

**The rule for the whole brief: no book is ever deleted, only moved. No `.wav` is ever deleted.
`ir.json` is never written by any code you add.** The render worker is a whole-document writer
(HANDOFF, "Known-real, not yet fixed", finding 2) — that is precisely why shelf state gets its
own file instead of a field in the IR.

**Steps 0–4 are the shippable chapter (E11). Steps 5–6 are the extras (E11.5) and can be a
separate commit or a separate session.** If Step 4's verification is not fully green, STOP and
close the chapter there rather than starting Step 5.

---

## Mission

The library has no management at all: a book can be ingested and never removed, and every book
is always visible. Tyler records social videos from this UI and needs to hide work-in-progress
and licensed material from frame.

Done means: every book row has a `⋯` menu with **Hide**, **Rename** and **Remove**; hidden books
vanish from the sidebar behind a "Show hidden" toggle; removing a book moves its whole folder to
`library/.trash/` and is undoable with one `mv`; and none of it can be lost by a render running
at the same time.

---

## Guardrails (read before touching anything)

- **GREEN (do autonomously):** edit `prosecast/library.py`, `server.py` (`/books` and the new
  shelf endpoints), `static/index.html`, `README.md`; add tests under `tests/` and
  `tests/ui/check_library_menu.py`; re-run `scripts/refresh_ui_fixtures.py` (the `/books` shape
  changes on purpose in this chapter); `STATUS.md` / `HANDOFF.md` at chapter-close; LOCAL commits.
- **YELLOW (do exactly as written):** Step 4's manual verification operates on Tyler's real
  library. Use `showrunner_run_sheet` as the guinea pig — it is the smallest book with renders.
  Trash it, confirm it is gone from the UI, then `mv` it back and confirm it returns intact.
- **RED (never):** `rm`, `shutil.rmtree`, or `os.remove` on anything under `library/` — removal
  is `shutil.move` into `library/.trash/`, always; write `ir.json`, `voice_map.json` or
  `corrections.jsonl` from any code in this chapter; regenerate audio (no `POST /render`, no
  `force`); hand-write anything in `tests/fixtures/`; put a real host/IP/user in a tracked file
  (placeholders: `GIDEON_HOST`, `192.168.1.50`, `/Users/YOUR_USER`); `git push`.
- **Tests that start a background job must wait for it** (HANDOFF "Key facts", 09-06).
- **Working tree:** expected clean at `main`. `git status -sb` first; if there are modified files,
  STOP and write what you found to `STATUS.md`.

---

## Step 0 — Read first

`HANDOFF.md` "Known-real, not yet fixed" (finding 2 is the reason for this design),
`prosecast/library.py` in full, `server.py` `/books` (~line 460) and the render-job dict
`_render_jobs` (~line 73), and `static/index.html` `renderBookList` (~line 2238) and its three
call sites (2227, 3478, 5206).

Note before you start: `list_book_slugs()` globs `*/ir.json` relative to `LIBRARY_DIR`. A book at
`library/.trash/<slug>/ir.json` is one level deeper and therefore **already invisible** to that
glob. Do not add a `.trash` exclusion — verify the glob instead, with a test.

---

## Step 1 — `shelf.json`, the only new state

Add to `prosecast/library.py`:

```
shelf_path(slug)      → library/<slug>/shelf.json
read_shelf(slug)      → dict, defaults applied, never raises
write_shelf(slug, d)  → lib.write_json_atomic
TRASH_DIR             → library/.trash
```

Schema, all optional, defaults in the reader:

```json
{
  "hidden": false,
  "pinned": false,
  "sort_index": null,
  "display_title": null
}
```

`sort_index` is reserved for a later drag-reorder; nothing reads it in this chapter. Write the
docstring in the house style of `library.py`'s module header: say what the file is, say that it
is view state and therefore **disposable** — losing it costs a checkbox, not labour — and say
explicitly that it exists so that hiding or renaming a book during a render cannot be clobbered
by the render worker's whole-document IR write.

`library/` is already gitignored wholesale (`.gitignore:14`), so `.trash/` and `shelf.json` are
covered. Confirm this rather than adding a line.

---

## Step 2 — The endpoints

**`GET /books`** gains `?include_hidden=false` and two fields per book:

- `hidden` — from the shelf.
- `title` — `display_title` if set, else `ir["book_title"]`, else the slug. The IR is not modified.
- `pinned` — from the shelf (used in Step 5; ship the field now so the fixture is stable).

Default (`include_hidden` absent or false) omits hidden books entirely. Sort: pinned first, then
by title, case-insensitive.

**`PATCH /books/{slug}/shelf`** — body may carry `hidden`, `pinned`, `display_title`. Validate
types (`hidden`/`pinned` must be bool, `display_title` a non-empty string ≤ 200 chars or null);
reject anything else with the house 400 style. Returns the merged shelf. Journal it via
`_journal(slug, "shelf", payload)`.

**`DELETE /books/{slug}`** — `shutil.move(lib.book_dir(slug), lib.TRASH_DIR / f"{slug}__{utc}")`
where `utc` is `%Y%m%dT%H%M%SZ`. Returns `{"trashed": "<trash dir name>"}`.

**The guard that matters:** refuse with **409** if the slug has a live job. Check `_render_jobs`
for any entry whose `book_slug` is this slug and whose status is not terminal, and the same for
the ingest and pipeline job dicts. Without this, the worker's next `save_ir()` recreates the
directory a half-second after the move and you get a phantom book with one chapter and no
journal. The 409 detail should name the job — the house style is a sentence, not a code.

Path safety on every one of these: the slug must be in `lib.list_book_slugs()`. Never build a
path from an unvalidated slug (`/audio` at server.py:1863 is the pattern to mirror).

There is **no empty-trash endpoint** in this chapter — deliberately. Trashed books accumulate
until Tyler moves or deletes them himself; the README line in Step 4 tells him how.

---

## Step 3 — The `⋯` menu

In `renderBookList`, each row gets a small overflow button (`⋯`) that opens a menu with **Hide**
(or **Unhide** when the book is hidden), **Rename…** and **Remove…**. Keep the existing
`loadBook` click on the row itself — the `⋯` must `stopPropagation` so opening the menu does not
also load the book.

- **Hide** → `PATCH .../shelf {hidden:true}` → refetch → repaint. No confirmation; it is reversible.
- **Rename…** → inline edit in the row, or a small prompt-style field in the house style —
  **not** `window.prompt`. Saves `display_title`. An empty value clears the override and the
  real title returns.
- **Remove…** → a confirmation that names the book and says, in plain words, that it moves to
  `library/.trash/` and can be moved back. One click to confirm; no typed title. On 409, show
  the server's sentence — "a render is running" is the honest message, not "failed".

Sidebar gains a **Show hidden** toggle and an honest count line, mirroring the Voices view's
pattern (E7). When hidden books are shown, each carries a muted `hidden` badge. The toggle is
UI-only state — it does not persist across reloads in this chapter.

`renderBookList` currently interpolates `b.title` and `b.slug` straight into an `onclick`
attribute. A book titled with an apostrophe already breaks that; a `display_title` makes it
trivially reachable. **Fix it while you are here** — build the rows with `createElement` and
`textContent`, or escape properly. Add a test with a title containing `'` and `<`.

---

## Step 4 — Verify E11, then decide

1. `.venv/bin/pytest tests/ -q` — new tests cover: shelf round-trip; `/books` hides and reveals;
   `display_title` overrides without `ir.json` changing (assert the IR's mtime and bytes are
   identical before and after a rename); DELETE moves rather than deletes (the trash dir exists
   and `ir.json` is inside it); DELETE during a live render returns 409 and the directory is
   still there; a trashed book does not appear in `list_book_slugs()`; a title with `'` and `<`
   renders without breaking the row.
2. `scripts/refresh_ui_fixtures.py` — `/books` shape changed on purpose. Then
   `.venv/bin/pytest tests/ -q` again; the drift tests must pass against the regenerated fixtures.
3. `python3 tests/ui/check_library_menu.py` — new, following `check_voices.py`'s structure:
   the menu opens without loading the book, Hide removes the row and the count line tells the
   truth, Show hidden brings it back with a badge, and a hidden book is still reachable by slug.
   Both skins. Save `library_classic.png` / `library_onair.png` next to the others.
4. All five existing `tests/ui/` checks green.
5. **The real-library check (YELLOW).** With the server running: hide `showrunner_run_sheet`,
   confirm it leaves the sidebar and comes back with Show hidden. Rename it, reload, confirm the
   new name survives and `library/showrunner_run_sheet/ir.json` is byte-identical to before.
   Remove it; confirm `library/.trash/showrunner_run_sheet__<stamp>/` holds `ir.json`,
   `voice_map.json`, `corrections.jsonl` and `renders/`. Then
   `mv library/.trash/showrunner_run_sheet__<stamp> library/showrunner_run_sheet` and confirm it
   returns to the sidebar with its audio intact. **Render nothing.**
6. `README.md` gains a short "Managing the library" section: hide is a view filter, remove means
   `library/.trash/`, and the `mv` line that brings a book back.

**If any of 1–6 is not green, STOP here.** Write it to `STATUS.md`, commit what works as
`E11: the shelf chapter`, and do not start Step 5.

---

## Step 5 — E11.5a: pin to top

`PATCH .../shelf {pinned:true}` already exists from Step 2; wire **Pin to top** into the `⋯` menu
and sort pinned books first. Pinned rows get a small marker. That is the whole feature — drag
reorder is explicitly **not** in this chapter; `sort_index` stays unused and unread.

Why pin and not reorder: pinning plus hiding already gives Tyler a clean recording shelf (hide
everything not in the video, pin what is), and a drag-reorder needs persisted ordering,
reindexing on delete, and its own UI test for a gain he can get from two clicks.

---

## Step 6 — E11.5b: duplicate a book (the careful one)

**`POST /books/{slug}/duplicate`** → new slug from `ingest_mod.slug_for(title)` so the
never-overwrite guarantee at `ingest.py:66` still holds.

Copy **`ir.json`, `voice_map.json`, `corrections.jsonl` and `shelf.json` only. Do NOT copy
`renders/` or `exports/`.**

Then, in the copied IR, **reset every audio pointer**: for every block, every entry in
`audioVariants` gets `url = None` and `cached = False`, and `cacheKey` is removed. Write it with
`lib.write_json_atomic` (this is the one place a *new* `ir.json` is written — never the original's).

**This is the whole reason duplicate is a separate step.** Block audio URLs in the IR are
absolute paths, many of them still pointing at the legacy `output/` layout —
`she_kills_monsters` has 612 of them, `carl_rpg_core_rulebook` 966. A plain `cp -r` gives the
clone pointers into the original's audio, and `renderer.block_needs_synthesis` (renderer.py:45)
checks `os.path.exists(variant["url"])`, so the clone would report everything cached while
playing the original's wavs — and trashing the original would silently gut it. A clone is
"same text, same cast, no audio yet". Say that in the confirmation copy.

Give the clone `display_title = "<title> (copy)"` so the two are distinguishable in the sidebar
without touching either IR's `book_title`.

Test it against a real fixture with absolute URLs: assert zero `cached: true` and zero non-null
`url` in the clone, assert the original's `ir.json` is byte-identical after the duplicate, and
assert `renders/` was not copied.

---

## Step 7 — Chapter-close

- `STATUS.md`: session entry "2026-09-1x (Claude Code, Mac) — E11: the shelf chapter" in the
  house style, with the test numbers and the real-library round-trip written out.
- `HANDOFF.md`: "Key facts" gains three lines — shelf state lives in `library/<slug>/shelf.json`
  and is disposable; removal is a move to `library/.trash/` and there is no empty-trash; a
  duplicate resets every audio pointer because IR block URLs are absolute. Note that E8's
  whole-document-write finding is *worked around* here, not fixed.
- `CLAUDE.md`: add `shelf.json` to the library layout description.
- Commits: `E11: the shelf chapter` (Steps 1–4), then `E11.5: pin and duplicate` (Steps 5–6) if
  reached, then `E11.6: chapter-close`. `git status -sb` clean, `[ahead N]`. **Do not push.**

END OF BRIEF
