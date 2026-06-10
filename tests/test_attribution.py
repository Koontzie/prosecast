"""Golden-file attribution tests on the built-in sample book (P&P excerpt).

The sample book must always attribute fully — 0 unresolved blocks with the
four known speakers. If any assertion here fails, a regex or heuristic layer
in prosecast/ir_generator.py has regressed.

Run:  .venv/bin/pytest tests/ -v
"""
from dataclasses import asdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

# The sample book only reaches 100% attribution with the spaCy NER layer
# active. Without it the golden numbers are meaningless, so skip outright.
pytest.importorskip("spacy")

from prosecast.book_parser import parse_book, write_sample_book
from prosecast.ir_generator import build_ir, _load_spacy

if _load_spacy() is None:  # spacy installed but en_core_web_sm missing
    pytest.skip("spaCy model en_core_web_sm not available", allow_module_level=True)

EXPECTED_CHARACTERS = {"Bingley", "Darcy", "Elizabeth", "Jane"}


@pytest.fixture(scope="module")
def sample_ir(tmp_path_factory):
    sample = tmp_path_factory.mktemp("sample") / "sample_book.txt"
    write_sample_book(str(sample))
    chapters = parse_book(str(sample))
    return asdict(build_ir("Sample Book", chapters))


def _blocks(ir):
    for ch in ir["chapters"]:
        for block in ch["blocks"]:
            yield block


def test_zero_unresolved(sample_ir):
    assert sample_ir["unresolved_count"] == 0
    unresolved = [b["segmentId"] for b in _blocks(sample_ir) if b["unresolved"]]
    assert unresolved == [], f"Unresolved blocks: {unresolved}"


def test_expected_characters(sample_ir):
    speakers = {
        b["speaker"] for b in _blocks(sample_ir)
        if b["type"] == "dialogue" and b["speaker"] not in ("NARRATOR", "UNKNOWN")
    }
    assert speakers == EXPECTED_CHARACTERS, f"Got speakers: {speakers}"


def test_every_dialogue_block_has_speaker_and_confidence(sample_ir):
    for b in _blocks(sample_ir):
        if b["type"] == "dialogue":
            assert b["speaker"], f"{b['segmentId']} has no speaker"
            assert b["speaker"] != "UNKNOWN", f"{b['segmentId']} is UNKNOWN"
            assert b["confidence"] > 0, f"{b['segmentId']} has zero confidence"


def test_segment_ids_well_formed(sample_ir):
    for b in _blocks(sample_ir):
        assert b["segmentId"].startswith("ch"), b["segmentId"]
        assert "_seg_" in b["segmentId"], b["segmentId"]
