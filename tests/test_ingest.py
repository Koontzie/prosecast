"""
Phase E2.1 — upload as a job: prepare/run, the three modes, and the two
endpoints that replaced the one-step upload.

Offline and hermetic: tiny fixtures, PDFs built in-test with PyMuPDF, a tmp
library and a tmp books/ dir. No Gideon, no network, no copyrighted files.
"""
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

from synthetic import NOVEL, PLAY, RULEBOOK, build_pdf  # noqa: E402


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
    server._uploads.clear()
    return TestClient(server.app)


def _txt(sandbox, name, body):
    p = sandbox / "books" / name
    p.write_text(body, encoding="utf-8")
    return p


def _pdf(sandbox, name="rules.pdf", **kw):
    pytest.importorskip("pymupdf")
    return build_pdf(sandbox / "books" / name, **kw)


def _wait(client, job_id, timeout=90):
    t0 = time.time()
    job = None
    while time.time() - t0 < timeout:
        job = client.get(f"/render_status/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"ingest job {job_id} never finished: {job}")


# ── naming ───────────────────────────────────────────────────────────────────

def test_slug_never_collides(sandbox):
    lib.ensure_book_dir("a_nice_book")
    assert ingest.slug_for("A Nice Book") == "a_nice_book_2"
    lib.ensure_book_dir("a_nice_book_2")
    assert ingest.slug_for("A Nice Book") == "a_nice_book_3"


def test_slug_matches_the_old_derivation(sandbox):
    assert ingest.slug_for("Brigands & Breadknives") == "brigands___breadknives"
    assert ingest.base_slug("") == "book"


def test_upload_path_never_clobbers_an_earlier_file(sandbox):
    first = ingest.unique_upload_path("My Book.epub", sandbox / "books")
    first.write_bytes(b"one")
    second = ingest.unique_upload_path("My Book.epub", sandbox / "books")
    assert second.name == "My_Book_2.epub"
    assert first.read_bytes() == b"one"


# ── prepare: format gate + mode guess ────────────────────────────────────────

def test_prepare_rejects_unsupported_format(sandbox):
    p = _txt(sandbox, "notes.docx", "not a book")
    with pytest.raises(ingest.IngestError) as e:
        ingest.prepare(p)
    assert ".epub" in str(e.value) and ".docx" in str(e.value)


def test_epub_is_guessed_as_a_novel():
    mode, why = ingest.guess_mode(".epub")
    assert mode == "novel" and "EPUB" in why


def test_prose_without_speaker_labels_guesses_narrator(sandbox):
    info = ingest.prepare(_txt(sandbox, "rules.txt", RULEBOOK))
    assert info["guess_mode"] == "narrator"
    assert info["format"] == ".txt" and info["title"] == "Rules"


def test_speaker_labels_guess_play(sandbox):
    info = ingest.prepare(_txt(sandbox, "scene.txt", PLAY))
    assert info["guess_mode"] == "play"
    assert "SPEAKER. labels" in info["guess_reason"]


def test_a_novels_dialogue_is_not_mistaken_for_a_script(sandbox):
    # "said Darcy" is not a speaker label; quoted dialogue must not trip the play check
    assert ingest.play_score(NOVEL)["is_play"] is False


# ── prepare: PDFs ────────────────────────────────────────────────────────────

def test_prepare_pdf_returns_a_reviewable_chapter_split(sandbox):
    info = ingest.prepare(_pdf(sandbox))
    det = info["detection"]
    assert det["source"] == "outline"
    assert [c["page"] for c in det["chapters"]] == [1, 3, 5]
    assert det["note"] and all("skip" in c for c in det["chapters"])
    assert info["is_scan"] is False


def test_prepare_flags_a_scan_instead_of_guessing(sandbox):
    info = ingest.prepare(_pdf(sandbox, "scanned.pdf", scan=True))
    assert info["is_scan"] is True
    assert "OCR" in info["guess_reason"]
    assert info["scan"]["pages"] == 6


# ── run: the three modes ─────────────────────────────────────────────────────

def test_novel_mode_keeps_characters_and_dialogue(sandbox):
    out = ingest.run(_txt(sandbox, "novel.txt", NOVEL), "novel", title="Novel")
    ir = json.loads(lib.ir_path(out["slug"]).read_text())
    assert out["chapters"] == 1
    kinds = {b["type"] for c in ir["chapters"] for b in c["blocks"]}
    assert "dialogue" in kinds
    assert "Darcy" in ir["characters"]


def test_narrator_mode_flattens_every_block_to_one_voice(sandbox):
    out = ingest.run(_txt(sandbox, "rules.txt", RULEBOOK), "narrator", title="Rules")
    ir = json.loads(lib.ir_path(out["slug"]).read_text())
    blocks = [b for c in ir["chapters"] for b in c["blocks"]]
    assert ir["characters"] == []
    assert {b["speaker"] for b in blocks} == {"NARRATOR"}
    assert {b["attribution_method"] for b in blocks} == {"single_narrator"}


def test_play_mode_attributes_by_speaker_label(sandbox):
    out = ingest.run(_txt(sandbox, "scene.txt", PLAY), "play", title="Scene")
    ir = json.loads(lib.ir_path(out["slug"]).read_text())
    dialogue = [b for c in ir["chapters"] for b in c["blocks"] if b["type"] == "dialogue"]
    assert {"AGNES", "TILLY"} <= set(ir["characters"])
    assert all(b["confidence"] == 1.0 and not b["unresolved"] for b in dialogue)
    assert all(b["attribution_method"] == "script_format" for b in dialogue)
    assert ir["unresolved_count"] == 0


def test_unknown_mode_is_refused(sandbox):
    with pytest.raises(ingest.IngestError):
        ingest.run(_txt(sandbox, "x.txt", RULEBOOK), "opera", title="X")


def test_run_records_how_the_book_got_here(sandbox):
    out = ingest.run(_txt(sandbox, "rules.txt", RULEBOOK), "narrator", title="Rules")
    prov = json.loads(lib.ir_path(out["slug"]).read_text())["ingest"]
    assert prov["mode"] == "narrator"
    assert prov["source"] == "rules.txt" and prov["format"] == ".txt"
    assert prov["at"]


def test_run_reports_every_stage_in_order(sandbox):
    seen = []
    ingest.run(_txt(sandbox, "rules.txt", RULEBOOK), "narrator", title="Rules",
               progress=lambda stage, detail="": seen.append(stage))
    assert seen[0] == "extracting" and seen[-1] == "done"
    assert [s for s in ingest.STAGES if s in seen] == list(ingest.STAGES)


# ── run: PDFs ────────────────────────────────────────────────────────────────

def test_pdf_run_honours_the_reviewed_split(sandbox):
    pdf = _pdf(sandbox)
    reviewed = ingest.prepare(pdf)["detection"]["chapters"]
    reviewed[0]["title"] = "Renamed Opening"
    reviewed[1]["skip"] = True                       # user drops the middle chapter
    out = ingest.run(pdf, "narrator", slug="reviewed", title="Reviewed", chapters=reviewed)
    titles = [c["title"] for c in json.loads(lib.ir_path("reviewed").read_text())["chapters"]]
    assert out["chapters"] == 2
    assert any("Renamed Opening" in t for t in titles)
    assert not any("Story 2" in t for t in titles)


def test_pdf_run_refuses_a_scan_with_a_usable_message(sandbox):
    with pytest.raises(ingest.IngestError) as e:
        ingest.run(_pdf(sandbox, "scanned.pdf", scan=True), "narrator", title="Scanned")
    msg = str(e.value)
    assert "scan" in msg and "OCR" in msg and "tesseract" in msg


# ── endpoints ────────────────────────────────────────────────────────────────

def test_upload_inspects_and_does_not_ingest(client, sandbox):
    r = client.post("/books/upload", files={"file": ("Scene One.txt", PLAY.encode())})
    assert r.status_code == 200
    body = r.json()
    assert body["guess_mode"] == "play"
    assert body["format"] == ".txt" and body["upload_id"]
    assert body["modes"] == list(ingest.MODES)
    assert lib.list_book_slugs() == []                # nothing ingested yet
    assert (sandbox / "books" / "Scene_One.txt").exists()


def test_upload_rejects_an_unreadable_format(client):
    r = client.post("/books/upload", files={"file": ("notes.docx", b"nope")})
    assert r.status_code == 400
    assert ".epub" in r.json()["detail"]


def test_ingest_runs_as_a_job_and_lands_a_book(client):
    up = client.post("/books/upload",
                     files={"file": ("Scene One.txt", PLAY.encode())}).json()
    started = client.post("/books/ingest", json={"upload_id": up["upload_id"]}).json()
    assert started["mode"] == "play"                  # guess accepted by default
    job = _wait(client, started["job_id"])
    assert job["status"] == "done" and job["kind"] == "ingest"
    assert job["stage"] == "done" and job["progress"] == job["total"]
    assert job["result"]["slug"] == started["slug"]
    assert started["slug"] in lib.list_book_slugs()
    assert any(b["slug"] == started["slug"] for b in client.get("/books").json())


def test_ingest_honours_an_explicit_mode(client):
    up = client.post("/books/upload",
                     files={"file": ("Scene One.txt", PLAY.encode())}).json()
    started = client.post("/books/ingest",
                          json={"upload_id": up["upload_id"], "mode": "narrator"}).json()
    _wait(client, started["job_id"])
    ir = json.loads(lib.ir_path(started["slug"]).read_text())
    assert ir["ingest"]["mode"] == "narrator" and ir["characters"] == []


def test_the_same_file_twice_makes_two_books(client):
    slugs = []
    for _ in range(2):
        up = client.post("/books/upload",
                         files={"file": ("Rules.txt", RULEBOOK.encode())}).json()
        started = client.post("/books/ingest", json={"upload_id": up["upload_id"]}).json()
        _wait(client, started["job_id"])
        slugs.append(started["slug"])
    assert slugs[0] != slugs[1]
    assert sorted(lib.list_book_slugs()) == sorted(slugs)


def test_ingest_rejects_unknown_upload_and_unknown_mode(client):
    assert client.post("/books/ingest", json={"upload_id": "nope"}).status_code == 404
    up = client.post("/books/upload",
                     files={"file": ("Rules.txt", RULEBOOK.encode())}).json()
    bad = client.post("/books/ingest",
                      json={"upload_id": up["upload_id"], "mode": "opera"})
    assert bad.status_code == 400 and "opera" in bad.json()["detail"]


def test_ingest_refuses_a_scan_up_front(client, sandbox):
    pdf = _pdf(sandbox, "scanned.pdf", scan=True)
    up = client.post("/books/upload",
                     files={"file": ("scanned.pdf", pdf.read_bytes())}).json()
    assert up["is_scan"] is True
    r = client.post("/books/ingest", json={"upload_id": up["upload_id"]})
    assert r.status_code == 400
    assert "OCR" in r.json()["detail"]
    assert lib.list_book_slugs() == []


def test_a_failing_ingest_reports_the_reason_not_a_traceback(client, sandbox, monkeypatch):
    up = client.post("/books/upload",
                     files={"file": ("Rules.txt", RULEBOOK.encode())}).json()

    def boom(*a, **k):
        raise ingest.IngestError("No chapters found in 'Rules.txt'.")
    monkeypatch.setattr(ingest, "run", boom)

    started = client.post("/books/ingest", json={"upload_id": up["upload_id"]}).json()
    job = _wait(client, started["job_id"])
    assert job["status"] == "error"
    assert job["error"] == "No chapters found in 'Rules.txt'."
    assert lib.list_book_slugs() == []


# ── keeping the wizard's fixtures honest ─────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"


def _upload_fixture(client, name, data):
    body = client.post("/books/upload", files={"file": (name, data)}).json()
    body["upload_id"] = "FIXTURE"          # random per call; pinned in the file
    return body


@pytest.mark.parametrize("fixture,name,payload", [
    ("upload_play_txt.json", "Scene One.txt", None),
    ("upload_pdf.json", "The Rulebook.pdf", "pdf"),
    ("upload_scan_pdf.json", "Scanned.pdf", "scan"),
])
def test_wizard_fixtures_still_match_this_endpoint(client, sandbox, fixture, name, payload):
    """`tests/ui/check_ingest_wizard.py` drives the wizard with these files.
    They are generated from POST /books/upload by scripts/refresh_ui_fixtures.py —
    regenerate them when the response shape changes on purpose, rather than
    hand-editing, or the headless check goes back to testing a fiction.
    """
    if payload == "pdf":
        data = build_pdf(sandbox / "gen.pdf").read_bytes()
    elif payload == "scan":
        data = build_pdf(sandbox / "gen_scan.pdf", scan=True).read_bytes()
    else:
        data = PLAY.encode()
    live = _upload_fixture(client, name, data)
    saved = json.loads((FIXTURES / fixture).read_text())
    assert live == saved, f"{fixture} has drifted from /books/upload — regenerate it"
