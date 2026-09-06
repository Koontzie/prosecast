#!/usr/bin/env python3
"""Headless check of the E7 Voices view. NOT part of the pytest run.

Driven by `tests/fixtures/voices_library*.json` and `voices_sources.json`,
which are generated from the live endpoints by scripts/refresh_ui_fixtures.py
against the fixed voice bank in tests/synthetic.py — tests/test_voices_library.py
fails if they drift. A hand-written mock would be free to be kinder than the
endpoint, which is exactly how a "verified headless" reader view spent a month
rendering a field the server had already stopped sending.

What it is looking for: that the chip really swaps views rather than stacking
them, that the count line tells the truth, that a typed note reaches the server
keyed on the STEM and not on the glyphed display name, that the licence badge
matches `distributable`, that a non-Chatterbox engine gets its own list and an
honest sentence instead of a fake one, and that every collapsed panel is
actually collapsed — in both skins.

    pip install playwright && playwright install chromium
    python3 tests/ui/check_voices.py [path/to/index.html]
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
PORT = 8783

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
    return json.loads((FIXTURES / name).read_text())


LIBRARY = fixture("voices_library.json")
LIBRARY_SAY = fixture("voices_library_say.json")
SOURCES = fixture("voices_sources.json")

# One block of silence — enough for <audio> to accept the src without the
# harness's own 'no supported source' noise drowning the real console errors.
WAV = (b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
       b"\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")


def router(*, calls: list, library=None, fail_library: bool = False,
           fail_meta: bool = False):
    """Answers the app's fetches. `calls` collects (method, path, body, full)."""
    lib = library if library is not None else LIBRARY

    def route(r):
        req = r.request
        full = req.url.split(f":{PORT}", 1)[-1]
        path = full.split("?")[0]
        calls.append((req.method, path, req.post_data, full))

        def js(obj, code=200):
            r.fulfill(status=code, content_type="application/json", body=json.dumps(obj))

        if path.endswith(INDEX.name):
            return r.continue_()
        if path == "/voices/library":
            if fail_library:
                return js({"detail": "chatterbox server not responding"}, 500)
            return js(lib)
        if path == "/voices/sources":
            return js(SOURCES)
        if path.startswith("/voices/meta/"):
            if fail_meta:
                return js({"detail": "disk full"}, 500)
            key = path.rsplit("/", 1)[-1]
            was = next((v for v in lib["voices"] if v["key"] == key), None)
            entry = {k: v for k, v in (was or {}).items()
                     if k not in ("id", "name", "key", "kind")}
            entry.update(json.loads(req.post_data or "{}"))
            entry.setdefault("edited", "2026-09-06T12:00:00+00:00")
            return js({"key": key, "entry": entry})
        if path.startswith("/voice/preview/"):
            return r.fulfill(status=200, content_type="audio/wav", body=WAV)
        if path in ("/engine_status", "/engine_status/recheck"):
            return js({"engine": lib["engine"], "ok": True, "source": "file",
                       "detail": "", "voice_count": len(lib["voices"])})
        if path == "/setup/status":
            return js(fixture("setup_status_chatterbox.json"))
        if path == "/config":
            return js(fixture("config_ready.json"))
        if path == "/books":
            return js([])
        return js({})
    return route


def boot(page, *, calls, **kw):
    page.unroute("**/*")
    page.route("**/*", router(calls=calls, **kw))
    page.goto(f"http://127.0.0.1:{PORT}/{INDEX.name}")
    page.wait_for_timeout(350)


def open_voices(page):
    page.click("#voices-chip")
    page.wait_for_selector("#voices-view .vv-row, #vv-empty:not(.vv-hidden), .vv-note.err",
                           timeout=8000)
    page.wait_for_timeout(150)


def collapsed_panels_are_collapsed(page) -> list[str]:
    """Trap 6: `.hidden` has no global rule in this file — a view that brings
    its own class but forgets the CSS renders every 'hidden' panel anyway."""
    return [sel for sel in ("#vv-sources", "#vv-ab", "#vv-engine-note")
            if page.locator(sel).count() and not page.locator(sel).is_hidden()]


