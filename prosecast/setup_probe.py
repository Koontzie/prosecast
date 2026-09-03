"""
Setup probes — "is this machine ready, and if not, what exactly is missing?"
(Phase E4.2)

Every row answers three questions a stranger can act on:
    ok      bool   — green or not
    state   str    — "ok" | "warn" | "missing" | "off"   (off = optional and not configured)
    detail  str    — what we actually found ("ChatterboxTTS · cuda · 34 voices")
    fix     str    — one sentence that tells you what to do about it

URLs are read from prosecast.config at *call* time, so the Setup page can
save a URL and re-probe without a restart. Network probes are short-timeout
and never raise. Everything here is monkeypatchable for offline tests:
`_get_json`, `_which`, `_el_user`.
"""

from __future__ import annotations

import json
import platform
import shutil
import urllib.error
import urllib.request

from prosecast import config

# ── tiny helpers (mock points) ───────────────────────────────────────────────

def _get_json(url: str, timeout: float = 4.0, headers: dict | None = None):
    """GET → parsed JSON, or None on any failure. Never raises."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def _el_user(key: str):
    """ElevenLabs /v1/user/subscription → dict, "unauthorized", or None."""
    try:
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": key},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode()) if resp.status == 200 else None
    except urllib.error.HTTPError as e:
        return "unauthorized" if e.code in (401, 403) else None
    except Exception:
        return None


def _row(key: str, label: str, ok: bool, state: str, detail: str, fix: str = "",
         optional: bool = False, **extra) -> dict:
    return {"key": key, "label": label, "ok": ok, "state": state, "detail": detail,
            "fix": fix, "optional": optional, **extra}


_OS = platform.system()          # "Darwin" | "Linux" | "Windows"


def _install_hint(pkg: str, brew: str | None = None, apt: str | None = None,
                  win: str | None = None) -> str:
    brew = brew or pkg
    apt = apt or pkg
    if _OS == "Darwin":
        return f"macOS: `brew install {brew}`"
    if _OS == "Windows":
        return win or f"Windows: install {pkg} and make sure it is on your PATH"
    return f"Linux: `sudo apt install {apt}` (or your distro's equivalent)"


# ── probes ───────────────────────────────────────────────────────────────────

def probe_voice_engine() -> dict:
    engine = config.get("tts_engine")
    src = config.source("tts_engine")
    where = {"env": "set by environment variable", "file": "set in config.json",
             "default": "not chosen yet"}[src]

    if engine == "auto":
        return _row("voice_engine", "Voice engine", False, "warn",
                    "auto-detect (" + where + ")",
                    "Pick an engine below. Auto-detect picks ElevenLabs whenever a key is "
                    "present — which makes every preview cost credits — so ProseCast asks "
                    "you to choose on purpose.")

    if engine == "chatterbox":
        base = config.get("chatterbox_url")
        mi = _get_json(base + "/api/model-info", timeout=6.0)
        if mi is None:
            return _row("voice_engine", "Voice engine", False, "missing",
                        f"Chatterbox · {base} · not responding",
                        "Start the Chatterbox TTS server (or fix the URL). If it runs on "
                        "another machine, make sure this one can reach it — a VPN like "
                        "Tailscale that isn't connected is the usual reason.",
                        engine=engine, endpoint=base)
        model = mi.get("class_name") or mi.get("type") or "?"
        device = mi.get("device") or "?"
        voices = _get_json(base + "/get_predefined_voices", timeout=6.0)
        n_voices = len(voices) if isinstance(voices, list) else 0
        detail = f"Chatterbox · {model} · {device} · {n_voices} voices"
        if "turbo" in (str(mi.get("type", "")) + str(mi.get("class_name", ""))).lower():
            return _row("voice_engine", "Voice engine", False, "warn", detail + " · TURBO",
                        "The Turbo model ignores emotion controls, so every line reads flat. "
                        "Load the base ('original') Chatterbox model on the server.",
                        engine=engine, endpoint=base)
        if device == "cpu":
            return _row("voice_engine", "Voice engine", True, "warn", detail,
                        "Chatterbox is running on CPU — it works, but expect roughly "
                        "10× slower renders than on a GPU.",
                        engine=engine, endpoint=base)
        return _row("voice_engine", "Voice engine", True, "ok", detail, "",
                    engine=engine, endpoint=base)

    if engine == "elevenlabs":
        key = config.get("elevenlabs_api_key")
        if not key:
            return _row("voice_engine", "Voice engine", False, "missing",
                        "ElevenLabs · no API key",
                        "Paste your ElevenLabs API key below (Profile → API Keys on "
                        "elevenlabs.io). It's your account and your bill — ProseCast "
                        "never marks anything up.", engine=engine)
        sub = _el_user(key)
        if sub == "unauthorized":
            return _row("voice_engine", "Voice engine", False, "missing",
                        "ElevenLabs · key rejected",
                        "ElevenLabs didn't accept that key. Generate a new one on "
                        "elevenlabs.io and paste it again.", engine=engine)
        if not isinstance(sub, dict):
            return _row("voice_engine", "Voice engine", False, "missing",
                        "ElevenLabs · could not reach api.elevenlabs.io",
                        "Check your internet connection — ElevenLabs is a cloud service.",
                        engine=engine)
        used = sub.get("character_count", 0)
        limit = sub.get("character_limit", 0)
        left = max(0, limit - used)
        tier = sub.get("tier", "?")
        return _row("voice_engine", "Voice engine", True, "ok",
                    f"ElevenLabs · {tier} plan · {left:,} of {limit:,} credits left this cycle",
                    "Heads up: a full novel is ~500,000 characters. Chatterbox (free, local) "
                    "is the better fit for whole books." if left < 200_000 else "",
                    engine=engine)

    if engine == "say":
        if _OS != "Darwin" or not _which("say"):
            return _row("voice_engine", "Voice engine", False, "missing",
                        "macOS system voices · not available on this OS",
                        "'say' only exists on macOS. Choose Piper (free, any OS) or Chatterbox.",
                        engine=engine)
        return _row("voice_engine", "Voice engine", True, "ok",
                    "macOS system voices (say) · no GPU needed",
                    "Fine for checking that everything works; robotic for a whole book. "
                    "Chatterbox is the free upgrade.", engine=engine)

    if engine == "piper":
        if not _which("piper"):
            return _row("voice_engine", "Voice engine", False, "missing",
                        "Piper · not installed",
                        "Install Piper TTS (`pip install piper-tts`) and download at least one "
                        "voice model (.onnx) from the Piper voices page.", engine=engine)
        return _row("voice_engine", "Voice engine", True, "ok",
                    "Piper (local, CPU) · no GPU needed", "", engine=engine)

    if engine == "gtts":
        return _row("voice_engine", "Voice engine", True, "warn",
                    "Google TTS (cloud) · one voice, needs internet",
                    "Works for a quick test; not suitable for multi-voice books.", engine=engine)

    return _row("voice_engine", "Voice engine", engine == "stub", "warn" if engine == "stub" else "missing",
                f"{engine}", "The stub engine writes silent audio — for tests only." if engine == "stub"
                else f"'{engine}' is not an engine ProseCast knows.", engine=engine)


def probe_ollama() -> dict:
    base = config.get("ollama_url")
    model = config.get("ollama_model")
    tags = _get_json(base + "/api/tags", timeout=4.0)
    if tags is None:
        return _row("ollama", "Who's speaking (local AI)", False, "missing",
                    f"Ollama · {base} · not responding",
                    "Install Ollama from ollama.com and start it, or point the URL at a "
                    "machine that runs it. Without it, ProseCast still attributes ~95% of "
                    "lines by rules — the AI pass only handles the hard ones.",
                    optional=True, endpoint=base, model=model)
    names = [m.get("name", "") for m in tags.get("models", []) if isinstance(m, dict)]
    # exact match, or an untagged name ("gemma3") matching any tag of it ("gemma3:12b")
    have = model in names or (":" not in model and any(n.split(":")[0] == model for n in names))
    if not have:
        return _row("ollama", "Who's speaking (local AI)", False, "warn",
                    f"Ollama · {base} · {len(names)} models, '{model}' not pulled",
                    f"Run `ollama pull {model}` on the Ollama machine (about 8 GB for gemma3:12b).",
                    optional=True, endpoint=base, model=model, models=names)
    return _row("ollama", "Who's speaking (local AI)", True, "ok",
                f"Ollama · {base} · {model} ready ({len(names)} models)", "",
                optional=True, endpoint=base, model=model, models=names)


def probe_whisper() -> dict:
    base = config.get("whisper_url")
    model = config.get("whisper_model")
    # faster-whisper-server is OpenAI-compatible; /v1/models is the cheap probe.
    models = _get_json(base + "/v1/models", timeout=4.0)
    if models is None:
        return _row("whisper", "Read-along timing (whisper)", False, "off",
                    f"whisper · {base} · not responding",
                    "Optional. Without it the read-along highlights by sentence (estimated) "
                    "instead of by word. To enable, run a faster-whisper server "
                    "(OpenAI-compatible) and set its URL.",
                    optional=True, endpoint=base, model=model)
    return _row("whisper", "Read-along timing (whisper)", True, "ok",
                f"whisper · {base} · {model}", "", optional=True, endpoint=base, model=model)


def probe_tools() -> list[dict]:
    rows = []
    for binary, label, why, optional, hint in (
        ("ffmpeg", "ffmpeg", "needed for M4B export and voice-clip prep", False,
         _install_hint("ffmpeg", win="Windows: download from ffmpeg.org and add it to PATH")),
        ("pdftotext", "pdftotext (poppler)", "needed to read PDFs", True,
         _install_hint("poppler", brew="poppler", apt="poppler-utils",
                       win="Windows: install poppler (e.g. from the poppler-windows releases) and add its bin/ to PATH")),
        ("tesseract", "tesseract (OCR)", "needed only for scanned PDFs", True,
         _install_hint("tesseract", apt="tesseract-ocr")),
    ):
        path = _which(binary)
        if path:
            rows.append(_row("tool_" + binary, label, True, "ok", path, "", optional=optional))
        else:
            rows.append(_row("tool_" + binary, label, False, "off" if optional else "missing",
                             f"not found · {why}", hint, optional=optional))
    return rows


def probe_gpu() -> dict:
    base = config.get("comfyui_url")
    if not base:
        return _row("gpu", "GPU headroom", True, "off", "no ComfyUI configured — not monitored",
                    "Optional. If ComfyUI shares the GPU with Chatterbox, set its URL and "
                    "ProseCast will check free VRAM (and reclaim it) before every render.",
                    optional=True)
    stats = _get_json(base + "/system_stats", timeout=4.0)
    try:
        dev = stats["devices"][0]
        free = dev["vram_free"] / 1e9
        total = dev["vram_total"] / 1e9
    except Exception:
        return _row("gpu", "GPU headroom", True, "warn",
                    f"ComfyUI · {base} · no GPU stats",
                    "ComfyUI didn't answer — the pre-render VRAM check will be skipped "
                    "(renders still run).", optional=True, endpoint=base)
    reclaim = float(config.get("gpu_reclaim_below_gb"))
    detail = f"{free:.1f} of {total:.1f} GB free"
    if free < 1.5:
        return _row("gpu", "GPU headroom", False, "warn", detail + " · too little to render",
                    "Something is holding the card. ProseCast will try to reclaim from an "
                    "idle ComfyUI before rendering; otherwise check `nvidia-smi`.",
                    optional=True, endpoint=base)
    if free < reclaim:
        return _row("gpu", "GPU headroom", True, "warn", detail + " · tight",
                    "Enough to start; anything else loading a model mid-render will break it.",
                    optional=True, endpoint=base)
    return _row("gpu", "GPU headroom", True, "ok", detail, "", optional=True, endpoint=base)


# ── the one call the Setup page makes ────────────────────────────────────────

def status() -> dict:
    # Probes run in parallel: with every service down, the sequential worst
    # case was ~30 s of timeouts; now it's the slowest single probe (~6 s).
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_engine = pool.submit(probe_voice_engine)
        f_ollama = pool.submit(probe_ollama)
        f_whisper = pool.submit(probe_whisper)
        f_tools = pool.submit(probe_tools)
        f_gpu = pool.submit(probe_gpu)
        rows = [f_engine.result(), f_ollama.result(), f_whisper.result(),
                *f_tools.result(), f_gpu.result()]
    required_ok = all(r["ok"] for r in rows if not r["optional"])
    return {
        "ready": required_ok,
        "os": _OS,
        "config_path": str(config.config_path()),
        "config_exists": config.has_file(),
        "shadowed_by_env": config.shadowed_by_env(),
        "rows": rows,
    }
