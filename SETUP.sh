#!/bin/bash
# ProseCast — one-shot local setup for macOS and Linux.
#
# Run from the project root:   bash SETUP.sh
# Safe to re-run: every step checks before it acts.
#
# What it does, in order — the same steps as SETUP.ps1:
#   1. checks Python is 3.11+ and creates .venv if missing
#   2. installs the Python dependencies (requirements.txt)
#   3. gets you a voice engine: Piper on Linux, offered on macOS
#   4. downloads the spaCy English model and PROVES it loads
#   5. creates config.json from config.example.json if you don't have one
#   6. checks the external tools (ffmpeg required; tesseract only for scans)
#   7. runs a silent end-to-end smoke test of the pipeline
#   8. writes the launcher — the file you open from now on
# Then offers to start it. Nothing here needs a GPU.
set -e

FAILED=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; FAILED=1; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }

# ask "<prompt>" "<y|n: what Enter means>" — 0 for yes, 1 for no.
# A run with no terminal attached (a pipe, a CI job) answers NO to everything
# regardless of the default: nothing here downloads 400 MB, writes to someone's
# Desktop or starts a server without a person present to say so.
ask() {
  local reply=""
  [ -t 0 ] || return 1
  printf '  %s ' "$1"
  read -r reply || reply=""
  [ -n "$reply" ] || reply="$2"
  case "$reply" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

cd "$(dirname "$0")"
OS=$(uname -s)

# Piper resolves `<name>.onnx` from the folder it is started in, so the voices
# live beside this script. Keep in step with VoiceAssigner.PIPER_VOICES —
# tests/test_piper_voices.py fails if this list drifts from it or from
# SETUP.ps1's copy.
PIPER_VOICES=(
  'en_US-lessac-medium'
  'en_US-ryan-medium'
  'en_GB-alan-medium'
  'en_US-kusal-medium'
  'en_US-hfc_female-medium'
  'en_GB-jenny_dioco-medium'
)

echo "=== 1. Python ==="
command -v python3 >/dev/null || die "python3 not found. Install Python 3.11 or newer first."
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python $PYV found; ProseCast needs 3.11 or newer."
ok "python3 is $PYV"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ok "created .venv"
else
  ok ".venv already exists"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo ""
echo "=== 2. Python dependencies ==="
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "requirements.txt installed"

echo ""
echo "=== 3. Voice engine ==="
# The gap this closes: before 2026-09-08 this script installed no voice engine
# at all, so a clean Linux install passed every step and still landed in a
# setup wizard whose "can it speak?" step could never go green. Windows had
# been getting Piper from SETUP.ps1 since E9; Linux got a sentence of advice.

# Piper's own check that it can speak, before 400 MB of voices are downloaded
# on the strength of a pip install that "succeeded".
#
# Found 2026-09-08 on an Apple Silicon Mac: piper-tts 1.8.0's wheel bundles a
# libespeak-ng whose data path is baked to the machine it was BUILT on
# (/Users/runner/work/piper1-gpl/...), and the correct directory piper passes
# in is ignored. It installs, the six voices download, the Setup page goes
# GREEN — and every render produces a zero-byte wav. ESPEAK_DATA_PATH does not
# rescue it. Phonemizing needs no voice model, so this fails in a second
# rather than after the download.
piper_can_speak() {
  python - >/dev/null 2>&1 <<'PIPER_CHECK_EOF'
from piper.phonemize_espeak import EspeakPhonemizer
out = EspeakPhonemizer().phonemize("en-us", "Testing one two three.")
raise SystemExit(0 if out and out[0] else 1)
PIPER_CHECK_EOF
}

# Never returns non-zero: a voice that will not download is a worse cast, not
# a broken install, and `set -e` would turn it into a dead stop. It records
# the ✗ and the run ends on one at the bottom.
install_piper() {
  if ! pip install --quiet piper-tts; then
    bad "piper-tts failed to install — Piper is the built-in voice engine here"
    return 0
  fi
  ok "piper-tts installed"

  if ! piper_can_speak; then
    if [ "$OS" = "Darwin" ]; then
      warn "Piper installed, but its bundled espeak-ng cannot find its own data files."
      warn "  This is a packaging problem in the macOS wheel, not something here."
      warn "  Skipping the 400 MB voice download — macOS 'say' is still your engine,"
      warn "  and Chatterbox (README rung 2) is the upgrade worth making instead."
    else
      bad "Piper installed but cannot phonemize: its bundled espeak-ng cannot find its data files."
      bad "  That is the wheel, not ProseCast, and nothing here can patch it. Chatterbox"
      bad "  (README rung 2) is the way to a voice on this machine."
    fi
    return 0
  fi
  ok "Piper can phonemize — it will actually make sound"

  for v in "${PIPER_VOICES[@]}"; do
    if [ -f "$v.onnx" ]; then
      ok "$v already here"
      continue
    fi
    echo "  downloading $v ..."
    # Output is left visible on purpose — several hundred MB behind a silent
    # prompt is indistinguishable from a hang.
    if python -m piper.download_voices "$v" && [ -f "$v.onnx" ]; then
      ok "$v"
    else
      bad "$v did not download — re-run this script, or: .venv/bin/python -m piper.download_voices $v"
    fi
  done
  return 0
}

piper_voices_present() {
  local n=0 v
  for v in "${PIPER_VOICES[@]}"; do
    if [ -f "$v.onnx" ]; then n=$((n + 1)); fi
  done
  echo "$n"
}

if [ "$OS" = "Darwin" ] && command -v say >/dev/null; then
  # macOS already has a working engine, so Piper is an upgrade, not a rescue,
  # and 400 MB is not something to help yourself to. Offered, never assumed.
  ok "macOS 'say' voices available — the zero-setup voice tier"
  if [ "$(piper_voices_present)" -eq "${#PIPER_VOICES[@]}" ]; then
    ok "Piper's ${#PIPER_VOICES[@]} voice files are already here too"
  elif ask "Also install Piper? Better voices than 'say', ~400 MB — install now? [y/N]" n; then
    install_piper
  else
    ok "skipped Piper — 'say' is enough to hear the sample, and the ⚙ Setup page prints the lines that add Piper later"
  fi
else
  # Linux (and a Mac with no `say`): Piper is the built-in engine, so install
  # it the way SETUP.ps1 does on Windows rather than printing advice.
  install_piper
fi

echo ""
echo "=== 4. spaCy English model (for 'who is speaking') ==="
if python -c 'import spacy; spacy.load("en_core_web_sm")' 2>/dev/null; then
  ok "en_core_web_sm already loads"
else
  python -m spacy download en_core_web_sm >/dev/null
  python -c 'import spacy; spacy.load("en_core_web_sm")' \
    || die "spaCy model downloaded but does not load — run: .venv/bin/python -m spacy download en_core_web_sm"
  ok "en_core_web_sm downloaded and loads"
fi

echo ""
echo "=== 5. config.json ==="
if [ -f config.json ]; then
  ok "config.json exists (left untouched)"
else
  cp config.example.json config.json
  ok "created config.json from config.example.json — no engine chosen yet, so the app opens its setup wizard on first run"
fi

echo ""
echo "=== 6. External tools ==="
if command -v ffmpeg >/dev/null; then
  ok "ffmpeg: $(command -v ffmpeg)"
else
  warn "ffmpeg not found — REQUIRED for M4B export and voice-clip prep."
  warn "  macOS: brew install ffmpeg   Debian/Ubuntu: sudo apt install ffmpeg"
fi
if command -v tesseract >/dev/null; then
  ok "tesseract: $(command -v tesseract) (scanned PDFs can be OCR'd)"
else
  ok "tesseract not found — only needed for scanned PDFs; install later if you have any"
fi

echo ""
echo "=== 7. Smoke test (silent audio, no network, ~10 s) ==="
python main.py --sample --tts stub >/dev/null 2>&1 && ok "pipeline runs end to end" \
  || die "smoke test failed — run it by hand to see why: .venv/bin/python main.py --sample --tts stub"

echo ""
echo "=== 8. The launcher ==="
# macOS gives .command files to Terminal on a double-click; Linux has no such
# convention, so there it is a plain .sh you run or point a shortcut at.
if [ "$OS" = "Darwin" ]; then
  LAUNCHER="start-prosecast.command"
  OPENER='open "$URL"'
else
  LAUNCHER="start-prosecast.sh"
  OPENER='command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1'
fi
cat > "$LAUNCHER" <<LAUNCHER_EOF
#!/bin/bash
# Start ProseCast and open it in your browser.
#
# Written by SETUP.sh for this machine — generated, not authored. Re-running
# SETUP.sh rewrites it.
cd "\$(dirname "\$0")"
URL="http://localhost:8000"

# PYTHONUTF8 is belt and braces: every text read and write in ProseCast names
# its encoding (tests/test_encoding_guard.py) and it fixes its own streams
# (prosecast/console.py). It costs nothing to be sure.
export PYTHONUTF8=1

# Open the browser a few seconds in, so it does not arrive before uvicorn is
# listening. uvicorn itself stays in the foreground: closing this window stops
# the server, which is what someone who double-clicked a file expects.
( sleep 3; $OPENER ) &

# The venv's python by name, never an activated shell — the same rule the
# Windows launcher follows, and the reason Piper is run as a module.
exec ./.venv/bin/python -m uvicorn server:app --port 8000
LAUNCHER_EOF
chmod 755 "$LAUNCHER"
ok "wrote $LAUNCHER"

echo ""
if [ "$FAILED" -ne 0 ]; then
  printf '\033[31m=== Finished with problems — see the ✗ lines above. ===\033[0m\n'
  exit 1
fi
printf '\033[32m=== Done. ===\033[0m\n'
echo ""
echo "  It opens http://localhost:8000 in your browser. The first run walks"
echo "  you through four steps and ends by reading you the sample book."
echo ""
echo "  Copy and run this:"
printf '      \033[36m./%s\033[0m\n' "$LAUNCHER"
echo ""
echo "  The ⚙ Setup page is the full list of services, with the fix for each row."
echo ""

# Offering to start it saves a step today; the command is printed above FIRST,
# because that is the thing to remember tomorrow.
if ask "Start ProseCast now? [Y/n]" y; then
  echo ""
  exec "./$LAUNCHER"
fi
