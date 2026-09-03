"""
ProseCast configuration — one place, three layers (Phase E4.1).

    defaults  <  config.json  <  environment variables

`config.json` lives at the repo root (gitignored; `config.example.json` is the
tracked template). Env vars keep working exactly as before so nothing anyone
already runs breaks — they are the *override* layer, not the source of truth.

Why this exists: every URL and key used to be an env var read at import time
by five different modules, with defaults that were either "localhost" or
Tyler's home server depending on which file you opened. A stranger could not
tell what the app was pointed at, and neither could the Setup page. Now the
Setup page reads `get()` and the render/LLM modules read the same values.

Usage:
    from prosecast import config
    config.get("ollama_url")            # resolved value (env > file > default)
    config.source("ollama_url")         # "env" | "file" | "default"
    config.set_many({"ollama_url": "http://GIDEON_HOST:11434"})   # writes config.json
    config.public()                     # everything, secrets masked — for GET /config

Effective-immediately vs restart: the Setup probes call `get()` at request
time, so a saved URL is probed live. The render/LLM modules resolve their URLs
when imported (`CHATTERBOX_BASE_URL`, `OLLAMA_BASE`, ...), so *those* pick up a
changed URL on the next server start; the engine itself is re-resolved by
POST /engine_status/recheck without a restart.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

# ── Schema ───────────────────────────────────────────────────────────────────
# key → (env var that overrides it, default, is_secret)
SCHEMA: dict[str, tuple[str, object, bool]] = {
    "tts_engine":           ("PROSECAST_TTS_ENGINE",     "auto",                          False),
    "chatterbox_url":       ("CHATTERBOX_URL",           "http://localhost:8101",         False),
    "ollama_url":           ("PROSECAST_OLLAMA_URL",     "http://localhost:11434",        False),
    "ollama_model":         ("PROSECAST_OLLAMA_MODEL",   "gemma3:12b",                    False),
    "whisper_url":          ("PROSECAST_WHISPER_URL",    "http://localhost:8100",         False),
    "whisper_model":        ("PROSECAST_WHISPER_MODEL",  "Systran/faster-whisper-small",  False),
    "elevenlabs_api_key":   ("ELEVENLABS_API_KEY",       "",                              True),
    "comfyui_url":          ("COMFYUI_URL",              "",                              False),
    "gpu_reclaim_below_gb": ("COMFY_RECLAIM_BELOW_GB",   4.0,                             False),
}

ENGINES = ("auto", "chatterbox", "elevenlabs", "piper", "say", "gtts", "stub")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_lock = threading.Lock()
_file_cache: dict | None = None
_file_cache_path: Path | None = None


def config_path() -> Path:
    """Where config.json lives: PROSECAST_CONFIG overrides, else repo root."""
    override = os.environ.get("PROSECAST_CONFIG", "").strip()
    return Path(override).expanduser() if override else _REPO_ROOT / "config.json"


def _read_file() -> dict:
    global _file_cache, _file_cache_path
    path = config_path()
    with _lock:
        if _file_cache is not None and _file_cache_path == path:
            return _file_cache
        data: dict = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                data = {}          # a broken file is treated as absent, never fatal
        _file_cache, _file_cache_path = data, path
        return data


def invalidate() -> None:
    """Forget the cached file (tests, and after set_many)."""
    global _file_cache, _file_cache_path
    with _lock:
        _file_cache, _file_cache_path = None, None


def _coerce(key: str, value):
    """Env vars are strings; cast to the default's type where it matters."""
    default = SCHEMA[key][1]
    if isinstance(default, float) and not isinstance(value, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if isinstance(value, str):
        value = value.strip()
        if key.endswith("_url"):
            value = value.rstrip("/")
        if key == "tts_engine":
            value = value.lower()
    return value


def get(key: str):
    """Resolved value: env > file > default."""
    if key not in SCHEMA:
        raise KeyError(f"unknown config key: {key}")
    env_name, default, _ = SCHEMA[key]
    env_val = os.environ.get(env_name)
    if env_val is not None and env_val.strip() != "":
        return _coerce(key, env_val)
    file_val = _read_file().get(key)
    if file_val is not None and file_val != "":
        return _coerce(key, file_val)
    return default


def source(key: str) -> str:
    """Which layer `get(key)` came from — the Setup page says this out loud."""
    env_name, _, _ = SCHEMA[key]
    env_val = os.environ.get(env_name)
    if env_val is not None and env_val.strip() != "":
        return "env"
    file_val = _read_file().get(key)
    if file_val is not None and file_val != "":
        return "file"
    return "default"


def has_file() -> bool:
    return config_path().exists()


def _mask(value: str) -> str:
    """Show enough to recognise a key, never enough to use it."""
    if not value:
        return ""
    return ("•" * 8) + value[-4:] if len(value) > 4 else "•" * len(value)


def public() -> dict:
    """Everything resolved, secrets masked, with per-key source. For GET /config."""
    out = {"path": str(config_path()), "exists": has_file(), "values": {}, "sources": {}}
    for key, (_env, _default, secret) in SCHEMA.items():
        val = get(key)
        out["values"][key] = _mask(val) if secret else val
        out["sources"][key] = source(key)
    out["values"]["elevenlabs_api_key_set"] = bool(get("elevenlabs_api_key"))
    return out


def validate(updates: dict) -> dict:
    """Return cleaned updates or raise ValueError with a human sentence."""
    clean: dict = {}
    for key, value in updates.items():
        if key not in SCHEMA:
            raise ValueError(f"'{key}' is not a setting ProseCast knows about")
        if value is None:
            clean[key] = ""
            continue
        value = _coerce(key, value)
        if key == "tts_engine" and value not in ENGINES:
            raise ValueError(f"engine must be one of {', '.join(ENGINES)} (got '{value}')")
        if key.endswith("_url") and value and not str(value).startswith(("http://", "https://")):
            raise ValueError(f"{key} must start with http:// or https:// (got '{value}')")
        if key == "gpu_reclaim_below_gb" and not (0 <= float(value) <= 64):
            raise ValueError("gpu_reclaim_below_gb must be between 0 and 64")
        clean[key] = value
    return clean


def set_many(updates: dict) -> dict:
    """Merge validated updates into config.json (created if missing).

    A masked secret coming back from the UI ("••••••••abcd") is ignored so a
    Save on the Setup page never overwrites a real key with its own mask.
    """
    clean = validate(updates)
    path = config_path()
    current = dict(_read_file())
    for key, value in clean.items():
        if SCHEMA[key][2] and isinstance(value, str) and value.startswith("•"):
            continue
        if value == "" or value == SCHEMA[key][1]:
            current.pop(key, None)          # back to default → don't pin it in the file
        else:
            current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)               # it may hold an API key
    except OSError:
        pass
    invalidate()
    return public()


def shadowed_by_env() -> list[str]:
    """Keys set in config.json but currently overridden by an env var — the
    Setup page warns about these, because editing the file would do nothing."""
    data = _read_file()
    return [k for k in data if k in SCHEMA and source(k) == "env"]
