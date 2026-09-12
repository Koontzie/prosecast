# Implementing the Library Board (artboard 1A)

Target: `static/index.html` + `server.py` in the prosecast repo. Replaces
`<p class="idle-msg">Select a book to begin.</p>` at index.html:1856.

**Corrections (2026-09-12, applied to the shipped code and to this doc the
same day):**

1. **Bug fix** — §2's `bookState` no longer has `|| b.unresolved > 0` in the
   needs-casting rule. The clause was redundant for the case it was written
   for (Frankenstein has no `voice_map.json` at all, so `!b.cast` already
   catches it) and wrong against the rest of the real library — it sent A
   Parade (`cast`, 5 unresolved, 0/115) and Sample Book (`cast`, 9
   unresolved, 2/2) to `needs-casting` when step 1's own expectations say
   `cast` and `ready`. Unresolved lines mean "review the attribution," not
   "pick voices" — routing them to the casting modal is the wrong next move,
   which is the one thing this board exists to get right. The rule is now
   `if (!b.cast) key = 'needs-casting';`, full stop.
2. **Renamed** the `'rendering'` state key to `'partial'` throughout (code and
   CSS selectors) — it collided with `isRenderLive()`'s unrelated "a render
   is running right now" meaning.
3. **Hidden books never reach the board's fetch.** `boardOrder`'s `!b.hidden`
   filter is now documented as a belt-and-braces guard, not the enforcement
   mechanism: the board's own fetch (`refreshLibraryBoard()`) calls plain
   `/books`, never `/books?include_hidden=true` — that query is the
   sidebar's alone. Hidden exists so a book stays out of frame while
   recording; letting it reach the board's data at all, even to filter
   client-side, would defeat that.
4. **§9 (sidebar collapse) defaults OPEN, not closed.** Collapsing to the
   52px rail is opt-in, persisted in `localStorage`; absence of a stored
   choice means expanded. §9 below reflects this.

---

## 1. Server — three fields on `/books`

`/books` (server.py:464) currently returns `slug, title, chapters, unresolved,
hidden, pinned`. The board needs two more. Inside the `for slug in
lib.list_book_slugs()` loop, after `shelf = lib.read_shelf(slug)`:

```python
n_ch = len(ir.get("chapters", []))
rendered = sum(1 for i in range(n_ch) if lib.chapter_wav_path(slug, i).exists())
cast = lib.voice_map_path(slug).exists()
```

and add to the appended dict:

```python
"rendered": rendered,
"cast": cast,
```

`unresolved` is already there. Nothing else is needed — no new endpoint, no
extra disk walk beyond the `n_ch` `exists()` calls the chapter list already
does at server.py:1054.

---

## 2. One derived state function

This is the whole feature. Everything else is layout. Put it next to
`renderBookList` in index.html.

```js
// The board's single source of truth. Four keys, one phrase each, one
// progress fraction. Deliberately returns nothing else — the board shows
// title + phrase + hairline and no fourth thing, so there is no fourth
// field to be tempted by.
//
// Unresolved lines are NOT part of this rule (2026-09-12 correction) —
// unresolved means "review the attribution," not "pick voices." A book can
// have unresolved lines and still be fully cast and rendered (Sample Book,
// on a machine without spaCy) — it must read "Ready to play."
const BOOK_STATES = {
  'needs-casting': { phrase: 'Needs casting',          tone: 'red'   },
  'cast':          { phrase: 'Cast, not yet rendered', tone: 'gold'  },
  'partial':       { phrase: null,                     tone: 'amber' }, // "N of M rendered"
  'ready':         { phrase: 'Ready to play',          tone: 'teal'  },
};

function bookState(b) {
  const total = b.chapters || 0;
  const done  = b.rendered || 0;
  let key;
  if (!b.cast)           key = 'needs-casting';
  else if (done === 0)   key = 'cast';
  else if (done < total) key = 'partial';
  else                   key = 'ready';
  return {
    key,
    phrase: key === 'partial' ? `${done} of ${total} rendered`
                               : BOOK_STATES[key].phrase,
    tone: BOOK_STATES[key].tone,
    progress: total ? done / total : 0,
  };
}
```

Rule order matters and encodes the real product logic: **no voice map means
not cast**, full stop. That is what makes Frankenstein (no `voice_map.json`)
read "Needs casting." Its 137 unresolved lines are a separate problem for a
future correction-UI surface, not this rule.

