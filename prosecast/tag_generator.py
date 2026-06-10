"""
Tag Generator — ProseCast Phase 4

Adds actor-facing emotion/tone tags to attributed IR blocks.
Each dialogue block gets: action verb, emotion descriptor, intensity, pace.
Narration blocks get a simplified subset (no action verb).

Runs after the attribution pipeline. Tags are stored in a new "tags" field
on each block — additive, never touches existing attribution fields.
TTS engines read tags via tag_mapper.py at render time.

Requires Gideon/Ollama at http://GIDEON_HOST:11434
"""

import json
import re
import time
import urllib.request
import urllib.error
from typing import Optional


OLLAMA_API = "http://GIDEON_HOST:11434/api/generate"
OLLAMA_TAGS_URL = "http://GIDEON_HOST:11434/api/tags"
DEFAULT_MODEL = "mistral:7b"
TAG_METHOD = "gideon-mistral"

VALID_PACES = {"slow", "measured", "brisk", "urgent"}


# ── Prompts ───────────────────────────────────────────────────────────────────

DIALOGUE_PROMPT = """\
You are a script supervisor tagging dialogue for a multi-voice audiobook director.
Your job: give each line an ACTOR'S ACTION — the specific INTENTION behind the words, not a label for how the speaker feels.

CRITICAL DISTINCTION:
  WRONG (emotion labels): "excited", "angry", "sad", "happy", "nervous"
  RIGHT (actioning verbs — what the character is DOING with their words):
    "to persuade", "to threaten", "to confess", "to deflect", "to comfort",
    "to seduce", "to dismiss", "to apologize", "to warn", "to manipulate",
    "to reassure", "to interrogate", "to boast", "to plead", "to mock",
    "to share delight", "to assert dominance", "to sow doubt", "to conceal fear",
    "to gain sympathy", "to buy time", "to test the waters", "to wound with kindness"

Think like a director coaching an actor: what is this character TRYING TO DO with these words?

FEW-SHOT EXAMPLES:

Speaker: Darcy | Line: "Miss Elizabeth, I hope I am not disturbing you."
Context before: [narration] Mr. Darcy entered, his expression unreadable.
OUTPUT: {{"action": "to make himself acceptable", "emotion": "guarded formality", "intensity": 0.4, "pace": "measured"}}

Speaker: Bingley | Line: "By Jove, she is the most beautiful creature I have ever beheld!"
Context before: [narration] Bingley had been glancing across the room all evening.
OUTPUT: {{"action": "to share unchecked delight", "emotion": "unguarded admiration", "intensity": 0.85, "pace": "brisk"}}

Speaker: Lady Catherine | Line: "You can be at no loss to understand the reason of my journey hither."
Context before: [narration] Lady Catherine's air was not conciliating.
OUTPUT: {{"action": "to assert dominance", "emotion": "imperious certainty", "intensity": 0.8, "pace": "slow"}}

Speaker: Wickham | Line: "I had not thought Mr. Darcy so bad as this — though I have never liked him."
Context before: [narration] Wickham's expression shifted to one of careful sympathy.
OUTPUT: {{"action": "to sow distrust", "emotion": "calculated sympathy", "intensity": 0.55, "pace": "measured"}}

Speaker: Jane | Line: "I cannot think so ill of anyone. I am sure he cannot have meant it."
Context before: [narration] Jane looked troubled, wanting to believe the best.
OUTPUT: {{"action": "to protect her good opinion of others", "emotion": "earnest hopefulness", "intensity": 0.45, "pace": "measured"}}

Speaker: Carl | Line: "We need to move. Right now."
Context before: [narration] The building shook again. Dust fell from the ceiling.
OUTPUT: {{"action": "to galvanize into action", "emotion": "controlled urgency", "intensity": 0.9, "pace": "urgent"}}

Speaker: Elizabeth | Line: "I am perfectly well, thank you."
Context before: [Mr. Darcy] "You look pale. Are you unwell?" [narration] She looked away.
OUTPUT: {{"action": "to close a door", "emotion": "walled-off composure", "intensity": 0.25, "pace": "measured"}}

Speaker: Anne | Line: "Yes. I suppose you are right."
Context before: [narration] She had argued for twenty minutes. Now she had nothing left.
OUTPUT: {{"action": "to surrender without peace", "emotion": "exhausted resignation", "intensity": 0.15, "pace": "slow"}}

NOW TAG THIS LINE:

Speaker: {speaker}
Line: {text}
Context before: {context_before}
Context after: {context_after}
Known characters: {characters}

Reply with ONLY a single line of valid JSON — no explanation, no markdown, no preamble:
{{"action": "to VERB PHRASE", "emotion": "short descriptive phrase", "intensity": 0.0, "pace": "slow|measured|brisk|urgent"}}

Rules:
- "action" MUST start with "to " followed by an infinitive verb phrase (e.g. "to persuade", "to wound gently")
- "emotion" is 2-5 words describing the underlying feeling FOR HUMAN READERS — not a single-word label
- "intensity" is a float: 0.1=near-whisper, 0.5=normal conversation, 1.0=maximum emotional force
- "pace" is exactly one of: slow, measured, brisk, urgent
"""

