"""
Phase E4.1 / E4.2 — config layering and the Setup probes.

All offline: config.json goes to tmp_path via PROSECAST_CONFIG, every network
probe is monkeypatched at its single mock point (_get_json / _el_user / _which).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import config, setup_probe as sp  # noqa: E402

ENV_KEYS = [v[0] for v in config.SCHEMA.values()] + ["PROSECAST_CONFIG"]


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Isolated config: no env vars from the real shell, file in tmp_path."""
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / "config.json"
    monkeypatch.setenv("PROSECAST_CONFIG", str(path))
    config.invalidate()
    yield path
    config.invalidate()


# ── config precedence ────────────────────────────────────────────────────────

def test_defaults_when_nothing_is_set(cfg):
    assert config.get("tts_engine") == "auto"
    assert config.get("ollama_url") == "http://localhost:11434"
    assert config.source("ollama_url") == "default"
    assert config.has_file() is False


def test_file_beats_default(cfg):
    cfg.write_text(json.dumps({"ollama_url": "http://GIDEON_HOST:11434/"}))
    config.invalidate()
    assert config.get("ollama_url") == "http://GIDEON_HOST:11434"   # trailing slash stripped
    assert config.source("ollama_url") == "file"


def test_env_beats_file(cfg, monkeypatch):
    cfg.write_text(json.dumps({"ollama_url": "http://file:11434", "tts_engine": "chatterbox"}))
    config.invalidate()
    monkeypatch.setenv("PROSECAST_OLLAMA_URL", "http://env:11434")
    assert config.get("ollama_url") == "http://env:11434"
    assert config.source("ollama_url") == "env"
    assert config.get("tts_engine") == "chatterbox"          # untouched key still from file
    assert config.shadowed_by_env() == ["ollama_url"]


def test_set_many_writes_file_and_drops_defaults(cfg):
    out = config.set_many({"tts_engine": "chatterbox", "ollama_url": "http://localhost:11434"})
    data = json.loads(cfg.read_text())
    assert data == {"tts_engine": "chatterbox"}      # default value is not pinned
    assert out["values"]["tts_engine"] == "chatterbox"
    assert out["sources"]["tts_engine"] == "file"


def test_set_many_rejects_bad_values(cfg):
    with pytest.raises(ValueError):
        config.set_many({"tts_engine": "siri"})
    with pytest.raises(ValueError):
        config.set_many({"ollama_url": "gideon:11434"})
    with pytest.raises(ValueError):
        config.set_many({"nope": 1})
    assert not cfg.exists()


def test_secret_is_masked_and_mask_never_written_back(cfg):
    config.set_many({"elevenlabs_api_key": "sk_abcdefgh1234"})
    pub = config.public()
    assert pub["values"]["elevenlabs_api_key"].endswith("1234")
    assert "abcdefgh" not in pub["values"]["elevenlabs_api_key"]
    assert pub["values"]["elevenlabs_api_key_set"] is True
    # UI round-trips the mask on Save → real key must survive
    config.set_many({"elevenlabs_api_key": pub["values"]["elevenlabs_api_key"]})
    assert config.get("elevenlabs_api_key") == "sk_abcdefgh1234"


def test_float_coercion_from_env(cfg, monkeypatch):
    monkeypatch.setenv("COMFY_RECLAIM_BELOW_GB", "6")
    assert config.get("gpu_reclaim_below_gb") == 6.0


def test_broken_file_is_treated_as_absent(cfg):
    cfg.write_text("{not json")
    config.invalidate()
    assert config.get("tts_engine") == "auto"


# ── probes ───────────────────────────────────────────────────────────────────

def _fake_get_json(routes: dict):
    """routes: {url_suffix: payload}; anything unmatched → None (unreachable)."""
    def _get(url, timeout=4.0, headers=None):
        for suffix, payload in routes.items():
            if url.endswith(suffix):
                return payload
        return None
    return _get


def test_engine_auto_is_amber_not_green(cfg, monkeypatch):
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({}))
    row = sp.probe_voice_engine()
    assert row["ok"] is False and row["state"] == "warn"
    assert "auto-detect" in row["detail"]


def test_chatterbox_ok(cfg, monkeypatch):
    config.set_many({"tts_engine": "chatterbox", "chatterbox_url": "http://cb:8101"})
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({
        "/api/model-info": {"class_name": "ChatterboxTTS", "type": "original", "device": "cuda"},
        "/get_predefined_voices": [{"name": "a"}, {"name": "b"}],
    }))
    row = sp.probe_voice_engine()
    assert row["ok"] and row["state"] == "ok"
    assert "cuda" in row["detail"] and "2 voices" in row["detail"]
    assert row["endpoint"] == "http://cb:8101"


def test_chatterbox_turbo_is_flagged(cfg, monkeypatch):
    config.set_many({"tts_engine": "chatterbox"})
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({
        "/api/model-info": {"class_name": "ChatterboxTurboTTS", "device": "cuda"},
    }))
    row = sp.probe_voice_engine()
    assert row["ok"] is False and "TURBO" in row["detail"] and "emotion" in row["fix"]


