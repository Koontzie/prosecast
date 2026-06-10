#!/bin/bash
# Polycast Phase 1 — one-shot local setup
# Run this from the polycast/ directory

echo "=== Installing Python dependencies ==="
pip install ebooklib beautifulsoup4 lxml spacy gtts pydub python-multipart

echo ""
echo "=== Installing spaCy language model ==="
python -m spacy download en_core_web_sm

echo ""
echo "=== Installing ffmpeg (needed for pydub MP3 output) ==="
# macOS:
command -v brew && brew install ffmpeg
# Linux (Debian/Ubuntu):
command -v apt && sudo apt install -y ffmpeg

echo ""
echo "=== Testing the pipeline with sample text ==="
python main.py --sample --tts stub

echo ""
echo "=== Done! Now try with a real book: ==="
echo "  python main.py --book yourbook.epub --ir-only    # fast IR test"
echo "  python main.py --book yourbook.epub --tts gtts   # real voices"
