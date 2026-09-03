# CC BRIEF — The Voices tab (voice library + notes + audition + sourcing)

**Written 2026-08-31 for an autonomous Claude Code run in `~/dev/prosecast`.**
**This brief has 8 steps (0–7). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

---

## Mission

Today the only way to record what a voice sounds like is to hand-edit `voice_meta.json` in an
editor, and the only way to find out is to render something and listen. Build a **Voices**
view in the ProseCast UI that makes the voice bank a first-class thing you can browse, audition,
annotate, filter, and grow — and make "this voice doesn't work" an enforceable fact instead of
a note nobody reads.

Four capabilities, in priority order:

1. **Notes + gender editing** — replaces hand-editing `voice_meta.json`.
2. **Audition + compare** — play a line in any voice from the page; A/B two voices.
3. **Tags, filter, and retire** — structured tags + a rating + a `hidden` flag that actually
   pulls a voice out of auto-assignment.
4. **Find more voices** — a panel listing vetted sources with their licences (seed of the
   marketplace).

Do NOT change server state on the Chatterbox box, do NOT touch precious data, do NOT `git push`.

---

## Guardrails (read before touching anything)

- **GREEN (do autonomously):** edit `server.py`, `static/index.html`, `voice_meta.json` schema;
  add `voice_sources.json`; add files under `tests/`; update `STATUS.md`; make a LOCAL
  `git commit` (no push).
- **YELLOW (leave for Tyler — do NOT do):** uploading voices; anything that POSTs to the
  Chatterbox server (`/upload_reference`, `/upload_predefined_voice`, `/save_settings`,
  `/restart_server`, `/api/unload`). You may only GET from it. Also: judging audio quality.
- **RED (never):** modify or delete `library/**/ir.json`, `voice_map.json`, or
  `corrections.jsonl`; delete anything in `library/`; delete anything in `librivox_voices/`;
  spend money; `git push`.
- ⚠️ **The working tree has uncommitted changes** in `server.py`, `static/index.html`,
  `prosecast/tts_engine.py`, `tests/test_render_queue.py` and `STATUS.md` from the 2026-08-30
  session. **Do not stash, reset, or check out over them.** Commit your work on top; if you
  need a clean diff, use `git diff` — never `git checkout --`.

## Smallest healthy-loop check (verify this before walking away)

After **Step 2**, run `.venv/bin/pytest tests/ -v`. All 107 existing tests must still pass and
your new `voice_meta` tests must pass. If that's green, the loop is healthy. If `server.py`
won't import, you have STOPPED there — that's the expected early exit.

---

## Step 0 — Orient

Read, in this order: `CLAUDE.md`, `STATUS.md`, `docs/voice-sources.md` (new — the licence
tiering and the reference-clip recipe), `docs/chatterbox-contract.md`, then in `server.py`:
`_chatterbox_voices()` (line ~149), `_voice_pool()` (~173), `_voice_meta()` / `_apply_voice_meta()`
(~189–220), `_voice_labels()` (~222), `_default_voice_map()` (~240), `GET /voices` (~1084),
`GET /voice/preview/{voice_name}` (~1153), `GET /engine_status` + `POST /engine_status/recheck`
(~1247/~1293). Then `tests/test_voice_meta.py`. Then skim `static/index.html` — note that the
cast drawer already builds voice dropdowns and already has working preview buttons
(`castPreview`, `#preview-audio-el`); **you are mirroring that code, not inventing new patterns.**

### Five traps in this specific code — read these before you write anything

1. **`_apply_voice_meta` appends a glyph to `name`.** It returns
   `{"id", "name": name + " ♀", "gender"}`. The glyph-suffixed name is a *display* string. It
   is NOT a key. Never round-trip it back to the server as an identifier.
2. **The overlay is keyed inconsistently today.** `_apply_voice_meta` looks up
   `meta.get(v["name"]) or meta.get(stem)`, and the existing file has both styles
   (`"Robert"`, `"bright-indian-1"`). **All new writes must use the stem** —
   `Path(id.split(":",1)[-1]).stem` — and the read path must keep the legacy display-name
   fallback so existing entries keep working. Write a test for both.
