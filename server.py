"""
ProseCast — Phase 3a/3b/3c local web server

Endpoints:
  GET  /                                        → index.html UI
  GET  /books                                   → list of processed books (library/<slug>/ir.json)
  POST /books/upload                            → save an .epub/.txt/.pdf, report format +
                                                  mode guess + PDF chapter split (no ingest)
  POST /books/ingest                            → ingest an upload in a mode (novel/narrator/
                                                  play) on its own thread; returns a job_id
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
  GET  /config                                  → resolved settings (secrets masked) + sources
  PUT  /config                                  → merge settings into config.json
  GET  /setup/status                            → live probes: engine, Ollama, whisper, tools, GPU
  GET  /pipeline/{book_slug}                    → pipeline card state: AI-pass history,
                                                  per-chapter alignment, probe verdicts
  POST /pipeline/{book_slug}/ai_pass            → queue the LLM attribution (+ profile) pass
  POST /pipeline/{book_slug}/align              → queue word alignment for chapters
"""

import copy
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
import re
from typing import Any
import shutil
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.background import BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prosecast import ingest as ingest_mod
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
        lib.write_json_atomic(ir_path, ir)

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
        from prosecast import config as _cfg
        override = _cfg.get("tts_engine")
        if override and override != "auto":
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


VOICE_META_PATH = Path(__file__).parent / "voice_meta.json"