Note there is no `exported` state. "Exported" and "Ready to play" both mean
*done, go listen* — collapsing them removes a distinction the user does not
act on. The M4B's existence still belongs on the book page, not the board.

---

## 3. Partition, don't sort in the grid

```js
const ACTIONABLE = ['needs-casting', 'cast', 'partial'];
const RANK = ['needs-casting', 'partial', 'cast', 'ready'];

// `/books` (no include_hidden) never returns a hidden book, so this filter
// is a belt-and-braces guard, not the enforcement mechanism — the board
// must never even fetch hidden books (see §7's refreshLibraryBoard).
function boardOrder(books) {
  return books
    .filter(b => !b.hidden)
    .map(b => ({ book: b, st: bookState(b) }))
    .sort((a, z) =>
      RANK.indexOf(a.st.key) - RANK.indexOf(z.st.key) ||
      a.book.title.localeCompare(z.book.title));
}
```

Actionable books render raised and large; `ready` books render flat and small.
The board does the triage — that is the entire reason it exists instead of a
list.

---

## 4. Tokens

The on-air palette already lives as `--oa-*` vars (index.html:1404 uses
`var(--oa-dim)`). Map tones to those names rather than hexes:

```
red → var(--oa-red)    gold → var(--oa-gold)
amber → var(--oa-amber)  teal → var(--oa-teal)
```

If any are missing from the `[data-theme="onair"]` block, add them:
`--oa-red:#d8503a; --oa-amber:#e0b25c; --oa-teal:#63b3a0; --oa-gold:#cd9a43;
--oa-gold-hi:#e2b463; --oa-raised:#241a11; --oa-hairline:#33261a;`

---

## 5. The tile

Built with `createElement` + `textContent` throughout — the existing
`bookMenuHTML` comment (index.html:2374) is explicit that a `display_title`
can carry `'` or `<` and must never be interpolated into HTML. The board is no
exception.

```js
function bookTile({ book, st }, variant) {
  const big = variant === 'actionable';
  const el = document.createElement('button');
  el.className = 'lb-tile lb-' + variant;
  el.dataset.state = st.key;
  el.addEventListener('click', () => openBookFor(book, st));

  const t = document.createElement('div');
  t.className = 'lb-title';
  t.textContent = book.title;                  // display_title-safe

  const line = document.createElement('div');
  line.className = 'lb-state';
  const dot = document.createElement('span');
  dot.className = 'lb-dot' + (st.key === 'partial' && isRenderLive(book.slug)
                              ? ' lb-live' : '');
  const phrase = document.createElement('span');
  phrase.textContent = st.phrase;
  line.append(dot, phrase);

  const bar = document.createElement('div');
  bar.className = 'lb-bar';
  const fill = document.createElement('i');
  fill.style.width = (st.progress * 100) + '%';
  bar.appendChild(fill);

  el.append(t, line, bar);
  return el;
}
```

Three children. No `children` param, no `meta` slot — the component is the
constraint, so the restraint survives the next six months of feature requests.

CSS, keyed off `data-state` so tone is declarative:

```css
.lb-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
           gap:22px; margin-top:24px; }
/* Container queries, not viewport ones — the sidebar (§9) collapsing or
   opening changes the pane's width independently of the window's. */
@container (max-width:1200px) { .lb-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@container (max-width:900px)  { .lb-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.lb-tile { aspect-ratio:.82; display:flex; flex-direction:column;
           text-align:left; border:1px solid var(--oa-hairline);
           padding:26px 24px 22px; cursor:pointer; }
.lb-actionable { background:var(--oa-raised); border-top-width:2px; }
.lb-settled    { background:var(--oa-bg); padding:22px 20px 18px; }
.lb-actionable .lb-title { font-size:35px; line-height:1.06;
                           letter-spacing:-.015em; }
.lb-settled    .lb-title { font-size:19px; line-height:1.25; }
.lb-title { font-weight:500; color:var(--oa-cream); text-wrap:pretty; }
.lb-state { margin-top:auto; padding-top:20px; display:flex;
            align-items:center; gap:9px; font-family:'IBM Plex Mono',monospace;
            font-size:11.5px; letter-spacing:.14em; text-transform:uppercase;
            color:var(--oa-muted); }
.lb-dot { width:6px; height:6px; border-radius:50%; flex:none; }
.lb-bar { margin-top:16px; height:2px; background:var(--oa-hairline); }
.lb-bar i { display:block; height:2px; }

.lb-tile[data-state="needs-casting"] { border-top-color:var(--oa-red); }
.lb-tile[data-state="needs-casting"] .lb-dot,
.lb-tile[data-state="needs-casting"] .lb-state { color:var(--oa-red);
                                                 background-color:initial; }
.lb-tile[data-state="needs-casting"] .lb-dot { background:var(--oa-red); }
.lb-tile[data-state="partial"] { border-top-color:var(--oa-amber); }
.lb-tile[data-state="partial"] .lb-state { color:var(--oa-amber); }
.lb-tile[data-state="partial"] .lb-dot { background:var(--oa-amber); }
.lb-tile[data-state="partial"] .lb-bar i { background:var(--oa-amber); }
.lb-tile[data-state="cast"] .lb-dot { background:var(--oa-gold); }
.lb-tile[data-state="ready"] .lb-dot,
.lb-tile[data-state="ready"] .lb-bar i { background:var(--oa-teal); }

@keyframes lb-pulse { 0%,100%{opacity:1} 50%{opacity:.28} }
.lb-live { animation:lb-pulse 1.9s ease-in-out infinite; }
```

