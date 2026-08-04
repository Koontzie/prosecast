"""
Word Aligner — sample-accurate read-along timings via faster-whisper.

The player's follow-along highlight was rate-ESTIMATED (linear interpolation
within each block), which drifts on pauses and emphasis. This module replaces
estimation with truth: each rendered block wav is transcribed by the whisper
server WITH word timestamps, whisper's words are matched back to the text we
already know (so transcription errors can only cost timing detail, never
corrupt text), and the result is saved as a sidecar JSON next to the blocks.

Purely additive: no timing file → the UI keeps its sentence-estimate mode.
Sequence: Chatterbox render first (produces block wavs) → this pass second.

Server: OpenAI-compatible POST /v1/audio/transcriptions (verified against
Gideon's speaches/faster-whisper instance on :8100).
Config:  PROSECAST_WHISPER_URL    (default http://localhost:8100)
         PROSECAST_WHISPER_MODEL  (default Systran/faster-whisper-small)

Output:  renders/ch{N}_blocks/word_timings.json
         {"total_duration": <sum of block wav secs — staleness fingerprint>,
          "words": [{"b": block_idx, "cs": char_start, "ce": char_end,
                     "t": abs_start_sec, "d": duration_sec}, ...]}
"""

import difflib
import json
import os
import re
import urllib.request
import urllib.error
import uuid
import wave
from pathlib import Path
from typing import Optional

from prosecast import library as lib

WHISPER_BASE = os.environ.get("PROSECAST_WHISPER_URL", "http://localhost:8100").rstrip("/")
WHISPER_MODEL = os.environ.get("PROSECAST_WHISPER_MODEL", "Systran/faster-whisper-small")
TRANSCRIBE_URL = f"{WHISPER_BASE}/v1/audio/transcriptions"

MAX_CONSECUTIVE_ERRORS = 3
STALE_TOLERANCE_SECS = 0.5   # timings whose fingerprint drifts more are stale

TIMINGS_FILENAME = "word_timings.json"


# ── Whisper client (OpenAI-compatible, multipart) ────────────────────────────