def _voice_meta() -> dict:
    """Hand-edited voice metadata overlay (gender labels, notes).

    Read per request (not cached) so edits to voice_meta.json show up on the
    next UI refresh without a server restart.
    """
    try:
        with open(VOICE_META_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _voice_key(voice_id: str) -> str:
    """The canonical overlay key for a voice id: the filename stem.

    'predefined:us-nyc-add.wav' and 'us-nyc-add.wav' both key on 'us-nyc-add'.
    Every NEW write to voice_meta.json uses this; the read path still falls
    back to the display name because the hand-edited file has entries in both
    styles ('Robert' alongside 'bright-indian-1').
    """
    return Path(str(voice_id).split(":", 1)[-1]).stem


def _clean_tags(raw) -> list[str]:
    """Free-form tags, lowercased, de-duplicated, order preserved, capped at 12."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for t in raw:
        t = str(t).strip().lower()[:40]
        if t and t not in out:
            out.append(t)
    return out[:12]


def _norm_meta(m: dict) -> dict:
    """One overlay entry, normalised to the full schema with safe defaults.

    Old entries carry only gender/notes; the staging script adds region,
    accent_label, license, distributable and source_url; the Voices view adds
    tags, rating and hidden. Everything is optional and nothing here raises —
    a hand-edited file must never be able to take the voice list down.
    """
    m = m if isinstance(m, dict) else {}
    g = str(m.get("gender", "")).strip().lower()[:1]
    try:
        rating = int(m.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0
    return {
        "gender": g if g in ("f", "m") else "",
        "notes": str(m.get("notes") or ""),
        "tags": _clean_tags(m.get("tags")),
        "rating": min(5, max(0, rating)),
        "hidden": bool(m.get("hidden")),
        "region": str(m.get("region") or ""),
        "accent_label": str(m.get("accent_label") or ""),
        "license": str(m.get("license") or ""),
        "distributable": bool(m.get("distributable")),
        "source_url": str(m.get("source_url") or ""),
    }


def _lookup_meta(meta: dict, voice_id: str, name: str) -> dict:
    """Overlay entry for a voice: stem first, then the legacy display-name key."""
    stem = _voice_key(voice_id)
    return _norm_meta(meta.get(stem) or meta.get(name) or {})


def _apply_voice_meta(voices: list[dict]) -> list[dict]:
    """Merge the voice_meta.json overlay into [{id, name}] voice entries.

    `name` gains the gender glyph — that is a DISPLAY string, never a key; the
    overlay key is `_voice_key(id)`. Every other overlay field rides along so
    the cast drawer can grey out a retired voice and the Voices view can filter
    on provenance without a second round trip.
    """
    meta = _voice_meta()
    out = []
    for v in voices:
        m = _lookup_meta(meta, v["id"], v["name"])
        g = m["gender"]
        glyph = " ♀" if g == "f" else " ♂" if g == "m" else ""
        out.append({"id": v["id"], "name": v["name"] + glyph, **m})
    return out


def _raw_voices(engine: str) -> list[dict]:
    """[{id, name}] for the given engine, before any overlay is applied.

    For engines where id == name (say, piper, gtts), both fields are the same
    string. For ElevenLabs, id is the opaque API identifier and name is the
    human-readable label. The Voices view wants these clean names — the glyph
    `_apply_voice_meta` appends is display only (see `_voice_key`).
    """
    from prosecast.tts_engine import VoiceAssigner
    if engine == 'elevenlabs':
        return [{'id': v['id'], 'name': v['name']} for v in VoiceAssigner.ELEVENLABS_VOICES]
    if engine == 'chatterbox':
        return list(_chatterbox_voices())
    return [{'id': v, 'name': v} for v in _voice_pool(engine)]


def _voice_labels(engine: str) -> list[dict]:
    """Return [{id, name, gender, ...overlay}] for the given engine.

    gender comes from the hand-edited voice_meta.json overlay ('' when
    unlabeled) and the name carries its ♀/♂ glyph; `hidden` rides along so the
    cast drawer can grey out a retired voice without dropping it (a voice
    already cast must stay selectable).
    """
    return _apply_voice_meta(_raw_voices(engine))


# Server-side test artefacts, not real voices. One definition, shared with
# scripts/audition_voices.py — see _test_artefact_re().
def _test_artefact_re():
    try:
        from scripts.audition_voices import _SKIP
        return _SKIP
    except Exception:                      # scripts/ missing from a slim deploy
        import re
        return re.compile(r"cachetest|selftest|scanprobe", re.IGNORECASE)


def _voice_pool_assignable(engine: str) -> list[str]:
    """The pool ProseCast may auto-assign FROM: everything, minus retired
    voices and minus the Chatterbox server's own test artefacts.

    Deliberately NOT the same list `_voice_pool` returns. That one validates
    saved voice maps, and narrowing it would 400 every book that already has a
    hidden voice cast — a policy decision that would look exactly like a UI bug.
    Hiding changes what we pick for you; it never changes what you may keep.
    """
    skip = _test_artefact_re()
    meta = _voice_meta()
    out = []
    for v in _raw_voices(engine):
        if skip.search(str(v["id"])):
            continue
        if _lookup_meta(meta, v["id"], v["name"])["hidden"]:
            continue
        out.append(v["id"])
    return out


def _default_voice_map(characters: list[str], engine: str) -> dict[str, str]:
    """Replicate VoiceAssigner round-robin without synthesizing anything."""
    # Hidden voices are excluded here and nowhere else. If retiring left
    # nothing to cast with, fall back to the full pool rather than handing
    # every character an empty voice.
    pool = _voice_pool_assignable(engine) or _voice_pool(engine)
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


# ── POST /books/upload → inspect; POST /books/ingest → do it (E2.1) ──────────

BOOKS_DIR = ingest_mod.BOOKS_DIR          # same path as before; ingest owns it now

_uploads: dict = {}                       # upload_id → prepare() info
_UPLOADS_KEPT = 40                        # bound the dict; uploads are cheap to redo


@app.post("/books/upload")
async def upload_book(file: UploadFile = File(...)):
    """Save an uploaded book and report what it looks like. Does NOT ingest.

    Two-step on purpose: ingesting a Parade-sized EPUB inside the request
    thread takes long enough to trip proxies, and the wizard needs to show the
    mode guess (and, for a PDF, the detected chapter split) before anything is
    committed. Follow up with POST /books/ingest, then poll /render_status.
    """
    name = file.filename or ""
    ext = Path(name).suffix.lower()
    if ext not in ingest_mod.SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"ProseCast reads {', '.join(ingest_mod.SUPPORTED)} — "
                   f"'{name or 'that file'}' is {ext or 'missing an extension'}.")

    dest = ingest_mod.unique_upload_path(name, BOOKS_DIR)
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        await file.close()

    try:
        info = ingest_mod.prepare(dest)
    except ingest_mod.IngestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read '{dest.name}': {e}")

    upload_id = uuid.uuid4().hex[:10]
    _uploads[upload_id] = info
    for stale in list(_uploads)[:-_UPLOADS_KEPT]:
        _uploads.pop(stale, None)

    return {
        "upload_id": upload_id,
        "filename": info["filename"],
        "format": info["format"],
        "title": info["title"],
        "slug": info["slug"],
        "guess_mode": info["guess_mode"],
        "guess_reason": info["guess_reason"],
        "modes": list(ingest_mod.MODES),
        "is_scan": info["is_scan"],
        "scan": info["scan"],
        "detection": info["detection"],
        # only set for a scan: can this machine OCR it, and if not, how to fix that
        "ocr_available": info.get("ocr_available"),
        "ocr_hint": info.get("ocr_hint"),
    }


class IngestBody(BaseModel):
    upload_id: str
    mode: str | None = None          # None → whatever prepare() guessed
    title: str | None = None
    chapters: list | None = None     # reviewed PDF split (page/title/skip)
    keep_tables: bool = False
    ocr: bool = False                # read a scanned PDF with tesseract first


def _run_ingest_job(job_id: str, path, mode: str, title: str,
                    chapters, keep_tables: bool, ocr: bool = False,
                    finish=None) -> None:
    """Background thread target. Deliberately NOT on the render queue: ingest is
    CPU-bound and GPU-free, and a new upload must not sit behind an overnight
    book render.

    Takes a plain path, not an upload entry: POST /books/sample writes its file
    itself and never goes through the in-memory upload table.

    `finish(job, result)` runs *before* the job is marked done, so anything the
    caller must have in place — the sample book's voice map — is on disk by the
    time a poller sees `done` and fires the next request.
    """
    job = _render_jobs[job_id]

    def progress(stage: str, detail: str = "") -> None:
        with _jobs_lock:
            job["stage"] = stage
            job["detail"] = detail
            if stage in ingest_mod.STAGES:
                job["progress"] = ingest_mod.STAGES.index(stage) + 1

    try:
        res = ingest_mod.run(path, mode, slug=job["book_slug"], title=title,
                             chapters=chapters, keep_tables=keep_tables, ocr=ocr,
                             progress=progress)
        if finish is not None:
            finish(job, res)
        with _jobs_lock:
            job.update(status="done", progress=len(ingest_mod.STAGES), result=res)
    except ingest_mod.IngestError as e:
        with _jobs_lock:
            job.update(status="error", error=str(e))
    except Exception as e:
        with _jobs_lock:
            job.update(status="error", error=f"Ingest failed: {e}")


@app.post("/books/ingest")
def ingest_book(body: IngestBody):
    """Ingest a previously uploaded file in the chosen mode. Returns a job_id
    to poll at /render_status/{job_id} (kind: 'ingest', plus stage + detail)."""
    info = _uploads.get(body.upload_id)
    if not info:
        raise HTTPException(status_code=404,
                            detail="That upload has expired — add the file again.")
    mode = body.mode or info["guess_mode"]
    if mode not in ingest_mod.MODES:
        raise HTTPException(status_code=400,
                            detail=f"Unknown mode '{mode}' — pick one of "
                                   f"{', '.join(ingest_mod.MODES)}.")
    if info["is_scan"]:
        # A scan is only readable if the user asked for OCR and tesseract is here.
        from prosecast import ocr as ocr_mod
        if not body.ocr:
            raise HTTPException(
                status_code=400,
                detail=f"'{info['filename']}' is a scan with no text layer. Add it again "
                       "and choose to read it with OCR.")
        if not ocr_mod.available():
            raise HTTPException(
                status_code=400,
                detail=f"'{info['filename']}' needs OCR, but tesseract isn't installed. "
                       f"{ocr_mod.install_hint()} — then add the file again.")

    title = (body.title or info["title"]).strip() or info["title"]
    slug = ingest_mod.slug_for(title)
    chapters = body.chapters
    if chapters is None and info.get("detection"):
        chapters = info["detection"]["chapters"]

    job_id = uuid.uuid4().hex[:10]
    _render_jobs[job_id] = {
        "job_id": job_id, "kind": "ingest", "book_slug": slug, "mode": mode,
        "ocr": body.ocr,
        "status": "running", "progress": 0, "total": len(ingest_mod.STAGES),
        "stage": "queued", "detail": f"reading {info['filename']}",
        "error": None, "result": None,
    }
    threading.Thread(target=_run_ingest_job, daemon=True, name=f"ingest-{slug}",
                     args=(job_id, info["path"], mode, title, chapters, body.keep_tables,
                           body.ocr)).start()
    return {"job_id": job_id, "slug": slug, "mode": mode, "title": title}


# ── POST /books/sample → the built-in sample book, as a book (E6.1) ──────────

SAMPLE_SLUG = "sample_book"


def _ensure_sample_cast() -> bool:
    """Give the sample book a voice map for whatever engine is active.

    The render preflight refuses an uncast book — rightly, because an overnight
    round-robin is never what anyone wanted — and it refuses a voice map made
    for a different engine. Both are correct for a real book and both are dead
    ends for the first-run wizard, which has no casting step and whose whole
    promise is that you hear something. The sample book is a demo asset this
    endpoint owns end to end, not anyone's casting labor, so it is the one book
    ProseCast will cast for you. No other book is touched.

    Returns True if it (re)cast — which also means any audio already on disk was
    made by a different engine and must not be reused.
    """
    engine = _get_active_engine()
    pool = set(_voice_pool(engine))
    vm_path = lib.voice_map_path(SAMPLE_SLUG)
    if vm_path.exists():
        try:
            saved = json.loads(vm_path.read_text())
        except Exception:
            saved = {}
        entries = saved.get("map") or {}
        if entries and saved.get("engine") == engine and (
                not pool or all(v in pool for v in entries.values())):
            return False                      # already cast for this engine

    characters = _speaking_characters(_load_ir(lib.ir_path(SAMPLE_SLUG)))
    lib.ensure_book_dir(SAMPLE_SLUG)
    with open(vm_path, "w", encoding="utf-8") as f:
        json.dump({"engine": engine, "map": _default_voice_map(characters, engine)},
                  f, indent=2, ensure_ascii=False)
    return True


def _cast_the_sample(job: dict, result: dict) -> None:
    """Runs inside the ingest job, before it is marked done — a poller that sees
    `done` and immediately posts a render must not beat the voice map to disk."""
    job["stage"] = "casting"
    job["detail"] = "giving everyone a voice"
    try:
        job["recast"] = _ensure_sample_cast()
    except Exception as e:                    # the book is fine; say what failed
        job["cast_error"] = str(e)


def _run_sample_job(job_id: str, path) -> None:
    """The sample book's ingest, plus the casting that makes it playable."""
    _run_ingest_job(job_id, path, "novel", "Sample Book", None, False, False,
                    finish=_cast_the_sample)


@app.post("/books/sample")
def create_sample_book():
    """Put the built-in sample book in the library, ingesting it if it is new.

    `library/` and `books/` are gitignored, so a fresh clone has no books at
    all and the first-run wizard has nothing to read. This is the only way the
    sample book is created — the wizard's last step calls it, and so can
    anyone who deleted it.

    Idempotent: if `library/sample_book/ir.json` is already there this does no
    ingest. Otherwise it writes the text and runs the same ingest job
    `/books/ingest` runs — own daemon thread, rules-only attribution, no LLM —
    returning a `job_id` to poll at `/render_status/{job_id}` like any other
    ingest.

    Either way the sample book ends up cast for the active engine (see
    `_ensure_sample_cast`); `recast` says whether that had to be redone, which
    is the caller's signal that audio already on disk came from another engine
    and the render wants `force=true`.
    """
    ir_path = lib.ir_path(SAMPLE_SLUG)
    if ir_path.exists():
        try:
            chapters = len(_load_ir(ir_path).get("chapters", []))
        except Exception:
            chapters = 0
        return {"slug": SAMPLE_SLUG, "exists": True, "chapters": chapters,
                "recast": _ensure_sample_cast()}

    from prosecast.book_parser import write_sample_book
    path = BOOKS_DIR / "sample_book.txt"
    try:
        write_sample_book(str(path))
    except OSError as e:
        raise HTTPException(status_code=500,
                            detail=f"Could not write the sample book to {path}: {e}")

    job_id = uuid.uuid4().hex[:10]
    _render_jobs[job_id] = {
        "job_id": job_id, "kind": "ingest", "book_slug": SAMPLE_SLUG, "mode": "novel",
        "ocr": False,
        "status": "running", "progress": 0, "total": len(ingest_mod.STAGES),
        "stage": "queued", "detail": "preparing the sample book",
        "error": None, "result": None,
    }
    threading.Thread(target=_run_sample_job, daemon=True, name=f"ingest-{SAMPLE_SLUG}",
                     args=(job_id, path)).start()
    return {"slug": SAMPLE_SLUG, "exists": False, "job_id": job_id}


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
            # The player's speaker label, the reader's per-paragraph label and its
            # dialogue styling all read this. Dropped by accident while
            # un-truncating `text` (30740dc, 2026-08-04), which made every line render as
            # NARRATOR. tests/test_timeline.py holds the line now.
            "speaker": block.get("speaker", "NARRATOR"),
            # Full text — the player needs it to keep the follow-along display
            # moving through long blocks (was truncated to 120 chars, which
            # froze the display on the first sentence of every long block).
            "text": block.get("text", ""),
            "unresolved": block.get("unresolved", False),
        })
        cursor += duration

    return {"chapter_index": chapter_index, "title": chapter.get("title"), "timeline": timeline}


