# CC BRIEF — E9: Windows findings (what the first real Windows install turned up)

**Written 2026-09-06 (evening) for an autonomous Claude Code run in `~/dev/prosecast`, on the Mac.**
**This brief has 7 steps (0–6). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

---

## Mission

Tonight Tyler installed ProseCast from scratch on a rebuilt Windows 11 gaming laptop (i9, RTX
4060 8 GB, Python 3.12 via winget, Piper in the venv, four Piper voices in the repo root) and it
**worked end to end**: the wizard rendered the sample on Piper and the reader followed along.
Getting there took nine things an average person cannot do and turned up two real bugs. Fix
what the code can fix, write down what it cannot, and make the README tell a Windows user the
truth. You are on a Mac and cannot run Windows; every fix here must be testable
platform-independently, and the Windows-specific claims go in docs with "tested 2026-09-06".

**Findings, in the order they bit:**

1. **`UnicodeDecodeError: 'charmap' codec` on `GET /`.** `server.py:2358` does
   `html_path.read_text()` with no encoding; Windows defaults to cp1252 and `index.html` is
   UTF-8. The server 500s on the first request. `PYTHONUTF8=1` was the workaround. There are
   ~14 `read_text()`/`write_text()` and ~17 text-mode `open()` calls without `encoding=` across
   `server.py`, `main.py`, `prosecast/`, `scripts/` (35 already have it).
2. **The wizard lost him.** The CLI smoke test (`main.py --sample --tts stub`) had already
   created `library/sample_book` cast for the *stub* engine. When the wizard reached step 4 with
   Piper active, the **casting modal appeared over the wizard**, and after "Cast the book" he
   was dropped onto the **Setup page** — a wall of optional MISSING/OFF rows under a green
   READY badge and no "play" anywhere. He said: "I don't know what to do from here, nor would
   an average person." `↻ Run setup again` then went straight through and played. So the
   sample endpoint's re-cast (E6.5) did not cover "book exists, cast for another engine, created
   outside the wizard", and the wizard's dismissal path lands on Setup instead of the book.
3. **Piper voices carry no gender; four voices for five characters.** Auto-cast gave Elizabeth
   `ryan` and Jane `kusal` (both male) and Bingley shared Elizabeth's voice. The cast profiler
   knows Elizabeth is female; the Piper pool gives it nothing to match on.
4. **Nothing tells a Windows user to download four voice models.** The Piper card says "Needs
   the piper binary and one voice model"; ProseCast's pool needs four (soon six). The Setup
   probe reports Piper `ok` when the binary exists, even if zero `.onnx` files are present — the
   failure would surface as a render error.
5. **ffmpeg row shows the full winget path** (`C:\Users\tyler\AppData\Local\Microsoft\WinGet\
   Packages\Gyan.FFmpeg_...\ffmpeg.EXE`). Accurate, useless to a person.
6. **The Setup page never says "you're ready, go listen."** READY badge + five amber rows reads
   as "something is wrong".
7. **Nine manual steps** an installer will do later (winget Python 3.12 + ffmpeg, execution
   policy, venv, pip ×3, four voice downloads, config copy, `PYTHONUTF8`). Plus a
   machine-specific tripwire: a leftover NVIDIA `extra-index-url` in *three* pip config files
   made every `pip install` retry a dead host five times. Not ours to fix; ours to warn about.
8. **Tyler's honest read on Piper:** "some of the voices weren't bad, some are more robotic
   than others. It could work. Of course Chatterbox is better." That sentence, or its meaning,
   belongs in the README.

Done means: a fresh Windows clone following the README's new Windows section reaches sound
without `PYTHONUTF8`, without a terminal after `SETUP.ps1`, and without ever seeing the casting
modal or the Setup page inside the wizard.

---

## Guardrails (read before touching anything)

- **GREEN (do autonomously):** edit `server.py`, `main.py`, `prosecast/*.py`, `scripts/*.py`,
  `static/index.html`, `README.md`, `CLAUDE.md`, `config.example.json`; add `SETUP.ps1`,
  tests under `tests/` and `tests/ui/`; extend `scripts/refresh_ui_fixtures.py`; `STATUS.md` /
  `HANDOFF.md` at chapter-close; LOCAL commits as each step says (no push).
