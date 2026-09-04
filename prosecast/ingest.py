"""Upload -> IR, as one callable pipeline (E2.1).

Everything the terminal used to do between "here is a file" and "there is a
book in the library" lives here, so the server can run it as a job and the
wizard (E2.3) can show the user what it found before committing.

Two halves:

    prepare(path)  — cheap, read-only. What format is this, is it a scan,
                     where do its chapters seem to be, and how should it
                     probably be read? Nothing is written.
    run(...)       — the actual ingest, honouring whatever the user reviewed.
                     Calls progress(stage, detail) as it goes and writes
                     library/<slug>/ir.json.

Three modes (the picker in E2.0):

    novel     — many voices; rules + spaCy attribute the dialogue (today's
                EPUB path). The LLM passes stay a separate step (E3).
    narrator  — one voice reads everything, blocks merged to ~900 chars.
                Rulebooks, non-fiction, run sheets.
    play      — SPEAKER. labels; deterministic attribution, stage directions
                read by the narrator.

Provenance goes into ir["ingest"] so a re-ingest, the E3 pipeline and any
future debugging all know how this book got here.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict
from pathlib import Path

from prosecast import library as lib

BOOKS_DIR = Path(__file__).resolve().parent.parent / "books"

SUPPORTED = (".epub", ".txt", ".pdf")
MODES = ("novel", "narrator", "play")
STAGES = ("extracting", "chapters", "attributing", "done")

# A play label ("AGNES. Where are we?") on this share of non-blank lines means
# the file really is a script. Measured 2026-09-04: She Kills Monsters (OCR)
# 41.5%, Moby Dick 0.8%, every other book 0.0%. The floor on raw count keeps a
# three-line fixture from tripping it.
PLAY_MIN_LABELS = 8
PLAY_MIN_SHARE = 0.05


class IngestError(Exception):
    """Something the user can act on: wrong format, a scan, an empty book."""


# ── naming ───────────────────────────────────────────────────────────────────

def title_for(path) -> str:
    """books/A_Nice_Book.epub -> 'A Nice Book' (same derivation as before)."""
    return Path(path).stem.replace("_", " ").title()


def base_slug(title: str) -> str:
    return re.sub(r"[^\w]", "_", title.lower())[:30] or "book"


def slug_for(title: str, taken=None) -> str:
    """A free slug for this title: 'sample', then 'sample_2', 'sample_3'…

    Never returns a slug whose directory already exists — uploading two files
    with the same stem must not overwrite the first book's IR (and its
    corrections journal, which is Tyler's labor).
    """
    base = base_slug(title)
    taken = set(taken) if taken is not None else set(lib.list_book_slugs())

    def free(s: str) -> bool:
        return s not in taken and not lib.book_dir(s).exists()

    if free(base):
        return base
    n = 2
    while not free(f"{base}_{n}"):
        n += 1
    return f"{base}_{n}"


def unique_upload_path(filename: str, books_dir=None) -> Path:
    """Where to save an upload without clobbering an earlier one."""
    d = Path(books_dir) if books_dir else BOOKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-.]", "_", filename or "book")
    p = d / safe
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    n = 2
    while (d / f"{stem}_{n}{suffix}").exists():
        n += 1
    return d / f"{stem}_{n}{suffix}"


# ── mode guessing ────────────────────────────────────────────────────────────

def play_score(text: str) -> dict:
    """How script-shaped is this text? {labels, lines, share, is_play}."""
    from prosecast.play_parser import SPEAKER_RE, clean_line, looks_like_speaker

    lines = [clean_line(l) for l in text.split("\n")]
    nonblank = [l for l in lines if l]
    labels = 0
    for l in nonblank:
        m = SPEAKER_RE.match(l)
        if m and looks_like_speaker(m.group(1)):
            labels += 1
    share = labels / len(nonblank) if nonblank else 0.0
    return {"labels": labels, "lines": len(nonblank), "share": round(share, 4),
            "is_play": labels >= PLAY_MIN_LABELS and share >= PLAY_MIN_SHARE}


def guess_mode(fmt: str, sample_text: str = "") -> tuple[str, str]:
    """(mode, reason). EPUB is a novel; anything else is a rulebook until its
    text says otherwise. The user overrides this in the picker."""
    if sample_text:
        ps = play_score(sample_text)
        if ps["is_play"]:
            return "play", (f"{ps['labels']} SPEAKER. labels in the first pages "
                            f"({ps['share']:.0%} of lines) — looks like a script")
    if fmt == ".epub":
        return "novel", "EPUB — assuming a novel with dialogue to cast"
    return "narrator", ("no script labels found — assuming one narrator reads "
                        "everything (change this if it's a novel)")


# ── text extraction ──────────────────────────────────────────────────────────

def _read_text_sample(path: Path, limit: int = 200_000) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _pdf_sample(doc, pages: int = 12) -> str:
    out = []
    for i in range(min(pages, doc.page_count)):
        out.append(doc[i].get_text("text", sort=True))
    return "\n".join(out)


def _pdf_script_lines(doc, repeated=None) -> list[str]:
    """Cleaned page lines with the chapter machinery (and reflow) bypassed —
    a script's line structure IS its speaker structure."""
    from prosecast import pdf_ingest as pi
    rep = set(repeated if repeated is not None else pi.repeated_lines(doc))
    lines: list[str] = []
    for pno in range(doc.page_count):
        lines.extend(pi.clean_page(doc[pno].get_text("text", sort=True), "", rep))
        lines.append("")
    return lines


