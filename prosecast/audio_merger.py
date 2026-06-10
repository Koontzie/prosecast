"""
Audio Merger — ProseCast Phase 1

Concatenates a list of audio block files (WAV or MP3) into a final WAV.
Uses pydub if available; falls back to pure-Python WAV concatenation.
"""

import os
import wave
from pathlib import Path


def _merge_wav_files(wav_paths: list, out_path: str):
    """Pure-Python WAV concatenation — no ffmpeg required."""
    params = None
    frames_list = []

    for p in wav_paths:
        if not os.path.exists(p):
            continue
        try:
            with wave.open(p, 'rb') as wf:
                if params is None:
                    params = wf.getparams()
                frames_list.append(wf.readframes(wf.getnframes()))
        except Exception as e:
            print(f"  [Merger] Skipping {p}: {e}")

    if not frames_list or params is None:
        print("[Merger] No valid WAV frames to merge.")
        return

    with wave.open(out_path, 'wb') as out_wf:
        out_wf.setparams(params)
        for frames in frames_list:
            out_wf.writeframes(frames)


def merge_blocks(block_files: list, out_path: str):
    """Merge block audio files into a single output WAV file."""
    if not block_files:
        print("[Merger] No blocks to merge.")
        return

    paths = [b['path'] for b in block_files]
    has_mp3 = any(p.endswith('.mp3') for p in paths)

    # Try pydub first — handles MP3 if ffmpeg is installed
    try:
        from pydub import AudioSegment
        combined = None
        skipped = 0
        for p in paths:
            if not os.path.exists(p):
                skipped += 1
                continue
            try:
                fmt = 'mp3' if p.endswith('.mp3') else 'wav'
                seg = AudioSegment.from_file(p, format=fmt)
                combined = seg if combined is None else combined + seg
            except Exception as e:
                print(f"  [Merger] pydub skipping {os.path.basename(p)}: {e}")
                skipped += 1

        if combined is not None:
            combined.export(out_path, format='wav')
            print(f"[Merger] Merged {len(paths) - skipped}/{len(paths)} blocks via pydub → {out_path}")
            return
    except Exception as e:
        print(f"[Merger] pydub unavailable ({e}), falling back to WAV-only merge.")

    # Fallback: pure-Python WAV merge (skips MP3 blocks)
    if has_mp3:
        print("[Merger] NOTE: MP3 blocks require ffmpeg. Install with: brew install ffmpeg")
        print("[Merger] Merging WAV-only blocks for now...")

    wav_paths = [p for p in paths if p.endswith('.wav') and os.path.exists(p)]
    if wav_paths:
        _merge_wav_files(wav_paths, out_path)
        print(f"[Merger] Merged {len(wav_paths)} WAV blocks → {out_path}")
    else:
        print("[Merger] No WAV blocks found. Install ffmpeg to merge MP3 output.")
