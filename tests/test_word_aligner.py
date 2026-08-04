"""
Word aligner tests — offline (whisper mocked; wavs synthesized with `wave`).
"""

import json
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import word_aligner as wa  # noqa: E402


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


# ── response parsing ──────────────────────────────────────────────────────────

def test_extract_words_top_level_and_segments():
    top = {"words": [_w("Hello,", 0.0, 0.4), _w("there.", 0.5, 0.9)]}
    seg = {"segments": [{"words": [_w("Hello,", 0.0, 0.4)]},
                        {"words": [_w("there.", 0.5, 0.9)]}]}
    assert len(wa.extract_words(top)) == 2
    assert len(wa.extract_words(seg)) == 2
    assert wa.extract_words({"text": "no timestamps"}) == []
    assert wa.extract_words({"words": [{"word": "x"}]}) == []   # missing times


# ── text matching ─────────────────────────────────────────────────────────────

def test_align_exact_match():
    text = '"Hello there, my friend."'
    words = [_w("Hello", 0.1, 0.4), _w("there,", 0.4, 0.7),
             _w("my", 0.8, 0.9), _w("friend.", 0.9, 1.4)]
    out = wa.align_words(text, words)
    assert len(out) == 4                                # our 4 tokens
    assert out[0]["t"] == 0.1 and out[3]["t"] == 0.9
    # char ranges point into OUR text, quotes intact
    assert text[out[0]["cs"]:out[0]["ce"]] == '"Hello'
    assert text[out[3]["cs"]:out[3]["ce"]] == 'friend."'


def test_align_interpolates_mistranscribed_words():
    # whisper heard 'Astryx' as 'Astrid' — that token interpolates between
    # its timed neighbors instead of corrupting anything
    text = "Then Astryx spoke."
    words = [_w("Then", 0.0, 0.2), _w("Astrid", 0.2, 0.8), _w("spoke.", 0.8, 1.2)]
    out = wa.align_words(text, words)
    assert len(out) == 3
    assert out[0]["t"] == 0.0 and out[2]["t"] == 0.8
    assert 0.2 <= out[1]["t"] <= 0.8                    # interpolated between
    assert text[out[1]["cs"]:out[1]["ce"]] == "Astryx"  # OUR text survives


def test_align_empty_inputs():
    assert wa.align_words("", [_w("x", 0, 1)]) == []
    assert wa.align_words("some text", []) == []


# ── chapter pass + staleness (mocked transcription, real tiny wavs) ──────────

def _write_wav(path, seconds=1.0, rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))


@pytest.fixture()
def book(tmp_path, monkeypatch):
    from prosecast import library as lib
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    slug = "align_test"
    ir = {"title": "T", "chapters": [{"title": "Ch 1", "blocks": [
        {"segmentId": "s0", "type": "dialogue", "text": '"Hello there."',
         "speaker": "A", "confidence": 0.9, "unresolved": False},
        {"segmentId": "s1", "type": "narration", "text": "She waved.",
         "speaker": "NARRATOR", "confidence": 1.0, "unresolved": False},
    ]}]}
    d = tmp_path / slug
    d.mkdir()
    (d / "ir.json").write_text(json.dumps(ir), encoding="utf-8")
    blocks = lib.chapter_blocks_dir(slug, 0)
    _write_wav(blocks / "block_0000.wav", 2.0)
    _write_wav(blocks / "block_0001.wav", 1.0)
    return slug


def test_align_chapter_offsets_and_save(book, monkeypatch):
    responses = {
        "block_0000.wav": [_w('"Hello', 0.2, 0.6), _w('there."', 0.7, 1.5)],
        "block_0001.wav": [_w("She", 0.1, 0.3), _w("waved.", 0.3, 0.8)],
    }
    monkeypatch.setattr(wa, "transcribe_wav",
                        lambda p, **k: responses[Path(p).name])
    doc = wa.align_chapter(book, 0)
    assert doc is not None
    assert doc["total_duration"] == 3.0
    words = doc["words"]
    assert [w["b"] for w in words] == [0, 0, 1, 1]
    assert words[2]["t"] == pytest.approx(2.1, abs=0.01)   # block 1 offset by 2.0s
    assert wa.timings_path(book, 0).exists()


def test_align_chapter_circuit_breaker(book, monkeypatch):
    calls = []
    monkeypatch.setattr(wa, "transcribe_wav",
                        lambda p, **k: calls.append(1) and None)
    assert wa.align_chapter(book, 0) is None
    assert len(calls) <= wa.MAX_CONSECUTIVE_ERRORS
    assert not wa.timings_path(book, 0).exists()           # nothing half-saved


def test_word_timings_endpoint_fresh_and_stale(book, monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import server
    client = TestClient(server.app)

    # No timings yet
    r = client.get(f"/word_timings/{book}/0").json()
    assert r["words"] is None and r["stale"] is False

    # Aligned → fresh
    monkeypatch.setattr(wa, "transcribe_wav",
                        lambda p, **k: [_w("Hello", 0.1, 0.5)])
    wa.align_chapter(book, 0)
    r = client.get(f"/word_timings/{book}/0").json()
    assert r["words"] and r["stale"] is False

    # Re-render changes a block's duration → stale, served as null
    from prosecast import library as lib
    _write_wav(lib.chapter_blocks_dir(book, 0) / "block_0000.wav", 4.0)
    r = client.get(f"/word_timings/{book}/0").json()
    assert r["words"] is None and r["stale"] is True
