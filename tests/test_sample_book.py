"""
Phase E6.1 — POST /books/sample: the built-in sample book as an ingest job.

The first-run wizard ends by reading the sample book aloud, and a fresh clone
has no books at all (`library/` and `books/` are gitignored). This endpoint is
the only way that book is created, so the things that matter are: it ingests on
the first call, does nothing at all on the second, and writes ir.json through
the atomic writer like every other IR write in the repo.

Offline and hermetic, like tests/test_ingest.py: tmp library, tmp books/.
"""
import builtins
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from prosecast import ingest  # noqa: E402
from prosecast import library as lib  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolate the library and books dirs; nothing touches Tyler's real ones."""
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(ingest, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(server, "BOOKS_DIR", tmp_path / "books")
    (tmp_path / "books").mkdir()
    return tmp_path


@pytest.fixture
def client(sandbox):
    return TestClient(server.app)


def _wait(client, job_id, timeout=90):
    t0 = time.time()
    job = None
    while time.time() - t0 < timeout:
        job = client.get(f"/render_status/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"sample ingest job {job_id} never finished: {job}")


# ── first call: it makes the book ────────────────────────────────────────────

def test_first_call_ingests_the_sample_as_a_job(client, sandbox):
    body = client.post("/books/sample").json()
    assert body["slug"] == "sample_book"
    assert body["exists"] is False
    assert body["job_id"]

    job = _wait(client, body["job_id"])
    assert job["status"] == "done", job
    assert job["kind"] == "ingest"           # polled like any upload
    assert job["book_slug"] == "sample_book"

    ir_path = lib.ir_path("sample_book")
    assert ir_path.exists()
    ir = json.loads(ir_path.read_text())
    assert len(ir["chapters"]) >= 2
    assert job["result"]["chapters"] == len(ir["chapters"])
    # rules-only: the wizard must work on rung 1 with nothing but `say`
    assert ir["ingest"]["mode"] == "novel"


def test_the_text_file_is_written_where_books_live(client, sandbox):
    client.post("/books/sample")
    assert (sandbox / "books" / "sample_book.txt").exists()


def test_the_book_shows_up_in_the_library_listing(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    slugs = [b["slug"] for b in client.get("/books").json()]
    assert "sample_book" in slugs


# ── second call: it does nothing ─────────────────────────────────────────────

def test_second_call_is_a_no_op(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    before = lib.ir_path("sample_book").read_bytes()

    body = client.post("/books/sample").json()
    assert body == {"slug": "sample_book", "exists": True,
                    "chapters": len(json.loads(before)["chapters"])}
    assert "job_id" not in body
    assert lib.ir_path("sample_book").read_bytes() == before


def test_a_second_call_never_makes_a_second_book(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    client.post("/books/sample")
    assert lib.list_book_slugs() == ["sample_book"]


# ── the atomic-write rule ────────────────────────────────────────────────────

def test_ir_is_written_atomically(client, sandbox, monkeypatch):
    """Same guard as tests/test_pipeline.py: a plain `open(ir.json, 'w')` is how
    a crash mid-write destroys attribution labor, so no path may take it."""
    ir_path = str(lib.ir_path("sample_book"))
    real_open = builtins.open

    def guarded(file, mode="r", *a, **kw):
        if str(file) == ir_path and any(m in mode for m in "wxa"):
            raise AssertionError(f"plain write of ir.json: open({file!r}, {mode!r})")
        return real_open(file, mode, *a, **kw)

    calls = []
    real_atomic = lib.write_json_atomic
    monkeypatch.setattr(lib, "write_json_atomic",
                        lambda p, d: (calls.append(str(p)), real_atomic(p, d))[1])
    monkeypatch.setattr(builtins, "open", guarded)
    try:
        job = _wait(client, client.post("/books/sample").json()["job_id"])
    finally:
        monkeypatch.setattr(builtins, "open", real_open)
    assert job["status"] == "done", job
    assert ir_path in calls, "ir.json was never written through write_json_atomic"


# ── keeping the wizard's fixtures honest ─────────────────────────────────────
#
# tests/ui/check_first_run.py drives the overlay with these files. They are
# generated from the live endpoints by scripts/refresh_ui_fixtures.py, and the
# probe's machine-dependent inputs are pinned the same way on both sides (see
# tests/synthetic.py). Regenerate them when a response shape changes on
# purpose, rather than hand-editing, or the headless check goes back to testing
# a fiction.

FIXTURES = Path(__file__).parent / "fixtures"

from prosecast import config as _config      # noqa: E402
from prosecast import setup_probe as _sp     # noqa: E402
from synthetic import pin_config, pin_machine, pin_status  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch):
    """No env var from the developer's shell reaches the probes."""
    for env_var, _default, _secret in _config.SCHEMA.values():
        monkeypatch.delenv(env_var, raising=False)
    _config.invalidate()
    yield
    _config.invalidate()


@pytest.fixture
def pinned(clean_env):
    """Pin the machine the way the generator does, then put the module back."""
    real = (_sp._OS, _sp._which, _sp.probe_ollama, _sp.probe_whisper)
    yield pin_machine
    _sp._OS, _sp._which, _sp.probe_ollama, _sp.probe_whisper = real


def test_firstrun_fixtures_still_match_these_endpoints(client, sandbox, pinned):
    pinned(_sp, os_name="Darwin", ollama_ok=False, whisper_ok=False)
    live = pin_status(client.get("/setup/status").json())
    assert live == json.loads((FIXTURES / "setup_status_firstrun.json").read_text()), \
        "setup_status_firstrun.json has drifted from /setup/status — regenerate it"
    live_cfg = pin_config(client.get("/config").json())
    assert live_cfg == json.loads((FIXTURES / "config_firstrun.json").read_text()), \
        "config_firstrun.json has drifted from /config — regenerate it"


def test_ready_fixtures_still_match_these_endpoints(client, sandbox, pinned):
    client.put("/config", json={"values": {"tts_engine": "say"}})
    pinned(_sp, os_name="Darwin", ollama_ok=True, whisper_ok=True)
    live = pin_status(client.get("/setup/status").json())
    assert live == json.loads((FIXTURES / "setup_status_ready.json").read_text()), \
        "setup_status_ready.json has drifted from /setup/status — regenerate it"
    live_cfg = pin_config(client.get("/config").json())
    assert live_cfg == json.loads((FIXTURES / "config_ready.json").read_text()), \
        "config_ready.json has drifted from /config — regenerate it"


def test_sample_fixture_still_matches_this_endpoint(client, sandbox):
    live = client.post("/books/sample").json()
    live["job_id"] = "FIXTURE"
    assert live == json.loads((FIXTURES / "sample_book.json").read_text()), \
        "sample_book.json has drifted from /books/sample — regenerate it"
