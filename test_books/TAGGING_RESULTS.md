# ProseCast Tagging Validation Results

Generated: 2026-05-28 | Model: mistral:7b (Gideon, GIDEON_HOST:11434)

---

## Sample Book (P&P excerpt) — Smoke Test

**Blocks:** 51 total (26 dialogue, 25 narration)  
**Tagged:** 51/51 (100%)  
**Errors:** 0  
**Avg latency:** 3.6s/block  
**Total runtime:** 3.1 min  

**Quality notes:**
- All dialogue action verbs use "to VERB" form — constraint holding
- Genre = restrained Austen drawing-room register; most actions are polite social maneuvering
- Best specific verbs: "to make himself acceptable", "to test the waters", "to evade direct answer", "to humor", "to signal change"
- Weakest: several "to acknowledge" / "to inform" — generic but accurate for minimal dialogue lines
- Pacing varies correctly: brisk for Bingley's entrance, measured for formal P&P register

**Verdict:** Solid first pass. P&P is a hard case (extreme restraint), not the best quality benchmark.

---

## Frankenstein — Literary Gothic Horror

**Blocks:** 690 total (365 dialogue)  
**Run mode:** dialogue-only  
**Tagged:** 365/365 (100%)  
**Errors:** 0  
**Avg latency:** 9.88s/block (Gideon under moderate load)  
**Total runtime:** 60.1 min  
**Attribution unresolved:** 137/365 (37.5%) — see note below

**Top 10 highest-intensity blocks:**

| Block | Intensity | Pace | Action | Emotion |
|-------|-----------|------|--------|---------|
| ch16_seg_0010 | 1.0 | urgent | to curse vehemently | unbridled fury |
| ch22_seg_0033 | 1.0 | urgent | to express uncontrolled fury | unbridled rage |
| ch23_seg_0007 | 1.0 | urgent | to threaten | malicious rage |
| ch26_seg_0007 | 1.0 | urgent | to assert dominance | unyielding anger |
| ch27_seg_0014 | 1.0 | slow | to express deep despair | agonizing sorrow |
| ch14_seg_0056 | 1.0 | slow | to express deep despair | heart-wrenching sorrow |
| ch16_seg_0012 | 1.0 | urgent | to curse vehemently | unbridled fury |
| ch30_seg_0039 | 0.9 | slow | to confess guilt | despairing remorse |
| ch30_seg_0041 | 0.9 | slow | to confess guilt | despairing remorse |
| ch30_seg_0058 | 0.9 | slow | to confess guilt | despairing remorse |

**Quality verdict:** Significantly better than P&P. Gothic register produces highly specific verbs:
"to curse vehemently", "to taunt" [malicious glee], "to avenge" [consuming rage],
"to assert dominance" [imperious certainty]. Pace assignments accurate throughout —
urgency flags fire in crisis scenes, slow/measured in grief and trial scenes.

**Notable observations:**
- The Creature's confrontation scenes (ch22-23, ch26) hit max intensity correctly
- Justine trial chapters (ch13-14) are tagged with high accuracy: "to appeal for mercy" [desperate plea], "to confess guilt" [resigned acceptance], "to defend Justine" [firm conviction]
- The ch30 finale sequence reads correctly as cascading despair/confession

**Attribution unresolved note:**  
137/365 (37.5%) unresolved is high — this is a Frankenstein structural issue, NOT a pipeline failure. The Creature's first-person narrative (chapters 16-21 in the Gutenberg edition, framed inside Victor's letter to Walton) uses "I" but the Creature has no explicit "said" attribution pattern. Without `--narrator "Creature"` targeting those specific chapters, these blocks all fall through to UNKNOWN. The tagging quality for those blocks is still correct (tagging reads context, not speaker attribution).

**Known character list noise:**  
spaCy tagged Gutenberg metadata contributors ("Al Haines", "Christy Phillips", "David Meltzer", "John Melbourne", "Judith Boss", "Lynn Hanninen") and archaic word forms ("Adieu", "Behold", "Farewell", "Cursed") as PERSON entities. 100+ "characters" in IR. Doesn't affect tagging quality but will cause attribution errors if audio is rendered without cleaning up the character list first.

---

## Yumi and the Nightmare Painter (Sanderson) — Fantasy

**Status:** Not yet run  
**Planned:** After Frankenstein completes  

---

## Summary Comparison

| Book | Blocks | Tagged | Error% | Avg lat | Quality |
|------|--------|--------|---------|---------|---------|
| Sample (P&P) | 51 | 51 (100%) | 0% | 3.6s | Good (restrained genre) |
| Frankenstein | 365d | 365 (100%) | 0% | 9.88s | Excellent |
| Yumi (Sanderson) | TBD | TBD | TBD | TBD | TBD |

---

## Estimated Cost to Tag a Full 100-Chapter Book

Based on Frankenstein (31 chapters, 365 dialogue blocks):
- Dialogue only at 9.88s/block (Gideon under load): 365 × 9.88 = ~60 min
- Dialogue only at ~4s/block (Gideon idle): 365 × 4 = ~25 min (estimated from sample)
- All blocks at 3.6s/block: 690 × 3.6 = ~41 min
- Parade of Horribles (3,890 dialogue blocks) at 4s/block: ~4.3 hours

**Token cost:** Local model, zero marginal cost. Time cost only.

**Recommendation for large books:** Run `--tag-dialogue-only` during review phase.
Run full block tagging only when preparing for final audio render.
