#!/usr/bin/env python3
"""Headless check of the E6 first-run wizard. NOT part of the pytest run.

Driven by `tests/fixtures/setup_status_*.json`, `config_*.json` and
`sample_book.json`, which are generated from the live endpoints by
scripts/refresh_ui_fixtures.py — tests/test_sample_book.py fails if they drift.
A hand-written mock of /setup/status would be free to be kinder than the probe,
and the whole point of this screen is that it repeats the probe's own words.

What it is looking for: that the wizard opens for a stranger and not for anyone
else, that it never traps them, that step 2 refuses to move on for a reason it
can name, and that the last step really does ask the server for the sample book
and then for a render of it.

    pip install playwright && playwright install chromium
    python3 tests/ui/check_first_run.py [path/to/index.html]
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
PORT = 8782

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


def silent_wav(seconds: float = 0.4) -> bytes:
    """A real, playable wav for the mocked /audio route.

    `playChapter` opens the reader view on the line AFTER `await
    audioEl.play()`, so a 404 there does not merely log — it stops the page
    short of `body.reader-open`, which is the thing this file now checks.
    """
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * int(22050 * seconds))
    return buf.getvalue()


SILENT_WAV = silent_wav()

# Did #casting-modal-overlay ever lose its `hidden` class? Checking once at the
# end would miss a modal that opened and was closed again; this watches.
CASTING_WATCHER = """
window.__castingEverShown = false;
document.addEventListener('DOMContentLoaded', function () {
  var el = document.getElementById('casting-modal-overlay');
  if (!el) return;
  function look() { if (!el.classList.contains('hidden')) window.__castingEverShown = true; }
  look();
  new MutationObserver(look).observe(el, {attributes: true, attributeFilter: ['class']});
});
"""


# The library row GET /books returns for a sample book that already exists —
# what init() sees, and why it opens that book by itself.
SAMPLE_BOOK_ROW = {"slug": "sample_book", "title": "Sample Book",
                   "chapters": 2, "unresolved": 0}

SAMPLE_CHAPTERS = {"book_title": "Sample Book", "chapters": [
    {"index": i, "title": t, "block_count": 12, "dialogue_count": 8,
     "unresolved_count": 0, "has_audio": i == 0, "wav_file": f"ch{i}.wav"}
    for i, t in enumerate(["Chapter 1: The Meeting", "Chapter 2: The Conversation"])]}


def router(*, calls: list, status: dict, config: dict, ticks: int = 2,
           sample_fixture: dict | None = None, fail_at: str = "",
           books_at_boot: list | None = None, cast_candidates: dict | None = None):
    """Answers the app's fetches. `calls` collects (method, path, body).

    `status` and `config` are mutable dicts the caller can swap between
    interactions, exactly as a save-then-reprobe would change them.

    `books_at_boot` seeds GET /books before anything happens — a library that
    already holds a book, which is what `init()` needs to open one by itself.
    `cast_candidates` is the generated shape from the live endpoint.
    """
    state = {"ingest_polls": 0, "render_polls": 0,
             "books": list(books_at_boot or [])}
    sample = sample_fixture or fixture("sample_book.json")

    def route(r):
        req = r.request
        full = req.url.split(f":{PORT}", 1)[-1]
        path = full.split("?")[0]
        calls.append((req.method, path, req.post_data, full))

        def js(obj, code=200):
            r.fulfill(status=code, content_type="application/json", body=json.dumps(obj))

        if path.endswith(INDEX.name):
            return r.continue_()
        if path == "/setup/status":
            return js(status)
        if path == "/config":
            return js(config)
        if path == "/books":
            return js(state["books"])
        if path == "/books/sample":
            if fail_at == "sample":
                return js({"detail": "Could not write the sample book to books/: disk full"}, 500)
            return js(sample)
        if path.startswith("/render/"):
            if fail_at == "render":
                return js({"detail": "No IR found for 'sample_book'"}, 404)
            return js({"job_id": "r1"})
        if path.startswith("/render_status/"):
            job = path.rsplit("/", 1)[-1]
            if job == "FIXTURE":                       # the ingest job
                state["ingest_polls"] += 1
                if state["ingest_polls"] <= ticks:
                    return js({"job_id": job, "kind": "ingest", "book_slug": "sample_book",
                               "status": "running", "stage": "attributing",
                               "detail": "finding who speaks each line",
                               "progress": 3, "total": 4})
                return js({"job_id": job, "kind": "ingest", "book_slug": "sample_book",
                           "status": "done", "stage": "done", "detail": "2 chapters, 31 blocks",
                           "progress": 4, "total": 4,
                           "result": {"slug": "sample_book", "chapters": 2, "blocks": 31}})
            state["render_polls"] += 1
            if state["render_polls"] <= ticks:
                return js({"job_id": job, "kind": "render", "book_slug": "sample_book",
                           "status": "running", "progress": 0, "total": 1,
                           "current_chapter": 0, "block_progress": 12, "block_total": 31,
                           "queue_position": 0, "error": None, "chapter_results": []})
            state["books"] = [{"slug": "sample_book", "title": "Sample Book",
                               "chapters": 2, "unresolved": 0}]
            return js({"job_id": job, "kind": "render", "book_slug": "sample_book",
                       "status": "done", "progress": 1, "total": 1, "queue_position": 0,
                       "error": None, "chapter_results": [{"chapter": 0, "blocks": 31}]})
        if path.startswith("/chapters/"):
            return js(SAMPLE_CHAPTERS)
        if path == "/engine_status":
            return js({"engine": "say", "ok": True, "source": "file", "detail": ""})
        if path.startswith("/pipeline/"):
            return js(fixture("pipeline_offline.json"))
        # Incidental: loadBook() and playChapter() after the wizard closes.
        if path.endswith("/characters"):
            return js({"characters": ["NARRATOR", "Elizabeth", "Darcy"]})
        if path.endswith("/cast_candidates"):
            return js(cast_candidates or {"characters": [], "voices": []})
        if path.startswith("/voice_map/"):
            return js({"engine": "say", "map": {"NARRATOR": "v1"}})
        if path == "/voices":
            return js([{"name": "v1", "label": "Voice One"}])
        if path.startswith("/timeline/"):
            return js(fixture("timeline_study_ch0.json"))
        if path.startswith("/audio/"):
            # A real, silent wav: playChapter opens the reader view only after
            # `await audioEl.play()` resolves, so a 404 here would hide whether
            # the wizard actually lands anyone on the book.
            return r.fulfill(status=200, content_type="audio/wav", body=SILENT_WAV)
        return js({})
    return route


def boot(page, *, calls, status, config, **kw):
    """Load the page fresh with a given server state."""
    page.unroute("**/*")
    page.route("**/*", router(calls=calls, status=status, config=config, **kw))
    page.goto(f"http://127.0.0.1:{PORT}/{INDEX.name}")
    page.wait_for_timeout(350)


def steps_hidden_except(page, n: int) -> list[int]:
    """Which step sections are actually rendering when they should not be."""
    return [i for i in range(1, 5)
            if i != n and page.locator(f"#fr-step-{i}").is_visible()]


def main() -> int:
    serve(INDEX.parent)
    firstrun = fixture("setup_status_firstrun.json")
    ready = fixture("setup_status_ready.json")
    setup_sh = fixture("setup_status_setup_sh.json")
    chatterbox = fixture("setup_status_chatterbox.json")
    cfg_first = fixture("config_firstrun.json")
    cfg_ready = fixture("config_ready.json")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for skin in ("onair", "classic"):
            print(f"\n=== {skin} skin ===")
            page = browser.new_page(viewport={"width": 1280, "height": 940})
            # On Air is the default and the choice is read from localStorage by an
            # inline script at parse time, so it must be set before the page loads.
            page.add_init_script(
                f"try {{ localStorage.setItem('prosecast-theme', '{skin}'); }} catch (e) {{}}")
            page.add_init_script(CASTING_WATCHER)
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("console",
                    lambda m: errs.append(f"console.error: {m.text}") if m.type == "error" else None)
            calls: list = []

            print("--- it opens itself for someone who has never set up ---")
            boot(page, calls=calls, status=firstrun, config=cfg_first)
            themed = page.evaluate("document.documentElement.dataset.theme || 'classic'")
            check(f"the {skin} skin is actually applied", themed == skin, themed)
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            check("the wizard opened on its own", not page.locator("#firstrun-modal-overlay").is_hidden())
            check("the Setup table did NOT open instead",
                  not page.evaluate("document.body.classList.contains('setup-open')"))
            check("it starts at step 1", page.locator("#fr-step-1").is_visible())
            stray = steps_hidden_except(page, 1)
            check("every other step is really hidden", not stray, stray)

            print("--- step 1 pre-selects the OS default ---")
            picked = page.get_attribute(".su-engine.selected", "data-engine")
            check("macOS pre-selects say", picked == "say", picked)
            check("all three engines are offered", page.locator(".su-engine").count() == 3)
            check("no ElevenLabs disclosure until it is picked",
                  (page.text_content("#fr-el-disclosure") or "").strip() == "")
            check("no engine field until one is needed",
                  page.locator("#fr-engine-fields").is_hidden())

            page.click(".su-engine[data-engine=chatterbox]")
            check("Chatterbox reveals its URL field",
                  page.locator("#suf-chatterbox_url").is_visible())
            page.click(".su-engine[data-engine=elevenlabs]")
            el_txt = page.text_content("#fr-el-disclosure") or ""
            check("the ElevenLabs disclosure appears when picked",
                  "independent affiliate of ElevenLabs" in el_txt)
            check("the trademark attribution comes with it",
                  "registered trademarks or trademarks of ElevenLabs" in el_txt)
            check("the affiliate link is there",
                  "try.elevenlabs.io" in (page.inner_html("#fr-el-disclosure") or ""))
            check("ElevenLabs reveals its key field",
                  page.locator("#suf-elevenlabs_api_key").is_visible())
            page.click(".su-engine[data-engine=say]")
            check("switching away drops the disclosure again",
                  (page.text_content("#fr-el-disclosure") or "").strip() == "")

            print("--- the wizard never traps anyone ---")
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
            check("Escape closes the wizard", page.locator("#firstrun-modal-overlay").is_hidden())
            check("Escape lands on the Setup page",
                  page.evaluate("document.body.classList.contains('setup-open')"))

            print("--- ↻ Run setup again re-opens it at step 1, pre-filled ---")
            page.unroute("**/*")
            page.route("**/*", router(calls=calls, status=ready, config=cfg_ready))
            page.click("#su-rerun-wizard")
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            check("it is back at step 1", page.locator("#fr-step-1").is_visible())
            picked = page.get_attribute(".su-engine.selected", "data-engine")
            check("the saved engine is pre-filled", picked == "say", picked)
            page.click("#fr-skip")
            page.wait_for_timeout(150)
            check("Skip closes it too", page.locator("#firstrun-modal-overlay").is_hidden())
            check("Skip lands on the Setup page",
                  page.evaluate("document.body.classList.contains('setup-open')"))

            print("--- it opens after SETUP.sh too, config.json and all ---")
            # The case E6.8 exists for: SETUP.sh copies config.example.json, so
            # config_exists is true before anyone has chosen anything. Firing on
            # !config_exists meant the wizard never greeted the documented
            # install path at all.
            calls.clear()
            boot(page, calls=calls, status=setup_sh, config=cfg_ready)
            check("a config.json with nothing chosen still counts as a first run",
                  setup_sh["config_exists"] is True)
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            check("the wizard opened anyway",
                  not page.locator("#firstrun-modal-overlay").is_hidden())
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)

            print("--- it does NOT open once an engine has been chosen ---")
            calls.clear()
            boot(page, calls=calls, status=ready, config=cfg_ready)
            check("no wizard when `say` is chosen",
                  page.locator("#firstrun-modal-overlay").is_hidden())

            calls.clear()
            boot(page, calls=calls, status=chatterbox, config=cfg_ready)
            engine_row = next(r for r in chatterbox["rows"] if r["key"] == "voice_engine")
            check("the chatterbox fixture really is a deliberate choice",
                  engine_row["engine"] == "chatterbox" and engine_row["source"] == "file")
            check("no wizard for someone who picked Chatterbox and moved on",
                  page.locator("#firstrun-modal-overlay").is_hidden())
            check("and it did not open the Setup table at them either",
                  not page.evaluate("document.body.classList.contains('setup-open')"))

            print("--- step 1 pre-selects piper when this is not a Mac ---")
            linux = json.loads(json.dumps(firstrun))
            linux["os"] = "Linux"
            calls.clear()
            boot(page, calls=calls, status=linux, config=cfg_first)
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            picked = page.get_attribute(".su-engine.selected", "data-engine")
            check("Linux pre-selects piper", picked == "piper", picked)
            check("the card is labelled Piper, not System voices",
                  "Piper" in (page.text_content(".su-engine.selected") or ""))

            print("--- step 2 will not move on, and says why in the probe's words ---")
            calls.clear()
            boot(page, calls=calls, status=firstrun, config=cfg_first)
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            page.click("#fr-next")
            page.wait_for_selector("#fr-step-2:not(.fr-hidden)", timeout=8000)
            saved = json.loads(next(c[2] for c in calls if c[1] == "/config" and c[0] == "PUT"))
            check("the engine was saved before probing",
                  saved["values"]["tts_engine"] == "say", saved)
            check("only the keys this step owns were sent",
                  set(saved["values"]) <= {"tts_engine", "chatterbox_url", "elevenlabs_api_key"},
                  list(saved["values"]))
            stray = steps_hidden_except(page, 2)
            check("only step 2 is showing", not stray, stray)
            rows = page.locator("#fr-probe-rows .su-row").count()
            check("exactly the two rows this step is about", rows == 2, f"{rows} rows")
            shown = page.text_content("#fr-probe-rows") or ""
            engine_row = next(r for r in firstrun["rows"] if r["key"] == "voice_engine")
            check("the probe's own detail is shown", engine_row["detail"] in shown)
            check("the probe's own fix is shown", engine_row["fix"][:40] in shown)
            check("ffmpeg is the other row", "ffmpeg" in shown)
            check("Continue is disabled while the engine is not ok",
                  page.is_disabled("#fr-next"))
            check("the disabled reason is the row's own fix",
                  (page.text_content("#fr-why") or "").strip() == engine_row["fix"])
            check("there is a way to the full list",
                  page.locator("#fr-full-list").is_visible())

            print("--- Check again, now that the engine answers ---")
            page.unroute("**/*")
            page.route("**/*", router(calls=calls, status=ready, config=cfg_ready))
            page.click("#fr-recheck")
            page.wait_for_timeout(400)
            check("Continue is enabled once voice_engine.ok", not page.is_disabled("#fr-next"))
            check("the disabled reason is gone", page.locator("#fr-why").is_hidden())
            page.screenshot(path=str(Path(__file__).parent / f"firstrun_{skin}_probe.png"))

            print("--- step 3 is skippable ---")
            page.click("#fr-next")
            page.wait_for_selector("#fr-step-3:not(.fr-hidden)", timeout=8000)
            stray = steps_hidden_except(page, 3)
            check("only step 3 is showing", not stray, stray)
            check("all three optional services are offered",
                  page.locator("#fr-brains .fr-group").count() == 3)
            for field in ("suf-ollama_url", "suf-ollama_model", "suf-whisper_url",
                          "suf-elevenlabs_api_key"):
                check(f"{field} is there", page.locator(f"#{field}").count() == 1)
            check("nothing here blocks progress", not page.is_disabled("#fr-next"))
            page.click("#fr-next")
            page.wait_for_selector("#fr-step-4:not(.fr-hidden)", timeout=8000)
            stray = steps_hidden_except(page, 4)
            check("only step 4 is showing", not stray, stray)

            print("--- step 4 asks for the sample book, then a render of it ---")
            calls.clear()
            check("no cost warning on a free engine",
                  page.locator("#fr-cost").is_hidden())
            page.click("#fr-hear-btn")
            page.wait_for_selector("#firstrun-modal-overlay.hidden", state="attached", timeout=15000)
            ordered = [f"{m} {p}" for m, p, _, _ in calls
                       if p in ("/books/sample",) or p.startswith("/render/")]
            check("it asked for the sample book first",
                  ordered[:1] == ["POST /books/sample"], ordered)
            check("then for a render of its first chapter",
                  ordered[1:2] == ["POST /render/sample_book/0"], ordered)
            check("it polled the ingest job", any(c[1] == "/render_status/FIXTURE" for c in calls))
            check("the book list was refreshed", any(c[1] == "/books" for c in calls))
            check("the book was opened",
                  any(c[1].startswith("/chapters/sample_book") for c in calls))
            check("the wizard closed itself", page.locator("#firstrun-modal-overlay").is_hidden())
            render_url = next(c[3] for c in calls if c[1].startswith("/render/"))
            check("a fresh sample is not force-rendered", "force" not in render_url, render_url)
            page.screenshot(path=str(Path(__file__).parent / f"firstrun_{skin}.png"))

            print("--- a sample cast for another engine is rendered past ---")
            calls.clear()
            boot(page, calls=calls, status=firstrun, config=cfg_first,
                 sample_fixture={"slug": "sample_book", "exists": True,
                                 "chapters": 2, "recast": True})
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            page.evaluate("fr.step = 3; frGo(4);")
            page.click("#fr-hear-btn")
            page.wait_for_selector("#firstrun-modal-overlay.hidden", state="attached", timeout=15000)
            render_url = next(c[3] for c in calls if c[1].startswith("/render/"))
            check("recast means force=true", "force=true" in render_url, render_url)
            check("an existing sample needs no ingest poll",
                  not any(c[1] == "/render_status/FIXTURE" for c in calls))

            print("--- a library that already has an uncast book: no modal, "
                  "and it ends on the book ---")
            # The Windows machine on 2026-09-06. SETUP.sh's smoke test
            # (`main.py --sample --tts stub`) had already made sample_book from
            # a terminal, so init() found exactly one book and opened it, and
            # loadBook's "no voice map → cast this" modal landed ON TOP of the
            # wizard. After "Cast the book" he was on the Setup page — a wall of
            # amber optional rows under a green READY badge — with no play
            # button anywhere. "I don't know what to do from here, nor would an
            # average person."
            calls.clear()
            uncast = fixture("cast_candidates_uncast.json")
            check("the fixture really is the modal's trigger",
                  uncast["has_voice_map"] is False and len(uncast["characters"]) > 1,
                  f"has_voice_map={uncast['has_voice_map']}, "
                  f"{len(uncast['characters'])} characters")
            boot(page, calls=calls, status=firstrun, config=cfg_first,
                 books_at_boot=[SAMPLE_BOOK_ROW], cast_candidates=uncast,
                 sample_fixture={"slug": "sample_book", "exists": True,
                                 "chapters": 2, "recast": True})
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            check("the book really was opened underneath",
                  any(c[1].startswith("/chapters/sample_book") for c in calls))
            check("the casting modal did NOT open over the wizard",
                  not page.evaluate("window.__castingEverShown"))
            check("the wizard is the thing on screen",
                  not page.locator("#firstrun-modal-overlay").is_hidden())

            page.evaluate("fr.step = 3; frGo(4);")
            page.click("#fr-hear-btn")
            page.wait_for_selector("#firstrun-modal-overlay.hidden", state="attached",
                                   timeout=15000)
            page.wait_for_timeout(400)
            check("the casting modal never appeared at all",
                  not page.evaluate("window.__castingEverShown"))
            check("it ends on the book, reading",
                  page.evaluate("document.body.classList.contains('reader-open')"))
            check("it does NOT end on the Setup page",
                  not page.evaluate("document.body.classList.contains('setup-open')"))

            print("--- Esc: Setup when nothing was made, the book when something was ---")
            # Esc still means "enough of this wizard" and still goes to Setup
            # (E6's design) — unless this run already made a book, in which case
            # the book is the better place to be left than a table of rows.
            calls.clear()
            boot(page, calls=calls, status=firstrun, config=cfg_first)
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            check("Esc with nothing made still lands on Setup",
                  page.evaluate("document.body.classList.contains('setup-open')"))

            # The book exists (POST /books/sample succeeded and cast it) but the
            # render failed, so the wizard is still up with its error. Esc here
            # must not throw away the book it just made.
            calls.clear()
            boot(page, calls=calls, status=firstrun, config=cfg_first, fail_at="render",
                 books_at_boot=[SAMPLE_BOOK_ROW], cast_candidates=fixture("cast_candidates_cast.json"),
                 sample_fixture={"slug": "sample_book", "exists": True,
                                 "chapters": 2, "recast": True})
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            page.evaluate("fr.step = 3; frGo(4);")
            page.click("#fr-hear-btn")
            page.wait_for_selector("#fr-recover:not(.fr-hidden)", timeout=8000)
            check("the wizard stayed open on the failure", 
                  not page.locator("#firstrun-modal-overlay").is_hidden())
            check("it knows which book it made",
                  page.evaluate("fr.bookSlug") == "sample_book", page.evaluate("fr.bookSlug"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            check("Esc lands on that book, not Setup",
                  not page.evaluate("document.body.classList.contains('setup-open')"))
            check("the book's chapters are what is on screen",
                  page.locator(".chapter-row").count() > 0,
                  page.locator(".chapter-row").count())

            print("--- the Skip link still goes to Setup, always ---")
            calls.clear()
            boot(page, calls=calls, status=firstrun, config=cfg_first,
                 books_at_boot=[SAMPLE_BOOK_ROW], cast_candidates=fixture("cast_candidates_cast.json"),
                 sample_fixture={"slug": "sample_book", "exists": True,
                                 "chapters": 2, "recast": True})
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            page.evaluate("fr.bookSlug = 'sample_book';")   # even with a book to go to
            page.click("#fr-skip")
            page.wait_for_timeout(200)
            check("Skip is a request for Setup and is always honoured",
                  page.evaluate("document.body.classList.contains('setup-open')"))

            print("--- ElevenLabs is told what it will cost, and asked twice ---")
            calls.clear()
            boot(page, calls=calls, status=firstrun, config=cfg_first)
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            page.click(".su-engine[data-engine=elevenlabs]")
            page.evaluate("fr.step = 3; frGo(4);")
            page.wait_for_selector("#fr-step-4:not(.fr-hidden)", timeout=8000)
            cost = page.text_content("#fr-cost") or ""
            check("the cost is stated in plain words before any click",
                  "characters" in cost and "credits" in cost, cost.strip()[:70])
            page.click("#fr-hear-btn")
            page.wait_for_timeout(250)
            check("the first click spends nothing",
                  not any(c[1] == "/books/sample" for c in calls))
            check("the button now asks for confirmation",
                  "Yes" in (page.text_content("#fr-hear-btn") or ""))
            page.click("#fr-hear-btn")
            page.wait_for_selector("#firstrun-modal-overlay.hidden", state="attached", timeout=15000)
            check("the second click goes ahead",
                  any(c[1] == "/books/sample" for c in calls))

            print("--- the Setup page says you're set, and points at the sound ---")
            # A green READY badge over five amber optional rows reads as
            # "something is wrong". That is the page the Windows install landed
            # on after the casting modal, with no play button anywhere.
            calls.clear()
            boot(page, calls=calls, status=ready, config=cfg_ready)
            page.click("#setup-chip")
            page.wait_for_selector("#setup-view", state="visible", timeout=8000)
            page.wait_for_timeout(300)
            check("the banner is there when the engine is ok",
                  page.locator("#su-banner").is_visible())
            said = page.text_content("#su-banner") or ""
            check("it says you are set", "You're set" in said, said[:60])
            check("it names the engine that is ready",
                  "System voices" in said, said[:80])
            check("it offers the sample", page.locator("#su-hear-sample").is_visible())
            check("it offers the wizard again",
                  "Run setup again" in (page.text_content(".su-banner-btns") or ""))
            check("the banner is above the intro",
                  page.evaluate("document.querySelector('#su-banner').compareDocumentPosition("
                                "document.querySelector('.su-intro')) "
                                "& Node.DOCUMENT_POSITION_FOLLOWING") > 0)
            check("the amber optional rows are still there, not hidden",
                  page.locator("#setup-view .su-plaque.off, #setup-view .su-plaque.warn").count() > 0,
                  page.locator("#setup-view .su-plaque.off, #setup-view .su-plaque.warn").count())
            ffmpeg_row = next(r for r in ready["rows"] if r["key"] == "tool_ffmpeg")
            shown = page.text_content("#setup-view") or ""
            check("the ffmpeg row says a version, not a path",
                  ffmpeg_row["detail"] in shown and ffmpeg_row["extra"] not in shown,
                  ffmpeg_row["detail"])
            check("the full path is in the tooltip",
                  ffmpeg_row["extra"] in (page.inner_html("#setup-view") or ""))

            print("--- ...and the button runs the same sequence the wizard does ---")
            calls.clear()
            page.click("#su-hear-sample")
            page.wait_for_selector("body.reader-open", timeout=15000)
            ordered = [f"{m} {p}" for m, p, _, _ in calls
                       if p == "/books/sample" or p.startswith("/render/")]
            check("it asked for the sample book, then a render",
                  ordered[:2] == ["POST /books/sample", "POST /render/sample_book/0"], ordered)
            check("it left the Setup page",
                  not page.evaluate("document.body.classList.contains('setup-open')"))
            check("it ends in the reader, reading",
                  page.evaluate("document.body.classList.contains('reader-open')"))

            print("--- no banner when the engine is not ready ---")
            boot(page, calls=calls, status=firstrun, config=cfg_first)
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            page.click("#fr-skip")
            page.wait_for_timeout(300)
            check("the Setup page is showing", 
                  page.evaluate("document.body.classList.contains('setup-open')"))
            check("no 'you're set' while the engine is missing",
                  page.locator("#su-banner").count() == 0)

            print("--- a failure lands in the wizard with a way out ---")
            calls.clear()
            boot(page, calls=calls, status=firstrun, config=cfg_first, fail_at="sample")
            page.wait_for_selector("#firstrun-modal-overlay:not(.hidden)", timeout=8000)
            page.evaluate("fr.step = 3; frGo(4);")
            page.click("#fr-hear-btn")
            page.wait_for_selector("#fr-recover:not(.fr-hidden)", timeout=8000)
            said = page.text_content("#fr-say") or ""
            check("the server's words are on screen", "disk full" in said, said[:70])
            check("it did not stop silently", "err" in (page.get_attribute("#fr-say", "class") or ""))
            check("Try again is offered",
                  "Try again" in (page.text_content("#fr-recover") or ""))
            check("Open Setup is offered",
                  "Open Setup" in (page.text_content("#fr-recover") or ""))
            check("the wizard is still open", not page.locator("#firstrun-modal-overlay").is_hidden())

            # Expected here: the 500 this section asked for, the app's own
            # [firstrun] log of it, and the <audio> element failing to play a
            # wav the mock never produced.
            ignorable = ("disk full", "500", "[firstrun]", "no supported source",
                         "404 (Not Found)")
            unexpected = [e for e in errs if not any(x in e for x in ignorable)]
            check("nothing unexpected on the console", not unexpected, unexpected)
            page.close()
        browser.close()

    print("\nFAILURES:", fails if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
