"""The upload step of scripts/stage_librivox_dialects.py — auditioned files carry a
listening note after the first space in their filename; the note must become the
voice's note and NOT part of the permanent upload name, and MANIFEST provenance
must still match on the clean name."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "stage_librivox", ROOT / "scripts" / "stage_librivox_dialects.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_split_note_name_separates_key_from_listening_note():
    m = _load()
    assert m.split_note_name("us-midwest-dm deep slow male.wav") == ("us-midwest-dm.wav", "deep slow male")
    assert m.split_note_name("x-irish-padraig.wav") == ("x-irish-padraig.wav", "")
    assert m.split_note_name("us-louisiana-south-psc croakish female.wav") == (
        "us-louisiana-south-psc.wav", "croakish female")


def test_merge_voice_meta_seeds_provenance_and_keeps_the_note(tmp_path):
    m = _load()
    (tmp_path / "MANIFEST.json").write_text(json.dumps([{
        "filename": "us-midwest-dm.wav", "region": "midwest",
        "accent_label": "American accent, Midwest", "gender_guess": "m",
        "license": {"spdx": "CC0-1.0", "distributable": True},
        "source": {"url": "https://archive.org/example"},
    }]))
    meta_path = tmp_path / "voice_meta.json"
    meta_path.write_text(json.dumps({"_readme": "keep me"}))

    m.merge_voice_meta(tmp_path, [("us-midwest-dm.wav", "deep slow male"), ("unknown.wav", "")], meta_path)

    meta = json.loads(meta_path.read_text())
    assert meta["_readme"] == "keep me"
    entry = meta["us-midwest-dm"]
    assert entry["notes"] == "deep slow male · American accent, Midwest"
    assert entry["license"] == "CC0-1.0" and entry["distributable"] is True
    assert entry["source_url"] == "https://archive.org/example"
    assert "unknown" not in meta


def test_merge_never_overwrites_a_hand_written_note(tmp_path):
    m = _load()
    (tmp_path / "MANIFEST.json").write_text(json.dumps([{
        "filename": "a.wav", "region": "r", "accent_label": "L", "gender_guess": "f",
        "license": {"spdx": "CC0-1.0", "distributable": True}, "source": {"url": "u"}}]))
    meta_path = tmp_path / "voice_meta.json"
    meta_path.write_text(json.dumps({"a": {"gender": "m", "notes": "my own words"}}))
    m.merge_voice_meta(tmp_path, [("a.wav", "script note")], meta_path)
    entry = json.loads(meta_path.read_text())["a"]
    assert entry["notes"] == "my own words" and entry["gender"] == "m"
