# CC BRIEF — E7: the Voices tab (voice library + notes + audition + sourcing)

**Written 2026-08-31, rewritten 2026-09-06 for an autonomous Claude Code run in `~/dev/prosecast`, on the Mac.**
**This brief has 8 steps (0–7). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

*(The 09-06 rewrite kept the 08-31 design and replaced everything that E1–E6 made stale: line
numbers, test counts, the view-switch pattern, the fixture rules, the atomic-write helper, the
tree state. If something here still disagrees with the code, the code wins — note it in STATUS.)*

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
4. **Find more voices** — a panel listing vetted sources with their licences (the seed of the
   cast exchange described in `docs/PHILOSOPHY.md`).

Do NOT change server state on the Chatterbox box, do NOT touch precious data, do NOT `git push`.

---

## Guardrails (read before touching anything)

- **GREEN (do autonomously):** edit `server.py`, `static/index.html`, the `voice_meta.json`
  schema; add `voice_sources.json`; add files under `tests/` and `tests/ui/`; extend
  `scripts/refresh_ui_fixtures.py`; update `STATUS.md` and `HANDOFF.md` at chapter-close;
  LOCAL `git commit`s as each step says (no push).
- **YELLOW (leave for Tyler — do NOT do):** uploading voices; anything that POSTs to the
  Chatterbox server (`/upload_reference`, `/upload_predefined_voice`, `/save_settings`,
  `/restart_server`, `/api/unload`). You may only GET from it. Also: judging audio quality.
- **RED (never):** modify or delete `library/**/ir.json`, `voice_map.json`, or
  `corrections.jsonl`; delete anything in `library/` or `librivox_voices/`; hand-write anything
  in `tests/fixtures/`; write JSON with a plain `open(..., "w")` when `lib.write_json_atomic`
  exists; put a real host/IP/user in a tracked file (placeholders are `GIDEON_HOST`,
  `192.168.1.50`, `/Users/YOUR_USER`; the real Chatterbox URL lives only in gitignored
  `config.json` and is read through `prosecast.config`); spend money; `git push`.
- **Working tree:** expected clean at `main` (E6.10 is `dedc900`). `git status -sb` first; if
  there are modified files, STOP and write what you found to `STATUS.md`.
- **Tests that start a background job must wait for it** — `monkeypatch` restores paths the
  instant a test returns (HANDOFF "Key facts", 09-06). Nothing in this brief needs a thread; if
  you find yourself adding one, stop and reconsider.

## Smallest healthy-loop check (verify this before walking away)

After **Step 2**, `.venv/bin/pytest tests/ -q` must show the baseline **plus** your new tests.
Baseline on this Mac: **247 passed, 1 skipped** (the skip is `en_core_web_sm`; 6 more skip
without tesseract — skips are healthy). If `server.py` imports and the count went up, the loop
is healthy. If it went down, you have STOPPED there.

---

## Step 0 — Orient (read, don't write)

Read, in this order: `CLAUDE.md`, `HANDOFF.md` → "Key facts" (it supersedes everything else),
`docs/voice-sources.md` (the licence tiering and the reference-clip recipe),
`docs/chatterbox-contract.md`. Then in `server.py`:

- `_chatterbox_voice_cache` (~157) and `_chatterbox_voices()` (~160) → these call
  `tts_engine.fetch_chatterbox_predefined()` / `fetch_chatterbox_references()` (~444 / ~425);
- `_voice_pool()` (~184), `VOICE_META_PATH` (~200), `_voice_meta()` (~203),
  `_apply_voice_meta()` (~217), `_voice_labels()` (~231), `_default_voice_map()` (~248);
- `GET /voices` (~1303), `POST /voice_map` → `save_voice_map` (~1343/1355),
  `GET /voice/preview/{voice_name}` (~1372; `?text` capped at 300, ~1399),
  `GET /engine_status` (~1466), `POST /engine_status/recheck` (~1513 — clears the voice cache);
