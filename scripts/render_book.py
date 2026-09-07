#!/usr/bin/env python3
"""render_book.py — the overnight whole-book render runner (Phase C5).

preflight -> loop chapters via the unified renderer (done chapters skip) ->
summary. Re-running after ANY failure is the whole recovery story: finished
chapters skip, partial chapters resume at the last rendered block.

Usage:
    python3 scripts/render_book.py carl_rpg_core_rulebook
    python3 scripts/render_book.py carl_rpg_core_rulebook --chapters 2-5
    python3 scripts/render_book.py <slug> --force          # re-render everything
    caffeinate -i .venv/bin/python scripts/render_book.py <slug>   # Mac awake

NOTE: --tts defaults to chatterbox ON PURPOSE (never auto-detect: an
ElevenLabs key in .env would silently burn credits on a whole book).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import library as lib
from prosecast.preflight import preflight
from prosecast.renderer import make_engine, render_chapter


def parse_chapters(spec: str, total: int) -> list:
    """'3' | '1-5' | '1,3,5' — 1-based, like main.py --chapters."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a) - 1, int(b)))
        elif part:
            out.append(int(part) - 1)
    return [c for c in out if 0 <= c < total]


def main():
    ap = argparse.ArgumentParser(description="Preflighted whole-book render, resumable.")
    ap.add_argument("slug", help="book slug under library/ (exact or unique substring)")
    ap.add_argument("--tts", default="chatterbox",
                    choices=["chatterbox", "elevenlabs", "piper", "say", "gtts", "stub"])
    ap.add_argument("--chapters", default="", help="1-based: '3', '1-5', '1,3,5' (default: all)")
    ap.add_argument("--force", action="store_true", help="re-render even done chapters")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="you almost never want this")
    args = ap.parse_args()

    matches = [s for s in lib.list_book_slugs() if args.slug in s]
    if len(matches) != 1:
        sys.exit(f"need exactly one slug match for '{args.slug}', got: {matches}")
    slug = matches[0]

    if not args.skip_preflight:
        rep = preflight(slug, args.tts)
        print(rep.summary())
        if not rep.ok:
            sys.exit(2)
    else:
        print("[Preflight] SKIPPED by flag — good luck.")

    ir_path = lib.ir_path(slug)
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    total = len(ir["chapters"])
    targets = parse_chapters(args.chapters, total) if args.chapters else list(range(total))

    engine = make_engine(slug, args.tts)
    print(f"[Book] {slug}: {len(targets)}/{total} chapters queued "
          f"(engine={args.tts}, force={args.force})")

    t0 = time.time()
    results = []
    for ch in targets:
        try:
            results.append(render_chapter(slug, ch, ir, ir_path=str(ir_path),
                                          engine=engine, force=args.force))
        except KeyboardInterrupt:
            print("\n[Book] interrupted — re-run this exact command to resume.")
            sys.exit(130)
        except Exception as e:
            print(f"[Book] ch{ch} FAILED: {e} — continuing with next chapter")
            results.append({"chapter_index": ch, "error": str(e),
                            "skipped": False, "rendered": 0, "cached": 0,
                            "failed": 0, "audio_seconds": 0, "render_seconds": 0})

    wall = time.time() - t0
    rendered = sum(r.get("rendered", 0) for r in results)
    skipped = sum(1 for r in results if r.get("skipped"))
    failed_ch = [r["chapter_index"] for r in results if r.get("error")]
    audio_min = sum(r.get("audio_seconds", 0) for r in results) / 60.0

    print("\n" + "=" * 60)
    print(f"[Summary] {len(results)} chapters: {skipped} skipped, "
          f"{len(failed_ch)} failed{' ' + str(failed_ch) if failed_ch else ''}")
    print(f"[Summary] {rendered} blocks newly rendered, "
          f"{audio_min:.0f} min audio total, wall time {wall/3600:.1f}h")
    if failed_ch:
        print("[Summary] re-run the same command to retry failures (done work skips).")
        sys.exit(1)
    print("[Summary] all good — export the M4B from the UI (or POST /export/{slug}).")


if __name__ == "__main__":
    main()
