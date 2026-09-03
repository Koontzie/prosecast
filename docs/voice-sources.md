# Voice sources — where ProseCast's reference clips come from

**Written:** 2026-08-31 (Cowork session). **Companion to:** `scripts/stage_librivox_dialects.py`,
`scripts/stage_vctk_voices.py`, `voice_meta.json`, `docs/market-research-communities-marketplaces.md`.

The problem this doc solves: the voice bank is VCTK-derived, and **VCTK has ~4 American
speakers out of 110** — which is why every US character ends up sounding like the same
three people. This is the vetted list of places to get more, with the licence verdict for
each, so the question never has to be re-researched.

---

## The rule that actually governs this

**A Creative Commons licence is a copyright licence. It is not voice consent.** They are
separate legal objects and only one of them is settled by a dataset card.

[Lehrman v. Lovo](https://www.skadden.com/insights/publications/2025/07/new-york-court-tackles-the-legality-of-ai-voice-cloning)
(SDNY, 2025) is the load-bearing case: the court **dismissed** the copyright claims —
copyright protects the fixed recording, *"not the abstract qualities of a voice"* — but let
the **New York right-of-publicity** claims stand, and held that continuing use of a trained
voice model is a *continuing* violation. Translation: the CC BY 4.0 on LibriTTS-R protects
you from the claim you were never going to lose, and does nothing about the claim you could.

The [NO FAKES Act](https://www.hklaw.com/en/insights/publications/2026/06/senate-judiciary-committee-advances-legislation-to-protect-name)
advanced out of Senate Judiciary on 2026-06-18 (not law yet); Tennessee's ELVIS Act already
covers voice at state level. A federal digital-replica right with takedown duties is
plausibly coming, and its research exemptions are *nonprofit* — they would not cover a
marketplace.

**So the tiering is:**

| Tier | What goes in it | Rule |
|---|---|---|
| **SHIP** | Public domain / CC0 / CC BY 4.0, where the speakers published for redistribution or the voice is synthetic | Can live in the open repo, a release, or marketplace inventory |
| **PRIVATE** | NC / SA / research-only corpora | Tyler's own box only. Never in a release, never in a public voice pack |
| **NEVER** | ND, all-rights-reserved, scraped-from-the-wild | Don't build on it at all |

Every voice needs a `license` + `distributable` + `source_url` field in `voice_meta.json`
so a release script can mechanically answer *"is this one safe to ship?"* — that is why
`stage_librivox_dialects.py` seeds those fields on upload.

---

## SHIP tier

### 1. LibriVox "Dialect and Accent" collections ← **wired up, 55 clips staged**
The only free corpus I found where English speakers are **explicitly labelled by US region**.
20 US readers across two volumes: Texas metro, North Texas, Texas, NYC, Upstate NY, South
Carolina, South Louisiana, SE Pennsylvania, W. Central PA, Southern Indiana, SoCal, Pacific
NW, Great Lakes, Kansas, Minnesota, Midwestern ×3, "western", "Air Force brat". Plus 35
international readers. Each reads the same short fable for 50–85 s.

- Vol 1: <https://archive.org/details/dialect_accent_0909_librivox> (PD)
- Vol 2: <https://archive.org/details/celebration_dialects_accents_vol2_1312_librivox> (PD Mark 1.0)
- Licence: **public domain.** LibriVox's own policy — *"LibriVox recordings are in the public
  domain… there is no need to credit LibriVox"* (<https://librivox.org/pages/public-domain/>).
- Verdict: **SHIP.** Cleanest footing available — volunteers who published deliberately into
  the public domain. The catch is quality: home-recorded MP3, variable room noise. The
  staging script scores each clip so you audition the clean ones first.
- Pull with: `python3 scripts/stage_librivox_dialects.py --region us`

### 2. Hi-Fi TTS — the fidelity tier
10 speakers, **44.1 kHz, ≥32 dB SNR, ≥17 h each**, LibriVox-sourced audiobook read speech.
Best raw audio quality of any free multi-speaker corpus. Not accent-labelled and only 10
voices — use it for narrator-grade references, not variety.
- <https://www.openslr.org/109/> · HF `MikhailT/hifi-tts` · **CC BY 4.0** → SHIP (attribute).

### 3. LibriTTS-R — the volume tier
24 kHz, ~585 h, ~2,400 speakers, Miipher speech-restored. No accent metadata, but the reader
pool is LibriVox, so it skews heavily American. Filter `train-clean-360` for 12–20 s
utterances and sample by speaker.
- <https://www.openslr.org/141/> · HF `mythicinfinity/libritts_r` · **CC BY 4.0** → SHIP.
- This is the "I need 200 distinct American voices" answer, at the cost of not knowing which
  region any of them is from.

### 4. VCTK — what you already have
110 speakers, accent-labelled, CC BY 4.0 → SHIP. Keep it; just stop expecting American range
from it.
- HF `CSTR-Edinburgh/vctk` · already wired via `scripts/stage_vctk_voices.py`.

### 5. Synthetic voice design — the consent-free option
Generate a voice from a text description, then feed that **synthetic** output to Chatterbox
as the clone reference. No real person exists, so right-of-publicity never attaches.
- **Qwen3-TTS VoiceDesign** — HF `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, **Apache 2.0**, no
  restriction on generated audio at all. Best licence of anything on this page.
- ⚠️ **Accent is not a controllable dimension.** It defaults toward standard American/English
  and is unreliable for regional dialects. So: synthetic for *demographic* variety (age,
  pitch, timbre, texture), real recordings for *accent* authenticity.
- ElevenLabs Voice Design handles accent better, but free-tier output is non-commercial and
  the ToU grants a broad licence back — fine for experiments, not for shipped inventory.
- Precedent worth knowing: the `devnen/Chatterbox-TTS-Server` you run already ships a
  `./voices` directory of **synthetic** curated voices. This approach is what's in production
  under you right now.

---

## PRIVATE tier — your box only, never in a release

| Source | What it gives | Licence |
|---|---|---|
| **CORAAL** — <https://lingtools.uoregon.edu/coraal/> (HF `zsayers/CORAAL`) | 220+ African American Language speakers across Atlanta, DC, Detroit, LA, Princeville NC, Providence, Rochester, Valdosta. The best AAVE regional coverage that exists — and a real gap in your bank. | **CC BY-NC-SA 4.0**, some components carry extra terms. Also sociolinguistic *interviews*: crosstalk, interviewer bleed, room noise. Usable but needs careful cutting. |
| **Speech Accent Archive** — <https://accent.gmu.edu/> | Thousands of speakers with birthplace metadata, all reading the same phonetically-loaded paragraph ("Please call Stella…") for ~20–30 s — ideal clip length, enormous US coverage. | **CC BY-NC-SA.** The SA is the real problem: it would virally relicense anything derived from it. |
| **EARS** — <https://sp-uhh.github.io/ears_dataset/> | 107 speakers, **48 kHz anechoic**, 22 emotional styles. Technically the best-engineered option anywhere. | **CC-NC 4.0.** Painful — this is the one you'd most want to ship. |
| **Expresso** — HF `ylacombe/expresso` | 48 kHz, 26 expressive styles — good for style-matched references (see recipe below). | Only 4 speakers. **CC BY-NC 4.0.** |

---

## NEVER tier — with reasons, so nobody re-litigates them

- **IDEA / dialectsarchive.com** — the obvious-looking answer for US dialects, and a hard no.
  Their [copyright page](https://www.dialectsarchive.com/copyright-credit-information) says
  you *"may not… distribute any sound files, or portion thereof, without express written
  consent"* plus fees. All rights reserved.
- **Santa Barbara Corpus of Spoken American English** — **CC BY-ND 3.0**. No Derivatives, and
  trimming + normalising a clip *is* a derivative. Also conversational audio with crosstalk.
- **TIMIT** (<https://catalog.ldc.upenn.edu/LDC93S1>) — the canonical "8 US dialect regions"
  corpus and useless here: utterances are ~3 s (far too short), 16 kHz, LDC paywall, no
  redistribution.
- **Emilia** (`amphion/Emilia`) — scraped from in-the-wild podcasts/YouTube. Worst consent
  profile on this page. Gated, CC BY-NC 4.0.
- **GigaSpeech**, **People's Speech** (per-clip licence variation = audit nightmare),
  **VoxPopuli** (EU-accented, no US value) — skip.
- **Common Voice** US English split is a near-miss worth noting: 5,705 speakers all tagged
  `United States English`, **CC0** content — but accent granularity is national only (no US
  sub-regions), clips are ~5 s MP3, and the packaging terms say *"you agree not to rehost
  this dataset."* Usable privately; awkward to ship derived clips from.

---

## Chatterbox reference-clip recipe

From the [Resemble AI repo](https://github.com/resemble-ai/chatterbox), the
[model card](https://huggingface.co/ResembleAI/chatterbox), and the devnen server config.

**Clip spec**
- **12–15 s.** Resemble's own example file is literally named `your_10s_ref_clip.wav`;
  guidance is 6–15 s, and the model only consumes the first ~6–10 s. devnen caps at 30 s.
  Anything past ~20 s is wasted bytes. (`stage_librivox_dialects.py` defaults to 15 s.)
- **Source at 44.1/48 kHz, never upsample.** Chatterbox resamples internally and outputs at
  24 kHz — real 24 kHz beats upsampled 16 kHz, which is why Hi-Fi TTS and LibriTTS-R rank
  above 16 kHz corpora.
- **Mono WAV**, silence trimmed, and **normalise the whole bank to one loudness target**
  (the script uses −20 LUFS, two-pass linear). An inconsistent bank produces clones that
  jump in volume between characters — very audible in a book with speaker switches.

**What makes a clone work vs. fail**
- ✅ Single speaker, complete sentences, clean articulation, natural pacing.
- ✅ **Style-match the reference to the target.** *"If you want energetic speech, use an
  energetic reference."* This is the highest-leverage rule and the one people miss: cut
  NARRATOR references from calm narration and character references from expressive dialogue.
  A calm reference fighting `exaggeration=1.3` is the main cause of "this clone sounds wrong."
- ❌ Failure modes: noisy audio, clips under ~10 s, and reference/target style mismatch.

**Generation params**
- Defaults `exaggeration=0.5, cfg=0.5` for most text.
- Fast-talking reference → drop `cfg` to ~0.3 to fix pacing.
- Dramatic/high-intensity → `exaggeration ≈ 0.7+` **with `cfg ≈ 0.3`**. Higher exaggeration
  speeds speech up; lower cfg compensates.
- 📌 **`exaggeration` and `cfg_weight` are coupled.** `tag_mapper.py` currently treats
  exaggeration and speed as independent. Per Resemble, intensity should pull `cfg_weight`
  *down* rather than touching `speed_factor`. Worth a pass.
- 📌 **Pin a seed per character** in `voice_map.json`. devnen's docs are explicit that a fixed
  seed + cloning is what keeps a voice consistent across chunks — over 100 chapters that's
  the difference between a coherent cast and slow drift.

---

## Two findings that change CLAUDE.md

1. **Chatterbox-Turbo has native paralinguistic tags** — `[laugh]`, `[chuckle]`, `[cough]`,
   `[sigh]`, `[gasp]`, `[groan]`, `[sniff]`, `[clear throat]`, `[shush]` — written inline in
   the text ([Resemble README](https://github.com/resemble-ai/chatterbox)). CLAUDE.md's
   "Orpheus vs Chatterbox" tradeoff says Chatterbox has *"no structured tag system"* and
   recommends layering Orpheus for sighs and laughs. **That claim is now stale** — but read
   the tradeoff before acting on it:

   | | emotion params (`exaggeration`/`cfg`) | inline `[laugh]`-style tags |
   |---|---|---|
   | **base** (what your box runs today — `/api/model-info` reports `type: original`, `supports_paralinguistic_tags: false`) | ✅ works | ❌ none |
   | **Turbo** | ❌ silently ignored (this is what the existing Turbo guard shouts about) | ✅ works |

   So it is one or the other, not both. Staying on base is still right for ProseCast, because
   tone tags driving `exaggeration` are the whole premise. Revisit only if Resemble merges the
   two paths. If you ever do switch, the `orpheus` mapping already in `tag_mapper.py` mostly
   ports over — `[]` instead of `<>`.
2. **Chatterbox-Nano** (110M) runs ~3× realtime on 8 CPU cores with the same tags — a
   plausible replacement for the `say` fallback tier, so the UI never silently degrades to
   macOS voices again.

---

## Nobody has published a Chatterbox voice pack

I searched Hugging Face datasets/models/spaces and GitHub: there is no curated,
licence-audited, accent-labelled reference-voice pack for Chatterbox. Only two forks of a
`chatterbox-voice-studio` Space, neither of which is a corpus.

That is a real hole in the ecosystem, it is directly adjacent to the marketplace thinking in
`docs/market-research-communities-marketplaces.md`, and the LibriVox pull already built here
is most of a first release: 20 US-region-labelled public-domain voices with per-voice
provenance. Publishing it is both seed inventory and a launch story — and it costs nothing,
because the licence work is already done and recorded in `MANIFEST.json`.