# ── prepare ──────────────────────────────────────────────────────────────────

def prepare(path, *, taken=None) -> dict:
    """Inspect an uploaded file. Reads; never writes.

    Returns {path, filename, format, title, slug, guess_mode, guess_reason,
             is_scan, scan, detection}. ``detection`` is the PDF chapter split
             (source/note/chapters, ready for the review screen) or None.
    """
    p = Path(path)
    fmt = p.suffix.lower()
    if fmt not in SUPPORTED:
        raise IngestError(
            f"'{p.name}' is a {fmt or 'file with no extension'} — ProseCast reads "
            f"{', '.join(SUPPORTED)}.")
    if not p.is_file():
        raise IngestError(f"No such file: {p}")

    title = title_for(p)
    info = {
        "path": str(p), "filename": p.name, "format": fmt, "title": title,
        "slug": slug_for(title, taken=taken), "is_scan": False, "scan": None,
        "detection": None,
    }

    if fmt == ".pdf":
        from prosecast import pdf_ingest as pi
        doc = pi.open_pdf(str(p))
        scan = pi.scan_report(doc)
        info["scan"] = scan
        info["is_scan"] = bool(scan["is_scan"])
        if info["is_scan"]:
            info["guess_mode"] = "narrator"
            info["guess_reason"] = (
                f"scanned PDF — {scan['avg_chars_per_page']:.0f} extractable chars/page "
                f"over {scan['pages']} pages; needs OCR before it can be read")
            return info
        det = pi.detect_chapters(doc)
        info["detection"] = det.to_dict()
        mode, why = guess_mode(fmt, _pdf_sample(doc))
    elif fmt == ".txt":
        mode, why = guess_mode(fmt, _read_text_sample(p))
    else:  # .epub — parsing it here just to guess would double the work
        mode, why = guess_mode(fmt)

    info["guess_mode"], info["guess_reason"] = mode, why
    return info


# ── run ──────────────────────────────────────────────────────────────────────

def _noop(stage: str, detail: str = "") -> None:
    pass


