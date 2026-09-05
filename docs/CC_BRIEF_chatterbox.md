# CC BRIEF — Wire the Chatterbox backend into ProseCast

**Written 2026-07-10 for an autonomous Claude Code run in `~/dev/prosecast`.**
**This brief has 7 steps (0–6). If you have not reached the `END OF BRIEF` line, you are NOT done.**
Run them in order. Verify as you go. When blocked, STOP and write the blocker to STATUS.md — do not guess.

---

## Mission
Add a `chatterbox` engine to the TTS pipeline so ProseCast can render dialogue on the local
devnen Chatterbox-TTS-Server (`http://GIDEON_HOST:8101`), cloning a per-character reference clip
for voice identity and driving emotion via `exaggeration`/`speed` from the existing tag mapper.
Do NOT change server state, do NOT touch precious data, do NOT push to any remote.

## Guardrails (read before touching anything)
- **GREEN (do autonomously):** edit `prosecast/tts_engine.py`, `prosecast/tag_mapper.py`; add files
  under `scripts/` and `tests/`; update `STATUS.md`; make a LOCAL `git commit` (no push).
- **YELLOW (leave for Tyler — do NOT do):** switching the server model Turbo→base; uploading voices;
  anything that POSTs to the server (`/save_settings`, `/restart_server`, `/upload_reference`,
  `/api/unload`). You may only GET from the server (read-only).
- **RED (never):** modify or delete `library/**/ir.json`, `voice_map.json`, or `corrections.jsonl`;
  delete anything in `library/`; spend money; `git push`.
- `renders/` is disposable; everything else in a book dir is Tyler's labor. Leave it alone.

## Smallest healthy-loop check (Tyler verifies this before walking away)
After Step 2, you must run `.venv/bin/pytest tests/ -v`. If it's green, the loop is healthy.
If the server was unreachable in Step 1, you must have STOPPED there — that's the expected early exit.

---

## Step 0 — Orient
Read, in this order: `PROJECT_REFERENCE*.md` (if present), `CLAUDE.md`, `STATUS.md`, `docs/PRD.md`, then
`prosecast/tts_engine.py` and `prosecast/tag_mapper.py`. Note the existing ElevenLabs backend
(`_synthesize_elevenlabs`, `test_elevenlabs_connection`) and the `VoiceAssigner` pools — you are
mirroring those patterns, not inventing new ones.

## Step 1 — Pull the REAL server contract (read-only; build against reality, not assumptions)
The PRD explicitly warns: do not trust the tag_mapper's assumed endpoint contract. So fetch it:
```
curl -sS -m 10 http://GIDEON_HOST:8101/openapi.json      # inspect the POST /tts requestBody schema
curl -sS -m 10 http://GIDEON_HOST:8101/api/model-info    # which model is loaded (base vs turbo)
curl -sS -m 10 http://GIDEON_HOST:8101/get_reference_files
curl -sS -m 10 http://GIDEON_HOST:8101/get_predefined_voices
```
Write a short `docs/chatterbox-contract.md` capturing: the exact `/tts` field names (text, voice mode,
reference-filename field, `exaggeration`, `cfg_weight`, `temperature`, `speed_factor`, `seed`,
`output_format`), and the shapes of the reference/predefined voice lists.
**BLOCKER RULE:** if the server does not respond (timeout / connection refused), STOP now. Write to
STATUS.md "Blocked on: Chatterbox server unreachable from this machine (Tailscale?)" and end the run.
Do not fabricate the contract.

## Step 2 — Implement the backend (`prosecast/tts_engine.py`)
Mirror the ElevenLabs backend exactly one tier over:
- `_synthesize_chatterbox(text, voice_cfg, out_path)` → POST to `/tts` using the field names from
  Step 1, in **clone** mode with the character's reference filename, passing
  `exaggeration`/`cfg_weight`/`speed` from `map_tags(tags, "chatterbox")`. Handle non-200 by printing
  the server body (never swallow errors silently).
- `test_chatterbox_connection()` → mirror `test_elevenlabs_connection()`; GET a cheap route and print
  `[Chatterbox] Connection OK ✓` or a clear failure.
- **Turbo guard:** in the connection check, GET `/api/model-info`; if the loaded model is a *turbo*
  variant, print a LOUD warning: `[Chatterbox] WARNING: turbo model loaded — exaggeration/cfg are
  IGNORED; emotion tags will not affect delivery. Switch the server to base ResembleAI/chatterbox.`
  (This is the silent-failure trap we already hit — make it impossible to miss.)
- Add a `CHATTERBOX_VOICES` pool + `engine == 'chatterbox'` branch in `VoiceAssigner`, following the
  same narrator=slot-0 / round-robin pattern. Populate the pool from `/get_reference_files` at runtime
  when reachable; fall back to a small static list of whatever filenames Step 1 returned.
- Wire `chatterbox` into `_voice_id_to_cfg`, `get_voice`, `summary`, and the engine dispatch, plus the
  auto-detect priority (leave ElevenLabs highest when a key is present; chatterbox is the local default).

## Step 3 — Finish the tag mapping (`prosecast/tag_mapper.py`)
The `speed` param for chatterbox is currently a stub (per PRD). Implement a sensible emotion→
`exaggeration` + `speed` table (e.g., calm→low exaggeration/slightly slower; angry/excited→higher
exaggeration/faster). Keep it small and legible; it's config, not cleverness.

## Step 4 — Smoke-test helper (`scripts/chatterbox_smoke.py`)
A tiny CLI so Tyler can render ONE line and listen. Args: `--text`, `--voice` (reference filename,
default = first entry from `/get_reference_files`, else first predefined voice), `--emotion`
(default "neutral"). It renders via the new backend to `output/chatterbox_smoke.wav` and prints the
path. Must work whether or not the VCTK voices have been uploaded yet (fall back to an existing voice).

## Step 5 — Verify (no regressions, no touching precious data)
Run `.venv/bin/pytest tests/ -v`. If a golden test needs a chatterbox fixture, add a mocked/stubbed
one — do NOT hit the network in tests and do NOT modify any `ir.json`/`voice_map.json`/`corrections.jsonl`.
All previously-passing tests must still pass.

## Step 6 — Chapter-close handoff
Update `STATUS.md` (this project's file ONLY — never the master dashboard):
- "Where it's at": chatterbox backend wired; contract captured in `docs/chatterbox-contract.md`.
- "Next step": the two YELLOW items that need Tyler — (1) switch the server to base
  `ResembleAI/chatterbox` (Turbo ignores exaggeration), (2) upload VCTK voices via
  `scripts/stage_vctk_voices.py --from-dir ./vctk_voices --upload-to …` — then run
  `.venv/bin/python scripts/chatterbox_smoke.py` and LISTEN (the Phase A gate).
- "Blocked on": whatever's true (likely "nothing — awaiting Tyler's listen test").
Then make a local WIP commit: `git add -A && git commit -m "Wire chatterbox backend (CC brief 2026-07-10)"`.
Do NOT push (repo isn't on GitHub yet).

---

## What you are explicitly NOT doing (leave for Tyler)
- Switching the server model (his infra).
- Uploading voices or any server-state POST.
- Judging audio quality — only Tyler can run the listen test.

END OF BRIEF
