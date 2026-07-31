"""
Scene attributor (v2) tests — all offline, Ollama mocked.

Covers: scope selection, the protected-method tiebreaker, scene segmentation,
prompt shape, think-block-tolerant parsing, and the apply/threshold logic.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import scene_attributor as sa  # noqa: E402


def blk(seg, typ="dialogue", text='"hi"', speaker="UNKNOWN", conf=0.0,
        unresolved=True, method="unresolved"):
    return {"segmentId": seg, "type": typ, "text": text, "speaker": speaker,
            "confidence": conf, "unresolved": unresolved,
            "attribution_method": method}


# ── scope / protection ────────────────────────────────────────────────────────

def test_scope_unresolved_targets_only_unresolved():
    unres = blk("a")
    alt = blk("b", speaker="Bob", conf=0.5, unresolved=False, method="alternating")
    assert sa.is_target(unres, "unresolved")
    assert not sa.is_target(alt, "unresolved")


def test_scope_low_confidence_adds_alternating_but_not_spacy():
    alt = blk("a", speaker="Bob", conf=0.5, unresolved=False, method="alternating")
    ner = blk("b", speaker="Ann", conf=0.7, unresolved=False, method="spacy_ner")
    assert sa.is_target(alt, "low-confidence")
    assert not sa.is_target(ner, "low-confidence")


def test_scope_all_targets_everything_unprotected():
    ner = blk("b", speaker="Ann", conf=0.7, unresolved=False, method="spacy_ner")
    assert sa.is_target(ner, "all")


@pytest.mark.parametrize("method,conf", [
    ("manual", 1.0), ("postfix_tag", 0.93), ("prefix_tag", 0.9),
])
def test_protected_methods_never_targeted_even_in_scope_all(method, conf):
    b = blk("a", speaker="Ann", conf=conf, unresolved=False, method=method)
    assert sa.is_protected(b)
    assert not sa.is_target(b, "all")


def test_high_confidence_is_protected_but_unresolved_never_is():
    high = blk("a", speaker="Ann", conf=0.96, unresolved=False, method="context_tag")
    assert sa.is_protected(high)
    weird = blk("b", conf=0.99)   # unresolved=True — junk confidence must not shield it
    assert not sa.is_protected(weird)
    assert sa.is_target(weird, "unresolved")


def test_narration_never_targeted():
    n = blk("a", typ="narration", unresolved=False, method=None)
    assert not sa.is_target(n, "all")


# ── segmentation ──────────────────────────────────────────────────────────────

def test_segment_breaks_on_narration_gap():
    blocks = (
        [blk(f"d{i}") for i in range(3)]
        + [blk(f"n{i}", typ="narration", unresolved=False) for i in range(3)]
        + [blk(f"e{i}") for i in range(2)]
    )
    scenes = sa.segment_scenes(blocks)
    assert len(scenes) == 2
    assert scenes[0] == [0, 1, 2, 3]          # keeps 1st narration blk for context
    assert 6 in scenes[1] and 7 in scenes[1]  # second scene has the later dialogue


def test_segment_caps_scene_size():
    blocks = [blk(f"d{i}") for i in range(120)]
    scenes = sa.segment_scenes(blocks, max_blocks=50)
    assert [len(s) for s in scenes] == [50, 50, 20]
    assert scenes[1][0] == 50                  # consecutive windows, no gaps
    assert sum(len(s) for s in scenes) == 120


# ── prompt ────────────────────────────────────────────────────────────────────

def test_prompt_marks_targets_and_labels_known_speakers():
    blocks = [
        blk("n0", typ="narration", text="She turned.", unresolved=False),
        blk("d1", text='"Who goes there?"', speaker="Anais", conf=0.9,
            unresolved=False, method="context_tag"),
        blk("d2", text='"Just me."'),
    ]
    prompt = sa.build_scene_prompt(blocks, [0, 1, 2], {2: 1},
                                   ["NARRATOR", "Anais"], "Ch 1")
    assert "[narration] She turned." in prompt
    assert '[Anais] "Who goes there?"' in prompt
    assert '[1?] "Just me."' in prompt
    assert "NARRATOR, Anais" in prompt


# ── parsing ───────────────────────────────────────────────────────────────────

def test_parse_plain_json():
    out = sa.parse_scene_response(
        '{"1": {"speaker": "Anais", "confidence": 0.9}}', ["Anais"])
    assert out == {1: ("Anais", 0.9)}


def test_parse_strips_think_blocks_and_fences():
    raw = ("<think>Line 1 follows Bob's line so it must be Anais "
           "speaking...</think>\n```json\n"
           '{"1": {"speaker": "anais", "confidence": 0.8}}\n```')
    out = sa.parse_scene_response(raw, ["Anais"])
    assert out == {1: ("Anais", 0.8)}          # canonicalized case too


def test_parse_bare_string_values_and_unknown():
    out = sa.parse_scene_response(
        '{"1": "Anais", "2": "UNKNOWN", "3": {"speaker": "", "confidence": 1}}',
        ["Anais"])
    assert 1 in out and out[1][0] == "Anais"
    assert 2 not in out and 3 not in out


def test_parse_garbage_returns_empty():
    assert sa.parse_scene_response("I think it is Anais.", ["Anais"]) == {}
    assert sa.parse_scene_response("", ["Anais"]) == {}


# ── end-to-end pass (mocked ollama) ──────────────────────────────────────────

def _two_scene_ir():
    return {
        "title": "T", "characters": ["Anais", "Bob"], "user_characters": [],
        "unresolved_count": 2,
        "chapters": [{
            "title": "Ch 1",
            "blocks": [
                blk("d0", text='"Hello."', speaker="Anais", conf=0.93,
                    unresolved=False, method="postfix_tag"),
                blk("d1", text='"Well met."', speaker="Bob", conf=0.5,
                    unresolved=False, method="alternating"),
                blk("d2", text='"Onward?"'),                       # unresolved
                blk("d3", text='"Aye."'),                          # unresolved
            ],
        }],
    }


def test_run_scene_pass_applies_above_threshold_only(monkeypatch, capsys):
    ir = _two_scene_ir()
    # targets in scope low-confidence: d1 (alternating .5), d2, d3 → lines 1,2,3
    monkeypatch.setattr(sa, "_call_ollama", lambda *a, **k: (
        '{"1": {"speaker": "Bob", "confidence": 0.9},'
        ' "2": {"speaker": "Anais", "confidence": 0.85},'
        ' "3": {"speaker": "Bob", "confidence": 0.3}}'))
    sa.run_scene_pass(ir, model="fake:1b", scope="low-confidence",
                      confidence_threshold=0.6)
    bl = ir["chapters"][0]["blocks"]
    assert bl[0]["attribution_method"] == "postfix_tag"      # protected untouched
    assert bl[1]["speaker"] == "Bob"                          # confirmed
    assert bl[1]["attribution_method"] == "llm_scene_fake"
    assert bl[2]["speaker"] == "Anais" and not bl[2]["unresolved"]
    assert bl[3]["unresolved"]                                # 0.3 < threshold
    assert ir["unresolved_count"] == 1


def test_run_scene_pass_scope_unresolved_leaves_alternating(monkeypatch):
    ir = _two_scene_ir()
    monkeypatch.setattr(sa, "_call_ollama", lambda *a, **k: (
        '{"1": {"speaker": "Anais", "confidence": 0.9},'
        ' "2": {"speaker": "Anais", "confidence": 0.9}}'))
    sa.run_scene_pass(ir, model="fake:1b", scope="unresolved",
                      confidence_threshold=0.6)
    bl = ir["chapters"][0]["blocks"]
    assert bl[1]["attribution_method"] == "alternating"       # not in scope
    assert not bl[2]["unresolved"] and not bl[3]["unresolved"]
    assert ir["unresolved_count"] == 0


def test_run_scene_pass_checkpoints(monkeypatch, tmp_path):
    ir = _two_scene_ir()
    ckpt = tmp_path / "ir.json"
    monkeypatch.setattr(sa, "_call_ollama", lambda *a, **k: (
        '{"1": {"speaker": "Bob", "confidence": 0.9},'
        ' "2": {"speaker": "Anais", "confidence": 0.9},'
        ' "3": {"speaker": "Bob", "confidence": 0.9}}'))
    sa.run_scene_pass(ir, model="fake:1b", scope="low-confidence",
                      confidence_threshold=0.6, checkpoint_path=str(ckpt))
    assert ckpt.exists()
    import json as _json
    saved = _json.loads(ckpt.read_text())
    assert saved["unresolved_count"] == 0


def test_run_scene_pass_connection_error_leaves_ir_untouched(monkeypatch):
    ir = _two_scene_ir()
    monkeypatch.setattr(sa, "_call_ollama", lambda *a, **k: None)
    sa.run_scene_pass(ir, model="fake:1b", scope="low-confidence")
    bl = ir["chapters"][0]["blocks"]
    assert bl[2]["unresolved"] and bl[3]["unresolved"]
    assert bl[1]["attribution_method"] == "alternating"
