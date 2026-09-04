#!/usr/bin/env python3
"""Headless check of the E2.3 ingest wizard. NOT part of the pytest run.

Drives the real modal with the real fixtures — `tests/fixtures/upload_*.json`
are generated from POST /books/upload by scripts/refresh_ui_fixtures.py, and
tests/test_ingest.py fails if they drift from it. That is the whole point: a
hand-written mock of this endpoint is how the reader view shipped broken.

    pip install playwright && playwright install chromium
    python3 tests/ui/check_ingest_wizard.py [path/to/index.html]
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
PORT = 8780

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


def router(upload_fixture: dict, *, calls: list, fail_ingest: str = "", ticks: int = 2):
    """Answers the app's fetches. `calls` collects (method, path, body)."""
    state = {"polls": 0, "books": []}

    def route(r):
        req = r.request
        path = req.url.split(f":{PORT}", 1)[-1].split("?")[0]
        calls.append((req.method, path, req.post_data))

        def js(obj, status=200):
            r.fulfill(status=status, content_type="application/json", body=json.dumps(obj))

        if path.endswith(INDEX.name):
            return r.continue_()
        if path == "/books":
            return js(state["books"])
        if path == "/books/upload":
            return js(upload_fixture)
        if path == "/books/ingest":
            if fail_ingest:
                return js({"detail": fail_ingest}, 400)
            return js({"job_id": "j1", "slug": "the_rulebook", "mode": "narrator",
                       "title": "The Rulebook"})
        if path.startswith("/render_status/"):
            state["polls"] += 1
            if state["polls"] <= ticks:
                return js({"job_id": "j1", "kind": "ingest", "book_slug": "the_rulebook",
                           "status": "running", "stage": "attributing",
                           "detail": "flattening to a single narrator",
                           "progress": 3, "total": 4})
            state["books"] = [{"slug": "the_rulebook", "title": "The Rulebook",
                               "chapters": 2, "unresolved": 0}]
            return js({"job_id": "j1", "kind": "ingest", "book_slug": "the_rulebook",
                       "status": "done", "stage": "done", "detail": "2 chapters, 9 blocks",
                       "progress": 4, "total": 4,
                       "result": {"slug": "the_rulebook", "chapters": 2, "blocks": 9}})
        if path.startswith("/chapters/"):
            return js({"book_title": "The Rulebook", "chapters": [
                {"index": i, "title": t, "block_count": 4, "dialogue_count": 0,
                 "unresolved_count": 0, "has_audio": False, "wav_file": f"ch{i}.wav"}
                for i, t in enumerate(["Renamed Opening", "Story 3"])]})
        # Incidental to this check — loadBook() calls them after the wizard closes.
        if path.endswith("/characters"):
            return js({"characters": ["NARRATOR"]})
        if path.endswith("/cast_candidates"):
            return js({"characters": [], "voices": []})
        if path.startswith("/voice_map/"):
            return js({"engine": "stub", "map": {"NARRATOR": "v1"}})
        if path == "/voices":
            return js([{"name": "v1", "label": "Voice One"}])
        return js({})
    return route


def open_wizard(page, fixture_name, calls, **kw):
    fixture = json.loads((FIXTURES / fixture_name).read_text())
    page.unroute("**/*")
    page.route("**/*", router(fixture, calls=calls, **kw))
    page.set_input_files("#epub-file-input", [])
    page.wait_for_timeout(80)
    page.set_input_files("#epub-file-input", str(FIXTURE_FILE))
    page.wait_for_selector("#ingest-modal-exists, #ingest-modal-overlay:not(.hidden)", timeout=8000)
    return fixture


FIXTURE_FILE = Path("/tmp/prosecast_wizard_input.txt")


