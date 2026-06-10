"""
LLM Attributor — ProseCast Phase 2

Sends unresolved dialogue blocks to a local Ollama LLM for speaker attribution.
Runs after the rule-based IR pass and resolves what the heuristics couldn't.

Requires Ollama running locally:  https://ollama.com
Recommended model:                llama3.2
"""

import json
import re
import urllib.request
import urllib.error
from typing import Optional


OLLAMA_API = "http://localhost:11434/api/generate"
OLLAMA_TAGS = "http://localhost:11434/api/tags"

PROMPT_TEMPLATE = """\
You are an expert at identifying dialogue speakers in novels and audiobooks.

Known characters in this book: {characters}

Here is the context around an unresolved line (speakers are labelled where known):
{context}

The UNRESOLVED line of dialogue is:
  {dialogue}

Who is most likely speaking that line? Choose from the known characters list.
Reply with ONLY a single line of valid JSON — no explanation, no markdown:
{{"speaker": "CHARACTER_NAME", "confidence": 0.0}}

Use confidence 0.0–1.0. If you truly cannot determine the speaker, reply:
{{"speaker": "UNKNOWN", "confidence": 0.0}}
"""


# ── Ollama connectivity ───────────────────────────────────────────────────────

def check_ollama(model: str) -> bool:
    """Return True if Ollama is reachable and the requested model is available."""
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=5) as resp:
            data = json.loads(resp.read())
        available = [m["name"] for m in data.get("models", [])]
        # Accept exact match or prefix match (e.g. "llama3.2" matches "llama3.2:latest")
        match = any(
            m == model or m.startswith(model.split(":")[0] + ":")
            for m in available
        )
        if not match:
            print(f"[LLM] Model '{model}' not found. Available: {available}")
        return match
    except Exception as e:
        print(f"[LLM] Ollama not reachable at localhost:11434 — {e}")
        return False


def _call_ollama(prompt: str, model: str, timeout: int = 60) -> Optional[str]:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,   # low temp → deterministic attribution
            "num_predict": 64,    # we only need a short JSON response
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
        print(f"  [LLM] Connection error: {e}")
        return None
    except Exception as e:
        print(f"  [LLM] Error: {e}")
        return None


# ── Response parsing ──────────────────────────────────────────────────────────

