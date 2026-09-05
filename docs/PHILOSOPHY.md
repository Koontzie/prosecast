# What ProseCast is for, and what it won't do

This page is the long answer to two questions a stranger reasonably asks of a
tool that clones voices and reads books aloud: *whose books?* and *whose
voices?*

## Your book, your machine

ProseCast is local-first because the alternative is not acceptable for a
book. You upload nothing. The file you add is parsed on your computer, the
voices are synthesized by services you run, and the only network calls
ProseCast makes are to the addresses you typed into its Setup page. There is
no account, no telemetry, no "improve the product by sharing usage data"
checkbox to untick. If you delete the folder, it is gone.

That design is also the legal shape of the thing. ProseCast is for books you
own, read to you privately: the paperback you bought and would rather listen
to while driving; the out-of-print title nobody will ever record; the
rulebook you need in your ears while your hands are busy; a book your eyes
can no longer manage. Making a personal audio rendition of a work you hold a
copy of, for yourself, is the use this is built for. Distributing generated
audio of a work you don't hold the rights to is not, and nothing here helps
you do it.

## Who's speaking is a fact about the text, not about the tool

The heart of ProseCast is not synthesis. It is the layer above it: working
out who says each line, letting you cast the characters, and letting you fix
the tool when it is wrong. Roughly nine lines in ten are settled by rules —
dialogue tags, name recognition, turn-taking — with no AI involved. A local
language model reads the hard scenes for the rest, and you correct whatever
it still gets wrong, without stopping playback.

Every correction is written to an append-only journal beside the book. That
journal is the most valuable file ProseCast produces, and it is why the
project treats it as yours: plain JSON, human-readable, never coupled to a
proprietary format. The reason it matters beyond your own library is in the
last section.

## The voice-actor question

An open tool with voice cloning in it will be asked whether it takes work
from narrators. The honest answer is not "it doesn't"; the honest answer is
where the project stands and what it refuses to do.

**Provenance.** ProseCast ships no voice recordings of any kind. The
predefined voices belong to the TTS server you run; the reference clips you
add for cloning are yours. The project keeps a written account of where
consent-clean reference audio can come from —
[voice-sources.md](voice-sources.md) — and sorts sources into three tiers:
public-domain and CC-BY material recorded for redistribution, or synthetic
voices with no real person behind them, can be shipped; research-only and
non-commercial corpora stay on a private machine; anything scraped from the
wild is not built on at all. That document also explains why a Creative
Commons license on a dataset is not the same thing as a person's consent to
have their voice cloned. They are separate, and only one of them is settled
by a dataset card.

**Consent.** The rule is: no cloning without the speaker's consent. If you
add a reference clip of someone, you are saying you have their permission to
make a voice from it and to use that voice this way. ProseCast can't verify
that from inside your computer, and it doesn't pretend to. It states the rule
and builds the rest of the design around it — which is why any future way of
*sharing* voices starts with a consent record rather than an upload button.

**Direction.** The part of the design that would turn narrators from the
people a tool replaces into the people a tool credits and pays is the
exchange described below. It is a direction, not a feature. Nothing about it
exists in the code today, and this page will be updated when that changes.

## Sharing casts and voices — how it would work

An exchange: people sharing the work of casting a book, with credit
attached, the way ComfyUI nodes and Ollama's model library began — a
community folder with a naming convention and a README, no payment rails.

**A cast is two small files, and neither contains the book.** On disk, a
finished cast is `voice_map.json` (character → voice) and
`corrections.jsonl` (the speaker fixes you made). A cast for a novel can be
shared without sharing a sentence of the novel, which is what makes sharing
it legal. The parsed text never leaves your machine.

**Importing one** would work like this: you add your own copy of the book;
ProseCast identifies it (title and author today, ISBN where the file carries
one) and looks for a matching cast — in a community repo, or a file someone
sent you. The corrections land on the matching lines *before* the AI pass
runs, so the hard scenes arrive already solved. The voice map casts the
characters, and where it names a voice you don't have, the cast panel says so
and lets you pick a substitute or fetch the pack. One thing has to change
first: today corrections are keyed by line number, which depends on how the
file was parsed; shared corrections will be keyed by a short hash of the
line's text instead, so a different edition still matches. Small change,
made before the first cast is shared, not after.

**A voice pack** is reference clips plus a manifest: who the speaker is, what
they consented to, which license tier the recording falls in, a credit line,
and, if they want one, a link where they get paid. A pack without a consent
record does not get listed. That manifest is the whole mechanism by which a
voice actor becomes someone this tool credits — and it is a JSON file and a
folder convention, not a platform.

**The order it would happen in**, each step useful on its own: casts for
public-domain books first, because there is nothing to argue about; then
voice packs with consent manifests; then ratings and credit for the people
who contribute corrections and casts; and only after all of that, and only if
the free tool has found an audience, any layer where money moves. If that
layer is ever built, the research behind it
([market-research-communities-marketplaces.md](market-research-communities-marketplaces.md))
already sets the floor: consent verified before listing, usage-metered
royalties with published rate math, and a creator share that never drops
below half.

## What is free, and what is not

The local tier is the product. A whole book can be narrated on Chatterbox,
on your own hardware, without paying anyone, and that will stay true.
ElevenLabs is an optional upgrade some people will want for a few hero
characters; it is your account and your bill, and ProseCast never marks it
up. If a referral arrangement exists, it is disclosed next to the link, in
plain words, every time. Support for the project is a coffee, never a gate.

## The one promise

ProseCast will never require your book, your corrections, or your voices to
leave your machine in order to work. Everything else on this page is how the
project tries to be worth trusting with them.
