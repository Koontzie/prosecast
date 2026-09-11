# AGENTS.md — ProseCast

Instructions for any coding agent working in this repo (Codex reads this file;
Claude Code reads `CLAUDE.md`). The two must not drift — change both together.

**`CLAUDE.md` is the full technical reference.** Read it, plus `HANDOFF.md`
(current state, supersedes anything that contradicts it) and `STATUS.md` (the
running log). This file carries only the rules that are dangerous to miss.

## Before you touch the GPU — read this first

Goldeye has **one** RTX 3090 Ti, and more than one agent session runs against
it at a time (Claude Code, Codex, Cowork). Sessions have broken each other's
work: unloading a model another session was mid-render on, restarting
`chatterbox-tts` during a live voice session, loading a 32B while the voice
stack was up.

**Take the lease before any command that loads, unloads, or restarts a
GPU-resident service** — `ollama run/stop/pull`, restarting `chatterbox-tts` /
`faster-whisper` / `comfyui` — and before starting a long render:

```
ssh "$GOLDEYE_HOST" '/mnt/bolt/ai/scripts/gpu-lease.sh \
  guard prosecast "<what you are doing>" -- <command>'
```

Check first: `ssh "$GOLDEYE_HOST" '/mnt/bolt/ai/scripts/gpu-lease.sh status'`

- **If it reports HELD, another project is mid-work. Stop.** Do not run the
  command anyway. Do not `steal` without asking Tyler first.
- `guard` releases on any exit, including failure and Ctrl-C — prefer it over
  bare `acquire` / `release`.
- A crashed session's lease clears itself after 15 minutes with no heartbeat.
- Short HTTP calls to Chatterbox do **not** need the lease. This is for model
  lifecycle and long renders, not every request.

`$GOLDEYE_HOST` is exported from the shell profile. **Never hardcode the host
or its IP into this repo.**

## Repo-specific rules that have cost real time

- **Commit to the Mac as you go.** Work that exists only in a cloud container
  is not work; a whole feature was lost that way on 2026-09-04.
- **Never hand-write a UI fixture or mock.** `tests/fixtures/*.json` come from
  the live endpoints via `scripts/refresh_ui_fixtures.py`.
- **After touching `static/index.html`, run all four checks in `tests/ui/`.**
- **No host names, IPs, or home-network details in this repo.** Its history was
  rewritten once to scrub exactly that, and it is going public under GPL.
- Every `ir.json` write goes through `lib.write_json_atomic()`; all book paths
  go through `prosecast/library.py`; `corrections.jsonl` is append-only; never
  rename WAVs on the Chatterbox server; never emit `speed` to Chatterbox.
