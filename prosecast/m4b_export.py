"""Chapterized M4B export — turns rendered chapter WAVs into a real audiobook file.

Takes library/<slug>/renders/ch{N}.wav (in IR chapter order) plus chapter
titles from ir.json, and produces library/<slug>/exports/<slug>.m4b with
embedded chapter markers. The result opens in any audiobook player
(Apple Books, BookPlayer, Prologue, etc.).

Requires ffmpeg on PATH (macOS: `brew install ffmpeg`).

Chapters without a rendered WAV are skipped (reported in the result) —
export what exists, don't block on a fully rendered book.
"""
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from prosecast import library as lib

DEFAULT_BITRATE = "64k"  # plenty for spoken word; ~28MB per hour


class M4BExportError(RuntimeError):
    pass


def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise M4BExportError(
            "ffmpeg not found on PATH — install it first (macOS: brew install ffmpeg)"
        )
    return path


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path)) as wf:
        return round(wf.getnframes() * 1000 / wf.getframerate())


def _ffmeta_escape(value: str) -> str:
    """Escape FFMETADATA special characters in a metadata value."""
    for ch in ("\\", "=", ";", "#"):
        value = value.replace(ch, "\\" + ch)
    return value.replace("\n", " ")


def export_m4b(
    book_slug: str,
    bitrate: str = DEFAULT_BITRATE,
    author: str = "",
) -> dict:
    """Build the m4b. Returns {path, exported_chapters, skipped_chapters, duration_ms}."""
    _require_ffmpeg()

    ir_path = lib.ir_path(book_slug)
    if not ir_path.exists():
        raise M4BExportError(f"No IR found for '{book_slug}'")
    with open(ir_path, encoding="utf-8") as f:
        ir = json.load(f)

    chapters = ir.get("chapters", [])
    available = []   # (index, title, wav_path, duration_ms)
    skipped = []
    for i, ch in enumerate(chapters):
        wav = lib.chapter_wav_path(book_slug, i)
        title = ch.get("title") or f"Chapter {i + 1}"
        if wav.exists():
            try:
                available.append((i, title, wav, _wav_duration_ms(wav)))
            except wave.Error as e:
                skipped.append({"index": i, "title": title, "reason": f"bad WAV: {e}"})
        else:
            skipped.append({"index": i, "title": title, "reason": "not rendered"})

    if not available:
        raise M4BExportError(
            f"No rendered chapters found for '{book_slug}' — render audio first"
        )

    out_path = lib.m4b_path(book_slug)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    book_title = ir.get("book_title", book_slug)

    with tempfile.TemporaryDirectory(prefix="prosecast_m4b_") as tmp:
        tmp = Path(tmp)

        # Concat list — single-quoted paths, quotes escaped per ffmpeg concat rules
        concat_file = tmp / "concat.txt"
        concat_file.write_text(
            "".join(
                "file '{}'\n".format(str(wav).replace("'", "'\\''"))
                for _, _, wav, _ in available
            ),
            encoding="utf-8",
        )

        # FFMETADATA with chapter markers
        lines = [
            ";FFMETADATA1",
            f"title={_ffmeta_escape(book_title)}",
            f"artist={_ffmeta_escape(author or 'Unknown')}",
            "album=" + _ffmeta_escape(book_title),
            "genre=Audiobook",
            "comment=Rendered with ProseCast",
        ]
        cursor = 0
        for _, title, _, dur in available:
            lines += [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={cursor}",
                f"END={cursor + dur}",
                f"title={_ffmeta_escape(title)}",
            ]
            cursor += dur
        meta_file = tmp / "metadata.txt"
        meta_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(meta_file),
            "-map_metadata", "1",
            "-c:a", "aac", "-b:a", bitrate, "-ac", "1",
            "-movflags", "+faststart",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise M4BExportError(f"ffmpeg failed: {result.stderr.strip()[-500:]}")

    return {
        "path": str(out_path),
        "book_title": book_title,
        "exported_chapters": len(available),
        "skipped_chapters": skipped,
        "duration_ms": cursor,
        "size_bytes": out_path.stat().st_size,
    }
