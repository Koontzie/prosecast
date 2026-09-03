#!/usr/bin/env python3
"""play_to_ir.py — stage/screen play text -> ProseCast IR (multi-voice, zero LLM).

Acting-edition format (Samuel French style):
    SPEAKER. Dialogue possibly wrapping
        over several lines.
            (Stage directions in parentheses, possibly
            spanning lines.)
Speaker labels are explicit, so attribution is deterministic: every dialogue
block lands with confidence 1.0 / method 'script_format'; stage directions
become NARRATOR narration blocks. Scene headings become chapters.

Input is plain text: pdftotext output for born-digital PDFs, OCR text for
scans (tesseract). Page breaks may be marked with \f or not at all.

Usage:
    python3 play_to_ir.py play.txt "She Kills Monsters" out_ir.json
        [--running-head "SHE KILLS MONSTERS|YOUNG ADVENTURERS"]
        [--keep-inline-parens]
"""
import argparse
import difflib
import json
import re
import sys

SCENE_RE = re.compile(r'^(scene|act)\s+[a-z0-9 -]{1,20}$', re.I)
SPEAKER_RE = re.compile(r"^([A-Z][A-Z'’ .&-]{1,28}?)\.\s+(\S.*)$")
PAGENUM_RE = re.compile(r'^\d{1,3}$')


