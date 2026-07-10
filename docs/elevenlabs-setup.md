# Using premium voices (ElevenLabs) — setup guide

**What this is:** the easy hand-off for people who want higher-quality cloud voices. Written
2026-07-10. Same model as AnimaForge: the free local option is complete on its own, and
ElevenLabs is an *optional* upgrade you set up with your **own** account. Doubles as the copy
that will front the in-app "key box"; works today via `.env` (see step 3).

---

## First, the honest part

ProseCast's built-in voice engine (**Chatterbox**, local) is free, runs on your own machine,
and is the default. It is *not* a crippled trial — a full book can be narrated on it start to
finish without paying anyone. You only need this guide if you want ElevenLabs' cloud voices for
certain characters or shorter pieces.

**ElevenLabs is your account, not ours.** You sign up with ElevenLabs, you pay ElevenLabs
directly for credits, and ProseCast never touches your money or marks anything up. If you sign
up through our link we may get a small referral from ElevenLabs — it costs you nothing extra,
and we'd rather say that out loud than bury it.

---

## Heads up before you start: a full book is a real bill

ElevenLabs charges by the character (roughly **1 character = 1 credit**; about half that on
their Turbo/Flash models). A typical 100,000-word novel is **~550,000 characters** — so
narrating a whole book on ElevenLabs can eat an entire month of a paid plan:

| Plan | Price/mo | Credits | Rough full-book capacity |
|---|---|---|---|
| Free | $0 | 10,000 | a few minutes — testing only |
| Starter | $6 | 30,000 | a short story |
| Creator | $22 | 121,000 | ~a quarter of a novel |
| Pro | $99 | 600,000 | ~one full novel |

*(Prices/credits current as of 2026-07 — check the live page, they move.)*

**The sane pattern:** render the whole book on **local Chatterbox** (free), and reserve
ElevenLabs for the handful of *hero characters* where the extra quality earns its cost, or for
short works. Don't point a 115-chapter batch render at ElevenLabs unless you mean to pay for it.

---

## Setup — step by step

**1. Make an ElevenLabs account.**
Go to [elevenlabs.io](https://elevenlabs.io), sign up (the free tier is enough to test), and
pick a paid plan only once you know you want the quality. Commercial-use rights start at the
Starter plan.

**2. Copy your API key.**
In ElevenLabs, open your profile → **API Keys** (or Settings → API), create a key, and copy it.
Treat it like a password — anyone with it can spend your credits.

**Checkpoint — look at what you copied.** It should be a long opaque string. If it's blank or
looks truncated, regenerate it before continuing.

**3. Give the key to ProseCast.**

*Today (dev):* put it in the project's `.env` file:

```
ELEVENLABS_API_KEY=your_key_here
```

Then restart the server. On startup you'll see an ElevenLabs connection check — look for
`[ElevenLabs] Connection OK ✓`. If you see `No API key found` or an HTTP error, the key isn't
being read (wrong file, typo, or the server didn't restart).

*Later (shipped app):* this same key goes in the in-app **key box** under voice settings —
paste, save, done. No file editing. The box will link back to this guide.

**4. Cast a character to an ElevenLabs voice.**
Once the key is live, ElevenLabs voices appear in the voices panel. Assign one to a character,
preview it on a real line from the book, and render. If no key is present, ProseCast quietly
falls back to the free local engine — nothing breaks, you just don't get the cloud voice.

---

## Your content, your responsibility

ProseCast is a tool that narrates the text *you* provide. You're responsible for having the
right to use the books you load, and your use of ElevenLabs is governed by ElevenLabs' own
terms under your own account. (See the project's general disclaimer for the full framing.)

---

## Quick reference

- Free/default engine: **Chatterbox**, local, no account, no cost.
- ElevenLabs: **optional**, your account, you pay them directly, we don't mark up.
- Key location: `.env` → `ELEVENLABS_API_KEY` today; in-app key box later.
- Startup confirms it: `[ElevenLabs] Connection OK ✓`.
- Full-book renders → use local. ElevenLabs → hero voices / short pieces.
- Live pricing: [elevenlabs.io/pricing](https://elevenlabs.io/pricing).
