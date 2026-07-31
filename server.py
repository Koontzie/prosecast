"""
ProseCast — Phase 3a/3b/3c local web server

Endpoints:
  GET  /                                        → index.html UI
  GET  /books                                   → list of processed books (library/<slug>/ir.json)
  POST /books/upload                            → upload an EPUB, run pipeline, return slug
  GET  /chapters/{book_slug}                    → chapter titles + block counts + audio availability
  GET  /ir/{book_slug}                          → full IR JSON
  GET  /ir/{book_slug}/characters               → speaking characters for this book
  GET  /ir/{book_slug}/cast_candidates          → top characters + sample lines + voice defaults
  GET  /ir/{book_slug}/unresolved/{ch}          → unresolved blocks in a chapter
  PATCH /ir/{book_slug}/block/{segment_id}      → correct a block's speaker
  POST  /ir/{book_slug}/block/{segment_id}/merge_next → merge block with next
  GET  /audio/{book_slug}/{filename}            → stream WAV from library/<slug>/renders/
  GET  /timeline/{book_slug}/{chapter_index}    → per-block speaker timeline
  GET  /voices                                  → available voices for the active TTS engine
  GET  /voice_map/{book_slug}                   → character→voice assignments (or auto-assigned defaults)
  POST /voice_map/{book_slug}                   → save character→voice assignments
  GET  /voice/preview/{voice_name}              → synthesize and stream a short sample WAV
  POST /render/{book_slug}/{chapter_index}      → background re-render of one chapter
  POST /render/{book_slug}                      → background re-render of all chapters
  GET  /render_status/{job_id}                  → poll render/export job status
  POST /export/{book_slug}                      → background m4b export of rendered chapters
  GET  /export/{book_slug}/file                 → download the m4b
"""

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
import re
import shutil
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.background import BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prosecast import library as lib

app = FastAPI(title="ProseCast")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

# In-memory render job state: job_id → {status, progress, total, error}
_render_jobs: dict = {}


# ── IR loader (migrates old format lazily) ────────────────────────────────────

def _load_ir(ir_path: Path) -> dict:
    """Load an IR JSON, migrating old-format blocks (id → segmentId) if needed.

    Migration is idempotent: the file is only rewritten when stale fields are found.
    """
    with open(ir_path, encoding="utf-8") as f:
        ir = json.load(f)

    needs_migration = any(
        "segmentId" not in block
        for ch in ir.get("chapters", [])
        for block in ch.get("blocks", [])
    )

    if needs_migration:
        from prosecast.ir_generator import migrate_ir
        ir = migrate_ir(ir)
        with open(ir_path, "w", encoding="utf-8") as f:
            json.dump(ir, f, indent=2, ensure_ascii=False)

    return ir


# ── Corrections journal ───────────────────────────────────────────────────────

