"""
Tag Mapper — ProseCast Phase 4

Translates abstract IR tags into engine-specific render parameters.
IR stores human-readable actioning tags; each TTS engine interprets them differently.

Usage at render time:
    from prosecast.tag_mapper import map_tags
    engine_params = map_tags(block.get("tags"), engine_name)
    # engine_params is a dict of engine-specific kwargs; {} means no tag support.

Adding a new engine: implement _map_<engine>() and register it in _MAP_FNS.
Stub mappings for engines not yet live return {} — the interface is correct now.
"""

from typing import Optional


VALID_PACES = {"slow", "measured", "brisk", "urgent"}


def map_tags(tags: Optional[dict], engine: str) -> dict:
    """
    Translate abstract IR tags to engine-specific format.

    Returns a dict of engine-specific parameters, or {} if the engine
    has no tag support or tags is None/empty.
    """
    if not tags or not isinstance(tags, dict):
        return {}
    fn = _MAP_FNS.get(engine)
    return fn(tags) if fn else {}


# ── ElevenLabs ────────────────────────────────────────────────────────────────
#
# ElevenLabs voice_settings:
#   stability (0-1): lower = more expressive, more variable across sentences
#   similarity_boost (0-1): how closely voice matches the trained clone
#   style (0-1): style exaggeration — higher = more dramatic delivery
#   use_speaker_boost (bool): extra clarity pass

_EL_AGGRESSIVE = {"threaten", "demand", "confront", "assert", "command", "accuse", "intimidate"}
_EL_GENTLE = {"comfort", "reassure", "apologize", "plead", "console", "soothe", "confess"}


def _map_elevenlabs(tags: dict) -> dict:
    intensity = tags.get("intensity", 0.5)
    pace = tags.get("pace", "measured")
    action = tags.get("action", "").lower()

    # Base mappings: high intensity → less stable, more stylized
    stability = max(0.15, 0.85 - (intensity * 0.55))
    style = min(0.90, intensity * 0.75)

    if pace == "urgent":
        stability = max(0.10, stability - 0.10)
        style = min(0.95, style + 0.10)
    elif pace == "slow":
        stability = min(0.95, stability + 0.10)
        style = max(0.00, style - 0.05)

    if any(word in action for word in _EL_AGGRESSIVE):
        stability = max(0.10, stability - 0.05)
        style = min(0.95, style + 0.05)
    elif any(word in action for word in _EL_GENTLE):
        stability = min(0.95, stability + 0.05)
        style = max(0.00, style - 0.05)

    return {
        "voice_settings": {
            "stability": round(stability, 2),
            "similarity_boost": 0.75,
            "style": round(style, 2),
            "use_speaker_boost": True,
        }
    }


# ── Orpheus ───────────────────────────────────────────────────────────────────
#
# Orpheus TTS supports structured inline tags inserted into the text string:
#   <laugh>, <chuckle>, <sigh>, <cough>, <sniffle>, <groan>, <yawn>, <gasp>
# The mapping prepends the tag to the text at render time via "prefix_tag".
# Render layer is responsible for injecting prefix_tag into the text string.

_ORPHEUS_TAG_MAP = {
    "to laugh": "<laugh>",
    "to chuckle": "<chuckle>",
    "to share delight": "<chuckle>",
    "to mock": "<chuckle>",
    "to sigh": "<sigh>",
    "to resign": "<sigh>",
    "to give up": "<sigh>",
    "to grieve": "<sigh>",
    "to gasp": "<gasp>",
    "to express shock": "<gasp>",
    "to groan": "<groan>",
    "to complain bitterly": "<groan>",
    "to yawn": "<yawn>",
    "to cough": "<cough>",
    "to sniffle": "<sniffle>",
}


def _map_orpheus(tags: dict) -> dict:
    action = tags.get("action", "").lower()
    prefix_tag = None
    for key, val in _ORPHEUS_TAG_MAP.items():
        if key in action:
            prefix_tag = val
            break
    return {"prefix_tag": prefix_tag} if prefix_tag else {}


# ── Chatterbox ────────────────────────────────────────────────────────────────
#
# Chatterbox (devnen server) supports, on the *base* ResembleAI/chatterbox model:
#   exaggeration (0-1): amplifies emotion in the generated voice
#   cfg_weight (0-1):   generation guidance — affects pacing/adherence
# NOTE: on the Turbo model both exaggeration and cfg are ignored by the server.
#
# Rev 2 (2026-07-13 listen tests, Tyler's ears):
#   - `speed` REMOVED — the server's speed_factor is a post-process time-stretch
#     that smears the audio into an echo/reverb artifact. NEVER emit it.
#   - cfg_weight NOT emitted — listen tests swept 0.25/0.35/0.5/0.7/0.9 and the
#     server default (0.5) beat every deviation in both directions (higher got
#     faster + robotic, lower also read as fast). It's a stability knob, not a
#     pace knob. `pace` is therefore unmapped for chatterbox: punctuation and
#     sentence rhythm in the text carry pacing.
#   - exaggeration compressed to [0.20, 0.85] — at 1.0 the model appends a
#     mouth-noise artifact after the line; 0.7 carries clear emotion cleanly.
#     Known tradeoff: higher exaggeration natively speeds delivery a touch
#     (generation-time, artifact-free) — acceptable per 2026-07-13 listen.
#
# Mapping = base level from `intensity`, nudged by an emotion-arousal table.
# Keep this table small and legible — it's config, not cleverness.

# Emotion keyword buckets. Matched as substrings against the `emotion` phrase.
_CB_HIGH_AROUSAL = {
    "anger", "angry", "furious", "rage", "outrage",
    "excite", "thrill", "elat", "ecstat", "joy", "glee",
    "panic", "terror", "fear", "afraid", "frantic", "desperat",
    "shock", "alarm", "urgent", "manic",
}
_CB_LOW_AROUSAL = {
    "calm", "serene", "tranquil", "gentle", "tender", "soft",
    "sad", "grief", "sorrow", "melanchol", "somber", "wistful",
    "weary", "tired", "resign", "content", "contemplat", "reflect",
    "reserve", "solemn", "hush",
}


def _map_chatterbox(tags: dict) -> dict:
    intensity = tags.get("intensity", 0.5)
    emotion = str(tags.get("emotion", "")).lower()

    # Base exaggeration tracks intensity, compressed into the artifact-free band:
    # intensity 0.0 → 0.30, 0.5 → 0.55, 1.0 → 0.80.
    exaggeration = 0.30 + intensity * 0.50

    # Emotion arousal nudges up or down.
    if any(word in emotion for word in _CB_HIGH_AROUSAL):
        exaggeration += 0.10
    elif any(word in emotion for word in _CB_LOW_AROUSAL):
        exaggeration -= 0.10

    exaggeration = round(min(0.85, max(0.20, exaggeration)), 2)
    # Deliberately NO `speed`: speed_factor time-stretch = echo (see header note).
    # `pace` is currently unmapped for chatterbox until the cfg_weight direction
    # is confirmed by listening.
    return {"exaggeration": exaggeration}


# ── No-op engines ─────────────────────────────────────────────────────────────

def _map_none(_tags: dict) -> dict:
    return {}


_MAP_FNS = {
    "elevenlabs": _map_elevenlabs,
    "orpheus": _map_orpheus,
    "chatterbox": _map_chatterbox,
    # No tag support — return {} so callers don't need to special-case
    "piper": _map_none,
    "say": _map_none,
    "gtts": _map_none,
    "stub": _map_none,
}
