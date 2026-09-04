"""
Phase E2.2 — PDF ingest on PyMuPDF. Every test builds its own small PDF, so
the suite stays offline and needs no copyrighted fixtures.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pymupdf = pytest.importorskip("pymupdf")
from prosecast import pdf_ingest as pi  # noqa: E402

BODY = ("The rain had not stopped for three days, and the town had begun to smell of wet "
        "stone and old bread. Nobody went out unless they had to. ") * 6
WATERMARK = "Copyright Example Studios — Unauthorized distribution prohibited"


def _book(tmp_path, n_chapters=4, pages_per=3, *, bookmarks=True, toc_page=False,
          big_headings=False, watermark=True, page_numbers=True, scan=False, name="book.pdf"):
    doc = pymupdf.open()
    toc = []
    if toc_page:
        p = doc.new_page()
        p.insert_text((72, 72), "Contents", fontsize=18)
        y = 120
        for c in range(n_chapters):
            printed = c * pages_per + 3           # printed numbers, offset from PDF pages
            p.insert_text((72, y), f"Chapter {c + 1}: Story {c + 1} ........ {printed}", fontsize=11)
            y += 18
        p.insert_text((72, 780), "Copyright page and other front matter", fontsize=9)
    for c in range(n_chapters):
        for k in range(pages_per):
            p = doc.new_page()
            if scan:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
                pix.clear_with(200)
                p.insert_image(pymupdf.Rect(72, 72, 400, 400), pixmap=pix)
                continue
            if k == 0:
                p.insert_text((72, 72), f"Chapter {c + 1}: Story {c + 1}",
                              fontsize=24 if big_headings else 11)
                toc.append([1, f"Chapter {c + 1}: Story {c + 1}", doc.page_count])
            p.insert_textbox(pymupdf.Rect(72, 110, 540, 700), BODY, fontsize=11)
            if watermark:
                p.insert_text((72, 790), WATERMARK, fontsize=8)
            if page_numbers:
                p.insert_text((500, 790), str(doc.page_count), fontsize=8)
    if bookmarks and not scan:
        doc.set_toc([[1, "Contents", 1]] + toc if toc_page else toc)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


# ── detection ────────────────────────────────────────────────────────────────

def test_bookmarks_win(tmp_path):
    doc = pi.open_pdf(_book(tmp_path))
    det = pi.detect_chapters(doc)
    assert det.source == "outline"
    assert [c.page for c in det.chapters] == [1, 4, 7, 10]
    assert det.chapters[0].title == "Chapter 1: Story 1"
    assert det.chapters[-1].end == doc.page_count
    assert det.chapters[0].end == 3


def test_junk_bookmarks_are_marked_skip_not_dropped(tmp_path):
    doc = pi.open_pdf(_book(tmp_path, toc_page=True))
    det = pi.detect_chapters(doc)
    assert det.source == "outline"
    assert det.chapters[0].title == "Contents" and det.chapters[0].skip is True
    assert all(not c.skip for c in det.chapters[1:])


def test_printed_toc_when_no_bookmarks(tmp_path):
    doc = pi.open_pdf(_book(tmp_path, bookmarks=False, toc_page=True))
    det = pi.detect_chapters(doc)
    assert det.source == "toc"
    assert len(det.chapters) == 4
    # printed numbers were 3,6,9,12 but the chapters start on PDF pages 2,5,8,11 → offset −1 found
    assert [c.page for c in det.chapters] == [2, 5, 8, 11]
    assert "offset" in det.note


def test_headings_when_no_bookmarks_or_toc(tmp_path):
    doc = pi.open_pdf(_book(tmp_path, bookmarks=False, big_headings=True))
    det = pi.detect_chapters(doc)
    assert det.source == "headings"
    assert [c.page for c in det.chapters] == [1, 4, 7, 10]
    assert det.chapters[2].title == "Chapter 3: Story 3"


def test_fallback_is_labelled_as_a_guess(tmp_path):
    doc = pi.open_pdf(_book(tmp_path, n_chapters=2, pages_per=25, bookmarks=False))
    det = pi.detect_chapters(doc)
    assert det.source == "fallback"
    assert det.chapters[0].title.startswith("Pages 1")
    assert "rename or merge" in det.note


def test_scan_is_detected(tmp_path):
    doc = pi.open_pdf(_book(tmp_path, scan=True))
    rep = pi.scan_report(doc)
    assert rep["is_scan"] is True and rep["avg_chars_per_page"] < 50
    text_doc = pi.open_pdf(_book(tmp_path, name="text.pdf"))
    assert pi.scan_report(text_doc)["is_scan"] is False


# ── furniture removal + extraction ───────────────────────────────────────────

def test_watermark_and_page_numbers_are_dropped_generically(tmp_path):
    doc = pi.open_pdf(_book(tmp_path))
    rep = pi.repeated_lines(doc)
    assert any("unauthorized distribution" in l for l in rep)
    out = pi.extract(doc, pi.detect_chapters(doc).chapters, repeated=rep)
    assert "Unauthorized" not in out["text"]
    assert "Copyright Example" not in out["text"]
    assert out["text"].count("Chapter ") == 4          # only our delimiters
    assert "wet stone and old bread" in out["text"]


def test_no_watermark_book_is_untouched(tmp_path):
    doc = pi.open_pdf(_book(tmp_path, watermark=False, page_numbers=False))
    # Only the "Chapter N" running-head pattern may register (digits normalise to #);
    # body text never does, even though this synthetic body repeats on every page.
    assert all("chapter" in l for l in pi.repeated_lines(doc))
    out = pi.extract(doc, pi.detect_chapters(doc).chapters)
    assert "wet stone and old bread" in out["text"]
    assert out["chapters"][0]["paragraphs"] >= 1


def test_skip_and_reviewed_edits_are_honoured(tmp_path):
    doc = pi.open_pdf(_book(tmp_path))
    det = pi.detect_chapters(doc)
    edited = [c.to_dict() for c in det.chapters]
    edited[0]["skip"] = True                            # user unticks chapter 1
    edited[1]["title"] = "Renamed by the user"
    out = pi.extract(doc, edited)
    assert out["text"].startswith("Chapter 1: Renamed by the user")
    assert len(out["chapters"]) == 3


def test_txt_output_splits_with_book_parser(tmp_path):
    from prosecast.book_parser import parse_book
    path = _book(tmp_path)
    out = tmp_path / "out.txt"
    res = pi.pdf_to_txt(path, out)
    assert res["detection"]["source"] == "outline"
    chapters = parse_book(str(out))
    assert len(chapters) == 4


def test_tableish_paragraphs_dropped_unless_kept():
    assert pi.is_tableish("+3 Strength, +1 Dexterity")
    assert pi.is_tableish("2d6 fire")
    assert not pi.is_tableish("She rolled the dice across the table and waited.")


def test_junk_title_patterns():
    for t in ("Contents", "Table of Contents", "Index", "Index of Rules", "Copyright 2026", "Credits"):
        assert pi.JUNK_TITLES.search(t), t
    for t in ("Chapter 1: Atlas", "Appendix 1: Iconic Gear", "Introduction: Welcome to the Dungeon"):
        assert not pi.JUNK_TITLES.search(t), t
