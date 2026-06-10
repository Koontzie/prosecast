"""
IR Generator — ProseCast Phase 1 (upgraded)

Attribution pipeline (layered, each fills gaps from the previous):

  Layer 0: Segmentation   — split text into narration/dialogue blocks
  Layer 1: Explicit tags  — "said Elizabeth", "Elizabeth said"
                            with pronoun filtering (skip He/She/His/Her/etc.)
  Layer 2: spaCy NER      — extract PERSON entities from surrounding context
                            (optional — degrades gracefully if spaCy not installed)
  Layer 3: Alias collapse — "Mr. Bennet" / "Bennet" / "Mr Bennet" → same character
  Layer 4: Alternating    — in a known 2-person exchange, flip from last speaker
  Layer 5: Unresolved     — flag for user correction / Phase 2 LLM pass
"""

import re
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Block:
    id: str
    type: str                   # "narration" | "dialogue"
    text: str
    speaker: Optional[str]
    confidence: float
    unresolved: bool = False
    attribution_method: str = ""
    context_before: str = ""
    context_after: str = ""


@dataclass
class Chapter:
    index: int
    title: str
    blocks: list = field(default_factory=list)


@dataclass
class IR:
    book_title: str
    chapters: list = field(default_factory=list)
    characters: list = field(default_factory=list)
    unresolved_count: int = 0


# ── Constants ─────────────────────────────────────────────────────────────────

SAID_VERBS = {
    "said", "says", "asked", "asks", "replied", "replies", "answered",
    "cried", "called", "whispered", "shouted", "muttered", "murmured",
    "added", "continued", "began", "exclaimed", "demanded", "pleaded",
    "insisted", "agreed", "laughed", "sighed", "snapped", "growled",
    "urged", "warned", "admitted", "noted", "observed", "remarked",
    "declared", "announced", "responded", "interrupted", "returned",
    "repeated", "conceded", "suggested", "ventured", "offered",
}

PRONOUNS = {
    "he", "she", "his", "her", "they", "it", "we", "i",
    "him", "them", "hers", "theirs", "its", "mine", "ours",
    "mr", "mrs", "ms", "dr", "lord", "lady",
}

def _norm(text):
    return (text
        .replace('\u201c', '"').replace('\u201d', '"')
        .replace('\u2018', "'").replace('\u2019', "'")
        .replace('\u2014', ' -- ').replace('\u2013', ' - '))


# ── Layer 0: Segmentation ────────────────────────────────────────────────────

QUOTE_RE = re.compile(r'"([^"]{1,800})"')

def segment(text):
    text = _norm(text)
    segs = []
    pos = 0
    for m in QUOTE_RE.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            segs.append({"type": "narration", "text": before})
        segs.append({"type": "dialogue", "text": m.group(0), "inner": m.group(1)})
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        segs.append({"type": "narration", "text": tail})
    return segs


# ── Layer 1: Explicit tag attribution ────────────────────────────────────────

VERB_PAT = '|'.join(re.escape(v) for v in SAID_VERBS)

POSTFIX_RE = re.compile(
    r'^[\s,\.]*(' + VERB_PAT + r')\s+((?:Mr\.|Mrs\.|Ms\.|Dr\.|Lord\s|Lady\s)?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)',
    re.IGNORECASE
)
PREFIX_RE = re.compile(
    r'((?:Mr\.|Mrs\.|Ms\.|Dr\.|Lord\s|Lady\s)?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(' + VERB_PAT + r')\s*[,:]?\s*$',
    re.IGNORECASE
)

def _is_pronoun(name):
    return name.lower().strip().rstrip('.') in PRONOUNS

def _clean_name(name):
    return re.sub(r'\s+', ' ', name).strip().title()

