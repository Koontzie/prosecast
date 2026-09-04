"""
PDF → chapters → ProseCast TXT, for any PDF (Phase E2.2).

Replaces the pdftotext + hand-written toc.json + book-specific regex path.
Built on PyMuPDF because it gives three things pdftotext cannot:

  1. the PDF's own bookmarks (``doc.get_toc()``) — the chapter list, for free,
     on most published PDFs;
  2. every text line with its position, so a line that repeats on most pages
     (copyright watermark, running head, "Page 12") is detectable *generically*
     instead of by a regex written for one book;
  3. font sizes, so "much bigger than the body text" works as a chapter-heading
     fallback when there are no bookmarks.

Chapter detection order (most → least trusted), each returning
``{"chapters": [{"page", "title", "skip"}], "source": str, "note": str}``:

    outline   → PDF bookmarks
    toc       → a printed contents page ("Title ........ 12")
    headings  → font-size outliers on distinct pages
    fallback  → one chapter per FALLBACK_PAGES pages, clearly labelled

The result is *a suggestion*: the ingest wizard shows it for review before
anything is extracted. ``extract()`` then takes the (possibly edited) list and
produces the same "Chapter N: Title" TXT that ``book_parser`` already splits.

Text-layer detection: ``scan_report()`` says whether the file is a scan (no
usable text layer) so the caller can route to OCR instead of producing an
empty book.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    import pymupdf  # PyMuPDF ≥ 1.24
except ImportError:  # pragma: no cover - older wheels expose only `fitz`
    import fitz as pymupdf  # type: ignore

FALLBACK_PAGES = 20
SCAN_CHARS_PER_PAGE = 200          # below this average, treat as a scan
REPEAT_MIN_FRACTION = 0.35         # a line on ≥35% of sampled pages is furniture
REPEAT_MIN_PAGES = 4
JUNK_TITLES = re.compile(
    r"^(table of )?contents$|^copyright|^credits?$|^index( of .*)?$|^acknowledg|^about the author"
    r"|^colophon$|^legal|^license|^also by|^title page$|^cover$|^back cover$|^blank$",
    re.I,
)
LEADER_RE = re.compile(r"^(?P<title>.+?)\s*[.·•_ ]{4,}\s*(?P<page>\d{1,4})\s*$")
PAGENUM_RE = re.compile(r"^\s*(page\s+)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.I)
CAPS_LINE = re.compile(r"^[^a-z]{4,60}$")
DICE_RE = re.compile(r"\b\d*d\d+\b")
STAT_BULLET = re.compile(r"^\s*[•▪◦]?\s*[+−–-]\d")


# ── data ─────────────────────────────────────────────────────────────────────

@dataclass
class Chapter:
    page: int                  # 1-based start page
    title: str
    skip: bool = False         # suggested skip (front/back matter)
    end: int | None = None     # 1-based inclusive end page; filled by _fill_ends

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Detection:
    chapters: list[Chapter]
    source: str                # outline | toc | headings | fallback
    note: str = ""
    pages: int = 0
    repeated_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"chapters": [c.to_dict() for c in self.chapters], "source": self.source,
                "note": self.note, "pages": self.pages, "repeated_lines": self.repeated_lines}


# ── helpers ──────────────────────────────────────────────────────────────────

def open_pdf(path):
    return pymupdf.open(str(path))


def _norm(line: str) -> str:
    """Normalise a line for repeat-detection: digits → #, collapse spaces, lower."""
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.strip())).lower()


def _sample_pages(doc, max_pages: int = 60) -> list[int]:
    n = doc.page_count
    if n <= max_pages:
        return list(range(n))
    step = n / max_pages
    return sorted({int(i * step) for i in range(max_pages)})


def scan_report(doc) -> dict:
    """Average extractable characters per page over a sample; is_scan if tiny."""
    idxs = _sample_pages(doc, 30)
    counts = [len(doc[i].get_text("text").strip()) for i in idxs]
    avg = (sum(counts) / len(counts)) if counts else 0.0
    return {"pages": doc.page_count, "avg_chars_per_page": round(avg, 1),
            "is_scan": avg < SCAN_CHARS_PER_PAGE}


def _page_lines(page) -> list[tuple[str, float]]:
    """(text, y-fraction-of-page-height) for every non-empty line on the page."""
    h = page.rect.height or 1.0
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            txt = "".join(s.get("text", "") for s in l.get("spans", [])).strip()
            if txt:
                out.append((txt, l["bbox"][1] / h))
    return out


