"""
Cast review endpoint tests — demote / merge / ranked cast.

Runs against a throwaway book in a tmp library (lib paths monkeypatched);
NEVER touches real library/ data. Requires fastapi's TestClient; skips if absent.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from prosecast import library as lib  # noqa: E402


def _mini_ir():
    def blk(seg, typ, text, speaker):
        return {"segmentId": seg, "type": typ, "text": text, "speaker": speaker,
                "confidence": 0.9, "unresolved": False, "attribution_method": "explicit_tag"}
    return {
        "title": "Cast Test",
        "characters": ["Alice", "Bob", "Bobby", "Gut Instinct"],
        "user_characters": [],
        "chapters": [{
            "title": "Ch 1",
            "blocks": [
                blk("s1", "narration", "It was a dark night full of narrative.", "NARRATOR"),
                blk("s2", "dialogue", '"Hello there, my old friend."', "Alice"),
                blk("s3", "dialogue", '"Well met indeed, and a fine evening."', "Bob"),
                blk("s4", "dialogue", '"I said something once, quietly."', "Bobby"),
                blk("s5", "dialogue", '"CRITICAL HIT DETECTED ON TARGET."', "Gut Instinct"),
                blk("s6", "dialogue", '"Another line for Alice to speak aloud."', "Alice"),
            ],
        }],
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    book = tmp_path / "cast_test"
    book.mkdir()
    (book / "ir.json").write_text(json.dumps(_mini_ir()), encoding="utf-8")
    return TestClient(server.app)


def _journal_events(tmp_path):
    p = tmp_path / "cast_test" / "corrections.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_cast_ranked(client):
    r = client.get("/ir/cast_test/cast")
    assert r.status_code == 200
    data = r.json()
    names = [c["name"] for c in data["characters"]]
    assert names[0] == "Alice"          # 2 blocks, ranked first
    assert set(names) == {"Alice", "Bob", "Bobby", "Gut Instinct"}
    assert data["characters"][0]["dialogue_count"] == 2


def test_demote_by_names_journals(client, tmp_path):
    r = client.post("/ir/cast_test/cast/demote", json={"names": ["Gut Instinct"]})
    assert r.status_code == 200
    assert r.json()["demoted"] == {"Gut Instinct": 1}

    ir = json.loads((tmp_path / "cast_test" / "ir.json").read_text())
    speakers = {b["speaker"] for b in ir["chapters"][0]["blocks"]}
    assert "Gut Instinct" not in speakers
    assert "Gut Instinct" not in ir["characters"]

    events = _journal_events(tmp_path)
    assert len(events) == 1
    assert events[0]["event"] == "character_demoted"
    assert events[0]["segment_ids"] == ["s5"]


def test_demote_by_threshold(client, tmp_path):
    # Everyone with <=1 block: Bob, Bobby, Gut Instinct. Alice (2) survives.
    r = client.post("/ir/cast_test/cast/demote", json={"max_blocks": 1})
    assert r.status_code == 200
    assert set(r.json()["demoted"]) == {"Bob", "Bobby", "Gut Instinct"}

    cast = client.get("/ir/cast_test/cast").json()
    assert [c["name"] for c in cast["characters"]] == ["Alice"]
    assert len(_journal_events(tmp_path)) == 3   # one journal event per demoted name


def test_merge_journals_alias_data(client, tmp_path):
    r = client.post("/ir/cast_test/cast/merge",
                    json={"from_names": ["Bobby"], "into": "Bob"})
    assert r.status_code == 200
    assert r.json()["merged"] == {"Bobby": 1}

    cast = client.get("/ir/cast_test/cast").json()
    by_name = {c["name"]: c["dialogue_count"] for c in cast["characters"]}
    assert by_name["Bob"] == 2          # absorbed Bobby's block
    assert "Bobby" not in by_name

    events = _journal_events(tmp_path)
    assert events[0]["event"] == "characters_merged"
    assert events[0]["from"] == "Bobby" and events[0]["into"] == "Bob"


def test_merge_into_self_rejected(client):
    r = client.post("/ir/cast_test/cast/merge",
                    json={"from_names": ["Bob"], "into": "Bob"})
    assert r.status_code == 400


def test_character_lines_with_context(client):
    r = client.get("/ir/cast_test/character/Alice/lines?limit=3")
    assert r.status_code == 200
    lines = r.json()["lines"]
    assert len(lines) == 2
    assert lines[0]["text"] == '"Hello there, my old friend."'
    assert lines[0]["chapter"] == "Ch 1"
    assert "context_before" in lines[0] and "context_after" in lines[0]


def test_merge_into_narrator_allowed(client, tmp_path):
    """POV books: the 'narrator' is sometimes a named character — merging a
    character INTO NARRATOR must work (distinct journal event from demote)."""
    r = client.post("/ir/cast_test/cast/merge",
                    json={"from_names": ["Bobby"], "into": "NARRATOR"})
    assert r.status_code == 200
    assert r.json()["merged"] == {"Bobby": 1}
    events = _journal_events(tmp_path)
    assert events[0]["event"] == "characters_merged"
    assert events[0]["into"] == "NARRATOR"


def test_narrator_cannot_be_demoted(client):
    r = client.post("/ir/cast_test/cast/demote", json={"names": ["NARRATOR"]})
    assert r.status_code == 200
    assert r.json()["demoted"] == {}