def _journal(book_slug: str, event: str, payload: dict) -> None:
    """Append a correction event to the book's append-only journal.

    {slug}_corrections.jsonl is the raw labeled data for the attribution
    training flywheel — every manual correction is a training example.
    Append-only: never rewrite or reorder this file.
    """
    from datetime import datetime, timezone
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        **payload,
    }
    try:
        path = lib.journal_path(book_slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # journaling must never break the correction itself


# ── Speaking characters helper ────────────────────────────────────────────────

def _speaking_characters(ir: dict) -> list[str]:
    """Return sorted list of characters who have at least one attributed dialogue block.

    Excludes UNKNOWN, NARRATOR, and unresolved blocks. Always prepends NARRATOR
    so it appears first in any dropdown regardless of book content.
    """
    seen = set()
    for chapter in ir.get("chapters", []):
        for block in chapter.get("blocks", []):
            if (
                block.get("type") == "dialogue"
                and not block.get("unresolved")
                and block.get("speaker") not in (None, "UNKNOWN", "NARRATOR")
            ):
                seen.add(block["speaker"])
    # NARRATOR always first, then alphabetical speakers, then user-added names
    user_chars = set(ir.get("user_characters", []))
    speaking = sorted(seen | user_chars)
    return ["NARRATOR"] + speaking


# ── Active TTS engine detection (cached at first use) ────────────────────────

_active_engine: str | None = None


def _get_active_engine() -> str:
    global _active_engine
    if _active_engine is None:
        # Explicit override first: PROSECAST_TTS_ENGINE=chatterbox uvicorn server:app
        # Auto-detect prefers ElevenLabs whenever a key is in .env, which makes every
        # UI preview cost credits — the override keeps dogfooding on the free tier.
        override = os.environ.get("PROSECAST_TTS_ENGINE", "").strip().lower()
        if override:
            _active_engine = override
        else:
            from prosecast.tts_engine import TTSEngine
            _active_engine = TTSEngine()._detect()
    return _active_engine


_chatterbox_voice_cache: list[dict] | None = None


def _chatterbox_voices() -> list[dict]:
    """[{id, name}] for the chatterbox engine: predefined voices + clone references.

    ids use the voice-map string format: 'predefined:<file>' for built-ins,
    bare filename for clone references. Cached for the process lifetime.
    """
    global _chatterbox_voice_cache
    if _chatterbox_voice_cache is None:
        from prosecast.tts_engine import (
            fetch_chatterbox_predefined, fetch_chatterbox_references,
        )
        voices = []
        for v in fetch_chatterbox_predefined() or []:
            fname = v.get("filename")
            if not fname:
                continue
            name = v.get("display_name") or Path(fname).stem
            voices.append({"id": f"predefined:{fname}", "name": name})
        for ref in fetch_chatterbox_references() or []:
            voices.append({"id": ref, "name": f"{Path(ref).stem} (clone)"})
        _chatterbox_voice_cache = voices
    return _chatterbox_voice_cache


def _voice_pool(engine: str) -> list[str]:
    """Return the flat list of voice IDs for the given engine (used for validation)."""
    from prosecast.tts_engine import VoiceAssigner
    if engine == 'elevenlabs':
        return [v['id'] for v in VoiceAssigner.ELEVENLABS_VOICES]
    elif engine == 'say':
        return list(VoiceAssigner.SAY_VOICES)
    elif engine == 'piper':
        return list(VoiceAssigner.PIPER_VOICES)
    elif engine == 'gtts':
        return [v['tld'] for v in VoiceAssigner.GTTS_VOICES]
    elif engine == 'chatterbox':
        return [v['id'] for v in _chatterbox_voices()]
    return []


def _voice_labels(engine: str) -> list[dict]:
    """Return [{id, name}] pairs for the given engine.

    For engines where id == name (say, piper, gtts), both fields are the same string.
    For ElevenLabs, id is the opaque API identifier and name is the human-readable label.
    """
    from prosecast.tts_engine import VoiceAssigner
    if engine == 'elevenlabs':
        return [{'id': v['id'], 'name': v['name']} for v in VoiceAssigner.ELEVENLABS_VOICES]
    elif engine == 'chatterbox':
        return _chatterbox_voices()
    ids = _voice_pool(engine)
    return [{'id': v, 'name': v} for v in ids]


def _default_voice_map(characters: list[str], engine: str) -> dict[str, str]:
    """Replicate VoiceAssigner round-robin without synthesizing anything."""
    pool = _voice_pool(engine)
    if not pool:
        return {c: '' for c in characters}
    result = {}
    char_idx = 0
    for speaker in characters:
        if speaker == 'NARRATOR':
            result[speaker] = pool[0]
        else:
            idx = (char_idx % (len(pool) - 1)) + 1 if len(pool) > 1 else 0
            result[speaker] = pool[idx]
            char_idx += 1
    return result


# ── /books ────────────────────────────────────────────────────────────────────

@app.get("/books")
def list_books():
    books = []
    for slug in lib.list_book_slugs():
        try:
            with open(lib.ir_path(slug)) as f:
                ir = json.load(f)
            books.append({
                "slug": slug,
                "title": ir.get("book_title", slug),
                "chapters": len(ir.get("chapters", [])),
                "unresolved": ir.get("unresolved_count", 0),
            })
        except Exception:
            pass
    return books


# ── POST /books/upload ────────────────────────────────────────────────────────

BOOKS_DIR = Path(__file__).parent / "books"


@app.post("/books/upload")
async def upload_book(file: UploadFile = File(...)):
    """Accept an EPUB upload, run it through the parse→IR pipeline, return the slug.

    The file is saved to books/ then processed.  Raises 400 on non-EPUB input
    and 500 if pipeline fails.  Does NOT render audio — that is triggered
    separately by the client via POST /render/{slug}/{chapter_index}.
    """
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="Only .epub files are accepted")

    BOOKS_DIR.mkdir(exist_ok=True)

    # Save the uploaded file
    safe_name = re.sub(r"[^\w\-.]", "_", file.filename)
    book_path = BOOKS_DIR / safe_name
    try:
        with open(book_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        await file.close()

    # Derive slug the same way main.py does
    book_title = book_path.stem.replace("_", " ").title()
    book_slug = re.sub(r"[^\w]", "_", book_title.lower())[:30]
    lib.ensure_book_dir(book_slug)
    ir_path = lib.ir_path(book_slug)

    try:
        from prosecast.book_parser import parse_book
        from prosecast.ir_generator import build_ir, save_ir

        chapters = parse_book(str(book_path))
        if not chapters:
            raise ValueError("No chapters found — check EPUB structure")

        ir = build_ir(book_title, chapters)
        save_ir(ir, str(ir_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    saved = json.loads(ir_path.read_text())
    return {
        "slug": book_slug,
        "title": book_title,
        "chapters": len(saved.get("chapters", [])),
        "unresolved": saved.get("unresolved_count", 0),
    }


# ── /ir/{book_slug}/characters ───────────────────────────────────────────────

@app.get("/ir/{book_slug}/characters")
def get_characters(book_slug: str):
    """Return characters who have at least one attributed dialogue block (speaking characters only).

    NARRATOR is always first. User-introduced names (via corrections) are included.
    """
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    ir = _load_ir(ir_path)
    return {"characters": _speaking_characters(ir)}


# ── /ir/{book_slug}/cast_candidates ─────────────────────────────────────────

@app.get("/ir/{book_slug}/cast_candidates")
def get_cast_candidates(book_slug: str):
    """Return top characters ranked by dialogue count with a sample line, plus voice data.

    Used by the pre-casting modal. Also reports whether a voice map already exists.
    """
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)
    vm_path = lib.voice_map_path(book_slug)
    has_voice_map = vm_path.exists()
    engine = _get_active_engine()

    # Count dialogue blocks per speaker; collect a representative sample line each
    counts: dict[str, int] = {}
    samples: dict[str, str] = {}

    for chapter in ir.get("chapters", []):
        for block in chapter.get("blocks", []):
            if block.get("type") != "dialogue":
                continue
            speaker = block.get("speaker")
            if not speaker or block.get("unresolved"):
                continue
            counts[speaker] = counts.get(speaker, 0) + 1
            if speaker not in samples:
                text = block.get("text", "").strip().strip('"').strip()
                if len(text) >= 30:
                    samples[speaker] = text

    # NARRATOR first, then other characters sorted by count desc, capped at 10
    sorted_chars = sorted(
        [(n, c) for n, c in counts.items() if n != "NARRATOR"],
        key=lambda x: -x[1],
    )[:10]

    characters = [{"name": "NARRATOR", "dialogue_count": counts.get("NARRATOR", 0), "sample_line": None}]
    for name, count in sorted_chars:
        characters.append({"name": name, "dialogue_count": count, "sample_line": samples.get(name)})

    # Build voice map: saved if exists, else defaults
    all_names = [c["name"] for c in characters]
    if has_voice_map:
        with open(vm_path) as f:
            saved = json.load(f)
        voice_map = saved.get("map", {})
        defaults = _default_voice_map(all_names, engine)
        for name in all_names:
            if name not in voice_map:
                voice_map[name] = defaults[name]
    else:
        voice_map = _default_voice_map(all_names, engine)

    return {
        "has_voice_map": has_voice_map,
        "characters": characters,
        "voices": _voice_labels(engine),
        "engine": engine,
        "voice_map": voice_map,
    }


# ── /chapters/{book_slug} ─────────────────────────────────────────────────────

@app.get("/chapters/{book_slug}")
def get_chapters(book_slug: str):
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)

    chapters = []
    for i, ch in enumerate(ir.get("chapters", [])):
        blocks = ch.get("blocks", [])
        dialogue = [b for b in blocks if b["type"] == "dialogue"]
        unresolved = [b for b in dialogue if b.get("unresolved")]
        wav_name = f"ch{i}.wav"
        chapters.append({
            "index": i,
            "title": ch.get("title", f"Chapter {i}"),
            "block_count": len(blocks),
            "dialogue_count": len(dialogue),
            "unresolved_count": len(unresolved),
            "has_audio": lib.chapter_wav_path(book_slug, i).exists(),
            "wav_file": wav_name,
        })
    return {"book_title": ir.get("book_title", book_slug), "chapters": chapters}


# ── /timeline/{book_slug}/{chapter_index} ────────────────────────────────────

@app.get("/timeline/{book_slug}/{chapter_index}")
def get_timeline(book_slug: str, chapter_index: int):
    """
    Returns a speaker timeline for a rendered chapter.
    Each entry has the start time (seconds), speaker, and dialogue text,
    derived from the WAV block files in the blocks directory.
    """
    import wave

    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR for '{book_slug}'")

    ir = _load_ir(ir_path)

    chapters = ir.get("chapters", [])
    if chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail=f"Chapter index {chapter_index} out of range")

    blocks_dir = lib.chapter_blocks_dir(book_slug, chapter_index)
    chapter = chapters[chapter_index]
    blocks = chapter.get("blocks", [])

    timeline = []
    cursor = 0.0  # running time in seconds

    for i, block in enumerate(blocks):
        wav_path = blocks_dir / f"block_{i:04d}.wav"
        duration = 0.0
        if wav_path.exists():
            try:
                with wave.open(str(wav_path)) as wf:
                    duration = wf.getnframes() / wf.getframerate()
            except Exception:
                pass

        timeline.append({
            "block_index": i,
            "segment_id": block.get("segmentId"),
            "start": round(cursor, 3),
            "duration": round(duration, 3),
            "type": block["type"],
            "speaker": block.get("speaker", "NARRATOR"),
            "text": block.get("text", "")[:120],
            "unresolved": block.get("unresolved", False),
        })
        cursor += duration

    return {"chapter_index": chapter_index, "title": chapter.get("title"), "timeline": timeline}


