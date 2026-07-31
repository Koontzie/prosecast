"""
Alias Suggester — deterministic merge suggestions for the cast screen.

Finds speaker names that are almost certainly the same character rendered
differently ("Astryx" / "Astryx Arboren" / "Warn Astryx") using token-overlap
rules — no LLM involved. Suggestions are surfaced as click-to-confirm chips
in the cast drawer; accepting one executes the normal journaled /cast/merge.
The human click is the decision; this module only nominates.

Precision over recall: diminutives (Bob/Bobby) and nicknames are deliberately
NOT suggested — a wrong auto-suggestion accepted by a tired human corrupts
attribution silently. Token rules only fire on near-certain cases.
"""

import re

# Stripped before comparison so "Captain Fern" ≡ "Fern".
HONORIFICS = {
    "mr", "mrs", "ms", "miss", "mx", "dr", "doctor", "sir", "dame", "lady",
    "lord", "master", "mistress", "captain", "capt", "professor", "prof",
    "aunt", "auntie", "uncle", "old", "young", "the",
}

MIN_ANCHOR_LEN = 3   # subset rule needs at least one shared token this long


def _tokens(name: str) -> frozenset:
    toks = re.findall(r"[a-z]+", name.lower())
    return frozenset(t for t in toks if t not in HONORIFICS)


def _speaker_counts(ir_data: dict) -> dict:
    counts = {}
    for ch in ir_data.get("chapters", []):
        for b in ch.get("blocks", []):
            if b.get("type") != "dialogue":
                continue
            s = b.get("speaker")
            if s and s not in ("NARRATOR", "UNKNOWN"):
                counts[s] = counts.get(s, 0) + 1
    return counts


def suggest_merges(ir_data: dict) -> list:
    """Return [{from_name, into, from_count, into_count, reason}, ...].

    Rules (both high-precision):
      variant  — identical token sets after honorific stripping
                 ("Captain Fern" / "Fern", "ASTRYX" / "Astryx")
      subset   — one name's tokens are a strict subset of the other's
                 ("Astryx" ⊂ "Astryx Arboren"), anchored by a token of
                 length >= MIN_ANCHOR_LEN

    The higher-dialogue-count name is the merge target. Ties keep the
    shorter name as target (it's usually the canonical form).
    """
    counts = _speaker_counts(ir_data)
    names = sorted(counts)
    toks = {n: _tokens(n) for n in names}

    suggestions = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ta, tb = toks[a], toks[b]
            if not ta or not tb:
                continue
            if ta == tb:
                reason = "same name"
            elif ta < tb or tb < ta:
                shared = ta & tb
                if max((len(t) for t in shared), default=0) < MIN_ANCHOR_LEN:
                    continue
                reason = "name overlap"
            else:
                continue
            if counts[a] == counts[b]:
                into, frm = (a, b) if len(a) <= len(b) else (b, a)
            else:
                into, frm = (a, b) if counts[a] > counts[b] else (b, a)
            suggestions.append({
                "from_name": frm,
                "into": into,
                "from_count": counts[frm],
                "into_count": counts[into],
                "reason": reason,
            })

    # Most impactful first: big orphaned line counts hurt renders the most
    suggestions.sort(key=lambda s: -s["from_count"])
    return suggestions
