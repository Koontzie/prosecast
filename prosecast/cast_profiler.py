"""
Cast Profiler — character gender/age/voice hints for blind casting.

A listener casting a book BEFORE reading it can't know whether "Astryx" is
feminine or masculine — and a wrong-gender voice is the most expensive
casting mistake (discovered after rendering, fixed by re-rendering every
line the character speaks). This pass infers, per speaking character:

    gender:      feminine | masculine | ambiguous
    age:         child | young-adult | adult | elder | unknown
    voice_hints: 2-4 free words for the caster ("gravelly, weary")
    evidence:    short quote grounding the call

Two layers, cheap first:
  1. Deterministic — gendered titles in the NAME itself (Abbess, Brother,
     Lady, Mr...) resolve instantly, no LLM, confidence 0.9.
  2. LLM — for the rest, the model reads a few of the character's lines
     WITH surrounding narration (where the he/she/they pronouns live) and
     returns a profile. Threshold-gated; below it → ambiguous/unknown.

Profiles land in ir["character_profiles"] = {name: {...}} — additive, never
touches attribution fields. The cast screen renders them as chips.

Ollama endpoint: PROSECAST_OLLAMA_URL (shared with the other passes).
"""

import json
import re
import urllib.request
import urllib.error
from typing import Optional

from prosecast.llm_attributor import OLLAMA_BASE

OLLAMA_API = f"{OLLAMA_BASE}/api/generate"

MIN_LINES_TO_PROFILE = 2      # walk-ons aren't worth a call (or a chip)
SAMPLE_LINES = 4              # excerpts per character shown to the model
CONTEXT_CHARS = 260           # narration context per excerpt side
VALID_GENDERS = {"feminine", "masculine", "ambiguous"}
VALID_AGES = {"child", "young-adult", "adult", "elder", "unknown"}

# Layer 1: gendered titles/honorifics inside the character's own name.
FEMININE_TITLES = {
    "mrs", "ms", "miss", "lady", "dame", "queen", "princess", "duchess",
    "abbess", "sister", "mother", "aunt", "auntie", "madam", "madame",
    "mistress", "widow", "countess", "baroness", "empress",
}
MASCULINE_TITLES = {
    "mr", "sir", "lord", "king", "prince", "duke", "abbot", "brother",
    "father", "uncle", "master", "count", "baron", "emperor", "monk",
}

PROMPT_TEMPLATE = """\
You are helping cast voice actors for an audiobook. Based ONLY on the
excerpts below, profile the character "{name}". Surrounding narration is
included — pronouns and descriptions there are your main evidence.

EXCERPTS:
{excerpts}

Reply with ONLY one line of valid JSON — no explanation, no markdown:
{{"gender": "feminine|masculine|ambiguous", "age": "child|young-adult|adult|elder|unknown", "voice_hints": "2-4 words", "confidence": 0.0, "evidence": "short quote from the excerpts"}}

Rules:
- gender is how the text refers to them (he/she/they, descriptions). If the
  excerpts never indicate it, use "ambiguous" with low confidence — do NOT
  guess from the name alone.
- confidence 0.0-1.0 reflects the pronoun/description evidence, not intuition.
- evidence: the strongest phrase you saw (e.g. "she snorted", "the old man").
"""


# ── Layer 1: deterministic ────────────────────────────────────────────────────

def profile_from_name(name: str) -> Optional[dict]:
    """Gendered title inside the name itself → instant profile (no LLM)."""
    tokens = set(re.findall(r"[a-z]+", name.lower()))
    fem = bool(tokens & FEMININE_TITLES)
    masc = bool(tokens & MASCULINE_TITLES)
    if fem == masc:          # neither, or contradictory
        return None
    title = (tokens & (FEMININE_TITLES | MASCULINE_TITLES)).pop()
    return {
        "gender": "feminine" if fem else "masculine",
        "age": "unknown",
        "voice_hints": "",
        "confidence": 0.9,
        "evidence": f"title '{title}' in name",
        "method": "title",
    }


# ── Excerpt gathering ─────────────────────────────────────────────────────────

