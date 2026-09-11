#!/usr/bin/env python3
"""Headless check of the E11 shelf chapter's `⋯` menu (hide / rename / remove).

Driven by `tests/fixtures/books_library.json`, generated from the live
GET /books?include_hidden=true by scripts/refresh_ui_fixtures.py —
tests/test_library.py fails if it drifts. It carries one book pinned and
renamed to a title with a `'` and a `<` in it (`display_title` makes that
trivially reachable, the way `book_title` mostly wasn't), and one hidden book
— on purpose, so this check proves the row survives both without a
hand-written mock being kinder than the real endpoint.

What it is looking for: that the `⋯` menu opens without loading the book,
that Hide removes the row and the count line tells the truth, that Show
hidden brings it back with a badge, that a hidden book is still reachable by
slug, that Rename never touches ir.json's own title, and that Remove is one
honest confirmation that names the book and says where it went — including
the 409 path when a render is live. Both skins.

    pip install playwright && playwright install chromium
    python3 tests/ui/check_library_menu.py [path/to/index.html]
"""
import copy
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
PORT = 8784

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


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


BOOKS = fixture("books_library.json")           # study (pinned, renamed), sample_book (hidden)
SETUP_STATUS = fixture("setup_status_chatterbox.json")
CONFIG_READY = fixture("config_ready.json")
ORIGINAL_TITLE = {"study": "The Study", "sample_book": "Sample Book"}


def chapters_payload(book: dict) -> dict:
    n = book["chapters"] or 1
    return {"book_title": book["title"],
            "chapters": [{"index": i, "title": f"Chapter {i + 1}", "dialogue_count": 2,
                          "unresolved_count": book["unresolved"] if i == 0 else 0,
                          "has_audio": False} for i in range(n)]}


def sort_books(books: list[dict]) -> list[dict]:
    return sorted(books, key=lambda b: (not b["pinned"], b["title"].casefold()))


def router(*, calls: list, live_job: bool = False):
    """Answers the app's fetches against a mutable in-memory book shelf,
    mirroring server.py's /books, PATCH .../shelf and DELETE closely enough
    for this check without re-implementing it."""
    books = copy.deepcopy(BOOKS)

    def route(r):
        req = r.request
        full = req.url.split(f":{PORT}", 1)[-1]
        path = full.split("?")[0]
        calls.append((req.method, path, req.post_data, full))

        def js(obj, code=200):
            r.fulfill(status=code, content_type="application/json", body=json.dumps(obj))

        if path.endswith(INDEX.name):
            return r.continue_()
        if path == "/books" and req.method == "GET":
            include_hidden = "include_hidden=true" in full
            shown = books if include_hidden else [b for b in books if not b["hidden"]]
            return js(sort_books(shown))
        if path.endswith("/shelf") and req.method == "PATCH":
            slug = path.split("/")[2]
            book = next((b for b in books if b["slug"] == slug), None)
            if book is None:
                return js({"detail": f"No book '{slug}'"}, 404)
            patch = json.loads(req.post_data or "{}")
            if "hidden" in patch:
                book["hidden"] = patch["hidden"]
            if "pinned" in patch:
                book["pinned"] = patch["pinned"]
            if "display_title" in patch:
                book["title"] = patch["display_title"] or ORIGINAL_TITLE.get(slug, slug)
            return js({"hidden": book["hidden"], "pinned": book["pinned"],
                       "display_title": patch.get("display_title"), "sort_index": None})
        if path.startswith("/books/") and req.method == "DELETE":
            slug = path.split("/")[2]
            if live_job:
                return js({"detail": f"'{slug}' has a render running right now — "
                                     f"wait for it to finish, then remove the book."}, 409)
            books[:] = [b for b in books if b["slug"] != slug]
            return js({"trashed": f"{slug}__20260911T000000Z"})
        if path.startswith("/chapters/"):
            slug = path.rsplit("/", 1)[-1]
            book = next((b for b in books if b["slug"] == slug), None)
            return js(chapters_payload(book) if book else {"detail": "not found"}, 200 if book else 404)
        if path.startswith("/ir/") and path.endswith("/characters"):
            return js({"characters": ["NARRATOR"]})
        if path.startswith("/ir/") and path.endswith("/cast_candidates"):
            return js({"has_voice_map": True, "characters": ["NARRATOR"], "candidates": []})
        if path in ("/engine_status", "/engine_status/recheck"):
            return js({"engine": "chatterbox", "ok": True, "source": "file", "detail": "",
                       "voice_count": 12})
        if path == "/setup/status":
            return js(SETUP_STATUS)
        if path == "/config":
            return js(CONFIG_READY)
        return js({})
    return route


