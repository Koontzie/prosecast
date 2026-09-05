#!/usr/bin/env python3
"""Regenerate tests/fixtures/*.json from the live endpoints.

The headless UI checks feed these files to the page instead of hand-written
mocks. A hand-written mock can be more generous than the server — that is how
`/timeline` lost its `speaker` field for a month while a "verified headless"
reader view kept rendering labels from a mock that still had it. Generating the
fixture from the real endpoint closes that gap; `tests/test_timeline.py`
asserts the two still agree.

Run after deliberately changing an endpoint's shape:

    .venv/bin/python scripts/refresh_ui_fixtures.py
    .venv/bin/pytest tests/ -q
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("PROSECAST_CONFIG", str(Path(tempfile.mkdtemp()) / "config.json"))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from prosecast import ingest as ingest_mod  # noqa: E402
from prosecast import library as lib  # noqa: E402
from prosecast import setup_probe as setup_probe_mod  # noqa: E402
from synthetic import PLAY, build_pdf, study_ir  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def build_study_book(root: Path) -> str:
    """The same little book tests/test_timeline.py uses (from synthetic.py)."""
    lib.ensure_book_dir("study")
    (root / "study" / "ir.json").write_text(json.dumps(study_ir()))
    return "study"


# GET /pipeline/{slug} asks Ollama and whisper whether they are up, so on a
# machine that runs them the answer differs from one that doesn't — the same
# problem `ocr_available` has. The probe verdicts are pinned to fixed rows here
# (the two states the card must draw) so the SHAPE still comes from the live
# endpoint while the fixture stays reproducible anywhere.
def probe_row(key: str, label: str, ok: bool, fix: str = "") -> dict:
    return {"key": key, "label": label, "ok": ok, "state": "ok" if ok else "missing",
            "detail": f"{label} · http://localhost · " + ("ready" if ok else "not responding"),
            "fix": fix, "optional": True}


OLLAMA_FIX = ("Install Ollama from ollama.com and start it, or point the URL at a machine "
              "that runs it.")
WHISPER_FIX = ("Optional. Without it the read-along highlights by sentence (estimated) "
               "instead of by word.")


def pin_probes(ollama_ok: bool, whisper_ok: bool) -> None:
    setup_probe_mod.probe_ollama = lambda: probe_row(
        "ollama", "Who's speaking (local AI)", ollama_ok, "" if ollama_ok else OLLAMA_FIX)
    setup_probe_mod.probe_whisper = lambda: probe_row(
        "whisper", "Read-along timing (whisper)", whisper_ok,
        "" if whisper_ok else WHISPER_FIX)


def upload(client, name: str, data: bytes) -> dict:
    """An upload response with the random id pinned, so the file is stable."""
    body = client.post("/books/upload", files={"file": (name, data)}).json()
    body["upload_id"] = "FIXTURE"
    # Machine-dependent: whether tesseract is on the box that generated this.
    if body.get("ocr_available") is not None:
        body["ocr_available"] = "MACHINE"
        body["ocr_hint"] = "MACHINE"
    return body


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    lib.LIBRARY_DIR = tmp
    slug = build_study_book(tmp)
    client = TestClient(server.app)

    FIXTURES.mkdir(parents=True, exist_ok=True)

    def write(name: str, data, source: str) -> None:
        (FIXTURES / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"{name:32s} <- {source}")

    write("timeline_study_ch0.json", client.get(f"/timeline/{slug}/0").json(),
          f"GET /timeline/{slug}/0")

    # The wizard's three shapes, straight from POST /books/upload.
    books = tmp / "books"
    books.mkdir(exist_ok=True)
    ingest_mod.BOOKS_DIR = server.BOOKS_DIR = books
    write("upload_pdf.json", upload(client, "The Rulebook.pdf",
                                    build_pdf(tmp / "r.pdf").read_bytes()),
          "POST /books/upload (pdf with bookmarks)")
    write("upload_play_txt.json", upload(client, "Scene One.txt", PLAY.encode()),
          "POST /books/upload (script)")
    write("upload_scan_pdf.json", upload(client, "Scanned.pdf",
                                          build_pdf(tmp / "s.pdf", scan=True).read_bytes()),
          "POST /books/upload (scanned pdf)")

    # The Pipeline card's two states: everything reachable, and nothing is.
    pin_probes(ollama_ok=True, whisper_ok=True)
    write("pipeline_ready.json", client.get(f"/pipeline/{slug}").json(),
          f"GET /pipeline/{slug} (services up)")
    pin_probes(ollama_ok=False, whisper_ok=False)
    write("pipeline_offline.json", client.get(f"/pipeline/{slug}").json(),
          f"GET /pipeline/{slug} (services down)")


if __name__ == "__main__":
    main()
