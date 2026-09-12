#!/usr/bin/env python3
"""Headless check of the library board's one derived function.

Design handoff: docs/design/library_board (2026-09-12, corrected same day —
see IMPLEMENT_library_board.md's changelog). `bookState()` is the whole
feature — layout just reads its output — so this exercises the four branches
directly, plus the ordering and click-routing rules built on top of it,
against `tests/fixtures/books_library.json` (generated from the live
GET /books?include_hidden=true — tests/test_library.py fails if it drifts).

Unresolved lines are deliberately NOT part of `bookState()` (the 2026-09-12
correction): unresolved means "review the attribution", not "pick voices",
and the first draft's `|| b.unresolved > 0` clause sent Sample Book — cast,
fully rendered, ships with the app — to the board in red. This check proves
that regression stays fixed.

    pip install playwright && playwright install chromium
    python3 tests/ui/check_library_board.py [path/to/index.html]
"""
import functools
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
INDEX = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "static" / "index.html"
FIXTURES = ROOT / "tests" / "fixtures"
PORT = 8785

fails: list[str] = []


def check(name: str, ok: bool, detail="") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(' — ' + str(detail)) if detail else ''}")
    if not ok:
        fails.append(name)


def serve(directory: Path) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))

    class Quiet(socketserver.TCPServer):
        allow_reuse_address = True

    httpd = Quiet(("127.0.0.1", PORT), handler)
    httpd.RequestHandlerClass.log_message = lambda *a, **k: None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


# One real book per branch, shaped like /books' real fields.
BOOKS = [
    {"slug": "no_map", "title": "No Map Yet", "chapters": 10, "unresolved": 0,
     "hidden": False, "pinned": False, "rendered": 0, "cast": False},
    {"slug": "just_cast", "title": "Just Cast", "chapters": 8, "unresolved": 0,
     "hidden": False, "pinned": False, "rendered": 0, "cast": True},
    {"slug": "mid_render", "title": "Mid Render", "chapters": 52, "unresolved": 0,
     "hidden": False, "pinned": False, "rendered": 3, "cast": True},
    {"slug": "all_done", "title": "All Done", "chapters": 4, "unresolved": 0,
     "hidden": False, "pinned": False, "rendered": 4, "cast": True},
    # Sample Book's real shape: cast, fully rendered, but unresolved lines
    # linger (no spaCy in this venv). Must read "ready", not "needs-casting".
    {"slug": "unresolved_but_ready", "title": "Unresolved But Ready", "chapters": 2,
     "unresolved": 9, "hidden": False, "pinned": False, "rendered": 2, "cast": True},
    {"slug": "hidden_one", "title": "Hidden One", "chapters": 1, "unresolved": 0,
     "hidden": True, "pinned": False, "rendered": 1, "cast": True},
]


