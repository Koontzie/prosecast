"""Pre-flight checks for batch renders (Phase C0).

Run before ANY whole-book / queued render — server queue worker and CLI runner
both call this. Every known overnight failure mode either aborts loudly here,
before synthesis starts, or is downgraded to an explicit warning.

Checks (chatterbox engine; others get the static-pool subset):
  1. Server reachable        (fast timeout — off-Tailscale fails in seconds)
  2. Model is base, not turbo (turbo silently ignores exaggeration/cfg)
  3. voice_map.json exists    (mapless batch render is never intended)
  4. voice_map engine matches the active engine (stale-EL-map landmine)
  5. Every mapped voice resolvable on the server / in the engine pool
  6. GPU has headroom — and reclaim it from an idle ComfyUI first. Chatterbox
     reports loaded:true even when the card is full, then fails every chunk
     with a 500, so this is invisible without an explicit check.
  7. Warn-only: unresolved blocks (render as narrator), chapters already
     rendered (will be skipped)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from prosecast import library as lib
from prosecast import tts_engine as tts


@dataclass
class PreflightReport:
    ok: bool = True
    aborts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def abort(self, msg: str):
        self.ok = False
        self.aborts.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)

    def summary(self) -> str:
        lines = []
        for a in self.aborts:
            lines.append(f"ABORT: {a}")
        for w in self.warnings:
            lines.append(f"warn:  {w}")
        if not lines:
            lines.append("preflight OK")
        return "\n".join(lines)


def _fetch_model_info(timeout: float = 4.0):
    """GET /api/model-info. Returns dict or None. Separate function so tests
    can monkeypatch it."""
    try:
        with urllib.request.urlopen(tts.CHATTERBOX_MODEL_INFO_URL, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ── GPU headroom ──────────────────────────────────────────────────────────────
#
# 2026-09-02: every Chatterbox synthesis returned
#   500 {"detail":"TTS engine failed to synthesize audio for chunk 1."}
# while /api/model-info cheerfully reported {"loaded": true, "device": "cuda"}.
# The card was simply full — ComfyUI had been holding a Wan2.2 video model
# resident since its last job 27 days earlier (it never unloads on its own).
# `loaded` means "was loaded once", NOT "can allocate for inference", so the
# only reliable signal is free VRAM. ComfyUI's /system_stats reports
# device-level free VRAM across ALL processes, which is what we want.

from prosecast import config as _config

COMFY_BASE_URL = _config.get("comfyui_url")          # "" = no ComfyUI → VRAM check skipped

MIN_FREE_VRAM_GB = 1.5        # below this, synthesis will fail — abort
COMFY_RECLAIM_BELOW_GB = float(_config.get("gpu_reclaim_below_gb"))  # reclaim from ComfyUI below this


def _get_json(url: str, timeout: float = 6.0):
    """GET url -> parsed JSON, or None. Separate so tests can monkeypatch."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _free_vram_gb(timeout: float = 6.0):
    """Free VRAM in GB across all processes, or None if unavailable."""
    stats = _get_json(COMFY_BASE_URL + "/system_stats", timeout=timeout)
    if not stats:
        return None
    for dev in stats.get("devices", []) or []:
        if "vram_free" in dev:
            return dev["vram_free"] / 1e9
    return None


def _comfy_idle(timeout: float = 6.0) -> bool:
    """True only if ComfyUI is definitely idle. Unknown == not idle: never
    free the card out from under someone else's running job."""
    q = _get_json(COMFY_BASE_URL + "/queue", timeout=timeout)
    if q is None:
        return False
    return not q.get("queue_running") and not q.get("queue_pending")