- `GET /setup/status` (~1557) → the `voice_engine` row carries `engine`, `source`, `state`.

Then `prosecast/library.py:69` `write_json_atomic(path, data)` — the only way JSON gets written
in this repo. Then `tests/test_voice_meta.py` (3 tests, `meta_file` fixture swapping
`server.VOICE_META_PATH`) and `tests/conftest.py` (autouse config isolation via
`PROSECAST_CONFIG`). Then in `static/index.html` (now **~4,900 lines**): `fetchJSON` (~1911),
`playPreview(btn, url)` / `stopPreview` / `#preview-audio-el` (~3758 / ~1651) — `castPreview`
delegates to `playPreview`, so mirror **`playPreview`**, not `castPreview`; `recheckEngine()`
(~1888) and `paintEngineStatus` (~1861); the view-switch idiom `body.reader-open #reader-view`
(CSS ~273, `openReaderView` ~2352) and `body.setup-open #setup-view` (CSS ~342,
`openSetupView` / `closeSetupView` / `isSetupOpen` / `toggleSetupView` ~2515–2530) plus the
header `#setup-chip` (~1544); the Setup page's card builders `engineChoices` / `engineCardsHTML`
(~2640–2660) for card styling; `.plaque` (~1523). Then `tests/ui/check_first_run.py` — the
template for the headless check — and `scripts/refresh_ui_fixtures.py`.

### Six traps in this specific code — read these before you write anything

1. **`_apply_voice_meta` appends a glyph to `name`.** It returns
   `{"id", "name": name + " ♀", "gender"}`. The glyph-suffixed name is a *display* string. It
   is NOT a key. Never round-trip it back to the server as an identifier.
2. **The overlay is keyed inconsistently today.** `_apply_voice_meta` looks up
   `meta.get(v["name"]) or meta.get(stem)`, and the existing file has both styles
   (`"Robert"`, `"bright-indian-1"`). **All new writes must use the stem** —
   `Path(id.split(":",1)[-1]).stem` — and the read path must keep the legacy display-name
   fallback so existing entries keep working. Write a test for both. One entry
   (`x-irish-padraig`) already carries the full extended schema from Step 1 — use it as the
   real example in tests.
3. **`_chatterbox_voice_cache` is cached for the process lifetime.** Newly uploaded voices do
   NOT appear on a page reload. The Voices view's refresh button must go through
   `recheckEngine()` → `POST /engine_status/recheck` (which clears that cache), not just
   re-`GET /voices`.
4. **`voice_meta.json` has a `_readme` key whose value is a string, not an object.** Preserve
   it verbatim on every write, and never let it reach the UI as a voice.
5. **`_voice_pool()` is used for BOTH validation and auto-assignment.** Hiding must not break
   validation — see Step 3, this is the one that will bite.
6. **`.hidden` is scoped per modal.** The global rule only exists for `.modal-overlay`; each
   modal scopes its own (`.ingest-modal .hidden`, `.firstrun-modal .fr-hidden`). A Voices view
   needs its own hidden rule or its collapsed panels will not collapse. Also: the class name
   **`.voices-btn` is already taken** (the per-book "🎤 Voices" button, ~706/~2003) — name the
   new view's classes `vv-*` to avoid the collision.

