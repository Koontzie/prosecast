# ProseCast — Productization Notes (2026-08-01)

Captured at the ComfyUI-pause. This is thinking, not commitments. Companion
to HANDOFF.md (technical resume) — this file is the "if strangers ever use
this" resume. Money-model baseline (decided 2026-07-10) still stands: free
local tier IS the product; ElevenLabs is BYO-key with affiliate link, no
markup; marketplace/royalties are moonshot-only and must never block
sharing the free tool.

## Honest state assessment (2026-08-01)

Core experience: genuinely good (Brigands end-to-end, listen passed).
Polished-for-Tyler ≠ polished-for-strangers. Three gaps before any outside
user: (1) INSTALL STORY — venv + spaCy + Chatterbox server + Ollama is a
wall; (2) two remaining terminal steps (LLM passes, align) → pipeline-in-UI;
(3) missing-service UX (friendly "Ollama isn't reachable, here's what that
means" instead of silent skips). A design/dev polish run only makes sense
AFTER those. Likely shape of v1: **a public repo people scaffold from**,
not a packaged app — great README, philosophy page, ko-fi + affiliate
links, "bring your own hardware tier" posture. That's shippable far sooner
and fits the audience (Ollama people live on GitHub).

## Positioning / philosophy (write as a first-class page)

- **Local-first, privacy-first:** "your book never leaves your machine" is
  sentence one. No telemetry.
- **Personal use framing:** books you own, accessibility, out-of-print
  works. This is also the legal shelter.
- **Voice actors:** three planks —
  1. *Provenance:* audit + document where the 33 predefined voices come
     from and their licenses BEFORE any outside user. (The one item with
     real downside if skipped.)
  2. *Consent:* explicit no-cloning-without-consent policy (clone-ref
     feature makes this non-optional).
  3. *Future:* VA voice marketplace with per-book payout — stated as
     direction, not promise.

## "How does this really work" (the explainer)

One page, plain words: your book → who's speaking (rules catch ~95%
deterministically, a local AI reads the scenes for the hard 5%) → you cast
voices (or let auto-cast do the crowd) → your computer performs it →
optional word-accurate read-along. Nothing leaves your machine.

## Hardware ladder (meet users where they are)

1. **No GPU:** Piper TTS (already an engine; CPU; robotic-but-fine) +
   llama3.2:3b attribution at scope=unresolved. Needs: eval harness to
   certify quality, demo clips so expectations are set by ears.
2. **Gaming PC (8-12GB):** Chatterbox + gemma-class. Full experience, slower.
3. **Home server (Tyler tier):** the current reference setup.
4. **No hardware, has a CLI subscription:** *(Tyler 2026-08-01)* Claude
   Code / Codex / Gemini CLI invoked headless (`claude -p ...`) as the
   attribution backend — subscription auth, supported use, slow-but-batch-
   tolerant. Cheap adapter: `PROSECAST_LLM_BACKEND=ollama|api|claude-cli`
   (scene pass is already prompt→JSON; CLI backend = subprocess).
5. **No hardware, pay-per-use:** BYO API key. NOTE: chat subscriptions
   (ChatGPT Plus / Claude web) can NOT be used programmatically — API keys
   only. One OpenAI-compatible adapter (base URL + key in settings) covers
   OpenAI/Anthropic/Groq/OpenRouter/Gemini at once; whole-book attribution
   via cheap API models ≈ pennies. TTS is the expensive part → BYOK
   ElevenLabs (affiliate) already exists.
6. **Cloud GPU middle path:** RunPod/Vast template (docker-compose:
   Chatterbox + Ollama + whisper). A docs page, not a feature.

## Git as proto-marketplace (spitball, has precedent)

ComfyUI custom nodes + Ollama's library both started as "community repos +
a manifest convention." ProseCast seeds already exist in the data model:
shared voice_meta.json packs, cast presets for public-domain books,
someday consented VA voice packs as repos with LICENSE files + payout
links. Start as a folder convention + README section. Zero payment rails
needed to germinate.

## Future input formats (Tyler 2026-08-01)

- **Scripts/screenplays: the EASY one.** Explicit speaker labels ("FERN:",
  stage directions = narration) → near-100% deterministic attribution, no
  LLM needed. New parser at the book_parser stage only; everything
  downstream unchanged. Fun one-session feature.
- **PDFs: the hard one** — extraction, not pipeline. Start text-layer-only
  (PyMuPDF), be honest about it; scanned/OCR later or never.

## Monetization touchpoints (never gates)

Ko-fi + ElevenLabs affiliate in README + app footer. That's it, per the
2026-07-10 decision.

## Open decisions before ANY outside user (checklist)

- [ ] Code license (open source? which? shapes marketplace options)
- [ ] Predefined-voice provenance/license audit
- [ ] Content-legality terms page (own the EPUB; personal use; don't
      distribute generated audio of copyrighted works)
- [ ] Security note: phone listening = server beyond localhost → recommend
      Tailscale in docs (or add auth)
- [ ] Support surface + boundary (GitHub issues only? Discord? how much of
      Tyler's life does a solo tool get)
- [ ] Name collision check ("ProseCast")
- [ ] 2-3 friendly beta users BEFORE anything public (the follow-toggle
      lesson: a second pair of ears finds things instantly)
