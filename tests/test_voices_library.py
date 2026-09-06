"""
Phase E7 — the Voices view's own endpoints.

`GET /voices/library` (everything about every voice, plus orphaned notes),
`POST /voices/meta/{key}` (patch one entry), `GET /voices/sources` (the vetted
corpus catalogue).

Offline and hermetic: the Chatterbox voice list is monkeypatched, never
fetched. Nothing here touches the real voice_meta.json.
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

ROOT = Path(__file__).resolve().parent.parent

# What the Chatterbox server actually hands back, test artefacts and all.
CB_VOICES = [
    {"id": "predefined:us-nyc-add.wav", "name": "us-nyc-add"},
    {"id": "predefined:x-irish-padraig.wav", "name": "x-irish-padraig"},
    {"id": "predefined:cachetest_1.wav", "name": "cachetest_1"},
    {"id": "predefined:voice_selftest.wav", "name": "voice_selftest"},
    {"id": "predefined:scanprobe.wav", "name": "scanprobe"},
    {"id": "Gianna.wav", "name": "Gianna (clone)"},
]

META = {
    "_readme": "Voice metadata overlay — edit by hand.",
    "us-nyc-add": {"gender": "m", "notes": "gruff narrator", "tags": ["american", "nyc"],
                   "rating": 4, "hidden": False},
    "x-irish-padraig": {"gender": "m", "notes": "Irish accent", "region": "irish",
                        "accent_label": "Irish accent", "license": "CC0-1.0",
                        "distributable": True,
                        "source_url": "https://archive.org/download/x.mp3"},
    # The legacy style: keyed by the DISPLAY name, not the stem. The shipped
    # file has both, and these entries must keep resolving.
    "Gianna (clone)": {"gender": "f", "notes": "legacy display-name key"},
    # A voice that was deleted on the server. Its notes must not vanish.
    "ScarJo_Voice": {"gender": "f", "notes": "shouldnt be used"},
}


@pytest.fixture
def meta_file(tmp_path, monkeypatch):
    p = tmp_path / "voice_meta.json"
    p.write_text(json.dumps(META, indent=2, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(server, "VOICE_META_PATH", p)
    return p


@pytest.fixture
def cb(monkeypatch):
    """Pin the engine and the voice list — no network, no cache surprises."""
    monkeypatch.setattr(server, "_active_engine", "chatterbox")
    monkeypatch.setattr(server, "_chatterbox_voice_cache", list(CB_VOICES))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path / "library")
    return TestClient(server.app)


# ── GET /voices/library ──────────────────────────────────────────────────────

def test_library_keys_on_the_stem(client, meta_file, cb):
    body = client.get("/voices/library").json()
    assert body["engine"] == "chatterbox"
    by_key = {v["key"]: v for v in body["voices"]}
    assert by_key["us-nyc-add"]["id"] == "predefined:us-nyc-add.wav"
    assert by_key["us-nyc-add"]["kind"] == "predefined"
    assert by_key["Gianna"]["kind"] == "clone"
    # The glyph is a display string; the library's name is the clean one.
    assert by_key["us-nyc-add"]["name"] == "us-nyc-add"
    assert "♂" not in by_key["us-nyc-add"]["name"]


def test_library_carries_the_whole_overlay(client, meta_file, cb):
    v = {x["key"]: x for x in client.get("/voices/library").json()["voices"]}["us-nyc-add"]
    assert v["gender"] == "m" and v["notes"] == "gruff narrator"
    assert v["tags"] == ["american", "nyc"] and v["rating"] == 4
    assert v["hidden"] is False
    p = {x["key"]: x for x in client.get("/voices/library").json()["voices"]}["x-irish-padraig"]
    assert p["license"] == "CC0-1.0" and p["distributable"] is True
    assert p["region"] == "irish" and p["source_url"].startswith("https://archive.org/")


def test_legacy_display_name_entries_still_resolve(client, meta_file, cb):
    v = {x["key"]: x for x in client.get("/voices/library").json()["voices"]}["Gianna"]
    assert v["gender"] == "f" and v["notes"] == "legacy display-name key"


def test_server_test_artefacts_are_not_voices(client, meta_file, cb):
    keys = {v["key"] for v in client.get("/voices/library").json()["voices"]}
    assert keys == {"us-nyc-add", "x-irish-padraig", "Gianna"}
    assert not any("cachetest" in k or "selftest" in k or "scanprobe" in k for k in keys)


def test_orphans_are_surfaced_not_deleted(client, meta_file, cb):
    body = client.get("/voices/library").json()
    assert body["orphans"] == ["ScarJo_Voice"]
    # …and the file still has them. Dropping a note is never the fix.
    assert "ScarJo_Voice" in json.loads(meta_file.read_text())


def test_a_matched_legacy_key_is_not_an_orphan(client, meta_file, cb):
    """'Gianna (clone)' has a live voice behind it — it is annotated, not lost."""
    assert "Gianna (clone)" not in client.get("/voices/library").json()["orphans"]


def test_library_is_not_chatterbox_only(client, meta_file, monkeypatch):
    monkeypatch.setattr(server, "_active_engine", "say")
    body = client.get("/voices/library").json()
    assert body["engine"] == "say"
    from prosecast.tts_engine import VoiceAssigner
    assert [v["id"] for v in body["voices"]] == list(VoiceAssigner.SAY_VOICES)
    assert all(v["key"] == v["id"] for v in body["voices"])


def test_library_does_not_change_the_cast_drawers_shape(client, meta_file, cb):
    """/voices is what the cast drawer reads; it must stay {id, name, …}."""
    body = client.get("/voices").json()
    assert body["engine"] == "chatterbox"
    v = body["voices"][0]
    assert v["id"] == "predefined:us-nyc-add.wav" and v["name"] == "us-nyc-add ♂"
    assert "hidden" in v          # so the drawer can grey a retired voice out


# ── POST /voices/meta/{key} ──────────────────────────────────────────────────

def test_patch_leaves_absent_fields_alone(client, meta_file, cb):
    r = client.post("/voices/meta/us-nyc-add", json={"notes": "actually great"})
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["notes"] == "actually great"
    assert r.json()["entry"]["gender"] == "m"          # untouched
    on_disk = json.loads(meta_file.read_text())["us-nyc-add"]
    assert on_disk["gender"] == "m" and on_disk["rating"] == 4
    assert on_disk["tags"] == ["american", "nyc"]


def test_readme_survives_every_write(client, meta_file, cb):
    client.post("/voices/meta/us-nyc-add", json={"rating": 5})
    data = json.loads(meta_file.read_text())
    assert data["_readme"] == META["_readme"]
    assert isinstance(data["_readme"], str)
    # …and it never reaches the UI as a voice.
    assert "_readme" not in {v["key"] for v in client.get("/voices/library").json()["voices"]}
    assert "_readme" not in client.get("/voices/library").json()["orphans"]


def test_new_writes_land_on_the_stem_not_the_display_name(client, meta_file, cb):
    """Trap 2: the file has both styles. Everything new uses the stem, and the
    legacy entry's content comes along rather than being silently orphaned."""
    r = client.post("/voices/meta/Gianna", json={"rating": 3})
    assert r.status_code == 200, r.text
    data = json.loads(meta_file.read_text())
    assert data["Gianna"]["rating"] == 3
    assert data["Gianna"]["notes"] == "legacy display-name key"
    assert data["Gianna"]["gender"] == "f"