# ── /word_timings/{book_slug}/{chapter_index} ────────────────────────────────

@app.get("/word_timings/{book_slug}/{chapter_index}")
def get_word_timings(book_slug: str, chapter_index: int):
    """Word-level timestamps for a rendered chapter (scripts/align_words.py).

    Returns {"words": null} when absent or stale (blocks re-rendered since
    alignment) — the player falls back to sentence estimation. Additive only.
    """
    from prosecast.word_aligner import (
        STALE_TOLERANCE_SECS, chapter_blocks_fingerprint, timings_path,
    )
    tp = timings_path(book_slug, chapter_index)
    if not tp.exists():
        return {"words": None, "stale": False}
    try:
        doc = json.loads(tp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"words": None, "stale": False}
    fingerprint = chapter_blocks_fingerprint(book_slug, chapter_index)
    if abs(doc.get("total_duration", -1) - fingerprint) > STALE_TOLERANCE_SECS:
        return {"words": None, "stale": True}
    return {"words": doc.get("words", []), "stale": False}


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

    lib.write_json_atomic(ir_path, ir)

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

    lib.write_json_atomic(ir_path, ir)

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

    lib.write_json_atomic(ir_path, ir)

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
    tier_overrides = ir.get("character_tiers", {})

    def _tier(name: str, count: int) -> tuple[str, str]:
        if name in tier_overrides:
            return tier_overrides[name], "manual"
        return ("main" if count >= MAIN_TIER_MIN_LINES else "supporting"), "auto"

    characters = []
    for name, count in ranked:
        tier, tier_source = _tier(name, count)
        characters.append({
            "name": name,
            "dialogue_count": count,
            "sample_line": samples.get(name),
            "voice": voice_map.get(name, ""),
            "profile": profiles.get(name),
            "tier": tier,
            "tier_source": tier_source,
        })

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


