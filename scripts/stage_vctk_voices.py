#!/usr/bin/env python3
"""
stage_vctk_voices.py — pull clean, distinct VCTK reference clips for Chatterbox cloning.

Streams the VCTK corpus from Hugging Face, picks N distinct speakers (with a gender mix),
builds a ~12s silence-trimmed reference clip per speaker (concatenating short utterances),
and saves them as WAVs you can audition. Optionally uploads straight to the devnen
Chatterbox-TTS-Server via POST /upload_reference.

Source: Milana/resampled_16KHrz_vctk_speakers_split  (48 kHz `audio` column)
        = the CSTR VCTK Corpus, license CC BY 4.0.

RECOMMENDED FLOW:
  1) Save + listen first (default):   python scripts/stage_vctk_voices.py --n 15
  2) Cull any you don't like in ./vctk_voices/
  3) Upload the keepers:              python scripts/stage_vctk_voices.py --from-dir ./vctk_voices \
                                          --upload-to http://GIDEON_HOST:8101

Deps (light, no torch/librosa):  pip install datasets soundfile numpy requests
"""

import argparse
import io
import sys
from collections import defaultdict
from pathlib import Path

REPO = "Milana/resampled_16KHrz_vctk_speakers_split"
LICENSE_NOTE = (
    "Reference voices derived from the CSTR VCTK Corpus (CC BY 4.0).\n"
    "Source: https://datashare.ed.ac.uk/handle/10283/3443\n"
    "Attribution required for distribution. These are REAL speakers recorded for research —\n"
    "'consented for research' is not 'consented for cloning in a shipped product'. Fine for a\n"
    "private dogfood test; check consent / right-of-publicity before shipping cloned voices.\n"
)


def trim_silence(x, sr, thresh_db=-40, pad_ms=50):
    import numpy as np
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = x.astype("float32")
    amp = np.abs(x)
    if amp.max() <= 0:
        return x
    thr = (10 ** (thresh_db / 20.0)) * amp.max()
    idx = np.where(amp > thr)[0]
    if idx.size == 0:
        return x
    pad = int(sr * pad_ms / 1000.0)
    return x[max(0, idx[0] - pad): min(len(x), idx[-1] + pad)]


def do_pull(args):
    import numpy as np
    import soundfile as sf
    from datasets import load_dataset, Audio

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Streaming VCTK ({args.split}) from Hugging Face — this can take a few minutes\n"
          f"and pull a couple GB before it has enough speakers. Progress below:\n", flush=True)
    ds = load_dataset(REPO, split=args.split, streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))  # decode bytes ourselves -> no torchcodec dep

    buf = defaultdict(list)      # speaker_id -> [np arrays]
    meta = {}                    # speaker_id -> (gender, accent)
    done = set()
    seen_rows = 0
    target_sr = None

    for row in ds:
        seen_rows += 1
        if seen_rows % 500 == 0:
            print(f"   …scanned {seen_rows} utterances, {len(done)}/{args.n} voices ready", flush=True)
        sid = row.get("speaker_id") or "unknown"
        if sid in done:
            continue
        a = row.get("audio") or {}
        raw = a.get("bytes")
        if not raw:
            continue
        try:
            data, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        except Exception:
            continue
        target_sr = sr
        clip = trim_silence(data, sr)
        if clip.size < sr * 0.8:      # skip too-short / broken
            continue
        buf[sid].append(clip)
        meta[sid] = (row.get("gender", "?") or "?",
                     (row.get("accent") or "na").replace(" ", "_"))
        total_s = sum(c.size for c in buf[sid]) / sr
        if total_s >= args.seconds:
            gap = np.zeros(int(sr * 0.25), dtype="float32")
            pieces = []
            for c in buf[sid]:
                pieces.append(c); pieces.append(gap)
            full = np.concatenate(pieces)[: int(args.seconds * sr)]
            g, acc = meta[sid]
            name = f"vctk_{sid}_{g}_{acc}.wav"
            sf.write(out / name, full, sr)
            done.add(sid)
            print(f"   ✓ {name}  ({total_s:.1f}s)", flush=True)
            if len(done) >= args.n:
                break

    (out / "ATTRIBUTION.txt").write_text(LICENSE_NOTE, encoding="utf-8")
    print(f"\nSaved {len(done)} reference clips to {out}/  (sr={target_sr} Hz)")
    print("Listen to them, delete any you don't want, then re-run with --from-dir + --upload-to.")
    return out


def do_upload(src_dir, base_url):
    import requests
    base = base_url.rstrip("/")
    wavs = sorted(Path(src_dir).glob("vctk_*.wav"))
    if not wavs:
        print(f"No vctk_*.wav files in {src_dir}"); return
    print(f"Uploading {len(wavs)} clips to {base}/upload_reference …")
    for w in wavs:
        with open(w, "rb") as f:
            try:
                r = requests.post(f"{base}/upload_reference",
                                  files={"files": (w.name, f, "audio/wav")}, timeout=60)
            except Exception as e:
                print(f"  {w.name}: ERROR {e}"); continue
        note = "" if r.status_code == 200 else f"  <-- body: {r.text[:200]}"
        print(f"  {w.name}: HTTP {r.status_code}{note}")
    # verify
    try:
        r = requests.get(f"{base}/get_reference_files", timeout=30)
        print(f"\nServer now reports reference files: {r.text[:400]}")
    except Exception as e:
        print(f"Could not verify via /get_reference_files: {e}")


def main():
    ap = argparse.ArgumentParser(description="Stage clean VCTK reference voices for Chatterbox.")
    ap.add_argument("--out", default="./vctk_voices", help="output dir for wavs")
    ap.add_argument("--n", type=int, default=15, help="number of distinct speakers")
    ap.add_argument("--seconds", type=float, default=12.0, help="target reference length")
    ap.add_argument("--split", default="test", choices=["test", "train"],
                    help="'test' is smaller; use 'train' if you want more speakers")
    ap.add_argument("--upload-to", default="", help="devnen base URL, e.g. http://GIDEON_HOST:8101")
    ap.add_argument("--from-dir", default="", help="skip pulling; just upload wavs already in this dir")
    args = ap.parse_args()

    if args.from_dir:
        if not args.upload_to:
            print("--from-dir needs --upload-to"); sys.exit(1)
        do_upload(args.from_dir, args.upload_to)
        return

    out = do_pull(args)
    if args.upload_to:
        do_upload(out, args.upload_to)


if __name__ == "__main__":
    main()