# ── /ir/{book_slug} ───────────────────────────────────────────────────────────

@app.get("/ir/{book_slug}")
def get_ir(book_slug: str):
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    return JSONResponse(content=_load_ir(ir_path))


# ── /ir/{book_slug}/unresolved/{chapter_index} ───────────────────────────────

@app.get("/ir/{book_slug}/unresolved/{chapter_index}")
def get_unresolved(book_slug: str, chapter_index: int):
    """Return all unresolved dialogue blocks in a chapter, with surrounding context."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)

    chapters = ir.get("chapters", [])
    if chapter_index >= len(chapters):
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_index} out of range")

    blocks = chapters[chapter_index].get("blocks", [])
    unresolved = [
        {
            "segment_id": b["segmentId"],
            "text": b["text"],
            "context_before": b.get("context_before", ""),
            "context_after": b.get("context_after", ""),
        }
        for b in blocks
        if b.get("unresolved")
    ]
    return {
        "chapter_index": chapter_index,
        "title": chapters[chapter_index].get("title", f"Chapter {chapter_index}"),
        "unresolved": unresolved,
        "characters": _speaking_characters(ir),
    }


# ── /ir/{book_slug}/block/{segment_id}/context ───────────────────────────────

@app.get("/ir/{book_slug}/block/{segment_id}/context")
def block_context(book_slug: str, segment_id: str,
                  radius: int = Query(default=6, ge=1, le=30)):
    """A readable excerpt of the IR around one block — the 'open the page' view.

    Returns up to `radius` whole blocks on each side of the target so the user
    can read enough surrounding prose to identify an unresolved speaker. Unlike
    the stored context_before/context_after snippets, these are full blocks.
    """
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    ir = _load_ir(ir_path)

    for ci, chapter in enumerate(ir.get("chapters", [])):
        blocks = chapter.get("blocks", [])
        for bi, block in enumerate(blocks):
            if block.get("segmentId") == segment_id:
                lo = max(0, bi - radius)
                hi = min(len(blocks), bi + radius + 1)
                return {
                    "segment_id": segment_id,
                    "chapter_index": ci,
                    "chapter_title": chapter.get("title", f"Chapter {ci}"),
                    "block_index": bi,
                    "total_blocks": len(blocks),
                    "has_more_before": lo > 0,
                    "has_more_after": hi < len(blocks),
                    "blocks": [
                        {
                            "segment_id": b.get("segmentId"),
                            "type": b.get("type"),
                            "speaker": b.get("speaker", "NARRATOR"),
                            "unresolved": bool(b.get("unresolved")),
                            "is_target": b.get("segmentId") == segment_id,
                            "text": b.get("text", ""),
                        }
                        for b in blocks[lo:hi]
                    ],
                }
    raise HTTPException(status_code=404, detail=f"Block '{segment_id}' not found")


# ── PATCH /ir/{book_slug}/block/{segment_id} ─────────────────────────────────

class SpeakerCorrection(BaseModel):
    speaker: str


@app.patch("/ir/{book_slug}/block/{segment_id}")
def correct_block(book_slug: str, segment_id: str, body: SpeakerCorrection):
    """Correct a block's speaker. Clears unresolved, sets attribution_method to 'manual'."""
    speaker = body.speaker.strip()
    if not speaker:
        raise HTTPException(status_code=400, detail="speaker must not be empty")

    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)

    # Find the block by segmentId across all chapters
    found = False
    unresolved_total = 0
    found_chapter_index = None       # chapter containing the corrected block
    chapter_unresolved = 0           # unresolved remaining in THAT chapter only
    old_speaker = None
    old_method = None
    for ci, chapter in enumerate(ir.get("chapters", [])):
        ch_unresolved = 0
        for block in chapter.get("blocks", []):
            if block.get("segmentId") == segment_id:
                old_speaker = block.get("speaker")
                old_method = block.get("attribution_method")
                block["speaker"] = speaker
                block["unresolved"] = False
                block["attribution_method"] = "manual"
                block["confidence"] = 1.0
                found = True
                found_chapter_index = ci
            if block.get("unresolved"):
                ch_unresolved += 1
        unresolved_total += ch_unresolved
        if found_chapter_index == ci:
            chapter_unresolved = ch_unresolved

    if not found:
        raise HTTPException(status_code=404, detail=f"Block '{segment_id}' not found")

    ir["unresolved_count"] = unresolved_total

    # Track user-introduced names separately from system-detected ones
    if speaker not in ("NARRATOR", "UNKNOWN"):
        known = set(ir.get("characters", []))
        if speaker not in known:
            ir.setdefault("characters", [])
            ir["characters"] = sorted(set(ir["characters"]) | {speaker})
            ir.setdefault("user_characters", [])
            if speaker not in ir["user_characters"]:
                ir["user_characters"].append(speaker)
                ir["user_characters"].sort()

    with open(ir_path, "w", encoding="utf-8") as f:
        json.dump(ir, f, indent=2, ensure_ascii=False)

    _journal(book_slug, "speaker_correction", {
        "segment_id": segment_id,
        "old_speaker": old_speaker,
        "new_speaker": speaker,
        "old_method": old_method,
    })

    return {
        "segment_id": segment_id,
        "speaker": speaker,
        "unresolved_count": unresolved_total,              # whole book
        "chapter_index": found_chapter_index,
        "chapter_unresolved_count": chapter_unresolved,    # this chapter only
        "characters": _speaking_characters(ir),
    }