FURNITURE_ZONE = 0.12        # top/bottom 12% of the page is header/footer territory
FURNITURE_MAX_CHARS = 70     # a repeated line anywhere counts only if it's short


def repeated_lines(doc) -> list[str]:
    """Lines (normalised) that repeat across pages: watermarks, running heads,
    page-number furniture. Two rules, so it works whether the watermark sits in
    the footer or is stamped mid-page, without ever eating body text:
      • in the top/bottom zone on ≥35% of sampled pages, or
      • anywhere on the page, short, on ≥60% of sampled pages."""
    idxs = _sample_pages(doc)
    if len(idxs) < REPEAT_MIN_PAGES:
        return []
    zone: Counter = Counter()
    anywhere: Counter = Counter()
    for i in idxs:
        seen_zone, seen_any = set(), set()
        for txt, yf in _page_lines(doc[i]):
            n = _norm(txt)
            if len(n) < 3:
                continue
            if yf <= FURNITURE_ZONE or yf >= 1 - FURNITURE_ZONE:
                seen_zone.add(n)
            if len(n) <= FURNITURE_MAX_CHARS:
                seen_any.add(n)
        zone.update(seen_zone)
        anywhere.update(seen_any)
    t_zone = max(REPEAT_MIN_PAGES, int(len(idxs) * REPEAT_MIN_FRACTION))
    t_any = max(REPEAT_MIN_PAGES, int(len(idxs) * 0.6))
    hits = {l for l, c in zone.items() if c >= t_zone} | {l for l, c in anywhere.items() if c >= t_any}
    return sorted(hits)


def _fill_ends(chapters: list[Chapter], page_count: int) -> None:
    for i, ch in enumerate(chapters):
        if ch.end is None:
            ch.end = (chapters[i + 1].page - 1) if i + 1 < len(chapters) else page_count


def _dedupe_by_page(items: list[Chapter]) -> list[Chapter]:
    out: list[Chapter] = []
    for c in sorted(items, key=lambda c: c.page):
        if out and out[-1].page == c.page:
            continue                      # first entry on a page wins
        out.append(c)
    return out


# ── chapter detection ────────────────────────────────────────────────────────

def _from_outline(doc) -> Detection | None:
    toc = doc.get_toc(simple=True)        # [[level, title, page], ...]
    if not toc:
        return None
    levels = Counter(lvl for lvl, _, _ in toc)
    # Use level 1; if that yields <3 entries but level 2 gives a real list, use ≤2.
    use_max = 1
    if levels.get(1, 0) < 3 and levels.get(2, 0) >= 3:
        use_max = 2
    items = [Chapter(page=max(1, int(p)), title=str(t).strip() or f"Section {i + 1}",
                     skip=bool(JUNK_TITLES.search(str(t).strip())))
             for i, (lvl, t, p) in enumerate(toc) if lvl <= use_max and p and p > 0]
    items = _dedupe_by_page(items)
    if len(items) < 2:
        return None
    return Detection(items, "outline",
                     f"found {len(items)} bookmarks in the PDF"
                     + (" (using sub-sections — the top level had too few)" if use_max == 2 else ""))


def _from_printed_toc(doc) -> Detection | None:
    """Look for a contents page in the first ~15 pages: many 'Title .... 12' rows."""
    best: list[tuple[str, int]] = []
    best_page = -1
    for i in range(min(15, doc.page_count)):
        rows = []
        for line in doc[i].get_text("text").split("\n"):
            m = LEADER_RE.match(line.strip())
            if m and 1 <= int(m.group("page")) <= doc.page_count:
                rows.append((m.group("title").strip(" .·•_"), int(m.group("page"))))
        if len(rows) > len(best):
            best, best_page = rows, i
    if len(best) < 3:
        return None
    # Printed page numbers rarely equal PDF page indices (front matter offset).
    # Estimate the offset by finding the first entry's title on a nearby page.
    offset = _toc_offset(doc, best, exclude={best_page})
    items = [Chapter(page=min(doc.page_count, max(1, p + offset)), title=t,
                     skip=bool(JUNK_TITLES.search(t))) for t, p in best]
    items = _dedupe_by_page(items)
    if len(items) < 2:
        return None
    note = f"read {len(items)} entries from the printed contents page"
    note += f" (printed page numbers are offset by {offset:+d} from PDF pages)" if offset else ""
    return Detection(items, "toc", note)