Write nothing in this step.

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
  "region": "nyc",               // already written by the staging script
  "accent_label": "American accent, New York City",
  "license": "CC0-1.0",          // SPDX
  "distributable": true,         // safe to ship in a release / voice pack
  "source_url": "https://archive.org/download/..."
}
```

`scripts/stage_librivox_dialects.py` → `merge_voice_meta` (~504–545) already writes `region`,
`accent_label`, `license`, `distributable` and `source_url` on upload — match those names
exactly. Update `_apply_voice_meta` to pass the new fields through onto each voice dict
(defaults: `tags: []`, `rating: 0`, `hidden: false`, empty strings elsewhere). Keep `gender`
and the glyph behaviour exactly as-is so the cast drawer is unaffected.

`git commit -m "E7.1: voice_meta schema — tags, rating, hidden, provenance (backwards compatible)"`.

---

## Step 2 — Server endpoints

All three go in `server.py` near the existing `/voices` route.

### `GET /voices/library`
Returns the full picture for the Voices view — do not overload `GET /voices`; the cast drawer
(`availableVoices` ~3280, `castData.voices` ~3490) depends on its current shape.

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
  uses (`_SKIP`, line 24: `cachetest|selftest|scanprobe`, case-insensitive). Import or lift it;
  don't re-type it.
- For `say` / `piper` / `elevenlabs`, return that engine's static list from
  `VoiceAssigner.SAY_VOICES` etc. (`tts_engine.py` ~31–66) with the overlay applied — the view
  must not be Chatterbox-only, even if the sourcing panel mostly is.

### `POST /voices/meta/{key}`
Body: any subset of `{gender, notes, tags, rating, hidden}`. Patch semantics — absent fields are
left alone. Returns the merged entry.

- Validate: `gender ∈ {"f","m",""}`; `rating` int 0–5; `tags` a list of ≤ 12 short strings,
  lowercased and de-duplicated; `notes` ≤ 2000 chars. 400 on anything else, with a sentence.
- **Write with `lib.write_json_atomic`.** A half-written `voice_meta.json` loses every note in
  the file, and `_voice_meta()` swallows `JSONDecodeError` and returns `{}` — so the failure
  mode is *silent total loss of notes*. Use the helper; do not hand-roll temp + `os.replace`.
- Preserve `_readme` and key order (`indent=2, ensure_ascii=False` — check what the helper
  does and match the file's current formatting so the diff stays readable).
- Do NOT reject unknown keys — a voice can be annotated before it exists on the server.

### `GET /voices/sources`
Serves a new `voice_sources.json` at the repo root: the vetted-source catalogue for the "Find
more voices" panel. Seed it from `docs/voice-sources.md` (tiers at ~45 / ~98 / ~109) — one
entry per source with `{id, name, tier, license, us_regional (bool), speakers, url, blurb,
command}` where `tier` is `"ship" | "private" | "never"` and `command` is the CLI line that
pulls it (`null` when there is no script yet). Include at minimum: LibriVox dialects (ship, has a
command), Hi-Fi TTS, LibriTTS-R, VCTK, Qwen3-VoiceDesign, CORAAL, GMU Speech Accent Archive,
EARS, and the NEVER entries with their reasons — the point of listing a `never` is so nobody
researches it twice. **Placeholders only** in any URL that points at Tyler's own hosts.

**This endpoint is read-only. It must not shell out, download anything, or POST to the
Chatterbox server.** The panel shows the command; Tyler runs it. (That is the YELLOW line.)

Tests for this step are in Step 5 — write them now, not later. **Healthy-loop check here.**
`git commit -m "E7.2: /voices/library, /voices/meta, /voices/sources"`.

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
`git commit -m "E7.3: hidden voices leave auto-assignment, never validation"`.

---

## Step 4 — The Voices view (`static/index.html`)

**Constraint: single file, no build step, no new dependencies, no `localStorage` for anything
that matters.** Take a fresh backup first, following the house naming:
`.backup/index_pre-voices_2026-09-06.html`.

**Navigation — follow the existing pattern, do not invent one.** The app already has two
full alternate views that share `#main`'s grid cell and are switched by body classes:
`body.reader-open #reader-view` and `body.setup-open #setup-view`, each with
`open*View()` / `close*View()` / `is*Open()`. Add a third the same way: `body.voices-open
#voices-view`, `openVoicesView()` / `closeVoicesView()` / `isVoicesOpen()`, mutually exclusive
with the other two (opening removes `reader-open` and `setup-open`; closing returns to the
reader if audio is playing, exactly as `closeSetupView` does). Entry point: a **🎤 Voices**
chip in the header next to `#setup-chip`. No router, no URL change.

