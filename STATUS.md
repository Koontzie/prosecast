# PROSECAST — STATUS

**Status:** Active
**Updated:** 2026-06-10

## Where it's at
Pipeline solid (99.8% attribution on Parade; tagging validated on Frankenstein, zero errors). Repo live at `Koontzie/prosecast`. This session: hygiene pass + library/ restructure + **M4B export shipped** — `prosecast/m4b_export.py`, `--export-m4b` CLI flag, `POST /export/{slug}` + download endpoint, ⬇ Export M4B button in the UI. Verified end-to-end: ffprobe shows correct chapter markers, titles, and metadata. Needs ffmpeg on the Mac (`brew install ffmpeg`).

## Next step
Push this session's commits, then render a real book chapter (say or ElevenLabs) and export a real m4b to play in Apple Books — first true end-product test.

## Blocked on
Nothing.

## Notes
- Run tests after touching attribution layers: `.venv/bin/pytest tests/ -v` (needs spaCy + en_core_web_sm; skips otherwise)
- All book paths via `prosecast/library.py` — `library/<slug>/{ir.json, voice_map.json, corrections.jsonl, renders/}`
- corrections.jsonl is append-only training flywheel data — never rewrite
- renders/ is disposable; everything else in a book dir is Tyler's labor — back it up
- Build queue: cast review screen, pipeline-in-UI jobs, per-chapter narrator dropdown
- Backup gap: library/ exists only on this Mac (gitignored — contains book text). Candidate: rsync to Bolt on Gideon.