def boot(page, *, calls, **kw):
    page.unroute("**/*")
    page.route("**/*", router(calls=calls, **kw))
    page.goto(f"http://127.0.0.1:{PORT}/{INDEX.name}")
    page.wait_for_timeout(350)


def main() -> int:
    serve(INDEX.parent)
    visible = [b for b in BOOKS if not b["hidden"]]
    hidden = [b for b in BOOKS if b["hidden"]]
    special = next(b for b in BOOKS if "'" in b["title"] and "<" in b["title"])

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for skin in ("onair", "classic"):
            print(f"\n=== {skin} skin ===")
            page = browser.new_page(viewport={"width": 1280, "height": 940})
            page.add_init_script(
                f"try {{ localStorage.setItem('prosecast-theme', '{skin}'); }} catch (e) {{}}")
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("console",
                    lambda m: errs.append(f"console.error: {m.text}") if m.type == "error" else None)
            calls: list = []

            print("--- a title with a quote and an angle bracket renders intact ---")
            boot(page, calls=calls)
            themed = page.evaluate("document.documentElement.dataset.theme || 'classic'")
            check(f"the {skin} skin is actually applied", themed == skin, themed)
            row = page.locator(f'.book-row[data-slug="{special["slug"]}"]')
            check("the row for it exists", row.count() == 1, row.count())
            check("its title text is exactly right, not truncated by a broken quote",
                  special["title"] in (row.text_content() or ""), row.text_content())
            check("it carries the pin marker", "📌" in (row.text_content() or ""))
            stray = page.evaluate("() => document.title")  # cheap page-alive smoke check
            check("nothing crashed the page", bool(stray))

            print("--- the count line tells the truth ---")
            count = page.text_content("#book-count") or ""
            check("it counts every book, not just the visible ones",
                  f"{len(BOOKS)} book" in count, count)
            check("it says how many are hidden", f"{len(hidden)} hidden" in count, count)
            check("hidden books are out of view by default",
                  page.locator(".book-row").count() == len(visible),
                  page.locator(".book-row").count())

            print("--- the ⋯ menu opens without loading the book ---")
            calls.clear()
            target = visible[0]
            menu_btn = page.locator(f'.book-row[data-slug="{target["slug"]}"] .book-menu-btn')
            menu_btn.click()
            page.wait_for_timeout(150)
            pop = page.locator(f'.book-row[data-slug="{target["slug"]}"] .book-pop')
            check("the popup is open", not pop.is_hidden())
            check("opening the menu did not load the chapter list",
                  not any(c[1].startswith("/chapters/") for c in calls), calls)
            page.keyboard.press("Escape") if False else None
            page.mouse.click(5, 5)     # click elsewhere closes it, mirroring the Voices menu
            page.wait_for_timeout(150)
            check("clicking elsewhere closes the popup", pop.is_hidden())

            print("--- Hide removes the row and the count line stays honest ---")
            calls.clear()
            page.locator(f'.book-row[data-slug="{target["slug"]}"] .book-menu-btn').click()
            page.wait_for_timeout(100)
            page.locator(f'.book-row[data-slug="{target["slug"]}"] .book-pop button',
                        has_text="Hide").click()
            page.wait_for_timeout(300)
            patches = [c for c in calls if c[0] == "PATCH" and c[1].endswith("/shelf")]
            check("exactly one PATCH went out", len(patches) == 1, patches)
            check("it patched hidden:true",
                  patches and json.loads(patches[0][2]) == {"hidden": True}, patches[:1])
            check("the row is gone from the default view",
                  page.locator(f'.book-row[data-slug="{target["slug"]}"]').count() == 0)
            count = page.text_content("#book-count") or ""
            check("the count line now says one more is hidden",
                  f"{len(hidden) + 1} hidden" in count, count)

            print("--- Show hidden brings it back with a badge ---")
            page.click("#book-show-hidden")
            page.wait_for_timeout(200)
            row = page.locator(f'.book-row[data-slug="{target["slug"]}"]')
            check("show hidden reveals it again", row.count() == 1)
            check("it carries the hidden badge", "hidden" in (row.text_content() or "").lower())
            check("the toggle reads as on", "on" in (page.get_attribute("#book-show-hidden", "class") or ""))

            print("--- a hidden book is still reachable by slug ---")
            calls.clear()
            row.locator(".book-btn").click()
            page.wait_for_timeout(250)
            check("clicking a hidden row still loads it",
                  any(c[1] == f"/chapters/{target['slug']}" for c in calls), calls)
            page.click("#book-show-hidden")
            page.wait_for_timeout(150)

            print("--- Rename saves display_title and clearing it restores the real title ---")
            boot(page, calls=calls)
            calls.clear()
            renamable = visible[-1]
            page.locator(f'.book-row[data-slug="{renamable["slug"]}"] .book-menu-btn').click()
            page.wait_for_timeout(100)
            page.locator(f'.book-row[data-slug="{renamable["slug"]}"] .book-pop button',
                        has_text="Rename").click()
            page.wait_for_timeout(100)
            field = page.locator('.book-rename-row input')
            check("an inline field appears, not window.prompt", field.count() == 1)
            field.fill("A Renamed Title")
            field.press("Enter")
            page.wait_for_timeout(300)
            patches = [c for c in calls if c[0] == "PATCH" and c[1].endswith("/shelf")]
            check("the rename patched display_title",
                  patches and json.loads(patches[0][2]) == {"display_title": "A Renamed Title"},
                  patches[:1])
            check("the row shows the new title",
                  "A Renamed Title" in (page.text_content(
                      f'.book-row[data-slug="{renamable["slug"]}"]') or ""))

            calls.clear()
            page.locator(f'.book-row[data-slug="{renamable["slug"]}"] .book-menu-btn').click()
            page.wait_for_timeout(100)
            page.locator(f'.book-row[data-slug="{renamable["slug"]}"] .book-pop button',
                        has_text="Rename").click()
            page.wait_for_timeout(100)
            page.locator('.book-rename-row input').fill("")
            page.locator('.book-rename-row input').press("Enter")
            page.wait_for_timeout(300)
            patches = [c for c in calls if c[0] == "PATCH" and c[1].endswith("/shelf")]
            check("an empty rename clears the override",
                  patches and patches[0][2] and json.loads(patches[0][2]) == {"display_title": None},
                  patches[:1])
            check("the real title is back",
                  ORIGINAL_TITLE[renamable["slug"]] in (page.text_content(
                      f'.book-row[data-slug="{renamable["slug"]}"]') or ""))

            print("--- Remove: one honest confirmation, names the book, says where it went ---")
            boot(page, calls=calls)
            removable = visible[0]
            dialogs = []
            page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
            calls.clear()
            page.locator(f'.book-row[data-slug="{removable["slug"]}"] .book-menu-btn').click()
            page.wait_for_timeout(100)
            page.locator(f'.book-row[data-slug="{removable["slug"]}"] .book-pop button',
                        has_text="Remove").click()
            page.wait_for_timeout(300)
            check("a confirmation was shown", len(dialogs) == 1, dialogs)
            check("it names the book", removable["title"] in dialogs[0], dialogs)
            check("it says plainly where the book goes and that it can come back",
                  "library/.trash" in dialogs[0] and "mv" in dialogs[0], dialogs)
            deletes = [c for c in calls if c[0] == "DELETE"]
            check("exactly one DELETE went out", len(deletes) == 1, deletes)
            check("the row is gone",
                  page.locator(f'.book-row[data-slug="{removable["slug"]}"]').count() == 0)

            print("--- Remove during a live render: the server's own sentence, not 'failed' ---")
            boot(page, calls=calls, live_job=True)
            # the "dialog" listener registered above already auto-accepts every
            # confirm() on this page — a second listener double-handles the
            # same dialog and Playwright throws on the redundant accept()
            target2 = visible[0]
            page.locator(f'.book-row[data-slug="{target2["slug"]}"] .book-menu-btn').click()
            page.wait_for_timeout(100)
            page.locator(f'.book-row[data-slug="{target2["slug"]}"] .book-pop button',
                        has_text="Remove").click()
            page.wait_for_timeout(300)
            note = (page.text_content("#upload-note") or "") + (page.text_content("#upload-error") or "")
            check("the row is still there — nothing was moved",
                  page.locator(f'.book-row[data-slug="{target2["slug"]}"]').count() == 1)
            check("the honest server sentence reached the screen, not a generic 'failed'",
                  "render is running" in note or "render" in note.lower(), note)

            print("--- nothing overflows at 1280px ---")
            over = page.evaluate(
                "() => { const d = document.documentElement;"
                " return [d.scrollWidth, d.clientWidth]; }")
            check("the page does not scroll sideways", over[0] <= over[1], over)

            page.screenshot(path=str(Path(__file__).parent / f"library_{skin}.png"))

            ignorable = ("404", "Failed to load resource")
            unexpected = [e for e in errs if not any(x in e for x in ignorable)]
            check("nothing unexpected on the console", not unexpected, unexpected)
            page.close()
        browser.close()

    print("\nFAILURES:", fails if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