# ── Character tiers (main vs supporting) ────────────────────────────────────

MAIN_TIER_MIN_LINES = 25   # default: this many dialogue lines ⇒ main cast


class TierBody(BaseModel):
    name: str
    tier: str   # "main" | "supporting" | "auto" (clear the manual override)


@app.post("/ir/{book_slug}/cast/tier")
def set_character_tier(book_slug: str, body: TierBody):
    """Manually override a character's tier (or 'auto' to fall back to the
    line-count heuristic). Tier steers casting UX only — grouping in the cast
    screen and which characters Auto-cast fills — never attribution."""
    if body.tier not in ("main", "supporting", "auto"):
        raise HTTPException(status_code=400, detail="tier must be main|supporting|auto")
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    ir = _load_ir(ir_path)

    tiers = ir.setdefault("character_tiers", {})
    if body.tier == "auto":
        tiers.pop(body.name, None)
    else:
        tiers[body.name] = body.tier

    lib.write_json_atomic(ir_path, ir)
    _journal(book_slug, "tier_set", {"name": body.name, "tier": body.tier})
    return {"name": body.name, "tier": body.tier}


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

    lib.write_json_atomic(ir_path, ir)
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

    lib.write_json_atomic(ir_path, ir)
    return {"merged": results, "into": into, "reassigned_total": total}


# ── /voices ──────────────────────────────────────────────────────────────────

@app.get("/voices")
def list_voices():
    """Return available voices for the active TTS engine as [{id, name}] pairs."""
    engine = _get_active_engine()
    return {"engine": engine, "voices": _voice_labels(engine)}


# ── /voices/library, /voices/meta, /voices/sources (Phase E7) ────────────────
#
# The Voices view's own endpoints. Deliberately NOT an extension of /voices:
# the cast drawer and the casting modal read that shape, and growing it to
# carry provenance and orphans would make every drawer open pay for the
# Voices page. `key` here is the canonical overlay key — the filename stem —
# and it is what the UI writes back with.

VOICE_SOURCES_PATH = Path(__file__).parent / "voice_sources.json"

_META_FIELDS = ("gender", "notes", "tags", "rating", "hidden")


@app.get("/voices/library")
def voices_library():
    """Every voice the active engine has, with its full overlay, plus orphans."""
    engine = _get_active_engine()
    skip = _test_artefact_re()
    meta = _voice_meta()

    voices, seen = [], set()
    for v in _raw_voices(engine):
        vid = str(v["id"])
        if skip.search(vid):
            continue                       # cachetest/selftest/scanprobe — not voices
        key = _voice_key(vid)
        seen.add(key)
        seen.add(v["name"])                # legacy display-name keys count as matched
        voices.append({
            "id": vid,
            "name": v["name"],             # clean: the glyph is the drawer's business
            "key": key,
            "kind": "clone" if (engine == "chatterbox"
                                and not vid.startswith("predefined:")) else "predefined",
            **_lookup_meta(meta, vid, v["name"]),
        })

    # Overlay entries with no live voice behind them. A voice deleted on the
    # server must not silently take Tyler's notes with it, so they are surfaced
    # rather than cleaned up.
    orphans = [k for k in meta
               if k != "_readme" and k not in seen and isinstance(meta[k], dict)]

    return {"engine": engine, "voices": voices, "orphans": sorted(orphans)}


class VoiceMetaPatch(BaseModel):
    """Every field is typed loosely on purpose: a wrong type should come back
    as a 400 with a sentence a person can act on, not pydantic's 422."""
    gender: Any = None
    notes: Any = None
    tags: Any = None
    rating: Any = None
    hidden: Any = None