def _comfy_free(timeout: float = 20.0) -> bool:
    """Ask ComfyUI to unload its models and release VRAM."""
    try:
        req = urllib.request.Request(
            COMFY_BASE_URL + "/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _check_gpu_headroom(rep) -> None:
    """Abort if the card has no room to synthesize; reclaim from idle ComfyUI
    first. Never aborts on a failed probe — a missing ComfyUI is not a reason
    to block a Chatterbox render."""
    if not COMFY_BASE_URL:
        return                      # no ComfyUI configured: nothing to probe, nothing to warn about
    free = _free_vram_gb()
    if free is None:
        rep.warn("could not read GPU stats from ComfyUI "
                 f"({COMFY_BASE_URL}/system_stats) — skipping the VRAM check.")
        return

    rep.details["vram_free_gb_before"] = round(free, 2)

    if free < COMFY_RECLAIM_BELOW_GB:
        if _comfy_idle():
            if _comfy_free():
                time.sleep(3)
                reclaimed = _free_vram_gb()
                if reclaimed is not None:
                    rep.warn(f"reclaimed VRAM from idle ComfyUI: "
                             f"{free:.1f} GB -> {reclaimed:.1f} GB free.")
                    free = reclaimed
            else:
                rep.warn("ComfyUI /free call failed — could not reclaim VRAM.")
        else:
            rep.warn("ComfyUI is busy (or unreachable) — not touching its "
                     "models; a running job would be killed.")

    rep.details["vram_free_gb"] = round(free, 2)

    if free < MIN_FREE_VRAM_GB:
        rep.abort(
            f"Only {free:.1f} GB VRAM free — Chatterbox will report "
            "loaded:true and then fail every chunk with a 500. Free the card "
            "before rendering: check `nvidia-smi` on Goldeye for what is "
            "holding it, and remember ComfyUI keeps its last model resident "
            "indefinitely (POST /free), while Ollama unloads on its own "
            "timer.")
    elif free < COMFY_RECLAIM_BELOW_GB:
        rep.warn(f"only {free:.1f} GB VRAM free — enough to start, but "
                 "anything else pulling a model mid-render will break it.")


def _static_pool(engine: str) -> list:
    """Voice IDs for non-chatterbox engines (static pools)."""
    va = tts.VoiceAssigner
    if engine == "elevenlabs":
        return [v["id"] for v in va.ELEVENLABS_VOICES]
    if engine == "say":
        return list(va.SAY_VOICES)
    if engine == "piper":
        return list(va.PIPER_VOICES)
    if engine == "gtts":
        return [v["tld"] for v in va.GTTS_VOICES]
    return []


def preflight(book_slug: str, engine: str) -> PreflightReport:
    rep = PreflightReport()
    rep.details["engine"] = engine

    # -- 1 & 2: server reachable + base model (chatterbox only) ---------------
    if engine == "chatterbox":
        # The shared server answers one request at a time; mid-synthesis it can
        # be slow to respond without being down. Be patient before aborting.
        info = None
        for attempt in range(3):
            info = _fetch_model_info(timeout=10.0)
            if info is not None:
                break
            if attempt < 2:
                time.sleep(2)
        if info is None:
            rep.abort(
                f"Chatterbox server not responding at {tts.CHATTERBOX_BASE_URL} "
                "— either down (Tailscale? container? -> sudo docker start "
                "chatterbox-tts on Goldeye) or busy grinding orphaned work "
                "from a killed run (-> sudo docker restart chatterbox-tts, "
                "or wait a few minutes and re-run).")
            return rep  # everything else depends on the server
        rep.details["model_info"] = info
        model_sig = (str(info.get("type", "")) + str(info.get("class_name", ""))).lower()
        if "turbo" in model_sig:
            rep.abort(
                "Chatterbox is running the TURBO model — exaggeration/cfg are "
                "silently ignored and a whole overnight render comes out flat. "
                "Switch the server to the base ResembleAI/chatterbox model first.")

        # -- 6: the card must have room to actually run inference -------------
        _check_gpu_headroom(rep)

    # -- 3: voice_map exists --------------------------------------------------
    vm_path = lib.voice_map_path(book_slug)
    if not vm_path.exists():
        rep.abort(
            f"No voice_map.json for '{book_slug}' — cast the book in the UI "
            "before a batch render (the auto round-robin fallback is never "
            "what you want overnight).")
        return rep
    try:
        vm = json.loads(vm_path.read_text(encoding="utf-8"))
    except Exception as e:
        rep.abort(f"voice_map.json unreadable: {e}")
        return rep

    # -- 4: engine match ------------------------------------------------------
    vm_engine = (vm.get("engine") or "").strip().lower()
    if vm_engine and vm_engine != engine:
        rep.abort(
            f"voice_map engine is '{vm_engine}' but the active engine is "
            f"'{engine}'. Rendering would fall through to wrong-engine voice "
            "IDs (the stale-ElevenLabs-map landmine). Archive this voice_map "
            "(e.g. mv voice_map.json voice_map.{vm_engine}.bak) and re-cast "
            "via the cast drawer.")
        return rep

    # -- 5: every voice resolvable -------------------------------------------
    mapping = vm.get("map", {}) or {}
    if engine == "chatterbox":
        predefined = {v.get("filename") for v in (tts.fetch_chatterbox_predefined() or [])}
        references = set(tts.fetch_chatterbox_references() or [])
        missing = []
        for char, voice_id in mapping.items():
            if isinstance(voice_id, dict):
                voice_id = voice_id.get("id", "")
            if not isinstance(voice_id, str) or not voice_id:
                missing.append(f"{char} -> {voice_id!r} (unparseable)")
            elif voice_id.startswith("predefined:"):
                if voice_id.split(":", 1)[1] not in predefined:
                    missing.append(f"{char} -> {voice_id} (not in predefined voices)")
            elif voice_id not in references:
                missing.append(f"{char} -> {voice_id} (no such reference clip on server)")
        if missing:
            rep.abort(
                "voice_map entries not resolvable on the Chatterbox server "
                "(voices swapped/deleted on the shared box?): "
                + "; ".join(missing[:8])
                + (f" … and {len(missing)-8} more" if len(missing) > 8 else ""))
    else:
        pool = set(_static_pool(engine))
        missing = [f"{c} -> {v}" for c, v in mapping.items()
                   if pool and isinstance(v, str) and v not in pool]
        if missing:
            rep.abort(f"voice_map entries not in the {engine} pool: "
                      + "; ".join(missing[:8]))

    # -- 7: warn-only informational checks ------------------------------------
    ir_path = lib.ir_path(book_slug)
    if ir_path.exists():
        try:
            ir = json.loads(ir_path.read_text(encoding="utf-8"))
            unresolved = ir.get("unresolved_count", 0)
            if unresolved:
                rep.warn(f"{unresolved} unresolved blocks — they render with "
                         "the narrator voice.")
            done = [ch.get("index", i) for i, ch in enumerate(ir.get("chapters", []))
                    if lib.chapter_wav_path(book_slug, ch.get("index", i)).exists()]
            if done:
                rep.warn(f"{len(done)} chapter(s) already rendered — they'll "
                         f"be skipped unless force is set: {done[:12]}")
            rep.details["chapters_total"] = len(ir.get("chapters", []))
            rep.details["chapters_done"] = done
        except Exception as e:
            rep.warn(f"could not inspect ir.json for informational checks: {e}")
    else:
        rep.abort(f"No ir.json for '{book_slug}'.")

    return rep