def main() -> int:
    FIXTURE_FILE.write_text("placeholder — the server response is what drives the wizard\n")
    serve(INDEX.parent)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for skin in ("onair", "classic"):
            print(f"\n=== {skin} skin ===")
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            # On Air is the default skin and the choice is read from localStorage by
            # an inline script at parse time, so it must be set before the page loads.
            page.add_init_script(
                f"try {{ localStorage.setItem('prosecast-theme', '{skin}'); }} catch (e) {{}}")
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("console",
                    lambda m: errs.append(f"console.error: {m.text}") if m.type == "error" else None)
            calls: list = []
            page.route("**/*", router({}, calls=calls))
            page.goto(f"http://127.0.0.1:{PORT}/{INDEX.name}")
            page.wait_for_timeout(300)
            themed = page.evaluate("document.documentElement.dataset.theme || 'classic'")
            check(f"the {skin} skin is actually applied", themed == skin, themed)

            print("--- a PDF opens the wizard with a split to review ---")
            calls.clear()
            open_wizard(page, "upload_pdf.json", calls)
            check("title is pre-filled from the file",
                  page.input_value("#ingest-title") == "The Rulebook")
            check("the guessed mode is pre-selected",
                  page.get_attribute(".ingest-mode.selected", "data-mode") == "narrator")
            why = page.text_content(".ingest-mode.selected .ingest-mode-why") or ""
            check("the guess explains itself", "Suggested" in why and "script labels" in why)
            check("all three modes are offered",
                  page.locator(".ingest-mode").count() == 3)
            rows = page.locator(".ingest-ch-row").count()
            note = page.text_content("#ingest-detect-note") or ""
            trust = page.text_content("#ingest-detect-trust") or ""
            check("the detected chapters are listed", rows == 3, f"{rows} rows")
            check("where the split came from is stated", "bookmark" in note, note)
            check("how far to trust it is stated in words", "usually right" in trust, trust)
            check("nothing was ingested just by looking",
                  not any(c[1] == "/books/ingest" for c in calls))
            page.screenshot(path=str(Path(__file__).parent / f"wizard_{skin}_review.png"))

            print("--- the review is honoured, not decoration ---")
            page.locator("#ich-0 input[type=text]").fill("Renamed Opening")
            page.locator("#ich-1 input[type=checkbox]").uncheck()
            page.locator("#ich-2 .ingest-ch-page").fill("6")
            check("unticking dims the row",
                  "skipped" in (page.get_attribute("#ich-1", "class") or ""))
            page.click(".ingest-mode[data-mode=play]")
            check("picking a different mode moves the selection",
                  page.get_attribute(".ingest-mode.selected", "data-mode") == "play")
            page.click(".ingest-mode[data-mode=narrator]")

            page.click("#ingest-go-btn")
            page.wait_for_selector("#ingest-modal-overlay.hidden", state="attached", timeout=8000)
            body = json.loads(next(c[2] for c in calls if c[1] == "/books/ingest"))
            check("the chosen mode is sent", body["mode"] == "narrator", body["mode"])
            check("the edited title is sent", body["title"] == "The Rulebook")
            check("the renamed chapter is sent",
                  body["chapters"][0]["title"] == "Renamed Opening")
            check("the unticked chapter is sent as skip",
                  body["chapters"][1]["skip"] is True and body["chapters"][0]["skip"] is False)
            check("the edited page number is sent", body["chapters"][2]["page"] == 6)
            check("the book list refreshed and the book opened",
                  any(c[1].startswith("/chapters/the_rulebook") for c in calls))
            note_txt = page.text_content("#upload-note") or ""
            check("what happened is stated afterwards",
                  "The Rulebook" in note_txt and "single narrator" in note_txt, note_txt)

            print("--- a script needs no chapter review ---")
            calls.clear()
            open_wizard(page, "upload_play_txt.json", calls)
            check("play is the pre-selected mode",
                  page.get_attribute(".ingest-mode.selected", "data-mode") == "play")
            check("no chapter list for a non-PDF",
                  page.locator("#ingest-chapters").is_hidden())
            page.keyboard.press("Escape")
            check("Escape closes the wizard",
                  page.locator("#ingest-modal-overlay").is_hidden())

            print("--- a scan is refused kindly, before any work ---")
            calls.clear()
            open_wizard(page, "upload_scan_pdf.json", calls)
            scan_txt = page.text_content(".ingest-scan") or ""
            check("it says the PDF is a scan", "scan" in scan_txt.lower(), scan_txt[:60])
            check("it says what to do about it",
                  "ocrmypdf" in scan_txt or "tesseract" in scan_txt)
            check("Add book is disabled", page.is_disabled("#ingest-go-btn"))
            page.keyboard.press("Escape")

            check("no page errors so far", not errs, errs)
            errs.clear()

            print("--- a server refusal lands in the modal, not the console ---")
            calls.clear()
            open_wizard(page, "upload_pdf.json", calls,
                        fail_ingest="That upload has expired — add the file again.")
            page.click("#ingest-go-btn")
            page.wait_for_selector("#ingest-error:not(.hidden)", timeout=8000)
            check("the server's words are shown",
                  "expired" in (page.text_content("#ingest-error") or ""))
            check("the form comes back", page.locator("#ingest-body").is_visible())
            check("you can try again", not page.is_disabled("#ingest-go-btn"))
            page.keyboard.press("Escape")

            # The 400 and the app's own [ingest] log are the point of that section;
            # anything else on the console is not.
            unexpected = [e for e in errs if "expired" not in e and "400" not in e]
            check("the failure path logs nothing unexpected", not unexpected, unexpected)
            page.screenshot(path=str(Path(__file__).parent / f"wizard_{skin}.png"))
            page.close()
        browser.close()

    print("\nFAILURES:", fails if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