@app.post("/voices/meta/{key}")
def save_voice_meta(key: str, body: VoiceMetaPatch):
    """Patch one voice's overlay entry. Absent fields are left alone.

    Unknown keys are accepted on purpose: a voice can be annotated before it
    exists on the server, and the alternative is losing the note.
    """
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to change.")

    def bad(msg):
        return HTTPException(status_code=400, detail=msg)

    if "gender" in patch:
        g = patch["gender"]
        if not isinstance(g, str) or g.strip().lower() not in ("f", "m", ""):
            raise bad(f"gender must be 'f', 'm' or '' (empty for unlabeled), not {g!r}.")
        patch["gender"] = g.strip().lower()
    if "rating" in patch:
        r = patch["rating"]
        if isinstance(r, bool) or not isinstance(r, int) or not 0 <= r <= 5:
            raise bad("rating must be a whole number from 0 to 5 (0 = unrated).")
    if "hidden" in patch and not isinstance(patch["hidden"], bool):
        raise bad("hidden must be true or false.")
    if "tags" in patch:
        raw = patch["tags"]
        if not isinstance(raw, list) or any(not isinstance(t, str) for t in raw):
            raise bad("tags must be a list of strings.")
        if len(raw) > 12:
            raise bad(f"at most 12 tags per voice (got {len(raw)}).")
        if any(len(t.strip()) > 40 for t in raw):
            raise bad("a tag may be at most 40 characters.")
        patch["tags"] = _clean_tags(raw)
    if "notes" in patch:
        if not isinstance(patch["notes"], str):
            raise bad("notes must be text.")
        if len(patch["notes"]) > 2000:
            raise bad(f"notes may be at most 2000 characters (got {len(patch['notes'])}).")

    data = _voice_meta()
    entry = dict(data.get(key) or {})
    # No stem entry yet, but this voice may already be annotated under the
    # legacy DISPLAY-name key ('Gianna (clone)' for stem 'Gianna'). Carry that
    # content forward so a first edit does not read as wiping the old note.
    # The legacy entry is left in place — the read path prefers the stem, and
    # deleting one of Tyler's lines to tidy up is not this endpoint's call.
    if not entry:
        try:
            for v in _raw_voices(_get_active_engine()):
                if _voice_key(v["id"]) == key and isinstance(data.get(v["name"]), dict):
                    entry = dict(data[v["name"]])
                    break
        except Exception:
            pass          # engine unreachable — saving the note still matters more
    entry.update(patch)
    data[key] = entry

    # write_json_atomic, not open(..,'w'): _voice_meta() swallows JSONDecodeError
    # and returns {}, so a half-written file is a SILENT total loss of every
    # note in it — the failure would not even look like a failure.
    lib.write_json_atomic(VOICE_META_PATH, data)
    return {"key": key, "entry": _norm_meta(entry)}


@app.get("/voices/sources")
def voices_sources():
    """The vetted voice-corpus catalogue. Read-only: it shells out to nothing,
    downloads nothing, and never POSTs to the Chatterbox server. The panel
    shows a command; a human runs it."""
    try:
        data = json.loads(VOICE_SOURCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500,
                            detail=f"Could not read voice_sources.json: {e}")
    return data


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


# ── Engine status ─────────────────────────────────────────────────────────────
#
# The active engine is decided ONCE at startup and cached for the process
# lifetime. A probe that timed out (shared server mid-synthesis) silently
# demoted rendering to macOS `say` with no visible sign — which is exactly the
# failure this endpoint exists to make impossible to miss.

@app.get("/engine_status")
def engine_status():
    """What engine/model this server is actually going to render with."""
    engine = _get_active_engine()
    from prosecast import config as _cfg
    override = _cfg.get("tts_engine") != "auto"
    info = {
        "engine": engine,
        "source": "override" if override else "auto-detected",
        "ok": True,
        "model": None,
        "device": None,
        "detail": "",
        "voice_count": 0,
        "endpoint": None,
    }
    if engine == "chatterbox":
        from prosecast import tts_engine as tts
        info["endpoint"] = tts.CHATTERBOX_BASE_URL
        from prosecast.preflight import _fetch_model_info
        mi = _fetch_model_info(timeout=8.0)
        if mi is None:
            info["ok"] = False
            info["detail"] = "server not responding"
        else:
            info["model"] = mi.get("class_name") or mi.get("type")
            info["device"] = mi.get("device")
            if "turbo" in (str(mi.get("type", "")) + str(mi.get("class_name", ""))).lower():
                info["ok"] = False
                info["detail"] = "TURBO model — emotion controls ignored"
        info["voice_count"] = len(_chatterbox_voices())
    elif engine == "elevenlabs":
        info["model"] = "ElevenLabs (paid API)"
        info["detail"] = "renders cost credits"
        info["voice_count"] = len(_voice_pool(engine))
    else:
        info["model"] = {"say": "macOS system voices",
                         "piper": "Piper (local)",
                         "gtts": "Google TTS",
                         "stub": "silent stub"}.get(engine, engine)
        info["voice_count"] = len(_voice_pool(engine))
        if engine == "say":
            info["ok"] = False
            info["detail"] = "fallback engine — Chatterbox was unreachable at startup"
    return info


@app.post("/engine_status/recheck")
def engine_status_recheck():
    """Drop the cached engine + voice list and probe again (no restart needed)."""
    global _active_engine, _chatterbox_voice_cache
    _active_engine = None
    _chatterbox_voice_cache = None
    return engine_status()


# ── Config + Setup (Phase E4.1 / E4.2) ───────────────────────────────────────
#
# config.json (repo root, gitignored) is the source of truth for URLs, the
# engine choice and the ElevenLabs key; env vars still override it. The Setup
# page reads /setup/status, which probes everything live and says, per row,
# what was found and what to do about it.

from prosecast import config as _config
from prosecast import setup_probe as _setup_probe


class ConfigUpdate(BaseModel):
    values: dict


@app.get("/config")
def get_config():
    """Resolved settings (secrets masked) + which layer each one came from."""
    return _config.public()


@app.put("/config")
def put_config(body: ConfigUpdate):
    """Merge settings into config.json. Drops the cached engine + voice list so
    the next /engine_status reflects the change without a restart."""
    global _active_engine, _chatterbox_voice_cache
    try:
        result = _config.set_many(body.values)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _active_engine = None
    _chatterbox_voice_cache = None
    return result


@app.get("/setup/status")
def setup_status():
    """Probe every service/tool and report {ok, state, detail, fix} per row."""
    return _setup_probe.status()


