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
  6. Warn-only: unresolved blocks (render as narrator), chapters already
     rendered (will be skipped)
"""
from __future__ import annotations

import json
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
        info = _fetch_model_info()
        if info is None:
            rep.abort(
                f"Chatterbox server unreachable at {tts.CHATTERBOX_BASE_URL} "
                "— is Tailscale up and the container running? "
                "(sudo docker start chatterbox-tts on Goldeye)")
            return rep  # everything else depends on the server
        rep.details["model_info"] = info
        model_sig = (str(info.get("type", "")) + str(info.get("class_name", ""))).lower()
        if "turbo" in model_sig:
            rep.abort(
                "Chatterbox is running the TURBO model — exaggeration/cfg are "
                "silently ignored and a whole overnight render comes out flat. "
                "Switch the server to the base ResembleAI/chatterbox model first.")

    # -- 3: voice_map exists --------------------------------------------------
    vm_path = lib.voice_map_path(book_slug)
    if not vm_path.exists():
        rep.abort(
            f"No voice_map.json for '{book_slug}' — cast the book in the UI "
            "before a batch render (the auto round-robin fallback is never "
            "what you want overnight).")
        return rep
    try:
        vm = json.loads(vm_path.read_text())
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

    # -- 6: warn-only informational checks ------------------------------------
    ir_path = lib.ir_path(book_slug)
    if ir_path.exists():
        try:
            ir = json.loads(ir_path.read_text())
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
