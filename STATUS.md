# PROSECAST — STATUS

**Status:** Active
**Updated:** 2026-06-10

## Where it's at
Pipeline solid (99.8% attribution on Parade; tagging validated on Frankenstein, zero errors). This session: git initialized (3+ commits), requirements.txt + golden tests added, corrections journal wired in, and output/ restructured into per-book `library/<slug>/` (all paths via `prosecast/library.py`). 5.5GB of disposable test renders deleted. GitHub push still pending.

## Next step
Create `Koontzie/prosecast` on GitHub and push (PAT in 1Password: "GitHub PAT — CLAIY+Mac"). Then: M4B chapterized export (agreed next build).

## Blocked on
Nothing — GitHub push just needs Tyler at the keyboard for the PAT.

## Notes
- Run tests after touching attribution layers: `.venv/bin/pytest tests/ -v` (needs spaCy + en_core_web_sm; skips otherwise)
- All book paths via `prosecast/library.py` — `library/<slug>/{ir.json, voice_map.json, corrections.jsonl, renders/}`
- corrections.jsonl is append-only training flywheel data — never rewrite
- renders/ is disposable; everything else in a book dir is Tyler's labor — back it up
- Build queue after M4B: cast review screen, pipeline-in-UI jobs, per-chapter narrator dropdown
