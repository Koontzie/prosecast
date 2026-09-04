"""Single-narrator mode: force every block to NARRATOR, then merge into
~900-char narration chunks so scare-quoted words don't render as isolated
TTS fragments.

For nonfiction/rulebook listening where dialogue attribution is irrelevant.
Runs AFTER IR generation, BEFORE rendering.

Lifted out of scripts/flatten_to_narrator.py (2026-09-04, E2.1) so the ingest
job can call it directly; the script is now a thin CLI over this module, same
flags and same printed summary. One change on the way over: the file write now
goes through lib.write_json_atomic() like every other ir.json write.
"""
import json
import shutil

from prosecast import library as lib

TARGET_CHARS = 900


def flatten_ir(ir: dict, *, merge: bool = True, target: int = TARGET_CHARS) -> dict:
    """Mutate ``ir`` in place; return stats.

    Idempotent: running it twice reassigns nothing and merges nothing new.
    """
    reassigned = 0
    for ch in ir.get("chapters", []):
        for b in ch.get("blocks", []):
            if b.get("speaker") != "NARRATOR" or b.get("unresolved"):
                reassigned += 1
            b["speaker"] = "NARRATOR"
            b["unresolved"] = False
            b["confidence"] = 1.0
            b["attribution_method"] = "single_narrator"
    ir["characters"] = []
    ir["unresolved_count"] = 0

    blocks_before = sum(len(c.get("blocks", [])) for c in ir.get("chapters", []))
    if merge:
        for ch in ir.get("chapters", []):
            out = []
            for b in ch.get("blocks", []):
                t = (b.get("text") or "").strip()
                if not t:
                    continue
                if out and len(out[-1]["text"]) + len(t) + 1 <= target:
                    out[-1]["text"] = out[-1]["text"] + " " + t
                else:
                    b["text"] = t
                    b["type"] = "narration"
                    out.append(b)
            ch["blocks"] = out
    blocks_after = sum(len(c.get("blocks", [])) for c in ir.get("chapters", []))

    return {"reassigned": reassigned, "blocks_before": blocks_before,
            "blocks_after": blocks_after, "chapters": len(ir.get("chapters", []))}


def flatten_book(slug: str, *, merge: bool = True) -> dict:
    """Flatten a book already in the library. Backs ir.json up to
    ir.json.pre-flatten once, then rewrites it atomically."""
    ir_file = lib.ir_path(slug)
    ir = json.loads(ir_file.read_text(encoding="utf-8"))

    backup = ir_file.with_suffix(".json.pre-flatten")
    if not backup.exists():
        shutil.copy2(ir_file, backup)

    stats = flatten_ir(ir, merge=merge)
    lib.write_json_atomic(ir_file, ir)
    stats["backup"] = backup.name
    stats["slug"] = slug
    return stats
