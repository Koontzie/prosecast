"""
Pipeline job tests — offline (Ollama and whisper mocked, real tiny wavs).

These cover the promises the Pipeline card in the UI makes to the user:
progress that means something, a circuit-breaker abort that arrives as data
rather than a log line, an alignment pass that knows the difference between
"already fresh" and "there is no per-block audio to align", and — the rule
that predates E3 and was being broken in two places — every write of ir.json
going through the atomic writer.
"""

import builtins
import json
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import cast_profiler as cp  # noqa: E402
from prosecast import library as lib  # noqa: E402
from prosecast import pipeline  # noqa: E402
from prosecast import scene_attributor as sa  # noqa: E402
from prosecast import word_aligner as wa  # noqa: E402


def _blk(i, kind="dialogue", text='"Who said that?"', speaker="UNKNOWN",
         conf=0.0, unresolved=True, method="unresolved"):
    return {"segmentId": f"ch0_seg_{i:04d}", "type": kind, "text": text,
            "speaker": speaker, "confidence": conf, "unresolved": unresolved,
            "attribution_method": method}


def _write_wav(path, seconds=1.0, rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))


@pytest.fixture()
def book(tmp_path, monkeypatch):
    """A two-chapter book with four unresolved dialogue lines."""
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    slug = "pipeline_test"
    chapters = []
    for c in range(2):
        blocks = [
            _blk(0, "narration", "The room went quiet.", "NARRATOR", 1.0, False, "narration"),
            _blk(1, speaker="Ada", conf=0.99, unresolved=False, method="postfix_tag",
                 text='"I did," said Ada.'),
            _blk(2),
            _blk(3, "narration", "Nobody moved.", "NARRATOR", 1.0, False, "narration"),
            _blk(4),
        ]
        chapters.append({"index": c, "title": f"Chapter {c + 1}", "blocks": blocks})
    ir = {"book_title": "The Pipeline", "unresolved_count": 4, "chapters": chapters}
    lib.ensure_book_dir(slug)
    lib.write_json_atomic(lib.ir_path(slug), ir)
    return slug


def _ollama_answers(speaker="Ada", conf=0.9):
    """Every scene call answers with that speaker for every requested line."""
    def fake(prompt, model, num_predict, timeout=180):
        lines = [int(m) for m in _line_numbers(prompt)]
        return json.dumps({str(n): {"speaker": speaker, "confidence": conf} for n in lines})
    return fake


def _line_numbers(prompt):
    import re
    return re.findall(r"^\[(\d+)\?\]", prompt, flags=re.M)


# ── the AI pass ───────────────────────────────────────────────────────────────

def test_ai_pass_resolves_and_reports_progress(book, monkeypatch):
    monkeypatch.setattr(sa, "_call_ollama", _ollama_answers())
    ticks = []
    res = pipeline.run_ai_pass(book, scope="unresolved", model="fake:1b", profile=False,
                               job_id="j1", on_progress=lambda *a: ticks.append(a))

    assert res["targets"] == 4
    assert res["unresolved_before"] == 4
    assert res["unresolved_after"] == 0
    assert res["resolved"] == 4
    assert res["aborted"] is False and res["abort_reason"] is None

    # shape: (stage, detail, done, total) — every stage in order, no strays
    assert all(len(t) == 4 for t in ticks)
    assert all(isinstance(t[0], str) and isinstance(t[1], str)
               and isinstance(t[2], int) and isinstance(t[3], int) for t in ticks)
    stages = [t[0] for t in ticks]
    assert stages[0] == "loading" and stages[-1] == "done"
    assert "attributing" in stages
    assert set(stages) <= set(pipeline.AI_STAGES)
    # the attributing ticks count scenes, and the last one is complete
    scene_ticks = [t for t in ticks if t[0] == "attributing" and t[3]]
    assert scene_ticks and scene_ticks[-1][2] == scene_ticks[-1][3]

    # the speaker actually landed on disk
    ir = json.loads(lib.ir_path(book).read_text())
    assert ir["chapters"][0]["blocks"][2]["speaker"] == "Ada"
    assert ir["unresolved_count"] == 0


