#!/bin/bash
# ProseCast — one-shot local setup.
#
# Run from the project root:   bash SETUP.sh
# Safe to re-run: every step checks before it acts.
#
# What it does, in order:
#   1. checks Python is 3.11+ and creates .venv if missing
#   2. installs the Python dependencies (requirements.txt)
#   3. downloads the spaCy English model and PROVES it loads
#   4. creates config.json from config.example.json if you don't have one
#   5. checks the external tools (ffmpeg required; tesseract only for scans)
#   6. runs a silent end-to-end smoke test of the pipeline
# Then tells you how to start the server. Nothing here needs a GPU.
set -e

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }

cd "$(dirname "$0")"

echo "=== 1. Python ==="
command -v python3 >/dev/null || fail "python3 not found. Install Python 3.11 or newer first."
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python $PYV found; ProseCast needs 3.11 or newer."
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
echo "=== 3. spaCy English model (for 'who is speaking') ==="
if python -c 'import spacy; spacy.load("en_core_web_sm")' 2>/dev/null; then
  ok "en_core_web_sm already loads"
else
  python -m spacy download en_core_web_sm >/dev/null
  python -c 'import spacy; spacy.load("en_core_web_sm")' \
    || fail "spaCy model downloaded but does not load — run: .venv/bin/python -m spacy download en_core_web_sm"
  ok "en_core_web_sm downloaded and loads"
fi

echo ""
echo "=== 4. config.json ==="
if [ -f config.json ]; then
  ok "config.json exists (left untouched)"
else
  cp config.example.json config.json
  ok "created config.json from config.example.json — no engine chosen yet, so the app opens its setup wizard on first run"
fi

echo ""
echo "=== 5. External tools ==="
if command -v ffmpeg >/dev/null; then
  ok "ffmpeg: $(command -v ffmpeg)"
else
  warn "ffmpeg not found — REQUIRED for M4B export and voice-clip prep."
  warn "  macOS: brew install ffmpeg   Debian/Ubuntu: sudo apt install ffmpeg   Windows: ffmpeg.org, add to PATH"
fi
if command -v tesseract >/dev/null; then
  ok "tesseract: $(command -v tesseract) (scanned PDFs can be OCR'd)"
else
  ok "tesseract not found — only needed for scanned PDFs; install later if you have any"
fi
case "$(uname -s)" in
  Darwin) command -v say >/dev/null && ok "macOS 'say' voices available — the zero-setup voice tier" ;;
  *)      if command -v piper >/dev/null; then ok "piper found — the no-GPU voice tier";
          else warn "no built-in voice engine on this OS: install piper (no GPU) or point config.json at a Chatterbox server"; fi ;;
esac

echo ""
echo "=== 6. Smoke test (silent audio, no network, ~10 s) ==="
python main.py --sample --tts stub >/dev/null 2>&1 && ok "pipeline runs end to end" \
  || fail "smoke test failed — run it by hand to see why: .venv/bin/python main.py --sample --tts stub"

echo ""
echo "=== Done. Start the app: ==="
echo "  .venv/bin/uvicorn server:app --port 8000"
echo "  then open http://localhost:8000 — it lands on the Setup page and shows"
echo "  what is green, what is missing, and how to fix each row."
