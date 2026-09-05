"""
Pipeline endpoints — the second worker, the honest refusals, the auto-chain.

Offline: the probes are patched (nothing reaches Ollama or whisper) and the
render side uses the stub engine, exactly like tests/test_render_queue.py.

The refusals are the point of most of this file. An "AI pass" button that
silently does nothing because Ollama is unreachable is the failure this whole
phase exists to avoid, so the server must say so in the probe's own words even
though the UI already disables the button.
"""

import importlib.util
import json
import queue
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from prosecast import library as lib
from prosecast import pipeline as pipe
from prosecast import setup_probe as sp

import synthetic


def _mk_book(root, slug, n_chapters=2, n_blocks=2, unresolved=1):
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
        for u in range(unresolved):
            blocks.append({
                "segmentId": f"ch{c}_seg_9{u:03d}", "type": "dialogue",
                "text": '"Who said that?"', "speaker": "UNKNOWN",
                "confidence": 0.0, "unresolved": True,
                "attribution_method": "unresolved",
                "audioVariants": {"standard": {"url": None, "cached": False},
                                  "premium": {"url": None, "cached": False}},
                "selectedVariant": "standard", "cacheKey": None,
            })
        chapters.append({"index": c, "title": f"Ch {c}", "blocks": blocks})
    ir = {"book_title": slug, "unresolved_count": n_chapters * unresolved,
          "chapters": chapters, "characters": []}
    (d / "ir.json").write_text(json.dumps(ir))
    (d / "voice_map.json").write_text(json.dumps(
        {"engine": "stub", "map": {"NARRATOR": "stub-voice", "UNKNOWN": "stub-voice"}}))
    return slug


def _row(ok, fix="", detail="not responding"):
    return {"key": "x", "label": "x", "ok": ok, "state": "ok" if ok else "missing",
            "detail": detail, "fix": fix, "optional": True}


OLLAMA_FIX = "Install Ollama from ollama.com and start it."
WHISPER_FIX = "Run a faster-whisper server (OpenAI-compatible) and set its URL."


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    monkeypatch.setattr(server, "_active_engine", "stub")
    server._render_jobs.clear()          # jobs are a module global; don't inherit
    return TestClient(server.app)


@pytest.fixture
def services_up(monkeypatch):
    monkeypatch.setattr(sp, "probe_ollama", lambda: _row(True))
    monkeypatch.setattr(sp, "probe_whisper", lambda: _row(True))


@pytest.fixture
def frozen(monkeypatch):
    """Jobs enqueue but never start, so a test can inspect the queue.

    A fresh Queue object rather than only a no-op `_ensure_pipeline_worker`:
    an earlier test may already have started the real worker thread, and it
    would happily consume from the shared one.
    """
    monkeypatch.setattr(server, "_pipeline_queue", queue.Queue())
    monkeypatch.setattr(server, "_pipeline_order", [])
    monkeypatch.setattr(server, "_ensure_pipeline_worker", lambda: None)


def _wait(client, job_id, timeout=15):
    t0 = time.time()
    job = None
    while time.time() - t0 < timeout:
        job = client.get(f"/render_status/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} never finished: {job}")


# ── refusals in the probe's own words ────────────────────────────────────────

def test_ai_pass_refused_with_the_fix_when_ollama_is_down(client, tmp_path, monkeypatch):
    slug = _mk_book(tmp_path, "pbook_down")
    monkeypatch.setattr(sp, "probe_ollama", lambda: _row(False, OLLAMA_FIX))
    r = client.post(f"/pipeline/{slug}/ai_pass", json={"scope": "unresolved"})
    assert r.status_code == 409
    assert OLLAMA_FIX in r.json()["detail"]
    assert not any(j.get("kind") == "ai_pass" for j in server._render_jobs.values())


def test_align_refused_with_the_fix_when_whisper_is_down(client, tmp_path, monkeypatch):
    slug = _mk_book(tmp_path, "pbook_nowhisper")
    monkeypatch.setattr(sp, "probe_whisper", lambda: _row(False, WHISPER_FIX))
    r = client.post(f"/pipeline/{slug}/align", json={})
    assert r.status_code == 409
    assert WHISPER_FIX in r.json()["detail"]


def test_unknown_book_and_unknown_scope_are_refused(client, tmp_path, services_up):
    slug = _mk_book(tmp_path, "pbook_scope")
    assert client.post("/pipeline/nope/ai_pass", json={}).status_code == 404
    assert client.get("/pipeline/nope").status_code == 404
    r = client.post(f"/pipeline/{slug}/ai_pass", json={"scope": "everything"})
    assert r.status_code == 400 and "scope" in r.json()["detail"]


# ── enqueue, poll, dedup ─────────────────────────────────────────────────────