def test_ai_pass_profiles_the_cast_when_asked(book, monkeypatch):
    monkeypatch.setattr(sa, "_call_ollama", _ollama_answers())
    monkeypatch.setattr(cp, "MIN_LINES_TO_PROFILE", 1)
    monkeypatch.setattr(cp, "_call_ollama", lambda *a, **k: json.dumps(
        {"gender": "feminine", "age": "adult", "voice_hints": "dry",
         "confidence": 0.9, "evidence": "called 'she'"}))
    ticks = []
    res = pipeline.run_ai_pass(book, scope="unresolved", model="fake:1b", profile=True,
                               job_id="j2", on_progress=lambda *a: ticks.append(a))
    assert res["profiled"] >= 1
    assert "profiling" in [t[0] for t in ticks]
    ir = json.loads(lib.ir_path(book).read_text())
    assert ir["character_profiles"]["Ada"]["gender"] == "feminine"


def test_ai_pass_abort_is_data_not_a_log_line(book, monkeypatch):
    monkeypatch.setattr(sa, "_call_ollama", lambda *a, **k: None)   # Ollama went away
    monkeypatch.setattr(cp, "_call_ollama", lambda *a, **k: None)
    monkeypatch.setattr(sa, "MAX_CONSECUTIVE_ERRORS", 2)            # this book has 2 scenes
    res = pipeline.run_ai_pass(book, scope="unresolved", model="fake:1b", profile=True,
                               job_id="j3")
    assert res["aborted"] is True
    assert "Ollama" in (res["abort_reason"] or "")
    assert res["unresolved_after"] == 4          # nothing was invented
    # the state file remembers it for a UI that reloads after the fact
    state = pipeline.read_state(book)["ai_pass"]
    assert state["result"]["aborted"] is True


def test_ai_pass_with_nothing_in_scope_is_not_an_error(book, monkeypatch):
    monkeypatch.setattr(sa, "_call_ollama", _ollama_answers())
    pipeline.run_ai_pass(book, scope="unresolved", model="fake:1b", profile=False)
    res = pipeline.run_ai_pass(book, scope="unresolved", model="fake:1b", profile=False)
    assert res["targets"] == 0 and res["resolved"] == 0 and res["aborted"] is False


def test_unknown_scope_is_refused_in_words(book):
    with pytest.raises(pipeline.PipelineError, match="scope"):
        pipeline.run_ai_pass(book, scope="everything", model="fake:1b")


