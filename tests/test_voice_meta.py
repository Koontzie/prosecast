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
    assert voices[0]["id"] == "x.wav" and voices[0]["name"] == "x"
    assert voices[0]["gender"] == "" and voices[0]["notes"] == ""
    assert voices[0]["tags"] == [] and voices[0]["rating"] == 0
    assert voices[0]["hidden"] is False and voices[0]["distributable"] is False
    meta_file.write_text("{not json", encoding="utf-8")
    voices = server._apply_voice_meta([{"id": "x.wav", "name": "x"}])
    assert voices[0]["gender"] == ""


def test_invalid_gender_values_normalize_to_unlabeled(meta_file):
    meta_file.write_text(json.dumps({"x": {"gender": "yes"}}), encoding="utf-8")
    voices = server._apply_voice_meta([{"id": "x.wav", "name": "x"}])
    assert voices[0]["gender"] == "" and voices[0]["name"] == "x"


# ── E7.1: the extended schema (tags / rating / hidden / provenance) ───────────
#
# Old entries carry only gender+notes and must keep working untouched; the
# staging script's provenance fields and the Voices view's new ones ride along
# on the same dict so the UI never needs a second round trip.

def test_extended_fields_pass_through(meta_file):
    meta_file.write_text(json.dumps({
        # The real one, exactly as stage_librivox_dialects.py wrote it.
        "x-irish-padraig": {
            "gender": "m", "notes": "Irish accent", "region": "irish",
            "accent_label": "Irish accent", "license": "CC0-1.0",
            "distributable": True,
            "source_url": "https://archive.org/download/dialect_accent_0909_librivox/x.mp3",
        },
    }), encoding="utf-8")
    v = server._apply_voice_meta(
        [{"id": "predefined:x-irish-padraig.wav", "name": "x-irish-padraig"}])[0]
    assert v["name"] == "x-irish-padraig ♂"        # glyph behaviour unchanged
    assert v["region"] == "irish" and v["license"] == "CC0-1.0"
    assert v["distributable"] is True
    assert v["accent_label"] == "Irish accent"
    assert v["source_url"].startswith("https://archive.org/")
    # Not yet annotated in the Voices view → the new fields default, not vanish.
    assert v["tags"] == [] and v["rating"] == 0 and v["hidden"] is False


def test_gender_only_entry_still_works(meta_file):
    """The shape every hand-written entry in the shipped file has."""
    meta_file.write_text(json.dumps({"Robert": {"gender": "m", "notes": "doesnt work well"}}),
                         encoding="utf-8")
    v = server._apply_voice_meta([{"id": "Robert.wav", "name": "Robert (clone)"}])[0]
    assert v["gender"] == "m" and v["notes"] == "doesnt work well"
    assert v["tags"] == [] and v["rating"] == 0 and v["hidden"] is False
    assert v["region"] == "" and v["license"] == "" and v["distributable"] is False


def test_tags_are_lowercased_deduped_and_capped(meta_file):
    meta_file.write_text(json.dumps({"x": {
        "tags": ["American", "american", " NYC ", "gravelly"] + [f"t{i}" for i in range(20)],
    }}), encoding="utf-8")
    v = server._apply_voice_meta([{"id": "x.wav", "name": "x"}])[0]
    assert v["tags"][:3] == ["american", "nyc", "gravelly"]
    assert len(v["tags"]) == 12


def test_junk_rating_and_tags_do_not_take_the_list_down(meta_file):
    meta_file.write_text(json.dumps({"x": {"rating": "lots", "tags": "american",
                                           "hidden": "yes"}}), encoding="utf-8")
    v = server._apply_voice_meta([{"id": "x.wav", "name": "x"}])[0]
    assert v["rating"] == 0 and v["tags"] == [] and v["hidden"] is True


def test_rating_clamps_to_0_5(meta_file):
    meta_file.write_text(json.dumps({"a": {"rating": 9}, "b": {"rating": -3}}),
                         encoding="utf-8")
    out = {v["id"]: v for v in server._apply_voice_meta(
        [{"id": "a.wav", "name": "a"}, {"id": "b.wav", "name": "b"}])}
    assert out["a.wav"]["rating"] == 5 and out["b.wav"]["rating"] == 0


def test_stem_key_wins_over_the_legacy_display_name(meta_file):
    """Both styles exist in the shipped file. New writes use the stem, so the
    stem is what must win when a voice happens to have both."""
    meta_file.write_text(json.dumps({
        "Gianna": {"gender": "f", "notes": "keyed by stem"},
        "Gianna (clone)": {"gender": "m", "notes": "keyed by display name"},
    }), encoding="utf-8")
    v = server._apply_voice_meta([{"id": "Gianna.wav", "name": "Gianna (clone)"}])[0]
    assert v["notes"] == "keyed by stem" and v["gender"] == "f"


def test_voice_key_is_the_stem():
    assert server._voice_key("predefined:us-nyc-add.wav") == "us-nyc-add"
    assert server._voice_key("Gianna.wav") == "Gianna"
    assert server._voice_key("Samantha") == "Samantha"