def _parse_response(response: str, known_characters: list) -> tuple[Optional[str], float]:
    """
    Extract (speaker, confidence) from an LLM response.

    Tries in order:
      1. Parse the whole response as JSON
      2. Extract a JSON object with regex
      3. Match a known character name directly in the response text
    """
    if not response:
        return None, 0.0

    text = response.strip()

    # 1. Direct JSON parse (ideal case)
    try:
        data = json.loads(text)
        return _extract_from_dict(data, known_characters)
    except json.JSONDecodeError:
        pass

    # 2. Extract first {...} block from response
    m = re.search(r'\{[^}]+\}', text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            return _extract_from_dict(data, known_characters)
        except json.JSONDecodeError:
            pass

    # 3. Fuzzy: find a known character name mentioned in the response
    lower = text.lower()
    for char in sorted(known_characters, key=len, reverse=True):
        if char.lower() in lower:
            # Try to pull a confidence value too
            conf_m = re.search(r'(\d+(?:\.\d+)?)', text)
            raw_conf = float(conf_m.group(1)) if conf_m else 0.0
            # Treat values > 1 as percentages
            confidence = raw_conf / 100.0 if raw_conf > 1.0 else raw_conf
            confidence = max(0.0, min(1.0, confidence))
            return char, confidence if confidence > 0 else 0.65

    return None, 0.0


def _extract_from_dict(data: dict, known_characters: list) -> tuple[Optional[str], float]:
    speaker = str(data.get("speaker", "")).strip()
    confidence = float(data.get("confidence", 0.0))

    if not speaker or speaker.upper() == "UNKNOWN":
        return None, confidence

    # Canonicalize: try exact match first, then case-insensitive
    for char in known_characters:
        if char.lower() == speaker.lower():
            return char, confidence

    # Accept the LLM's name if it looks reasonable (title-cased, not a stopword)
    if re.match(r'^[A-Z][a-z]', speaker):
        return speaker.title(), confidence

    return None, confidence


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(blocks: list, target_idx: int, window: int = 6) -> str:
    """
    Return a labelled context string of up to `window` blocks either side of
    target_idx, skipping the target block itself.
    """
    start = max(0, target_idx - window)
    end = min(len(blocks), target_idx + window + 1)
    lines = []

    for i in range(start, end):
        if i == target_idx:
            continue
        b = blocks[i]
        text = b["text"][:120].replace("\n", " ")
        if b["type"] == "narration":
            lines.append(f"  [narration] {text}")
        else:
            spk = b.get("speaker", "UNKNOWN")
            marker = ">>UNRESOLVED<<" if b.get("unresolved") else spk
            lines.append(f"  [{marker}] {text}")

    return "\n".join(lines) if lines else "  (no surrounding context)"


# ── Main pass ─────────────────────────────────────────────────────────────────

def run_llm_pass(
    ir_data: dict,
    model: str = "llama3.2",
    confidence_threshold: float = 0.6,
) -> dict:
    """
    Run the LLM attribution pass over all unresolved blocks in ir_data.
    Modifies ir_data in place and returns it.
    """
    characters = ir_data.get("characters", [])
    char_list = ", ".join(characters) if characters else "(none detected)"

    total_unresolved = sum(
        1 for ch in ir_data["chapters"]
        for b in ch["blocks"]
        if b["type"] == "dialogue" and b["unresolved"]
    )

    if total_unresolved == 0:
        print("[LLM] No unresolved blocks — nothing to do.")
        return ir_data

    print(f"[LLM] Model:     {model}")
    print(f"[LLM] Threshold: confidence > {confidence_threshold}")
    print(f"[LLM] Blocks:    {total_unresolved} unresolved")
    print()

    resolved = 0
    low_conf = 0
    errors = 0
    processed = 0
    conf_sum = 0.0

    for ch_idx, chapter in enumerate(ir_data["chapters"]):
        blocks = chapter["blocks"]
        ch_resolved = 0

        for blk_idx, block in enumerate(blocks):
            if block["type"] != "dialogue" or not block["unresolved"]:
                continue

            processed += 1
            if processed % 25 == 0:
                pct = processed / total_unresolved * 100
                print(
                    f"\n── progress: {processed}/{total_unresolved} "
                    f"({pct:.0f}%)  resolved={resolved}  low_conf={low_conf}  errors={errors} ──\n"
                )

            context_str = _build_context(blocks, blk_idx)
            prompt = PROMPT_TEMPLATE.format(
                characters=char_list,
                context=context_str,
                dialogue=block["text"],
            )

            raw = _call_ollama(prompt, model)
            if raw is None:
                errors += 1
                print(f"  ✗ ch{ch_idx:03d}_blk{blk_idx:04d}  [connection error]")
                continue

            speaker, confidence = _parse_response(raw, characters)

            if speaker and confidence >= confidence_threshold:
                block["speaker"] = speaker
                block["confidence"] = round(confidence, 2)
                block["attribution_method"] = f"llm_{model.split(':')[0]}"
                block["unresolved"] = False
                resolved += 1
                ch_resolved += 1
                conf_sum += confidence
                print(
                    f"  ✓ ch{ch_idx:03d}_blk{blk_idx:04d}  "
                    f"{speaker:<18} conf={confidence:.2f}  "
                    f"{block['text'][:55]!r}"
                )
            else:
                low_conf += 1
                conf_str = f"{confidence:.2f}" if confidence else "n/a"
                print(
                    f"  ? ch{ch_idx:03d}_blk{blk_idx:04d}  "
                    f"{'UNKNOWN':<18} conf={conf_str}  "
                    f"{block['text'][:55]!r}"
                )

        if ch_resolved:
            print(f"    → chapter '{chapter['title'][:40]}': +{ch_resolved} resolved")

    ir_data["_llm_stats"] = {
        "resolved": resolved,
        "low_conf": low_conf,
        "errors": errors,
        "avg_confidence": round(conf_sum / resolved, 3) if resolved else 0.0,
    }

    # Recount
    ir_data["unresolved_count"] = sum(
        1 for ch in ir_data["chapters"]
        for b in ch["blocks"]
        if b["type"] == "dialogue" and b["unresolved"]
    )

    print()
    print(f"[LLM] Resolved:   {resolved}/{total_unresolved}")
    print(f"[LLM] Low-conf:   {low_conf}  (below {confidence_threshold} threshold — still UNKNOWN)")
    if errors:
        print(f"[LLM] Errors:     {errors}  (Ollama connection failures)")
    print(f"[LLM] Remaining:  {ir_data['unresolved_count']}")

    return ir_data