# ── POST /ir/{book_slug}/block/{segment_id}/merge_next ───────────────────────

@app.post("/ir/{book_slug}/block/{segment_id}/merge_next")
def merge_next(book_slug: str, segment_id: str):
    """Merge the block with the following block in the same chapter.

    The current block absorbs the next block's text (space-separated).
    The next block is deleted. The current block's speaker and metadata
    are preserved. Returns the updated block and new unresolved_count.
    """
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)

    merged_block = None
    absorbed_segment_id = None
    for chapter in ir.get("chapters", []):
        blocks = chapter.get("blocks", [])
        for i, block in enumerate(blocks):
            if block.get("segmentId") == segment_id:
                if i + 1 >= len(blocks):
                    raise HTTPException(status_code=400, detail="No next block to merge into")
                next_block = blocks[i + 1]
                absorbed_segment_id = next_block.get("segmentId")
                block["text"] = block["text"].rstrip('"') + " " + next_block["text"].lstrip('"')
                if not block["text"].startswith('"'):
                    pass  # narration merge; text is fine as-is
                block["context_after"] = next_block.get("context_after", "")
                blocks.pop(i + 1)
                merged_block = block
                break
        if merged_block:
            break

    if not merged_block:
        raise HTTPException(status_code=404, detail=f"Block '{segment_id}' not found")

    unresolved_total = sum(
        1 for ch in ir.get("chapters", [])
        for b in ch.get("blocks", [])
        if b.get("unresolved")
    )
    ir["unresolved_count"] = unresolved_total

    with open(ir_path, "w", encoding="utf-8") as f:
        json.dump(ir, f, indent=2, ensure_ascii=False)

    _journal(book_slug, "merge_next", {
        "segment_id": segment_id,
        "absorbed_segment_id": absorbed_segment_id,
        "speaker": merged_block.get("speaker"),
    })

    return {"segment_id": segment_id, "merged_block": merged_block, "unresolved_count": unresolved_total}


