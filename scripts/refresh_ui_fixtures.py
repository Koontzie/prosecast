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
from prosecast import library as lib  # noqa: E402
from test_timeline import BLOCKS  # noqa: E402

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


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    lib.LIBRARY_DIR = tmp
    slug = build_study_book(tmp)
    client = TestClient(server.app)

    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, url in [("timeline_study_ch0.json", f"/timeline/{slug}/0")]:
        data = client.get(url).json()
        (FIXTURES / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"{name:32s} <- {url}")


if __name__ == "__main__":
    main()
