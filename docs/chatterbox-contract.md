# Chatterbox-TTS-Server contract (captured 2026-07-10)

Server: **devnen Chatterbox-TTS-Server** at `http://GIDEON_HOST:8101` (Gideon, Tailscale).
Captured read-only from `/openapi.json`, `/api/model-info`, `/get_reference_files`,
`/get_predefined_voices`. This is the ground truth — do **not** trust the tag_mapper's
older assumptions over this file.

## Loaded model (from `GET /api/model-info`)

```json
{
  "loaded": true,
  "type": "turbo",
  "class_name": "ChatterboxTurboTTS",
  "device": "cuda",
  "sample_rate": 24000,
  "supports_paralinguistic_tags": true,
  "available_paralinguistic_tags": ["laugh","chuckle","sigh","gasp","cough","clear throat","sniff","groan","shush"],
  "supports_multilingual": false,
  "supported_languages": {"en": "English"}
}
```

> **⚠ Turbo caveat.** `type == "turbo"` (`ChatterboxTurboTTS`). On the Turbo variant the
> `exaggeration` / `cfg_weight` controls are **ignored** — emotion tags will NOT change
> delivery. To get emotion-driven delivery Tyler must switch the server to the base
> `ResembleAI/chatterbox` model. The connection check prints a LOUD warning when it sees a
> turbo model so this silent-failure trap is impossible to miss.
>
> Note: this Turbo build *does* advertise `supports_paralinguistic_tags` (inline `[laugh]`,
> `[sigh]`, etc.), which is a separate expressive channel from `exaggeration`. We are not
> wiring those in this pass — they belong to the tag_mapper's Orpheus-style path, not the
> exaggeration/speed path.

## `POST /tts` — request body (`CustomTTSRequest`)

Content-Type `application/json`. Returns the audio file bytes (WAV by default).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `text` | string (min 1) | — | **required.** Text to synthesize. |
| `voice_mode` | `"predefined"` \| `"clone"` | `"predefined"` | Use `clone` for per-character reference clips. |
| `predefined_voice_id` | string \| null | — | Filename of a built-in voice. Required when `voice_mode == "predefined"`. |
| `reference_audio_filename` | string \| null | — | Filename of an uploaded reference clip. Required when `voice_mode == "clone"`. |
| `output_format` | `"wav"` \| `"opus"` \| `"mp3"` | `"wav"` | We request `wav`. |
| `split_text` | bool \| null | `true` | Auto-split long text into chunks. |
| `chunk_size` | int 50–500 \| null | `120` | Target chunk length when splitting. |
| `temperature` | number \| null | server default | |
| `exaggeration` | number \| null | server default | Emotion amplitude (0–1). **Ignored on Turbo.** |
| `cfg_weight` | number \| null | server default | CFG guidance weight. **Ignored on Turbo.** |
| `seed` | int \| null | server default | |
| `speed_factor` | number \| null | server default | Delivery speed multiplier. This is the real field name — the mapper's old `speed` key must be translated to `speed_factor`. |
| `language` | string \| null | server default | Only `en` supported on this build. |
| `stream` | bool | `false` | If true, streams WAV chunks; `output_format` ignored. We use non-streaming. |

### Field-name reconciliation (mapper → server)

`map_tags(tags, "chatterbox")` returns `{"exaggeration", "cfg_weight", "speed"}`. When
building the `/tts` payload the backend maps:

- `exaggeration` → `exaggeration`
- `cfg_weight`   → `cfg_weight`
- `speed`        → `speed_factor`  ← **name differs**

## Voice inventory (captured 2026-07-10)

`GET /get_reference_files` (clone-mode references — user-uploaded clips):
```json
["Gianna.wav", "Robert.wav"]
```

`GET /get_predefined_voices` (built-in voices):
```json
[
  {"display_name": "Panelselftest", "filename": "PanelSelftest.wav"},
  {"display_name": "Robert",        "filename": "Robert.wav"},
  {"display_name": "Scarjo Voice",  "filename": "ScarJo_Voice.wav"}
]
```

The VCTK per-character reference clips are **not yet uploaded** (only Gianna/Robert exist as
references). The backend populates its clone pool from `/get_reference_files` at runtime and
falls back to this static list when the server is unreachable.

## Other endpoints (for reference — do NOT POST to the write ones)

- `GET  /api/model-info` — model status (used by the Turbo guard).
- `GET  /api/ui/initial-data` — full UI bootstrap payload.
- `GET  /get_reference_files` — clone references.
- `GET  /get_predefined_voices` — built-in voices.
- `GET  /v1/audio/voices` — OpenAI-compatible voices list.
- `POST /v1/audio/speech` — OpenAI-compatible speech endpoint (alternative to `/tts`).
- `POST /save_settings`, `/reset_settings`, `/restart_server`, `/api/unload`,
  `/upload_reference`, `/upload_predefined_voice` — **YELLOW/write; Tyler-only, do not call.**