# ── Render endpoints — single-worker FIFO queue (Phase C2) ────────────────────
#
# One GPU, one worker: all render jobs run strictly sequentially. Enqueue
# returns a job_id immediately; preflight runs at DEQUEUE time per job (a
# voice swapped mid-night aborts that job loudly, not silently), and a failed
# job never kills the jobs behind it.

import queue as _queue_mod

_render_queue: "_queue_mod.Queue[str]" = _queue_mod.Queue()
_queue_order: list = []          # job_ids in enqueue order (for queue_position)
_queue_worker_started = False
_queue_worker_lock = threading.Lock()
_jobs_lock = threading.Lock()    # guards job-dict mutation vs status serialization


def _render_state_path(book_slug: str) -> Path:
    return lib.book_dir(book_slug) / "render_state.json"


def _save_render_state(book_slug: str, job: dict) -> None:
    """Advisory snapshot (disposable, like renders/) so a restarted server can
    show what happened overnight. Real resume comes from cacheKeys."""
    try:
        path = _render_state_path(book_slug)
        state = {"jobs": []}
        if path.exists():
            try:
                state = json.loads(path.read_text())
            except Exception:
                pass
        state["jobs"] = [j for j in state.get("jobs", [])
                         if j.get("job_id") != job["job_id"]][-19:] + [{
            "job_id": job["job_id"],
            "chapters": job["chapters"],
            "status": job["status"],
            "error": job.get("error"),
            "chapter_results": job.get("chapter_results", []),
        }]
        path.write_text(json.dumps(state, indent=2))
    except Exception:
        pass  # advisory only — never let bookkeeping kill a render


def _run_one_render_job(job_id: str) -> None:
    job = _render_jobs[job_id]
    book_slug = job["book_slug"]
    with _jobs_lock:
        job["status"] = "running"
    try:
        from prosecast.preflight import preflight
        from prosecast.renderer import make_engine, render_chapter

        engine_name = _get_active_engine()
        rep = preflight(book_slug, engine_name)
        with _jobs_lock:
            job["preflight"] = {"ok": rep.ok, "aborts": rep.aborts,
                                "warnings": rep.warnings}
            if not rep.ok:
                job["status"] = "aborted"
                job["error"] = rep.summary()
        if not rep.ok:
            print(f"[Queue] job {job_id} PREFLIGHT ABORT:\n{rep.summary()}")
            return

        ir_path = lib.ir_path(book_slug)
        ir = _load_ir(ir_path)
        engine = make_engine(book_slug, engine_name)
        whisper_ok = None          # probed lazily, once, after the first chapter
        for i, ch_idx in enumerate(job["chapters"]):
            with _jobs_lock:
                job["progress"] = i
                job["current_chapter"] = ch_idx
            try:
                def _block_cb(done, total, _job=job):
                    with _jobs_lock:
                        _job["block_progress"] = done
                        _job["block_total"] = total
                r = render_chapter(book_slug, ch_idx, ir, ir_path=str(ir_path),
                                   engine=engine, force=job.get("force", False),
                                   progress_cb=_block_cb)
                with _jobs_lock:
                    job["chapter_results"].append(
                        {k: r[k] for k in ("chapter_index", "skipped", "rendered",
                                           "cached", "failed", "audio_seconds")})
                # Auto-chain alignment (E3): a rendered chapter gets word timings
                # without anyone asking. Enqueued on the PIPELINE worker, never
                # run inline — the render worker must not call whisper and must
                # not wait for it. Probed once per job, not once per chapter.
                if whisper_ok is None:
                    whisper_ok = bool(_probe_row("whisper").get("ok"))
                # Chained whether or not this render synthesized anything: an
                # all-cache render of a chapter that was never aligned still
                # needs timings, and run_align skips the ones already fresh.
                if whisper_ok:
                    _enqueue_pipeline("align", book_slug,
                                      {"chapters": [ch_idx], "force": False},
                                      merge=True)
            except Exception as e:
                # continue-on-chapter-failure: a mid-night hiccup on chapter 3
                # must not kill chapters 4-10
                with _jobs_lock:
                    job["chapter_results"].append(
                        {"chapter_index": ch_idx, "error": str(e)})
                print(f"[Queue] job {job_id} ch{ch_idx} failed: {e} — continuing")
            _save_render_state(book_slug, job)
        with _jobs_lock:
            job["progress"] = len(job["chapters"])
            errors = [c for c in job["chapter_results"] if c.get("error")]
            job["status"] = "done" if not errors else "done_with_errors"
            if errors:
                job["error"] = f"{len(errors)} chapter(s) failed — see chapter_results"
    except Exception as e:
        with _jobs_lock:
            job["status"] = "error"
            job["error"] = str(e)
    finally:
        with _jobs_lock:
            job.pop("current_chapter", None)
        _save_render_state(book_slug, job)


def _queue_worker() -> None:
    while True:
        job_id = _render_queue.get()
        try:
            _run_one_render_job(job_id)
        except Exception as e:
            _render_jobs.get(job_id, {}).update(status="error", error=str(e))
        finally:
            if job_id in _queue_order:
                _queue_order.remove(job_id)
            _render_queue.task_done()


def _ensure_queue_worker() -> None:
    global _queue_worker_started
    with _queue_worker_lock:
        if not _queue_worker_started:
            threading.Thread(target=_queue_worker, daemon=True,
                             name="render-queue-worker").start()
            _queue_worker_started = True


def _enqueue_render(book_slug: str, chapter_indices: list, force: bool) -> str:
    # The overlap guard (E3.3). The render worker holds one IR snapshot for the
    # whole job and writes the whole document back after every block; the AI
    # pass read-modify-writes the same file from the pipeline worker. Whichever
    # finishes second silently wins, and what is lost is attribution labor.
    # Fixing that properly (the worker merging only the fields it owns) is its
    # own item in HANDOFF; until then the two simply refuse to overlap.
    #
    # Alignment is NOT in the guard, in either direction: it writes only
    # renders/chN_blocks/word_timings.json, which nothing else touches — and
    # the auto-chain depends on being able to run while a render continues.
    if _live_job("ai_pass", book_slug) is not None:
        raise HTTPException(
            status_code=409,
            detail="An AI pass is running on this book — render when it finishes.")
    job_id = uuid.uuid4().hex[:10]
    _render_jobs[job_id] = {
        "job_id": job_id, "kind": "render", "book_slug": book_slug,
        "chapters": chapter_indices, "force": force,
        "status": "queued", "progress": 0, "total": len(chapter_indices),
        "error": None, "chapter_results": [],
    }
    _queue_order.append(job_id)
    _render_queue.put(job_id)
    _ensure_queue_worker()
    return job_id


