"""Piper: six voices, a gender on each, and a probe that checks the files exist.

The first Windows install (2026-09-06) rendered the sample on Piper and the
result was miscast in a way nobody could fix from the UI: four voices for five
characters, no gender on any of them, so Elizabeth got `ryan` and Jane got
`kusal` — both men — and Bingley shared Elizabeth's voice. The cast profiler
had known both were women the whole time.

The probe had also said Piper was `ok` on the strength of the binary being on
PATH, with zero .onnx files on disk. `piper --model <name>` resolves
`<name>.onnx` from the working directory, so that machine would have failed at
render time instead — the worst place to learn it.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("fastapi")

import server  # noqa: E402
from prosecast import config, setup_probe as sp  # noqa: E402
from prosecast.tts_engine import VoiceAssigner  # noqa: E402


@pytest.fixture()
def meta_file(tmp_path, monkeypatch):
    """An empty overlay: what a fresh clone's auto-cast has to work from."""
    p = tmp_path / "voice_meta.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server, "VOICE_META_PATH", p)
    return p


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("PROSECAST_CONFIG", str(tmp_path / "config.json"))
    for env_var, _d, _s in config.SCHEMA.values():
        monkeypatch.delenv(env_var, raising=False)
    config.invalidate()
    yield
    config.invalidate()


# ── the pool ─────────────────────────────────────────────────────────────────

def test_there_are_six_voices():
    assert len(VoiceAssigner.PIPER_VOICES) == 6
    assert len(set(VoiceAssigner.PIPER_VOICES)) == 6, "no duplicates"


def test_every_voice_has_a_gender():
    """Shipped in code, not in voice_meta.json: a fresh clone must auto-cast
    correctly before anyone has hand-edited an overlay."""
    meta = VoiceAssigner.PIPER_VOICE_META
    assert set(meta) == set(VoiceAssigner.PIPER_VOICES), \
        "PIPER_VOICE_META and PIPER_VOICES must describe the same voices"
    assert all(m["gender"] in ("f", "m") for m in meta.values()), meta


def test_both_genders_can_actually_be_cast():
    """Three and three. One female voice would put every woman in the book on
    the same one, which is the bug in a different costume."""
    genders = [m["gender"] for m in VoiceAssigner.PIPER_VOICE_META.values()]
    assert genders.count("f") >= 3 and genders.count("m") >= 3, genders


def test_the_names_are_the_piper_catalogue_shape():
    """`piper --model <name>` and `python -m piper.download_voices <name>` both
    take this exact string, so a typo here is a download that 404s."""
    for name in VoiceAssigner.PIPER_VOICES:
        assert name.startswith("en_"), name
        assert name.endswith("-medium"), f"{name}: medium quality is the tested tier"
        assert len(name.split("-")) == 3, name


# ── the overlay layering ─────────────────────────────────────────────────────

def test_piper_voices_carry_their_gender_through_the_api(meta_file, monkeypatch):
    monkeypatch.setattr(server, "_active_engine", "piper")
    labels = {v["id"]: v for v in server._voice_labels("piper")}
    assert len(labels) == 6
    lessac = labels["en_US-lessac-medium"]
    assert lessac["gender"] == "f"
    assert lessac["name"].endswith("♀"), lessac["name"]
    assert labels["en_US-ryan-medium"]["name"].endswith("♂")


def test_a_hand_edit_beats_the_shipped_default(meta_file, monkeypatch):
    monkeypatch.setattr(server, "_active_engine", "piper")
    meta_file.write_text(json.dumps(
        {"en_US-ryan-medium": {"gender": "f"}}), encoding="utf-8")
    labels = {v["id"]: v for v in server._voice_labels("piper")}
    assert labels["en_US-ryan-medium"]["gender"] == "f", "the overlay must win"


def test_annotating_a_voice_does_not_drop_its_gender(meta_file, monkeypatch):
    """The Voices tab PATCHes one field. Replacing the shipped entry instead of
    merging would silently un-gender a voice the moment anyone wrote a note."""
    monkeypatch.setattr(server, "_active_engine", "piper")
    meta_file.write_text(json.dumps(
        {"en_US-ryan-medium": {"notes": "a bit nasal"}}), encoding="utf-8")
    labels = {v["id"]: v for v in server._voice_labels("piper")}
    assert labels["en_US-ryan-medium"]["gender"] == "m"
    assert labels["en_US-ryan-medium"]["notes"] == "a bit nasal"


def test_chatterbox_voices_are_unaffected_by_the_shipped_defaults(meta_file, monkeypatch):
    """The shipped map is keyed on Piper's own names; nothing else may pick it
    up by accident."""
    monkeypatch.setattr(server, "_raw_voices",
                        lambda e: [{"id": "Gianna.wav", "name": "Gianna"}])
    labels = server._voice_labels("chatterbox")
    assert labels[0]["gender"] == ""


# ── auto-cast respects gender ────────────────────────────────────────────────

SAMPLE_PROFILES = {
    "Elizabeth": {"gender": "feminine"},
    "Jane": {"gender": "feminine"},
    "Darcy": {"gender": "masculine"},
    "Bingley": {"gender": "masculine"},
}


def _gender_of(voice_id):
    return VoiceAssigner.PIPER_VOICE_META[voice_id]["gender"]


def test_women_get_female_voices_and_men_male_ones(meta_file, monkeypatch):
    """The exact cast that came out wrong on Windows."""
    monkeypatch.setattr(server, "_active_engine", "piper")
    chars = ["NARRATOR", "Elizabeth", "Jane", "Darcy", "Bingley"]
    vm = server._default_voice_map(chars, "piper", SAMPLE_PROFILES)

    assert _gender_of(vm["Elizabeth"]) == "f", vm
    assert _gender_of(vm["Jane"]) == "f", vm
    assert _gender_of(vm["Darcy"]) == "m", vm
    assert _gender_of(vm["Bingley"]) == "m", vm