def main() -> int:
    serve(INDEX.parent)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console",
                lambda m: errs.append(f"console.error: {m.text}") if m.type == "error" else None)
        # Every API call answers {} — these checks call bookState/boardOrder/
        # renderLibraryBoard directly, so the page only needs to load.
        page.route("**/*", lambda r: r.continue_() if r.request.url.endswith(INDEX.name)
                   else r.fulfill(status=200, content_type="application/json", body="{}"))
        page.goto(f"http://127.0.0.1:{PORT}/{INDEX.name}")
        page.wait_for_timeout(400)

        print("\n--- bookState()'s four branches ---")
        states = page.evaluate("(books) => books.map(bookState)", BOOKS)
        got = [s["key"] for s in states]
        want = ["needs-casting", "cast", "partial", "ready", "ready", "ready"]
        check("no cast at all -> needs-casting", got[0] == want[0], got[0])
        check("cast, nothing rendered yet -> cast", got[1] == want[1], got[1])
        check("some chapters rendered -> partial", got[2] == want[2], got[2])
        check("every chapter rendered -> ready", got[3] == want[3], got[3])
        check("cast + fully rendered + unresolved lines -> still ready "
              "(unresolved is not part of this rule — Sample Book's real shape)",
              got[4] == want[4], got[4])
        check("a hidden book still gets a real state (filtering is boardOrder's job)",
              got[5] == want[5], got[5])
        check("only the partial phrase carries a number",
              states[2]["phrase"] == "3 of 52 rendered" and states[1]["phrase"] == "Cast, not yet rendered",
              [s["phrase"] for s in states])
        check("progress is a 0..1 fraction, not a percentage",
              abs(states[2]["progress"] - 3 / 52) < 1e-9 and states[3]["progress"] == 1,
              [s["progress"] for s in states])

        print("\n--- boardOrder() partitions and ranks, hides hidden books ---")
        order = page.evaluate("(books) => boardOrder(books).map(e => [e.book.slug, e.st.key])", BOOKS)
        check("the hidden book never appears",
              "hidden_one" not in [s for s, _ in order], order)
        check("needs-casting first, then partial, then cast, then ready(s)",
              [k for _, k in order] == ["needs-casting", "partial", "cast", "ready", "ready"],
              order)

        print("\n--- the board renders one tile per visible book, sized by state ---")
        page.evaluate("(books) => renderLibraryBoard(books)", BOOKS)
        tiles = page.evaluate("""() => [...document.querySelectorAll('.lb-tile')].map(t => ({
            slug: t.dataset.state, variant: t.className.includes('lb-actionable') ? 'actionable' : 'settled',
        }))""")
        check("five tiles (the hidden book stays off the board)", len(tiles) == 5, tiles)
        check("needs-casting/cast/partial render actionable (large); ready renders settled",
              [t["variant"] for t in tiles] ==
              ["actionable", "actionable", "actionable", "settled", "settled"],
              tiles)

        print("\n--- column count follows the wider row, not a fixed 4 ---")
        grid_state = page.evaluate("""() => {
            const grid = document.querySelector('.lb-grid');
            return {
                lbCols: grid.style.getPropertyValue('--lb-cols'),
                children: [...grid.children].map(c => c.className),
            };
        }""")
        check("--lb-cols is 3 (max of 3 actionable, 2 settled) — a 4th empty "
              "track would be a dead strip, not whitespace",
              grid_state["lbCols"] == "3", grid_state)
        check("a full-row spacer separates the groups, so settled tiles never "
              "share a row with actionable ones",
              grid_state["children"] == [
                  "lb-tile lb-actionable", "lb-tile lb-actionable", "lb-tile lb-actionable",
                  "lb-row-break", "lb-tile lb-settled", "lb-tile lb-settled",
              ], grid_state)

        print("\n--- no spacer when one of the two rows is empty ---")
        only_actionable = [b for b in BOOKS if b["slug"] in ("no_map", "just_cast")]
        page.evaluate("(books) => renderLibraryBoard(books)", only_actionable)
        no_spacer = page.evaluate(
            "() => [...document.querySelectorAll('.lb-grid > *')].some(c => c.className === 'lb-row-break')")
        check("a single-group board never emits an empty spacer", not no_spacer)
        page.evaluate("(books) => renderLibraryBoard(books)", BOOKS)  # restore for later checks

        print("\n--- the board's own fetch never asks for hidden books ---")
        board_urls = page.evaluate("""async () => {
            const seen = [];
            const orig = window.fetch;
            window.fetch = (url, opts) => {
                seen.push(String(url));
                return Promise.resolve(new Response(JSON.stringify([]),
                    {status: 200, headers: {'Content-Type': 'application/json'}}));
            };
            await refreshLibraryBoard();
            window.fetch = orig;
            return seen;
        }""")
        check("refreshLibraryBoard() never passes include_hidden=true",
              board_urls and all("include_hidden" not in u for u in board_urls), board_urls)

        print("\n--- click routing: needs-casting alone raises the casting prompt ---")
        calls = page.evaluate("""() => {
            window.__loaded = [];
            window.loadBook = (slug) => window.__loaded.push(slug);
            const board = boardOrder(""" + json.dumps(BOOKS) + """);
            const needsCasting = board.find(e => e.st.key === 'needs-casting');
            const ready = board.find(e => e.st.key === 'ready');
            openBookFor(needsCasting.book, needsCasting.st);
            openBookFor(ready.book, ready.st);
            return window.__loaded;
        }""")
        check("openBookFor always opens the chapter view", len(calls) == 2, calls)

        print("\n--- against the real fixture (books_library.json) ---")
        real_books = json.loads((FIXTURES / "books_library.json").read_text(encoding="utf-8"))
        real_states = page.evaluate("(books) => books.map(bookState).map(s => s.key)", real_books)
        check("every fixture book resolves to one of the four known states",
              all(s in ("needs-casting", "cast", "partial", "ready") for s in real_states),
              real_states)

        check("no page errors", not errs, errs)
        browser.close()

    print("\nFAILURES:", fails if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
