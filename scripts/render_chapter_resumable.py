#!/usr/bin/env python3
"""
render_chapter_resumable.py — block-level resumable single-chapter render.

Unlike main.py's render loop (which persists cacheKeys only after the whole
chapter finishes), this saves the IR after EVERY block. Kill it anywhere,
re-run it, and it resumes from the last completed block via the engine's
cacheKey check. Merges to renders/ch{N}.wav once all blocks are done.

Also reports render throughput: seconds of render time per minute of audio —
the number that decides whether a full-book render is overnight or a weekend.

Usage:
    python3 scripts/render_chapter_resumable.py sample_book 0
    python3 scripts/render_chapter_resumable.py sample_book 0 --tts chatterbox
    python3 scripts/render_chapter_resumable.py a_parade_of_horribles_generic_ 3 --max-blocks 8

NOTE: --tts defaults to chatterbox ON PURPOSE. Never let this script fall
through to engine auto-detect: with an ElevenLabs key in .env, auto-detect
picks elevenlabs and a whole chapter silently burns credits.
"""

import argparse
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast.tts_engine import TTSEngine
from prosecast.audio_merger import merge_blocks
from prosecast import library as lib


def wav_seconds(path: str) -> float:
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def main():
    ap = argparse.ArgumentParser(description="Block-level resumable chapter render.")
    ap.add_argument("slug", help="book slug under library/")
    ap.add_argument("chapter", type=int, help="chapter index (0-based IR index)")
    ap.add_argument("--tts", default="chatterbox",
                    choices=["chatterbox", "elevenlabs", "piper", "say", "gtts", "stub"],
                    help="engine (default chatterbox — never auto-detect here)")
    ap.add_argument("--max-blocks", type=int, default=0,
                    help="stop after N newly-rendered blocks (0 = no limit); for slicing long runs")
    args = ap.parse_args()

    ir_path = lib.ir_path(args.slug)
    if not ir_path.exists():
        print(f"No IR at {ir_path}")
        sys.exit(1)
    ir_data = json.loads(ir_path.read_text(encoding="utf-8"))
    chapter = ir_data["chapters"][args.chapter]
    blocks = chapter["blocks"]

    engine = TTSEngine(engine=args.tts)

    vm_path = lib.voice_map_path(args.slug)
    if vm_path.exists():
        engine.load_voice_map(json.loads(vm_path.read_text()).get("map", {}))
        print(f"[Audio] Loaded voice map → {vm_path}")

    blocks_dir = lib.chapter_blocks_dir(args.slug, args.chapter)
    blocks_dir.mkdir(parents=True, exist_ok=True)

    def save_ir():
        ir_path.write_text(json.dumps(ir_data, indent=2, ensure_ascii=False), encoding="utf-8")

    total = len(blocks)
    newly_rendered = 0
    render_seconds = 0.0
    print(f"[Audio] '{chapter.get('title')}' — {total} blocks (resumable)")

    for i, block in enumerate(blocks):
        if not block.get("text", "").strip():
            continue
        out_path = str(blocks_dir / f"block_{i:04d}.wav")

        was_cached = bool(block.get("audioVariants", {}).get("standard", {}).get("cached"))
        t0 = time.time()
        ok = engine.synthesize_segment(block, out_path)
        dt = time.time() - t0

        if not ok:
            print(f"  ✗ block {i:04d} FAILED — continuing")
            continue

        cached_now = dt < 0.05 and was_cached
        if not cached_now:
            newly_rendered += 1
            render_seconds += dt
            save_ir()  # persist cacheKey immediately — this is the resume point
            print(f"  ✓ block {i:04d} [{block.get('speaker','NARRATOR'):<12}] {dt:5.1f}s")
        else:
            print(f"  · block {i:04d} cached")

        if args.max_blocks and newly_rendered >= args.max_blocks:
            print(f"[Audio] --max-blocks {args.max_blocks} reached; re-run to continue.")
            sys.exit(0)

    # All blocks attempted — merge whatever rendered.
    block_files = []
    audio_seconds = 0.0
    for i, block in enumerate(blocks):
        url = block.get("audioVariants", {}).get("standard", {}).get("url")
        if url and Path(url).exists():
            block_files.append({"path": url, "speaker": block.get("speaker", "NARRATOR")})
            audio_seconds += wav_seconds(url)

    final_path = str(lib.chapter_wav_path(args.slug, args.chapter))
    merge_blocks(block_files, final_path)
    save_ir()

    print(f"\n[Done] {len(block_files)}/{total} blocks → {final_path}")
    print(f"[Done] audio length: {audio_seconds/60:.1f} min")
    if newly_rendered and audio_seconds:
        rspm = render_seconds / (audio_seconds / 60.0)
        print(f"[Perf] this run: {newly_rendered} blocks in {render_seconds:.0f}s render time")
        print(f"[Perf] ≈ {rspm:.0f}s of render per minute of audio "
              f"(115-chapter book at this chapter's length ≈ "
              f"{115 * (audio_seconds * (rspm/60)) / 3600:.1f}h)")


if __name__ == "__main__":
    main()
