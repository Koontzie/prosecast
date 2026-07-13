"""
Chatterbox backend tests — pure, offline, no network.

Covers the three things that would silently break a real render:
  1. tag_mapper emotion → exaggeration/speed table (bounds + arousal nudge)
  2. VoiceAssigner clone-pool assignment (narrator=slot 0, round-robin, no class mutation)
  3. _synthesize_chatterbox payload shape — especially the speed → speed_factor rename
  4. the Turbo guard warning fires on a turbo model-info response

All server I/O is mocked via urllib.request.urlopen. These tests must NEVER hit the
network and must NOT touch any library/**/ir.json / voice_map.json / corrections.jsonl.
"""

import io
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import tts_engine
from prosecast.tag_mapper import map_tags


class _FakeResp:
    """Minimal context-manager stand-in for an http.client.HTTPResponse."""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ── tag mapper ────────────────────────────────────────────────────────────────

def test_map_tags_neutral():
    out = map_tags({"intensity": 0.5, "pace": "measured", "emotion": "neutral"}, "chatterbox")
    assert out == {"exaggeration": 0.55}


def test_map_tags_high_arousal_pushes_up():
    out = map_tags({"intensity": 0.9, "pace": "urgent", "emotion": "hot anger"}, "chatterbox")
    assert out["exaggeration"] == 0.85           # clamped at the artifact-free ceiling


def test_map_tags_low_arousal_pulls_down():
    out = map_tags({"intensity": 0.3, "pace": "slow", "emotion": "calm reserve"}, "chatterbox")
    assert out["exaggeration"] < 0.55


def test_map_tags_clamps_to_range():
    out = map_tags({"intensity": 1.0, "pace": "urgent", "emotion": "furious rage"}, "chatterbox")
    assert 0.20 <= out["exaggeration"] <= 0.85


def test_map_tags_never_emits_speed():
    """Echo regression guard (2026-07-13): speed_factor is a time-stretch post-
    process on the server that smears audio into echo/reverb. The chatterbox
    mapping must NEVER emit `speed`, whatever the pace tag says."""
    for pace in ("slow", "measured", "brisk", "urgent"):
        for emotion in ("neutral", "hot anger", "calm reserve"):
            out = map_tags({"intensity": 0.7, "pace": pace, "emotion": emotion}, "chatterbox")
            assert "speed" not in out, f"speed leaked for pace={pace}, emotion={emotion}"
            assert "speed_factor" not in out


def test_map_tags_empty_returns_empty():
    assert map_tags(None, "chatterbox") == {}
    assert map_tags({}, "chatterbox") == {}


# ── voice assigner ──────────────────────────────────────────────────────────────

def test_chatterbox_pool_assignment():
    va = tts_engine.VoiceAssigner(engine="stub")   # avoids the network fetch in __init__
    va.engine = "chatterbox"
    va._chatterbox_pool = ["Narr.wav", "A.wav", "B.wav"]

    narr = va.get_voice("NARRATOR")
    assert narr == {"voice_mode": "clone", "reference_audio_filename": "Narr.wav"}

    a = va.get_voice("Alice")
    b = va.get_voice("Bob")
    assert a["reference_audio_filename"] == "A.wav"
    assert b["reference_audio_filename"] == "B.wav"
    # round-robin wraps back to the first character slot (index 1), never onto narrator
    c = va.get_voice("Carol")
    assert c["reference_audio_filename"] == "A.wav"


def test_chatterbox_pool_does_not_mutate_class():
    va = tts_engine.VoiceAssigner(engine="stub")
    va._chatterbox_pool.append("SHOULD_NOT_LEAK.wav")
    assert "SHOULD_NOT_LEAK.wav" not in tts_engine.VoiceAssigner.CHATTERBOX_VOICES


# ── synthesize payload ──────────────────────────────────────────────────────────

def test_synthesize_chatterbox_payload_and_write(tmp_path):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode())
        return _FakeResp(b"RIFFfake-wav-bytes", status=200)

    out = tmp_path / "seg.wav"
    voice_cfg = {
        "voice_mode": "clone",
        "reference_audio_filename": "Gianna.wav",
        "_tag_params": {"exaggeration": 0.8, "cfg_weight": 0.4, "speed": 1.25},
    }
    with mock.patch("urllib.request.urlopen", fake_urlopen):
        ok = tts_engine._synthesize_chatterbox("Hello there.", voice_cfg, str(out))

    assert ok is True
    assert out.read_bytes() == b"RIFFfake-wav-bytes"

    p = captured["payload"]
    assert p["text"] == "Hello there."
    assert p["voice_mode"] == "clone"
    assert p["reference_audio_filename"] == "Gianna.wav"
    assert p["output_format"] == "wav"
    assert p["stream"] is False
    assert p["exaggeration"] == 0.8
    assert p["cfg_weight"] == 0.4
    # the critical rename: mapper emits `speed`, server wants `speed_factor`
    assert p["speed_factor"] == 1.25
    assert "speed" not in p


def test_synthesize_chatterbox_predefined_mode(tmp_path):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data.decode())
        return _FakeResp(b"wav", status=200)

    out = tmp_path / "seg.wav"
    voice_cfg = {"voice_mode": "predefined", "predefined_voice_id": "Robert.wav", "_tag_params": {}}
    with mock.patch("urllib.request.urlopen", fake_urlopen):
        ok = tts_engine._synthesize_chatterbox("Hi.", voice_cfg, str(out))

    assert ok is True
    assert captured["payload"]["predefined_voice_id"] == "Robert.wav"
    assert "reference_audio_filename" not in captured["payload"]


def test_synthesize_chatterbox_missing_reference_fails(tmp_path):
    out = tmp_path / "seg.wav"
    voice_cfg = {"voice_mode": "clone"}  # no reference filename
    # Should fail fast without ever calling the network.
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("must not call network")):
        ok = tts_engine._synthesize_chatterbox("x", voice_cfg, str(out))
    assert ok is False


# ── turbo guard ─────────────────────────────────────────────────────────────────

def test_turbo_guard_warns(capsys):
    info = json.dumps({"loaded": True, "type": "turbo", "class_name": "ChatterboxTurboTTS"}).encode()
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp(info)):
        ok = tts_engine.test_chatterbox_connection()
    assert ok is True
    out = capsys.readouterr().out
    assert "Connection OK" in out
    assert "WARNING" in out and "turbo" in out.lower()


def test_base_model_no_warning(capsys):
    info = json.dumps({"loaded": True, "type": "base", "class_name": "ChatterboxTTS"}).encode()
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp(info)):
        ok = tts_engine.test_chatterbox_connection()
    assert ok is True
    out = capsys.readouterr().out
    assert "Connection OK" in out
    assert "WARNING" not in out
