# CC BRIEF — E10.1: two install edges (a probe that can't tell mute from moved, and a shortcut a space breaks)

**Written 2026-09-08 for an autonomous Claude Code run in `~/dev/prosecast`, on the Mac.**
**This brief has 5 steps (0–4). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to `STATUS.md` — do not guess.

**This is a small chapter on purpose.** Two findings from the E10 review, both in `SETUP.sh`,
both in the "silent failure a stranger cannot diagnose" class. Nothing here touches the render
path, the IR, or any library. If a change starts growing past these two, stop and write why.

---

## Mission

E10 shipped and is pushed (`fb23346`). Two edges in `SETUP.sh` survived it:

1. **`piper_can_speak()` cannot tell "Piper is mute" from "the check could not run."**
   (`SETUP.sh` ~line 93.) The probe runs under `>/dev/null 2>&1`, so an `ImportError` —
   `piper.phonemize_espeak` renamed, `EspeakPhonemizer` moved, any upstream reshuffle — comes
   back as the same non-zero as a genuine phonemize failure. On Linux that path calls `bad`,
   which means a **failed install and zero voices downloaded on a machine where Piper works
   fine**: `_synthesize_piper` shells `python -m piper` and never imports that module. Linux is
   the platform where Piper is the only built-in engine, so this is the whole install lost to a
   check that was wrong.

2. **The Linux `.desktop` `Exec=` line is unquoted.** (`SETUP.sh` ~line 317.)
   `Exec=$HERE/$LAUNCHER` — clone into `~/My Projects/prosecast` and the shortcut does nothing
   at all, with no error in any log a normal person reads. The Desktop Entry spec requires the
   `Exec` value be quoted when it contains spaces. The macOS branch already quotes
   (`open -a Terminal "$HERE/$LAUNCHER"`); Linux does not.

Done means: an unrunnable check warns and continues instead of failing the install; a repo path
with a space produces a working `.desktop`; both are held by a test; the suite is green and
`STATUS.md` says what changed.

---

## Guardrails

- **GREEN (do autonomously):** edit `SETUP.sh`, `tests/test_setup_scripts.py`, `README.md` (only
  if a sentence there stops being true), `STATUS.md` / `HANDOFF.md` at chapter-close; LOCAL
  commits.
- **YELLOW (do exactly as written):** nothing in this brief is yellow. If you find something
  that feels like it is, it belongs in the parking lot at the bottom, not in this chapter.
- **RED (never):** run `SETUP.sh` against this machine's real repo root (it would rewrite the
  launcher, and step 9 would offer to write to Tyler's Desktop — test in a temp clone with
  `HOME` pointed at a scratch dir, the way E10 did); download the Piper voices again; touch
  `SETUP.ps1` (Windows is unaffected by both findings and Tyler is verifying that script on the
  laptop tonight — a change here would invalidate his run); touch any library, `ir.json`,
  `corrections.jsonl`, or `voice_map.json`; put a real host / IP / user in a tracked file
  (placeholders: `GIDEON_HOST`, `192.168.1.50`, `/Users/YOUR_USER`); `git push`.
- **Working tree:** expected clean at `main`, `fb23346`. `git status -sb` first; if there are
  modified files, STOP and write what you found to `STATUS.md`.

---

## Step 0 — orient

```
git status -sb
git log --oneline -1
.venv/bin/pytest tests/test_setup_scripts.py tests/test_piper_voices.py -q
```

Expected: clean tree, `fb23346`, both files green. Read `SETUP.sh` lines 78–166 (step 3) and
286–330 (the two shortcut builders) before editing either.

---

## Step 1 — the probe gets a third answer

Give `piper_can_speak()` three outcomes instead of two:

- **0** — phonemized, Piper will make sound. Unchanged.
- **1** — imported fine, phonemize returned nothing. The real mute case (the Apple Silicon
  wheel). Unchanged behaviour: `warn` on macOS, `bad` on Linux.
- **2** — the check itself could not run. Warn on **both** platforms and **continue to the
  voice download**, because the overwhelmingly likely reading is that piper moved a module and
  works fine. A wrong `✓` here costs a confusing Setup page later; a wrong `✗` costs the whole
  install now.

Shape:

```bash
piper_can_speak() {
  python - >/dev/null 2>&1 <<'PIPER_CHECK_EOF'
try:
    from piper.phonemize_espeak import EspeakPhonemizer
except Exception:
    raise SystemExit(2)          # the check could not run; not an answer about Piper
out = EspeakPhonemizer().phonemize("en-us", "Testing one two three.")
raise SystemExit(0 if out and out[0] else 1)
PIPER_CHECK_EOF
}
```

**⚠️ The trap that will bite you, and it is silent.** `set -e` is on at the top of this script.
Calling `piper_can_speak` as a bare command and letting it return non-zero **exits the whole
script on the spot** — no `✗`, no summary, no launcher, nothing. The current code is safe only
because it is inside `if ! piper_can_speak`. Capture the code explicitly:

