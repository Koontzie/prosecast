# Market Research — Community + Marketplace Platforms (2026-07-03)

Research for ProseCast's long-term model: local free-to-premium app + marketplace where
VO artists offer cloned voices for books/PDFs, community castings/tags/corrections,
coin economy. Sources inline.

> **Direction update (2026-07-10).** ProseCast is *not* going to run its own premium render
> economy or payment rails. The model is the AnimaForge one: a **complete free local tier**
> (Chatterbox — free forever, not a crippled trial), and for higher-quality cloud voices the
> user brings their **own ElevenLabs account / API key** (affiliate referral, no markup, we
> never touch their money — see `elevenlabs-setup.md`). The marketplace / royalty / coin
> research below is **preserved as moonshot thinking, not the near-term plan.** Read the
> "Monetization spine" note in the Synthesis with that reframe in mind.

## 1. Voice/audio marketplaces

### ElevenLabs Voice Library — the closest existing model
- VO artists upload a Professional Voice Clone, opt into the library, earn whenever
  **paid** users generate with it (free-tier usage pays $0). Default ≈ **$0.03 per 1,000
  characters generated**, weekly Stripe payouts, $10 minimum.
  [help.elevenlabs.io](https://help.elevenlabs.io/hc/en-us/articles/22976234546705-What-are-Voice-Actor-Payouts) · [elevenlabs.io/payouts](https://elevenlabs.io/payouts)
- Creator controls: reward type (cash vs credits), permitted use cases, and a **notice
  period up to 2 years** — voice stays usable that long after withdrawal; longer notice =
  higher rate. [VLA addendum](https://elevenlabs.io/vla)
- Scale: ~$2M to ~5,000 voices by Apr 2025 → **$22M cumulative, 10,400+ earning creators
  by mid-2026**. [blog](https://elevenlabs.io/blog/22-million-earned-by-voice-creators-on-elevenlabs)
- Nov 2025 "Iconic Voice Marketplace" (celebrity/estate licensing) drew consent praise +
  displacement backlash (Saga Communications replaced VO across 113 radio stations, Jul 2025).
  [Radio World](https://www.radioworld.com/columns-and-views/guest-commentaries/elevenlabs-launches-ai-voice-licensing-marketplace)
- **Copy:** usage-metered royalty, creator-set use restrictions, notice-period mechanic
  (protects buyers of long-form audiobooks from voices vanishing mid-series).
  **Avoid:** opaque flat rates; silence about free-tier paying nothing.

### The rest of the VO field
- **Voices.com**: memberships + **20% commission** on managed jobs — resented double-dipping.
- **Voice123**: subscription-only ($49–$4,950/yr), 0% commission, but pay-to-play
  (150+ auditions without booking common complaint). [Trustpilot](https://www.trustpilot.com/review/voice123.com)
- **Fiverr**: flat 20% seller cut, 14-day holds; where Lovo covertly sourced the
  recordings behind the landmark cloning lawsuit.
- **ACX/Audible royalty share**: narrator-takes-royalty is a proven "VO artist earns per
  book" structure. New model May 2026: **50% exclusive / 30% non-exclusive**.
  [ACX](https://help.acx.com/s/article/audible-s-new-royalty-model)
- **Casting Call Club**: free for talent, monetizes creator premium features — beloved
  because talent never pays to audition. [castingcall.club](https://www.castingcall.club/)
- **Pattern to avoid across the board:** talent paying before earning is the most-hated
  model in VO.

## 2. Community + marketplace hybrids

- **Nexus Mods Donation Points** — best precedent for the coin economy. Platform funds a
  monthly pool (~$325k) distributed by engagement; points redeem for cash/games/charity.
  Content stays free; money comes from platform revenue. Trust leak: secret allocation
  algorithm. [nexusmods.com/about/donation-points](https://www.nexusmods.com/about/donation-points)
- **Steam paid mods (2015)** — canonical failure: creators got **25%**, community revolt
  killed it in a week. Lessons: never paywall a previously-free community layer; creator
  share must be visibly majority. [history](https://www.voletic.com/p/rise-fall-steam-paid-mods)
- **itch.io** — seller chooses the platform's cut (0–100%, default ~10%); enormous
  goodwill; PWYW buyers average ~30% above minimum. [itch.io](https://itch.io/updates/introducing-open-revenue-sharing)
- **Gumroad vs Etsy** — Gumroad flat 10% (30% marketplace-discovery); Etsy's stacked fees
  (effective 12–20%, unavoidable offsite-ads fee) are a chronic grievance. Avoid fee stacking.
- **Chub/character-card communities** — proof that shareable AI config files (≈ ProseCast
  casts) sustain huge libraries with ratings, tags, usage-count sorting.
- **Audiobookshelf** — thriving self-hosted audiobook ecosystem; its users are exactly
  ProseCast's local-first early adopters. Cheap goodwill: export M4B/renders into ABS
  libraries cleanly. [GitHub](https://github.com/advplyr/audiobookshelf)

## 3. Community correction/cataloging models

- **MusicBrainz** — edit queue + voting; votes required scale *inversely* with editor
  reputation (trusted editors auto-apply). Directly applicable to shared attribution
  corrections. [wiki](https://musicbrainz.org/doc/How_to_Contribute)
- **SponsorBlock** — nearest analog to per-block corrections on media: anonymous IDs
  accrue reputation, votes weight which overlapping submission gets served, new
  submissions still surface for validation. **Copy this architecture** for community
  speaker corrections keyed to book hash + block ID.
  [design writeup](https://blog.ajay.app/voting-and-pseudo-randomness-or-sponsorblock-or-youtube-sponsorship-segment-blocker/)
- **Goodreads Librarians** — gated volunteer tier (pass a test → catalog edit rights);
  status/badges alone sustain contribution. The correction layer may not need money at all.

## 4. Legal/consent — table stakes for a voice-clone marketplace

- **Lehrman & Sage v. Lovo** (SDNY, Jul 2025): actors recorded via Fiverr "for test
  purposes," clones sold commercially. Voice isn't copyrightable, but NY right-of-publicity
  + contract claims proceed. Consent must be explicit, written, use-case-bounded.
  [Skadden](https://www.skadden.com/insights/publications/2025/07/new-york-court-tackles-the-legality-of-ai-voice-cloning)
- **ELVIS Act** (TN, 2024): first state law explicitly covering AI voice simulation;
  reaches *platforms* whose primary purpose is unauthorized cloning. State patchwork growing.
- **NO FAKES Act**: Senate Judiciary unanimously advanced S.4591 on **2026-06-18** — a
  federal digital-replica right with platform takedown duties is likely coming.
  [Congress.gov](https://www.congress.gov/bill/119th-congress/house-bill/2794/text)
- **Design implications (build in from day one):** verified-identity onboarding with
  recorded consent statement (ElevenLabs PVC pattern), scoped per-use licenses
  (audiobook-only, per-book or per-render), takedown + notice-period machinery,
  provenance metadata on every render.

## Synthesis — the ProseCast model

1. **Monetization spine (revised 2026-07-10):** near-term there is **no ProseCast-run
   payment economy.** Free tier = local Chatterbox, complete and free forever. Higher-quality
   voices = the user's **own ElevenLabs key** (affiliate/referral, no markup); ProseCast never
   processes render payments. Being upfront about the referral *is* the pitch, not a footnote.
   *Moonshot only —* if ProseCast ever runs its own voice marketplace, the research below
   holds: usage-metered royalties (per rendered hour/character), creator share ≥50% (Steam's
   25% is the proven failure line; ACX moved to 50%), *published* rate math, creator-set
   restrictions + notice periods. Don't build a payment rail before the free tier has an
   audience.
2. **Community spine:** participation is always free (Casting Call Club). Corrections
   use SponsorBlock-style vote-weighting + MusicBrainz reputation-scaled auto-approval.
   Casts get Chub-style ratings/usage counts. A gated librarian tier handles catalog
   merges. Coins earned from corrections/casts spend on premium renders (Nexus DP proves
   points→perks works when funded from platform revenue).
3. **Legal:** consent verification + scoped licensing is now mandatory (Lovo, ELVIS,
   NO FAKES) — and a marketing differentiator: "every voice here is consented and paid."
4. **Already-safe architecture calls:** exportable human-readable IR/corrections (the
   marketplace constraint in CLAUDE.md) and the local-first free tier are exactly what
   the Audiobookshelf-style community expects. No changes needed to current direction.

---

# Part 2 — Community-Driven Sites: CCC, Reddit, Forums (added 2026-07-03)

## Casting Call Club deep dive

- Entry-level marketplace for indie creators ↔ voice actors (games, fan dubs, audio
  dramas). Explicitly not competing with Fiverr/Upwork — "for the long-tail of creators."
  ~28,700 Discord members; essentially a one-person company.
  [castingcall.club](https://www.castingcall.club/) · [pricing](https://www.castingcall.club/pricing)
- **Free to audition** (its core differentiator vs Voices.com/Voice123). Most projects
  unpaid/credit-only; paid listings flagged, with instant alerts as a premium hook.
- Tiers: Free → Apprentice $6/mo → Maker $8/mo → Business $12/mo (annual pricing).
  Includes **cccCoins** virtual currency — direct analog to ProseCast's planned coins.
- Reputation = achievements, completed-role credits, followers, audition analytics.
- Sentiment: great for beginners building reels; pros outgrow it (unpaid work, projects
  that never ship). [Trustpilot 3.4](https://www.trustpilot.com/review/castingcall.club)
- **ProseCast angle: recruit, don't partner.** CCC's audition-hungry semi-pros are the
  voice-pack talent pool — recurring royalty income beats CCC's unpaid-credits norm.
  ⚠️ Adjacent Voice Acting Club **bans AI-training casting calls outright**
  ([rules](https://voiceactingclub.com/ccrules/)) — any recruiting pitch must lead with
  consent + per-use compensation.

## Reddit / forum landscape (mid-2026 sizes)

| Community | Size / growth | Fit / posture |
|---|---|---|
| r/audiobooks | 338k, +17%/yr | Core listeners; rec-request culture; multi-voice ("graphic audio") is polarizing even pre-AI. Cautious self-promo (Promotion flair exists; indie apps have been celebrated). |
| r/audiodrama | 289k | Full-cast-native audience. Cautious. |
| r/VoiceActing | 118k | Talent pool; **high AI hostility — never announce here.** |
| r/recordthis | 24k | Free VO requests — the "human tier" pipeline for casts. Hostile to AI pitches. |
| r/selfhosted | ~792k | Local-first IS the pitch; self-promo allowed if relevant (9:1 rule). **Friendly.** |
| r/audiobookshelf (+Discord) | 16k, **+91%/yr** | Fastest-growing niche here; natural integration target. **Friendly.** |
| r/LocalLLaMA | 764k | TTS releases routinely front-page; ship code, not marketing. **Friendly.** |
| r/litrpg | 143k, +37%/yr | Tyler's test genre; underserved by human narration economics. Cautious. |
| r/Fantasy | 3.9M | Strictly no self-promo. |
| MobileRead forums | ~261k members | Calibre-adjacent tinkerers; active "Audiobooks & AI" thread. Friendly. |

**AI-displacement sentiment (characterize accurately):** NAVA's 2025 survey (1,305
responses) — ~15% of VO actors already lost work to synthetic voices
([navavoices.org](https://navavoices.org/voiceover-survey-2025/)). Canonical grievances:
Lovo (non-consensual cloning) and Apex Legends' French cast resigning over forced
AI-training clauses. Listener willingness to try AI narration slipped 77%→70% even as
AI titles grew 1,600→40,000+ ([Twin Flames Studios](https://twinflamesstudios.com/the-state-of-ai-audiobooks-in-2025/)).
The objection is consent + buyouts-instead-of-royalties — exactly what ProseCast's
model fixes. In VO spaces, let a VO partner tell that story, not the developer.

## Community mechanics → product features

**Translate well:**
- Flair → **provenance badges on casts**: "Human-narrated," "Hybrid," "AI-tagged,
  human-corrected" — defuses the AI-disclosure fight r/audiobooks keeps having.
- Karma → **correction reputation**: weight corrections by track record; earned trust
  gates powers (merge approvals), Stack Overflow-style — not cosmetic points.
- Mod curation → **featured casts** (editor picks beat raw vote sorting).
- Wiki → **per-book cast pages** (canonical character/voice notes, community-maintained).
- Weekly threads → **"cast this book" request board** (mirrors r/audiobooks' dominant behavior).
- Discord roles → engine-tier roles; stage events as cast-release listening parties.

**Failure modes:**
- Reddit killed blockchain Community Points (2023): speculation, regulatory exposure,
  86% crash ([TechCrunch](https://techcrunch.com/2023/10/17/reddit-is-phasing-out-community-points-blockchain-rewards/)).
  **ProseCast coins must be earn-and-spend utility only — never tradable/cash-out** —
  or they become a farming target and a securities question. (VO artist payouts are
  separate real money via the royalty rail, not coins.)
- Points-for-posts gamification produces low-quality volume. Reward **accepted**
  (peer-validated) corrections, not submissions.

## Go-to-market sequencing

Talent: CCC + r/recordthis via consent-first paid cloning. Early users: r/selfhosted,
r/audiobookshelf, r/LocalLLaMA (lead with local-first + ABS integration). Listeners:
r/audiobooks, r/litrpg later. VO spaces: earn presence through the royalty model itself;
never launch-announce.