**Layout of `#voices-view`** (classes prefixed `vv-`):

- **Toolbar:** search box (matches name, notes, tags, region), filter chips for gender /
  region / `distributable` / rating≥N / show-hidden, a sort control (name, rating, region,
  recently-edited), a **↻ refresh** button that calls `recheckEngine()` then reloads (trap 3),
  and a count — *"38 voices · 20 American · 3 hidden."*
- **Voice rows** (a table or card grid — match the existing panel styling and the On Air
  tokens; `.plaque` is a good fit for the licence badge): name + gender glyph, region, tag
  chips, a 5-star rating, an inline-editable notes field, a ▶ audition button, an "A/B"
  button, and a ⋯ menu with *Hide/Unhide* and *Copy voice id*.
- **Notes editing:** edit in place, save on blur *and* on ⌘/Ctrl-Enter, debounce ~600 ms,
  show a tiny saved/failed indicator per row. Never block on a save. If a save fails, keep the
  text in the box and say so — losing a typed note is the worst possible bug here.
- **Licence badge** per row: green when `distributable`, amber otherwise, with the SPDX id in
  the tooltip. This is what makes "can I ship this voice pack?" answerable at a glance.
- **Audition:** reuse `GET /voice/preview/{voice_name}` through `playPreview(btn, url)` so the
  toggle/stop semantics match the cast drawer. Chatterbox predefined ids look like
  `predefined:foo.wav` — `encodeURIComponent` the id as `castPreview` does (~3765). A shared
  audition-line text box at the top of the view feeds `?text=`, defaulting to
  `audition_voices.py`'s `DEFAULT_TEXT`: *"The rain had stopped by the time she reached the
  crossroads, and somewhere beyond the hills, a bell began to ring."* Cap at 300 chars.
- **A/B compare:** two slots (A and B). Clicking A/B on a row fills the next empty slot. A
  sticky bar at the bottom plays A, plays B, and plays them back-to-back with a ~400 ms gap.
  Renders are slow — cache each slot's fetched blob URL so re-playing is instant, and show a
  spinner on first fetch. This is the feature that actually answers "which of these two is my
  narrator," so make it feel fast.
- **Find more voices panel:** a slide-in from `GET /voices/sources`, grouped by tier, each with
  the licence, US-regional flag, a one-line blurb, and the pull command in a copyable code
  block. **A copy button, not a run button** — running it is Tyler's call (YELLOW). Put a short
  standing note at the top of the panel: *a CC licence is a copyright licence, not voice
  consent* — the wording already exists in `librivox_voices/SOURCES.md` (~11–14); link to
  `docs/voice-sources.md`.

