#!/usr/bin/env python3
"""
audition_voices.py — render one audition line through every predefined voice on
the Chatterbox server, into numbered files for easy picking.

Resumable: skips files that already exist, so re-running continues where it
stopped. Output: output/audition/NN_<voice>.wav + a manifest.txt index.

Usage:
    python3 scripts/audition_voices.py
    python3 scripts/audition_voices.py --text "Custom line here."
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast.tts_engine import _synthesize_chatterbox, fetch_chatterbox_predefined

# Server-side test artifacts, not real voices.
_SKIP = re.compile(r"cachetest|selftest|scanprobe", re.IGNORECASE)

DEFAULT_TEXT = ("The rain had stopped by the time she reached the crossroads, "
                "and somewhere beyond the hills, a bell began to ring.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--out-dir", default="output/audition")
    args = ap.parse_args()

    voices = fetch_chatterbox_predefined() or []
    files = sorted({v.get("filename") for v in voices if v.get("filename")})
    files = [f for f in files if not _SKIP.search(f)]
    if not files:
        print("No predefined voices found on the server.")
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    done = skipped = failed = 0
    for n, fname in enumerate(files, start=1):
        stem = Path(fname).stem
        out = out_dir / f"{n:02d}_{stem}.wav"
        manifest.append(f"{n:02d}  {stem}")
        if out.exists() and out.stat().st_size > 1000:
            skipped += 1
            continue
        cfg = {"voice_mode": "predefined", "predefined_voice_id": fname,
               "_tag_params": {"exaggeration": 0.55}}
        if _synthesize_chatterbox(args.text, cfg, str(out)):
            done += 1
            print(f"  ✓ {out.name}")
        else:
            failed += 1
            print(f"  ✗ {out.name} FAILED")

    (out_dir / "manifest.txt").write_text("\n".join(manifest) + "\n")
    total = len(files)
    print(f"\n[Audition] {done} rendered, {skipped} already done, {failed} failed — "
          f"{skipped + done}/{total} total. Re-run to continue if incomplete.")


if __name__ == "__main__":
    main()
