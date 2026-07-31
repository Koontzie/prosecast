"""
Alias suggester + suggestion endpoints.

Suggester tests are pure. Endpoint tests reuse the tmp-library pattern from
test_cast_endpoints (lib paths monkeypatched; no real library data touched).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast.alias_suggester import suggest_merges, _tokens  # noqa: E402

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from prosecast import library as lib  # noqa: E402


def _ir(speakers):
    """speakers: {name: n_dialogue_blocks}"""
    blocks = []
    i = 0
    for name, n in speakers.items():
        for _ in range(n):
            blocks.append({"segmentId": f"s{i}", "type": "dialogue",
                           "text": f'"line {i}"', "speaker": name,
                           "confidence": 0.9, "unresolved": False,
                           "attribution_method": "context_tag"})
            i += 1
    return {"title": "T", "characters": list(speakers), "user_characters": [],
            "chapters": [{"title": "Ch 1", "blocks": blocks}]}


# ── suggester rules ───────────────────────────────────────────────────────────

def test_subset_rule_finds_astryx_family():
    ir = _ir({"Astryx": 30, "Astryx Arboren": 9, "Warn Astryx": 5, "Fern": 32})
    sugg = suggest_merges(ir)
    pairs = {(s["from_name"], s["into"]) for s in sugg}
    assert ("Astryx Arboren", "Astryx") in pairs
    assert ("Warn Astryx", "Astryx") in pairs
    # different-token names never suggested
    assert not any("Fern" in p for pair in pairs for p in pair)


def test_variant_rule_honorifics_and_case():
    ir = _ir({"Captain Fern": 4, "Fern": 40, "BLUEBRIAR": 2, "Bluebriar": 20})
    pairs = {(s["from_name"], s["into"]): s["reason"] for s in suggest_merges(ir)}
    assert pairs[("Captain Fern", "Fern")] == "same name"
    assert pairs[("BLUEBRIAR", "Bluebriar")] == "same name"


def test_higher_count_wins_as_target():
    ir = _ir({"Astryx": 3, "Astryx Arboren": 30})
    s = suggest_merges(ir)[0]
    assert s["into"] == "Astryx Arboren" and s["from_name"] == "Astryx"


def test_diminutives_not_suggested():
    """Bob/Bobby share no full token — deliberately out of scope (precision)."""
    ir = _ir({"Bob": 10, "Bobby": 8})
    assert suggest_merges(ir) == []


def test_short_anchor_tokens_do_not_fire():
    # 'Jo' ⊂ 'Jo An' would anchor on a 2-char token — suppressed
    ir = _ir({"Jo": 5, "Jo An": 3})
    assert suggest_merges(ir) == []


def test_narrator_and_unknown_excluded():
    ir = _ir({"NARRATOR": 50, "UNKNOWN": 5, "Fern": 10})
    assert suggest_merges(ir) == []


def test_honorific_stripping():
    assert _tokens("Captain Fern") == frozenset({"fern"})
    assert _tokens("The Old Master") == frozenset()


def test_impactful_suggestions_first():
    ir = _ir({"Fern": 40, "Captain Fern": 12, "Astryx": 30, "Warn Astryx": 2})
    sugg = suggest_merges(ir)
    assert sugg[0]["from_name"] == "Captain Fern"   # 12 lines > 2 lines


# ── endpoints ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    book = tmp_path / "sugg_test"
    book.mkdir()
    (book / "ir.json").write_text(
        json.dumps(_ir({"Astryx": 30, "Astryx Arboren": 9, "Fern": 32})),
        encoding="utf-8")
    return TestClient(server.app)


def test_suggestions_endpoint(client):
    r = client.get("/ir/sugg_test/cast/suggestions")
    assert r.status_code == 200
    sugg = r.json()["suggestions"]
    assert [(s["from_name"], s["into"]) for s in sugg] == [("Astryx Arboren", "Astryx")]


def test_dismiss_journals_and_hides(client, tmp_path):
    r = client.post("/ir/sugg_test/cast/suggestions/dismiss",
                    json={"from_name": "Astryx Arboren", "into": "Astryx"})
    assert r.status_code == 200
    assert client.get("/ir/sugg_test/cast/suggestions").json()["suggestions"] == []
    events = [json.loads(l) for l in
              (tmp_path / "sugg_test" / "corrections.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "merge_suggestion_dismissed"
    assert events[-1]["from"] == "Astryx Arboren"


def test_accepted_merge_removes_suggestion(client):
    r = client.post("/ir/sugg_test/cast/merge",
                    json={"from_names": ["Astryx Arboren"], "into": "Astryx"})
    assert r.status_code == 200
    assert client.get("/ir/sugg_test/cast/suggestions").json()["suggestions"] == []
