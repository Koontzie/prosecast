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
    # GPU probes default to "plenty of room" so the existing matrix stays offline.
    # A ComfyUI URL must be configured or the headroom check skips entirely (E4.1).
    monkeypatch.setattr(pf, "COMFY_BASE_URL", "http://comfy.test:8188")
    monkeypatch.setattr(pf, "_free_vram_gb", lambda timeout=6.0: 12.0)
    monkeypatch.setattr(pf, "_comfy_idle", lambda timeout=6.0: True)
    monkeypatch.setattr(pf, "_comfy_free", lambda timeout=20.0: True)
    return slug


def test_happy_path(book):
    rep = pf.preflight(book, "chatterbox")
    assert rep.ok, rep.summary()
    assert rep.aborts == []


def test_server_unreachable(book, monkeypatch):
    monkeypatch.setattr(pf, "_fetch_model_info", lambda timeout=4.0: None)
    rep = pf.preflight(book, "chatterbox")
    assert not rep.ok
    assert "not responding" in rep.summary()


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


# ── GPU headroom (added 2026-09-02) ───────────────────────────────────────────
# Regression cover for the day every chunk 500'd while /api/model-info said
# loaded:true — ComfyUI had held a video model resident for 27 days.


def test_gpu_headroom_ok_is_silent(book):
    rep = pf.preflight(book, "chatterbox")
    assert rep.ok, rep.summary()
    assert not any("VRAM" in w for w in rep.warnings)
    assert rep.details["vram_free_gb"] == 12.0


def test_gpu_full_aborts(book, monkeypatch):
    monkeypatch.setattr(pf, "_free_vram_gb", lambda timeout=6.0: 0.05)
    monkeypatch.setattr(pf, "_comfy_idle", lambda timeout=6.0: False)
    rep = pf.preflight(book, "chatterbox")
    assert not rep.ok
    assert "GB VRAM free" in rep.summary()


def test_gpu_reclaims_from_idle_comfy(book, monkeypatch):
    calls = {"freed": 0}
    seq = iter([0.2, 10.4])          # before free, after free

    def fake_free_vram(timeout=6.0):
        try:
            return next(seq)
        except StopIteration:
            return 10.4

    def fake_comfy_free(timeout=20.0):
        calls["freed"] += 1
        return True

    monkeypatch.setattr(pf, "_free_vram_gb", fake_free_vram)
    monkeypatch.setattr(pf, "_comfy_idle", lambda timeout=6.0: True)
    monkeypatch.setattr(pf, "_comfy_free", fake_comfy_free)
    monkeypatch.setattr(pf.time, "sleep", lambda *_: None)

    rep = pf.preflight(book, "chatterbox")
    assert rep.ok, rep.summary()
    assert calls["freed"] == 1
    assert rep.details["vram_free_gb"] == 10.4
    assert any("reclaimed VRAM" in w for w in rep.warnings)


def test_gpu_busy_comfy_is_never_freed(book, monkeypatch):
    calls = {"freed": 0}

    def fake_comfy_free(timeout=20.0):
        calls["freed"] += 1
        return True

    monkeypatch.setattr(pf, "_free_vram_gb", lambda timeout=6.0: 0.3)
    monkeypatch.setattr(pf, "_comfy_idle", lambda timeout=6.0: False)
    monkeypatch.setattr(pf, "_comfy_free", fake_comfy_free)

    rep = pf.preflight(book, "chatterbox")
    assert calls["freed"] == 0, "must not unload models out from under a running job"
    assert not rep.ok
    assert any("busy" in w for w in rep.warnings)


def test_gpu_tight_but_usable_warns_only(book, monkeypatch):
    monkeypatch.setattr(pf, "_free_vram_gb", lambda timeout=6.0: 2.5)
    monkeypatch.setattr(pf, "_comfy_idle", lambda timeout=6.0: False)
    rep = pf.preflight(book, "chatterbox")
    assert rep.ok, rep.summary()
    assert any("enough to start" in w for w in rep.warnings)


def test_gpu_stats_unavailable_warns_but_does_not_block(book, monkeypatch):
    monkeypatch.setattr(pf, "_free_vram_gb", lambda timeout=6.0: None)
    rep = pf.preflight(book, "chatterbox")
    assert rep.ok, rep.summary()
    assert any("could not read GPU stats" in w for w in rep.warnings)
