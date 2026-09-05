# Origins — what the ideas are and when they were made

A short, dated record, kept so that credit is legible. Everything here is
verifiable in this repository's history; the repository was initialised on
2026-06-10 and the earliest artifacts predate it by a few weeks.

## Actioning verbs as delivery tags (May 2026)

Every line in the intermediate representation carries a tag of the form
`{action: "to <verb>", emotion, intensity, pace}`. The `action` is an
**actioning verb** — the playable intention an actor would be given by a
director ("to evade", "to reassure", "to wound") — rather than an emotion
label ("sad", "angry"). The tag is stored abstractly and translated to each
speech engine's controls only at render time (`prosecast/tag_mapper.py`), so
the stored tags never depend on which engine is underneath.

Two things this joins are each old. Expressive control of synthesized speech
by tag is common (SSML emotion extensions, Bark's `[laughs]`, Orpheus's
nonverbal tags, ElevenLabs audio tags, Fish Audio's natural-language
directions). Actioning as a rehearsal vocabulary is a century old and is
catalogued in *Actions: The Actors' Thesaurus* (Caldarone & Lloyd-Williams,
2004). Using the actor's vocabulary as the *tag schema*, and decoupling it
from the engine, is the contribution claimed here. Designed and first
implemented by Tyler Koontz in May 2026 (`prosecast/tag_generator.py`,
`prosecast/tag_mapper.py`, and the validation run recorded in
`test_books/TAGGING_RESULTS.md`, dated 2026-05-28); first committed
2026-06-10.

## The corrections journal as a training flywheel (June 2026)

Every manual speaker correction is appended to `library/<slug>/corrections.jsonl`
— append-only, human-readable, keyed to the line and the book identity, never
containing the book's text. The stated purpose from the first commit that
introduced it (2026-06-10) is that these corrections are labeled examples for
a future fine-tuned attribution model and for sharing casts between users of
the same book. See `docs/PHILOSOPHY.md` → "Sharing casts and voices".

## Rules-first attribution with provenance (May–July 2026)

Speaker attribution runs a six-layer rule cascade before any model is
consulted; every block records how it was attributed and with what
confidence, and a scene-batched local-LLM pass (2026-07-31,
`prosecast/scene_attributor.py`) handles only what the rules could not.
The approach is not novel in its parts; the specific cascade, the provenance
on every block, and the correction loop around it are this project's.

## The cast exchange (design, 2026-08/09)

Described, not built. `docs/PHILOSOPHY.md` and
`docs/market-research-communities-marketplaces.md` are the dated record of
the design: casts as text-free files, voice packs with consent manifests,
credit before money.
