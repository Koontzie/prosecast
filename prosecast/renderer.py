"""Unified per-block-resumable chapter renderer (Phase C1).

Single render core used by main.py, server.py's queue worker, and
scripts/render_book.py. Behaviors proven in scripts/render_chapter_resumable.py:

  * IR saved after EVERY newly-rendered block  -> kill it anywhere, resume free
  * continue on block failure                  -> one bad block never sinks a chapter
  * throughput report (s render / min audio)   -> the overnight-or-weekend number
  * merge whatever rendered

Chapter-done semantics (Phase C3): renders/ch{N}.wav exists AND no non-empty
block needs re-synthesis under the current engine+voice config (cacheKey
check). A done chapter is skipped unless force=True.
"""
from __future__ import annotations

import json
import os
import time
import wave
from pathlib import Path

from prosecast import library as lib
from prosecast.audio_merger import merge_blocks
from prosecast.tts_engine import TTSEngine


def wav_seconds(path: str) -> float:
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def make_engine(book_slug: str, engine_name: str | None) -> TTSEngine:
    """Build a TTSEngine with the book's voice map loaded (if present)."""
    engine = TTSEngine(engine=engine_name)
    vm_path = lib.voice_map_path(book_slug)
    if vm_path.exists():
        engine.load_voice_map(json.loads(vm_path.read_text()).get("map", {}))
    return engine


def block_needs_synthesis(engine: TTSEngine, block: dict) -> bool:
    """Mirror of synthesize_segment's cache check, without synthesizing."""
    text = block.get("text", "")
    if not text.strip():
        return False
    speaker = block.get("speaker") or "NARRATOR"
    if block.get("unresolved"):
        speaker = "NARRATOR"
    cache_key = engine._cache_key(text, engine.assigner.get_voice(speaker))
    variant = block.get("audioVariants", {}).get("standard", {})
    return not (variant.get("cached")
                and variant.get("url")
                and os.path.exists(variant["url"])
                and block.get("cacheKey") == cache_key)


def chapter_is_done(book_slug: str, chapter_index: int, chapter: dict,
                    engine: TTSEngine) -> bool:
    if not lib.chapter_wav_path(book_slug, chapter_index).exists():
        return False
    return not any(block_needs_synthesis(engine, b) for b in chapter["blocks"])


def render_chapter(book_slug: str, chapter_index: int, ir_data: dict,
                   ir_path: str | Path | None = None,
                   engine: TTSEngine | None = None,
                   engine_name: str | None = None,
                   force: bool = False,
                   save_every_block: bool = True,
                   progress_cb=None,
                   log=print) -> dict:
    """Render one chapter, per-block resumable. Returns a report dict."""
    engine = engine or make_engine(book_slug, engine_name)
    chapter = ir_data["chapters"][chapter_index]
    blocks = chapter["blocks"]
    report = {"chapter_index": chapter_index, "title": chapter.get("title"),
              "skipped": False, "blocks_total": len(blocks), "rendered": 0,
              "cached": 0, "failed": 0, "audio_seconds": 0.0,
              "render_seconds": 0.0, "wav_path": None}

    if not force and chapter_is_done(book_slug, chapter_index, chapter, engine):
        report["skipped"] = True
        report["wav_path"] = str(lib.chapter_wav_path(book_slug, chapter_index))
        log(f"[Render] ch{chapter_index} '{chapter.get('title')}' already done — skipping")
        return report

    if force:
        for b in blocks:
            b["cacheKey"] = None  # bust the cache: every block re-synthesizes

    ir_path = Path(ir_path) if ir_path else lib.ir_path(book_slug)

    def save_ir():
        ir_path.write_text(json.dumps(ir_data, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    blocks_dir = lib.chapter_blocks_dir(book_slug, chapter_index)
    blocks_dir.mkdir(parents=True, exist_ok=True)
    log(f"[Render] ch{chapter_index} '{chapter.get('title')}' — {len(blocks)} blocks")

    for i, block in enumerate(blocks):
        if not block.get("text", "").strip():
            continue
        out_path = str(blocks_dir / f"block_{i:04d}.wav")
        needed = block_needs_synthesis(engine, block)
        t0 = time.time()
        ok = engine.synthesize_segment(block, out_path)
        dt = time.time() - t0

        if not ok:
            report["failed"] += 1
            log(f"  x block {i:04d} FAILED — continuing")
        elif needed:
            report["rendered"] += 1
            report["render_seconds"] += dt
            if save_every_block:
                save_ir()  # the resume point
            log(f"  + block {i:04d} [{block.get('speaker', 'NARRATOR'):<12}] {dt:5.1f}s")
        else:
            report["cached"] += 1
        if progress_cb:
            progress_cb(i + 1, len(blocks))

    block_files = []
    for block in blocks:
        url = block.get("audioVariants", {}).get("standard", {}).get("url")
        if url and Path(url).exists():
            block_files.append({"path": url,
                                "speaker": block.get("speaker", "NARRATOR")})
            report["audio_seconds"] += wav_seconds(url)

    final_path = str(lib.chapter_wav_path(book_slug, chapter_index))
    merge_blocks(block_files, final_path)
    save_ir()
    report["wav_path"] = final_path

    mins = report["audio_seconds"] / 60.0
    log(f"[Render] ch{chapter_index} done: {report['rendered']} new / "
        f"{report['cached']} cached / {report['failed']} failed — "
        f"{mins:.1f} min audio")
    if report["rendered"] and mins:
        log(f"[Perf]  ~{report['render_seconds'] / mins:.0f}s render per minute of audio")
    return report