NARRATION_PROMPT = """\
You are a script supervisor tagging narration passages for a multi-voice audiobook.
Tag this narration block with the appropriate mood and delivery pace.

NARRATION: {text}
Context before: {context_before}
Context after: {context_after}

Reply with ONLY a single line of valid JSON:
{{"emotion": "short descriptive phrase", "intensity": 0.0, "pace": "slow|measured|brisk|urgent"}}

Rules:
- "emotion" is the narrator's tone for this passage (e.g. "quiet dread", "warm nostalgia", "urgent tension")
- "intensity" is 0.1 to 1.0
- "pace" is one of: slow, measured, brisk, urgent
"""

RETRY_SUFFIX_DIALOGUE = (
    '\nIMPORTANT: Reply with ONLY the JSON object. No other text. '
    'Example: {"action": "to reassure", "emotion": "gentle firmness", "intensity": 0.6, "pace": "measured"}'
)

RETRY_SUFFIX_NARRATION = (
    '\nIMPORTANT: Reply with ONLY the JSON object. No other text. '
    'Example: {"emotion": "quiet tension", "intensity": 0.5, "pace": "measured"}'
)


# ── Ollama client ─────────────────────────────────────────────────────────────

def check_gideon(model: str = DEFAULT_MODEL) -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as resp:
            data = json.loads(resp.read())
        available = [m["name"] for m in data.get("models", [])]
        match = any(
            m == model or m.startswith(model.split(":")[0] + ":")
            for m in available
        )
        if not match:
            print(f"[TAG] Model '{model}' not found on Gideon. Available: {available}")
        return match
    except Exception as e:
        print(f"[TAG] Gideon not reachable at {OLLAMA_TAGS_URL} — {e}")
        return False