def tag_explicit(segs):
    for i, seg in enumerate(segs):
        if seg["type"] != "dialogue":
            continue

        # Postfix: narration after quote starts with "said X"
        if i + 1 < len(segs) and segs[i+1]["type"] == "narration":
            m = POSTFIX_RE.match(segs[i+1]["text"])
            if m:
                candidate = _clean_name(m.group(2))
                if not _is_pronoun(candidate):
                    seg["speaker"] = candidate
                    seg["confidence"] = 0.93
                    seg["method"] = "postfix_tag"
                    continue

        # Prefix: narration before quote ends with "X said"
        if i > 0 and segs[i-1]["type"] == "narration":
            m = PREFIX_RE.search(segs[i-1]["text"])
            if m:
                candidate = _clean_name(m.group(1))
                if not _is_pronoun(candidate):
                    seg["speaker"] = candidate
                    seg["confidence"] = 0.90
                    seg["method"] = "prefix_tag"
                    continue

        # Wider context scan (±1 narration block combined)
        surrounding = ""
        if i > 0 and segs[i-1]["type"] == "narration":
            surrounding += segs[i-1]["text"][-200:]
        if i + 1 < len(segs) and segs[i+1]["type"] == "narration":
            surrounding += " " + segs[i+1]["text"][:200]

        for pat in [POSTFIX_RE, PREFIX_RE]:
            m = pat.search(surrounding)
            if m:
                grp = m.group(2) if pat is POSTFIX_RE else m.group(1)
                candidate = _clean_name(grp)
                if not _is_pronoun(candidate):
                    seg["speaker"] = candidate
                    seg["confidence"] = 0.82
                    seg["method"] = "context_tag"
                    break

    return segs


# ── Layer 2: spaCy NER ───────────────────────────────────────────────────────

def _load_spacy():
    try:
        import spacy
        for model in ["en_core_web_md", "en_core_web_sm", "en_core_web_lg"]:
            try:
                nlp = spacy.load(model)
                print(f"[IR] spaCy loaded: {model}")
                return nlp
            except OSError:
                continue
        print("[IR] spaCy models not found. Run: python -m spacy download en_core_web_sm")
        return None
    except ImportError:
        print("[IR] spaCy not installed. Run: pip install spacy")
        return None


# ── Layer 3: Alias collapse ──────────────────────────────────────────────────

def build_alias_map(names):
    sorted_names = sorted(names, key=len, reverse=True)
    alias_map = {}
    for canonical in sorted_names:
        if canonical in alias_map:
            continue
        alias_map[canonical] = canonical
        canonical_words = set(canonical.lower().split())
        for other in sorted_names:
            if other == canonical or other in alias_map:
                continue
            other_words = set(other.lower().split())
            if other_words and other_words.issubset(canonical_words):
                alias_map[other] = canonical
    return alias_map

def apply_aliases(segs, alias_map):
    for seg in segs:
        spk = seg.get("speaker")
        if spk and spk in alias_map:
            seg["speaker"] = alias_map[spk]
    return segs


# ── Layer 4: Alternating heuristic ──────────────────────────────────────────

def tag_alternating(segs, known_names):
    for i, seg in enumerate(segs):
        if seg["type"] != "dialogue" or "speaker" in seg:
            continue
        prev_attrs = [
            s for s in segs[:i]
            if s.get("type") == "dialogue"
            and s.get("speaker")
            and s.get("confidence", 0) >= 0.82
        ]
        if not prev_attrs:
            continue
        last_speaker = prev_attrs[-1]["speaker"]
        recent_others = list(dict.fromkeys(
            s["speaker"] for s in prev_attrs[-6:]
            if s["speaker"] != last_speaker
        ))
        if recent_others:
            seg["speaker"] = recent_others[-1]
            seg["confidence"] = 0.50
            seg["method"] = "alternating"
    return segs


# ── Layer 5: Mark unresolved ─────────────────────────────────────────────────

def mark_unresolved(segs):
    for seg in segs:
        if seg["type"] == "narration":
            seg.setdefault("speaker", "NARRATOR")
            seg.setdefault("confidence", 1.0)
            seg.setdefault("method", "narration")
            seg["unresolved"] = False
        else:
            if "speaker" not in seg or seg.get("confidence", 0) < 0.45:
                seg["speaker"] = "UNKNOWN"
                seg["confidence"] = 0.0
                seg["method"] = "unresolved"
                seg["unresolved"] = True
            else:
                seg["unresolved"] = False
    return segs