@app.post("/render/{book_slug}/{chapter_index}")
def render_chapter_endpoint(book_slug: str, chapter_index: int,
                            force: bool = Query(default=False)):
    """Enqueue a render of one chapter. Returns a job_id to poll."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    chapter_count = len(_load_ir(ir_path).get("chapters", []))
    if chapter_index >= chapter_count:
        raise HTTPException(status_code=400,
                            detail=f"Chapter {chapter_index} out of range (book has {chapter_count})")
    return {"job_id": _enqueue_render(book_slug, [chapter_index], force)}


@app.post("/render/{book_slug}")
def render_book(book_slug: str, force: bool = Query(default=False)):
    """Enqueue a render of all chapters (done chapters skip unless force)."""
    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    chapter_count = len(_load_ir(ir_path).get("chapters", []))
    if not chapter_count:
        raise HTTPException(status_code=400, detail="Book has no chapters")
    return {"job_id": _enqueue_render(book_slug, list(range(chapter_count)), force)}


@app.get("/render_status/{job_id}")
def get_render_status(job_id: str):
    """Poll a render/export job. Same shape as before + queue_position."""
    if job_id not in _render_jobs:
        raise HTTPException(status_code=404, detail=f"No job '{job_id}'")
    with _jobs_lock:
        job = copy.deepcopy(_render_jobs[job_id])
    order = _queue_order if job_id in _queue_order else _pipeline_order
    job["queue_position"] = (order.index(job_id)
                             if job_id in order and job.get("status") == "queued"
                             else 0)
    return job


@app.get("/render_queue")
def get_render_queue():
    """Everything the queue knows: queued / running / finished render jobs."""
    with _jobs_lock:
        jobs = [copy.deepcopy(j) for j in _render_jobs.values()
                if j.get("kind") == "render"]
    return {"queued": [j["job_id"] for j in jobs if j["status"] == "queued"],
            "jobs": jobs}


# ── Pipeline endpoints — the AI pass and alignment as jobs (E3) ───────────────
#
# A SECOND worker, deliberately not the render queue. The render queue is one
# job at a time because there is one GPU; these jobs are a different resource
# (Ollama coexists with a resident Chatterbox) and a 40-minute attribution pass
# must never sit in front of an overnight render — or behind one.
#
# Jobs live in the same _render_jobs table, so GET /render_status/{id} serves
# them too, carrying kind: 'ai_pass' | 'align' plus stage / detail / done /
# total. The UI reuses one poller for all four job kinds.

_pipeline_queue: "_queue_mod.Queue[str]" = _queue_mod.Queue()
_pipeline_order: list = []
_pipeline_worker_started = False
_pipeline_worker_lock = threading.Lock()

PIPELINE_KINDS = ("ai_pass", "align")


def _live_job(kind: str, book_slug: str) -> dict | None:
    """The queued-or-running job of this kind for this book, if there is one."""
    with _jobs_lock:
        for j in _render_jobs.values():
            if (j.get("kind") == kind and j.get("book_slug") == book_slug
                    and j.get("status") in ("queued", "running")):
                return j
    return None


def _run_one_pipeline_job(job_id: str) -> None:
    from prosecast import pipeline as pipe

    job = _render_jobs[job_id]
    slug = job["book_slug"]
    params = job.get("params", {})
    with _jobs_lock:
        job["status"] = "running"

    def progress(stage: str, detail: str, done: int, total: int) -> None:
        with _jobs_lock:
            job["stage"] = stage
            job["detail"] = detail
            job["progress"] = done
            job["total"] = total

    try:
        if job["kind"] == "ai_pass":
            res = pipe.run_ai_pass(slug, scope=params.get("scope", "unresolved"),
                                   model=None, profile=params.get("profile", True),
                                   job_id=job_id, on_progress=progress)
        else:
            res = pipe.run_align(slug, params.get("chapters"),
                                 force=params.get("force", False),
                                 job_id=job_id, on_progress=progress)
        with _jobs_lock:
            job["result"] = res
            # An aborted pass is DONE, not failed: everything it decided before
            # the breaker fired is saved. The card shows the reason in amber.
            job["status"] = "done"
            if res.get("aborted"):
                job["error"] = res.get("abort_reason")
    except pipe.PipelineError as e:
        with _jobs_lock:
            job.update(status="error", error=str(e))
    except Exception as e:
        with _jobs_lock:
            job.update(status="error", error=f"{job['kind']} failed: {e}")


def _pipeline_worker() -> None:
    while True:
        job_id = _pipeline_queue.get()
        try:
            _run_one_pipeline_job(job_id)
        except Exception as e:
            _render_jobs.get(job_id, {}).update(status="error", error=str(e))
        finally:
            if job_id in _pipeline_order:
                _pipeline_order.remove(job_id)
            _pipeline_queue.task_done()


def _ensure_pipeline_worker() -> None:
    global _pipeline_worker_started
    with _pipeline_worker_lock:
        if not _pipeline_worker_started:
            threading.Thread(target=_pipeline_worker, daemon=True,
                             name="pipeline-worker").start()
            _pipeline_worker_started = True


def _enqueue_pipeline(kind: str, book_slug: str, params: dict,
                      merge: bool = False) -> str:
    """Queue one pipeline job. One at a time, per kind, per book.

    `merge=False` (what the endpoints use): a second request while one is
    queued or running hands back the existing job_id instead of stacking a
    duplicate. `merge=True` (what the render worker's auto-chain uses): fold
    the chapters into a still-queued align job if there is one, and otherwise
    always make a new job — a chapter that finished rendering must not be
    swallowed by an align job that is already past it.
    """
    existing = _live_job(kind, book_slug)
    if existing is not None:
        if kind == "align" and existing["status"] == "queued":
            with _jobs_lock:
                have = existing["params"].get("chapters")
                want = params.get("chapters")
                if have is None or want is None:
                    existing["params"]["chapters"] = None      # None = whole book
                else:
                    existing["params"]["chapters"] = sorted(set(have) | set(want))
                existing["params"]["force"] = (existing["params"].get("force")
                                               or params.get("force", False))
            return existing["job_id"]
        if not merge:
            return existing["job_id"]

    job_id = uuid.uuid4().hex[:10]
    _render_jobs[job_id] = {
        "job_id": job_id, "kind": kind, "book_slug": book_slug, "params": params,
        "status": "queued", "progress": 0, "total": 0,
        "stage": "queued", "detail": "", "error": None, "result": None,
    }
    _pipeline_order.append(job_id)
    _pipeline_queue.put(job_id)
    _ensure_pipeline_worker()
    return job_id


def _probe_row(name: str) -> dict:
    probe = getattr(_setup_probe, f"probe_{name}")
    try:
        return probe()
    except Exception as e:                       # a probe must never 500 the page
        return {"ok": False, "state": "missing", "detail": str(e), "fix": ""}


def _refusal(row: dict) -> str:
    """The probe's own words — 'not responding' plus the sentence that fixes it."""
    return " — ".join(x for x in (row.get("detail"), row.get("fix")) if x)


class AIPassBody(BaseModel):
    scope: str = "unresolved"           # unresolved | low-confidence | all
    profile: bool = True                # also sketch the cast for blind casting


class AlignBody(BaseModel):
    chapters: list | None = None        # None = every chapter that needs it
    force: bool = False


@app.post("/pipeline/{book_slug}/ai_pass")
def start_ai_pass(book_slug: str, body: AIPassBody):
    """Queue the scene-batch attribution pass (+ optional cast profile).

    The button is disabled in the UI when Ollama is down, but the server is the
    one that must not silently do nothing — hence the 409 with the probe's
    fix text rather than a job that quietly resolves zero lines.
    """
    from prosecast import pipeline as pipe

    if not lib.ir_path(book_slug).exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    if body.scope not in pipe.SCOPES:
        raise HTTPException(status_code=400,
                            detail=f"Unknown scope '{body.scope}' — pick one of "
                                   f"{', '.join(pipe.SCOPES)}.")
    render = _live_job("render", book_slug)
    if render is not None:
        raise HTTPException(
            status_code=409,
            detail="A render is running on this book — the AI pass would fight it for "
                   "ir.json. Try again when the render finishes.")
    row = _probe_row("ollama")
    if not row.get("ok"):
        raise HTTPException(status_code=409, detail=_refusal(row))
    return {"job_id": _enqueue_pipeline("ai_pass", book_slug,
                                        {"scope": body.scope, "profile": body.profile})}


@app.post("/pipeline/{book_slug}/align")
def start_align(book_slug: str, body: AlignBody):
    """Queue word alignment. Alignment writes only word_timings.json, so it is
    free to run alongside a render — that is what the auto-chain depends on."""
    if not lib.ir_path(book_slug).exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    row = _probe_row("whisper")
    if not row.get("ok"):
        raise HTTPException(status_code=409, detail=_refusal(row))
    chapters = ([int(c) for c in body.chapters] if body.chapters is not None else None)
    return {"job_id": _enqueue_pipeline("align", book_slug,
                                        {"chapters": chapters, "force": body.force})}


@app.get("/pipeline/{book_slug}")
def get_pipeline(book_slug: str):
    """Everything the Pipeline card draws, in one call."""
    from concurrent.futures import ThreadPoolExecutor

    from prosecast import pipeline as pipe
    from prosecast.scene_attributor import is_target

    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise HTTPException(status_code=404, detail=f"No IR found for '{book_slug}'")
    ir = _load_ir(ir_path)
    blocks = [b for ch in ir.get("chapters", []) for b in ch.get("blocks", [])]

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_ollama = pool.submit(_probe_row, "ollama")
        f_whisper = pool.submit(_probe_row, "whisper")
        ollama, whisper = f_ollama.result(), f_whisper.result()

    state = pipe.read_state(book_slug)
    ai_state = state.get("ai_pass", {})
    align_state = state.get("align", {})
    running = (_live_job("ai_pass", book_slug) or _live_job("align", book_slug))

    per_chapter = pipe.align_overview(book_slug)
    alignable = [c for c in per_chapter if c["state"] in ("stale", "none")]

    return {
        "slug": book_slug,
        "chapters": len(ir.get("chapters", [])),
        "rendered": sum(1 for i in range(len(ir.get("chapters", [])))
                        if lib.chapter_wav_path(book_slug, i).exists()),
        "ai_pass": {
            "unresolved": sum(1 for b in blocks if b.get("unresolved")),
            "in_scope": {scope: sum(1 for b in blocks if is_target(b, scope))
                         for scope in pipe.SCOPES},
            "last_run": ai_state.get("updated"),
            "stage": ai_state.get("stage"),
            "detail": ai_state.get("detail"),
            "result": ai_state.get("result"),
        },
        "align": {
            "per_chapter": per_chapter,
            "needs_alignment": [c["index"] for c in alignable],
            "last_run": align_state.get("updated"),
            "result": align_state.get("result"),
            "auto_chain": bool(whisper.get("ok")),
        },
        "ollama_ok": bool(ollama.get("ok")),
        "ollama_fix": _refusal(ollama) if not ollama.get("ok") else "",
        "whisper_ok": bool(whisper.get("ok")),
        "whisper_fix": _refusal(whisper) if not whisper.get("ok") else "",
        "render_running": _live_job("render", book_slug) is not None,
        "running_job_id": running["job_id"] if running else None,
        "running_kind": running["kind"] if running else None,
    }


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
