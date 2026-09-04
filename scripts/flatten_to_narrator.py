#!/usr/bin/env python3
"""Force every block in a book's IR to the NARRATOR voice (single-narrator mode),
then merge consecutive blocks into ~900-char narration chunks so scare-quoted
words don't render as isolated TTS fragments. Pass --no-merge to skip merging.

Thin CLI over prosecast.narrator_flatten (the ingest job calls the module).

For nonfiction/rulebook listening where dialogue attribution is irrelevant.
Run AFTER IR generation, BEFORE rendering:

  .venv/bin/python scripts/flatten_to_narrator.py <slug-or-prefix> [--no-merge]

Idempotent. Rewrites ir.json in place (backs up to ir.json.pre-flatten once).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import library                 # noqa: E402
from prosecast import narrator_flatten        # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    merge = "--no-merge" not in sys.argv
    if len(args) != 1:
        slugs = library.list_book_slugs()
        sys.exit(f"usage: flatten_to_narrator.py <slug> [--no-merge]\navailable: {slugs}")
    want = args[0]
    matches = [s for s in library.list_book_slugs() if want in s]
    if len(matches) != 1:
        sys.exit(f"need exactly one slug match for '{want}', got: {matches}")

    st = narrator_flatten.flatten_book(matches[0], merge=merge)
    print(f"{st['slug']}: {st['reassigned']} reassigned to NARRATOR; merged "
          f"{st['blocks_before']} -> {st['blocks_after']} blocks across "
          f"{st['chapters']} chapters. Backup at {st['backup']}.")


if __name__ == "__main__":
    main()