def transcribe_wav(wav_path: str, model: str = WHISPER_MODEL,
                   timeout: int = 120) -> Optional[list]:
    """Return [{'word','start','end'}, ...] for one wav, or None on error."""
    boundary = uuid.uuid4().hex
    try:
        audio = Path(wav_path).read_bytes()
    except OSError as e:
        print(f"  [ALIGN] Cannot read {wav_path}: {e}")
        return None

    def part(name, value):
        return (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n").encode()

    body = b"".join([
        part("model", model),
        part("response_format", "verbose_json"),
        part("timestamp_granularities[]", "word"),
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="file"; filename="block.wav"\r\n'
         f"Content-Type: audio/wav\r\n\r\n").encode(),
        audio, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        TRANSCRIBE_URL, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"  [ALIGN] Connection error: {e}")
        return None
    except Exception as e:
        print(f"  [ALIGN] Error: {e}")
        return None
    return extract_words(data)


def extract_words(data: dict) -> list:
    """Pull word timestamps out of a verbose_json response.

    OpenAI-style puts them at top-level 'words'; some servers nest them under
    segments[].words. Either way → [{'word','start','end'}, ...].
    """
    if not isinstance(data, dict):
        return []
    words = data.get("words")
    if not words:
        words = [w for seg in data.get("segments") or []
                 for w in (seg.get("words") or [])]
    out = []
    for w in words or []:
        try:
            out.append({"word": str(w.get("word", "")).strip(),
                        "start": float(w["start"]), "end": float(w["end"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ── Matching whisper words back to OUR text ──────────────────────────────────

_WORD_RE = re.compile(r"\S+")


def tokenize(text: str) -> list:
    """[(token, char_start, char_end), ...] over whitespace-separated tokens."""
    return [(m.group(), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def _norm(token: str) -> str:
    return re.sub(r"[^\w']", "", token.lower())


def align_words(text: str, whisper_words: list) -> list:
    """Assign a (start, duration) to each token of `text`.

    Sequence-match normalized tokens against whisper's words; matched tokens
    take whisper's times verbatim, unmatched runs are interpolated between
    their timed neighbors. Returns [{'cs','ce','t','d'}] with block-relative
    times — the caller offsets to chapter-absolute.
    """
    tokens = tokenize(text)
    if not tokens:
        return []
    if not whisper_words:
        return []

    ours = [_norm(t[0]) for t in tokens]
    theirs = [_norm(w["word"]) for w in whisper_words]
    times: list = [None] * len(tokens)

    sm = difflib.SequenceMatcher(a=ours, b=theirs, autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            w = whisper_words[b + k]
            times[a + k] = (w["start"], max(0.0, w["end"] - w["start"]))

    # Interpolate unmatched runs between timed neighbors
    block_end = max(w["end"] for w in whisper_words)
    n = len(tokens)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        run_start = i
        while i < n and times[i] is None:
            i += 1
        left_t = (times[run_start - 1][0] + times[run_start - 1][1]
                  if run_start > 0 else 0.0)
        right_t = times[i][0] if i < n else block_end
        span = max(0.0, right_t - left_t)
        count = i - run_start
        for k in range(count):
            s = left_t + span * (k / count)
            times[run_start + k] = (s, span / count)

    return [{"cs": cs, "ce": ce, "t": round(t[0], 3), "d": round(t[1], 3)}
            for (tok, cs, ce), t in zip(tokens, times)]


# ── Chapter pass ──────────────────────────────────────────────────────────────

def timings_path(book_slug: str, chapter_index: int) -> Path:
    return lib.chapter_blocks_dir(book_slug, chapter_index) / TIMINGS_FILENAME


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path)) as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def chapter_blocks_fingerprint(book_slug: str, chapter_index: int) -> float:
    """Sum of block wav durations — cheap staleness check for saved timings."""
    blocks_dir = lib.chapter_blocks_dir(book_slug, chapter_index)
    total = 0.0
    if blocks_dir.exists():
        for p in blocks_dir.glob("block_*.wav"):
            total += _wav_duration(p)
    return round(total, 3)


def align_chapter(book_slug: str, chapter_index: int,
                  model: str = WHISPER_MODEL) -> Optional[dict]:
    """Align every rendered block of a chapter; save + return the timings doc.

    Mirrors the /timeline cursor exactly (missing wav → duration 0) so word
    times line up with the player's block starts. Returns None if the chapter
    has no rendered blocks or the whisper server is unreachable.
    """
    ir = json.loads(lib.ir_path(book_slug).read_text(encoding="utf-8"))
    chapters = ir.get("chapters", [])
    if chapter_index >= len(chapters):
        print(f"[ALIGN] Chapter {chapter_index} out of range")
        return None
    blocks = chapters[chapter_index].get("blocks", [])
    blocks_dir = lib.chapter_blocks_dir(book_slug, chapter_index)
    if not blocks_dir.exists():
        print(f"[ALIGN] ch{chapter_index}: no rendered blocks — render first.")
        return None

    words = []
    cursor = 0.0
    consecutive_errors = 0
    transcribed = skipped = 0

    for i, block in enumerate(blocks):
        wav = blocks_dir / f"block_{i:04d}.wav"
        duration = _wav_duration(wav) if wav.exists() else 0.0
        text = block.get("text", "")
        if duration > 0 and text.strip():
            ww = transcribe_wav(str(wav), model=model)
            if ww is None:
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"[ALIGN] {consecutive_errors} connection failures in a row — "
                          "aborting (nothing saved; re-run when the server is back).")
                    return None
                skipped += 1
            else:
                consecutive_errors = 0
                if ww:
                    for entry in align_words(text, ww):
                        entry["b"] = i
                        entry["t"] = round(entry["t"] + cursor, 3)
                        words.append(entry)
                    transcribed += 1
                else:
                    skipped += 1
        cursor += duration

    if transcribed == 0:
        # Nothing aligned (connection errors / empty responses) — saving an
        # empty doc would read as "fresh" and block future retry attempts.
        print(f"[ALIGN] ch{chapter_index}: nothing aligned "
              f"({skipped} skipped) — not saving; re-run when the server is healthy.")
        return None

    doc = {"total_duration": round(cursor, 3), "words": words}
    out = timings_path(book_slug, chapter_index)
    out.write_text(json.dumps(doc), encoding="utf-8")
    print(f"[ALIGN] ch{chapter_index}: {transcribed} blocks aligned, "
          f"{skipped} skipped, {len(words)} words → {out.name}")
    return doc
