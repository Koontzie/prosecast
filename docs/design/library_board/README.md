# Handoff: ProseCast Library Board

## Overview

The right-hand pane of ProseCast's desktop web app currently shows
`Select a book to begin.` on an empty field. This handoff replaces it with a
**library board** — the view a user checks before sitting down to work.

The board answers exactly one question: **what is the next move on this book?**
It is not a stats readout. Per book it shows three things and nothing else:
the title, one state phrase, one hairline progress indicator.

Three structural directions were explored (card grid, rundown, grouped-by-state).
**The card grid — artboard 1A — is the approved direction.** 1B and 1C are
included as rejected alternates for context only; do not build them.

Two follow-on screens are also approved and specified: the skippable casting
prompt (2A) and the book landing it lands on (2B).

## About the Design Files

The files in this bundle are **design references created in HTML** — prototypes
showing intended look and behavior, not production code to copy directly.

This case is unusually direct, however: the target environment is
`static/index.html`, a single-file vanilla-JS app with hand-written CSS and a
FastAPI backend (`server.py`). There is no React, no build step, no component
library. So the design's inline styles must be **rewritten as CSS rules in
index.html's existing stylesheet** and its markup as `createElement` calls in
index.html's existing idiom — not pasted in as-is.

`IMPLEMENT_library_board.md` in this bundle is the primary document: it is a
patch-level spec written against the real repo, with file and line references.
Read it first. This README is the design reference behind it.

## Fidelity

**High-fidelity.** Final colors, typography, spacing, and states. The tiles
should be recreated to match — this is the app's own on-air skin, and the
palette below is the skin's existing token set, not a new one.

One deliberate exception: the mockup uses inline `style` attributes and
absolute pixel values at a fixed 1600×1000 artboard size. The real pane is
fluid. Use the grid and type values as given; let the pane's width drive the
column measure.

## Target environment

| | |
|---|---|
| UI | `static/index.html` — single file, vanilla JS, hand-written CSS |
| Server | `server.py` — FastAPI |
| Library helpers | `prosecast/library.py` |
| Pipeline | `prosecast/pipeline.py` |
| Insertion point | `index.html:1856` — `<p class="idle-msg">Select a book to begin.</p>` |
| Sidebar (unchanged) | 390px `<aside>`; `renderBookList` at `index.html:2319` |

The 390px sidebar in the mockups is drawn as a plain edge strip **for
proportion only** — it already exists and is out of scope.

## Screens / Views

### 1A — Library Board (the deliverable)

**Purpose:** triage. The user scans the pane and knows which book to open and
why, without reading numbers.

**Layout**

