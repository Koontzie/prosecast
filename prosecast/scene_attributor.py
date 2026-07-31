"""
Scene Attributor — ProseCast attribution v2 (2026-07-31)

Batch speaker attribution: instead of one LLM call per unresolved block
(llm_attributor.py, v1), this pass sends a WHOLE SCENE per call and asks for
a JSON map of every line that needs a speaker. The model sees the full
conversation, so turn-taking, address patterns ("you", names) and narration
beats work in its favor — and a book needs ~tens of calls, not hundreds.

Scope (the --llm-scope knob) decides the AI's jurisdiction:
  unresolved      only blocks the rule cascade gave up on (laptop-friendly)
  low-confidence  unresolved + rule guesses below LOW_CONF_CEILING — chiefly
                  the 'alternating' turn-taking coin flips (default)
  all             every non-protected dialogue block (full second opinion)

Tiebreaker rule — rules beat models on the easy cases: blocks attributed by
manual correction or an explicit said-tag (prefix/postfix), or with
confidence >= 0.95, are PROTECTED — never re-judged, never overwritten.

Ollama endpoint config is shared with the other passes:
PROSECAST_OLLAMA_URL (default http://localhost:11434).
"""

import json
import re
import urllib.request
import urllib.error
from typing import Optional

from prosecast.llm_attributor import OLLAMA_BASE

OLLAMA_API = f"{OLLAMA_BASE}/api/generate"

LOW_CONF_CEILING = 0.6            # 'low-confidence' scope: conf below this is reviewed
PROTECTED_METHODS = {"manual", "postfix_tag", "prefix_tag"}
PROTECTED_CONFIDENCE = 0.95
SCENE_GAP = 3                     # >= this many consecutive narration blocks ends a scene
MAX_SCENE_BLOCKS = 50             # hard cap per scene window (small-model context safety)
TARGETS_PER_CALL = 15             # chunk targets so JSON output stays small + parseable
BLOCK_TEXT_LIMIT = 220            # chars of each block shown in the prompt
CAST_LIMIT = 30                   # top speakers offered as candidates

PROMPT_TEMPLATE = """\
You are attributing dialogue speakers in a scene from a novel.

Candidate speakers (use these names exactly; NARRATOR is the narrating voice):
{cast}

SCENE from chapter "{chapter}", in reading order. Lines marked [n?] need a
speaker. Other dialogue lines already show their speaker.

{scene}

For each numbered line, decide who speaks it. Use turn-taking, who is being
addressed, and the narration beats between lines.

Reply with ONLY one line of valid JSON — no explanation, no markdown:
{{"1": {{"speaker": "Name", "confidence": 0.9}}, "2": {{"speaker": "Name", "confidence": 0.7}}}}

Confidence is 0.0-1.0. If a line is truly undeterminable use "UNKNOWN".
"""


