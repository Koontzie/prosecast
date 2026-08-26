"""Phase C2/C3 — queue sequencing, done-skip, force, preflight abort.

Offline: stub engine, real queue worker thread, tmp library.
"""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

import server
from prosecast import library as lib
from prosecast import renderer as renderer_mod


def _mk_book(root, slug, n_chapters=2, n_blocks=2):
    d = root / slug
    d.mkdir(parents=True)
    chapters = []
    for c in range(n_chapters):
        blocks = []
        for b in range(n_blocks):
            blocks.append({
                "segmentId": f"ch{c}_seg_{b:04d}", "type": "narration",
                "text": f"Chapter {c} block {b} text.", "speaker": "NARRATOR",
                "confidence": 1.0, "unresolved": False,
                "attribution_method": "narration",
                "audioVariants": {"standard": {"url": None, "cached": False},
                                  "premium": {"url": None, "cached": False}},
                "selectedVariant": "standard", "cacheKey": None,
            })
        chapters.append({"index": c, "title": f"Ch {c}", "blocks": blocks})
    ir = {"book_title": slug, "unresolved_count": 0, "chapters": chapters,
          "characters": []}
    (d / "ir.json").write_text(json.dumps(ir))
    (d / "voice_map.json").write_text(json.dumps(
        {"engine": "stub", "map": {"NARRATOR": "stub-voice"}}))
    return slug


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    monkeypatch.setattr(server, "_active_engine", "stub")
    return TestClient(server.app)


def _wait(client, job_id, timeout=15):
    job = None
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = client.get(f"/render_status/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} never finished: {job}")


def test_jobs_run_sequentially_never_overlap(client, tmp_path, monkeypatch):
    slug_a = _mk_book(tmp_path, "qbook_a")
    slug_b = _mk_book(tmp_path, "qbook_b")

    active = {"count": 0, "max": 0}
    lock = threading.Lock()
    real = renderer_mod.render_chapter

    def tracked(*args, **kwargs):
        with lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        try:
            time.sleep(0.05)  # widen the overlap window
            return real(*args, **kwargs)
        finally:
            with lock:
                active["count"] -= 1

    monkeypatch.setattr(renderer_mod, "render_chapter", tracked)
    ja = client.post(f"/render/{slug_a}").json()["job_id"]
    jb = client.post(f"/render/{slug_b}").json()["job_id"]
    a = _wait(client, ja)
    b = _wait(client, jb)
    assert a["status"] == "done", a
    assert b["status"] == "done", b
    assert active["max"] == 1, "two render jobs overlapped on the single GPU worker"


def test_queue_position_reported(client, tmp_path):
    slug = _mk_book(tmp_path, "qbook_pos", n_chapters=1)
    j1 = client.post(f"/render/{slug}").json()["job_id"]
    j2 = client.post(f"/render/{slug}").json()["job_id"]
    st = client.get(f"/render_status/{j2}").json()
    assert "queue_position" in st
    _wait(client, j1)
    _wait(client, j2)


def test_done_chapters_skip_and_force_rerenders(client, tmp_path):
    slug = _mk_book(tmp_path, "qbook_skip", n_chapters=2)
    j1 = _wait(client, client.post(f"/render/{slug}").json()["job_id"])
    assert j1["status"] == "done"
    assert all(not c["skipped"] and c["rendered"] > 0
               for c in j1["chapter_results"])

    j2 = _wait(client, client.post(f"/render/{slug}").json()["job_id"])
    assert all(c["skipped"] for c in j2["chapter_results"]), j2

    j3 = _wait(client, client.post(f"/render/{slug}?force=true").json()["job_id"])
    assert all(not c["skipped"] and c["rendered"] > 0
               for c in j3["chapter_results"]), j3


def test_preflight_abort_stops_job_loudly(client, tmp_path):
    slug = _mk_book(tmp_path, "qbook_abort")
    (tmp_path / slug / "voice_map.json").unlink()
    job = _wait(client, client.post(f"/render/{slug}").json()["job_id"])
    assert job["status"] == "aborted"
    assert "voice_map" in job["error"]
    assert not lib.chapter_wav_path(slug, 0).exists(), \
        "aborted job must not have rendered anything"


def test_engine_mismatch_aborts(client, tmp_path):
    slug = _mk_book(tmp_path, "qbook_mismatch")
    (tmp_path / slug / "voice_map.json").write_text(json.dumps(
        {"engine": "elevenlabs", "map": {"NARRATOR": "EXAVITQu4vr4xnSDxMaL"}}))
    job = _wait(client, client.post(f"/render/{slug}").json()["job_id"])
    assert job["status"] == "aborted"
    assert "elevenlabs" in job["error"]


def test_render_state_snapshot_written(client, tmp_path):
    slug = _mk_book(tmp_path, "qbook_state", n_chapters=1)
    _wait(client, client.post(f"/render/{slug}").json()["job_id"])
    state = json.loads((tmp_path / slug / "render_state.json").read_text())
    assert state["jobs"][-1]["status"] == "done"
    assert state["jobs"][-1]["chapter_results"]
