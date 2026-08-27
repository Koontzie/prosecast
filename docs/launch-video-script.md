# ProseCast Launch Video — Script & Shot List

**Format:** screen recording + voiceover (no camera)
**Target runtime:** ~10–11 minutes
**Demo book:** *Dracula* (Project Gutenberg #345) — recommended. Dialogue-heavy, wildly
distinct character voices (Van Helsing, Mina, Renfield, the Count), and famous enough
that viewers instantly get why casting matters. Swap freely for another Gutenberg pick
(*Sherlock Holmes*, *Pride & Prejudice*) — the script beats don't change.

⚠️ **Copyright rule for every frame and every second of audio:** only public-domain
text is ever visible or audible. No Brigands, no Carl rulebook, no copyrighted EPUBs
in the book sidebar during capture. Easiest fix: capture with a fresh `library/` that
contains only the demo book(s).

---

## Pre-production checklist (do before recording anything)

1. **Render the demo book end-to-end**: attribution → LLM pass → cast in the Voices
   panel → render 2–3 chapters on Chatterbox → M4B export works. (This doubles as
   your Phase C queue smoke test.)
2. **Render the "flat" version** of the same scene: one narrator voice, no casting —
   Piper or a single Chatterbox voice for everything. This is the cold-open "before."
3. **Pick the hero scene**: a fast 2–3 person exchange with narration between lines.
   For *Dracula*: Harker's first dinner with the Count (Ch. 2), or Van Helsing
   explaining the stakes to Seward (Ch. 14). You want at least 3 distinct voices
   audible within ~15 seconds.
4. **Capture hygiene**: clean browser profile, no bookmarks bar, no personal tabs,
   window at 1080p+ with UI zoomed so text is readable on a phone. Hide the macOS
   dock/menu bar if possible.
5. **Record VO separately from screen capture, then sync in edit.** Trying to narrate
   live while driving the UI is how takes die. Capture the screen actions slow and
   silent; read the script into a mic afterward; stretch/trim footage to fit.
6. **Record VO one beat at a time.** Each `## Beat` below is one take. Flub a line →
   re-read that sentence, keep rolling, cut in edit. Never restart a beat from the top
   more than twice; move on and punch in later.
7. Keep ALL raw captures — the shorts (appendix) are mined from this same footage.

---

## Beat 0 — Cold open: the before/after (0:00–0:35)

**Screen:** Black frame, or a simple audio waveform. Caption text only.

> **[CAPTION: "an audiobook made by ordinary text-to-speech"]**

*(No VO. Play ~8 seconds of the FLAT render of the hero scene — one monotone voice
reading narration and all dialogue.)*

> **[CAPTION: "the same scene — cast and performed on my own computer"]**

*(Play ~18 seconds of the ProseCast render: narrator voice for prose, distinct voices
snapping in for each character. Let it breathe — this clip is the entire pitch.)*

**VO (over the tail of the good render):**

> Same book. Same computer. Nothing sent to the cloud, no subscription, no
> per-character fees. I built a tool that reads a novel, figures out who's speaking
> on every single line, casts a voice for each character, and performs the whole
> book locally. Let me show you how it works.

**[TITLE CARD: ProseCast — logo/wordmark, 2 seconds]**

---

## Beat 1 — Why this exists (0:35–1:30)

**Screen:** Slow scroll through a Gutenberg book page → cut to an audiobook storefront
search with no results → cut to the ProseCast library sidebar.

**VO:**

> Here's the problem. Most books never get an audiobook. Out-of-print stuff, indie
> fiction, web serials, that 650-page RPG rulebook you swore you'd read — nobody is
> paying a narrator to record those. And the text-to-speech tools that do exist give
> you one flat voice droning through everything, where the narrator and every
> character sound like the same bored robot.
>
> The audiobooks people actually love have a cast. Different voices, real deliveries,
> a narrator who gets out of the way. That's a *casting and direction* problem, not
> just a speech problem — and that's the part nobody was solving. So I did.
>
> One rule up front: this is for books you own, on your own machine. Your library
> never leaves your computer. No telemetry, no uploads, no accounts.

**Shot note:** land "your library never leaves your computer" on a shot of the app
running at `localhost` — the URL bar is the proof.

---

## Beat 2 — How it works, in plain words (1:30–3:00)

**Screen:** Simple 4-step diagram (book → who's speaking → cast voices → performance).
Make it one static slide with progressive highlights — don't over-animate. Then cut to
the real IR/unresolved panel as evidence.

**VO:**

> Under the hood it's a pipeline. Step one: parse the book — EPUB, plain text, and
> now PDFs. Step two, the hard part: figure out who speaks every line of dialogue.
>
> A layered set of rules handles most of it deterministically — "said Mina" is easy;
> tracking an untagged back-and-forth exchange across a chapter boundary is not.
> The rules alone resolve about ninety percent of dialogue. Then a local language
> model — running on my own hardware through Ollama — reads the scenes the rules
> couldn't crack and attributes the rest. On a hundred-chapter novel I use as a test
> book, the combined pipeline gets to ninety-nine point eight percent.
>
> Step three: casting. Every character gets a voice. And step four: your machine
> performs the book — with a tagging pass that marks the emotional intent of each
> line, so delivery can follow the scene instead of flatlining through it.
>
> And for the lines it still gets wrong? You fix them with one click, while
> listening. More on that in a second — it's my favorite part.

**Shot note:** when the VO says "ninety-nine point eight," show the unresolved badge
on a chapter going from a big number to a small one (or a before/after of the
unresolved panel). Numbers land harder when the UI shows them.

---

## Beat 3 — The demo: book in, audiobook out (3:00–6:30)

This is the spine of the video. Capture each sub-beat as its own clip.

**3a. Drop the book in.**
**Screen:** "+ Add Book" → upload the *Dracula* EPUB → processing → chapter list
appears with real titles.

> Here's the whole flow, start to finish. I drop in Dracula — public domain, four
> hundred pages, a dozen speaking characters. ProseCast parses it into chapters and
> runs attribution.

**3b. Meet the cast.**
**Screen:** open the Voices panel — the character list with one row per speaking
character. Hover a few names.

> When it's done, the book has a cast list. It found the Count, Van Helsing, Mina,
> Renfield — every speaking character, pulled straight out of the prose. Now I get
> to play casting director. Each character gets a voice — and auto-cast handles the
> crowd of minor characters so I only hand-pick the leads.

**3c. Preview and cast voices.**
**Screen:** open a voice dropdown, hit preview on 2–3 voices for one character —
*with actual dialogue text*, not a stock phrase. React to a bad fit, pick the right one.

> Previews use the character's actual lines from the book, so you're not guessing —
> you hear Van Helsing's voice saying Van Helsing's words before you commit.

**3d. Render.**
**Screen:** hit render on a chapter → job queued → status ticking. Time-lapse or
jump-cut the wait; show the queue UI briefly.

> Hit render, and the render queue takes it from there — chapter by chapter, one job
> at a time so the GPU never fights itself, resumable if anything dies mid-book. On
> my machine this runs on a local model called Chatterbox. Kick off a whole novel
> before bed; it's an audiobook by morning.

**3e. Listen — with read-along.**
**Screen:** playback view. Timeline scrubber, current speaker name updating as the
audio plays, block text highlighted in sync. Let it play ~20 seconds with minimal VO.

> And here's the result. As it plays, ProseCast shows you exactly who's speaking and
> follows along in the text, word for word.

*(Let the render carry this beat. Resist narrating over the demo audio.)*

**3f. The one-click fix — the correction loop.**
**Screen:** while audio plays, catch a line, click the ✎ next to the speaker name,
reassign it in the inline popup, save. Show the block re-render.

> No attribution system is perfect — so when a line comes out in the wrong voice,
> you don't stop, you don't open a file, you don't re-render the book. Click the
> speaker name, pick the right character, done — only that block re-renders. Every
> correction is also logged, which quietly builds a labeled dataset for training a
> better attribution model over time. The tool gets smarter the more it's used.

**3g. Take it with you.**
**Screen:** ⬇ Export M4B button → download → the file opening in an audiobook player
(Apple Books or similar) with real chapter markers.

> When you're happy, one click exports a proper M4B audiobook — chapter markers and
> all — that drops into any audiobook player on your phone.

---

## Beat 4 — What it takes to run (6:30–7:45)

**Screen:** simple "hardware ladder" slide, three rungs. Then a brief shot of
`nvidia-smi`/Activity Monitor or the Chatterbox server terminal for credibility.

**VO:**

> "Runs locally" always raises the question: on what? There's a ladder.
>
> No GPU at all? Piper runs on CPU — the voices are plainer, but the full casting
> and attribution pipeline still works. A gaming PC with eight to twelve gigs of
> VRAM gets you the full experience with expressive local voices. I run it on a home
> server with a used 3090 — that's the "render a novel overnight" tier.
>
> And if you want studio-grade voices, ProseCast plugs into ElevenLabs with your own
> API key — your account, your usage, no markup from me. The local tier isn't a
> crippled trial. It's the product.

---

## Beat 5 — The elephant in the studio (7:45–9:15)

*The inoculation beat. Two conversations WILL happen in the comments — voice actors
and piracy — so the video has them first, on its own terms. Delivery note: no
defensive tone, no rushing. Slow down here. This beat is where trust is won.*

**Screen:** a human narrator's audiobook page (something beloved and public-facing) →
cut back to the app → the repo's voice provenance page → a plain-text slide with the
three rules as they're spoken.

**VO:**

> Before the comments write themselves, let's have the two conversations directly.
>
> First: voice actors. A great human narrator is a performance — an interpretation
> of the book — and this doesn't compete with that, and isn't trying to. If a book
> you love has a real narration, buy it; it's better. ProseCast exists for the
> enormous pile of books that will *never* get one — out-of-print titles, indie
> fiction, web serials, technical books, and readers who need audio to access text
> at all. The realistic alternative to ProseCast isn't a hired narrator. It's
> silence.
>
> And I've set three rules I won't break. One: every voice that ships with this is
> documented — where it came from and under what license, in the open, in the repo.
> Two: no cloning anyone's voice without their consent. The tech can do it; the
> tool won't. Three: if there's ever a voice marketplace on top of this, voice
> actors set the terms and get paid per use. That's stated as a direction, not a
> promise — but it's the only version of that future I'll build.
>
> Second: piracy. ProseCast doesn't download books, doesn't share books, and
> doesn't distribute audio. You bring a book you already have, it renders on your
> own hardware, and the result stays with you — the same as reading it aloud to
> yourself, just with better casting. There's no server because your library is
> none of my business.

**Shot note:** the three rules should be on screen as literal text while spoken —
this is the clip people will screenshot, so make it screenshot-able.

---

## Beat 6 — What's next + the ask (9:15–10:30)

**Screen:** the GitHub repo README (with the demo clip embedded), then the roadmap
section. End on the repo URL, full screen.

**VO:**

> ProseCast is open source, GPL, on GitHub — link below. Fair warning: right now
> it's a builder's tool. If you're comfortable with a Python venv and you already
> run Ollama, you can have this working tonight. A friendlier install is on the
> roadmap, along with per-chapter narrators for multi-POV books and a delivery
> editor for directing individual line readings.
>
> If you try it, the single most useful thing you can do is use the correction
> loop and tell me where attribution breaks — every genre breaks it differently,
> and that feedback is the whole flywheel. If you want to support the project,
> there's a Ko-fi. And if you build something on top of it — I want to see it.
>
> Thanks for listening. Literally.

**[END CARD: repo URL + Ko-fi + one more 5-second burst of the multi-voice demo
audio — end on the product, not on silence.]**

---
---

# Appendix A — Titles & thumbnail

**Title options** (pick one; A/B later if YouTube lets you):

1. My computer turns any book into a full-cast audiobook — locally
2. I built an AI casting director for audiobooks (100% local)
3. Every book deserves an audiobook, so I built this
4. Turning a 400-page novel into a multi-voice audiobook overnight — no cloud

**Thumbnail concept:** split frame. Left: dense book page, grayscale, "1 voice 🤖".
Right: the cast panel with 4–5 character voice rows, full color, "a full cast".
Minimal text; the split does the work. (No book covers of copyrighted works.)

---

# Appendix B — YouTube description block

> ProseCast reads a book, figures out who speaks every line, lets you cast a voice
> for each character, and performs the whole thing on your own hardware. Local-first:
> your library never leaves your machine.
>
> ⭐ Repo: https://github.com/Koontzie/prosecast
> ☕ Support: [Ko-fi link]
> 🎙 Premium voices via ElevenLabs (your own key): [affiliate link, disclosed]
>
> Chapters:
> 0:00 One book, two audiobooks
> 0:35 Why I built this
> 1:30 How it works
> 3:00 Demo: book in, audiobook out
> 6:30 What hardware you need
> 7:45 Voice actors, piracy, and three rules I won't break
> 9:15 Open source + roadmap
>
> Demo text: Dracula by Bram Stoker (public domain, Project Gutenberg).
> Built with: Python, spaCy, Ollama, Chatterbox TTS, Piper, FastAPI.
> [Affiliate disclosure: the ElevenLabs link is a referral link.]

---

# Appendix C — Shorts cut list (from the same footage)

One moment per short, vertical re-frame, captions burned in (most shorts play muted
until the viewer un-mutes — open with a caption that forces the un-mute).

1. **"Before/after"** (the killer one — post everywhere first):
   Cold open Beat 0 verbatim, 30s. Caption: "unmute this 🔊 — same book, same
   computer." End card: repo URL.
2. **"Casting a vampire"**: Beat 3c — previewing 3 voices for the Count with his
   actual lines, picking the winner. Caption: "playing casting director for a
   130-year-old novel."
3. **"The one-click fix"**: Beat 3f — wrong voice plays, ✎ click, reassign,
   re-listen. Caption: "when the AI casts the wrong actor, I just… fix it."
4. **"Overnight audiobook"**: Beat 3d render queue time-lapse → morning M4B on the
   phone. Caption: "started a render before bed. woke up to an audiobook."
5. **"It knows who's talking"**: Beat 3e read-along — speaker name flipping in sync
   with the voices. Caption: "watch it track who's speaking. 99.8% accurate."

Post cadence: before/after short **the same day** as the main video + the Reddit
(r/LocalLLaMA, r/selfhosted) post; drip the other four over the following two weeks,
each linking back to the main video.

---

# Appendix D — Staying ahead of the comments

The video inoculates (Beat 5); this appendix is the ground game for launch day.
Rule of engagement: answer each objection **once**, substantively, then point later
comments at that answer. Never debate in threads — rage threads feed the algorithm
with the wrong signal and eat your day.

## Pinned comment (post the second the video is live)

> The two questions I expect most, answered up front:
>
> **"What about voice actors?"** This isn't for books that have narrators — if a
> human recorded it, buy that, it's better. It's for the ~95% of books that will
> never get an audiobook at all. House rules: every bundled voice's origin and
> license is documented in the repo, no cloning without consent, and if a voice
> marketplace ever exists here, VAs set terms and get paid per use.
>
> **"Isn't this piracy?"** ProseCast doesn't download, share, or distribute
> anything. You bring your own book; audio renders on your own machine and stays
> there. The demo in this video is Dracula — public domain.
>
> Repo (GPL): [link] — attribution bug reports are the most useful thing you can
> give me.

## Objection → prepared response

**"This puts narrators out of work."**
Lead with agreement, not defense: human narration is the ceiling, and this doesn't
reach it. The market this serves has no narrator in it — out-of-print, indie, web
serials, personal documents, accessibility. Then stop. Don't get pulled into
defending the AI-voice industry at large (ElevenLabs' celebrity marketplace, radio
stations replacing staff) — that's not your product, and trying to defend the whole
category is unwinnable. Your scope is: *this tool, these rules.*

**"AI slop / no soul."**
Concede the premise, keep the frame: "You're right that a great human read is a
performance this can't match. The honest comparison isn't ProseCast vs. a narrator —
it's ProseCast vs. no audiobook existing." Optionally invite ears: the before/after
clip is the argument.

**"Voice cloning is theft."**
The cloning feature requires a reference clip the user supplies — the policy is
consent-only, and bundled voices have documented provenance/licenses (link the
provenance page). Never answer this one until that page actually exists — it's the
single reply that goes worst if the receipts aren't real. (This is why the
provenance audit is a launch *gate*.)

**"Did you train this on stolen voices/books?"**
ProseCast trains nothing today — it orchestrates existing open TTS models
(Chatterbox, Piper) and a local LLM. The "flywheel" is opt-in *text attribution*
corrections (who spoke which line), not voice data, and by default corrections stay
on the user's machine.

**"Isn't this against author/publisher interests?"**
Personal-use format shifting of a book you own, with nothing redistributed. You're
not a lawyer and shouldn't play one in the comments — state the design posture
(local, no sharing, no DRM circumvention features) rather than legal conclusions.
"Buy the book" is always part of the answer.

**"Why not just use ElevenLabs / Speechify / ElevenReader?"**
Different layer. Those give one voice reading everything through the cloud.
ProseCast's whole point is the layer above synthesis: per-character attribution,
casting, direction, correction — and it runs locally. ElevenLabs isn't a
competitor in the reply; it's an optional backend (BYO key).

**"What's the catch / how do you make money?"**
No catch: the local tier is the whole product, GPL, forever. Ko-fi if people want
to support it; ElevenLabs referral link (disclosed) if they bring their own key; no
markup, no telemetry, no accounts.

**"This should be illegal / reported."**
One reply, calm, pointing at the pinned comment. Then disengage. Some threads
exist to be fed; don't.

## Where else this lands

- The **Reddit post** gets its own one-paragraph version of the pinned comment at
  the bottom of the post body — r/LocalLLaMA is friendly, but crossposts travel.
- The **repo** carries the durable versions: PHILOSOPHY.md (positioning),
  VOICES.md (provenance/licenses), and a short FAQ section in the README that the
  pinned comment can link to. Comments decay; the repo answer is permanent.

---

# Appendix E — Recording-day run sheet (ADHD-proofing)

The whole shoot is 3 sessions. Don't do them in one sitting.

- **Session 1 — capture (screen only, silent):** work through Beats 3a→3g in order,
  one clip per sub-beat, slow deliberate mouse movement. Then grab the localhost URL
  shot (Beat 1) and the terminal shot (Beat 4). ~45 min.
- **Session 2 — VO:** read the script one beat per take, in order. Mark bad takes
  verbally ("again") instead of stopping. ~30 min.
- **Session 3 — edit:** sync VO to clips, build the two slides (pipeline diagram,
  hardware ladder), captions, end card. Cut shorts LAST, from the finished timeline.

Definition of done for launch day: main video live, before/after short live,
Reddit post live, repo README has the demo clip embedded. Everything else is drip.