def test_ai_pass_runs_on_the_pipeline_worker_and_polls_like_a_render(
        client, tmp_path, services_up, monkeypatch):
    slug = _mk_book(tmp_path, "pbook_run")
    result = {"targets": 2, "resolved": 2, "unresolved_after": 0,
              "aborted": False, "abort_reason": None}

    def fake_pass(s, *, scope, model, profile, job_id="", on_progress=None):
        assert s == slug and scope == "low-confidence" and profile is False
        on_progress("attributing", "scene 1 of 2", 1, 2)
        return result

    monkeypatch.setattr(pipe, "run_ai_pass", fake_pass)
    job_id = client.post(f"/pipeline/{slug}/ai_pass",
                         json={"scope": "low-confidence", "profile": False}
                         ).json()["job_id"]
    job = _wait(client, job_id)
    assert job["kind"] == "ai_pass"
    assert job["book_slug"] == slug
    assert job["status"] == "done"
    assert job["result"] == result
    assert job["stage"] == "attributing" and job["detail"] == "scene 1 of 2"
    assert job["progress"] == 1 and job["total"] == 2


def test_an_aborted_pass_is_done_with_the_reason_not_a_failure(
        client, tmp_path, services_up, monkeypatch):
    slug = _mk_book(tmp_path, "pbook_abort")
    monkeypatch.setattr(pipe, "run_ai_pass", lambda s, **k: {
        "targets": 9, "resolved": 3, "unresolved_after": 6,
        "aborted": True, "abort_reason": "Ollama stopped answering after 3 tries"})
    job_id = client.post(f"/pipeline/{slug}/ai_pass", json={}).json()["job_id"]
    job = _wait(client, job_id)
    assert job["status"] == "done"                    # the 3 it resolved are saved
    assert "Ollama stopped answering" in job["error"]
    assert job["result"]["aborted"] is True


def test_a_pipeline_error_becomes_a_failed_job_with_its_sentence(
        client, tmp_path, services_up, monkeypatch):
    slug = _mk_book(tmp_path, "pbook_err")

    def boom(s, **k):
        raise pipe.PipelineError("No book 'x' in the library.")

    monkeypatch.setattr(pipe, "run_ai_pass", boom)
    job_id = client.post(f"/pipeline/{slug}/ai_pass", json={}).json()["job_id"]
    job = _wait(client, job_id)
    assert job["status"] == "error" and "library" in job["error"]


def test_a_second_request_returns_the_running_job_not_a_duplicate(
        client, tmp_path, services_up, frozen):
    slug = _mk_book(tmp_path, "pbook_dup")
    first = client.post(f"/pipeline/{slug}/ai_pass", json={}).json()["job_id"]
    second = client.post(f"/pipeline/{slug}/ai_pass", json={}).json()["job_id"]
    assert first == second
    assert sum(1 for j in server._render_jobs.values() if j.get("kind") == "ai_pass") == 1


def test_align_requests_merge_into_a_job_that_has_not_started(
        client, tmp_path, services_up, frozen):
    slug = _mk_book(tmp_path, "pbook_merge")
    a = client.post(f"/pipeline/{slug}/align", json={"chapters": [0]}).json()["job_id"]
    b = client.post(f"/pipeline/{slug}/align", json={"chapters": [1]}).json()["job_id"]
    assert a == b
    assert server._render_jobs[a]["params"]["chapters"] == [0, 1]


def test_align_jobs_are_per_book(client, tmp_path, services_up, frozen):
    one = _mk_book(tmp_path, "pbook_one")
    two = _mk_book(tmp_path, "pbook_two")
    a = client.post(f"/pipeline/{one}/align", json={"chapters": [0]}).json()["job_id"]
    b = client.post(f"/pipeline/{two}/align", json={"chapters": [0]}).json()["job_id"]
    assert a != b


# ── the one call the card renders from ───────────────────────────────────────

def test_pipeline_overview_shape(client, tmp_path, monkeypatch):
    slug = _mk_book(tmp_path, "pbook_view", n_chapters=2, unresolved=2)
    monkeypatch.setattr(sp, "probe_ollama", lambda: _row(False, OLLAMA_FIX))
    monkeypatch.setattr(sp, "probe_whisper", lambda: _row(True))
    body = client.get(f"/pipeline/{slug}").json()

    assert body["slug"] == slug and body["chapters"] == 2
    assert body["ai_pass"]["unresolved"] == 4
    assert body["ai_pass"]["in_scope"]["unresolved"] == 4
    assert set(body["ai_pass"]["in_scope"]) == set(pipe.SCOPES)
    assert body["ai_pass"]["last_run"] is None          # never run
    assert body["align"]["per_chapter"] == [
        {"index": 0, "state": "no_blocks"}, {"index": 1, "state": "no_blocks"}]
    assert body["align"]["auto_chain"] is True
    assert body["ollama_ok"] is False and OLLAMA_FIX in body["ollama_fix"]
    assert body["whisper_ok"] is True and body["whisper_fix"] == ""
    assert body["running_job_id"] is None and body["render_running"] is False


