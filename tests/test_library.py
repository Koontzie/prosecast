"""
E11 — the shelf chapter: hide / rename / remove a book without ever writing
ir.json, voice_map.json or corrections.jsonl.

shelf.json lives next to ir.json but is disposable view state (see
lib.read_shelf's docstring) — kept separate specifically so the render
worker's whole-document IR write (HANDOFF finding 2) can never clobber a
hide/rename/remove. Removal moves the book directory into library/.trash/;
nothing under library/ is ever actually deleted.

Offline and hermetic, like tests/test_sample_book.py: tmp library, no real
book ever touched.
"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from prosecast import library as lib  # noqa: E402
from synthetic import study_ir  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(lib, "TRASH_DIR", tmp_path / "library" / ".trash")
    yield tmp_path


@pytest.fixture
def client(sandbox):
    return TestClient(server.app)


def make_book(slug: str, title: str = "The Study") -> Path:
    lib.ensure_book_dir(slug)
    ir = study_ir()
    ir["book_title"] = title
    lib.write_json_atomic(lib.ir_path(slug), ir)
    (lib.voice_map_path(slug)).write_text("{}", encoding="utf-8")
    return lib.book_dir(slug)


# ── shelf round-trip ─────────────────────────────────────────────────────────

def test_read_shelf_defaults_when_missing(sandbox):
    make_book("bookone")
    shelf = lib.read_shelf("bookone")
    assert shelf == {"hidden": False, "pinned": False, "sort_index": None,
                      "display_title": None}


def test_write_then_read_shelf_round_trips(sandbox):
    make_book("bookone")
    lib.write_shelf("bookone", {"hidden": True, "pinned": False,
                                 "sort_index": None, "display_title": "Renamed"})
    shelf = lib.read_shelf("bookone")
    assert shelf["hidden"] is True
    assert shelf["display_title"] == "Renamed"


def test_read_shelf_never_raises_on_garbage(sandbox):
    make_book("bookone")
    lib.shelf_path("bookone").write_text("not json{{{", encoding="utf-8")
    assert lib.read_shelf("bookone") == {"hidden": False, "pinned": False,
                                          "sort_index": None, "display_title": None}


# ── list_book_slugs() and the .trash glob ───────────────────────────────────

def test_trashed_book_invisible_to_list_book_slugs(sandbox):
    d = make_book("bookone")
    lib.TRASH_DIR.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.move(str(d), str(lib.TRASH_DIR / "bookone__20260911T000000Z"))
    assert "bookone" not in lib.list_book_slugs()
    # the glob really is one level deep — a trashed book's ir.json is two
    # levels below LIBRARY_DIR and never matches `*/ir.json`
    assert (lib.TRASH_DIR / "bookone__20260911T000000Z" / "ir.json").exists()


# ── GET /books ───────────────────────────────────────────────────────────────

def test_books_omits_hidden_by_default(client, sandbox):
    make_book("bookone")
    make_book("booktwo")
    client.patch("/books/booktwo/shelf", json={"hidden": True})
    slugs = [b["slug"] for b in client.get("/books").json()]
    assert slugs == ["bookone"]


def test_books_include_hidden_reveals_it(client, sandbox):
    make_book("bookone")
    make_book("booktwo")
    client.patch("/books/booktwo/shelf", json={"hidden": True})
    books = {b["slug"]: b for b in client.get("/books?include_hidden=true").json()}
    assert set(books) == {"bookone", "booktwo"}
    assert books["booktwo"]["hidden"] is True
    assert books["bookone"]["hidden"] is False


def test_books_sorts_pinned_first_then_title(client, sandbox):
    make_book("zzz", title="Zzz Book")
    make_book("aaa", title="Aaa Book")
    client.patch("/books/zzz/shelf", json={"pinned": True})
    slugs = [b["slug"] for b in client.get("/books").json()]
    assert slugs == ["zzz", "aaa"]


def test_display_title_overrides_without_touching_ir_json(client, sandbox):
    d = make_book("bookone", title="Original Title")
    ir_path = lib.ir_path("bookone")
    before_bytes = ir_path.read_bytes()
    before_mtime = ir_path.stat().st_mtime_ns

    client.patch("/books/bookone/shelf", json={"display_title": "A New Name"})

    books = {b["slug"]: b for b in client.get("/books").json()}
    assert books["bookone"]["title"] == "A New Name"
    assert ir_path.read_bytes() == before_bytes
    assert ir_path.stat().st_mtime_ns == before_mtime


def test_empty_display_title_clears_the_override(client, sandbox):
    make_book("bookone", title="Original Title")
    client.patch("/books/bookone/shelf", json={"display_title": "Renamed"})
    r = client.patch("/books/bookone/shelf", json={"display_title": None})
    assert r.status_code == 200
    books = {b["slug"]: b for b in client.get("/books").json()}
    assert books["bookone"]["title"] == "Original Title"


def test_shelf_rejects_bad_types(client, sandbox):
    make_book("bookone")
    assert client.patch("/books/bookone/shelf", json={"hidden": "yes"}).status_code == 400
    assert client.patch("/books/bookone/shelf",
                         json={"display_title": "x" * 201}).status_code == 400
    assert client.patch("/books/bookone/shelf", json={"display_title": ""}).status_code == 400


def test_shelf_unknown_slug_404s(client, sandbox):
    assert client.patch("/books/nope/shelf", json={"hidden": True}).status_code == 404


def test_title_with_quote_and_angle_bracket_round_trips(client, sandbox):
    make_book("bookone", title="Carl's <Rulebook>")
    books = {b["slug"]: b for b in client.get("/books").json()}
    assert books["bookone"]["title"] == "Carl's <Rulebook>"


# ── DELETE /books/{slug} — move, never delete ────────────────────────────────

def test_delete_moves_to_trash_not_deletes(client, sandbox):
    make_book("bookone")
    r = client.delete("/books/bookone")
    assert r.status_code == 200
    trashed = r.json()["trashed"]
    assert trashed.startswith("bookone__")
    trash_dir = lib.TRASH_DIR / trashed
    assert (trash_dir / "ir.json").exists()
    assert (trash_dir / "voice_map.json").exists()
    assert not lib.book_dir("bookone").exists()
    assert "bookone" not in lib.list_book_slugs()


def test_delete_unknown_slug_404s(client, sandbox):
    assert client.delete("/books/nope").status_code == 404


def test_delete_refuses_409_while_a_job_is_live(client, sandbox):
    make_book("bookone")
    server._render_jobs["job-1"] = {
        "job_id": "job-1", "kind": "render", "book_slug": "bookone", "status": "running",
    }
    try:
        r = client.delete("/books/bookone")
        assert r.status_code == 409
        assert "render" in r.json()["detail"]
        assert lib.book_dir("bookone").exists()
    finally:
        server._render_jobs.pop("job-1", None)


def test_delete_allows_when_job_is_terminal(client, sandbox):
    make_book("bookone")
    server._render_jobs["job-1"] = {
        "job_id": "job-1", "kind": "render", "book_slug": "bookone", "status": "done",
    }
    try:
        r = client.delete("/books/bookone")
        assert r.status_code == 200
    finally:
        server._render_jobs.pop("job-1", None)


def test_moved_back_returns_to_the_library(client, sandbox):
    make_book("bookone")
    trashed = client.delete("/books/bookone").json()["trashed"]
    import shutil
    shutil.move(str(lib.TRASH_DIR / trashed), str(lib.book_dir("bookone")))
    slugs = [b["slug"] for b in client.get("/books").json()]
    assert "bookone" in slugs


# ── keeping tests/ui/check_library_menu.py's fixture honest ────────────────
#
# books_library.json comes from the live GET /books?include_hidden=true via
# scripts/refresh_ui_fixtures.py, built on the same "study" book synthetic.py
# feeds the other drift tests, renamed and pinned — plus the sample book,
# hidden. A hand-written mock could stay kinder than the endpoint forever;
# this proves it hasn't.

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_books_library_fixture_still_matches_this_endpoint(client, sandbox):
    import json as _json
    make_book("study", title="The Study")
    make_book("sample_book", title="Sample Book")
    client.patch("/books/study/shelf",
                 json={"pinned": True, "display_title": "Carl's <Rulebook>"})
    client.patch("/books/sample_book/shelf", json={"hidden": True})
    live = client.get("/books?include_hidden=true").json()
    saved = _json.loads((FIXTURES / "books_library.json").read_text())
    live_by_slug = {b["slug"]: b for b in live}
    saved_by_slug = {b["slug"]: b for b in saved}
    for slug in ("study", "sample_book"):
        for field in ("hidden", "pinned"):
            assert live_by_slug[slug][field] == saved_by_slug[slug][field], (
                f"books_library.json has drifted from /books — regenerate it ({slug}.{field})")
    assert live_by_slug["study"]["title"] == saved_by_slug["study"]["title"], \
        "books_library.json has drifted from /books — regenerate it (study.title)"
