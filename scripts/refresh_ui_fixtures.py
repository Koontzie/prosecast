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
from synthetic import BLOCKS, PLAY, build_pdf  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def build_study_book(root: Path) -> str:
    """The same little book tests/test_timeline.py uses."""
    blocks = []
    for i, (kind, speaker, text, unresolved) in enumerate(BLOCKS):
        blocks.append({
            "segmentId": f"ch0_seg_{i:04d}", "type": kind, "text": text,
            "speaker": speaker, "confidence": 0.0 if unresolved else 0.9,
            "unresolved": unresolved, "attribution_method": "postfix",
            "cacheKey": None,
            "audioVariants": {"standard": {"url": None, "cached": False},
                              "premium": {"url": None, "cached": False}},
            "selectedVariant": "standard",
        })
    ir = {"book_title": "The Study", "unresolved_count": 1,
          "characters": ["Darcy", "Elizabeth", "O'Brien"],
          "chapters": [{"index": 0, "title": "One", "blocks": blocks}]}
    lib.ensure_book_dir("study")
    (root / "study" / "ir.json").write_text(json.dumps(ir))
    return "study"


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


if __name__ == "__main__":
    main()