# ── DELETE /ir/{book_slug}/character/{name} ──────────────────────────────────

@app.delete("/ir/{book_slug}/character/{name}")
def delete_character(book_slug: str, name: str):
    """Reassign all dialogue blocks attributed to {name} back to NARRATOR.

    Removes {name} from ir['characters'] and ir['user_characters'] if present.
    Returns the count of reassigned blocks.
    """
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)

    reassigned = 0
    reassigned_segments = []
    for chapter in ir.get("chapters", []):
        for block in chapter.get("blocks", []):
            if block.get("speaker") == name:
                block["speaker"] = "NARRATOR"
                block["attribution_method"] = "manual"
                block["confidence"] = 1.0
                if block.get("type") == "dialogue":
                    reassigned += 1
                    reassigned_segments.append(block.get("segmentId"))

    # Remove from character lists
    ir["characters"] = [c for c in ir.get("characters", []) if c != name]
    ir["user_characters"] = [c for c in ir.get("user_characters", []) if c != name]

    with open(ir_path, "w", encoding="utf-8") as f:
        json.dump(ir, f, indent=2, ensure_ascii=False)

    _journal(book_slug, "character_deleted", {
        "name": name,
        "reassigned_to": "NARRATOR",
        "reassigned_count": reassigned,
        "segment_ids": reassigned_segments,
    })

    return {"name": name, "reassigned": reassigned}


# ── Cast review (Phase B) ─────────────────────────────────────────────────────

def _cast_counts(ir: dict) -> tuple[dict[str, int], dict[str, str]]:
    """Dialogue-block counts and one representative sample line per speaker."""
    counts: dict[str, int] = {}
    samples: dict[str, str] = {}
    for chapter in ir.get("chapters", []):
        for block in chapter.get("blocks", []):
            if block.get("type") != "dialogue":
                continue
            speaker = block.get("speaker")
            if not speaker or block.get("unresolved"):
                continue
            counts[speaker] = counts.get(speaker, 0) + 1
            if speaker not in samples:
                text = block.get("text", "").strip().strip('"').strip()
                if len(text) >= 30:
                    samples[speaker] = text
    return counts, samples


def _reassign_speaker(ir: dict, from_name: str, to_name: str) -> tuple[int, list]:
    """Reassign every block of from_name → to_name. Returns (dialogue_count, segment_ids)."""
    count = 0
    seg_ids = []
    for chapter in ir.get("chapters", []):
        for block in chapter.get("blocks", []):
            if block.get("speaker") == from_name:
                block["speaker"] = to_name
                block["attribution_method"] = "manual"
                block["confidence"] = 1.0
                if block.get("type") == "dialogue":
                    count += 1
                    seg_ids.append(block.get("segmentId"))
    ir["characters"] = [c for c in ir.get("characters", []) if c != from_name]
    ir["user_characters"] = [c for c in ir.get("user_characters", []) if c != from_name]
    return count, seg_ids