def _call_ollama(prompt: str, model: str, timeout: int = 90) -> Optional[str]:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 96,
        },
    }).encode()

    req = urllib.request.Request(
        OLLAMA_API,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except urllib.error.URLError as e:
        print(f"  [TAG] Connection error: {e}")
        return None
    except Exception as e:
        print(f"  [TAG] Error: {e}")
        return None


# ── Response parsing ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    for attempt in [text]:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
    m = re.search(r'\{[^}]+\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _validate_dialogue_tags(data: dict) -> Optional[dict]:
    action = str(data.get("action", "")).strip()
    emotion = str(data.get("emotion", "")).strip()
    try:
        intensity = float(data.get("intensity", 0.5))
    except (TypeError, ValueError):
        intensity = 0.5
    pace = str(data.get("pace", "measured")).strip().lower()

    if not action.lower().startswith("to ") or len(action.split()) < 2:
        return None
    if not emotion:
        return None

    intensity = max(0.0, min(1.0, intensity))
    if pace not in VALID_PACES:
        pace = "measured"

    return {
        "action": action,
        "emotion": emotion,
        "intensity": round(intensity, 2),
        "pace": pace,
    }


def _validate_narration_tags(data: dict) -> Optional[dict]:
    emotion = str(data.get("emotion", "")).strip()
    try:
        intensity = float(data.get("intensity", 0.5))
    except (TypeError, ValueError):
        intensity = 0.5
    pace = str(data.get("pace", "measured")).strip().lower()

    if not emotion:
        return None
    intensity = max(0.0, min(1.0, intensity))
    if pace not in VALID_PACES:
        pace = "measured"

    return {"emotion": emotion, "intensity": round(intensity, 2), "pace": pace}


def _parse_dialogue_tags(response: str) -> Optional[dict]:
    data = _extract_json(response)
    return _validate_dialogue_tags(data) if data else None


def _parse_narration_tags(response: str) -> Optional[dict]:
    data = _extract_json(response)
    return _validate_narration_tags(data) if data else None


# ── Context builder ───────────────────────────────────────────────────────────

def _context_strings(all_blocks: list, block_idx: int, window: int = 3) -> tuple[str, str]:
    start = max(0, block_idx - window)
    end = min(len(all_blocks), block_idx + window + 1)
    before_parts, after_parts = [], []

    for i in range(start, block_idx):
        b = all_blocks[i]
        snippet = b["text"][:100].replace("\n", " ")
        label = "narration" if b["type"] == "narration" else b.get("speaker", "UNKNOWN")
        before_parts.append(f"[{label}] {snippet}")

    for i in range(block_idx + 1, end):
        b = all_blocks[i]
        snippet = b["text"][:100].replace("\n", " ")
        label = "narration" if b["type"] == "narration" else b.get("speaker", "UNKNOWN")
        after_parts.append(f"[{label}] {snippet}")

    before = " | ".join(before_parts) or "(start of chapter)"
    after = " | ".join(after_parts) or "(end of chapter)"
    return before, after


# ── Single block tagger ───────────────────────────────────────────────────────

def tag_block(
    block: dict,
    all_blocks: list,
    block_idx: int,
    characters: list,
    model: str = DEFAULT_MODEL,
) -> Optional[dict]:
    """Tag a single block. Returns tag dict or None on failure."""
    context_before, context_after = _context_strings(all_blocks, block_idx)
    char_list = ", ".join(characters) if characters else "unknown"

    if block["type"] == "dialogue":
        prompt = DIALOGUE_PROMPT.format(
            speaker=block.get("speaker", "UNKNOWN"),
            text=block["text"][:300],
            context_before=context_before[:300],
            context_after=context_after[:300],
            characters=char_list,
        )
        raw = _call_ollama(prompt, model)
        tags = _parse_dialogue_tags(raw) if raw else None

        if tags is None and raw is not None:
            raw2 = _call_ollama(prompt + RETRY_SUFFIX_DIALOGUE, model)
            tags = _parse_dialogue_tags(raw2) if raw2 else None

        parse_fn = _validate_dialogue_tags  # for type annotation
    else:
        prompt = NARRATION_PROMPT.format(
            text=block["text"][:300],
            context_before=context_before[:200],
            context_after=context_after[:200],
        )
        raw = _call_ollama(prompt, model)
        tags = _parse_narration_tags(raw) if raw else None

        if tags is None and raw is not None:
            raw2 = _call_ollama(prompt + RETRY_SUFFIX_NARRATION, model)
            tags = _parse_narration_tags(raw2) if raw2 else None

    if tags:
        tags["tag_method"] = TAG_METHOD

    return tags


# ── Full IR pass ──────────────────────────────────────────────────────────────

def tag_ir(
    ir_data: dict,
    model: str = DEFAULT_MODEL,
    retag: bool = False,
    dialogue_only: bool = False,
    failure_log_path: str = "/tmp/prosecast-tag-failures.json",
    checkpoint_path: str = None,
    checkpoint_every: int = 25,
) -> dict:
    """
    Tag all blocks in an IR. Modifies ir_data in place and returns it.

    retag: if True, re-tag blocks that already have tags.
    dialogue_only: if True, only tag dialogue blocks (skip narration for speed).
    checkpoint_path: if set, save ir_data to this path every checkpoint_every blocks.
                     Lets --use-existing-ir resume a partial run without losing progress.
    """
    characters = ir_data.get("characters", [])

    blocks_to_tag = [
        (ch_idx, blk_idx, block)
        for ch_idx, chapter in enumerate(ir_data["chapters"])
        for blk_idx, block in enumerate(chapter["blocks"])
        if (not dialogue_only or block["type"] == "dialogue")
        and (retag or not block.get("tags"))
    ]

    to_tag = len(blocks_to_tag)

    total_all = sum(len(ch["blocks"]) for ch in ir_data["chapters"])
    dialogue_count = sum(
        1 for ch in ir_data["chapters"]
        for b in ch["blocks"] if b["type"] == "dialogue"
    )
    skipped = total_all - to_tag if not dialogue_only else (dialogue_count - to_tag)

    print(f"[TAG] Model:        {model}")
    print(f"[TAG] Blocks total: {total_all} ({dialogue_count} dialogue)")
    print(f"[TAG] To tag:       {to_tag}  {'(dialogue only)' if dialogue_only else ''}")
    if skipped > 0:
        print(f"[TAG] Skipping:     {skipped} already-tagged blocks (use --retag to override)")
    print()

    tagged = 0
    errors = 0
    failures = []
    latencies = []

    for processed, (ch_idx, blk_idx, block) in enumerate(blocks_to_tag, 1):
        if processed % 25 == 0:
            avg_lat = sum(latencies) / len(latencies) if latencies else 0
            pct = processed / to_tag * 100
            print(
                f"── Tagged {processed}/{to_tag} ({pct:.0f}%)  "
                f"ok={tagged}  errors={errors}  avg={avg_lat:.1f}s/block ──"
            )
            if checkpoint_path and tagged > 0:
                try:
                    import json as _json
                    with open(checkpoint_path, "w", encoding="utf-8") as _f:
                        _json.dump(ir_data, _f, indent=2, ensure_ascii=False)
                    print(f"  [TAG] Checkpoint saved ({tagged} tagged) → {checkpoint_path}")
                except Exception as _e:
                    print(f"  [TAG] Checkpoint save failed: {_e}")

        all_blocks = ir_data["chapters"][ch_idx]["blocks"]
        t_start = time.time()

        try:
            tags = tag_block(block, all_blocks, blk_idx, characters, model=model)
        except Exception as e:
            tags = None
            print(f"  ✗ {block.get('segmentId', f'ch{ch_idx}_blk{blk_idx}')}  [exception: {e}]")

        elapsed = time.time() - t_start
        latencies.append(elapsed)

        if tags:
            block["tags"] = tags
            tagged += 1
            sym = "💬" if block["type"] == "dialogue" else "📖"
            action = tags.get("action", "")
            emotion = tags.get("emotion", "")
            pace = tags.get("pace", "")
            print(
                f"  {sym} {block.get('segmentId', ''):<22}  "
                f"{action!r:<40}  [{pace}]  {emotion!r}  ({elapsed:.1f}s)"
            )
        else:
            errors += 1
            seg_id = block.get("segmentId", f"ch{ch_idx}_blk{blk_idx}")
            failures.append({
                "segmentId": seg_id,
                "type": block["type"],
                "speaker": block.get("speaker", ""),
                "text": block["text"][:120],
                "reason": "parse_failure",
            })
            print(f"  ✗ {block.get('segmentId', '')}  [parse failure]  ({elapsed:.1f}s)")

    if failures:
        try:
            with open(failure_log_path, "w") as f:
                json.dump(failures, f, indent=2)
            print(f"\n[TAG] Failure log → {failure_log_path}")
        except Exception as e:
            print(f"\n[TAG] Could not write failure log: {e}")

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    total_lat = sum(latencies)

    ir_data["_tag_stats"] = {
        "tagged": tagged,
        "skipped_existing": skipped,
        "errors": errors,
        "model": model,
        "avg_latency_s": round(avg_lat, 2),
        "total_latency_s": round(total_lat, 1),
    }

    print()
    print(f"[TAG] Done:      {tagged} tagged, {errors} errors")
    print(f"[TAG] Avg:       {avg_lat:.2f}s/block")
    print(f"[TAG] Total:     {total_lat:.0f}s ({total_lat/60:.1f} min)")

    return ir_data