- **YELLOW (ask by stopping):** any change to `renderer.py`'s write path or the render
  worker — that is E8's job (`docs/CC_BRIEF_data_safety.md`), not this brief's.
- **RED (never):** modify or delete anything under `library/**` by hand; write `ir.json` with a
  plain `open` (`lib.write_json_atomic`); hand-write anything in `tests/fixtures/`; put a real
  host/IP/user in a tracked file (placeholders: `GIDEON_HOST`, `192.168.1.50`,
  `/Users/YOUR_USER`); spend money; `git push`.
- **Tests that start a background job must wait for it** (HANDOFF "Key facts", 09-06). The
  sample endpoint and the render worker are such jobs.
- **Working tree:** expected clean at `main`. `git status -sb` first; if there are modified
  files, STOP and write what you found to `STATUS.md`.

## Smallest healthy-loop check (verify this before walking away)

After **Step 1**, `.venv/bin/pytest tests/ -q` must show the baseline **plus** the new encoding
guard test. Baseline on this Mac: **297 passed, 1 skipped**. If the count went up and all five
`tests/ui/` checks still pass, the loop is healthy.

---

## Step 0 — Orient (read, don't write)

Read `CLAUDE.md`, `HANDOFF.md` → "Key facts" (the first-run wizard paragraph, the E6.8
paragraph, the sample endpoint). Then in code:

- `server.py`: `index()` (~2358, the crashing `read_text()`); `POST /books/sample` (~499) and
  whatever E6.5 added to cast the sample book for the active engine — find the exact condition
  under which it re-casts, because finding 2 slipped past it; `GET /setup/status` and
  `prosecast/setup_probe.py` `probe_voice_engine` (the `piper` branch ~163) and `probe_tools`
  (~222, the ffmpeg row's `detail` is the path).
- `static/index.html`: the first-run wizard (`fr` state, `openFirstRun`, the step-4 handler that
  calls `/books/sample` → render → open book); **where the casting modal is triggered when a
  book opens** (`castingModalOverlay` ~3764 and whatever decides a book "needs casting"); the
  wizard's close/skip handlers (`Skip — take me to Setup`, and what happens after step 4
  succeeds or after any modal closes over it); `renderSetup()` intro text.
- `prosecast/tts_engine.py`: `PIPER_VOICES` (~47), `_synthesize_piper` (~234 — runs
  `piper --model <name> --output_file <path>`; Piper resolves `<name>.onnx` from the **current
  working directory**, so the repo root is where voices live), `VoiceAssigner` pool rotation
  (~138–143), and how the cast profiler's gender hints reach `_default_voice_map` (`server.py`
  ~248) — for Chatterbox, gender comes from `voice_meta.json`; Piper needs the same shape.
- `SETUP.sh` — every step it performs; `SETUP.ps1` must mirror it.
- `scripts/refresh_ui_fixtures.py`, `tests/ui/check_first_run.py` — the fixture pattern.

Write nothing in this step.

---

## Step 1 — UTF-8 everywhere (finding 1)

Add `encoding="utf-8"` to every text-mode `open()`, `read_text()`, `write_text()` in
`server.py`, `main.py`, `prosecast/`, `scripts/` (binary modes untouched). `Path.read_text()`
of JSON, `json.load(open(...))`, `write_text(json.dumps(...))` — all of them.
`lib.write_json_atomic` already does it? Verify, don't assume.

Then a guard test, `tests/test_encoding_guard.py`, in the spirit of `test_pipeline.py`'s
plain-write check: walk those four locations with `ast`, and fail on any `open()` call whose
mode is text (absent or without `b`) that lacks an `encoding` keyword, and any
`.read_text()` / `.write_text()` call without one. Allowlist nothing; if a call cannot take an
encoding, it is not a text read. The test must pass on the Mac and would have failed before
this step (prove it: run it before the sweep, see it fail, then sweep).

Also: `server.py` should refuse to guess. At import, if `sys.flags.utf8_mode == 0` and
`sys.platform == "win32"`, print one line to the log: "Tip: set PYTHONUTF8=1 or run through
SETUP.ps1's launcher" — belt and braces, not a fix; the sweep is the fix.

`git commit -m "E9.1: encoding=utf-8 on every text read/write; guard test"`.

---

## Step 2 — The wizard never loses the user (finding 2)

