"""Preflight matrix (Phase C0) — fully offline, server mocked."""
import json

import pytest

from prosecast import library as lib
from prosecast import preflight as pf
from prosecast import tts_engine as tts


BASE_INFO = {"loaded": True, "type": "original", "class_name": "ChatterboxTTS"}
TURBO_INFO = {"loaded": True, "type": "turbo", "class_name": "ChatterboxTurboTTS"}
PREDEFINED = [{"display_name": "Robert", "filename": "Robert.wav"}]
REFERENCES = ["Gianna.wav"]


@pytest.fixture
def book(tmp_path, monkeypatch):
    """Throwaway book with a valid chatterbox voice_map; server mocked healthy."""
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    slug = "pf_test"
    d = tmp_path / slug
    d.mkdir()
    ir = {
        "book_title": "PF Test",
        "unresolved_count": 0,
        "chapters": [
            {"index": 0, "title": "One", "blocks": []},
            {"index": 1, "title": "Two", "blocks": []},
        ],
    }
    (d / "ir.json").write_text(json.dumps(ir))
    (d / "voice_map.json").write_text(json.dumps({
        "engine": "chatterbox",
        "map": {"NARRATOR": "predefined:Robert.wav", "Alice": "Gianna.wav"},
    }))
    monkeypatch.setattr(pf, "_fetch_model_info", lambda timeout=4.0: BASE_INFO)
    monkeypatch.setattr(tts, "fetch_chatterbox_predefined", lambda timeout=5: PREDEFINED)
    monkeypatch.setattr(tts, "fetch_chatterbox_references", lambda timeout=5: REFERENCES)
    return slug


def test_happy_path(book):
    rep = pf.preflight(book, "chatterbox")
    assert rep.ok, rep.summary()
    assert rep.aborts == []


def test_server_unreachable(book, monkeypatch):
    monkeypatch.setattr(pf, "_fetch_model_info", lambda timeout=4.0: None)
    rep = pf.preflight(book, "chatterbox")
    assert not rep.ok
    assert "unreachable" in rep.summary()


def test_turbo_model_aborts(book, monkeypatch):
    monkeypatch.setattr(pf, "_fetch_model_info", lambda timeout=4.0: TURBO_INFO)
    rep = pf.preflight(book, "chatterbox")
    assert not rep.ok
    assert "TURBO" in rep.summary()


def test_missing_voice_map(book, tmp_path):
    (tmp_path / book / "voice_map.json").unlink()
    rep = pf.preflight(book, "chatterbox")
    assert not rep.ok
    assert "voice_map" in rep.summary()


def test_engine_mismatch_aborts(book, tmp_path):
    (tmp_path / book / "voice_map.json").write_text(json.dumps({
        "engine": "elevenlabs",
        "map": {"NARRATOR": "EXAVITQu4vr4xnSDxMaL"},
    }))
    rep = pf.preflight(book, "chatterbox")
    assert not rep.ok
    assert "elevenlabs" in rep.summary()
    assert "re-cast" in rep.summary()


def test_missing_server_voice_aborts(book, monkeypatch):
    monkeypatch.setattr(tts, "fetch_chatterbox_references", lambda timeout=5: [])
    rep = pf.preflight(book, "chatterbox")
    assert not rep.ok
    assert "Gianna.wav" in rep.summary()


def test_unresolved_and_done_chapters_warn_only(book, tmp_path):
    d = tmp_path / book
    ir = json.loads((d / "ir.json").read_text())
    ir["unresolved_count"] = 7
    (d / "ir.json").write_text(json.dumps(ir))
    lib.chapter_wav_path(book, 0).parent.mkdir(parents=True, exist_ok=True)
    lib.chapter_wav_path(book, 0).write_bytes(b"RIFF")
    rep = pf.preflight(book, "chatterbox")
    assert rep.ok, rep.summary()
    assert any("unresolved" in w for w in rep.warnings)
    assert any("already rendered" in w for w in rep.warnings)
    assert rep.details["chapters_done"] == [0]


def test_no_ir_aborts(book, tmp_path):
    (tmp_path / book / "ir.json").unlink()
    rep = pf.preflight(book, "chatterbox")
    assert not rep.ok