# ── Fast regex name scan ──────────────────────────────────────────────────────

def extract_names_regex(full_text):
    names = set()
    pattern = re.compile(
        r'(?:' + VERB_PAT + r')\s+((?:Mr\.|Mrs\.|Ms\.|Dr\.|Lord\s|Lady\s)?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)'
        r'|((?:Mr\.|Mrs\.|Ms\.|Dr\.|Lord\s|Lady\s)?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:' + VERB_PAT + r')',
        re.IGNORECASE
    )
    for m in pattern.finditer(full_text):
        raw = m.group(1) or m.group(2)
        if raw:
            candidate = _clean_name(raw)
            if not _is_pronoun(candidate) and len(candidate) > 2:
                names.add(candidate)
    return names


# ── Public API ────────────────────────────────────────────────────────────────

def build_ir(book_title, chapters_raw):
    ir = IR(book_title=book_title)
    full_text = _norm(" ".join(c["text"] for c in chapters_raw))

    regex_names = extract_names_regex(full_text)

    # Load spaCy once
    nlp = _load_spacy()
    spacy_names = set()
    if nlp:
        chunk_size = 50000
        for i in range(0, len(full_text), chunk_size):
            doc = nlp(full_text[i:i+chunk_size])
            for ent in doc.ents:
                if ent.label_ == "PERSON":
                    name = _clean_name(ent.text)
                    if len(name) > 2 and not _is_pronoun(name):
                        spacy_names.add(name)
        print(f"[IR] spaCy PERSON entities: {sorted(spacy_names)}")

    all_names = regex_names | spacy_names
    alias_map = build_alias_map(all_names)
    canonical_names = set(alias_map.values())
    ir.characters = sorted(canonical_names)
    print(f"[IR] Final character list: {ir.characters}")

    unresolved_total = 0

    for i, ch in enumerate(chapters_raw):
        chapter = Chapter(index=i, title=ch["title"])
        ch_text = _norm(ch["text"])

        segs = segment(ch_text)
        segs = tag_explicit(segs)

        # spaCy per-segment for unresolved dialogue
        if nlp:
            for j, seg in enumerate(segs):
                if seg["type"] != "dialogue" or "speaker" in seg:
                    continue
                window = " ".join(
                    s["text"] for s in segs[max(0,j-2):j+3]
                    if s["type"] == "narration"
                )
                if not window.strip():
                    continue
                doc = nlp(window[:2000])
                local_persons = [
                    _clean_name(ent.text) for ent in doc.ents
                    if ent.label_ == "PERSON"
                    and not _is_pronoun(ent.text)
                    and len(ent.text) > 2
                ]
                if local_persons:
                    candidate = alias_map.get(local_persons[-1], local_persons[-1])
                    seg["speaker"] = candidate
                    seg["confidence"] = 0.70
                    seg["method"] = "spacy_ner"

        segs = apply_aliases(segs, alias_map)
        segs = tag_alternating(segs, canonical_names)
        segs = mark_unresolved(segs)

        for j, seg in enumerate(segs):
            ctx_before = " ".join(s["text"] for s in segs[max(0,j-2):j])[-200:]
            ctx_after  = " ".join(s["text"] for s in segs[j+1:j+3])[:200]

            if seg["unresolved"]:
                unresolved_total += 1

            block = Block(
                id=f"ch{i:03d}_blk{j:04d}",
                type=seg["type"],
                text=seg["text"],
                speaker=seg["speaker"],
                confidence=seg["confidence"],
                unresolved=seg["unresolved"],
                attribution_method=seg.get("method", ""),
                context_before=ctx_before,
                context_after=ctx_after,
            )
            chapter.blocks.append(asdict(block))

        ir.chapters.append(asdict(chapter))

    ir.unresolved_count = unresolved_total
    return ir


def save_ir(ir, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(ir), f, indent=2, ensure_ascii=False)
    print(f"[IR] Saved -> {path}")


def load_ir(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