Three changes, tested against a fixture-built library where `sample_book` already exists and is
cast for `stub`:

1. **`POST /books/sample` re-casts whenever the existing voice map does not fit the active
   engine's pool** — regardless of who created the book (wizard, CLI, previous engine). Reuse
   the pool check the render preflight already does (`voice_map entries not in the <engine>
   pool` was the message on 09-06). Return `recast: true` so the wizard knows to force-render.
   A book whose map *does* fit is left alone (never re-cast Tyler's real casts).
2. **The wizard suppresses the casting modal while it is open.** Whatever opens
   `#casting-modal-overlay` on book open must check `isFirstRunOpen()` (or equivalent) and skip.
   Casting is step 4's job via the endpoint, never a surprise screen.
3. **Every exit from the wizard lands on the book, not on Setup**, except the explicit
   "Skip — take me to Setup" link. After step 4 succeeds: reader open, playing. If step 4 fails:
   stay on step 4 with the error and the two buttons (that already exists — keep it). If the
   wizard is dismissed by Esc it goes to Setup by design (E6) — keep that, but if a book was
   created or rendered during this wizard run, land on that book instead.

Tests: `tests/test_sample_book.py` gains "exists, cast for stub, engine is say → re-cast, and
`recast: true`"; "exists, cast for say, engine is say → untouched". `check_first_run.py` gains:
fixture where the sample exists with a mismatched map → step 4 completes, the casting overlay
never becomes visible, and the page ends with `body.reader-open`, not `body.setup-open`.
Regenerate fixtures through `refresh_ui_fixtures.py`, never by hand.

`git commit -m "E9.2: wizard re-casts a mismatched sample, suppresses the casting modal, lands on the book"`.

---

## Step 3 — Piper voices with gender, six of them, and a probe that checks they exist (findings 3–4)

- `PIPER_VOICES` becomes six with a gender each. Verify genders against the Piper voices
  catalogue (`python -m piper.download_voices` lists them; the rhasspy/piper-voices README and
  sample pages say who is who) — do not guess. Known: `en_US-lessac-medium` (female),
  `en_US-ryan-medium` (male), `en_GB-alan-medium` (male), `en_US-kusal-medium` (male). Add two
  female English voices from the same catalogue (candidates: `en_US-amy-medium`,
  `en_GB-jenny_dioco-medium`, `en_US-hfc_female-medium` — confirm they exist and are medium
  quality). Store gender where the Chatterbox path stores it, so `_default_voice_map` and the
  Voices tab see Piper voices with the same shape (`_apply_voice_meta` / static-list engines
  from E7).
- **Auto-cast on Piper respects gender** the same way it does on Chatterbox — if the profiler
  says female, pick from the female voices first. Test with the sample book's cast profile.
- **`probe_voice_engine`'s piper branch checks for the voice files.** For each name in
  `PIPER_VOICES`, look for `<name>.onnx` in the working directory (where `_synthesize_piper`
  will look). All present → `ok`. Some missing → `warn` with the count and a `fix` that is the
  exact command, one line per missing voice: `python -m piper.download_voices <name>` and the
  sentence "run these from the ProseCast folder — Piper looks for voices there". None present →
  `missing` with the same fix. The wizard's step 2 will then show it (it renders the probe's own
  words).
- The Piper card text becomes true: "Local, CPU-only, any OS. Needs the piper program and six
  voice files; Setup lists the download commands."