- Fills the `<main>` pane to the right of the sidebar (390px in the mockup,
  280px in the real app — collapsible to a 52px rail, open by default; see
  IMPLEMENT_library_board.md §9, and §4's correction of "closed by default").
- Pane padding: `40px 56px 0` (relaxed from an initial `56px 56px 0` so both
  tile rows fit a 1000px-tall window at the revised `.82` aspect-ratio).
- Header row: baseline-aligned, `space-between`, `padding-bottom: 22px`,
  `border-bottom: 1px solid #33261a`.
- Grid: `display: grid; grid-template-columns: repeat(min(N,4), minmax(0,1fr)); gap: 22px;`
  `margin-top: 24px`, where **N is the wider of the actionable/settled rows**,
  not a fixed 4 — an unused track reads as a dead strip, not as whitespace.
  See IMPLEMENT_library_board.md §10.
- Tiles are **book-shaped**: `aspect-ratio: .82` (relaxed from an initial
  `.68`; still portrait, roughly a trade paperback). Two rows of four at
  eight books, but settled tiles always start a fresh row via a full-span
  spacer — they never share a row with actionable tiles just because the
  actionable count doesn't divide evenly into the column count.
- Tile internals: `display:flex; flex-direction:column`. Title at top, state
  line pushed to the bottom with `margin-top:auto`, hairline last.

**Two tile weights — this is the board's whole visual logic**

| | Actionable | Settled |
|---|---|---|
| States | needs-casting, cast, rendering | ready |
| Order | first (grid `order: 1–2`) | second (grid `order: 3`) |
| Background | `#241a11` (raised) | `#161009` (pane ground — tile recedes) |
| Border | `1px solid #3d2c1b`, **top border 2px in the state color** | `1px solid #33261a`, no accent |
| Padding | `26px 24px 22px` | `22px 20px 18px` |
| Title | 35px / 500 / line-height 1.06 / letter-spacing −0.015em | 19px / 400 / line-height 1.25 |

Finished books are not hidden — they are quieted. A user with eight ready
books should see a calm pane, not an empty one.

**Components inside a tile — exactly three**

1. **Title** — Jost, weight per table above, `color: #f2e6ca`,
   `text-wrap: pretty`. Long titles wrap; the tile does not truncate.
2. **State line** — a 6px dot (`border-radius: 50%`, `flex: none`) then the
   phrase. IBM Plex Mono, 11.5px, `letter-spacing: .14em`,
   `text-transform: uppercase`. `padding-top: 20px`, `gap: 9px`.
3. **Hairline** — `height: 2px; background: #33261a`, `margin-top: 16px`, with
   an inner fill `div` at `width: <progress>%`.

Nothing else. No chapter counts, no dates, no character counts, no "last
opened", no hover tooltip. The tile component should take no `children` and no
`meta` prop, so the restraint survives future feature requests.

**The five states**

| Key | Phrase | Dot / text | Hairline fill | Top border |
|---|---|---|---|---|
| `needs-casting` | `Needs casting` | `#d8503a` (text red too) | none | `#d8503a` |
| `cast` | `Cast, not yet rendered` | dot `#cd9a43`, text `#9b8767` | none | `#e0b25c` |
| `rendering` | `N of M rendered` | `#e0b25c` (text amber too) | `#e0b25c` at N/M | `#e0b25c` |
| `ready` | `Ready to play` | dot `#63b3a0`, text `#9b8767` | `#63b3a0` full | none |

A number appears **only when the number is the state** — `3 of 52 rendered`.
Everywhere else the phrase is words.

There is **no `exported` state.** "Exported" and "Ready to play" both mean
*done, go listen*; the user does not act differently on them, so they collapse
into one phrase. The M4B's existence belongs on the book page, not the board.

**Live signal** — when a render is genuinely running, that book's amber dot
pulses: `@keyframes` 0/100% `opacity: 1`, 50% `opacity: .28`, `1.9s
ease-in-out infinite`. Exactly one thing on the board moves. A paused or
queued render gets a **static** amber dot — an animating dot on a stalled job
is the board lying, and that is the failure mode that makes people stop
trusting it.

**Header**

- Left: `Library` — Jost 28px / 400 / `#f2e6ca`.
- Right, in a `flex` row with `gap: 22px`:
  - `8 books` — IBM Plex Mono 12px, `letter-spacing: .16em`, uppercase, `#6f5f45`.
  - `+ Add book` — IBM Plex Mono 12px, same tracking, `color: #cd9a43`,
    `border: 1px solid #cd9a43`, `padding: 8px 16px`.
    Hover: `color: #161009; background: #cd9a43`.
    Wire to the existing `triggerBookPicker()` (`index.html:1850`) — same file
    input, same ingest wizard, second entry point. Keep the sidebar button too.

**Empty case (first run)**

Header still renders, reading `Library` · `0 books` · `+ Add book`. Body is one
centered mono line — `Nothing cast yet` — IBM Plex Mono 12px,
`letter-spacing: .14em`, uppercase, `#6f5f45`, `padding: 52px 0 44px`. The Add
button is the only affordance.

`refreshBooks` (`index.html:2337`) already distinguishes *no books at all* from
*all books hidden*. Keep both messages — they are different problems.

Shown in the bundle as a small inset on artboard 1C.

### 2A — Casting prompt (skippable)

**Purpose:** offer the next move on an uncast book without demanding it.

Opens as a modal over the dimmed pane (`rgba(14,10,6,.72)` scrim) when the
user clicks a `needs-casting` tile.

- Panel: 720px wide, `#1d1510`, `1px solid #33261a`,
  `box-shadow: 0 40px 90px rgba(0,0,0,.55)`, centered.
- Title bar: `padding: 16px 32px`, bottom hairline. Left `Cast the book` in
  gold mono 11px / `.22em` / uppercase; right `Step 1 of 1` in `#6f5f45`.
- Body `padding: 34px 32px 30px`, `gap: 26px`.
  - Book title — Jost 31px / 500 / line-height 1.12 / `−.015em`.
  - Explainer — IBM Plex Mono 13px, line-height 1.6, `#9b8767`, max-width 520px:
    *"Assign a voice to each speaker now, or skip — every line falls back to the
    narrator voice and you can cast later."*
  - Speaker rows, hairline-separated, `padding: 15px 0`: name in Jost 19px
    `#f2e6ca`; right column 230px wide. Assigned shows the voice in teal mono
    12px (`Bramble · en-GB`); unassigned shows a `Choose a voice ▾` select in
    `#6f5f45` with a `1px solid #33261a` border and `8px 12px` padding.
  - Footer count — `137 lines unresolved`, mono 11.5px, `#6f5f45`.
- Action row, `space-between`:
  - `Skip for now` — text only, `#9b8767`, hover `#f2e6ca`. **Left side, alone.**
  - `Run AI pass` — gold text, `1px solid #33261a`, hover border `#cd9a43`.
  - `Cast & continue` — `#161009` on `#cd9a43`, hover `#e2b463`.

Skip sits opposite the primaries so it reads as a real path, not a dismissal.
It closes the modal and leaves the user on the chapter list with narrator
fallback: no state change, no nag, no second prompt on the next open.

### 2B — Book landing (where skip lands)

**Purpose:** the working view for one book. This screen largely exists already
(the chapter list); the change is the header and the explicit next-move line.

- Header: book title Jost 36px / 500 / line-height 1.1 / `−.015em`, with the
  book's **one state phrase** beneath it (dot + mono, same tokens as the tile).
- Right-aligned actions: `Cast` and `Voices` as outlined gold chips
  (`1px solid #33261a`, hover border `#cd9a43`), `Render all` as the solid gold
  primary. All `padding: 11px 18–20px`, mono 12px `.14em` uppercase.
- Pipeline strip: `#1d1510` panel, `1px solid #33261a`, `padding: 14px 20px`,
  `gap: 14px`. Stage names in mono 11px `.2em` uppercase, colored by status
  (done `#63b3a0`, active `#e0b25c`, blocked `#d8503a`, pending `#6f5f45`),
  separated by `→` in `#33261a`. Right-aligned, after a `flex: 1` spacer:
  **`Next move: cast 137 unresolved lines`** in mono 11.5px `#9b8767`.
  This line is the point of the strip — the stages alone don't tell the user
  what to do.
- Chapters header: `Chapters` Jost 22px; right `31 · none rendered` in mono
  11.5px `#6f5f45`. Bottom hairline.
- Chapter rows, `padding: 17px 0`, hairline-separated, `gap: 24px`:
  index in mono 13px `#6f5f45` (34px wide) · title Jost 20px `#f2e6ca`
  (`flex: 1`) · state in mono 11.5px uppercase, 190px wide (`Narration only` in
  `#6f5f45`, `7 unresolved` in `#d8503a`) · `Generate` chip, gold on
  `1px solid #33261a`.

The chapter screen is the one place a second number is allowed. It is a work
queue, not the board.

## Interactions & Behavior

**Click routing — differs by state.** This is the board's payoff and the easy
thing to get wrong; sending every tile to the same place discards the triage
the board just did.

| Tile state | Click does |
|---|---|
| `needs-casting` | open the book (2B) **and** raise the casting modal (2A) |
| `cast`, `rendering`, `ready` | open the book (2B) as today |

```js
function openBookFor(book, st) {
  loadBook(book.slug);
  if (st.key === 'needs-casting') openCastPrompt(book.slug);
}
```

Other behavior:

- **Hover** — tile is a `<button>`; hover may lift the border toward
  `#3d2c1b`. No tooltips, no revealed metadata.
- **Live re-render** — repaint tiles on the same poll that already drives the
  job progress bar. Nothing else on the board changes without a refresh.
- **Transitions** — none beyond the one pulse. The board is checked, not
  browsed.
- **Add book** — reuses the existing upload → wizard → ingest job flow
  (`index.html:5276`). On completion, refresh the board.
- **Responsive** — the artboards are fixed 1600×1000 for comparison; the real
  pane is fluid. Drop to 3 columns below roughly 1200px of pane width, 2 below
  900px (expanding the sidebar counts against this, same as shrinking the
  window). Tiles keep `aspect-ratio: .82`. Below that width-driven cap, the
  column count can drop further still if the library itself is small — see
  the N-not-4 note above.

## State Management

**One derived function is the entire feature.** Everything else is layout.

**Corrected 2026-09-12:** the first draft below OR'd in `b.unresolved > 0`.
Delete it. Frankenstein has no `voice_map.json` at all, so `!b.cast` already
catches it — the clause changed nothing for the case it was written to
justify, and it wrongly sent A Parade (cast, 5 unresolved, 0/115) and Sample
Book (cast, 9 unresolved, 2/2 — no spaCy in the venv) to `needs-casting`.
Unresolved means "review the attribution," not "pick voices"; that's a
different next move and, if it ever needs surfacing, a different phrase and
click target — not this rule.

```js
function bookState(b) {
  const total = b.chapters || 0, done = b.rendered || 0;
  let key;
  if (!b.cast)          key = 'needs-casting';
  else if (done === 0)  key = 'cast';
  else if (done < total) key = 'partial';
  else                  key = 'ready';
  return {
    key,
    phrase: key === 'partial' ? `${done} of ${total} rendered` : PHRASES[key],
    tone: TONES[key],
    progress: total ? done / total : 0,
  };
}
```

(The state key is `partial`, not `rendering` — `rendering` was already taken
by "a render is running right now" elsewhere in the file.)

Rule order encodes real product logic: **no voice map means not cast**, full
stop. That is what makes Frankenstein read `Needs casting`.

The return value carries four fields and no more. Every other number the app
knows stays out of it — that is the mechanism that keeps the board honest.

**Partition, don't let the grid decide:**

```js
const RANK = ['needs-casting', 'partial', 'cast', 'ready'];
// sort by RANK, then title.localeCompare
```

**Server data required.** `/books` (`server.py:464`) returns `slug, title,
chapters, unresolved, hidden, pinned` — two fields short. Add inside the
existing loop:

```python
n_ch = len(ir.get("chapters", []))
rendered = sum(1 for i in range(n_ch) if lib.chapter_wav_path(slug, i).exists())
cast = lib.voice_map_path(slug).exists()
```

…and surface them as `"rendered"` and `"cast"`. No new endpoint, no extra disk
walk beyond `exists()` calls the chapter endpoint already makes
(`server.py:1054`).

Live-render check mirrors `_any_live_job` (`server.py:496`):

```js
function isRenderLive(slug) {
  return !!(state.activeJob && state.activeJob.book_slug === slug
            && state.activeJob.status === 'running');
}
```

**Security requirement.** Build tiles with `createElement` +
`textContent`, never template-string HTML. The existing comment at
`index.html:2374` is explicit that a user-set `display_title` can carry `'` or
`<`. The board is the newest place to forget this.

## Design Tokens

The on-air skin's existing token set. Map through the `--oa-*` CSS vars — the
`[data-theme="onair"]` block already defines several (`index.html:1404` uses
`var(--oa-dim)`); add any missing rather than inlining hexes.

| Token | Hex | Use |
|---|---|---|
| bg | `#161009` | pane ground; settled tile fill |
| panel | `#1d1510` | sidebar, modal, pipeline strip |
| raised | `#241a11` | actionable tile fill |
| hairline | `#33261a` | all 1px rules, unfilled bar track |
| hairline-lift | `#3d2c1b` | actionable tile border |
| cream | `#f2e6ca` | primary text, all titles |
| muted | `#9b8767` | state phrases (neutral states) |
| dim | `#6f5f45` | counts, labels, placeholders |
| gold | `#cd9a43` | primary action, `cast` dot |
| gold-hi | `#e2b463` | gold hover |
| teal | `#63b3a0` | `ready` |
| red | `#d8503a` | `needs-casting` |
| amber | `#e0b25c` | `rendering` |

**Type**

- **Jost** — titles and UI. 500 for titles, 400 for headers/labels.
  Title sizes: 35px actionable tile / 19px settled tile / 36px book landing /
  31px modal / 28px pane header / 20–22px rows.
  Large titles get `letter-spacing: −.015em` and `line-height: 1.06–1.12`.
- **IBM Plex Mono** — every label, state phrase, and number. 11–13px,
  `letter-spacing: .14em` (states) / `.16em` (counts) / `.2–.22em` (section
  labels), `text-transform: uppercase`.
- **Limelight** — wordmark only. **Never** for book titles.

**Spacing** — 22px grid gap; 56px pane padding; tile padding 26/24/22
(actionable) and 22/20/18 (settled); 20px title-to-state; 16px state-to-bar.

**Other** — no border radius anywhere except the 6px state dots (`50%`). One
shadow, on the modal only: `0 40px 90px rgba(0,0,0,.55)`.

## Assets

**None, by design.** No cover art, no book spines, no illustration, no stock
photography, no emoji. The 6px state dot is the only permitted ornament.

The app has no cover-art data. Inventing it here would design a feature that
does not exist. If the tiles feel bare, that is the brief working — the board
is checked in two seconds, not browsed.

Fonts load from Google Fonts in the mockup; the app should use whatever
mechanism `index.html` already uses for Jost and IBM Plex Mono.

## The eight real books

Use these verbatim for any fixture or test. They are the real library
(`prosecast/library/`), with their real states.

| Title | State | Derivation |
|---|---|---|
| Sample Book | `Ready to play` | cast, rendered == chapters (its 9 unresolved lines, absent spaCy, don't count — see the 2026-09-12 correction above) |
| Showrunner Run Sheet | `Ready to play` | rendered == chapters |
| Carl RPG Core Rulebook | `Ready to play` | 11 of 11 |
| She Kills Monsters (Young Adventurers Edition) | `Ready to play` | 16 of 16 |
| Brigands & Breadknives | `3 of 52 rendered` | 0 < rendered < chapters |
| A Parade of Horribles | `Cast, not yet rendered` | cast, 0 of 115 (its 5 unresolved lines don't count either) |
| Carousel B8 Ch17–30 | `Needs casting` | no voice map |
| Frankenstein; or, The Modern Prometheus | `Needs casting` | no voice map (137 unresolved lines are a separate, unrelated fact about it) |

## Files

| File | What it is |
|---|---|
| `IMPLEMENT_library_board.md` | **Start here.** Patch-level spec against the real repo, with line references and order of work. |
| `Library Board.dc.html` | The design prototype. Six artboards at 1600×1000: **1A (approved)**, 1B and 1C (rejected alternates, context only), 2A casting modal, 2B book landing. Open in a browser. |
| `support.js` | Runtime the prototype needs to render. Not for production. |

## Order of work

1. **Server fields** (~6 lines). Verify against the real library — the eight
   books above should derive exactly those eight states.
2. **`bookState` + ordering**, with a unit test on the five branches. Point it
   at `tests/fixtures`; `scripts/refresh_ui_fixtures.py` exists for this.
3. **Tile + CSS**, replacing `idle-msg` at `index.html:1856`.
4. **Header and empty case.**
5. **Click routing + the 2A modal.**

Steps 1–2 are the feature. Steps 3–5 are markup that follows from them.

## Two open product questions

Worth settling before step 5, because they change behavior rather than pixels:

1. **Should a skipped casting prompt ever return?** The spec says no — skip is
   permanent until the user clicks `Cast`. If it should reappear (once? after a
   render?), that is a stored flag and needs deciding now.
2. **Does `Render all` on an uncast book flatten to narrator, or refuse?** 2B
   shows it enabled on a `needs-casting` book. If the pipeline would reject
   that, the button needs a disabled state and the board's `needs-casting`
   phrase becomes a harder gate than currently drawn.
