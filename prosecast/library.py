"""Per-book library layout — the single source of truth for on-disk paths.

Layout:
    library/<slug>/
        ir.json              — the IR (attribution + tags); precious
        voice_map.json       — character → voice assignments; precious
        corrections.jsonl    — append-only correction journal; precious (training flywheel)
        renders/ch{N}.wav    — merged chapter audio; disposable, reproducible
        renders/ch{N}_blocks/block_{i:04d}.wav — per-block audio; disposable

Anything in renders/ can be deleted and re-rendered. Everything else is
the product of pipeline runs plus Tyler's manual correction labor — back it up.

Replaced the legacy flat layout (output/<slug>_ir.json, <slug>_ch0.wav, ...)
on 2026-06-10; scripts/migrate_to_library.sh moved existing books over.
"""
from pathlib import Path

LIBRARY_DIR = Path(__file__).resolve().parent.parent / "library"


def book_dir(slug: str) -> Path:
    return LIBRARY_DIR / slug


def ir_path(slug: str) -> Path:
    return book_dir(slug) / "ir.json"


def voice_map_path(slug: str) -> Path:
    return book_dir(slug) / "voice_map.json"


def journal_path(slug: str) -> Path:
    return book_dir(slug) / "corrections.jsonl"


def renders_dir(slug: str) -> Path:
    return book_dir(slug) / "renders"


def chapter_wav_path(slug: str, chapter_index: int) -> Path:
    return renders_dir(slug) / f"ch{chapter_index}.wav"


def chapter_blocks_dir(slug: str, chapter_index: int) -> Path:
    return renders_dir(slug) / f"ch{chapter_index}_blocks"


def ensure_book_dir(slug: str) -> Path:
    """Create the book's directory tree (idempotent) and return it."""
    d = book_dir(slug)
    renders_dir(slug).mkdir(parents=True, exist_ok=True)
    return d


def list_book_slugs() -> list[str]:
    """Slugs of all books that have an ir.json, sorted."""
    if not LIBRARY_DIR.exists():
        return []
    return sorted(p.parent.name for p in LIBRARY_DIR.glob("*/ir.json"))
