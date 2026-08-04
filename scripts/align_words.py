#!/usr/bin/env python3
"""
Align rendered chapters to word-level timestamps via the whisper server.

Run AFTER rendering (Chatterbox produces the block wavs this reads).

Usage:
    # All rendered chapters that lack fresh timings (the usual move):
    PROSECAST_WHISPER_URL=http://GIDEON_HOST:8100 \
        .venv/bin/python scripts/align_words.py <slug>

    # Specific chapters (0-based indices, same numbering as the UI list):
    ... scripts/align_words.py <slug> 4 8 16

    # Force re-alignment even if timings look fresh:
    ... scripts/align_words.py <slug> --force
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json  # noqa: E402

from prosecast import library as lib  # noqa: E402
from prosecast.word_aligner import (  # noqa: E402
    STALE_TOLERANCE_SECS, WHISPER_BASE, WHISPER_MODEL,
    align_chapter, chapter_blocks_fingerprint, timings_path,
)


def _needs_alignment(slug: str, ch: int) -> bool:
    tp = timings_path(slug, ch)
    if not tp.exists():
        return True
    try:
        saved = json.loads(tp.read_text(encoding="utf-8"))
        return abs(saved.get("total_duration", -1)
                   - chapter_blocks_fingerprint(slug, ch)) > STALE_TOLERANCE_SECS
    except (OSError, json.JSONDecodeError):
        return True


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    if not args:
        print(__doc__)
        return 1
    slug = args[0]
    if not lib.ir_path(slug).exists():
        print(f"No book '{slug}' in library. Available: {lib.list_book_slugs()}")
        return 1

    ir = json.loads(lib.ir_path(slug).read_text(encoding="utf-8"))
    n_chapters = len(ir.get("chapters", []))

    if len(args) > 1:
        targets = [int(a) for a in args[1:]]
    else:
        targets = [ch for ch in range(n_chapters)
                   if lib.chapter_blocks_dir(slug, ch).exists()]

    print(f"[ALIGN] Server: {WHISPER_BASE}  model: {WHISPER_MODEL}")
    done = fresh = failed = 0
    for ch in targets:
        if not lib.chapter_blocks_dir(slug, ch).exists():
            print(f"[ALIGN] ch{ch}: not rendered — skipping.")
            continue
        if not force and not _needs_alignment(slug, ch):
            fresh += 1
            continue
        result = align_chapter(slug, ch)
        if result is None:
            failed += 1
            if failed >= 2:
                print("[ALIGN] Repeated failures — stopping. Check the whisper server.")
                return 1
        else:
            done += 1

    print(f"\n[ALIGN] {done} chapter(s) aligned, {fresh} already fresh, {failed} failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