`<main>` needs `container-type: inline-size` for the `@container` queries
above to measure the pane's own width rather than the viewport's — put it on
`main`'s existing rule, not a new wrapper. `.lb-root` (the tile grid's
container) cancels `<main>`'s own 24px padding with `margin:-24px` and
applies the pane's own values with `padding:40px 56px 0`.

---

## 6. Pulse only when a render is actually live

```js
function isRenderLive(slug) {
  return !!(state.activeJob && state.activeJob.book_slug === slug
            && state.activeJob.status === 'running');
}
```

`_any_live_job` (server.py:496) is the server-side twin. A paused or queued
render gets a static amber dot — an animated dot on a stalled job is the board
telling a lie, which is the one failure mode that makes people stop trusting
it. Re-render the tile on the same poll that already drives the job progress
bar; nothing else on the board changes without a refresh.

The board's own fetch is a dedicated function, never the sidebar's:

```js
// Deliberately NOT include_hidden=true — that query is the sidebar's "show
// hidden" toggle alone, never the board's.
async function refreshLibraryBoard() {
  const books = await fetchJSON('/books');
  renderLibraryBoard(books);
  return books;
}
```

`refreshBooks()` (the sidebar's `/books?include_hidden=true` fetch) calls
this too, whenever the board happens to be the visible view — but the board
never renders off `refreshBooks()`'s own hidden-inclusive result directly.

---

## 7. Header

```js
// "Library · 8 books · + Add book"
```

The count comes from the same `boardOrder` length. The `+ Add book` button
reuses the existing `triggerBookPicker()` (index.html:1850) — same file input,
same wizard, second entry point. Keep the sidebar button too; discovery costs
nothing and the board is where a first-run user is looking.

Empty case: render the header ("Library · 0 books · + Add book") and a single
mono line — *Nothing cast yet* — plus the Add button as the only affordance.
`refreshBooks` already distinguishes "no books" from "all hidden"
(index.http:2337); keep both messages, they are different problems.

---

## 8. Click targets differ by state

This is the board's payoff and the easy thing to get wrong — sending every
tile to the same place throws away the triage the board just did.

```js
function openBookFor(book, st) {
  loadBook(book.slug);                  // existing chapter view
}
```

Shipped simpler than drafted: `loadBook` already opens the pre-casting modal
itself whenever a book has no voice map and more than one character — that
is the same `needs-casting` condition, so `openBookFor` does not duplicate
it. `needs-casting` → the skippable casting modal over the chapter view (2A),
so the next move is offered, not demanded. Everything else → the chapter
view (2B) as it already works. `Skip for now` just closes the modal and
leaves the user on the chapter list with narrator fallback — no state
change, no nag.

---

## 9. Sidebar collapse (open by default)

The 390px/280px sidebar can now collapse to a 52px rail — a `#sidebar-toggle`
button, always visible, wraps the rest of the sidebar's markup in
`#sidebar-content`:

```js
const KEY = 'prosecast-sidebar-open';
function isOpen() { return document.documentElement.dataset.sidebar !== 'collapsed'; }
window.toggleSidebar = function () {
  const open = !isOpen();
  if (open) delete document.documentElement.dataset.sidebar;
  else document.documentElement.dataset.sidebar = 'collapsed';
  try { localStorage.setItem(KEY, open ? '1' : '0'); } catch (e) {}
  paint();  // relabels the toggle: ✕ when open, ☰ when collapsed
};
```

**Open is the default** — collapsing is opt-in, the reverse of how the
board's own idle state defaults (closed sidebar was the first draft; it made
the board's default view assume a click before it was useful). No stored
choice means expanded; only an explicit prior "closed" (`'0'`) collapses it.
Applied via an early inline `<script>` in `<head>` (the same pattern as the
On Air / classic theme choice) so there is no flash of the wrong width:

```html
<script>
try { if (localStorage.getItem('prosecast-sidebar-open') === '0')
  document.documentElement.dataset.sidebar = 'collapsed'; } catch (e) {}
</script>
```

```css
body { grid-template-columns: 280px 1fr; }                          /* default: open */
html[data-sidebar="collapsed"] body { grid-template-columns: 52px 1fr; }
#sidebar-content { display: flex; }
html[data-sidebar="collapsed"] #sidebar-content { display: none; }
```

No column count is hardcoded for "sidebar open" vs. "sidebar collapsed" —
the board's own `@container` queries (§5) react to whatever width the pane
actually has. In practice that means roughly 3 columns with the sidebar open
and 4 once it's collapsed, at a typical window width — an emergent result of
the container queries, not a rule tied to the toggle.

---

## 10. Column count follows content too, not just width

A fourth addition, from the same design pass: "track count always matches
the books in a row — an unused track reads as a dead strip, not as
whitespace." A 3-book library at full width must render 3 columns, not 4
with a gap on the right. §5's CSS grows a second variable for this:

```css
.lb-grid {
  --lb-cols: 4;      /* set per render, from JS — see below */
  --lb-max-cols: 4;  /* the width's own cap, from @container */
  grid-template-columns: repeat(min(var(--lb-cols), var(--lb-max-cols)), minmax(0, 1fr));
}
@container (max-width: 1200px) { .lb-grid { --lb-max-cols: 3; } }
@container (max-width: 900px)  { .lb-grid { --lb-max-cols: 2; } }
.lb-row-break { grid-column: 1 / -1; height: 0; }
```

`min()` as a `repeat()` track count is a CSS Values Level 4 feature — modern
Chromium supports it. It's what lets the width cap (pure CSS, reactive to
the sidebar toggling live) and the content cap (set once per render, from
JS) combine without either one needing to know the other exists.

