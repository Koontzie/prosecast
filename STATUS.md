# PROSECAST — STATUS

**Status:** Active
**Updated:** 2026-06-10

## Where it's at
Pipeline solid (99.8% attribution on Parade; tagging validated on Frankenstein, zero errors). This session: project hygiene — git initialized, stray file removed, requirements.txt + tests added, corrections journal wired into server.py. GitHub push still pending.

## Next step
Create `Koontzie/prosecast` on GitHub and push (PAT in 1Password: "GitHub PAT — CLAIY+Mac").

## Blocked on
Nothing — GitHub push just needs Tyler at the keyboard for the PAT.

## Notes
- Run tests after touching attribution layers: `.venv/bin/pytest tests/ -v`
- Corrections journal: `output/{slug}_corrections.jsonl` — append-only, training flywheel data, never rewrite
- Agreed roadmap (not yet built): library/ restructure of output/, pipeline-in-UI jobs, cast review screen, per-chapter narrator dropdown, m4b export
- output/ is ~5.8 GB, mostly disposable `say`-engine test renders; IR JSONs + voice maps + corrections journals are the precious part