def gather_excerpts(ir_data: dict, name: str, limit: int = SAMPLE_LINES) -> list:
    """Spread samples across the book — pronoun evidence clusters by scene,
    and early scenes may deliberately obscure a character."""
    hits = []
    for chapter in ir_data.get("chapters", []):
        for b in chapter.get("blocks", []):
            if (b.get("type") == "dialogue" and b.get("speaker") == name
                    and not b.get("unresolved")):
                hits.append(b)
    if not hits:
        return []
    step = max(1, len(hits) // limit)
    picked = hits[::step][:limit]
    out = []
    for b in picked:
        before = (b.get("context_before") or "")[-CONTEXT_CHARS:]
        after = (b.get("context_after") or "")[:CONTEXT_CHARS]
        out.append(f"...{before}\n  {name}: {b.get('text', '')}\n{after}...")
    return out


# ── LLM layer ─────────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, model: str, timeout: int = 120) -> Optional[str]:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 160},
    }).encode()
    req = urllib.request.Request(
        OLLAMA_API, data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except urllib.error.URLError as e:
        print(f"  [PROFILE] Connection error: {e}")
        return None
    except Exception as e:
        print(f"  [PROFILE] Error: {e}")
        return None


def parse_profile_response(raw: str) -> Optional[dict]:
    """Tolerates <think> blocks and fences; validates enums; clamps confidence."""
    if not raw:
        return None
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    gender = str(data.get("gender", "")).strip().lower()
    if gender not in VALID_GENDERS:
        gender = "ambiguous"
    age = str(data.get("age", "")).strip().lower()
    if age not in VALID_AGES:
        age = "unknown"
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "gender": gender,
        "age": age,
        "voice_hints": str(data.get("voice_hints", ""))[:60],
        "confidence": round(conf, 2),
        "evidence": str(data.get("evidence", ""))[:160],
        "method": "llm",
    }


# ── Main pass ─────────────────────────────────────────────────────────────────

def run_profile_pass(
    ir_data: dict,
    model: str = "llama3.2",
    confidence_threshold: float = 0.5,
    reprofile: bool = False,
    checkpoint_path: Optional[str] = None,
) -> dict:
    """Profile every character with >= MIN_LINES_TO_PROFILE dialogue blocks.

    Existing profiles are kept unless reprofile=True (so re-runs after new
    corrections only fill gaps). Below-threshold LLM answers are stored as
    ambiguous/unknown — an honest '?' chip beats a confident wrong one.
    """
    counts = {}
    for ch in ir_data.get("chapters", []):
        for b in ch.get("blocks", []):
            if b.get("type") == "dialogue" and not b.get("unresolved"):
                s = b.get("speaker")
                if s and s not in ("NARRATOR", "UNKNOWN"):
                    counts[s] = counts.get(s, 0) + 1

    targets = [n for n, c in sorted(counts.items(), key=lambda x: -x[1])
               if c >= MIN_LINES_TO_PROFILE]
    profiles = ir_data.setdefault("character_profiles", {})
    if not reprofile:
        targets = [n for n in targets if n not in profiles]

    if not targets:
        print("[PROFILE] Every eligible character already profiled — nothing to do.")
        return ir_data

    print(f"[PROFILE] Model:   {model}")
    print(f"[PROFILE] Targets: {len(targets)} characters (>= {MIN_LINES_TO_PROFILE} lines)")

    by_title = llm_done = ambiguous = errors = 0
    consecutive_errors = 0
    for name in targets:
        titled = profile_from_name(name)
        if titled:
            profiles[name] = titled
            by_title += 1
            print(f"  ✓ {name:<22} {titled['gender']:<10} (title, no LLM)")
            continue

        excerpts = gather_excerpts(ir_data, name)
        if not excerpts:
            continue
        raw = _call_ollama(
            PROMPT_TEMPLATE.format(name=name, excerpts="\n\n".join(excerpts)),
            model,
        )
        if raw is None:
            errors += 1
            consecutive_errors += 1
            if consecutive_errors >= 3:
                print(f"\n[PROFILE] {consecutive_errors} connection failures in a row — "
                      "aborting pass (profiles so far are saved; re-run to resume).")
                break
            continue
        consecutive_errors = 0
        prof = parse_profile_response(raw)
        if prof is None:
            errors += 1
            continue
        if prof["confidence"] < confidence_threshold:
            prof["gender"] = "ambiguous"
            ambiguous += 1
        else:
            llm_done += 1
        profiles[name] = prof
        print(f"  ✓ {name:<22} {prof['gender']:<10} conf={prof['confidence']:.2f}  "
              f"{prof['evidence'][:45]!r}")

        if checkpoint_path:
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(ir_data, f, indent=2, ensure_ascii=False)

    print(f"\n[PROFILE] {by_title} by title, {llm_done} by LLM, "
          f"{ambiguous} ambiguous, {errors} errors")
    return ir_data
