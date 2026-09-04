#!/usr/bin/env python3
"""play_to_ir.py — stage/screen play text -> ProseCast IR (thin CLI over
prosecast.play_parser; the parsing lives there so the ingest job can call it).

Acting-edition format (Samuel French style):
    SPEAKER. Dialogue possibly wrapping
        over several lines.
            (Stage directions in parentheses, possibly
            spanning lines.)
Speaker labels are explicit, so attribution is deterministic: every dialogue
block lands with confidence 1.0 / method 'script_format'; stage directions
become NARRATOR narration blocks. Scene headings become chapters.

Input is plain text: PDF text for born-digital PDFs, OCR text for scans
(tesseract). Page breaks may be marked with \\f or not at all.

Usage:
    python3 play_to_ir.py play.txt "She Kills Monsters" out_ir.json
        [--running-head "SHE KILLS MONSTERS|YOUNG ADVENTURERS"]
        [--keep-inline-parens]
        [--keep-front-matter]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import library as lib          # noqa: E402
from prosecast import play_parser             # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("txt")
    ap.add_argument("title")
    ap.add_argument("out")
    ap.add_argument("--running-head", default="",
                    help="regex; lines matching it are dropped (title headers)")
    ap.add_argument("--keep-inline-parens", action="store_true")
    ap.add_argument("--keep-front-matter", action="store_true",
                    help="keep text before the first scene heading (default: dropped)")
    args = ap.parse_args()

    text = open(args.txt, encoding="utf-8", errors="replace").read()
    res = play_parser.play_to_ir(
        text, args.title,
        running_head=args.running_head,
        keep_inline_parens=args.keep_inline_parens,
        keep_front_matter=args.keep_front_matter,
    )

    print(f"[Play] {res['scenes']} scenes, {res['blocks']} blocks "
          f"({res['dialogue']} dialogue), cast of {len(res['cast'])}: "
          f"{', '.join(res['cast'])}", file=sys.stderr)
    if res["merged"]:
        print(f"[Play] merged OCR variants: {res['merged']}", file=sys.stderr)
    lib.write_json_atomic(args.out, res["ir"])
    print(f"[Play] wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
