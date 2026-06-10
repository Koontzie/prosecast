#!/bin/bash
# ProseCast — one-shot local setup
# Run from the project root.
set -e

echo "=== Creating venv (.venv) if missing ==="
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate

echo ""
echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo ""
echo "=== Installing spaCy language model ==="
python -m spacy download en_core_web_sm

echo ""
echo "=== ffmpeg (optional — only needed for pydub MP3 merging) ==="
command -v ffmpeg >/dev/null || echo "ffmpeg not found. macOS: brew install ffmpeg | Debian/Ubuntu: sudo apt install ffmpeg"

echo ""
echo "=== Testing the pipeline with sample text ==="
python main.py --sample --tts stub

echo ""
echo "=== Done! Next steps: ==="
echo "  .venv/bin/python main.py --book yourbook.epub --ir-only   # fast IR test"
echo "  .venv/bin/python main.py --book yourbook.epub --tts say   # real voices"
echo "  .venv/bin/uvicorn server:app --reload                     # web UI"
