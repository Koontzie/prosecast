# Attribution Scorecard — Listening Triage (2026-07-03)

Purpose: focus Tyler's chapter spot-checks on the books/chapters most likely to expose
problems. Existing books scored from their `library/` IR; Moby Dick and Yumi scored
fresh, **rules-only** (no LLM pass — sandbox couldn't reach Ollama), first 20 chapters.
Nothing was written to `library/` for the two new books.

## Summary table

| Book | Scope | Dialogue | Unresolved | Speakers (noise ≤2 lines) | LLM pass? |
|---|---|---|---|---|---|
| Parade of Horribles | full, 115 ch | 3,890 | **0.1%** (5) | 257 (137 noise) | ✅ |
| Brigands & Breadknives | full, 52 ch | 2,149 | 5.9% (126) | 44 (11 noise) | ? |
| Yumi (Sanderson) | first 20/51 ch | 1,178 | 26.4% (311) | 22 (10 noise) | ❌ rules-only |
| Carousel b8 | 8 ch | 959 | 10.7% (103) | 47 (20 noise) | ❌ (POV problem) |
| Frankenstein | full, 31 ch | 365 | **37.5%** (137) | 43 (24 noise) | ❌ |
| Moby Dick | first 20/142 ch | 236 | **61.9%** (146) | 50 (**46 noise**) | ❌ rules-only |

## Per-book reads

**Parade** — attribution basically solved. The remaining problem is the *cast*: 137
noise "speakers" (spaCy tagging LitRPG skill names as people). This is the cast-review-
screen use case, not an attribution bug. Worst chapters barely register (1 unresolved each).

**Brigands** — healthiest raw book. 5.9% overall but concentrated: **Ch 27 (25/54 = 46%)
and Ch 4 (20/43 = 47%)** hold ~36% of all unresolved blocks. Listen to those two first.

**Yumi** — modern prose parses beautifully: only 22 speakers, clean top cast
(Yumi/Akane/Painter/Liyun/Design). 26.4% unresolved is rules-only; expect the LLM pass
to pull it near Parade levels (Parade went 10% → 0.2%). Worst: **Ch 14 (128/207 = 62%),
Ch 11 (92/173 = 53%)** — likely long back-and-forth exchanges where alternation loses
the thread. Best modern-fantasy validation target after Parade.

**Carousel** — known quantity: first-person POV shifts, messy source. Blocked on the
per-chapter narrator dropdown (post-MVP). Don't spend listening time here yet.

**Frankenstein** — ⚠️ the "zero-error Frankenstein" result was the **tagging** pass;
attribution is 37.5% unresolved. Epistolary/nested-quote structure (Walton's letters
quoting Victor quoting the creature) defeats the said-X regex layers. Also: chapter
titles all come out as "Frankenstein | Project Gutenberg" — Gutenberg EPUB title
extraction is broken. Run the LLM pass before judging; may also need a
nested-quote segmentation fix.

**Moby Dick** — genre stress test, and it fails hard as expected: 61.9% rules-only,
and NER noise is catastrophic (Nantucket, Death, Whales, Sabbath, Cabin as "people";
`I. "Landlord!` as a character name = a segmentation bug worth a look). Same Gutenberg
chapter-title breakage as Frankenstein. 19th-century discursive prose is a post-MVP
genre; keep as the canary, don't tune for it now.

## Recommended listening plan (order of information value)

1. **Run the LLM pass first** (on the Mac, Ollama up) for Yumi + Frankenstein:
   `python main.py --book <epub> --ir-only --llm` — no point listening to rules-only gaps.
2. **Yumi Ch 14 & 11** — post-LLM. Tests dialogue stability in long modern exchanges.
3. **Brigands Ch 27 & 4** — what kind of lines defeat the rules?
4. **Parade any mid-book chapter** — the "does the finished product feel good" check
   (attribution is solved; this is a voice/tag quality listen once render exists).
5. **Frankenstein Walton letters (early chapters)** — only after LLM pass; decides
   whether nested-quote segmentation is worth fixing pre-MVP.

## Bugs surfaced by this pass (file, don't fix yet)

- Gutenberg EPUBs: chapter titles resolve to the page `<title>` ("… | Project Gutenberg")
  instead of chapter headings (Frankenstein, Moby Dick).
- Segmentation can emit fragments like `I. "Landlord!` as speaker names (Moby Dick).
- Front-matter chapters (Gutenberg license text) generate 1-dialogue-block junk chapters.