3. **`_chatterbox_voice_cache` is cached for the process lifetime.** Newly uploaded voices do
   NOT appear on a page reload. The Voices view's refresh button must call
   `POST /engine_status/recheck` (which clears that cache), not just re-`GET /voices`.
4. **`voice_meta.json` has a `_readme` key whose value is a string, not an object.** Preserve
   it verbatim on every write, and never let it reach the UI as a voice.
5. **`_voice_pool()` is used for BOTH validation and auto-assignment.** Hiding must not break
   validation — see Step 3, this is the one that will bite.

---

## Step 1 — Extend the metadata schema (backwards compatible)

`voice_meta.json` entries gain optional fields. Existing files with only `gender`/`notes` must
keep working untouched.

```jsonc
"us-nyc-add": {
  "gender": "m",                 // existing: "f" | "m" | ""
  "notes": "great for gruff narrator",  // existing: free text
  "tags": ["american", "nyc", "gravelly"],   // NEW: free-form, lowercased
  "rating": 4,                   // NEW: 0-5, 0 = unrated
  "hidden": false,               // NEW: true = retired, excluded from auto-assignment
  "region": "nyc",               // NEW: seeded by the staging script
  "accent_label": "American accent, New York City",  // NEW: as published by the source
  "license": "CC0-1.0",          // NEW: SPDX
  "distributable": true,         // NEW: safe to ship in a release / voice pack
  "source_url": "https://archive.org/download/..."   // NEW: provenance
}
```

`scripts/stage_librivox_dialects.py` already writes `region`, `accent_label`, `license`,
`distributable` and `source_url` on upload (`merge_voice_meta`) — match those names exactly.

Update `_apply_voice_meta` to pass the new fields through onto each voice dict (defaults:
`tags: []`, `rating: 0`, `hidden: false`, empty strings elsewhere). Keep `gender` and the glyph
behaviour exactly as-is so the cast drawer is unaffected.

---

## Step 2 — Server endpoints

All three go in `server.py` near the existing `/voices` route.

### `GET /voices/library`
Returns the full picture for the Voices view — do not overload `GET /voices`, the cast drawer
depends on its current shape.

```json
{ "engine": "chatterbox",
  "voices": [ { "id": "predefined:us-nyc-add.wav", "name": "Us Nyc Add", "key": "us-nyc-add",
                "gender": "m", "notes": "...", "tags": [], "rating": 0, "hidden": false,
                "region": "nyc", "license": "CC0-1.0", "distributable": true,
                "source_url": "...", "kind": "predefined" } ],
  "orphans": ["ScarJo_Voice"] }
```

- `key` is the canonical overlay key (the stem). The UI writes back with it.
- `kind` is `"predefined"` or `"clone"` (clone = bare filename id, per `_chatterbox_voices`).
- `orphans` = overlay keys with no matching live voice (e.g. a voice deleted server-side).
  Surface them, don't delete them — silently dropping Tyler's notes is unacceptable.
- Filter out the server's own test artefacts with the same regex `scripts/audition_voices.py`
  uses: `cachetest|selftest|scanprobe` (case-insensitive). Reuse it, don't re-type it.

### `POST /voices/meta/{key}`
Body: any subset of `{gender, notes, tags, rating, hidden}`. Patch semantics — absent fields are
left alone. Returns the merged entry.

- Validate: `gender ∈ {"f","m",""}`; `rating` int 0–5; `tags` a list of ≤ 12 short strings,
  lowercased and de-duplicated; `notes` ≤ 2000 chars. 400 on anything else.
- **Write atomically**: `json.dump` to a temp file in the same directory, then `os.replace`.
  A half-written `voice_meta.json` loses every note in the file, and `_voice_meta()` swallows
  `JSONDecodeError` and returns `{}` — so the failure mode is *silent total loss of notes*.
  This is not optional.
- Preserve `_readme` and preserve key order (`json.dump(..., indent=2, ensure_ascii=False)`).
- Do NOT reject unknown keys — a voice can be annotated before it exists on the server.