def _toc_offset(doc, rows: list[tuple[str, int]], exclude: set[int] = frozenset()) -> int:
    """Search ±25 pages around each printed number (nearest first) for a page
    whose top lines contain the title; the most common delta wins. The
    contents page itself is excluded — it contains every title. 0 if nothing
    matches."""
    deltas: Counter = Counter()
    for title, printed in rows[:8]:
        key = _norm(title)[:30]
        if len(key) < 4:
            continue
        for delta in sorted(range(-25, 26), key=abs):
            idx = printed - 1 + delta
            if idx in exclude or not (0 <= idx < doc.page_count):
                continue
            head_lines = [l for l in doc[idx].get_text("text").split("\n")[:8]
                          if not LEADER_RE.match(l.strip())]
            if key in _norm(" ".join(head_lines)):
                deltas[delta] += 1
                break
    return deltas.most_common(1)[0][0] if deltas else 0


def _from_headings(doc) -> Detection | None:
    """Lines whose font size is far above the body size, one per page at most."""
    idxs = _sample_pages(doc, 80)
    sizes: Counter = Counter()
    for i in idxs:
        for b in doc[i].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    txt = s.get("text", "").strip()
                    if txt:
                        sizes[round(s["size"])] += len(txt)
    if not sizes:
        return None
    body = sizes.most_common(1)[0][0]
    big = body * 1.6
    items: list[Chapter] = []
    for i in range(doc.page_count):
        for b in doc[i].get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                spans = [s for s in l.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                if max(s["size"] for s in spans) >= big:
                    title = " ".join(s["text"].strip() for s in spans)
                    if 3 <= len(title) <= 80 and not PAGENUM_RE.match(title):
                        items.append(Chapter(page=i + 1, title=title,
                                             skip=bool(JUNK_TITLES.search(title))))
                        break
            else:
                continue
            break                                   # one heading per page
    items = _dedupe_by_page(items)
    if not (3 <= len(items) <= 400):
        return None
    return Detection(items, "headings",
                     f"guessed {len(items)} chapters from large headings (body text ≈{body}pt) — check these")


def _fallback(doc) -> Detection:
    n = doc.page_count
    items = [Chapter(page=p, title=f"Pages {p}–{min(n, p + FALLBACK_PAGES - 1)}")
             for p in range(1, n + 1, FALLBACK_PAGES)]
    return Detection(items, "fallback",
                     f"no bookmarks, contents page or headings found — split every {FALLBACK_PAGES} pages; "
                     "rename or merge these before ingesting")


def detect_chapters(doc) -> Detection:
    det = _from_outline(doc) or _from_printed_toc(doc) or _from_headings(doc) or _fallback(doc)
    det.pages = doc.page_count
    det.repeated_lines = repeated_lines(doc)
    _fill_ends(det.chapters, doc.page_count)
    return det


# ── text cleanup (ported from scripts/pdf_to_txt.py, made book-agnostic) ─────

def caps_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    return (sum(c.isupper() for c in letters) / len(letters)) if letters else 0.0


def digit_sym_ratio(s: str) -> float:
    core = [c for c in s if not c.isspace()]
    return (sum(c.isdigit() or c in "+−–%/()x×" for c in core) / len(core)) if core else 0.0


def clean_page(page_text: str, chapter_title: str, repeated: set[str]) -> list[str]:
    lines, out = page_text.split("\n"), []
    title_up = chapter_title.upper()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            out.append("")
            continue
        if _norm(s) in repeated:
            continue                                  # watermark / running head / furniture
        if PAGENUM_RE.match(s):
            continue
        if LEADER_RE.match(s):
            continue                                  # TOC leader rows
        toks = s.split()
        if len(toks) >= 3 and sum(len(t) <= 2 for t in toks) / len(toks) > 0.7:
            continue                                  # divider-art letter salad
        if len(s) <= 2 and s.isupper():
            continue                                  # single stacked divider letters
        if i < 4 and len(s) <= len(chapter_title) + 15 and (
                (title_up and title_up in s.upper()) or re.match(r"^CHAPTER \d", s.upper())):
            continue                                  # running head / repeated chapter title (short lines only)
        out.append(s)
    return out


def reflow(lines: list[str]) -> list[str]:
    """Join hard-wrapped lines into paragraphs; merge consecutive caps headers."""
    paras: list[str] = []
    cur: list[str] = []

    def flush():
        if cur:
            p = " ".join(cur)
            p = re.sub(r"(\w)[­-]\s+(\w)", r"\1\2", p)   # de-hyphenate
            p = re.sub(r"\s+", " ", p).strip()
            for item in re.split(r"\s+[•▪◦]\s+", p):
                item = item.lstrip("•▪◦ ").strip()
                if item:
                    paras.append(item)
            cur.clear()

    prev_caps = False
    for ln in lines:
        if not ln:
            flush(); prev_caps = False
            continue
        is_caps = bool(CAPS_LINE.match(ln)) and caps_ratio(ln) > 0.8 and not DICE_RE.search(ln)
        if is_caps:
            if prev_caps and cur:
                cur.append(ln)                        # multi-line header
            else:
                flush(); cur.append(ln)
            prev_caps = True
        else:
            if prev_caps:
                flush()                               # header done
            prev_caps = False
            cur.append(ln)
    flush()
    out = []
    for p in paras:
        if caps_ratio(p) > 0.8 and len(p) < 70 and not p.endswith((".", "!", "?", ":")):
            out.append(p.title().rstrip(":") + ".")   # don't let TTS shout/spell headers
        else:
            out.append(p)
    return out


def is_tableish(p: str) -> bool:
    if re.match(r"^Table \d+", p):
        return True
    if digit_sym_ratio(p) > 0.22:
        return True                                   # numeric grids
    if STAT_BULLET.match(p):
        return True                                   # "+3 Strength" bonus rows
    words = p.split()
    if len(words) <= 6 and DICE_RE.search(p):
        return True                                   # bare dice cells
    return False


# ── extraction ───────────────────────────────────────────────────────────────

def extract(doc, chapters: list[Chapter] | list[dict], *, keep_tables: bool = False,
            repeated: list[str] | None = None, progress=None) -> dict:
    """Produce ProseCast TXT from a (reviewed) chapter list.

    Returns {"text": str, "chapters": [{title, pages, paragraphs, chars}], "dropped_tables": int}.
    ``progress(done, total, title)`` is called per chapter if given.
    """
    chs = [c if isinstance(c, Chapter) else Chapter(**{k: v for k, v in c.items()
                                                       if k in ("page", "title", "skip", "end")})
           for c in chapters]
    chs = [c for c in chs if not c.skip]
    chs.sort(key=lambda c: c.page)
    _fill_ends(chs, doc.page_count)
    rep = set(repeated if repeated is not None else repeated_lines(doc))

    book_out, report, dropped = [], [], 0
    for num, ch in enumerate(chs, 1):
        lines: list[str] = []
        for pno in range(ch.page - 1, min(ch.end or doc.page_count, doc.page_count)):
            lines.extend(clean_page(doc[pno].get_text("text", sort=True), ch.title, rep))
            lines.append("")
        kept = []
        for p in reflow(lines):
            if len(p) < 5:
                continue                              # divider-page fragments
            if re.search(r"chapt", p[:20], re.I) and len(p) < 80:
                continue                              # garbled chapter art
            if re.match(r"(?i)^chapt\S*\s+\S+", p):   # scrambled divider text w/ blurb
                p = re.sub(r"(?i)^chapt\S*(\s+\S+){0,4}?\.\s*", "", p)
                if len(p) < 5:
                    continue
            if not keep_tables and is_tableish(p):
                dropped += 1
                continue
            if re.match(r"(?i)^\s*(chapter|part)\s+\w+", p) and kept:
                kept[-1] = kept[-1] + " " + p         # body lines must not look like delimiters
                continue
            kept.append(p)
        title = re.sub(r"(?i)^\s*chapter\s+\d+\s*[:.\-–—]?\s*", "", ch.title.replace("\n", " ")).strip() \
            or ch.title.strip() or f"Chapter {num}"
        book_out.append(f"Chapter {num}: {title}\n\n" + "\n\n".join(kept))
        report.append({"title": title, "pages": [ch.page, ch.end], "paragraphs": len(kept),
                       "chars": sum(len(p) for p in kept)})
        if progress:
            progress(num, len(chs), title)
    return {"text": "\n\n\n".join(book_out) + "\n", "chapters": report, "dropped_tables": dropped}


def pdf_to_txt(pdf_path, out_path, *, chapters=None, keep_tables=False, progress=None) -> dict:
    """One-call convenience: detect (unless a chapter list is given), extract, write."""
    doc = open_pdf(pdf_path)
    det = None
    if chapters is None:
        det = detect_chapters(doc)
        chapters = det.chapters
    result = extract(doc, chapters, keep_tables=keep_tables,
                     repeated=det.repeated_lines if det else None, progress=progress)
    Path(out_path).write_text(result["text"], encoding="utf-8")
    result["detection"] = det.to_dict() if det else None
    result["out"] = str(out_path)
    return result
