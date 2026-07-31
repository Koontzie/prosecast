"""
voice_meta.json overlay: gender glyphs + gender field on /voices and /cast.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fastapi = pytest.importorskip("fastapi")

import server  # noqa: E402


@pytest.fixture()
def meta_file(tmp_path, monkeypatch):
    p = tmp_path / "voice_meta.json"
    monkeypatch.setattr(server, "VOICE_META_PATH", p)
    return p


def test_overlay_adds_glyph_and_gender(meta_file):
    meta_file.write_text(json.dumps({
        "bright-toronto-1": {"gender": "f", "notes": ""},
        "deep-sydney-1": {"gender": "M", "notes": "case-insensitive"},
        "Gianna": {"gender": "f"},
    }), encoding="utf-8")
    voices = server._apply_voice_meta([
        {"id": "predefined:bright-toronto-1.wav", "name": "bright-toronto-1"},
        {"id": "predefined:deep-sydney-1.wav", "name": "deep-sydney-1"},
        {"id": "predefined:clear-warm-1.wav", "name": "clear-warm-1"},
        {"id": "Gianna.wav", "name": "Gianna (clone)"},   # matched by filename stem
    ])
    by_id = {v["id"]: v for v in voices}
    assert by_id["predefined:bright-toronto-1.wav"]["name"] == "bright-toronto-1 ♀"
    assert by_id["predefined:bright-toronto-1.wav"]["gender"] == "f"
    assert by_id["predefined:deep-sydney-1.wav"]["name"] == "deep-sydney-1 ♂"
    assert by_id["predefined:clear-warm-1.wav"]["name"] == "clear-warm-1"   # unlabeled
    assert by_id["predefined:clear-warm-1.wav"]["gender"] == ""
    assert by_id["Gianna.wav"]["name"] == "Gianna (clone) ♀"


def test_missing_or_broken_meta_file_is_harmless(meta_file):
    voices = server._apply_voice_meta([{"id": "x.wav", "name": "x"}])
    assert voices == [{"id": "x.wav", "name": "x", "gender": ""}]
    meta_file.write_text("{not json", encoding="utf-8")
    voices = server._apply_voice_meta([{"id": "x.wav", "name": "x"}])
    assert voices[0]["gender"] == ""


def test_invalid_gender_values_normalize_to_unlabeled(meta_file):
    meta_file.write_text(json.dumps({"x": {"gender": "yes"}}), encoding="utf-8")
    voices = server._apply_voice_meta([{"id": "x.wav", "name": "x"}])
    assert voices[0]["gender"] == "" and voices[0]["name"] == "x"