def test_chatterbox_unreachable_says_how_to_fix(cfg, monkeypatch):
    config.set_many({"tts_engine": "chatterbox"})
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({}))
    row = sp.probe_voice_engine()
    assert row["state"] == "missing" and "not responding" in row["detail"]
    assert row["fix"]


def test_elevenlabs_branches(cfg, monkeypatch):
    config.set_many({"tts_engine": "elevenlabs"})
    assert sp.probe_voice_engine()["state"] == "missing"          # no key
    config.set_many({"elevenlabs_api_key": "sk_x"})
    monkeypatch.setattr(sp, "_el_user", lambda key: "unauthorized")
    assert "rejected" in sp.probe_voice_engine()["detail"]
    monkeypatch.setattr(sp, "_el_user", lambda key: {"tier": "starter", "character_count": 1000,
                                                     "character_limit": 30000})
    row = sp.probe_voice_engine()
    assert row["ok"] and "29,000" in row["detail"] and "Chatterbox" in row["fix"]


def test_ollama_model_missing_gives_pull_command(cfg, monkeypatch):
    config.set_many({"ollama_model": "gemma3:12b"})
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({
        "/api/tags": {"models": [{"name": "llama3.2:latest"}]},
    }))
    row = sp.probe_ollama()
    assert row["ok"] is False and row["state"] == "warn"
    assert "ollama pull gemma3:12b" in row["fix"]
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({
        "/api/tags": {"models": [{"name": "gemma3:12b"}]},
    }))
    assert sp.probe_ollama()["ok"] is True


def test_ollama_untagged_model_matches_any_tag(cfg, monkeypatch):
    config.set_many({"ollama_model": "gemma3"})
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({
        "/api/tags": {"models": [{"name": "gemma3:12b"}]},
    }))
    assert sp.probe_ollama()["ok"] is True


def test_ollama_down_is_optional_and_explains(cfg, monkeypatch):
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({}))
    row = sp.probe_ollama()
    assert row["ok"] is False and row["optional"] is True and "95%" in row["fix"]


def test_whisper_off_is_not_a_failure(cfg, monkeypatch):
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({}))
    row = sp.probe_whisper()
    assert row["state"] == "off" and row["optional"]


def test_tools_missing_get_install_hint(cfg, monkeypatch):
    monkeypatch.setattr(sp, "_which", lambda b: "/usr/bin/ffmpeg" if b == "ffmpeg" else None)
    rows = {r["key"]: r for r in sp.probe_tools()}
    assert rows["tool_ffmpeg"]["ok"]
    assert rows["tool_tesseract"]["state"] == "off" and rows["tool_tesseract"]["fix"]
    # PDFs are read by PyMuPDF (E2.2) — poppler/pdftotext must not be probed,
    # or a new user is told to install something nothing uses.
    assert "tool_pdftotext" not in rows


def test_gpu_rows(cfg, monkeypatch):
    assert sp.probe_gpu()["state"] == "off"                       # no ComfyUI configured
    config.set_many({"comfyui_url": "http://comfy:8188"})
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({
        "/system_stats": {"devices": [{"vram_free": 0.4e9, "vram_total": 25e9}]},
    }))
    row = sp.probe_gpu()
    assert row["ok"] is False and "too little" in row["detail"]
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({
        "/system_stats": {"devices": [{"vram_free": 12e9, "vram_total": 25e9}]},
    }))
    assert sp.probe_gpu()["state"] == "ok"


def test_status_ready_only_when_required_rows_ok(cfg, monkeypatch):
    config.set_many({"tts_engine": "chatterbox"})
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({
        "/api/model-info": {"class_name": "ChatterboxTTS", "device": "cuda"},
        "/get_predefined_voices": [],
    }))
    monkeypatch.setattr(sp, "_which", lambda b: "/usr/bin/" + b if b == "ffmpeg" else None)
    st = sp.status()
    assert st["ready"] is True                # engine + ffmpeg ok; ollama/whisper/pdf are optional
    assert {r["key"] for r in st["rows"]} >= {"voice_engine", "ollama", "whisper", "tool_ffmpeg", "gpu"}
    monkeypatch.setattr(sp, "_which", lambda b: None)
    assert sp.status()["ready"] is False      # ffmpeg is required


# ── server wiring ────────────────────────────────────────────────────────────

def test_config_endpoints_and_engine_cache_drop(cfg, monkeypatch):
    from fastapi.testclient import TestClient
    import server
    monkeypatch.setattr(sp, "_get_json", _fake_get_json({}))
    monkeypatch.setattr(sp, "_which", lambda b: None)
    c = TestClient(server.app)

    r = c.get("/config")
    assert r.status_code == 200 and r.json()["values"]["tts_engine"] == "auto"

    server._active_engine = "say"             # pretend something was cached
    r = c.put("/config", json={"values": {"tts_engine": "stub"}})
    assert r.status_code == 200 and r.json()["values"]["tts_engine"] == "stub"
    assert server._active_engine is None      # cache dropped
    assert c.get("/engine_status").json()["engine"] == "stub"

    r = c.put("/config", json={"values": {"tts_engine": "siri"}})
    assert r.status_code == 400 and "siri" in r.json()["detail"]

    r = c.get("/setup/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False and body["config_exists"] is True
    assert any(row["key"] == "voice_engine" for row in body["rows"])
    server._active_engine = None