### `GET /voices/sources`
Serves a new `voice_sources.json` at the repo root: the vetted-source catalogue for the "Find
more voices" panel. Seed it from `docs/voice-sources.md` — one entry per source with
`{id, name, tier, license, us_regional (bool), speakers, url, blurb, command}` where `tier` is
`"ship" | "private" | "never"` and `command` is the CLI line that pulls it (null when there is
no script yet). Include at minimum: LibriVox dialects (ship, has a command), Hi-Fi TTS,
LibriTTS-R, VCTK, Qwen3-VoiceDesign, CORAAL, GMU Speech Accent Archive, EARS, and the NEVER
entries with their reasons — the point of listing a `never` is so nobody researches it twice.

**This endpoint is read-only. It must not shell out, download anything, or POST to the
Chatterbox server.** The panel shows the command; Tyler runs it. (That is the YELLOW line.)

---

## Step 3 — Make `hidden` mean something

⚠️ **The trap:** `_voice_pool(engine)` is used both to validate saved voice maps
(`save_voice_map` 400s on an unknown id) *and* to build auto-assignments in
`_default_voice_map`. If you filter hidden voices out of `_voice_pool` itself, every book that
already has a hidden voice assigned will **fail to save** — and the failure looks like a UI bug,
not a policy decision.

Do this instead:

- `_voice_pool(engine)` keeps returning **everything**. Validation is unchanged.
- Add `_voice_pool_assignable(engine)` = `_voice_pool` minus hidden minus test artefacts.
- Use `_voice_pool_assignable` in `_default_voice_map()` only. If it comes back empty, fall
  back to the full pool rather than assigning `''` to every character.