@app.get("/ir/{book_slug}/cast")
def get_cast(book_slug: str):
    """Full ranked cast list for the cast review screen (no cap, unlike cast_candidates)."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    ir = _load_ir(ir_path)
    counts, samples = _cast_counts(ir)

    vm_path = lib.voice_map_path(book_slug)
    voice_map = {}
    if vm_path.exists():
        with open(vm_path) as f:
            voice_map = json.load(f).get("map", {})

    ranked = sorted(
        [(n, c) for n, c in counts.items() if n != "NARRATOR"],
        key=lambda x: (-x[1], x[0]),
    )
    profiles = ir.get("character_profiles", {})
    characters = [{
        "name": name,
        "dialogue_count": count,
        "sample_line": samples.get(name),
        "voice": voice_map.get(name, ""),
        "profile": profiles.get(name),
    } for name, count in ranked]

    engine = _get_active_engine()
    return {
        "narrator_voice": voice_map.get("NARRATOR", ""),
        "narrator_dialogue_count": counts.get("NARRATOR", 0),
        "characters": characters,
        "voices": _voice_labels(engine),
        "engine": engine,
    }


@app.get("/ir/{book_slug}/character/{name}/lines")
def character_lines(book_slug: str, name: str, limit: int = Query(default=3, le=10)):
    """Up to `limit` dialogue blocks for a character, with surrounding context.

    Powers the cast screen's expandable context view — lets the user judge who a
    'character' actually is before demoting/merging.
    """
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    ir = _load_ir(ir_path)

    lines = []
    for chapter in ir.get("chapters", []):
        for block in chapter.get("blocks", []):
            if (block.get("type") == "dialogue"
                    and block.get("speaker") == name
                    and not block.get("unresolved")):
                lines.append({
                    "chapter": chapter.get("title", ""),
                    "segment_id": block.get("segmentId"),
                    "context_before": (block.get("context_before") or "")[-300:],
                    "text": block.get("text", ""),
                    "context_after": (block.get("context_after") or "")[:300],
                })
                if len(lines) >= limit:
                    return {"name": name, "lines": lines}
    return {"name": name, "lines": lines}


# ── Merge suggestions (deterministic, click-to-confirm) ─────────────────────

def _journal_events(book_slug: str) -> list:
    """Read the append-only corrections journal (empty list if none)."""
    path = lib.journal_path(book_slug)
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


@app.get("/ir/{book_slug}/cast/suggestions")
def cast_merge_suggestions(book_slug: str):
    """Deterministic alias-merge suggestions, minus previously dismissed ones.

    Pure nomination: nothing here mutates the IR. Accepting a suggestion goes
    through the normal POST /cast/merge (journaled); dismissing journals a
    merge_suggestion_dismissed event so the chip never comes back.
    """
    from prosecast.alias_suggester import suggest_merges

    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    ir = _load_ir(ir_path)

    dismissed = {
        (e.get("from"), e.get("into"))
        for e in _journal_events(book_slug)
        if e.get("event") == "merge_suggestion_dismissed"
    }
    suggestions = [
        s for s in suggest_merges(ir)
        if (s["from_name"], s["into"]) not in dismissed
    ]
    return {"suggestions": suggestions}


class DismissSuggestionBody(BaseModel):
    from_name: str
    into: str


@app.post("/ir/{book_slug}/cast/suggestions/dismiss")
def dismiss_merge_suggestion(book_slug: str, body: DismissSuggestionBody):
    """Journal a dismissal so this suggestion pair stops appearing."""
    if not lib.ir_path(book_slug).exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    _journal(book_slug, "merge_suggestion_dismissed", {
        "from": body.from_name,
        "into": body.into,
    })
    return {"dismissed": {"from": body.from_name, "into": body.into}}


class DemoteBody(BaseModel):
    names: list[str] = []
    max_blocks: int | None = None   # demote every character with <= this many blocks


@app.post("/ir/{book_slug}/cast/demote")
def demote_characters(book_slug: str, body: DemoteBody):
    """Bulk-reassign characters to NARRATOR. Explicit names, a max_blocks threshold, or both."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    ir = _load_ir(ir_path)
    counts, _ = _cast_counts(ir)

    targets = set(n for n in body.names if n and n != "NARRATOR")
    if body.max_blocks is not None:
        targets |= {n for n, c in counts.items()
                    if n != "NARRATOR" and c <= body.max_blocks}
    if not targets:
        return {"demoted": {}, "reassigned_total": 0}

    results = {}
    total = 0
    for name in sorted(targets):
        count, seg_ids = _reassign_speaker(ir, name, "NARRATOR")
        results[name] = count
        total += count
        _journal(book_slug, "character_demoted", {
            "name": name, "reassigned_to": "NARRATOR",
            "reassigned_count": count, "segment_ids": seg_ids,
            "bulk": True, "max_blocks_threshold": body.max_blocks,
        })

    with open(ir_path, "w", encoding="utf-8") as f:
        json.dump(ir, f, indent=2, ensure_ascii=False)
    return {"demoted": results, "reassigned_total": total}


class MergeBody(BaseModel):
    from_names: list[str]
    into: str


@app.post("/ir/{book_slug}/cast/merge")
def merge_characters(book_slug: str, body: MergeBody):
    """Merge one or more characters into another (alias collapse, e.g. Kimberly→Kimberley).

    Merge events are labeled alias data for the training flywheel.
    """
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    if not body.into or not body.into.strip():
        raise HTTPException(status_code=400, detail="Merge target 'into' is required")
    into = body.into.strip()
    sources = [n for n in body.from_names if n and n != into]
    if not sources:
        raise HTTPException(status_code=400, detail="No source characters to merge")

    ir = _load_ir(ir_path)
    results = {}
    total = 0
    for name in sources:
        count, seg_ids = _reassign_speaker(ir, name, into)
        results[name] = count
        total += count
        _journal(book_slug, "characters_merged", {
            "from": name, "into": into,
            "reassigned_count": count, "segment_ids": seg_ids,
        })

    with open(ir_path, "w", encoding="utf-8") as f:
        json.dump(ir, f, indent=2, ensure_ascii=False)
    return {"merged": results, "into": into, "reassigned_total": total}


