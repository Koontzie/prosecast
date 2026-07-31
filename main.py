#!/usr/bin/env python3
"""
ProseCast CLI — Phase 1 Prototype
═══════════════════════════════════════════════════════════════════════

Usage:
  python main.py --book path/to/book.epub
  python main.py --book path/to/book.txt --chapter 0
  python main.py --sample                   # generate a sample book and run it
  python main.py --ir only                  # only generate IR, no audio
  python main.py --book book.epub --tts stub  # IR + silent audio (fastest test)

What it does:
  1. Parses your EPUB/TXT into chapters
  2. Builds an IR (voice map) — JSON with every block tagged
  3. Synthesizes audio per block using the best available TTS
  4. Merges blocks into a final chapter .wav/.mp3 file

Outputs (per-book library layout — see prosecast/library.py):
  library/<slug>/ir.json               — the full IR
  library/<slug>/voice_map.json        — character→voice assignments
  library/<slug>/corrections.jsonl     — append-only correction journal
  library/<slug>/renders/ch0.wav       — final chapter audio
  library/<slug>/renders/ch0_blocks/   — individual block audio files
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add the project root to sys.path so "prosecast" package resolves
sys.path.insert(0, str(Path(__file__).parent))

from prosecast.book_parser import parse_book, write_sample_book
from prosecast.ir_generator import build_ir, save_ir
from prosecast.tts_engine import TTSEngine
from prosecast.audio_merger import merge_blocks
from prosecast.llm_attributor import run_llm_pass, check_ollama
from prosecast.ir_generator import migrate_ir
from prosecast.tag_generator import tag_ir, check_gideon


from prosecast import library as lib

BOOKS_DIR = Path(__file__).parent / "books"


# ---------------------------------------------------------------------------
# IR report printer
# ---------------------------------------------------------------------------

def print_ir_report(ir_data: dict):
    print("\n" + "═" * 60)
    print(f"  PROSECAST IR REPORT: {ir_data['book_title']}")
    print("═" * 60)
    print(f"  Characters detected: {', '.join(ir_data['characters']) or 'none'}")
    print(f"  Unresolved lines:    {ir_data['unresolved_count']}")

    for chapter in ir_data['chapters']:
        blocks = chapter['blocks']
        dialogue_blocks = [b for b in blocks if b['type'] == 'dialogue']
        resolved = [b for b in dialogue_blocks if not b['unresolved']]
        print(f"\n  [{chapter['title']}]")
        print(f"    Total blocks:   {len(blocks)}")
        print(f"    Dialogue lines: {len(dialogue_blocks)}")
        print(f"    Resolved:       {len(resolved)}/{len(dialogue_blocks)}")

        # Print first 6 blocks as a preview
        print(f"\n    First blocks preview:")
        for b in blocks[:6]:
            tag = f"[{b['speaker']:<14}  conf={b['confidence']:.2f}]"
            preview = b['text'][:60].replace('\n', ' ')
            flag = " ⚠ UNRESOLVED" if b['unresolved'] else ""
            print(f"      {tag}  {preview!r}{flag}")

    print("\n" + "═" * 60)

    if ir_data['unresolved_count'] > 0:
        print(f"\n  ⚠  {ir_data['unresolved_count']} dialogue lines couldn't be attributed.")
        print("     They'll use the narrator voice for now.")
        print("     Phase 2 will add an LLM pass + correction UI to fix these.\n")


# ---------------------------------------------------------------------------
# Audio generation pipeline
# ---------------------------------------------------------------------------

def generate_audio(ir_data: dict, chapter_index: int, book_slug: str, tts_override: str = None, ir_path: str = None):
    engine = TTSEngine(engine=tts_override)

    voice_map_path = lib.voice_map_path(book_slug)
    if voice_map_path.exists():
        with open(voice_map_path) as f:
            engine.load_voice_map(json.load(f).get("map", {}))
        print(f"[Audio] Loaded voice map → {voice_map_path}")

    chapter = ir_data['chapters'][chapter_index]
    blocks = chapter['blocks']

    blocks_dir = lib.chapter_blocks_dir(book_slug, chapter_index)
    blocks_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[Audio] Generating {len(blocks)} blocks for '{chapter['title']}'...")
    block_files = []

    for i, block in enumerate(blocks):
        if not block.get('text', '').strip():
            continue

        out_path = str(blocks_dir / f"block_{i:04d}.wav")
        ok = engine.synthesize_segment(block, out_path)

        if ok:
            url = block.get('audioVariants', {}).get('standard', {}).get('url') or out_path
            block_files.append({"path": url, "speaker": block.get('speaker', 'NARRATOR')})
            sym = "🎙" if block['type'] == 'dialogue' else "📖"
            cached_marker = " (cached)" if block.get('audioVariants', {}).get('standard', {}).get('cached') else ""
            print(f"  {sym} [{block.get('speaker', 'NARRATOR'):<14}] block {i:04d}  ✓{cached_marker}")
        else:
            print(f"  ✗ block {i:04d} failed — skipping")

    # Merge
    final_path = str(lib.chapter_wav_path(book_slug, chapter_index))
    merge_blocks(block_files, final_path)

    print(f"\n[Done] Final audio → {final_path}")
    print(f"       Voice map:  {engine.assigner.summary()}")

    # Persist updated audioVariants / cacheKey back to the IR file
    if ir_path:
        with open(ir_path, "w", encoding="utf-8") as f:
            json.dump(ir_data, f, indent=2, ensure_ascii=False)
        print(f"[IR] Updated segment cache metadata → {ir_path}")

    return final_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _find_ir_by_name(query: str) -> str | None:
    """Search output/ for an IR file whose book_title fuzzy-matches query.

    Normalises both strings to lowercase words and checks that every word in
    the query appears somewhere in the title words.  Returns the IR file path
    on a match, or None.
    """
    def _words(s: str) -> list[str]:
        return re.sub(r'[^a-z0-9 ]', ' ', s.lower()).split()

    query_words = _words(query)
    if not query_words:
        return None

    for slug in lib.list_book_slugs():
        ir_file = lib.ir_path(slug)
        try:
            with open(ir_file) as f:
                title = json.load(f).get("book_title", "")
        except Exception:
            continue
        title_words = _words(title)
        if all(w in title_words for w in query_words):
            return str(ir_file)
    return None


def _parse_chapters(spec: str, chapter_count: int) -> list[int]:
    """Parse a chapter range spec (1-based) into a sorted list of 0-based indices.

    Accepts: single int "3", range "1-5", comma list "1,3,5", or combos "1-3,7".
    Returns indices clamped to [0, chapter_count).
    """
    indices = set()
    for part in spec.split(','):
        part = part.strip()
        if '-' in part:
            lo, _, hi = part.partition('-')
            lo_i = max(1, int(lo.strip()))
            hi_i = min(chapter_count, int(hi.strip()))
            indices.update(range(lo_i - 1, hi_i))
        else:
            n = int(part)
            if 1 <= n <= chapter_count:
                indices.add(n - 1)
    return sorted(indices)


def main():
    parser = argparse.ArgumentParser(
        description="ProseCast — Multi-voice book narration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --sample\n"
            "  python main.py --book book.epub --chapters 1-3\n"
            '  python main.py "A Parade of Horribles" --chapters 1-2 --tts elevenlabs\n'
        ),
    )
    parser.add_argument("book_name",  nargs="?", help="Book title to look up in output/ (fuzzy match against IR files)")
    parser.add_argument("--book",    help="Path to .epub or .txt file")
    parser.add_argument("--sample",  action="store_true", help="Run with built-in sample text")
    parser.add_argument("--chapter", type=int, default=None, help="Single chapter to render by 1-based number (legacy; prefer --chapters)")
    parser.add_argument("--chapters", help="Chapter(s) to render, 1-based: '3', '1-5', '1,3,5' (default: chapter 1)")
    parser.add_argument("--all-chapters", action="store_true", help="Render audio for every chapter in the book")
    parser.add_argument("--ir-only",  action="store_true", help="Generate IR only, skip audio")
    parser.add_argument("--tts",      choices=["elevenlabs", "chatterbox", "piper", "say", "gtts", "stub"], help="Override TTS engine")
    parser.add_argument("--narrator",   help="POV character name for first-person dialogue (e.g. 'Lucky')")
    parser.add_argument("--use-existing-ir", action="store_true", help="Load IR from disk instead of rebuilding (skips parse; combine with --llm to attribute remaining unresolved blocks)")
    parser.add_argument("--llm",        action="store_true", help="Run Ollama LLM pass on unresolved blocks after rule-based IR")
    parser.add_argument("--llm-model",  default="llama3.2",  help="Ollama model to use (default: llama3.2)")
    parser.add_argument("--llm-threshold", type=float, default=0.6, help="Min confidence to accept LLM attribution (default: 0.6)")
    parser.add_argument("--tag",           action="store_true", help="Run emotion/tone tagging pass after attribution (uses Gideon/Ollama)")
    parser.add_argument("--retag",         action="store_true", help="Force re-tagging of blocks that already have tags")
    parser.add_argument("--tag-model",     default="mistral:7b", help="Ollama model to use for tagging (default: mistral:7b)")
    parser.add_argument("--tag-dialogue-only", action="store_true", help="Only tag dialogue blocks, skip narration (faster)")
    parser.add_argument("--export-m4b",    action="store_true", help="Export rendered chapters as a chapterized .m4b audiobook (needs ffmpeg)")
    parser.add_argument("--author",        default="", help="Author metadata for the m4b export")
    args = parser.parse_args()

    lib.LIBRARY_DIR.mkdir(exist_ok=True)

    # ── Choose input ────────────────────────────────────────────────────────
    ir_path = None
    if args.sample:
        sample_path = str(BOOKS_DIR / "sample_book.txt")
        write_sample_book(sample_path)
        book_path = sample_path
    elif args.book_name and not args.book:
        # Positional name — try as file path first, then IR name lookup
        candidate = Path(args.book_name)
        if candidate.exists():
            book_path = str(candidate)
        else:
            ir_path = _find_ir_by_name(args.book_name)
            if not ir_path:
                print(f"❌  No book found matching '{args.book_name}'")
                print(f"    Available books in {lib.LIBRARY_DIR}:")
                for slug in lib.list_book_slugs():
                    try:
                        title = json.load(open(lib.ir_path(slug))).get("book_title", slug)
                        print(f"      {title}")
                    except Exception:
                        pass
                sys.exit(1)
            # Found an IR — force --use-existing-ir behaviour
            args.use_existing_ir = True
            book_path = ir_path  # slug derived from IR path below
    elif args.book:
        book_path = args.book
    else:
        parser.print_help()
        print("\nTip: run with --sample to test without a real book.\n")
        sys.exit(0)

    # ── Derive slug and IR path ──────────────────────────────────────────────
    if ir_path:
        # IR was located by name lookup — slug is the library folder name
        book_slug = Path(ir_path).parent.name
    else:
        book_title = Path(book_path).stem.replace("_", " ").title()
        book_slug = re.sub(r'[^\w]', '_', book_title.lower())[:30]
        lib.ensure_book_dir(book_slug)
        ir_path = str(lib.ir_path(book_slug))

    if args.use_existing_ir:
        # ── Load pre-built IR from disk ──────────────────────────────────────
        if not Path(ir_path).exists():
            print(f"❌  No existing IR found at {ir_path}")
            print("    Run without --use-existing-ir to build it first.")
            sys.exit(1)
        with open(ir_path) as f:
            ir_data = json.load(f)
        print(f"[IR] Loaded existing IR → {ir_path}")
        print(f"[IR] {len(ir_data['chapters'])} chapters, {ir_data['unresolved_count']} unresolved")

        # Migrate to new segment model if needed
        ir_data = migrate_ir(ir_data)
        with open(ir_path, "w", encoding="utf-8") as f:
            json.dump(ir_data, f, indent=2, ensure_ascii=False)
        print(f"[IR] Migrated to new segment model → {ir_path}")
    else:
        # ── Parse → Build IR ─────────────────────────────────────────────────
        chapters = parse_book(book_path)
        if not chapters:
            print("❌  No chapters found. Check your file.")
            sys.exit(1)

        ir = build_ir(book_title, chapters, narrator_character=args.narrator)

        from prosecast.ir_generator import save_ir, asdict
        save_ir(ir, ir_path)

        with open(ir_path) as f:
            ir_data = json.load(f)

    # ── LLM attribution pass (Phase 2) ───────────────────────────────────────
    # Runs on fresh AND existing IRs (--use-existing-ir --llm re-attributes the
    # unresolved residue without rebuilding — manual corrections are preserved
    # because only blocks still marked unresolved are touched).
    if args.llm:
        if check_ollama(args.llm_model):
            print(f"\n[LLM] Running attribution pass with {args.llm_model}...")
            ir_data = run_llm_pass(
                ir_data,
                model=args.llm_model,
                confidence_threshold=args.llm_threshold,
            )
            with open(ir_path, "w", encoding="utf-8") as f:
                json.dump(ir_data, f, indent=2, ensure_ascii=False)
            print(f"[LLM] IR updated → {ir_path}")
        else:
            print(f"\n[LLM] Skipping LLM pass — model '{args.llm_model}' unavailable.")

    # ── Tagging pass (Phase 4) ───────────────────────────────────────────────
    if args.tag or args.retag:
        if check_gideon(args.tag_model):
            print(f"\n[TAG] Running tagging pass with {args.tag_model}...")
            ir_data = tag_ir(
                ir_data,
                model=args.tag_model,
                retag=args.retag,
                dialogue_only=args.tag_dialogue_only,
                checkpoint_path=ir_path,
            )
            with open(ir_path, "w", encoding="utf-8") as f:
                json.dump(ir_data, f, indent=2, ensure_ascii=False)
            print(f"[TAG] IR updated → {ir_path}")
        else:
            print(f"\n[TAG] Skipping tag pass — Gideon/Ollama not reachable or model '{args.tag_model}' unavailable.")

    print_ir_report(ir_data)

    if args.ir_only:
        print(f"\nIR saved → {ir_path}")
        print("Skipping audio generation (--ir-only).")
        return

    chapter_count = len(ir_data['chapters'])

    # ── Resolve which chapters to render ────────────────────────────────────
    if args.all_chapters:
        ch_indices = list(range(chapter_count))
    elif args.chapters:
        try:
            ch_indices = _parse_chapters(args.chapters, chapter_count)
        except ValueError:
            print(f"❌  Invalid --chapters value: {args.chapters!r}")
            print("    Examples: '3', '1-5', '1,3,5'")
            sys.exit(1)
        if not ch_indices:
            print(f"❌  --chapters {args.chapters!r} matched no chapters (book has {chapter_count})")
            sys.exit(1)
    elif args.chapter is not None:
        # Legacy --chapter flag (1-based for consistency, kept for scripts)
        ch_idx = args.chapter - 1
        if ch_idx < 0 or ch_idx >= chapter_count:
            print(f"❌  Chapter {args.chapter} not found (book has {chapter_count} chapters, 1–{chapter_count})")
            sys.exit(1)
        ch_indices = [ch_idx]
    elif args.export_m4b:
        ch_indices = []  # export-only run: don't trigger the default ch0 render
    else:
        ch_indices = [0]  # default: first chapter

    for ch_idx in ch_indices:
        generate_audio(ir_data, ch_idx, book_slug, tts_override=args.tts, ir_path=ir_path)

    # ── M4B export ───────────────────────────────────────────────────────────
    if args.export_m4b:
        from prosecast.m4b_export import export_m4b, M4BExportError
        try:
            res = export_m4b(book_slug, author=args.author)
        except M4BExportError as e:
            print(f"❌  M4B export failed: {e}")
            sys.exit(1)
        mins = res["duration_ms"] / 60000
        mb = res["size_bytes"] / 1_048_576
        print(f"\n[M4B] {res['exported_chapters']} chapters, {mins:.1f} min, {mb:.1f} MB")
        if res["skipped_chapters"]:
            print(f"[M4B] Skipped {len(res['skipped_chapters'])} unrendered chapters")
        print(f"[M4B] → {res['path']}")


# needed for the import in generate_audio
import re
from prosecast.ir_generator import asdict

if __name__ == "__main__":
    main()