- In `GET /voices` (the cast drawer's source), keep hidden voices in the list but include the
  `hidden` flag so the UI can grey them out and sort them last. A voice already cast must stay
  selectable, otherwise reopening an old book silently loses its cast.

Add a test for exactly this: a book whose saved map references a hidden voice still saves.

---

## Step 4 — The Voices view (`static/index.html`)

**Constraint: single file, no build step, no new dependencies, no `localStorage` for anything
that matters.** The file is ~2,740 lines and carries a full On Air theme layer; a backup of the
pre-On-Air version lives in `.backup/`. Take a fresh backup before you start.

**Navigation.** There is no tab bar today — the app is book-list + `#main` + slide-in panels.
Add a minimal two-item nav in the `<header>` (next to the theme toggle): **Books** / **Voices**.
Selecting Voices hides `#book-list` + `#main` + the player bar and shows a new `#voices-view`.
No router, no URL change; a single `showView('books'|'voices')` function. Preserve scroll
position when switching back.

**Layout of `#voices-view`:**

- **Toolbar:** search box (matches name, notes, tags, region), filter chips for gender /
  region / `distributable` / rating≥N / show-hidden, a sort control (name, rating, region,
  recently-edited), a **↻ refresh** button that calls `POST /engine_status/recheck` then
  reloads (see trap 3), and a count — *"38 voices · 20 American · 3 hidden."*
- **Voice rows** (a table or card grid — match the existing panel styling and the On Air
  tokens; the `.plaque` component already in the CSS is a good fit for the licence badge):
  name + gender glyph, region, tag chips, a 5-star rating, an inline-editable notes field, a
  ▶ audition button, an "A/B" button, and a ⋯ menu with *Hide/Unhide* and *Copy voice id*.
- **Notes editing:** edit in place, save on blur *and* on ⌘/Ctrl-Enter, debounce ~600 ms,
  show a tiny saved/failed indicator per row. Never block on a save. If a save fails, keep the
  text in the box and say so — losing a typed note is the worst possible bug here.
- **Licence badge** per row: green when `distributable`, amber otherwise, with the SPDX id in
  the tooltip. This is what makes "can I ship this voice pack?" answerable at a glance.
- **Audition:** reuse `GET /voice/preview/{voice_name}` and the existing `#preview-audio-el`
  pattern from `castPreview`. ⚠️ Chatterbox predefined ids look like `predefined:foo.wav` —
  `encodeURIComponent` the id, and confirm the FastAPI path param survives the colon (it does
  today for the cast drawer; verify, don't assume). A shared audition-line text box at the top
  of the view feeds `?text=`, defaulting to `audition_voices.py`'s line: *"The rain had stopped
  by the time she reached the crossroads, and somewhere beyond the hills, a bell began to
  ring."* Cap at 300 chars, matching the endpoint.
- **A/B compare:** two slots (A and B). Clicking A/B on a row fills the next empty slot. A
  sticky bar at the bottom plays A, plays B, and plays them back-to-back with a ~400 ms gap.
  Renders are slow — cache each slot's fetched blob URL so re-playing is instant, and show a
  spinner on first fetch. This is the feature that actually answers "which of these two is my
  narrator," so make it feel fast.
- **Find more voices panel:** a slide-in from `GET /voices/sources`, grouped by tier, each with
  the licence, US-regional flag, a one-line blurb, and the pull command in a copyable code
  block. **A copy button, not a run button** — running it is Tyler's call (YELLOW). Put a short
  standing note at the top of the panel: *a CC licence is a copyright licence, not voice
  consent* — with a link to `docs/voice-sources.md`.

**Empty and failure states, explicitly:** engine is `say`/`stub` (the strip already knows —
say "connect Chatterbox to manage voices" and don't render a fake list); zero voices; a filter
that matches nothing; `/voices/library` returning 500. Silent failure is the thing that costs
hours here.

---

## Step 5 — Tests

Extend `tests/test_voice_meta.py`, add `tests/test_voices_library.py`. Mock the Chatterbox
fetches the same way the existing tests do — **no network in tests.**

1. `/voices/library` shape: key is the stem; legacy display-name overlay entries still resolve;
   test artefacts (`cachetest*`, `*selftest*`, `*scanprobe*`) are excluded; `orphans` lists
   overlay keys with no live voice.
2. `POST /voices/meta/{key}` patch semantics: setting `notes` alone leaves `gender` intact;
   `_readme` survives; invalid gender/rating/tags → 400.
3. Atomic write: patch `os.replace` to raise and assert the original file is still intact and
   parseable. (This is the test that protects every note Tyler will ever write.)
4. `hidden` excluded from `_voice_pool_assignable` but present in `_voice_pool`, **and** a
   voice map referencing a hidden voice still saves (Step 3's trap).
5. `/voices/sources` returns the catalogue and every entry has a `tier` in the allowed set.

---

## Step 6 — Verify by looking at it

Run `.venv/bin/pytest tests/ -v` — 107 existing + your new ones, all green.

Then take headless Chromium screenshots of the Voices view in **both skins** (`onair` and
`classic`) against a mocked `/voices/library`, the same way the 2026-08-27 session verified the
On Air skin. Check: nothing overflows at ~1280px, the tag chips wrap, the rating stars are
hittable, hidden rows are visibly de-emphasised, and the licence badges read correctly in both
themes. Save them under `output/` (disposable) and note the paths in `STATUS.md`.

Do NOT judge audio. The audition path is verified by Tyler with his ears.

---

## Step 7 — Chapter-close handoff

Update `STATUS.md` (this project's file ONLY — never the master `DASHBOARD.md`) with a new
session block:

- **Where it's at:** Voices view shipped; endpoints; schema extension; `hidden` wired into
  auto-assignment only.
- **Next step:** the two YELLOW items for Tyler — (1) audition `librivox_voices/*.wav`, cull,
  rename survivors, and upload with
  `python3 scripts/stage_librivox_dialects.py --from-dir librivox_voices --upload-to http://GIDEON_HOST:8101`;
  (2) hit ↻ in the Voices view and rate/tag the new bank.
- **Blocked on:** whatever is actually true.

Then run `scripts/status_rollup.py` if it exists here, and make a local commit:
`git add -A && git commit -m "Voices view: library endpoints, metadata schema, audition + A/B, source catalogue"`.
**Do NOT push** — and do not commit over the 2026-08-30 working-tree changes without reading
them first (see Guardrails).

---

## What you are explicitly NOT doing (leave for Tyler)

- Uploading voices or any POST to the Chatterbox server.
- Judging audio quality or picking which voices are keepers.
- Building the marketplace. The sources panel is a **catalogue with copyable commands** — no
  accounts, no payments, no downloads triggered from the UI.
- Pushing to GitHub.

END OF BRIEF
