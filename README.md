<p align="center">
  <img src="docs/assets/prosecast-banner.png" alt="ProseCast — full-cast audiobooks from the books you own" width="800">
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: GPL-3.0" src="https://img.shields.io/badge/license-GPL--3.0-cd9a43?style=flat-square"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-cd9a43?style=flat-square">
  <img alt="Runs locally" src="https://img.shields.io/badge/runs-100%25%20local-63b3a0?style=flat-square">
  <img alt="EPUB · PDF · TXT" src="https://img.shields.io/badge/reads-EPUB%20%C2%B7%20PDF%20%C2%B7%20TXT-cdbb97?style=flat-square">
  <a href="https://ko-fi.com/tylerxkoontz"><img alt="Ko-fi" src="https://img.shields.io/badge/ko--fi-buy%20me%20a%20coffee-d8503a?style=flat-square"></a>
</p>

**Turn a book you own into a full-cast audiobook, on your own machine.**
ProseCast reads an EPUB, PDF or text file, works out who is speaking on every
line, lets you cast a different voice for each character, and performs the
book with local text-to-speech. Your book never leaves your computer. There is
no account, no upload, no telemetry — the only network calls are to services
you run yourself.

It is a public repo you clone and run, not a packaged app. If you already run
Ollama or a local TTS server, you are the person this was written for.

