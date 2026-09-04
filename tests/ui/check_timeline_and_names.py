#!/usr/bin/env python3
"""Headless UI checks for the player/reader contract. NOT part of the pytest run.

Why this file is in the repo at all: the 2026-09-03 reader-view session verified
itself headless and still shipped a player that labelled every line NARRATOR.
The verification lived in a throwaway container and used a hand-written mock
that included a `speaker` field the server had already stopped sending. Both
halves of that are fixed here — the harness is committed, and its timeline mock
is `tests/fixtures/timeline_study_ch0.json`, generated from the live endpoint by
`scripts/refresh_ui_fixtures.py` and kept honest by `tests/test_timeline.py`.

Needs playwright (not a project dependency — install it where you run this):

    pip install playwright && playwright install chromium
    python3 tests/ui/check_timeline_and_names.py [path/to/index.html]

Exits non-zero on the first failed expectation.
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
FIXTURE = ROOT / "tests" / "fixtures" / "timeline_study_ch0.json"
PORT = 8779

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


def main() -> int:
    timeline = json.loads(FIXTURE.read_text())
    serve(INDEX.parent)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 860})
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console",
                lambda m: errs.append(f"console.error: {m.text}") if m.type == "error" else None)
        # Every API call answers {} — these checks drive the render functions
        # directly, so the page only needs to load without exploding.
        page.route("**/*", lambda r: r.continue_() if r.request.url.endswith(INDEX.name)
                   else r.fulfill(status=200, content_type="application/json", body="{}"))
        page.goto(f"http://127.0.0.1:{PORT}/{INDEX.name}")
        page.wait_for_timeout(400)

        print("\n--- the reader renders speakers from a real /timeline payload ---")
        rows = page.evaluate("""(tl) => tl.timeline.map(b => {
            const html = readerParaInner(b, false, 0);
            const m = html.match(/<span class="reader-speaker ([^"]*)">([^<]*)<\\/span>/);
            return {cls: m && m[1], label: m && m[2],
                    dialogue: (b.speaker || 'NARRATOR') !== 'NARRATOR'};
        })""", timeline)
        labels = [r["label"] for r in rows]
        check("labels come from the payload, not a NARRATOR default",
              labels == ["NARRATOR", "Darcy", "Elizabeth", "UNKNOWN"], labels)
        check("dialogue is distinguishable from narration",
              [r["dialogue"] for r in rows] == [False, True, True, True])
        check("each character gets its own colour class",
              len({r["cls"] for r in rows}) > 1, sorted({r["cls"] for r in rows}))

        print("\n--- apostrophe names survive an inline handler ---")
        got = page.evaluate("""() => {
            const results = [];
            window.previewVoice = n => results.push(n);
            const names = ["O'Brien", "Ka'thul", "D'Arcy O'Neill", 'Plain Name'];
            const host = document.createElement('div');
            host.innerHTML = names.map(n =>
                `<button class="t" onclick="previewVoice('${escAttr(n)}')">x</button>`).join('');
            document.body.appendChild(host);
            host.querySelectorAll('button.t').forEach(b => b.click());
            return {sent: names, got: results};
        }""")
        check("every name reaches the handler intact", got["got"] == got["sent"], got)
        markup = page.evaluate("""() => escAttr('Angry <b>&\"quoted\"</b>')""")
        check("markup in a name is still HTML-escaped",
              "<b>" not in markup and "&lt;b&gt;" in markup and "&quot;" in markup, markup)

        check("no page errors", not errs, errs)
        browser.close()

    print("\nFAILURES:", fails if fails else "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
