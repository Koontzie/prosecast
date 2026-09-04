"""OCR for scanned PDFs (E2.4).

A scan is a PDF of photographs: `pdf_ingest.scan_report()` spots one by the
near-total absence of extractable text. This module turns those pictures into
the plain text the rest of the pipeline already knows how to read.

Two deliberate choices:

* **PyMuPDF rasterizes, not `pdftoppm`.** E2.2 moved PDF handling onto PyMuPDF
  specifically to stop requiring poppler; rendering a page to PNG is one call
  there, so the OCR path adds no new dependency beyond tesseract itself.
* **tesseract stays an external binary.** It is the one thing a user has to
  install, so `available()` and `install_hint()` exist to say so plainly rather
  than failing with a traceback.

OCR is slow — seconds per page, so a 300-page book is a coffee break. The
caller gets per-page progress, and the text is cached beside the PDF as
`<stem>_ocr.txt`, so re-adding the same file is free.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from prosecast.setup_probe import _install_hint

TESSERACT = "tesseract"
DEFAULT_DPI = 300
DEFAULT_LANG = "eng"
PAGE_TIMEOUT = 180          # seconds per page; a slow machine on a dense page
MIN_CHARS_PER_PAGE = 40     # below this average, OCR read nothing usable


class OCRError(Exception):
    """Something the user can act on: tesseract missing, or a scan too poor to read."""


def available() -> bool:
    return shutil.which(TESSERACT) is not None


def install_hint() -> str:
    return _install_hint("tesseract", apt="tesseract-ocr")


def version() -> str | None:
    if not available():
        return None
    try:
        out = subprocess.run([TESSERACT, "--version"], capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).splitlines()[0].strip() or None
    except Exception:
        return None


def cache_path(pdf_path) -> Path:
    """Where this PDF's OCR text lives — beside the upload, in books/."""
    p = Path(pdf_path)
    return p.with_name(p.stem + "_ocr.txt")


def ocr_page(png_bytes: bytes, *, lang: str = DEFAULT_LANG, timeout: int = PAGE_TIMEOUT) -> str:
    """One page image -> text. Uses a temp file: `tesseract <file> stdout` is the
    form every tesseract build accepts, where stdin support varies."""
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        tmp.write(png_bytes)
        tmp.flush()
        try:
            proc = subprocess.run([TESSERACT, tmp.name, "stdout", "-l", lang],
                                  capture_output=True, timeout=timeout)
        except FileNotFoundError:
            raise OCRError(f"tesseract isn't installed. {install_hint()}")
        except subprocess.TimeoutExpired:
            raise OCRError(f"tesseract gave up on a page after {timeout}s.")
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise OCRError("tesseract failed: " + (tail[-1] if tail else f"exit {proc.returncode}"))
    return proc.stdout.decode("utf-8", "replace")


def ocr_pdf(pdf_path, *, dpi: int = DEFAULT_DPI, lang: str = DEFAULT_LANG,
            progress=None, use_cache: bool = True, out_path=None) -> Path:
    """Read a scanned PDF into a text file and return its path.

    ``progress(done, total)`` is called after each page. The result is cached at
    ``<stem>_ocr.txt`` and reused unless it is older than the PDF.
    """
    pdf_path = Path(pdf_path)
    out = Path(out_path) if out_path else cache_path(pdf_path)

    if use_cache and out.exists() and out.stat().st_size > 0 \
            and out.stat().st_mtime >= pdf_path.stat().st_mtime:
        if progress:
            progress(1, 1)
        return out

    if not available():
        raise OCRError(
            f"'{pdf_path.name}' is a scan and needs OCR, but tesseract isn't installed. "
            f"{install_hint()} — then add the file again.")

    from prosecast import pdf_ingest as pi
    doc = pi.open_pdf(str(pdf_path))
    total = doc.page_count
    pages: list[str] = []
    for i in range(total):
        pix = doc[i].get_pixmap(dpi=dpi)
        text = ocr_page(pix.tobytes("png"), lang=lang)
        # tesseract breaks lines where the image did. Rejoin them into paragraphs
        # with the same reflow the born-digital path uses, or every line break in
        # the scan becomes a TTS block boundary mid-sentence.
        paras = pi.reflow(text.split("\n"))
        pages.append("\n\n".join(paras))
        if progress:
            progress(i + 1, total)

    body = "\n\n".join(p for p in pages if p.strip())
    per_page = len(body) / max(1, total)
    if per_page < MIN_CHARS_PER_PAGE:
        raise OCRError(
            f"OCR read almost nothing from '{pdf_path.name}' — about {per_page:.0f} characters "
            f"a page across {total} pages. The scan may be too low-resolution, upside down, or "
            f"in a language tesseract doesn't have installed (this run used '{lang}').")

    out.write_text(body + "\n", encoding="utf-8")
    return out