> **Status (September 2026):** works end to end for novels, plays and
> rulebooks, including scanned PDFs. Used daily by one person. Every step is
> in the browser — adding a book, the AI "who's speaking" pass, casting,
> rendering, read-along timing, export. See
> [Where it is](#%EF%B8%8F-where-it-is) before you decide it is for you.

---

## 📖 What it actually does

1. **Reads the book.** EPUB, TXT, or PDF. Born-digital PDFs get chapter
   detection from bookmarks, the printed contents page, or heading sizes, and
   you review the split before anything runs. Scans are read with OCR.
2. **Works out who is speaking.** A rule-based pass (dialogue tags, name
   recognition, turn-taking) settles roughly nine lines in ten with no AI at
   all. A local language model reads the hard scenes for the rest.
3. **You cast it.** One voice per character, previewed on the character's own
   lines. Or let auto-cast handle the crowd and hand-pick the leads.
4. **Your computer performs it.** Chapter by chapter, resumable, cached — fix
   one speaker and only that line re-renders.
5. **You correct it while listening.** Wrong voice on a line? Tap the speaker
   name mid-playback, reassign, keep listening. Every correction is journaled,
   because it is also the training data for a better attribution model later.
6. **Read along, export, take it with you.** A full-page reader with the
   words lighting up as they are spoken; a chapterized `.m4b` for your phone.

What it is not: a one-click "convert this file to audio" tool. Those exist
(see [ebook2audiobook](https://github.com/DrewThomasson/ebook2audiobook) for a
good one). ProseCast's whole reason to exist is the layer above synthesis —
casting, correction and directorial control — and it treats voice quality as
something you bring.

*(A 90-second clip of the reader goes here. Not recorded yet.)*

---

## 🎙️ Why not just hire a narrator?

You should, when you can. A professional full-cast recording is the best
version of any book, and it costs what skilled people cost — thousands of
dollars and weeks of studio time. Most books will never get one: the indie
novel with forty readers, the 650-page rulebook, the play a cast needs to
hear before rehearsal, the out-of-print paperback, the manuscript you are
still writing. ProseCast is for the books that would otherwise stay silent,
and for the author who wants to hear an audiobook of their own work before
deciding whether to pay for a real one.

It is also an accessibility tool. Plenty of people cannot read a page of
text the way it was printed — low vision, dyslexia, fatigue, a brain injury,
or just eyes that are done for the day — and a flat screen-reader voice
turns a novel into a manual. A performed version, with a different voice for
each character and the words lighting up as they are spoken, is the
difference between "I can technically access this book" and actually
enjoying it.

What it refuses to do: ship anyone's voice, or clone one without the
speaker's consent. The voices come from the TTS server you run; the
reference clips are yours. The direction the project is heading — where
narrators and voice actors publish voice and casting packs, get credited,
and charge for them if they want to — is written up in
[docs/PHILOSOPHY.md](docs/PHILOSOPHY.md). It is a direction, not a feature,
and that document says so plainly.

---

## 🪜 Which rung are you on?

ProseCast is built as a ladder. Every rung works on its own; each one up
sounds better or thinks harder.

| Rung | Hardware | Voices | "Who's speaking" | What to expect |
|---|---|---|---|---|
| **1 — Try it** | Any Mac, or any machine with `piper` | macOS system voices / Piper (CPU) | rules only | Robotic but real multi-voice — the setup wizard ends by reading you the sample book. The "does this work at all" rung. |
| **2 — Sounds like a book** | A GPU with 8–12 GB of VRAM, in this machine or one across the room | **Chatterbox** (local, free, voice cloning) | rules only, or a small Ollama model | Audiobook-grade narration. Slower on smaller cards. |
| **3 — Thinks too** | Same GPU with headroom, or a second box | Chatterbox | **Ollama** (`gemma3:12b`) + **faster-whisper** for read-along | The full experience: hard scenes attributed by AI, words lighting up as they are read. This is the reference setup. |
| **BYO key** | Anything | Your own **ElevenLabs** account for a few hero characters | as above | Premium voices where they earn their cost. A whole book on ElevenLabs is a real bill — see below. |

You do not pick a rung up front. Install rung 1, let the setup wizard get you
listening, and add services as you go; on the Setup page (⚙) each row turns
green as its service appears.

---

## 🔧 Install

**You need:** Python 3.11 or newer, `git`, and `ffmpeg` (required — it makes
the `.m4b` and preps voice clips). `tesseract` only if you have scanned PDFs.
Poppler is *not* needed.

```bash
# macOS
brew install python ffmpeg          # + tesseract if you have scans
# Debian / Ubuntu
sudo apt install python3 python3-venv ffmpeg   # + tesseract-ocr
```

**Windows:** ProseCast is developed on macOS and Linux and has not been tested
natively on Windows. The known-good path is **WSL2** (Ubuntu), which makes it
the Linux install above. The macOS `say` engine does not exist on Windows, so
your rung-1 voice engine is Piper. Reports welcome in Issues.

### Rung 1 — get it running

```bash
git clone https://github.com/Koontzie/prosecast.git
cd prosecast
bash SETUP.sh
```

`SETUP.sh` creates a virtualenv, installs the Python dependencies, downloads
the spaCy English model *and checks that it loads*, creates `config.json` from
the example if you don't have one, checks for `ffmpeg`, and runs a silent
smoke test of the whole pipeline. Every step prints a ✓ or tells you exactly
what to install. It is safe to re-run.

Then start the app:

```bash
.venv/bin/uvicorn server:app --port 8000
```

Open <http://localhost:8000>. On first run it opens a **short setup wizard**:
pick a voice engine (on a Mac, system voices are already selected and need
nothing installed), let it check that the engine answers, skip the optional AI
services, and press **▶ Read me the sample** — it adds the two-chapter sample
book, renders the first chapter and plays it. That is the whole first run: no
terminal, no README.

The wizard appears until you have picked an engine — having a `config.json`
is not the test, because `SETUP.sh` writes one before you have chosen
anything. Once an engine is chosen it stays out of your way; press
**↻ Run setup again** on the Setup page any time you want it back.

**How you know it worked:** you heard it. After that, click **+ Add Book**,
drop in an EPUB, answer "novel, single narrator, or play?", and render
chapter 1: the chapter list shows a rendered duration, play works, and the
speaker name changes as the voices change. On a Mac all of that happens with
no other services installed.

The **Setup page** (⚙ in the header) is the full list: one row per service,
green / amber / red, each with the command that fixes it.

Not on a Mac? Install [Piper](https://github.com/rhasspy/piper), make sure
`piper` is on your `PATH`, and set `"tts_engine": "piper"` in `config.json`
(or pick it on the Setup page).

### Rung 2 — Chatterbox voices

Chatterbox is a separate server you run, on this machine or any machine you
can reach. ProseCast talks to
[devnen/Chatterbox-TTS-Server](https://github.com/devnen/Chatterbox-TTS-Server);
follow that project's own install instructions.

Two things to get right, both of which the Setup page checks for you:

- **Load the base model, not Turbo.** The Turbo variant ignores the
  `exaggeration` control, which is how ProseCast's emotion tags shape delivery.
  On Turbo every line comes out flat and nothing tells you why — except the
  Setup page, which warns loudly when it sees `"type": "turbo"`.
- **Give ProseCast the URL** — `http://localhost:8101` if it's on this
  machine, or the other machine's address — in the Setup page or as
  `"chatterbox_url"` in `config.json`, and set `"tts_engine": "chatterbox"`.

**How you know it worked:** the Voices row on Setup goes green and reports the
model and the number of predefined voices (40 at the time of writing). Open a
book's cast panel and voices have previews.

Chatterbox can clone a voice from a short reference clip. ProseCast ships **no
voice recordings** of any kind; the clips you add are yours, and the policy
is *no cloning without the speaker's consent* — see
[docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) and
[docs/voice-sources.md](docs/voice-sources.md) for where consent-clean
reference audio comes from.

### Rung 3 — the AI passes

**Who's speaking (Ollama).** Pull the model and point ProseCast at the server:

```bash
ollama pull gemma3:12b
```

Set `"ollama_url"` (default `http://localhost:11434`) and `"ollama_model"` in
`config.json` or on the Setup page. The Ollama row goes green and lists the
models it can see; amber means the server is up but the configured model
isn't pulled.

**Read-along timing (faster-whisper).** Any server that speaks the
OpenAI-compatible `POST /v1/audio/transcriptions` works —
[Speaches / faster-whisper-server](https://github.com/speaches-ai/speaches)
is what this was built against. Set `"whisper_url"` (default
`http://localhost:8100`). This one is optional: without it the reader
highlights by sentence estimate instead of by word.

**How you know it worked:** open a book and look at the **Pipeline card**
above the chapter list. *Rules → AI pass → Cast → Render → Align → Export*,
each one green when it is done. **▶ Run AI pass** is enabled with a scope to
pick and a count of the lines it would review; **Align** says how many
chapters need timings, and the card tells you that alignment now happens by
itself after every render. If either service is down the button is disabled
and says why, with a link straight to Setup — it never quietly does nothing.

Per chapter, the list shows **words ✓** once its timings match its audio, and
the reader lights up words individually rather than a sentence at a time.

Both passes are still available from the terminal if you prefer it — see
`main.py --help` and `scripts/align_words.py` — but nothing requires it.

---

## ⚙️ `config.json`

One file at the project root, created for you by `SETUP.sh` from
`config.example.json`. It is gitignored, so your URLs and keys stay local. The
Setup page edits the same file; environment variables
(`CHATTERBOX_URL`, `PROSECAST_OLLAMA_URL`, `ELEVENLABS_API_KEY`, …) override it.

| Key | What it is | Default |
|---|---|---|
| `tts_engine` | `auto` · `chatterbox` · `piper` · `say` · `elevenlabs` · `gtts` · `stub` | `auto` — nothing chosen, so the setup wizard asks |
| `chatterbox_url` | Chatterbox-TTS-Server base URL | `http://localhost:8101` |
| `ollama_url` / `ollama_model` | Ollama server and the model for attribution | `http://localhost:11434` / `gemma3:12b` |
| `whisper_url` / `whisper_model` | Transcription server for read-along timing | `http://localhost:8100` / `Systran/faster-whisper-small` |
| `elevenlabs_api_key` | Your own ElevenLabs key, if you use it | empty |

Delete the file and ProseCast falls back to looking for everything on
`localhost`.

**Heads up if anything runs on another machine:** the app binds to the
address `uvicorn` is given. If you open it from your phone, the server is
reachable beyond `localhost` — put it behind Tailscale or similar rather than
exposing it; there is no authentication.

---

## 🎧 Using it

- **Add a book** — `+ Add Book` takes `.epub`, `.txt`, `.pdf`. The wizard
  guesses whether it's a novel, a single-narrator work or a play, and tells
  you *why*; for PDFs it shows the detected chapter split and how much to
  trust it before it commits.
- **Cast** — the Voices panel lists every speaking character with a voice
  dropdown and a preview on that character's own lines. Delete a noisy
  "character" (a skill name the parser mistook for a person) and its lines go
  back to the narrator.
- **Render** — per chapter or the whole book. Renders queue one at a time
  (the GPU is the bottleneck), survive a restart, and cache per line.
- **Listen and correct** — the block text shows above the scrubber; click it
  or the ✎ to reassign the speaker without leaving the player.
- **Read along** — the full-page reader; the current paragraph lights up and
  dialogue is marked, by word when timings exist.
- **Export** — ⬇ Export M4B builds a chapterized audiobook from whatever
  chapters are rendered.

Everything precious about a book — its attribution, your corrections, your
cast — lives in `library/<slug>/` as plain JSON. `renders/` inside it is
disposable. Back up the rest; `scripts/backup_library.sh` is one way.

---

## ✨ ElevenLabs (optional)

The local tier is the product, not a trial: a whole book can be narrated on
Chatterbox without paying anyone. ElevenLabs is an optional upgrade for people
who want premium cloud voices on a few characters. It is **your** account and
**your** key — ProseCast never touches your money and never marks anything up.

ElevenLabs voices sound better, but today ProseCast's emotion tags do not reach them — each line is read with ElevenLabs's own interpretation, not the direction the tag pass chose. This is a known gap; see HANDOFF.md.

Know before you start: ElevenLabs charges per character, and a typical novel
is about 550,000 of them. The sane pattern is to render the book locally and
reserve ElevenLabs for the leads. Full guide, with the cost table:
[docs/elevenlabs-setup.md](docs/elevenlabs-setup.md).

**Disclosure:** ProseCast is an independent affiliate of ElevenLabs and may
receive compensation for referrals. If you sign up through
[this link](https://try.elevenlabs.io/dmylr2z8w3w9), ElevenLabs may pay us a
referral; it costs you nothing extra, and we would rather say so out loud than
bury it.

*ElevenLabs and the ElevenLabs logo are registered trademarks or trademarks of
ElevenLabs, Inc. Used with permission. ProseCast is not sponsored by, endorsed
by, or affiliated with ElevenLabs except as an independent participant in the
ElevenLabs Creator Affiliate Program.*

---

## 🗺️ Where it is

Done and used daily: EPUB/TXT/PDF ingest including scans, three reading modes,
rule-based + LLM attribution (99.8% on a 115-chapter test novel), per-character
casting with cloning, resumable whole-book renders, inline correction, the
reader view, word-level read-along, M4B export, a Setup page that probes every
service.

Next: cover art and the images already inside the book, and a way to share a
finished cast. The full plan is in
[docs/ROADMAP_PHASE_E_UI.md](docs/ROADMAP_PHASE_E_UI.md).

Known rough edges are listed honestly in [HANDOFF.md](HANDOFF.md) under
"Known-real, not yet fixed".

Tests: `.venv/bin/pytest tests/ -q` — around 230; the attribution and OCR
tests skip themselves when spaCy's model or tesseract is absent, which is
healthy, not a failure.

---

## 🛠️ How this was built

This repo keeps its process files in the open, because they are half the
story. A solo builder, working in short chapters with Claude (Cowork and
Claude Code) and an occasional outside review from Codex:

- [`CLAUDE.md`](CLAUDE.md) — the standing brief an AI session reads first.
- [`STATUS.md`](STATUS.md) — the running log, one entry per chapter of work.
- [`HANDOFF.md`](HANDOFF.md) — the resume for the next session: where things
  stand, what's real and unfixed, the hard-won facts.
- [`docs/`](docs/) — roadmaps, the PRD, engine contracts, the Claude Code
  briefs, the research behind the voice-sourcing and marketplace decisions.
- [`docs/ORIGINS.md`](docs/ORIGINS.md) — what the ideas are, when they were
  made, and what prior art each one joins. [`CITATION.cff`](CITATION.cff) if
  you build on them.

None of it is needed to *use* ProseCast. It is there for anyone curious how a
project like this gets made — including the day a whole feature was lost
because it was built in a cloud container and never committed, and the rule
that came out of it.

---

## 🤝 Contributing, support, license

Issues and pull requests are welcome on GitHub. This is one person's project
built in evenings; there is no promised response time, and Issues is the only
support channel.

**If ProseCast read you a book, consider buying its author a coffee.**
Every full-cast render it does for free is one you didn't pay a subscription
or an audiobook credit for. This is built in evenings by one person on one
home server; the coffees pay for the parts, the GPU hours and the next
feature. [**☕ ko-fi.com/tylerxkoontz**](https://ko-fi.com/tylerxkoontz)

Never a gate — nothing in ProseCast is paywalled, and nothing will be.

**License:** [GPL-3.0](LICENSE). Use it on books you own, for yourself.
Don't distribute generated audio of works you don't hold the rights to.