- The Voices tab lists the six with their gender glyphs and no licence badge (Piper voices are
  MIT-licensed models with synthetic or consented speakers per the catalogue — say "see Piper
  voices page" in the tooltip rather than asserting a licence you did not check).

`git commit -m "E9.3: six Piper voices with gender; probe checks the .onnx files exist"`.

---

## Step 4 — Words (findings 5–6)

- ffmpeg row `detail`: "found · ffmpeg 9.0.1" (parse the first line of `ffmpeg -version`;
  fall back to "found" if parsing fails). The full path moves to the row's tooltip / an
  `extra` field the Setup page shows on hover or in a `<details>`. Same for tesseract.
- Setup page: when `voice_engine.ok`, a one-line banner at the top, above the intro:
  "**You're set.** Piper is ready — open a book and press play, or run the wizard again to hear
  the sample." with two buttons: **▶ Hear the sample** (runs the same sequence as wizard step 4)
  and **↻ Run setup again**. Both skins. The amber optional rows stay; the banner reframes
  them.
- Wizard step 4's copy already says what it does; leave it.

`check_first_run.py` / a small `check_setup_banner` inside it: banner present when the fixture
is ready, absent when not. `git commit -m "E9.4: ffmpeg row says a version, Setup says you're set"`.

---

## Step 5 — `SETUP.ps1` and the README's Windows section (finding 7–8)

**`SETUP.ps1`** mirrors `SETUP.sh` step for step, PowerShell-native, safe to re-run:
checks `py -3.12` (or `py -3.11`+) exists and says `winget install -e --id Python.Python.3.12`
if not; checks `ffmpeg` and says `winget install -e --id Gyan.FFmpeg` if not; creates
`.venv` with `py -3.12 -m venv .venv`; installs `-r requirements.txt` **with
`--isolated`** so machine-wide pip config (the NVIDIA index) cannot slow or break it; installs
`piper-tts`; downloads the six voices into the repo root, skipping ones already present;
`python -m spacy download en_core_web_sm` and proves it loads; copies `config.example.json` →
`config.json` if missing; runs `main.py --sample --tts stub`; prints ✓/✗ per step and the
exact next command: `.\.venv\Scripts\Activate.ps1; uvicorn server:app --port 8000`. Also
writes **`start-prosecast.ps1`**: activates the venv, `cd`s to the repo, starts uvicorn, opens
`http://localhost:8000` in the default browser — the one file a Windows user double-clicks
after setup (note the execution-policy line they may need once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`). You cannot run PowerShell on the Mac;
keep the script simple, lint it by eye, and mark it "tested by Tyler 2026-09-06 on Windows 11"
only for the steps he actually ran (all of the above except `--isolated` and the two new
voices).

**README → replace the "Windows: … known-good path is WSL2" paragraph** with a real section
under Install, "### Windows (tested 2026-09-06)": winget lines for Python 3.12 and ffmpeg;
"close and reopen PowerShell"; `git clone`; `.\SETUP.ps1`; `.\start-prosecast.ps1`; the wizard
takes it from there. Two heads-ups in the section: (a) if `pip` prints repeated "Retrying…
getaddrinfo failed" lines for a host you don't recognise, an old tool left a dead package index
in your pip config — `pip config debug` shows which file, and SETUP.ps1's `--isolated` avoids
it; (b) Piper on Windows: Tyler's sentence, in the README's voice — some Piper voices are fine,
some are noticeably robotic; it works, and it is the rung you use to decide whether Chatterbox
is worth setting up. Keep "WSL2 also works" as one line, not the headline. Update the rung
table's rung-1 row ("Any Mac, or any machine with `piper`" → "Any Mac, Windows or Linux
machine; Piper on CPU"). Drop `PYTHONUTF8` from everything — after Step 1 it is not needed;
if you kept the import-time tip, it names `SETUP.ps1`.

`CLAUDE.md`: one line under Dependencies pointing at `SETUP.ps1` for Windows.

`git commit -m "E9.5: SETUP.ps1 + start-prosecast.ps1; README Windows section from a real install"`.

---

## Step 6 — Chapter-close

- Full `.venv/bin/pytest tests/ -q` and all five `tests/ui/` checks green.
- `STATUS.md`: session entry "2026-09-06 (Claude Code, Mac) — E9: Windows findings" in the
  house style, listing the eight findings and what happened to each (fixed / documented /
  Tyler's to verify on Windows). **Still Tyler's to verify:** re-run on the laptop from a fresh
  clone with `SETUP.ps1`; the two new voices' gender by ear; the wizard on a machine where the
  sample book already exists.
- `HANDOFF.md`: E9 row in the phase table; "Key facts" gets **"Windows (09-06)"**: encoding
  guard exists and why; Piper resolves voices from the CWD; `SETUP.ps1`/`start-prosecast.ps1`
  are the Windows entry points; the wizard suppresses the casting modal. "Where to start":
  next is E8 (data safety) when Gideon is free, then the installer (a design session — the
  nine manual steps are its spec).
- `git commit -m "E9.6: chapter-close — Windows findings"`. `git status -sb` clean, `[ahead N]`.
  **Do not push.**

END OF BRIEF
