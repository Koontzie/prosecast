# PROSECAST — STATUS

**Status:** Active
**Updated:** 2026-06-10

## Where it's at
Pipeline solid (99.8% attribution on Parade; tagging validated on Frankenstein, zero errors). Repo live at `Koontzie/prosecast`. This session: hygiene pass + library/ restructure + **M4B export shipped** — `prosecast/m4b_export.py`, `--export-m4b` CLI flag, `POST /export/{slug}` + download endpoint, ⬇ Export M4B button in the UI. Verified end-to-end: ffprobe shows correct chapter markers, titles, and metadata. Needs ffmpeg on the Mac (`brew install ffmpeg`).

## Next step
At the Mac: `git push`, then (optional, recommended) install the nightly backup job:
`cp scripts/com.prosecast.backup.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.prosecast.backup.plist`
Then on to the next build: cast review screen / pipeline-in-UI / narrator dropdown.

## Blocked on
Nothing.

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