```js
const actionable = ordered.filter(e => LB_ACTIONABLE.includes(e.st.key));
const settled = ordered.filter(e => !LB_ACTIONABLE.includes(e.st.key));
grid.style.setProperty('--lb-cols', Math.max(actionable.length, settled.length, 1));
for (const e of actionable) grid.appendChild(bookTile(e, 'actionable'));
if (actionable.length && settled.length) {
  const rowBreak = document.createElement('div');
  rowBreak.className = 'lb-row-break';
  grid.appendChild(rowBreak);
}
for (const e of settled) grid.appendChild(bookTile(e, 'settled'));
```

The column count is the wider of the two rows, not the total book count —
1 actionable + 7 settled should not stretch the actionable row across 4
columns it doesn't have tiles for. The `.lb-row-break` spacer (full-span,
zero height) is what actually forces settled tiles onto their own row
regardless of whether the actionable count divides evenly into the column
count; without it, a grid whose actionable count isn't a multiple of the
column count lets a settled tile drift onto the end of the actionable row.
No spacer is emitted when either group is empty.

---

## Order of work

1. Server fields (~6 lines). Verify against the real library: Frankenstein and
   Carousel should come back `needs-casting` (no voice map), A Parade `cast`
   (voice map, 0/115 rendered — its 5 unresolved lines don't change this),
   Brigands `partial` at 3/52, the other four `ready` (Sample Book included,
   despite its 9 unresolved lines without spaCy).
2. `bookState` + `boardOrder` + a unit test on the four branches. Point it at
   `tests/fixtures` — `refresh_ui_fixtures.py` exists for exactly this.
3. Tile + CSS, replacing the idle-msg.
4. Header and empty case.
5. Click routing + the 2A modal.
6. Sidebar collapse (§9) — independent of 1–5, can land in either order.
7. Dynamic column count + row-break spacer (§10) — depends on 3 (the tile/
   grid CSS) but not on 6.

Steps 1–2 are the feature. Steps 3–6 are markup and interaction that follow
from them.