**Empty and failure states, explicitly:** engine is `say`/`stub`/`piper` (show that engine's
list and say plainly that sourcing and cloning need Chatterbox — don't render a fake list and
don't render nothing); zero voices; a filter that matches nothing; `/voices/library` returning
500 (say so, keep the toolbar). Silent failure is the thing that costs hours here. Both skins.

`git commit -m "E7.4: Voices view — library, notes, audition + A/B, sources panel"`.

---

## Step 5 — Tests (pytest)

Extend `tests/test_voice_meta.py`, add `tests/test_voices_library.py`. Mock the Chatterbox
fetches the way the existing tests do — `monkeypatch.setattr(server, "_chatterbox_voice_cache",
[...])` + `monkeypatch.setattr(server, "_active_engine", "chatterbox")`
(`tests/test_render_queue.py` ~153–171) or `monkeypatch.setattr(tts,
"fetch_chatterbox_predefined", ...)` (`tests/test_preflight.py` ~38). **No network in tests.**

1. `/voices/library` shape: key is the stem; legacy display-name overlay entries still resolve;
   test artefacts (`cachetest*`, `*selftest*`, `*scanprobe*`) are excluded; `orphans` lists
   overlay keys with no live voice; the `say` engine returns its static list.
2. `POST /voices/meta/{key}` patch semantics: setting `notes` alone leaves `gender` intact;
   `_readme` survives; invalid gender/rating/tags → 400.
3. Atomic write: patch `os.replace` to raise and assert the original file is still intact and
   parseable. (This is the test that protects every note Tyler will ever write.)
4. `hidden` excluded from `_voice_pool_assignable` but present in `_voice_pool`, **and** a
   voice map referencing a hidden voice still saves (Step 3's trap).
5. `/voices/sources` returns the catalogue, every entry has a `tier` in the allowed set, and no
   entry contains a non-placeholder private host.

These land with Steps 2–3's commits; this step is the checklist.

---

## Step 6 — Headless check: `tests/ui/check_voices.py`

**Not screenshots by hand — the house pattern.** Add `voices_library.json` (and
`voices_sources.json`) to `scripts/refresh_ui_fixtures.py` so they are generated from the real
endpoints against a mocked voice cache, plus a drift test tying each fixture to its endpoint the
way `test_ingest.py` / `test_sample_book.py` do. Then `tests/ui/check_voices.py`, same shape as
`check_first_run.py`: fixtures only, tiny HTTP server, Playwright, **both skins**, `check()`
per assertion, exit 1 on any failure, `voices_*.png` screenshots (gitignored).

Assert at least: the header chip opens `#voices-view` and closes `#setup-view` / `#reader-view`;
the count line matches the fixture; search narrows rows; the hidden filter toggles a
de-emphasised row; a note edit issues `POST /voices/meta/<key>` with the **stem** as the key
(intercept the request); the licence badge class matches `distributable`; the A/B bar appears
after two slot clicks; the empty state renders for a `say` fixture; nothing overflows at
1280 px; every collapsed panel is actually hidden in both skins (trap 6).

Run all five `tests/ui/` checks — the four existing ones must still pass. Playwright is in the
Mac venv, not the device VM. `git commit -m "E7.5: headless Voices check, both skins, generated fixtures"`.

Do NOT judge audio. The audition path is verified by Tyler with his ears.

---

## Step 7 — Chapter-close

- `STATUS.md`: new session entry "2026-09-06 (Claude Code, Mac) — E7: the Voices tab" in the
  house style (Shipped / Verified / Things the code showed / Still Tyler's to verify), header
  status line + `Updated:` date, test counts before/after.
- `HANDOFF.md`: phase table gets an **E7** row; "Where to start" updated; "Key facts" gets a
  short **"The Voices view (new, 09-06)"** paragraph: the three endpoints, stem keys, the
  `_voice_pool` / `_voice_pool_assignable` split, the `vv-` prefix and body-class switch. Then
  add this finding to the YELLOW list for Tyler, because it will bite him on the next upload:
  **`librivox_voices/` holds 39 WAVs that Tyler renamed after auditioning (notes appended to the
  filenames); `MANIFEST.json` still lists the original 55 names, and `merge_voice_meta` keys on
  the MANIFEST filename — so an upload today would silently skip ~38 of them.** Do not fix the
  script in this brief; name the problem.
- Final `.venv/bin/pytest tests/ -q` and all five `tests/ui/` checks green.
- `git commit -m "E7.6: chapter-close — STATUS/HANDOFF for the Voices tab"`.
- `git status -sb` must be clean and read `[ahead N]`. **Do not push.**

---

## What you are explicitly NOT doing (leave for Tyler)

- Uploading voices or any POST to the Chatterbox server.
- Judging audio quality or picking which voices are keepers.
- Fixing the MANIFEST/rename mismatch in `stage_librivox_dialects.py` (name it, don't fix it).
- Building the exchange. The sources panel is a **catalogue with copyable commands** — no
  accounts, no payments, no downloads triggered from the UI.
- Pushing to GitHub.

END OF BRIEF