def run(path, mode="novel", *, slug=None, title=None, chapters=None,
        keep_tables=False, narrator=None, progress=None) -> dict:
    """Ingest a prepared file into library/<slug>/ir.json.

    ``chapters`` is the reviewed PDF chapter list (list of dicts with
    page/title/skip); None means "use what detection found". ``progress`` is
    called as progress(stage, detail) with the stages in STAGES.
    """
    say = progress or _noop
    p = Path(path)
    fmt = p.suffix.lower()
    if mode not in MODES:
        raise IngestError(f"Unknown mode '{mode}' — pick one of {', '.join(MODES)}.")
    if fmt not in SUPPORTED:
        raise IngestError(f"'{p.name}' is a {fmt or 'file with no extension'} — "
                          f"ProseCast reads {', '.join(SUPPORTED)}.")
    if not p.is_file():
        raise IngestError(f"No such file: {p}")

    title = title or title_for(p)
    slug = slug or slug_for(title)
    detection_source = None
    text_path = p
    script_lines = None

    # ── extracting ──
    say("extracting", f"reading {p.name}")
    if fmt == ".pdf":
        from prosecast import pdf_ingest as pi
        doc = pi.open_pdf(str(p))
        scan = pi.scan_report(doc)
        if scan["is_scan"]:
            raise IngestError(
                f"'{p.name}' is a scan ({scan['avg_chars_per_page']:.0f} extractable "
                f"chars/page over {scan['pages']} pages) — it has no text layer to read. "
                "OCR isn't wired into the app yet; run it through tesseract or "
                "ocrmypdf first, then upload the result.")
        rep = pi.repeated_lines(doc)
        if mode == "play":
            script_lines = _pdf_script_lines(doc, rep)
            detection_source = "script"
            say("extracting", f"{doc.page_count} pages, {len(script_lines)} lines")
        else:
            det = None
            if chapters is None:
                det = pi.detect_chapters(doc)
                chapters, detection_source = det.chapters, det.source
            else:
                detection_source = "reviewed"
            kept = [c for c in chapters
                    if not (c.skip if hasattr(c, "skip") else c.get("skip"))]
            say("extracting", f"{doc.page_count} pages, {len(kept)} chapters "
                              f"({detection_source})")
            result = pi.extract(doc, chapters, keep_tables=keep_tables, repeated=rep,
                                progress=lambda done, total, t: say(
                                    "extracting", f"chapter {done}/{total}: {t[:48]}"))
            text_path = p.with_name(p.stem + "_extracted.txt")
            text_path.write_text(result["text"], encoding="utf-8")
            if not result["text"].strip():
                raise IngestError(
                    f"Nothing readable came out of '{p.name}' — every page was empty "
                    "or filtered. Check the chapter split, or try --keep-tables.")

    # ── chapters ──
    say("chapters", "splitting into chapters")
    if mode == "play":
        if script_lines is None:
            if fmt == ".epub":
                from prosecast.book_parser import parse_book
                script_lines = "\n".join(c["text"] for c in parse_book(str(p))).split("\n")
            else:
                script_lines = _read_text_sample(text_path, limit=50_000_000).split("\n")
        say("chapters", f"{len(script_lines)} script lines")
    else:
        from prosecast.book_parser import parse_book
        parsed = parse_book(str(text_path))
        if not parsed:
            raise IngestError(
                f"No chapters found in '{p.name}'. For an EPUB that usually means an "
                "unusual spine; for a PDF, the chapter split needs a look.")
        say("chapters", f"{len(parsed)} chapters, "
                        f"{sum(len(c['text']) for c in parsed):,} characters")

    # ── attributing ──
    say("attributing", {"novel": "finding who speaks each line",
                        "narrator": "flattening to a single narrator",
                        "play": "reading speaker labels"}[mode])
    stats = {}
    if mode == "play":
        from prosecast import play_parser
        res = play_parser.play_to_ir(script_lines, title)
        ir = res["ir"]
        stats = {"scenes": res["scenes"], "dialogue": res["dialogue"],
                 "merged_variants": res["merged"]}
        say("attributing", f"{res['scenes']} scenes, cast of {len(res['cast'])}")
    else:
        from prosecast.ir_generator import build_ir
        ir = asdict(build_ir(title, parsed, narrator))
        if mode == "narrator":
            from prosecast import narrator_flatten
            stats = narrator_flatten.flatten_ir(ir)
            say("attributing", f"merged {stats['blocks_before']} -> "
                               f"{stats['blocks_after']} narration blocks")
        else:
            say("attributing", f"{len(ir.get('characters', []))} characters, "
                               f"{ir.get('unresolved_count', 0)} unresolved")

    # ── done ──
    ir["ingest"] = {
        "mode": mode, "source": p.name, "format": fmt,
        "chapter_source": detection_source, "keep_tables": bool(keep_tables),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    lib.ensure_book_dir(slug)
    lib.write_json_atomic(lib.ir_path(slug), ir)

    out = {
        "slug": slug, "title": title, "mode": mode,
        "chapters": len(ir.get("chapters", [])),
        "blocks": sum(len(c.get("blocks", [])) for c in ir.get("chapters", [])),
        "characters": len(ir.get("characters", [])),
        "unresolved": ir.get("unresolved_count", 0),
        "stats": stats,
    }
    say("done", f"{out['chapters']} chapters, {out['blocks']} blocks")
    return out
