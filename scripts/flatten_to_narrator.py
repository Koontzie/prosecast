#!/usr/bin/env python3
"""Force every block in a book's IR to the NARRATOR voice (single-narrator mode),
then merge consecutive blocks into ~900-char narration chunks so scare-quoted
words don't render as isolated TTS fragments. Pass --no-merge to skip merging.

For nonfiction/rulebook listening where dialogue attribution is irrelevant.
Run AFTER IR generation, BEFORE rendering:

  .venv/bin/python scripts/flatten_to_narrator.py <slug-or-prefix>

Idempotent. Rewrites ir.json in place (backs up to ir.json.pre-flatten once).
"""
import json, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prosecast import library


def main():
    if len(sys.argv) != 2:
        slugs = library.list_book_slugs()
        sys.exit(f"usage: flatten_to_narrator.py <slug>\navailable: {slugs}")
    want = sys.argv[1]
    matches = [s for s in library.list_book_slugs() if want in s]
    if len(matches) != 1:
        sys.exit(f"need exactly one slug match for '{want}', got: {matches}")
    slug = matches[0]
    ir_file = library.ir_path(slug)
    ir = json.load(open(ir_file))

    backup = ir_file.with_suffix('.json.pre-flatten')
    if not backup.exists():
        shutil.copy2(ir_file, backup)

    changed = 0
    for ch in ir['chapters']:
        for b in ch['blocks']:
            if b.get('speaker') != 'NARRATOR' or b.get('unresolved'):
                changed += 1
            b['speaker'] = 'NARRATOR'
            b['unresolved'] = False
            b['confidence'] = 1.0
            b['attribution_method'] = 'single_narrator'
    ir['characters'] = []
    ir['unresolved_count'] = 0

    TARGET = 900
    merged_from = sum(len(c['blocks']) for c in ir['chapters'])
    if '--no-merge' not in sys.argv:
        for ch in ir['chapters']:
            out = []
            for b in ch['blocks']:
                t = (b.get('text') or '').strip()
                if not t:
                    continue
                if out and len(out[-1]['text']) + len(t) + 1 <= TARGET:
                    out[-1]['text'] = out[-1]['text'] + ' ' + t
                else:
                    b['text'] = t
                    b['type'] = 'narration'
                    out.append(b)
            ch['blocks'] = out

    json.dump(ir, open(ir_file, 'w'), indent=2, ensure_ascii=False)
    total = sum(len(c['blocks']) for c in ir['chapters'])
    print(f"{slug}: {changed} reassigned to NARRATOR; merged {merged_from} -> "
          f"{total} blocks across {len(ir['chapters'])} chapters. Backup at {backup.name}.")


if __name__ == '__main__':
    main()