```bash
local rc=0
piper_can_speak || rc=$?
case "$rc" in
  0) ok "Piper can phonemize — it will actually make sound" ;;
  2) warn "could not check whether Piper can speak (its phonemizer module has moved upstream)."
     warn "  Continuing — if renders come out silent, that is where to look." ;;
  *) # the existing mute branch, macOS warn / Linux bad, unchanged
     ;;
esac
```

Keep the existing comment block explaining the Apple Silicon wheel — it is the reason this
function exists and it is still true. Add one sentence saying why 2 is not 1.

**A test in the way:** `test_a_mute_piper_is_fatal_on_linux_and_a_warning_on_macos` currently
does `block.split("else", 1)` on the text between `if ! piper_can_speak` and the `ok` line. A
`case` statement will break that split. Rewrite the test to assert the behaviour rather than the
shape — for each of the three codes, that the right one of `ok` / `warn` / `bad` is reached —
and keep its docstring's reasoning.

**New test:** the inconclusive path must not be fatal. Assert that the `2` branch calls `warn`
and not `bad` on either platform, and that it does not sit between the check and
`piper.download_voices` in a way that skips the download. `heredoc(sh(), "PIPER_CHECK_EOF")` is
the existing helper for reading the probe body; extend
`test_setup_sh_proves_piper_can_speak_before_it_downloads_the_voices` rather than duplicating it.

**Acceptance:** `bash -n SETUP.sh` parses. A local harness that stubs `piper_can_speak` to return
each of 0/1/2 in turn reaches the expected line and, for 2, still reaches the download loop.

---

## Step 2 — a path with a space

In `make_shortcut_linux`, quote the `Exec` value:

```
Exec="$HERE/$LAUNCHER"
```

**Only `Exec`.** Per the Desktop Entry spec, `Exec` is a command line and takes quoting; `Path`
and `Icon` are plain string values and must NOT be quoted — adding quotes there breaks them.
Resist the tidiness instinct.

**A test in the way:** `test_the_linux_shortcut_is_a_desktop_entry_with_an_icon` asserts the
literal `"Exec=$HERE/$LAUNCHER"` and will fail. Update it to the quoted form, and add a
sentence to its body saying why the quotes are load-bearing.

**New test:** build the `.desktop` in a temp dir whose path contains a space, and assert the
`Exec` line survives a parse — read it back with `configparser` (it reads Desktop Entry files),
confirm the `Exec` value resolves to an existing executable file. That is the check that would
have caught this.

**Acceptance:** the generated entry parses and its `Exec` points at a real file when the repo
path contains a space.

---

## Step 3 — the whole suite

```
.venv/bin/pytest tests/ -q
```

Expected: **462 + your new tests passed, 1 skipped**. The count went 432 → 462 in E10; it must
not go down.

Then all five `tests/ui/` checks. They need Playwright, which is in the Mac venv. If any is red,
STOP — nothing in this chapter touches `static/index.html`, so a red UI check means something
else moved and Tyler needs to know before it is buried under a commit.

---

## Step 4 — chapter-close

- `STATUS.md`: a new entry at the top, dated 2026-09-08, saying what the two findings were, why
  each was a silent failure rather than a loud one, and the new test count. Single-writer — do
  not touch any other project's STATUS or the DASHBOARD.
- `HANDOFF.md`: only if one of its sentences stopped being true. It was refreshed in `224af45`
  and should mostly still hold.
- Commit locally, one commit per finding plus the chapter-close. **Do not push.**
- End your report with what Tyler still has to check by hand. For this chapter that is
  **nothing** — both fixes are testable here, which is the point of a small chapter.

---

## Parking lot — found in the E10 review, deliberately NOT in this brief

Do not do these. They are recorded so they are not lost:

- **Port 8000 has no collision check.** Both launchers `exec` uvicorn on a hardcoded 8000. E10
  made "double-click an icon" the primary way in, which makes double-clicking it twice a thing
  that will happen; the second one dies with `[Errno 48] Address already in use` in a Terminal
  window a stranger cannot parse. Wants a probe that opens the browser instead when something is
  already listening — and the same fix on the Windows launcher, which means waiting until Tyler
  is at that machine.
- **macOS has no `~/Desktop` fallback.** Linux falls back to `~/.local/share/applications`; the
  macOS branch calls `ln -s` unconditionally and, under `set -e`, exits 1 after every other step
  succeeded. Rare, asymmetric, worth a line eventually.
- **`Goldeye` is in six tracked files**, including user-facing error text in
  `prosecast/preflight.py` ("check `nvidia-smi` on Goldeye"). Public since `cf9e8cc` in E2.1.
  Not a secret — a codename with no routing value — but a stranger hitting a render error is
  told to check a machine that is not theirs. A rename sweep, its own small chapter.
- **The README's Apple Silicon paragraph says "there is nothing ProseCast can do about it."**
  `espeakng-loader` on PyPI ships a working espeak-ng plus data for macOS arm and is how
  `phonemizer` solves this exact problem. Whether it can be made to work with piper1-gpl's
  bundled loader is unknown and is a listening/experiment task, not a code task. Softening the
  sentence to "nothing ProseCast can do at install time" would be true today and would not
  invite the correction.

---

END OF BRIEF