def main() -> int:
    serve(INDEX.parent)
    voices = LIBRARY["voices"]
    visible = [v for v in voices if not v["hidden"]]
    hidden = [v for v in voices if v["hidden"]]
    shippable = next(v for v in visible if v["distributable"])
    restricted = next(v for v in visible if v["license"] and not v["distributable"])

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for skin in ("onair", "classic"):
            print(f"\n=== {skin} skin ===")
            page = browser.new_page(viewport={"width": 1280, "height": 940})
            # On Air is the default and the skin is read from localStorage by an
            # inline script at parse time — setting data-theme after load does
            # nothing, which is how this repo "verified both skins" twice in
            # On Air more than once.
            page.add_init_script(
                f"try {{ localStorage.setItem('prosecast-theme', '{skin}'); }} catch (e) {{}}")
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("console",
                    lambda m: errs.append(f"console.error: {m.text}") if m.type == "error" else None)
            calls: list = []

            print("--- the chip swaps views, it does not stack them ---")
            boot(page, calls=calls)
            themed = page.evaluate("document.documentElement.dataset.theme || 'classic'")
            check(f"the {skin} skin is actually applied", themed == skin, themed)
            check("the Voices view is closed to start with",
                  page.locator("#voices-view").is_hidden())
            page.click("#setup-chip")
            page.wait_for_timeout(200)
            check("the Setup view is open before we start",
                  page.evaluate("document.body.classList.contains('setup-open')"))
            open_voices(page)
            check("the chip opened the Voices view",
                  page.evaluate("document.body.classList.contains('voices-open')"))
            check("#voices-view is actually visible", page.locator("#voices-view").is_visible())
            check("it closed the Setup view",
                  not page.evaluate("document.body.classList.contains('setup-open')"))
            check("and #setup-view is not rendering underneath",
                  page.locator("#setup-view").is_hidden())
            check("nor is the reader", page.locator("#reader-view").is_hidden())
            check("nor the chapter list", page.locator("#main").is_hidden())
            stray = collapsed_panels_are_collapsed(page)
            check("every collapsed panel is really collapsed", not stray, stray)

            print("--- the count line tells the truth ---")
            count = page.text_content("#vv-count") or ""
            check("it counts every voice, not just the visible ones",
                  f"{len(voices)} voices" in count, count)
            check("it says how many are hidden",
                  f"{len(hidden)} hidden" in count, count)
            check("an untouched page does not read as filtered",
                  "showing" not in count, count)
            check("hidden voices are out of view by default",
                  page.locator(".vv-row").count() == len(visible),
                  page.locator(".vv-row").count())
            check("the American count is there — the whole point of the sourcing work",
                  "American" in count, count)

            print("--- orphaned notes are surfaced, not swallowed ---")
            orphan_txt = page.text_content("#vv-orphans") or ""
            for key in LIBRARY["orphans"]:
                check(f"orphan {key} is named on screen", key in orphan_txt)
            check("and it says nothing was deleted", "Nothing has been deleted" in orphan_txt)

            print("--- search narrows the rows ---")
            target = visible[0]
            page.fill("#vv-search", target["key"])
            page.wait_for_timeout(200)
            check("search narrows to the one match",
                  page.locator(".vv-row").count() == 1, page.locator(".vv-row").count())
            check("the count line says it is filtered",
                  "showing 1 of" in (page.text_content("#vv-count") or ""))
            page.fill("#vv-search", "notavoiceanywhere")
            page.wait_for_timeout(200)
            check("a filter that matches nothing says so, and does not render nothing",
                  page.locator("#vv-empty").is_visible() and page.locator(".vv-row").count() == 0)
            check("the toolbar survives an empty result",
                  page.locator("#vv-search").is_visible())
            # Notes are searched too, not just names.
            noted = next(v for v in visible if v["notes"])
            page.fill("#vv-search", noted["notes"].split()[-1])
            page.wait_for_timeout(200)
            check("search reaches into the notes", page.locator(".vv-row").count() >= 1)
            page.fill("#vv-search", "")
            page.wait_for_timeout(200)

            print("--- the hidden filter brings back a de-emphasised row ---")
            page.click("#vv-f-hidden")
            page.wait_for_timeout(250)
            check("show hidden reveals them all",
                  page.locator(".vv-row").count() == len(voices),
                  page.locator(".vv-row").count())
            check("a hidden voice renders de-emphasised",
                  page.locator(".vv-row.retired").count() == len(hidden))
            row = page.locator(f'.vv-row[data-key="{hidden[0]["key"]}"]')
            check("and it is the right one", row.count() == 1 and "retired" in
                  (row.get_attribute("class") or ""))
            page.click("#vv-f-hidden")
            page.wait_for_timeout(200)

            print("--- the licence badge answers 'can I ship this?' ---")
            ok_badge = page.locator(f'.vv-row[data-key="{shippable["key"]}"] .vv-lic')
            no_badge = page.locator(f'.vv-row[data-key="{restricted["key"]}"] .vv-lic')
            check("distributable reads green",
                  "vv-lic-ok" in (ok_badge.get_attribute("class") or ""),
                  ok_badge.get_attribute("class"))
            check("non-distributable reads amber",
                  "vv-lic-no" in (no_badge.get_attribute("class") or ""),
                  no_badge.get_attribute("class"))
            check("the SPDX id is in the tooltip",
                  restricted["license"] in (no_badge.get_attribute("title") or ""),
                  no_badge.get_attribute("title"))

            print("--- a typed note is saved under the STEM, never the display name ---")
            calls.clear()
            key = target["key"]
            page.fill(f'.vv-row[data-key="{key}"] .vv-notes', "a note typed by hand")
            page.wait_for_timeout(1100)                     # past the 600 ms debounce
            posts = [c for c in calls if c[1].startswith("/voices/meta/") and c[0] == "POST"]
            check("exactly one save went out, not one per keystroke",
                  len(posts) == 1, [c[1] for c in posts])
            check("it is keyed on the stem",
                  posts and posts[0][1] == f"/voices/meta/{key}", posts[:1])
            check("and the glyph never travelled with it",
                  posts and "♂" not in posts[0][1] and "♀" not in posts[0][1])
            body = json.loads(posts[0][2]) if posts else {}
            check("only the field that changed was sent",
                  set(body) == {"notes"}, list(body))
            check("the row says it saved",
                  "saved" in (page.text_content(f'.vv-row[data-key="{key}"] .vv-saved') or ""))

            print("--- a rating and a tag edit go the same way ---")
            calls.clear()
            page.click(f'.vv-row[data-key="{key}"] .vv-stars [data-star="3"]')
            page.wait_for_timeout(400)
            posts = [c for c in calls if c[0] == "POST"]
            check("a star click patches rating alone",
                  posts and json.loads(posts[0][2]) == {"rating": 3}, posts[:1])
            calls.clear()
            tag_box = f'.vv-row[data-key="{key}"] .vv-tags'
            page.fill(tag_box, "American, Gravelly, american")
            page.locator(tag_box).press("Enter")
            page.wait_for_timeout(400)
            posts = [c for c in calls if c[0] == "POST"]
            check("tags are lowercased and de-duplicated before they are sent",
                  posts and json.loads(posts[0][2]) == {"tags": ["american", "gravelly"]},
                  posts[:1])

            print("--- a failed save keeps the text and says so ---")
            boot(page, calls=calls, fail_meta=True)
            open_voices(page)
            box = f'.vv-row[data-key="{key}"] .vv-notes'
            page.fill(box, "this save will fail")
            page.wait_for_timeout(1100)
            said = page.text_content(f'.vv-row[data-key="{key}"] .vv-saved') or ""
            check("it says the save failed", "not saved" in said, said)
            check("the typed text is still in the box",
                  page.input_value(box) == "this save will fail")

            print("--- audition and A/B ---")
            boot(page, calls=calls)
            open_voices(page)
            check("the audition line is prefilled from audition_voices.py",
                  (page.input_value("#vv-line-input") or "").startswith("The rain had stopped"))
            calls.clear()
            page.click(f'.vv-row[data-key="{key}"] [id^="vv-play-"]')
            page.wait_for_timeout(400)
            prev = [c for c in calls if c[1].startswith("/voice/preview/")]
            check("auditioning asks the server for this voice",
                  prev and prev[0][1].endswith(target["id"].replace(":", "%3A")),
                  prev[:1])
            check("the audition line is what it sends",
                  prev and "The+rain+had+stopped" in prev[0][3].replace("%20", "+")
                  or prev and "The%20rain" in prev[0][3], prev[:1])

            check("the A/B bar is hidden before anything is slotted",
                  page.locator("#vv-ab").is_hidden())
            page.click(f'.vv-row[data-key="{visible[0]["key"]}"] [id^="vv-ab-"]')
            page.wait_for_timeout(150)
            page.click(f'.vv-row[data-key="{visible[1]["key"]}"] [id^="vv-ab-"]')
            page.wait_for_timeout(250)
            check("the A/B bar appears once two voices are slotted",
                  not page.locator("#vv-ab").is_hidden())
            check("slot A names the first voice",
                  visible[0]["name"] in (page.text_content("#vv-slot-A") or ""),
                  page.text_content("#vv-slot-A"))
            check("slot B names the second",
                  visible[1]["name"] in (page.text_content("#vv-slot-B") or ""),
                  page.text_content("#vv-slot-B"))
            check("A-then-B is offered", not page.is_disabled("#vv-play-ab"))
            calls.clear()
            page.click("#vv-play-a")
            page.wait_for_timeout(500)
            n_first = len([c for c in calls if c[1].startswith("/voice/preview/")])
            page.click("#vv-play-a")           # toggle off
            page.wait_for_timeout(150)
            page.click("#vv-play-a")           # and on again
            page.wait_for_timeout(500)
            n_after = len([c for c in calls if c[1].startswith("/voice/preview/")])
            check("a slot's clip is fetched once and then cached",
                  n_first == 1 and n_after == 1, f"{n_first} then {n_after}")
            page.screenshot(path=str(Path(__file__).parent / f"voices_{skin}.png"))

            print("--- refresh goes through the engine re-check ---")
            calls.clear()
            page.click("#vv-refresh")
            page.wait_for_timeout(600)
            paths = [f"{m} {p}" for m, p, _, _ in calls]
            check("it drops the cached voice list first",
                  "POST /engine_status/recheck" in paths, paths)
            check("and only then re-reads the library",
                  paths.index("POST /engine_status/recheck") < paths.index("GET /voices/library"),
                  paths)

            print("--- Find more voices is a catalogue, not a download button ---")
            page.click("#vv-sources-btn")
            page.wait_for_selector("#vv-sources:not(.vv-hidden)", timeout=8000)
            page.wait_for_timeout(200)
            body_txt = page.text_content("#vv-src-body") or ""
            check("every source is listed",
                  page.locator(".vv-src").count() == len(SOURCES["sources"]),
                  page.locator(".vv-src").count())
            check("all three tiers are shown", page.locator(".vv-tier").count() == 3)
            check("the standing note travels with it",
                  "not voice consent" in body_txt, body_txt[:80])
            check("it points at the doc", "docs/voice-sources.md" in body_txt)
            html = page.inner_html("#vv-src-body")
            check("there is a copy button", "copy</button>" in html)
            check("there is NO run button — pulling a corpus is Tyler's call",
                  "run</button>" not in html.lower() and "onclick=\"vvRun" not in html)
            with_cmd = [s for s in SOURCES["sources"] if s["command"]]
            check("only the ship tier offers a command",
                  all(s["tier"] == "ship" for s in with_cmd), [s["id"] for s in with_cmd])
            check("the command is shown verbatim",
                  with_cmd and with_cmd[0]["command"] in body_txt)
            page.screenshot(path=str(Path(__file__).parent / f"voices_sources_{skin}.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            check("Escape closes the panel first, not the whole view",
                  page.locator("#vv-sources").is_hidden()
                  and page.evaluate("document.body.classList.contains('voices-open')"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            check("a second Escape leaves the view",
                  not page.evaluate("document.body.classList.contains('voices-open')"))

            print("--- nothing overflows at 1280px ---")
            open_voices(page)
            over = page.evaluate(
                "() => { const d = document.documentElement;"
                " return [d.scrollWidth, d.clientWidth]; }")
            check("the page does not scroll sideways", over[0] <= over[1], over)
            wide = page.evaluate(
                "() => [...document.querySelectorAll('#voices-view *')]"
                ".filter(e => e.getBoundingClientRect().right > window.innerWidth + 1)"
                ".map(e => e.className || e.id).slice(0, 5)")
            check("no element runs off the right edge", not wide, wide)

            print("--- a non-Chatterbox engine gets its own list and an honest sentence ---")
            boot(page, calls=calls, library=LIBRARY_SAY)
            open_voices(page)
            check("say's own voices are listed",
                  page.locator(".vv-row").count() == len(LIBRARY_SAY["voices"]),
                  page.locator(".vv-row").count())
            note = page.text_content("#vv-engine-note") or ""
            check("the note is showing", not page.locator("#vv-engine-note").is_hidden())
            check("it names the engine", "say" in note, note[:60])
            check("and says plainly that sourcing/cloning need Chatterbox",
                  "Chatterbox" in note, note[:120])
            check("no orphan panel on a static-list engine",
                  page.locator("#vv-orphans").is_hidden())
            check("collapsed panels are still collapsed here",
                  not [s for s in ("#vv-sources", "#vv-ab") if not page.locator(s).is_hidden()])

            print("--- zero voices, and a library that will not load ---")
            boot(page, calls=calls, library={"engine": "stub", "voices": [], "orphans": []})
            open_voices(page)
            check("an empty bank says so rather than showing nothing",
                  page.locator("#vv-empty").is_visible()
                  and "no voices" in (page.text_content("#vv-empty") or "").lower(),
                  page.text_content("#vv-empty"))

            boot(page, calls=calls, fail_library=True)
            open_voices(page)
            err = page.text_content("#vv-engine-note") or ""
            check("a 500 is said out loud", "Could not read the voice list" in err, err[:80])
            check("it names the failure", "500" in err, err[:80])
            check("and points somewhere useful", "Setup" in err)
            check("the toolbar survives the failure", page.locator("#vv-search").is_visible())
            check("nothing is claimed about the count",
                  "unavailable" in (page.text_content("#vv-count") or ""))

            # Expected here: the 500 this section asked for, the failed-save
            # 500, and the <audio> element's complaints about the one-block wav.
            ignorable = ("500", "disk full", "not responding", "no supported source",
                         "Failed to load resource", "404")
            unexpected = [e for e in errs if not any(x in e for x in ignorable)]
            check("nothing unexpected on the console", not unexpected, unexpected)
            page.close()
        browser.close()

    print("\nFAILURES:", fails if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