def test_pipeline_overview_reports_the_running_job(client, tmp_path, services_up, frozen):
    slug = _mk_book(tmp_path, "pbook_running")
    job_id = client.post(f"/pipeline/{slug}/ai_pass", json={}).json()["job_id"]
    body = client.get(f"/pipeline/{slug}").json()
    assert body["running_job_id"] == job_id and body["running_kind"] == "ai_pass"


def test_pipeline_overview_carries_the_last_run_forward(
        client, tmp_path, services_up, monkeypatch):
    slug = _mk_book(tmp_path, "pbook_history")
    pipe.write_state(slug, "ai_pass", {
        "job_id": "old", "kind": "ai_pass", "stage": "done", "detail": "12 resolved",
        "done": 1, "total": 1, "started": 1.0, "updated": 2.0,
        "result": {"resolved": 12, "aborted": False}})
    body = client.get(f"/pipeline/{slug}").json()
    assert body["ai_pass"]["last_run"] == 2.0
    assert body["ai_pass"]["result"]["resolved"] == 12


# ── the auto-chain ───────────────────────────────────────────────────────────

def _align_jobs(slug):
    return [j for j in server._render_jobs.values()
            if j.get("kind") == "align" and j.get("book_slug") == slug]


def test_align_auto_chains_after_a_render_when_whisper_is_up(
        client, tmp_path, monkeypatch, frozen):
    slug = _mk_book(tmp_path, "pbook_chain")
    monkeypatch.setattr(sp, "probe_whisper", lambda: _row(True))
    job = client.post(f"/render/{slug}").json()["job_id"]
    _wait(client, job)

    jobs = _align_jobs(slug)
    assert len(jobs) == 1, "one merged align job, not one per chapter"
    assert jobs[0]["params"]["chapters"] == [0, 1]
    assert jobs[0]["status"] == "queued"          # queued, never run inline


def test_align_does_not_auto_chain_when_whisper_is_down(
        client, tmp_path, monkeypatch, frozen):
    slug = _mk_book(tmp_path, "pbook_nochain")
    monkeypatch.setattr(sp, "probe_whisper", lambda: _row(False, WHISPER_FIX))
    job = client.post(f"/render/{slug}").json()["job_id"]
    _wait(client, job)
    assert _align_jobs(slug) == []


def test_the_whisper_probe_runs_once_per_render_job_not_once_per_chapter(
        client, tmp_path, monkeypatch, frozen):
    slug = _mk_book(tmp_path, "pbook_probes", n_chapters=3)
    probes = []
    monkeypatch.setattr(sp, "probe_whisper",
                        lambda: (probes.append(1), _row(True))[1])
    _wait(client, client.post(f"/render/{slug}").json()["job_id"])
    assert len(probes) == 1, f"probed {len(probes)} times for 3 chapters"


# ── keeping the card's fixtures honest ───────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parent.parent


def _generator():
    """scripts/refresh_ui_fixtures.py, loaded by path (scripts/ is not a package).

    Imported rather than reimplemented so the probe rows this test pins are
    byte-identical to the ones the fixtures were generated with.
    """
    spec = importlib.util.spec_from_file_location(
        "refresh_ui_fixtures", ROOT / "scripts" / "refresh_ui_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("fixture,ollama_ok,whisper_ok", [
    ("pipeline_ready.json", True, True),
    ("pipeline_offline.json", False, False),
])
def test_pipeline_fixtures_still_match_this_endpoint(
        client, tmp_path, monkeypatch, fixture, ollama_ok, whisper_ok):
    """`tests/ui/check_pipeline_card.py` feeds these files to the page instead
    of a hand-written mock, which only helps while they are a true copy of what
    the server sends. If this fails the endpoint changed on purpose: re-run
    scripts/refresh_ui_fixtures.py rather than editing the JSON.

    The probe verdicts are pinned on both sides — whether this machine happens
    to run Ollama is not something a fixture may depend on.
    """
    gen = _generator()
    lib.ensure_book_dir("study")
    (tmp_path / "study" / "ir.json").write_text(json.dumps(synthetic.study_ir()))
    monkeypatch.setattr(sp, "probe_ollama", lambda: gen.probe_row(
        "ollama", "Who\'s speaking (local AI)", ollama_ok,
        "" if ollama_ok else gen.OLLAMA_FIX))
    monkeypatch.setattr(sp, "probe_whisper", lambda: gen.probe_row(
        "whisper", "Read-along timing (whisper)", whisper_ok,
        "" if whisper_ok else gen.WHISPER_FIX))

    live = client.get("/pipeline/study").json()
    saved = json.loads((FIXTURES / fixture).read_text())
    assert live == saved, f"{fixture} has drifted from /pipeline — regenerate it"