# ── Ollama client ─────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, model: str, num_predict: int, timeout: int = 180) -> Optional[str]:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": num_predict,
        },
    }).encode()
    req = urllib.request.Request(
        OLLAMA_API, data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except urllib.error.URLError as e:
        print(f"  [SCENE] Connection error: {e}")
        return None
    except Exception as e:
        print(f"  [SCENE] Error: {e}")
        return None


# ── Selection ─────────────────────────────────────────────────────────────────

def is_protected(block: dict) -> bool:
    """Blocks where the rule/manual attribution outranks any model opinion."""
    if block.get("attribution_method") in PROTECTED_METHODS:
        return True
    return (not block.get("unresolved")) and block.get("confidence", 0) >= PROTECTED_CONFIDENCE


def is_target(block: dict, scope: str) -> bool:
    if block.get("type") != "dialogue":
        return False
    if is_protected(block):
        return False
    if block.get("unresolved"):
        return True
    if scope == "unresolved":
        return False
    if scope == "low-confidence":
        return block.get("confidence", 0.0) < LOW_CONF_CEILING
    if scope == "all":
        return True
    raise ValueError(f"Unknown scope: {scope}")


# ── Scene segmentation ────────────────────────────────────────────────────────

def segment_scenes(blocks: list, max_blocks: int = MAX_SCENE_BLOCKS) -> list:
    """Split a chapter's blocks into scene windows (lists of block indices).

    A run of >= SCENE_GAP consecutive narration blocks ends a scene. Scenes
    longer than max_blocks are split into consecutive windows.
    """
    scenes = []
    current = []
    narration_run = 0
    for i, b in enumerate(blocks):
        if b.get("type") == "narration":
            narration_run += 1
            if narration_run >= SCENE_GAP and current:
                # close the scene: keep ONE trailing narration block as the
                # closing beat, drop the rest of the gap
                drop = narration_run - 2
                kept = current[:-drop] if drop > 0 else list(current)
                if kept:
                    scenes.append(kept)
                current = []
                narration_run = 0
                continue
        else:
            narration_run = 0
        current.append(i)
        if len(current) >= max_blocks:
            scenes.append(current)
            current = []
            narration_run = 0
    if current:
        scenes.append(current)
    return scenes


# ── Prompt construction ───────────────────────────────────────────────────────

def _build_cast(ir_data: dict) -> list:
    """Top confidently-speaking characters book-wide + user-added names."""
    counts = {}
    for ch in ir_data.get("chapters", []):
        for b in ch.get("blocks", []):
            if b.get("type") == "dialogue" and not b.get("unresolved"):
                s = b.get("speaker")
                if s and s != "UNKNOWN":
                    counts[s] = counts.get(s, 0) + 1
    ranked = sorted(counts, key=counts.get, reverse=True)[:CAST_LIMIT]
    for extra in ir_data.get("user_characters", []):
        if extra not in ranked:
            ranked.append(extra)
    if "NARRATOR" not in ranked:
        ranked.insert(0, "NARRATOR")
    return ranked


def build_scene_prompt(blocks: list, scene_idx: list, target_ids: dict,
                       cast: list, chapter_title: str) -> str:
    """target_ids: {block_index: line_number} for the lines the model must decide."""
    lines = []
    for i in scene_idx:
        b = blocks[i]
        text = (b.get("text") or "")[:BLOCK_TEXT_LIMIT].replace("\n", " ")
        if b.get("type") != "dialogue":
            lines.append(f"[narration] {text}")
        elif i in target_ids:
            lines.append(f"[{target_ids[i]}?] {text}")
        else:
            lines.append(f"[{b.get('speaker', 'UNKNOWN')}] {text}")
    return PROMPT_TEMPLATE.format(
        cast=", ".join(cast),
        chapter=chapter_title,
        scene="\n".join(lines),
    )


# ── Response parsing ──────────────────────────────────────────────────────────

def parse_scene_response(raw: str, known_characters: list) -> dict:
    """Return {line_number(int): (speaker, confidence)}.

    Tolerates <think>...</think> blocks (qwen3 etc.), markdown fences, and
    values that are bare name strings instead of {"speaker": ..} objects.
    """
    if not raw:
        return {}
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    text = re.sub(r"```(?:json)?", "", text).strip()

    start = text.find("{")
    if start < 0:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}

    by_lower = {c.lower(): c for c in known_characters}
    out = {}
    for key, val in data.items():
        try:
            num = int(str(key).strip())
        except ValueError:
            continue
        if isinstance(val, dict):
            speaker = str(val.get("speaker", "")).strip()
            try:
                conf = float(val.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
        elif isinstance(val, str):
            speaker, conf = val.strip(), 0.6
        else:
            continue
        if not speaker or speaker.upper() == "UNKNOWN":
            continue
        # Canonicalize against the candidate list; else accept plausible names
        canonical = by_lower.get(speaker.lower())
        if canonical is None:
            if speaker.upper() == "NARRATOR":
                canonical = "NARRATOR"
            elif re.match(r"^[A-Z][a-z]", speaker):
                canonical = speaker
            else:
                continue
        out[num] = (canonical, max(0.0, min(1.0, conf)))
    return out


# ── Main pass ─────────────────────────────────────────────────────────────────

def run_scene_pass(
    ir_data: dict,
    model: str = "llama3.2",
    scope: str = "low-confidence",
    confidence_threshold: float = 0.6,
    checkpoint_path: Optional[str] = None,
) -> dict:
    """Scene-batch attribution over ir_data (modified in place and returned)."""
    cast = _build_cast(ir_data)
    method_label = f"llm_scene_{model.split(':')[0]}"

    total_targets = sum(
        1 for ch in ir_data.get("chapters", [])
        for b in ch.get("blocks", [])
        if is_target(b, scope)
    )
    if total_targets == 0:
        print(f"[SCENE] No blocks in scope '{scope}' — nothing to do.")
        return ir_data

    print(f"[SCENE] Model:   {model}")
    print(f"[SCENE] Scope:   {scope}  ({total_targets} blocks to review)")
    print(f"[SCENE] Accept:  confidence >= {confidence_threshold}")

    changed = confirmed = low_conf = errors = calls = 0

    for ch_idx, chapter in enumerate(ir_data.get("chapters", [])):
        blocks = chapter.get("blocks", [])
        title = chapter.get("title", f"Chapter {ch_idx}")
        chapter_dirty = False

        for scene_idx in segment_scenes(blocks):
            targets = [i for i in scene_idx if is_target(blocks[i], scope)]
            if not targets:
                continue

            for chunk_start in range(0, len(targets), TARGETS_PER_CALL):
                chunk = targets[chunk_start:chunk_start + TARGETS_PER_CALL]
                target_ids = {bi: n + 1 for n, bi in enumerate(chunk)}
                prompt = build_scene_prompt(blocks, scene_idx, target_ids, cast, title)

                calls += 1
                raw = _call_ollama(prompt, model, num_predict=48 * len(chunk) + 96)
                if raw is None:
                    errors += 1
                    continue

                results = parse_scene_response(raw, cast)
                for bi, line_no in target_ids.items():
                    got = results.get(line_no)
                    if not got:
                        low_conf += 1
                        continue
                    speaker, conf = got
                    if conf < confidence_threshold:
                        low_conf += 1
                        continue
                    block = blocks[bi]
                    was = block.get("speaker")
                    if speaker == was and not block.get("unresolved"):
                        confirmed += 1
                    else:
                        changed += 1
                        print(f"  ✓ ch{ch_idx:03d}_blk{bi:04d}  {was or '?':<16} → {speaker:<16} conf={conf:.2f}")
                    block["speaker"] = speaker
                    block["confidence"] = round(conf, 2)
                    block["attribution_method"] = method_label
                    block["unresolved"] = False
                    chapter_dirty = True

            if chapter_dirty and checkpoint_path:
                _recount_unresolved(ir_data)
                with open(checkpoint_path, "w", encoding="utf-8") as f:
                    json.dump(ir_data, f, indent=2, ensure_ascii=False)

    _recount_unresolved(ir_data)
    print(f"\n[SCENE] {calls} calls: {changed} changed, {confirmed} confirmed, "
          f"{low_conf} left low-confidence, {errors} errors")
    print(f"[SCENE] Unresolved remaining: {ir_data.get('unresolved_count')}")
    return ir_data


def _recount_unresolved(ir_data: dict) -> None:
    ir_data["unresolved_count"] = sum(
        1 for ch in ir_data.get("chapters", [])
        for b in ch.get("blocks", [])
        if b.get("unresolved")
    )
