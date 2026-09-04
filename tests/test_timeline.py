"""
Contract tests for GET /timeline/{slug}/{chapter}.

This endpoint is the *only* thing the player and the reader view read while
audio is playing: the speaker label, the per-paragraph label, the dialogue
styling and the sentence-click seek all come from here. It has no other
consumer, which is why it lost a field in 30740dc (2026-08-04) — `speaker` was
dropped while `text` was being un-truncated — and why nothing failed for a
month: every line simply rendered as NARRATOR, and the headless UI check of the
day used a hand-written mock that still included the field.

So these tests assert the *contract*, field by field, rather than one bug.
"""
import json
import sys
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from prosecast import library as lib  # noqa: E402

# Every key the frontend reads off a timeline entry. Adding one here is fine;
# removing one is a breaking change to the player and should fail loudly.
PLAYER_FIELDS = {"block_index", "segment_id", "start", "duration", "type",
                 "speaker", "text", "unresolved"}

LONG_LINE = ("It was a truth universally acknowledged that a single man in "
             "possession of a good fortune must be in want of a wife, and the "
             "neighbourhood took the matter as settled long before he had any "
             "say in it at all, which is how these things usually go. ") * 2

BLOCKS = [
    ("narration", "NARRATOR", "The morning light fell across the study.", False),
    ("dialogue", "Darcy", "You have been avoiding me.", False),
    ("dialogue", "Elizabeth", LONG_LINE, False),
    ("dialogue", "UNKNOWN", "Then I shall wait.", True),
]


def _silent_wav(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * int(22050 * seconds))


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    slug = "study"
    blocks = []
    for i, (kind, speaker, text, unresolved) in enumerate(BLOCKS):
        blocks.append({
            "segmentId": f"ch0_seg_{i:04d}", "type": kind, "text": text,
            "speaker": speaker, "confidence": 0.0 if unresolved else 0.9,
            "unresolved": unresolved,
            "attribution_method": "postfix" if not unresolved else "unresolved",
            "audioVariants": {"standard": {"url": None, "cached": False},
                              "premium": {"url": None, "cached": False}},
            "selectedVariant": "standard", "cacheKey": None,
        })
    ir = {"book_title": "The Study", "unresolved_count": 1, "characters": ["Darcy", "Elizabeth"],
          "chapters": [{"index": 0, "title": "One", "blocks": blocks},
                       {"index": 1, "title": "Two", "blocks": []}]}
    lib.ensure_book_dir(slug)
    (tmp_path / slug / "ir.json").write_text(json.dumps(ir))
    return slug


@pytest.fixture
def client(book):
    return TestClient(server.app)


def _timeline(client, slug, ch=0):
    r = client.get(f"/timeline/{slug}/{ch}")
    assert r.status_code == 200, r.text
    return r.json()["timeline"]


# ── the regression this file exists for ──────────────────────────────────────

def test_timeline_carries_the_speaker(client, book):
    speakers = [e["speaker"] for e in _timeline(client, book)]
    assert speakers == ["NARRATOR", "Darcy", "Elizabeth", "UNKNOWN"]
    assert speakers != ["NARRATOR"] * 4, "every line reading NARRATOR is the 30740dc bug"


def test_speaker_matches_the_ir_block_for_block(client, book):
    ir = json.loads(lib.ir_path(book).read_text())
    blocks = ir["chapters"][0]["blocks"]
    for entry, block in zip(_timeline(client, book), blocks):
        assert entry["speaker"] == block["speaker"]
        assert entry["segment_id"] == block["segmentId"]
        assert entry["type"] == block["type"]


def test_an_unresolved_block_keeps_its_own_speaker_and_flag(client, book):
    last = _timeline(client, book)[-1]
    assert last["unresolved"] is True
    assert last["speaker"] == "UNKNOWN", "the correction UI needs the real value, not a default"


# ── the rest of the contract, so the next edit here fails loudly ─────────────

def test_every_field_the_player_reads_is_present(client, book):
    for entry in _timeline(client, book):
        missing = PLAYER_FIELDS - set(entry)
        assert not missing, f"timeline entry is missing {sorted(missing)}"


def test_text_is_not_truncated(client, book):
    long_entry = _timeline(client, book)[2]
    assert long_entry["text"] == LONG_LINE
    assert len(long_entry["text"]) > 120, "the 120-char truncation froze the read-along display"


def test_start_times_accumulate_from_rendered_durations(client, book):
    for i, secs in enumerate([1.0, 2.0, 0.5, 0.5]):
        _silent_wav(lib.chapter_blocks_dir(book, 0) / f"block_{i:04d}.wav", secs)
    tl = _timeline(client, book)
    assert [e["duration"] for e in tl] == [1.0, 2.0, 0.5, 0.5]
    assert [e["start"] for e in tl] == [0.0, 1.0, 3.0, 3.5]


def test_missing_audio_is_zero_duration_not_an_error(client, book):
    tl = _timeline(client, book)          # nothing rendered in this book
    assert all(e["duration"] == 0.0 and e["start"] == 0.0 for e in tl)


def test_empty_chapter_is_an_empty_timeline(client, book):
    assert _timeline(client, book, ch=1) == []


def test_unknown_book_and_out_of_range_chapter_404(client, book):
    assert client.get("/timeline/nope/0").status_code == 404
    assert client.get(f"/timeline/{book}/99").status_code == 404


# ── keeping the UI's mock honest ─────────────────────────────────────────────

FIXTURE = Path(__file__).parent / "fixtures" / "timeline_study_ch0.json"


def test_the_ui_fixture_still_matches_this_endpoint(client, book):
    """The headless UI check feeds `fixtures/timeline_study_ch0.json` to the
    page instead of a hand-written mock. That only helps while the fixture is
    a true copy of what the server sends — so this test compares them.

    If it fails, the endpoint changed on purpose: regenerate the fixture
    (scripts/refresh_ui_fixtures.py) and re-run the headless check, rather than
    editing the JSON by hand.
    """
    live = client.get(f"/timeline/{book}/0").json()
    saved = json.loads(FIXTURE.read_text())
    assert live == saved, "UI fixture has drifted from /timeline — regenerate it"
