"""
Pipeline jobs — the AI attribution pass and word alignment, as callable jobs.

Both of these were terminal-only until E3:

    main.py "<title>" --use-existing-ir --llm-scene --profile-cast
    scripts/align_words.py <slug>

This module wraps the same functions the CLI calls, adds a progress callback
and an advisory state file, and returns a *result dict* instead of a printed
summary — the circuit breaker in `scene_attributor` must reach the UI as data
("Ollama stopped answering"), not as a log line nobody reads.

No HTTP here: `server.py` owns the queue, the worker and the probe checks.
Nothing in this module knows it is being called from a web request, which is
also what makes it testable offline.

State: `library/<slug>/pipeline_state.json`, advisory and disposable in the
same way `render_state.json` is — it exists so a restarted server can still
say what happened, never so a job can resume from it. Keyed by job kind
(`ai_pass` / `align`) so a later alignment does not erase the record of the
attribution pass that preceded it.

Every write of `ir.json` goes through `lib.write_json_atomic`.
"""

import json
import time
from pathlib import Path
from typing import Callable, Optional

from prosecast import config as _config
from prosecast import library as lib

# on_progress(stage, detail, done, total)
Progress = Callable[[str, str, int, int], None]

AI_STAGES = ("loading", "attributing", "profiling", "saving", "done")
ALIGN_STAGES = ("aligning", "done")

SCOPES = ("unresolved", "low-confidence", "all")


class PipelineError(Exception):
    """Something the user needs to read, not a stack trace."""


# ── advisory state ────────────────────────────────────────────────────────────

def state_path(slug: str) -> Path:
    return lib.book_dir(slug) / "pipeline_state.json"