def clean_line(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r'^[|_\\/;:~\-]{1,3}\s*', '', s)      # binding-edge artifacts
    s = re.sub(r'\s*[|_\\]{1,3}$', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def looks_like_speaker(name: str) -> bool:
    # "AGNES" yes; "WHOA, WHAT IN THE HADES" no (comma); "I" no (too short)
    if ',' in name or len(name) < 2:
        return False
    words = name.split()
    return 1 <= len(words) <= 4 and all(len(w) <= 14 for w in words)


def parse(lines, running_head_re, keep_inline):
    scenes = []          # [{title, events:[(kind, speaker|None, text)]}]
    cur = {"title": "Front Matter", "events": []}
    speaker = None       # active speech owner
    paren_depth = 0
    buf_kind, buf = None, []   # 'direction' | 'speech' | 'narr'

    def flush():
        nonlocal buf_kind, buf
        if buf:
            text = ' '.join(buf).strip()
            if text:
                cur["events"].append((buf_kind, speaker if buf_kind == 'speech' else None, text))
        buf_kind, buf = None, []

    for raw in lines:
        s = clean_line(raw)
        if not s or PAGENUM_RE.match(s):
            continue
        if running_head_re and running_head_re.search(s):
            continue

        if paren_depth == 0 and SCENE_RE.match(s):
            flush()
            if cur["events"] or not scenes:
                scenes.append(cur)
            cur = {"title": s.title(), "events": []}
            speaker = None
            continue

        if paren_depth > 0:
            buf.append(s)
            paren_depth += s.count('(') - s.count(')')
            if paren_depth <= 0:
                paren_depth = 0
                flush()
            continue

        if s.startswith('('):
            flush()
            buf_kind = 'direction'
            buf = [s]
            paren_depth = s.count('(') - s.count(')')
            if paren_depth <= 0:
                paren_depth = 0
                flush()
            continue

        m = SPEAKER_RE.match(s)
        if m and looks_like_speaker(m.group(1)):
            flush()
            speaker = re.sub(r"[ .]+$", '', m.group(1)).strip()
            buf_kind = 'speech'
            buf = [m.group(2)]
            continue

        # plain line: continuation of the current speech, or narration
        if speaker is not None:
            if buf_kind != 'speech':
                flush()
                buf_kind = 'speech'
            buf.append(s)
        else:
            if buf_kind != 'narr':
                flush()
                buf_kind = 'narr'
            buf.append(s)

    flush()
    scenes.append(cur)
    return scenes


def canonicalize_cast(scenes):
    """Merge OCR-mangled speaker variants (GNES -> AGNES) into frequent names."""
    from collections import Counter
    counts = Counter(sp for sc in scenes for k, sp, _ in sc["events"] if k == 'speech')
    canon = {}
    names_by_freq = [n for n, _ in counts.most_common()]
    for name in names_by_freq:
        if name in canon:
            continue
        for big in names_by_freq:
            if big == name or counts[big] <= counts[name] or big not in canon.values() and counts[big] < 3:
                continue
            ratio = difflib.SequenceMatcher(None, name, big).ratio()
            if counts[name] < counts[big] and (ratio >= 0.8 or big.endswith(name) or name.endswith(big)):
                canon[name] = canon.get(big, big)
                break
        canon.setdefault(name, name)
    # Fallback: a speaker seen once or twice that matched nobody is almost
    # always an OCR mangle — fold it into the closest frequent name.
    for name in names_by_freq:
        if canon[name] != name or counts[name] > 2:
            continue
        best, best_r = None, 0.0
        for big in names_by_freq:
            if big == name or counts[big] < 5:
                continue
            r = difflib.SequenceMatcher(None, name, canon[big]).ratio()
            if r > best_r:
                best, best_r = canon[big], r
        if best and best_r >= 0.45:
            canon[name] = best
    merged = {k: v for k, v in canon.items() if k != v}
    return canon, merged


def strip_inline_parens(text: str) -> str:
    return re.sub(r'\s*\((?:[^()]{1,70})\)\s*', ' ', text).strip()


def strip_outer_parens(text: str) -> str:
    t = text.strip()
    if t.startswith('(') and t.endswith(')'):
        t = t[1:-1]
    return t.strip().rstrip('.') + '.'


def build_ir(title, scenes, canon, keep_inline):
    def variants():
        return {"standard": {"url": None, "cached": False},
                "premium": {"url": None, "cached": False}}
    chapters = []
    cast = set()
    for ci, sc in enumerate(s for s in scenes if s["events"]):
        blocks = []
        prev_narr = None
        for kind, sp, text in sc["events"]:
            if kind == 'speech':
                sp = canon.get(sp, sp)
                cast.add(sp)
                if not keep_inline:
                    text = strip_inline_parens(text)
                if not text:
                    continue
                prev_narr = None
                blocks.append({"type": "dialogue", "speaker": sp,
                               "confidence": 1.0, "unresolved": False,
                               "attribution_method": "script_format",
                               "text": text})
            else:  # direction / narr -> narrator, merge consecutive
                text = strip_outer_parens(text)
                if prev_narr is not None and len(prev_narr["text"]) + len(text) < 900:
                    prev_narr["text"] += ' ' + text
                    continue
                prev_narr = {"type": "narration", "speaker": "NARRATOR",
                             "confidence": 1.0, "unresolved": False,
                             "attribution_method": "narration", "text": text}
                blocks.append(prev_narr)
        for i, b in enumerate(blocks):
            b.update({"segmentId": f"ch{ci}_seg_{i:04d}",
                      "context_before": "", "context_after": "",
                      "audioVariants": variants(), "selectedVariant": "standard",
                      "regenerationCount": 0, "freeRegensRemaining": 2,
                      "cacheKey": None})
        chapters.append({"index": ci, "title": sc["title"], "blocks": blocks})
    return {"book_title": title, "chapters": chapters,
            "characters": sorted(cast - {"NARRATOR"}),
            "unresolved_count": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("txt")
    ap.add_argument("title")
    ap.add_argument("out")
    ap.add_argument("--running-head", default="",
                    help="regex; lines matching it are dropped (title headers)")
    ap.add_argument("--keep-inline-parens", action="store_true")
    ap.add_argument("--keep-front-matter", action="store_true",
                    help="keep text before the first scene heading (default: dropped)")
    args = ap.parse_args()

    head_re = re.compile(args.running_head, re.I) if args.running_head else None
    lines = open(args.txt, encoding="utf-8", errors="replace").read().split('\n')
    scenes = parse(lines, head_re, args.keep_inline_parens)
    if not args.keep_front_matter and len(scenes) > 1 and scenes[0]["title"] == "Front Matter":
        scenes = scenes[1:]
    canon, merged = canonicalize_cast(scenes)
    ir = build_ir(args.title, scenes, canon, args.keep_inline_parens)

    n_blocks = sum(len(c["blocks"]) for c in ir["chapters"])
    n_dlg = sum(1 for c in ir["chapters"] for b in c["blocks"] if b["type"] == "dialogue")
    print(f"[Play] {len(ir['chapters'])} scenes, {n_blocks} blocks "
          f"({n_dlg} dialogue), cast of {len(ir['characters'])}: "
          f"{', '.join(ir['characters'])}", file=sys.stderr)
    if merged:
        print(f"[Play] merged OCR variants: {merged}", file=sys.stderr)
    json.dump(ir, open(args.out, 'w'), indent=2, ensure_ascii=False)
    print(f"[Play] wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