# ── /voices ──────────────────────────────────────────────────────────────────

@app.get("/voices")
def list_voices():
    """Return available voices for the active TTS engine as [{id, name}] pairs."""
    engine = _get_active_engine()
    return {"engine": engine, "voices": _voice_labels(engine)}


# ── /voice_map/{book_slug} ────────────────────────────────────────────────────

@app.get("/voice_map/{book_slug}")
def get_voice_map(book_slug: str):
    """Return saved character→voice assignments, or auto-assigned defaults."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)
    characters = _speaking_characters(ir)
    engine = _get_active_engine()

    vm_path = lib.voice_map_path(book_slug)
    if vm_path.exists():
        with open(vm_path) as f:
            saved = json.load(f)
        voice_map = saved.get("map", {})
        # Fill in any characters not yet in the saved map with auto-assigned defaults
        defaults = _default_voice_map(characters, engine)
        for char in characters:
            if char not in voice_map:
                voice_map[char] = defaults[char]
    else:
        voice_map = _default_voice_map(characters, engine)

    return {"engine": engine, "map": voice_map}


class VoiceMapBody(BaseModel):
    map: dict


@app.post("/voice_map/{book_slug}")
def save_voice_map(book_slug: str, body: VoiceMapBody):
    """Save character→voice assignments. Validates all voice IDs against the active engine's pool."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    engine = _get_active_engine()
    valid_voices = set(_voice_pool(engine))

    if valid_voices:
        bad = {k: v for k, v in body.map.items() if v and v not in valid_voices}
        if bad:
            bad_list = ", ".join(f"{k!r}: {v!r}" for k, v in bad.items())
            raise HTTPException(
                status_code=400,
                detail=f"Unknown voice IDs for engine '{engine}': {bad_list}. "
                       f"Valid voices: {sorted(valid_voices)}",
            )

    vm_path = lib.voice_map_path(book_slug)
    with open(vm_path, "w", encoding="utf-8") as f:
        json.dump({"engine": engine, "map": body.map}, f, indent=2, ensure_ascii=False)

    return {"engine": engine, "map": body.map}


# ── /voice/preview/{voice_name} ───────────────────────────────────────────────

@app.get("/voice/preview/{voice_name}")
def preview_voice(
    voice_name: str,
    background_tasks: BackgroundTasks,
    character: str = Query(default=""),
    text: str = Query(default=""),
):
    """Synthesize a short sample with the given voice and stream it back as WAV.

    Priority for synthesis text:
      1. ?text=... (arbitrary text, e.g. an actual dialogue line)
      2. ?character=Name → "Hello, my name is Name."
      3. Fallback: "Hello."
    Temp file is deleted after the response is sent.
    """
    engine_name = _get_active_engine()
    pool = _voice_pool(engine_name)

    if pool and voice_name not in pool:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown voice '{voice_name}' for engine '{engine_name}'. "
                   f"Valid voices: {pool}",
        )

    if text.strip():
        text = text.strip()[:300]  # cap length for safety
    elif character.strip():
        text = f"Hello, my name is {character}."
    else:
        text = "Hello."

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    tmp_path = tmp.name

    # Bypass VoiceAssigner — call the backend directly with the requested voice.
    from prosecast.tts_engine import (
        _synthesize_say, _synthesize_gtts, _synthesize_piper,
        _synthesize_elevenlabs, _write_stub_wav,
    )
    if engine_name == 'elevenlabs':
        ok = _synthesize_elevenlabs(text, {'voice_id': voice_name}, tmp_path)
    elif engine_name == 'chatterbox':
        from prosecast.tts_engine import _synthesize_chatterbox
        if voice_name.startswith('predefined:'):
            cfg = {'voice_mode': 'predefined',
                   'predefined_voice_id': voice_name.split(':', 1)[1]}
        else:
            cfg = {'voice_mode': 'clone', 'reference_audio_filename': voice_name}
        cfg['_tag_params'] = {'exaggeration': 0.55}
        ok = _synthesize_chatterbox(text, cfg, tmp_path)
    elif engine_name == 'say':
        ok = _synthesize_say(text, {'voice': voice_name}, tmp_path)
    elif engine_name == 'piper':
        ok = _synthesize_piper(text, {'voice': voice_name}, tmp_path)
    elif engine_name == 'gtts':
        ok = _synthesize_gtts(text, {'tld': voice_name, 'slow': False}, tmp_path)
    else:
        _write_stub_wav(tmp_path)
        ok = True

    if not ok:
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail=f"Synthesis failed for voice '{voice_name}'")

    background_tasks.add_task(os.unlink, tmp_path)
    return FileResponse(path=tmp_path, media_type="audio/wav")


# ── /audio/{filename} ────────────────────────────────────────────────────────

@app.get("/audio/{book_slug}/{filename}")
def stream_audio(book_slug: str, filename: str):
    # Safety: only allow plain names, no path traversal
    if any("/" in part or ".." in part for part in (book_slug, filename)):
        raise HTTPException(status_code=400, detail="Invalid path")
    wav_path = lib.renders_dir(book_slug) / filename
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file '{filename}' not found")
    return FileResponse(
        path=str(wav_path),
        media_type="audio/wav",
        headers={"Accept-Ranges": "bytes"},
    )