def read_state(slug: str) -> dict:
    try:
        return json.loads(state_path(slug).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(slug: str, kind: str, entry: dict) -> None:
    """Merge one job's snapshot into the book's pipeline state. Advisory —
    never let bookkeeping kill a job."""
    try:
        doc = read_state(slug)
        doc[kind] = entry
        lib.write_json_atomic(state_path(slug), doc)
    except Exception:
        pass


def _stage_writer(slug: str, kind: str, job_id: str, on_progress: Optional[Progress]):
    """Returns a progress function that both calls `on_progress` and keeps
    pipeline_state.json current. One place, so the two can never disagree."""
    entry = {"job_id": job_id, "kind": kind, "stage": "queued", "detail": "",
             "done": 0, "total": 0,
             "started": time.time(), "updated": time.time()}
    write_state(slug, kind, entry)

    def progress(stage: str, detail: str = "", done: int = 0, total: int = 0) -> None:
        changed = (stage != entry["stage"])
        entry.update(stage=stage, detail=detail, done=done, total=total,
                     updated=time.time())
        if on_progress:
            on_progress(stage, detail, done, total)
        # Per-item ticks are frequent; only a stage change earns a disk write.
        if changed:
            write_state(slug, kind, dict(entry))

    def finish(result: dict) -> None:
        entry.update(stage="done", updated=time.time(), result=result)
        write_state(slug, kind, dict(entry))

    return progress, finish


# ── the AI attribution pass ───────────────────────────────────────────────────

def _unresolved_count(ir: dict) -> int:
    return sum(1 for ch in ir.get("chapters", [])
               for b in ch.get("blocks", []) if b.get("unresolved"))


def run_ai_pass(slug: str, *, scope: str = "unresolved", model: Optional[str] = None,
                profile: bool = True, job_id: str = "",
                on_progress: Optional[Progress] = None) -> dict:
    """Scene-batch attribution (+ optional cast profiling) over one book.

    Returns `{targets, resolved, unresolved_before, unresolved_after, changed,
    confirmed, profiled, aborted, abort_reason}`. An abort is a *result*, not
    an exception: the breaker fires when Ollama goes away mid-pass, and
    everything decided before that is already checkpointed.
    """
    from prosecast.scene_attributor import is_target, run_scene_pass

    if scope not in SCOPES:
        raise PipelineError(f"Unknown scope '{scope}' — pick one of {', '.join(SCOPES)}.")
    ir_path = lib.ir_path(slug)
    if not ir_path.exists():
        raise PipelineError(f"No book '{slug}' in the library.")
    model = model or _config.get("ollama_model") or "gemma3:12b"

    progress, finish = _stage_writer(slug, "ai_pass", job_id, on_progress)
    progress("loading", f"reading {slug}")
    ir = json.loads(ir_path.read_text(encoding="utf-8"))

    targets = sum(1 for ch in ir.get("chapters", [])
                  for b in ch.get("blocks", []) if is_target(b, scope))
    unresolved_before = _unresolved_count(ir)

    report: dict = {}
    progress("attributing", f"{targets} lines in scope · {model}", 0, 0)
    run_scene_pass(
        ir, model=model, scope=scope, checkpoint_path=str(ir_path), report=report,
        on_progress=lambda done, total: progress(
            "attributing", f"scene {done} of {total}" if total else "nothing in scope",
            done, total),
    )

    profiled = 0
    if profile and not report.get("aborted"):
        from prosecast.cast_profiler import run_profile_pass
        prof_report: dict = {}
        progress("profiling", "sketching the cast", 0, 0)
        run_profile_pass(
            ir, model=model, checkpoint_path=str(ir_path), report=prof_report,
            on_progress=lambda done, total: progress(
                "profiling", f"character {done} of {total}" if total else "cast already profiled",
                done, total),
        )
        profiled = prof_report.get("profiled", 0)
        if prof_report.get("aborted"):
            report["aborted"] = True
            report["abort_reason"] = prof_report.get("abort_reason")

    # The passes mutate `ir` in place and checkpoint as they go; this is the
    # same object, written once more so a pass that changed nothing on its last
    # chapter still lands on disk.
    progress("saving", "writing ir.json")
    lib.write_json_atomic(ir_path, ir)

    unresolved_after = _unresolved_count(ir)
    result = {
        "targets": targets,
        "resolved": max(0, unresolved_before - unresolved_after),
        "unresolved_before": unresolved_before,
        "unresolved_after": unresolved_after,
        "changed": report.get("changed", 0),
        "confirmed": report.get("confirmed", 0),
        "profiled": profiled,
        "scope": scope,
        "model": model,
        "aborted": bool(report.get("aborted")),
        "abort_reason": report.get("abort_reason"),
    }
    progress("done", _ai_summary(result), 1, 1)
    finish(result)
    return result


def _ai_summary(r: dict) -> str:
    if r["aborted"]:
        return f"stopped early — {r['resolved']} of {r['targets']} resolved first"
    if not r["targets"]:
        return "nothing was in scope"
    return (f"{r['resolved']} resolved, {r['unresolved_after']} still unresolved"
            + (f", {r['profiled']} characters profiled" if r["profiled"] else ""))


# ── word alignment ────────────────────────────────────────────────────────────

def chapter_align_state(slug: str, chapter_index: int) -> str:
    """One of `no_blocks` / `none` / `stale` / `fresh`.

    `no_blocks` is the honest answer for a chapter rendered on an engine that
    writes no per-block wavs (`say`) — there is nothing for whisper to hear, so
    the UI must not offer an Align button rather than offering one that fails.
    """
    from prosecast.word_aligner import (STALE_TOLERANCE_SECS,
                                        chapter_blocks_fingerprint, timings_path)
    blocks_dir = lib.chapter_blocks_dir(slug, chapter_index)
    if not blocks_dir.exists() or not any(blocks_dir.glob("block_*.wav")):
        return "no_blocks"
    tp = timings_path(slug, chapter_index)
    if not tp.exists():
        return "none"
    try:
        saved = json.loads(tp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "stale"
    drift = abs(saved.get("total_duration", -1)
                - chapter_blocks_fingerprint(slug, chapter_index))
    return "fresh" if drift <= STALE_TOLERANCE_SECS else "stale"


def align_overview(slug: str) -> list:
    """Per-chapter alignment state for the whole book — what the card renders."""
    ir_path = lib.ir_path(slug)
    if not ir_path.exists():
        return []
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    return [{"index": i, "state": chapter_align_state(slug, i)}
            for i in range(len(ir.get("chapters", [])))]


def run_align(slug: str, chapters: Optional[list] = None, *, force: bool = False,
              job_id: str = "", on_progress: Optional[Progress] = None) -> dict:
    """Word-align rendered chapters. Returns
    `{aligned, skipped_fresh, no_blocks, failed}` — four lists of chapter
    indices, so the caller can say what it did rather than how many times."""
    from prosecast.word_aligner import align_chapter

    ir_path = lib.ir_path(slug)
    if not ir_path.exists():
        raise PipelineError(f"No book '{slug}' in the library.")
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    n_chapters = len(ir.get("chapters", []))
    targets = ([c for c in chapters if 0 <= c < n_chapters] if chapters is not None
               else list(range(n_chapters)))

    progress, finish = _stage_writer(slug, "align", job_id, on_progress)
    aligned, skipped_fresh, no_blocks, failed = [], [], [], []
    total = len(targets)
    progress("aligning", f"{total} chapter(s) to check", 0, total)

    for n, ch in enumerate(targets):
        state = chapter_align_state(slug, ch)
        if state == "no_blocks":
            no_blocks.append(ch)
            progress("aligning", f"chapter {ch + 1}: no per-block audio", n + 1, total)
            continue
        if state == "fresh" and not force:
            skipped_fresh.append(ch)
            progress("aligning", f"chapter {ch + 1}: timings already fresh", n + 1, total)
            continue
        progress("aligning", f"chapter {ch + 1} of {n_chapters}", n, total)
        try:
            doc = align_chapter(slug, ch)
        except Exception as e:                       # a bad wav must not kill the rest
            print(f"[PIPELINE] align ch{ch} failed: {e}")
            doc = None
        (aligned if doc else failed).append(ch)
        progress("aligning",
                 f"chapter {ch + 1}: {'aligned' if doc else 'whisper had nothing to say'}",
                 n + 1, total)

    result = {"aligned": aligned, "skipped_fresh": skipped_fresh,
              "no_blocks": no_blocks, "failed": failed}
    progress("done", _align_summary(result), total, total)
    finish(result)
    return result


def _align_summary(r: dict) -> str:
    bits = [f"{len(r['aligned'])} aligned"]
    if r["skipped_fresh"]:
        bits.append(f"{len(r['skipped_fresh'])} already fresh")
    if r["no_blocks"]:
        bits.append(f"{len(r['no_blocks'])} with no per-block audio")
    if r["failed"]:
        bits.append(f"{len(r['failed'])} failed")
    return ", ".join(bits)
