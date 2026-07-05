# PROSECAST — STATUS

**Status:** Active
**Updated:** 2026-07-03

## Where it's at
Planning + triage session (no code changes). **PRD.md** now defines the dogfood MVP:
Tyler listens to Parade end-to-end, multi-voice, on his phone. Phases: A) Chatterbox
backend + listen test (THE GATE — no Chatterbox backend exists in tts_engine.py yet,
only the tag_mapper half) → B) cast review screen → C) resumable full-book render →
D) listen-through. **test_books/ATTRIBUTION_SCORECARD.md** scores all 6 books (Yumi
looks excellent rules-only: 22 clean speakers; Frankenstein attribution is actually
37.5% unresolved — the old "zero-error" result was tagging, not attribution).
**docs/market-research-communities-marketplaces.md** covers marketplace + community
models (ElevenLabs payouts, Nexus DP, SponsorBlock corrections, CCC talent pool,
NO FAKES Act implications).

## Next step
**Phase A smoke test (~10 min):** confirm Chatterbox-Turbo answers on Gideon
(`curl http://GIDEON_HOST:8101/docs` or its health route), generate ONE line of
dialogue via curl, listen to the WAV. If it sounds good → build the `chatterbox`
backend in tts_engine.py. If not → PRD gate fails, rethink render tier before
building anything else.

## Blocked on
Nothing. (LLM pass for Yumi/Frankenstein IR needs Ollama reachable — note
llm_attributor defaults to localhost:11434; from the Mac that means either local
Ollama or pointing it at Gideon.)

## Backup (2026-06-12)
- **Where:** `NAS_USER@GIDEON_HOST:/mnt/bolt/backups/prosecast/library/` (ZFS dataset `bolt/backups`, owned by NAS_USER)
- **What:** ir.json + voice_map.json + corrections.jsonl per book; renders/ and exports/ excluded (disposable). No `--delete` — local mistakes can't propagate.
- **Re-run:** `./scripts/backup_library.sh` (works from Mac or a Cowork session; log in `.backup/last_backup.log`)
- **Nightly:** `scripts/com.prosecast.backup.plist` → 21:30 daily once installed (see Next step)
- **Auth:** dedicated key `.backup/prosecast_backup_ed25519` (gitignored), registered in NAS_USER's SSH keys as "prosecast-backup (Cowork session key)" — delete that line in TrueNAS UI to revoke
- Initial backup verified 2026-06-12: 61/61 files, checksum-clean, IR readable from server

## Notes
- Run tests after touching attribution layers: `.venv/bin/pytest tests/ -v` (needs spaCy + en_core_web_sm; skips otherwise)
- All book paths via `prosecast/library.py` — `library/<slug>/{ir.json, voice_map.json, corrections.jsonl, renders/}`
- corrections.jsonl is append-only training flywheel data — never rewrite
- renders/ is disposable; everything else in a book dir is Tyler's labor — back it up
- Build queue: cast review screen, pipeline-in-UI jobs, per-chapter narrator dropdown
- Backup gap CLOSED — see Backup section above.
