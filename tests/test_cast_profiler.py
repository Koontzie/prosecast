"""
Cast profiler tests — offline (Ollama mocked). Covers the title layer, the
LLM layer's parsing/thresholding, excerpt spreading, incremental re-runs,
and profile exposure through /cast.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import cast_profiler as cp  # noqa: E402


def _ir(speakers, ctx=""):
    blocks = []
    i = 0
    for name, n in speakers.items():
        for _ in range(n):
            blocks.append({"segmentId": f"s{i}", "type": "dialogue",
                           "text": f'"line {i}"', "speaker": name,
                           "confidence": 0.9, "unresolved": False,
                           "attribution_method": "context_tag",
                           "context_before": ctx, "context_after": ""})
            i += 1
    return {"title": "T", "characters": list(speakers), "user_characters": [],
            "chapters": [{"title": "Ch 1", "blocks": blocks}]}


# ── title layer ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,gender", [
    ("Abbess Bluebriar", "feminine"), ("Brother Rhubarb", "masculine"),
    ("Mrs Hudson", "feminine"), ("Lord Vane", "masculine"),
])
def test_title_layer(name, gender):
    p = cp.profile_from_name(name)
    assert p["gender"] == gender and p["method"] == "title"


def test_title_layer_declines_plain_and_contradictory_names():
    assert cp.profile_from_name("Astryx") is None
    assert cp.profile_from_name("Fern") is None
    assert cp.profile_from_name("Mother Father Confessor") is None


# ── parsing ───────────────────────────────────────────────────────────────────

def test_parse_valid_profile():
    p = cp.parse_profile_response(
        '{"gender": "Feminine", "age": "adult", "voice_hints": "dry, clipped",'
        ' "confidence": 0.85, "evidence": "she snorted"}')
    assert p["gender"] == "feminine" and p["age"] == "adult"
    assert p["confidence"] == 0.85 and p["method"] == "llm"


def test_parse_bad_enums_normalize():
    p = cp.parse_profile_response(
        '{"gender": "male", "age": "teenager", "confidence": "high"}')
    assert p["gender"] == "ambiguous"     # 'male' not in enum — no silent guess
    assert p["age"] == "unknown"
    assert p["confidence"] == 0.0


def test_parse_think_blocks_and_garbage():
    p = cp.parse_profile_response(
        '<think>narration says his</think>{"gender": "masculine", "confidence": 0.8}')
    assert p["gender"] == "masculine"
    assert cp.parse_profile_response("The character seems female.") is None
    assert cp.parse_profile_response("") is None


# ── excerpt gathering ─────────────────────────────────────────────────────────

def test_excerpts_spread_across_book():
    ir = _ir({"Fern": 40}, ctx="She grinned.")
    ex = cp.gather_excerpts(ir, "Fern", limit=4)
    assert len(ex) == 4
    assert all("Fern:" in e and "She grinned." in e for e in ex)
    assert cp.gather_excerpts(ir, "Nobody") == []


# ── pass behavior ─────────────────────────────────────────────────────────────

def test_pass_title_hits_skip_llm(monkeypatch):
    ir = _ir({"Abbess Bluebriar": 5, "Astryx": 5})
    calls = []
    monkeypatch.setattr(cp, "_call_ollama", lambda *a, **k: calls.append(1) or
        '{"gender": "masculine", "age": "adult", "confidence": 0.9, "evidence": "his ear"}')
    cp.run_profile_pass(ir, model="fake:1b")
    profs = ir["character_profiles"]
    assert profs["Abbess Bluebriar"]["method"] == "title"
    assert profs["Astryx"]["gender"] == "masculine"
    assert len(calls) == 1                       # only Astryx cost a call


def test_pass_below_threshold_becomes_ambiguous(monkeypatch):
    ir = _ir({"Astryx": 5})
    monkeypatch.setattr(cp, "_call_ollama", lambda *a, **k:
        '{"gender": "feminine", "confidence": 0.3, "evidence": "weak"}')
    cp.run_profile_pass(ir, model="fake:1b", confidence_threshold=0.5)
    assert ir["character_profiles"]["Astryx"]["gender"] == "ambiguous"


def test_pass_incremental_and_reprofile(monkeypatch):
    ir = _ir({"Astryx": 5})
    ir["character_profiles"] = {"Astryx": {"gender": "masculine", "method": "llm",
                                           "confidence": 0.9, "age": "adult",
                                           "voice_hints": "", "evidence": "old"}}
    calls = []
    monkeypatch.setattr(cp, "_call_ollama", lambda *a, **k: calls.append(1) or
        '{"gender": "feminine", "confidence": 0.9, "evidence": "new"}')
    cp.run_profile_pass(ir, model="fake:1b")             # incremental: skip
    assert not calls
    cp.run_profile_pass(ir, model="fake:1b", reprofile=True)
    assert calls and ir["character_profiles"]["Astryx"]["gender"] == "feminine"


def test_pass_skips_walk_ons(monkeypatch):
    ir = _ir({"Astryx": 5, "Guard": 1})
    monkeypatch.setattr(cp, "_call_ollama", lambda *a, **k:
        '{"gender": "masculine", "confidence": 0.9, "evidence": "he"}')
    cp.run_profile_pass(ir, model="fake:1b")
    assert "Guard" not in ir["character_profiles"]


# ── /cast exposure ────────────────────────────────────────────────────────────

def test_cast_endpoint_includes_profiles(tmp_path, monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import server
    from prosecast import library as lib

    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    ir = _ir({"Astryx": 5})
    ir["character_profiles"] = {"Astryx": {"gender": "feminine", "age": "adult",
                                           "voice_hints": "bright", "confidence": 0.9,
                                           "evidence": "she said", "method": "llm"}}
    book = tmp_path / "prof_test"
    book.mkdir()
    (book / "ir.json").write_text(json.dumps(ir), encoding="utf-8")

    r = TestClient(server.app).get("/ir/prof_test/cast")
    assert r.status_code == 200
    chars = {c["name"]: c for c in r.json()["characters"]}
    assert chars["Astryx"]["profile"]["gender"] == "feminine"
