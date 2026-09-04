"""
Phase E2.4 — OCR for scanned PDFs.

Real tesseract when it is installed (these tests build their own scans, so
there is nothing copyrighted to check in); skipped cleanly when it is not, the
same way the spaCy-gated attribution tests behave.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import ocr  # noqa: E402
from prosecast import pdf_ingest as pi  # noqa: E402
from synthetic import build_scanned_pdf  # noqa: E402

pytest.importorskip("pymupdf")
needs_tesseract = pytest.mark.skipif(not ocr.available(), reason="tesseract not installed")


# ── the probe ────────────────────────────────────────────────────────────────

def test_availability_comes_with_a_way_to_fix_it():
    hint = ocr.install_hint()
    assert isinstance(ocr.available(), bool)
    assert "install" in hint.lower()
    assert any(os_name in hint for os_name in ("macOS", "Linux", "Windows"))


def test_the_cache_sits_beside_the_pdf():
    assert ocr.cache_path("/books/Some Scan.pdf").name == "Some Scan_ocr.txt"


# ── reading a scan ───────────────────────────────────────────────────────────

@needs_tesseract
def test_a_scan_is_read_back_into_text(tmp_path):
    pdf = build_scanned_pdf(tmp_path / "scan.pdf")
    assert pi.scan_report(pi.open_pdf(str(pdf)))["is_scan"] is True, "fixture must be a real scan"

    seen = []
    out = ocr.ocr_pdf(pdf, progress=lambda done, total: seen.append((done, total)))
    text = out.read_text()

    assert "Locked Room" in text
    assert "wet stone" in text
    assert "second page" in text
    assert seen == [(1, 2), (2, 2)], "progress should count real pages"


@needs_tesseract
def test_paragraphs_are_rejoined_not_left_at_the_image_line_breaks(tmp_path):
    """tesseract breaks lines where the picture did. If those survive, every
    line becomes its own TTS block and the narration stutters mid-sentence."""
    out = ocr.ocr_pdf(build_scanned_pdf(tmp_path / "scan.pdf"))
    body = out.read_text()
    sentence = [ln for ln in body.split("\n") if "wet stone" in ln][0]
    assert "The rain had not stopped" in sentence and "smelled of wet stone" in sentence


@needs_tesseract
def test_the_text_is_cached_and_the_second_run_is_free(tmp_path, monkeypatch):
    pdf = build_scanned_pdf(tmp_path / "scan.pdf")
    first = ocr.ocr_pdf(pdf)

    def explode(*a, **k):
        raise AssertionError("tesseract was run again instead of using the cache")
    monkeypatch.setattr(ocr, "ocr_page", explode)

    again = ocr.ocr_pdf(pdf)
    assert again == first and again.read_text()


@needs_tesseract
def test_a_scan_with_nothing_on_it_says_so(tmp_path):
    pdf = build_scanned_pdf(tmp_path / "blank.pdf", blank=True)
    with pytest.raises(ocr.OCRError) as e:
        ocr.ocr_pdf(pdf)
    msg = str(e.value)
    assert "almost nothing" in msg
    assert "resolution" in msg or "language" in msg, "say what to try next"


def test_a_missing_tesseract_is_explained_not_crashed(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    pdf = build_scanned_pdf(tmp_path / "scan.pdf")
    with pytest.raises(ocr.OCRError) as e:
        ocr.ocr_pdf(pdf, use_cache=False)
    assert "tesseract isn't installed" in str(e.value)
    assert "install" in str(e.value).lower()
