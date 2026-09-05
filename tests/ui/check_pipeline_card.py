#!/usr/bin/env python3
"""Headless check of the E3 Pipeline card. NOT part of the pytest run.

Driven by `tests/fixtures/pipeline_*.json`, which are generated from
GET /pipeline/{slug} by scripts/refresh_ui_fixtures.py — tests/test_pipeline_api.py
fails if they drift from the endpoint. A hand-written mock of this endpoint
would be free to be more generous than the server, which is how the reader view
shipped broken once already.

What it is looking for is the honesty of the card, not its prettiness: a button
that is disabled says WHY and offers Setup, a running job shows real numbers, a
circuit-breaker abort lands in the card instead of an alert, and a chapter with
no per-block audio is offered nothing rather than something that would fail.

    pip install playwright && playwright install chromium
    python3 tests/ui/check_pipeline_card.py [path/to/index.html]
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
PORT = 8781

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


SLUG = "study"
CHAPTERS = [
    {"index": 0, "title": "One", "block_count": 4, "dialogue_count": 3,
     "unresolved_count": 1, "has_audio": True, "wav_file": "ch0.wav"},
    {"index": 1, "title": "Two", "block_count": 4, "dialogue_count": 2,
     "unresolved_count": 2, "has_audio": True, "wav_file": "ch1.wav"},
    {"index": 2, "title": "Three", "block_count": 4, "dialogue_count": 0,
     "unresolved_count": 0, "has_audio": False, "wav_file": "ch2.wav"},
]


def load(fixture: str) -> dict:
    return json.loads((FIXTURES / fixture).read_text())


def three_chapter(pipeline: dict, per_chapter: list) -> dict:
    """The one-chapter study fixture stretched over the three-chapter list the
    check drives, with the fields the card reads made explicit."""
    p = json.loads(json.dumps(pipeline))
    p["chapters"] = 3
    p["rendered"] = 2
    p["align"]["per_chapter"] = per_chapter
    p["align"]["needs_alignment"] = [c["index"] for c in per_chapter
                                     if c["state"] in ("stale", "none")]
    return p


def router(pipeline: dict, *, calls: list, job_ticks: list, refuse: str = "",
           chapters=None):
    """Answers the app's fetches. `calls` collects (method, path, body).

    `job_ticks` is the sequence GET /render_status/<id> walks through, so a
    single check can watch a job go queued → running → done.
    """
    state = {"tick": 0, "pipeline": pipeline}

    def route(r):
        req = r.request
        path = req.url.split(f":{PORT}", 1)[-1].split("?")[0]
        calls.append((req.method, path, req.post_data))

        def js(obj, status=200):
            r.fulfill(status=status, content_type="application/json", body=json.dumps(obj))

        if path.endswith(INDEX.name):
            return r.continue_()
        if path == "/books":
            return js([{"slug": SLUG, "title": "The Study", "chapters": 3, "unresolved": 3}])
        if path.startswith("/pipeline/"):
            if req.method == "POST":
                if refuse:
                    return js({"detail": refuse}, 409)
                return js({"job_id": "pj1"})
            return js(state["pipeline"])
        if path.startswith("/render_status/"):
            tick = job_ticks[min(state["tick"], len(job_ticks) - 1)]
            state["tick"] += 1
            return js(tick)
        if path.startswith("/chapters/"):
            return js({"book_title": "The Study", "chapters": chapters or CHAPTERS})
        if path.endswith("/characters"):
            return js({"characters": ["NARRATOR", "Darcy", "Elizabeth"]})
        if path.endswith("/cast_candidates"):
            return js({"characters": [], "voices": [], "has_voice_map": True})
        if path.startswith("/voice_map/"):
            return js({"engine": "stub", "map": {"NARRATOR": "v1"}})
        if path == "/voices":
            return js([{"name": "v1", "label": "Voice One"}])
        if path == "/setup/status":
            return js({"ready": True, "rows": [], "config_exists": True,
                       "shadowed_by_env": [], "os": "mac", "config_path": "/tmp/c.json"})
        return js({})
    return route


PER_MIXED = [{"index": 0, "state": "fresh"},
             {"index": 1, "state": "stale"},
             {"index": 2, "state": "no_blocks"}]

RUNNING_TICKS = [
    {"job_id": "pj1", "kind": "ai_pass", "book_slug": SLUG, "status": "running",
     "stage": "attributing", "detail": "scene 41 of 120", "progress": 41, "total": 120,
     "error": None, "result": None, "queue_position": 0},
    {"job_id": "pj1", "kind": "ai_pass", "book_slug": SLUG, "status": "done",
     "stage": "done", "detail": "18 resolved, 0 still unresolved", "progress": 1, "total": 1,
     "error": None, "queue_position": 0,
     "result": {"targets": 18, "resolved": 18, "unresolved_after": 0, "profiled": 4,
                "aborted": False, "abort_reason": None}},
]

ABORT_TICKS = [
    {"job_id": "pj1", "kind": "ai_pass", "book_slug": SLUG, "status": "done",
     "stage": "done", "detail": "stopped early", "progress": 1, "total": 1,
     "queue_position": 0,
     "error": "Ollama stopped answering after 3 tries — everything decided so far is saved.",
     "result": {"targets": 18, "resolved": 6, "unresolved_after": 12, "profiled": 0,
                "aborted": True,
                "abort_reason": "Ollama stopped answering after 3 tries."}},
]


def open_book(page, pipeline, calls, **kw):
    page.unroute("**/*")
    page.route("**/*", router(pipeline, calls=calls, **kw))
    page.click(".book-btn")
    page.wait_for_selector("#pipe-card", timeout=8000)
    page.wait_for_function(
        "() => !document.getElementById('pipe-ai-detail').textContent.includes('checking')",
        timeout=8000)


def main() -> int:
    serve(INDEX.parent)
    ready = load("pipeline_ready.json")
    offline = load("pipeline_offline.json")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for skin in ("onair", "classic"):
            print(f"\n=== {skin} skin ===")
            page = browser.new_page(viewport={"width": 1400, "height": 950})
            # On Air is the default and the choice is read from localStorage by an
            # inline script at parse time, so it must be set before navigation.
            page.add_init_script(
                f"try {{ localStorage.setItem('prosecast-theme', '{skin}'); }} catch (e) {{}}")
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("console",
                    lambda m: errs.append(f"console.error: {m.text}") if m.type == "error" else None)
            calls: list = []
            page.route("**/*", router(ready, calls=calls, job_ticks=RUNNING_TICKS))
            page.goto(f"http://127.0.0.1:{PORT}/{INDEX.name}")
            page.wait_for_selector(".book-btn", timeout=8000)
            themed = page.evaluate("document.documentElement.dataset.theme || 'classic'")
            check(f"the {skin} skin is actually applied", themed == skin, themed)

            print("--- the card shows the whole pipeline, not just two buttons ---")
            calls.clear()
            up = three_chapter(ready, PER_MIXED)
            open_book(page, up, calls, job_ticks=RUNNING_TICKS)
            stages = page.locator("#pipe-flow .pipe-step").all_text_contents()
            check("all six stages are shown in order",
                  [s.strip() for s in stages] ==
                  ["Rules", "AI pass", "Cast", "Render", "Align", "Export"], stages)
            check("rules is green — it ran at ingest",
                  "ok" in (page.get_attribute("#pipe-flow .pipe-step", "class") or ""))
            check("the card asked the server exactly once",
                  sum(1 for c in calls if c[1] == f"/pipeline/{SLUG}" and c[0] == "GET") == 1,
                  [c[1] for c in calls])

            print("--- the AI pass says what it would do ---")
            detail = page.text_content("#pipe-ai-detail") or ""
            check("the unresolved count is on the card", "unresolved" in detail, detail)
            check("when it last ran is on the card", "never run" in detail, detail)
            check("the button is enabled when Ollama is up",
                  not page.is_disabled("#pipe-ai-btn"))
            opts = page.locator("#pipe-scope option").all_text_contents()
            check("all three scopes are offered with their counts",
                  len(opts) == 3 and all("(" in o for o in opts), opts)
            check("no provenance warning on the default scope",
                  page.locator("#pipe-scope-warning").is_hidden())
            page.select_option("#pipe-scope", "all")
            warn = page.text_content("#pipe-scope-warning") or ""
            check("scope 'all' warns about provenance", "provenance" in warn, warn[:60])
            check("...and promises corrections are safe",
                  "never overwritten" in warn, warn[-60:])
            page.select_option("#pipe-scope", "unresolved")
            check("the warning goes away again",
                  page.locator("#pipe-scope-warning").is_hidden())
            page.screenshot(path=str(Path(__file__).parent / f"pipeline_{skin}.png"))

            print("--- alignment states are per chapter, and honest ---")
            check("a fresh chapter says so",
                  (page.text_content("#alignchip-0") or "").strip() == "words ✓")
            check("a stale chapter says so",
                  "stale" in (page.text_content("#alignchip-1") or ""))
            check("a chapter with no per-block audio is offered nothing",
                  page.locator("#alignchip-2").is_hidden())
            albtn = page.text_content("#pipe-align-btn") or ""
            check("the Align button counts what it will do", "1 chapter" in albtn, albtn)
            check("the card says alignment is automatic after a render",
                  "automatically" in (page.text_content("#pipe-align-detail") or ""))

            print("--- a running job shows real numbers, from the shared poller ---")
            calls.clear()
            page.click("#pipe-ai-btn")
            page.wait_for_selector("#pipe-run:not(.pipe-hidden)", timeout=8000)
            page.wait_for_function(
                "() => document.getElementById('pipe-run-text').textContent.includes('scene')",
                timeout=8000)
            check("the stage and the scene number are shown",
                  "attributing · scene 41 of 120" in (page.text_content("#pipe-run-text") or ""),
                  page.text_content("#pipe-run-text"))
            check("the progress bar is at 34%",
                  page.get_attribute("#pipe-run-fill", "style").startswith("width: 34%"),
                  page.get_attribute("#pipe-run-fill", "style"))
            body = json.loads(next(c[2] for c in calls if c[1].endswith("/ai_pass")))
            check("the chosen scope is what gets sent", body["scope"] == "unresolved", body)
            page.wait_for_selector("#pipe-note:not(.pipe-hidden)", timeout=8000)
            note = page.text_content("#pipe-note") or ""
            check("the result is reported in the card", "18 lines resolved" in note, note)
            check("...including the cast it profiled", "4 characters profiled" in note, note)
            check("the progress bar goes away when it is done",
                  page.locator("#pipe-run").is_hidden())
            check("only one poller is used — /render_status, same as renders",
                  any(c[1].startswith("/render_status/") for c in calls))

            print("--- a circuit-breaker abort lands in the card, not an alert ---")
            calls.clear()
            page.on("dialog", lambda d: (fails.append("an alert() was raised"), d.dismiss()))
            open_book(page, up, calls, job_ticks=ABORT_TICKS)
            page.click("#pipe-ai-btn")
            page.wait_for_selector("#pipe-note:not(.pipe-hidden)", timeout=8000)
            note = page.text_content("#pipe-note") or ""
            check("the reason the pass stopped is shown",
                  "Ollama stopped answering" in note, note)
            check("...and how much it saved first", "6 lines were resolved" in note, note)
            check("the abort is amber, not red",
                  "bad" not in (page.get_attribute("#pipe-note", "class") or ""))

            print("--- with the services down, the buttons say why ---")
            calls.clear()
            down = three_chapter(offline, PER_MIXED)
            open_book(page, down, calls, job_ticks=RUNNING_TICKS)
            check("Run AI pass is disabled", page.is_disabled("#pipe-ai-btn"))
            reason = page.text_content("#pipe-ai-reason") or ""
            check("it says Ollama is the reason", "Ollama isn't reachable" in reason, reason[:60])
            check("...and offers Setup", "open Setup" in reason)
            check("...and carries the probe's own fix",
                  "ollama.com" in reason, reason[-70:])
            check("Align is disabled too", page.is_disabled("#pipe-align-btn"))
            check("and says whisper is the reason",
                  "Whisper isn't reachable" in (page.text_content("#pipe-align-reason") or ""))
            check("the card no longer claims alignment is automatic",
                  "automatically" not in (page.text_content("#pipe-align-detail") or ""))
            page.click("#pipe-ai-reason a")
            page.wait_for_timeout(200)
            check("the Setup link actually opens Setup",
                  page.evaluate("document.body.classList.contains('setup-open')"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
            page.screenshot(path=str(Path(__file__).parent / f"pipeline_{skin}_offline.png"))

            print("--- a render in progress blocks the AI pass, and says so ---")
            calls.clear()
            busy = three_chapter(ready, PER_MIXED)
            busy["render_running"] = True
            open_book(page, busy, calls, job_ticks=RUNNING_TICKS)
            check("Run AI pass is disabled while a render runs",
                  page.is_disabled("#pipe-ai-btn"))
            check("it explains the ir.json conflict in words",
                  "ir.json" in (page.text_content("#pipe-ai-reason") or ""),
                  page.text_content("#pipe-ai-reason"))

            print("--- an AI pass in progress blocks the render button ---")
            calls.clear()
            passing = three_chapter(ready, PER_MIXED)
            passing["running_job_id"] = "pj1"
            passing["running_kind"] = "ai_pass"
            open_book(page, passing, calls, job_ticks=RUNNING_TICKS)
            check("Render all is disabled", page.is_disabled("#regen-all-btn"))
            check("...and says why in its tooltip",
                  "AI pass" in (page.get_attribute("#regen-all-btn", "title") or ""),
                  page.get_attribute("#regen-all-btn", "title"))
            check("the AI pass plaque is busy",
                  "busy" in (page.get_attribute("#pipe-ai-plaque", "class") or ""))

            print("--- a server refusal lands in the card, in the server's words ---")
            calls.clear()
            page.unroute("**/*")
            page.route("**/*", router(up, calls=calls, job_ticks=RUNNING_TICKS,
                                      refuse="A render is running on this book — the AI "
                                             "pass would fight it for ir.json."))
            page.click(".book-btn")
            page.wait_for_selector("#pipe-card", timeout=8000)
            page.wait_for_function(
                "() => !document.getElementById('pipe-ai-btn').disabled", timeout=8000)
            page.click("#pipe-ai-btn")
            page.wait_for_selector("#pipe-note:not(.pipe-hidden)", timeout=8000)
            check("the server's sentence is shown verbatim",
                  "would fight it for ir.json" in (page.text_content("#pipe-note") or ""),
                  page.text_content("#pipe-note"))
            check("the button comes back so you can try again",
                  not page.is_disabled("#pipe-ai-btn"))

            # The 409 itself is the point of that section; anything else is not.
            unexpected = [e for e in errs if "409" not in e and "ir.json" not in e]
            check("no page errors anywhere", not unexpected, unexpected)
            page.close()
        browser.close()

    print("\nFAILURES:", fails if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
