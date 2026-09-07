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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("PROSECAST_CONFIG", str(Path(tempfile.mkdtemp()) / "config.json"))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from prosecast import config as config_mod  # noqa: E402
from prosecast import ingest as ingest_mod  # noqa: E402
from prosecast import library as lib  # noqa: E402
from prosecast import setup_probe as setup_probe_mod  # noqa: E402
from synthetic import (PLAY, build_pdf, pin_chatterbox, pin_config,  # noqa: E402
                       pin_machine, pin_probes, pin_status, pin_voice_bank,
                       study_ir)

FIXTURES = ROOT / "tests" / "fixtures"


def build_study_book(root: Path) -> str:
    """The same little book tests/test_timeline.py uses (from synthetic.py)."""
    lib.ensure_book_dir("study")
    (root / "study" / "ir.json").write_text(json.dumps(study_ir()), encoding="utf-8")
    return "study"


# GET /pipeline/{slug} and GET /setup/status ask Ollama, whisper, the PATH and
# the OS what is here, so on Tyler's Mac the answer differs from a container's —
# the same problem `ocr_available` has. The probe *inputs* are pinned (see
# tests/synthetic.py) so the SHAPE and the wording still come from the live
# endpoint while the fixture stays reproducible anywhere. The drift tests pin
# them the same way.

def wait_for(client, job_id: str, timeout: float = 120.0) -> dict:
    job = None
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f"/render_status/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} never finished: {job}")


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
        (FIXTURES / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
    pin_probes(setup_probe_mod, ollama_ok=True, whisper_ok=True)
    write("pipeline_ready.json", client.get(f"/pipeline/{slug}").json(),
          f"GET /pipeline/{slug} (services up)")
    pin_probes(setup_probe_mod, ollama_ok=False, whisper_ok=False)
    write("pipeline_offline.json", client.get(f"/pipeline/{slug}").json(),
          f"GET /pipeline/{slug} (services down)")

    # ── The first-run wizard (E6) ───────────────────────────────────────────
    # Two ends of the same endpoint: a machine that has never been set up
    # (no config.json, engine still 'auto'), and one where the voice engine
    # answers. Everything the probe can see about the machine is pinned.
    pin_machine(setup_probe_mod, os_name="Darwin", ollama_ok=False, whisper_ok=False)
    write("setup_status_firstrun.json", pin_status(client.get("/setup/status").json()),
          "GET /setup/status (no config.json yet)")
    write("config_firstrun.json", pin_config(client.get("/config").json()),
          "GET /config (no config.json yet)")

    os.environ["PROSECAST_CONFIG"] = str(tmp / "config.json")
    config_mod.invalidate()
    client.put("/config", json={"values": {"tts_engine": "say"}})
    pin_machine(setup_probe_mod, os_name="Darwin", ollama_ok=True, whisper_ok=True)
    write("setup_status_ready.json", pin_status(client.get("/setup/status").json()),
          "GET /setup/status (engine picked, everything answering)")
    write("config_ready.json", pin_config(client.get("/config").json()),
          "GET /config (engine saved)")

    # The two shapes that decide whether the wizard greets someone. `SETUP.sh`
    # copies config.example.json, so a config.json exists before anyone has
    # chosen anything — that must still open the wizard. An engine actually
    # picked (and answering) must not.
    (tmp / "config.json").write_text(
        json.dumps(json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))), encoding="utf-8")
    config_mod.invalidate()
    pin_machine(setup_probe_mod, os_name="Darwin", ollama_ok=False, whisper_ok=False)
    write("setup_status_setup_sh.json", pin_status(client.get("/setup/status").json()),
          "GET /setup/status (config.json from SETUP.sh, no engine chosen)")

    client.put("/config", json={"values": {"tts_engine": "chatterbox"}})
    pin_machine(setup_probe_mod, os_name="Darwin", ollama_ok=True, whisper_ok=True)
    pin_chatterbox(setup_probe_mod)
    write("setup_status_chatterbox.json", pin_status(client.get("/setup/status").json()),
          "GET /setup/status (an engine chosen and answering)")
    client.put("/config", json={"values": {"tts_engine": "say"}})

    # ── The Voices view (E7) ────────────────────────────────────────────────
    # A fixed voice list and a fixed overlay, so the fixture is reproducible on
    # any machine while the SHAPE still comes from the live endpoint. The bank
    # lives in tests/synthetic.py so the drift test feeds the same input.
    real_engine, real_meta = server._active_engine, server.VOICE_META_PATH
    real_cache = server._chatterbox_voice_cache
    pin_voice_bank(server, tmp, engine="chatterbox")
    write("voices_library.json", client.get("/voices/library").json(),
          "GET /voices/library (chatterbox)")
    pin_voice_bank(server, tmp, engine="say")
    write("voices_library_say.json", client.get("/voices/library").json(),
          "GET /voices/library (say — no cloning, no sourcing)")
    server._active_engine, server.VOICE_META_PATH = real_engine, real_meta
    server._chatterbox_voice_cache = real_cache
    write("voices_sources.json", client.get("/voices/sources").json(),
          "GET /voices/sources")

    # The wizard's last step: the built-in sample book, ingested as a job.
    started = client.post("/books/sample").json()
    wait_for(client, started["job_id"])
    started["job_id"] = "FIXTURE"
    write("sample_book.json", started, "POST /books/sample (first call)")

    # The shape that decides whether the casting modal opens over a book, in
    # the state the Windows machine was actually in on 2026-09-06: the sample
    # book exists (SETUP.sh's `main.py --sample --tts stub` made it from a
    # terminal) and has no voice map, so `has_voice_map` is false and there is
    # more than one character. That is the modal's exact trigger, and
    # tests/ui/check_first_run.py needs the server's own words for it rather
    # than a mock that could be kinder.
    real_vm = lib.voice_map_path("sample_book").read_bytes()
    lib.voice_map_path("sample_book").unlink()
    write("cast_candidates_uncast.json",
          client.get("/ir/sample_book/cast_candidates").json(),
          "GET /ir/sample_book/cast_candidates (book exists, never cast)")
    lib.voice_map_path("sample_book").write_bytes(real_vm)
    write("cast_candidates_cast.json",
          client.get("/ir/sample_book/cast_candidates").json(),
          "GET /ir/sample_book/cast_candidates (cast by POST /books/sample)")


if __name__ == "__main__":
    main()