def test_tags_are_normalised_on_the_way_in(client, meta_file, cb):
    r = client.post("/voices/meta/us-nyc-add",
                    json={"tags": ["American", " NYC ", "american", "Gravelly"]})
    assert r.json()["entry"]["tags"] == ["american", "nyc", "gravelly"]


def test_hiding_and_unhiding_round_trips(client, meta_file, cb):
    assert client.post("/voices/meta/us-nyc-add", json={"hidden": True}).json()["entry"]["hidden"]
    v = {x["key"]: x for x in client.get("/voices/library").json()["voices"]}["us-nyc-add"]
    assert v["hidden"] is True
    assert client.post("/voices/meta/us-nyc-add",
                       json={"hidden": False}).json()["entry"]["hidden"] is False


def test_a_voice_can_be_annotated_before_it_exists(client, meta_file, cb):
    """Unknown keys are accepted on purpose — the alternative is losing a note."""
    r = client.post("/voices/meta/not-uploaded-yet", json={"notes": "staged, not up yet"})
    assert r.status_code == 200, r.text
    assert json.loads(meta_file.read_text())["not-uploaded-yet"]["notes"] == "staged, not up yet"


@pytest.mark.parametrize("body,word", [
    ({"gender": "yes"}, "gender"),
    ({"gender": 4}, "gender"),
    ({"rating": 9}, "rating"),
    ({"rating": -1}, "rating"),
    ({"rating": "lots"}, "rating"),
    ({"tags": "american"}, "tags"),
    ({"tags": [1, 2]}, "tags"),
    ({"tags": [f"t{i}" for i in range(13)]}, "12 tags"),
    ({"tags": ["x" * 41]}, "40 characters"),
    ({"notes": "n" * 2001}, "2000"),
    ({"hidden": "yes"}, "hidden"),
    ({}, "Nothing to change"),
])
def test_bad_input_is_a_400_with_a_sentence(client, meta_file, cb, body, word):
    r = client.post("/voices/meta/us-nyc-add", json=body)
    assert r.status_code == 400, r.text
    assert word in r.json()["detail"]
    # And the file is exactly as it was.
    assert json.loads(meta_file.read_text()) == META


