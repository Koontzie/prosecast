---
name: Competitive Landscape
description: Key competitors and ProseCast's strategic positioning vs. ElevenReader and ElevenLabs
type: project
---

**ElevenReader** — closest surface-level competitor. Read-aloud app, one voice for everything, "Auto-assign voices" labeled Alpha and non-functional. Productivity/commuting positioning (PDFs, articles). Not solving multi-voice casting.

**ElevenLabs audiobook creator (ElevenCreative)** — EPUB/PDF upload, single default voice, experimental character detection. No correction loop, no per-character casting UI, flat audio file output.

**The gap:** Neither does attribution at scale, per-character assignment, inline correction, or directorial cast control. ElevenReader's Alpha feature is the closest attempt at what ProseCast already does at 99.8% on 115 chapters.

**Why:** ElevenReader's Alpha status signals the problem is known but unsolved at the product level. ProseCast's correction loop, shared attribution database, and voice marketplace have no equivalent.

**Strategic note:** Using ElevenLabs as ProseCast's premium TTS backend is correct — compete on the attribution + UX layer above voice synthesis, not on voice quality itself.

**How to apply:** When scoping features or making architecture decisions, frame ProseCast's value as directorial control + attribution quality, not voice generation. Don't over-invest in voice synthesis improvements — that's ElevenLabs' job.