# ── Render endpoints ──────────────────────────────────────────────────────────

def _run_render_job(job_id: str, ir: dict, chapter_indices: list[int], book_slug: str, ir_path: str):
    """Background thread target: renders given chapters and updates _render_jobs."""
    try:
        from main import generate_audio as _gen_audio
        # Pin the engine the UI is running with (PROSECAST_TTS_ENGINE override
        # included). Without this, generate_audio auto-detects and silently
        # renders whole chapters on ElevenLabs credits whenever a key is in .env.
        engine = _get_active_engine()
        _render_jobs[job_id]["total"] = len(chapter_indices)
        for i, ch_idx in enumerate(chapter_indices):
            _render_jobs[job_id]["progress"] = i
            _gen_audio(ir, ch_idx, book_slug, tts_override=engine, ir_path=ir_path)
        _render_jobs[job_id]["progress"] = len(chapter_indices)
        _render_jobs[job_id]["status"] = "done"
    except Exception as e:
        _render_jobs[job_id]["status"] = "error"
        _render_jobs[job_id]["error"] = str(e)


@app.post("/render/{book_slug}/{chapter_index}")
def render_chapter(book_slug: str, chapter_index: int):
    """Trigger a background re-render of one chapter. Returns a job_id to poll."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)
    chapter_count = len(ir.get("chapters", []))
    if chapter_index >= chapter_count:
        raise HTTPException(status_code=400, detail=f"Chapter {chapter_index} out of range (book has {chapter_count})")

    job_id = uuid.uuid4().hex[:10]
    _render_jobs[job_id] = {"status": "running", "progress": 0, "total": 1, "error": None}

    t = threading.Thread(
        target=_run_render_job,
        args=(job_id, ir, [chapter_index], book_slug, str(ir_path)),
        daemon=True,
    )
    t.start()
    return {"job_id": job_id}


@app.post("/render/{book_slug}")
def render_book(book_slug: str):
    """Trigger a background re-render of all chapters. Returns a job_id to poll."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)
    chapter_count = len(ir.get("chapters", []))
    if not chapter_count:
        raise HTTPException(status_code=400, detail="Book has no chapters")

    job_id = uuid.uuid4().hex[:10]
    _render_jobs[job_id] = {"status": "running", "progress": 0, "total": chapter_count, "error": None}

    t = threading.Thread(
        target=_run_render_job,
        args=(job_id, ir, list(range(chapter_count)), book_slug, str(ir_path)),
        daemon=True,
    )
    t.start()
    return {"job_id": job_id}


@app.get("/render_status/{job_id}")
def get_render_status(job_id: str):
    """Poll the status of a background render or export job."""
    if job_id not in _render_jobs:
        raise HTTPException(status_code=404, detail=f"No job '{job_id}'")
    return _render_jobs[job_id]


# ── M4B export endpoints ──────────────────────────────────────────────────────

def _run_export_job(job_id: str, book_slug: str, author: str = ""):
    """Background thread target: builds the m4b and updates _render_jobs."""
    from prosecast.m4b_export import export_m4b, M4BExportError
    try:
        res = export_m4b(book_slug, author=author)
        _render_jobs[job_id]["progress"] = 1
        _render_jobs[job_id]["status"] = "done"
        _render_jobs[job_id]["result"] = {
            "exported_chapters": res["exported_chapters"],
            "skipped_chapters": len(res["skipped_chapters"]),
            "duration_ms": res["duration_ms"],
            "size_bytes": res["size_bytes"],
        }
    except Exception as e:
        _render_jobs[job_id]["status"] = "error"
        _render_jobs[job_id]["error"] = str(e)


@app.post("/export/{book_slug}")
def export_book(book_slug: str, author: str = Query(default="")):
    """Trigger a background m4b export of all rendered chapters. Returns a job_id to poll."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")

    ir = _load_ir(ir_path)
    rendered = [
        i for i in range(len(ir.get("chapters", [])))
        if lib.chapter_wav_path(book_slug, i).exists()
    ]
    if not rendered:
        raise HTTPException(status_code=400, detail="No rendered chapters — render audio first")

    job_id = uuid.uuid4().hex[:10]
    _render_jobs[job_id] = {"status": "running", "progress": 0, "total": 1, "error": None}
    t = threading.Thread(target=_run_export_job, args=(job_id, book_slug, author), daemon=True)
    t.start()
    return {"job_id": job_id, "rendered_chapters": len(rendered)}


@app.get("/export/{book_slug}/file")
def download_m4b(book_slug: str):
    """Download the most recent m4b export for this book."""
    m4b = lib.m4b_path(book_slug)
    if not m4b.exists():
        raise HTTPException(status_code=404, detail="No m4b export — run POST /export/{slug} first")

    # Friendly download filename from the book title
    nice_name = book_slug
    try:
        title = json.load(open(lib.ir_path(book_slug))).get("book_title", book_slug)
        nice_name = re.sub(r"[^\w\- ]", "", title).strip() or book_slug
    except Exception:
        pass
    return FileResponse(path=str(m4b), media_type="audio/mp4", filename=f"{nice_name}.m4b")


# ── / → index.html ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>index.html not found in static/</h1>", status_code=500)