def test_two_women_do_not_share_one_voice(meta_file, monkeypatch):
    monkeypatch.setattr(server, "_active_engine", "piper")
    vm = server._default_voice_map(
        ["NARRATOR", "Elizabeth", "Jane", "Darcy", "Bingley"], "piper", SAMPLE_PROFILES)
    assert vm["Elizabeth"] != vm["Jane"], vm
    assert vm["Darcy"] != vm["Bingley"], vm


def test_the_narrator_still_takes_index_zero(meta_file, monkeypatch):
    monkeypatch.setattr(server, "_active_engine", "piper")
    vm = server._default_voice_map(["NARRATOR", "Elizabeth"], "piper", SAMPLE_PROFILES)
    assert vm["NARRATOR"] == VoiceAssigner.PIPER_VOICES[0]


def test_the_narrators_voice_is_not_dealt_out_again(meta_file, monkeypatch):
    """VoiceAssigner reserves index 0 at render time; the map must agree, or a
    character shares the narrator's voice for no reason."""
    monkeypatch.setattr(server, "_active_engine", "piper")
    vm = server._default_voice_map(
        ["NARRATOR", "Elizabeth", "Jane", "Darcy", "Bingley"], "piper", SAMPLE_PROFILES)
    narrator = vm["NARRATOR"]
    assert [c for c, v in vm.items() if v == narrator] == ["NARRATOR"], vm


def test_an_unprofiled_character_still_gets_a_voice(meta_file, monkeypatch):
    """No profile at all is the common case — the AI pass is optional."""
    monkeypatch.setattr(server, "_active_engine", "piper")
    vm = server._default_voice_map(["NARRATOR", "A", "B", "C"], "piper", None)
    assert all(v in VoiceAssigner.PIPER_VOICES for v in vm.values()), vm
    assert len({vm["A"], vm["B"], vm["C"]}) == 3, "still spread out"


def test_ambiguous_gender_is_not_forced_into_a_bucket(meta_file, monkeypatch):
    monkeypatch.setattr(server, "_active_engine", "piper")
    vm = server._default_voice_map(
        ["NARRATOR", "X"], "piper", {"X": {"gender": "ambiguous"}})
    assert vm["X"] in VoiceAssigner.PIPER_VOICES


def test_an_engine_with_no_labelled_voices_is_unchanged(meta_file, monkeypatch):
    """say has no gender in the shipped defaults, so a profiled book must fall
    straight back to plain round-robin rather than cast everyone the same."""
    monkeypatch.setattr(server, "_active_engine", "say")
    vm = server._default_voice_map(
        ["NARRATOR", "Elizabeth", "Jane", "Darcy"], "say", SAMPLE_PROFILES)
    assert len(set(vm.values())) == 4, vm


# ── the probe ────────────────────────────────────────────────────────────────

@pytest.fixture()
def piper_on(cfg, tmp_path, monkeypatch):
    """piper on PATH, and an empty folder for it to look for voices in."""
    config.set_many({"tts_engine": "piper"})
    monkeypatch.setattr(sp, "_which", lambda b: "/usr/bin/piper" if b == "piper" else None)
    monkeypatch.setattr(sp, "_voices_dir", lambda: tmp_path)
    return tmp_path


def _put(folder, *names):
    for n in names:
        (folder / f"{n}.onnx").write_bytes(b"onnx")


def test_piper_with_no_voice_files_is_not_ok(piper_on):
    row = sp.probe_voice_engine()
    assert row["ok"] is False and row["state"] == "missing"
    assert row["voices_present"] == 0 and row["voices_wanted"] == 6


def test_the_fix_is_the_exact_command_for_each_missing_voice(piper_on):
    row = sp.probe_voice_engine()
    for name in VoiceAssigner.PIPER_VOICES:
        assert f"`python -m piper.download_voices {name}`" in row["fix"], name
    assert "Piper looks for voices in the folder it is started in" in row["fix"]


def test_all_six_present_is_green(piper_on):
    _put(piper_on, *VoiceAssigner.PIPER_VOICES)
    row = sp.probe_voice_engine()
    assert row["ok"] and row["state"] == "ok"
    assert row["voices_present"] == 6
    assert "6 voice files" in row["detail"]


def test_some_missing_warns_and_names_only_those(piper_on):
    _put(piper_on, *VoiceAssigner.PIPER_VOICES[:4])
    row = sp.probe_voice_engine()
    assert row["state"] == "warn"
    assert row["voices_present"] == 4
    for name in VoiceAssigner.PIPER_VOICES[4:]:
        assert name in row["fix"], name
    for name in VoiceAssigner.PIPER_VOICES[:4]:
        assert name not in row["fix"], f"{name} is already downloaded"


def test_a_partial_download_does_not_block_the_wizard(piper_on):
    """Step 2's Continue is gated on `ok`. Fewer voices is a worse cast, not a
    broken one — it must not be a wall."""
    _put(piper_on, *VoiceAssigner.PIPER_VOICES[:4])
    assert sp.probe_voice_engine()["ok"] is True


def test_piper_missing_from_path_still_says_how_to_get_voices(cfg, monkeypatch, tmp_path):
    config.set_many({"tts_engine": "piper"})
    monkeypatch.setattr(sp, "_which", lambda b: None)
    monkeypatch.setattr(sp, "_voices_dir", lambda: tmp_path)
    row = sp.probe_voice_engine()
    assert row["ok"] is False and row["state"] == "missing"
    assert "pip install piper-tts" in row["fix"]
    assert "download_voices" in row["fix"]
