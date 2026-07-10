#!/usr/bin/env python3
"""
chatterbox_smoke.py — render ONE line through the Chatterbox backend and listen.

The Phase A gate: Tyler runs this, opens output/chatterbox_smoke.wav, and decides
whether Chatterbox quality is good enough to build the cast screen around.

Usage:
    .venv/bin/python scripts/chatterbox_smoke.py
    .venv/bin/python scripts/chatterbox_smoke.py --text "You can't be serious." --emotion angry
    .venv/bin/python scripts/chatterbox_smoke.py --voice Gianna.wav --emotion calm

Args:
    --text     line to synthesize (default: a short sample line)
    --voice    reference/predefined filename. Default: first entry from
               /get_reference_files, else the first predefined voice. Works
               whether or not the VCTK clips have been uploaded yet.
    --emotion  one of the presets below (default "neutral"); anything else is
               treated as a free-text emotion phrase at medium intensity.

Reads the server at $CHATTERBOX_URL (default http://GIDEON_HOST:8101).
This is READ + render only — it never POSTs to any server-state endpoint.
"""

import argparse
import sys
from pathlib import Path

# Make `prosecast` importable when run as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast.tag_mapper import map_tags
from prosecast.tts_engine import (
    _synthesize_chatterbox,
    test_chatterbox_connection,
    fetch_chatterbox_references,
    fetch_chatterbox_predefined,
)

# emotion preset → abstract IR tags (intensity/pace/emotion). Free-text emotions
# fall through to a medium-intensity, measured default.
_EMOTION_PRESETS = {
    "neutral":  {"intensity": 0.5, "pace": "measured", "emotion": "neutral"},
    "calm":     {"intensity": 0.3, "pace": "slow",     "emotion": "calm reserve"},
    "sad":      {"intensity": 0.4, "pace": "slow",     "emotion": "quiet grief"},
    "excited":  {"intensity": 0.8, "pace": "brisk",    "emotion": "bright excitement"},
    "angry":    {"intensity": 0.9, "pace": "urgent",   "emotion": "hot anger"},
    "afraid":   {"intensity": 0.8, "pace": "urgent",   "emotion": "rising fear"},
}


def _resolve_voice(voice_arg):
    """Return (voice_mode, filename) — honoring --voice, else auto-picking.

    Falls back from clone references to predefined voices so the smoke test works
    before any VCTK clips are uploaded.
    """
    refs = fetch_chatterbox_references() or []
    predefined = fetch_chatterbox_predefined() or []
    predefined_files = [p.get("filename") for p in predefined if p.get("filename")]

    if voice_arg:
        if voice_arg in predefined_files and voice_arg not in refs:
            return "predefined", voice_arg
        # Default an explicit --voice to clone mode (reference filename).
        return "clone", voice_arg

    if refs:
        return "clone", refs[0]
    if predefined_files:
        return "predefined", predefined_files[0]
    return None, None


def main():
    ap = argparse.ArgumentParser(description="Render one Chatterbox line to listen to.")
    ap.add_argument("--text", default="This is a ProseCast Chatterbox smoke test. If you can hear me, the backend works.",
                    help="line to synthesize")
    ap.add_argument("--voice", default="", help="reference/predefined filename (default: auto)")
    ap.add_argument("--emotion", default="neutral",
                    help="emotion preset (neutral/calm/sad/excited/angry/afraid) or a free-text phrase")
    ap.add_argument("--out", default="output/chatterbox_smoke.wav", help="output WAV path")
    args = ap.parse_args()

    if not test_chatterbox_connection():
        print("Chatterbox server not reachable — aborting. Check Tailscale / CHATTERBOX_URL.")
        sys.exit(1)

    voice_mode, filename = _resolve_voice(args.voice)
    if not filename:
        print("No reference or predefined voices available on the server — upload one first "
              "(scripts/stage_vctk_voices.py) or check the server.")
        sys.exit(1)

    tags = _EMOTION_PRESETS.get(args.emotion.lower(),
                                {"intensity": 0.5, "pace": "measured", "emotion": args.emotion})
    tag_params = map_tags(tags, "chatterbox")

    voice_cfg = {"voice_mode": voice_mode, "_tag_params": tag_params}
    if voice_mode == "clone":
        voice_cfg["reference_audio_filename"] = filename
    else:
        voice_cfg["predefined_voice_id"] = filename

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[smoke] voice={filename} ({voice_mode})  emotion={args.emotion}  "
          f"tag_params={tag_params}")
    print(f"[smoke] text: {args.text!r}")

    ok = _synthesize_chatterbox(args.text, voice_cfg, str(out_path))
    if not ok:
        print("[smoke] render FAILED — see server body above.")
        sys.exit(1)

    print(f"\n[smoke] ✓ wrote {out_path.resolve()}")
    print("[smoke] Listen to it — that's the Phase A gate.")


if __name__ == "__main__":
    main()