def test_missing_book_is_refused_in_words(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    with pytest.raises(pipeline.PipelineError, match="library"):
        pipeline.run_ai_pass("no_such_book", scope="unresolved")
    with pytest.raises(pipeline.PipelineError, match="library"):
        pipeline.run_align("no_such_book")


# ── the RED rule: ir.json is only ever written atomically ────────────────────

def test_ai_pass_never_writes_ir_with_a_plain_open(book, monkeypatch):
    """Both the checkpoint inside run_scene_pass and the final save were plain
    `open(..., 'w')` until E3. A plain write of ir.json is the one way to lose
    Tyler's attribution labor to a crash, so the test forbids it outright."""
    monkeypatch.setattr(sa, "_call_ollama", _ollama_answers())
    ir_path = str(lib.ir_path(book))

    real_open = builtins.open

    def guarded(file, mode="r", *a, **kw):
        if str(file) == ir_path and any(m in mode for m in "wxa"):
            raise AssertionError(f"plain write of ir.json: open({file!r}, {mode!r})")
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", guarded)

    calls = []
    real_atomic = lib.write_json_atomic
    monkeypatch.setattr(lib, "write_json_atomic",
                        lambda p, d: (calls.append(str(p)), real_atomic(p, d))[1])

    pipeline.run_ai_pass(book, scope="unresolved", model="fake:1b", profile=False)
    assert ir_path in calls, "ir.json was never written through write_json_atomic"


# ── alignment ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def rendered(book):
    """Chapter 0 rendered on Chatterbox (per-block wavs); chapter 1 on `say`
    (a merged chapter wav and nothing else)."""
    blocks = lib.chapter_blocks_dir(book, 0)
    for i in range(5):
        _write_wav(blocks / f"block_{i:04d}.wav", 1.0)
    lib.chapter_wav_path(book, 1).parent.mkdir(parents=True, exist_ok=True)
    _write_wav(lib.chapter_wav_path(book, 1), 5.0)
    return book


def _whisper(text_words):
    return lambda p, **k: [{"word": w, "start": i * 0.2, "end": i * 0.2 + 0.15}
                           for i, w in enumerate(text_words)]


def test_align_reports_no_blocks_for_a_say_rendered_chapter(rendered, monkeypatch):
    monkeypatch.setattr(wa, "transcribe_wav", _whisper(["Who", "said", "that?"]))
    res = pipeline.run_align(rendered, force=False, job_id="a1")
    assert res["aligned"] == [0]
    assert res["no_blocks"] == [1]        # `say` leaves nothing to hear per block
    assert res["failed"] == []
    assert pipeline.chapter_align_state(rendered, 1) == "no_blocks"


def test_align_skips_fresh_timings_and_force_overrides(rendered, monkeypatch):
    monkeypatch.setattr(wa, "transcribe_wav", _whisper(["Who", "said", "that?"]))
    pipeline.run_align(rendered)
    assert pipeline.chapter_align_state(rendered, 0) == "fresh"

    again = pipeline.run_align(rendered)
    assert again["skipped_fresh"] == [0] and again["aligned"] == []

    forced = pipeline.run_align(rendered, force=True)
    assert forced["aligned"] == [0] and forced["skipped_fresh"] == []


def test_align_state_goes_stale_when_the_audio_changes(rendered, monkeypatch):
    monkeypatch.setattr(wa, "transcribe_wav", _whisper(["Who", "said", "that?"]))
    pipeline.run_align(rendered)
    _write_wav(lib.chapter_blocks_dir(rendered, 0) / "block_0002.wav", 4.0)   # re-rendered
    assert pipeline.chapter_align_state(rendered, 0) == "stale"


def test_align_progress_shape_and_state_file(rendered, monkeypatch):
    monkeypatch.setattr(wa, "transcribe_wav", _whisper(["Who", "said", "that?"]))
    ticks = []
    pipeline.run_align(rendered, chapters=[0, 1], job_id="a2",
                       on_progress=lambda *a: ticks.append(a))
    assert all(len(t) == 4 for t in ticks)
    assert set(t[0] for t in ticks) <= set(pipeline.ALIGN_STAGES)
    assert ticks[-1][0] == "done"
    state = pipeline.read_state(rendered)["align"]
    assert state["job_id"] == "a2" and state["result"]["aligned"] == [0]


def test_align_failure_is_reported_not_raised(rendered, monkeypatch):
    monkeypatch.setattr(wa, "transcribe_wav", lambda p, **k: None)   # whisper down
    res = pipeline.run_align(rendered, chapters=[0])
    assert res["failed"] == [0] and res["aligned"] == []
    assert pipeline.chapter_align_state(rendered, 0) == "none"       # nothing half-saved


def test_align_overview_covers_every_chapter(rendered, monkeypatch):
    monkeypatch.setattr(wa, "transcribe_wav", _whisper(["Who", "said", "that?"]))
    pipeline.run_align(rendered, chapters=[0])
    assert pipeline.align_overview(rendered) == [
        {"index": 0, "state": "fresh"}, {"index": 1, "state": "no_blocks"}]