def test_empty_gender_clears_the_label(client, meta_file, cb):
    r = client.post("/voices/meta/us-nyc-add", json={"gender": ""})
    assert r.status_code == 200 and r.json()["entry"]["gender"] == ""


def test_a_failed_write_leaves_every_note_intact(client, meta_file, cb, monkeypatch):
    """The one that protects every note Tyler will ever write.

    `_voice_meta()` swallows JSONDecodeError and returns {}, so a half-written
    file is a SILENT total loss — it would not even look like a failure. The
    atomic writer means a crash mid-write leaves the previous version standing.
    """
    import os as _os
    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(_os, "replace", boom)

    with pytest.raises(OSError):
        client.post("/voices/meta/us-nyc-add", json={"notes": "this write dies"})

    assert json.loads(meta_file.read_text()) == META
    assert client.get("/voices/library").json()["voices"], "the list still loads"


def test_the_write_really_goes_through_the_atomic_helper(client, meta_file, cb, monkeypatch):
    seen = []
    real = lib.write_json_atomic
    monkeypatch.setattr(lib, "write_json_atomic",
                        lambda p, d: (seen.append(Path(p)), real(p, d))[1])
    client.post("/voices/meta/us-nyc-add", json={"rating": 1})
    assert seen == [meta_file]


# ── GET /voices/sources ──────────────────────────────────────────────────────

TIERS = {"ship", "private", "never"}


def test_sources_is_the_catalogue(client):
    body = client.get("/voices/sources").json()
    ids = {s["id"] for s in body["sources"]}
    for expected in ("librivox-dialects", "hifi-tts", "libritts-r", "vctk",
                     "qwen3-voicedesign", "coraal", "speech-accent-archive", "ears"):
        assert expected in ids, expected
    assert any(s["tier"] == "never" for s in body["sources"]), \
        "the point of listing a NEVER is so nobody researches it twice"


def test_every_entry_has_the_fields_the_panel_draws(client):
    for s in client.get("/voices/sources").json()["sources"]:
        assert s["tier"] in TIERS, s
        for field in ("id", "name", "license", "us_regional", "url", "blurb", "command"):
            assert field in s, (s["id"], field)
        assert isinstance(s["us_regional"], bool)
        assert s["url"].startswith("https://")
        assert s["command"] is None or isinstance(s["command"], str)


def test_the_licence_warning_travels_with_the_catalogue(client):
    body = client.get("/voices/sources").json()
    assert "not voice consent" in body["note"]
    assert body["doc"] == "docs/voice-sources.md"


def test_no_private_host_leaks_into_the_catalogue(client):
    """Placeholders only. The history was rewritten once to scrub a real host."""
    blob = json.dumps(client.get("/voices/sources").json())
    import re
    for ip in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", blob):
        assert ip == "192.168.1.50", ip
    for word in ("gideon", "tailscale", "/Users/tylerkoontz", "localhost", "127.0.0.1"):
        assert word.lower() not in blob.lower(), word


def test_the_ship_tier_is_the_only_one_with_a_pull_command(client):
    """A private/never source must not offer a one-click way to fetch it."""
    for s in client.get("/voices/sources").json()["sources"]:
        if s["command"]:
            assert s["tier"] == "ship", s["id"]


def test_the_shipped_catalogue_file_parses(client):
    assert json.loads((ROOT / "voice_sources.json").read_text())["sources"]
