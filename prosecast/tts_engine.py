"""
TTS Engine — ProseCast

Supports: elevenlabs (premium, API), piper (local), say (macOS), gtts (Google TTS), stub (silent WAV)
"""

import hashlib
import json
import os
import wave
from pathlib import Path

# Load .env from project root (two levels up from this file: prosecast/ → project root)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


# ── Voice Assigner ────────────────────────────────────────────────────────────

class VoiceAssigner:
    """Maps speaker names to TTS voice configs."""

    # ElevenLabs standard library voices — id is the opaque API identifier, name is display label.
    # Index 0 (Sarah) is reserved for NARRATOR; rest round-robin for characters.
    ELEVENLABS_VOICES = [
        {'id': 'EXAVITQu4vr4xnSDxMaL', 'name': 'Sarah'},    # warm, female — narrator default
        {'id': 'onwK4e9ZLuTAKqWW03F9', 'name': 'Daniel'},   # deep, male
        {'id': '9BWtsMINqrJLrRacOk9x', 'name': 'Aria'},     # expressive, female
        {'id': 'IKne3meq5aSn9XLyUdCD', 'name': 'Charlie'},  # casual, male
        {'id': 'XrExE9yKIg1WjnnlVkGX', 'name': 'Matilda'},  # friendly, female
    ]

    GTTS_VOICES = [
        {'tld': 'com',    'slow': False},   # US English (narrator default)
        {'tld': 'co.uk',  'slow': False},   # British
        {'tld': 'com.au', 'slow': False},   # Australian
        {'tld': 'ca',     'slow': False},   # Canadian
        {'tld': 'co.in',  'slow': False},   # Indian
    ]

    PIPER_VOICES = [
        'en_US-lessac-medium',
        'en_US-ryan-medium',
        'en_GB-alan-medium',
        'en_US-kusal-medium',
    ]

    SAY_VOICES = [
        'Samantha',
        'Daniel',
        'Karen',
        'Moira',
        'Tessa',
    ]

    def __init__(self, engine: str = 'stub'):
        self.engine = engine
        self._map = {}        # speaker → voice config
        self._pool_idx = 0    # next index for character voices (skip index 0 = narrator)
        self._voice_map = {}  # explicit speaker → voice_id overrides from voice_map.json

    def load_voice_map(self, voice_map: dict):
        """Load explicit speaker → voice_id assignments from a saved voice_map.json.

        Entries are applied before auto-assignment. Unknown speakers still fall
        back to the round-robin pool.
        """
        self._voice_map = voice_map or {}

    def _voice_id_to_cfg(self, voice_id: str) -> dict:
        """Convert a plain voice ID string to the engine-specific config dict."""
        if self.engine == 'gtts':
            return {'tld': voice_id, 'slow': False}
        elif self.engine in ('piper', 'say'):
            return {'voice': voice_id}
        elif self.engine == 'elevenlabs':
            return {'voice_id': voice_id}
        return {}

    def get_voice(self, speaker: str) -> dict:
        if speaker in self._map:
            return self._map[speaker]

        # Explicit override from voice_map.json takes priority over auto-assign
        if speaker in self._voice_map:
            cfg = self._voice_id_to_cfg(self._voice_map[speaker])
            self._map[speaker] = cfg
            return cfg

        if self.engine == 'elevenlabs':
            pool = self.ELEVENLABS_VOICES
            if speaker == 'NARRATOR':
                cfg = {'voice_id': pool[0]['id']}
            else:
                idx = (self._pool_idx % (len(pool) - 1)) + 1
                cfg = {'voice_id': pool[idx]['id']}
                self._pool_idx += 1
        elif self.engine == 'gtts':
            if speaker == 'NARRATOR':
                cfg = {'tld': 'com', 'slow': False}
            else:
                # Start at index 1 to reserve index 0 for narrator
                idx = (self._pool_idx % (len(self.GTTS_VOICES) - 1)) + 1
                cfg = self.GTTS_VOICES[idx]
                self._pool_idx += 1
        elif self.engine == 'piper':
            if speaker == 'NARRATOR':
                cfg = {'voice': self.PIPER_VOICES[0]}
            else:
                idx = (self._pool_idx % (len(self.PIPER_VOICES) - 1)) + 1
                cfg = {'voice': self.PIPER_VOICES[idx]}
                self._pool_idx += 1
        elif self.engine == 'say':
            if speaker == 'NARRATOR':
                cfg = {'voice': self.SAY_VOICES[0]}
            else:
                idx = (self._pool_idx % (len(self.SAY_VOICES) - 1)) + 1
                cfg = {'voice': self.SAY_VOICES[idx]}
                self._pool_idx += 1
        else:
            cfg = {}

        self._map[speaker] = cfg
        return cfg

    def summary(self) -> str:
        if not self._map:
            return '(no voices assigned)'
        # Build a reverse map from voice_id → name for ElevenLabs display
        el_id_to_name = {v['id']: v['name'] for v in self.ELEVENLABS_VOICES}
        parts = []
        for speaker, cfg in self._map.items():
            if self.engine == 'elevenlabs':
                vid = cfg.get('voice_id', '?')
                parts.append(f"{speaker}→{el_id_to_name.get(vid, vid)}")
            elif self.engine == 'gtts':
                parts.append(f"{speaker}→{cfg.get('tld', '?')}")
            elif self.engine in ('piper', 'say'):
                parts.append(f"{speaker}→{cfg.get('voice', '?')}")
            else:
                parts.append(f"{speaker}→stub")
        return ', '.join(parts)


# ── Stub backend ──────────────────────────────────────────────────────────────

def _write_stub_wav(path: str, duration_ms: int = 400):
    sample_rate = 22050
    n_samples = int(sample_rate * duration_ms / 1000)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b'\x00\x00' * n_samples)


# ── gTTS backend ──────────────────────────────────────────────────────────────

def _synthesize_gtts(text: str, voice_cfg: dict, out_path: str) -> bool:
    try:
        import io
        import wave
        from gtts import gTTS
        import miniaudio

        # Stream MP3 bytes from Google TTS into memory
        tts = gTTS(text=text, lang='en', tld=voice_cfg.get('tld', 'com'),
                   slow=voice_cfg.get('slow', False))
        mp3_buf = io.BytesIO()
        tts.write_to_fp(mp3_buf)
        mp3_bytes = mp3_buf.getvalue()

        # Decode MP3 → raw PCM using miniaudio (no ffmpeg needed)
        decoded = miniaudio.decode(mp3_bytes, output_format=miniaudio.SampleFormat.SIGNED16)

        # Write PCM frames to a proper WAV file
        with wave.open(out_path, 'wb') as wf:
            wf.setnchannels(decoded.nchannels)
            wf.setsampwidth(2)  # SIGNED16 = 2 bytes per sample
            wf.setframerate(decoded.sample_rate)
            wf.writeframes(decoded.samples.tobytes())

        return True
    except Exception as e:
        print(f"    [gTTS error] {e}")
        return False


# ── Piper backend ─────────────────────────────────────────────────────────────

def _synthesize_piper(text: str, voice_cfg: dict, out_path: str) -> bool:
    import subprocess
    voice = voice_cfg.get('voice', 'en_US-lessac-medium')
    try:
        proc = subprocess.run(
            ['piper', '--model', voice, '--output_file', out_path],
            input=text, capture_output=True, text=True, timeout=30
        )
        return proc.returncode == 0 and os.path.exists(out_path)
    except FileNotFoundError:
        print("    [Piper] piper not found in PATH")
        return False
    except Exception as e:
        print(f"    [Piper error] {e}")
        return False


# ── macOS say backend ────────────────────────────────────────────────────────

def _synthesize_say(text: str, voice_cfg: dict, out_path: str) -> bool:
    import subprocess

    voice = voice_cfg.get('voice', 'Samantha')
    aiff_path = str(Path(out_path).with_suffix('.aiff'))
    try:
        subprocess.run(
            ['say', '-v', voice, '-o', aiff_path],
            input=text,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        subprocess.run(
            ['afconvert', '-f', 'WAVE', '-d', 'LEI16@22050', aiff_path, out_path],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return os.path.exists(out_path)
    except FileNotFoundError as e:
        print(f"    [say] missing tool: {e}")
        return False
    except Exception as e:
        print(f"    [say error] {e}")
        return False
    finally:
        if os.path.exists(aiff_path):
            os.remove(aiff_path)


# ── ElevenLabs backend ───────────────────────────────────────────────────────

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ELEVENLABS_USER_URL = "https://api.elevenlabs.io/v1/user"


def _elevenlabs_api_key() -> str:
    return os.environ.get("ELEVENLABS_API_KEY", "")


def test_elevenlabs_connection() -> bool:
    """Lightweight connectivity check — synthesizes a single silent character to confirm
    the API key is valid and the TTS endpoint is reachable.

    Uses /v1/voices (no special permissions required) rather than /v1/user.
    """
    import urllib.request
    import urllib.error
    key = _elevenlabs_api_key()
    if not key:
        print("[ElevenLabs] No API key found. Set ELEVENLABS_API_KEY in .env")
        return False
    try:
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": key},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            ok = resp.status == 200
            if ok:
                print("[ElevenLabs] Connection OK ✓")
            else:
                print(f"[ElevenLabs] Connection check returned HTTP {resp.status}")
            return ok
    except urllib.error.HTTPError as e:
        print(f"[ElevenLabs] Connection failed: HTTP {e.code} — check your API key")
        return False
    except Exception as e:
        print(f"[ElevenLabs] Connection failed: {e}")
        return False


def _synthesize_elevenlabs(text: str, voice_cfg: dict, out_path: str) -> bool:
    import io
    import urllib.request
    import urllib.error
    import wave
    import miniaudio

    voice_id = voice_cfg.get("voice_id", "")
    if not voice_id:
        print("    [ElevenLabs] No voice_id in config")
        return False

    key = _elevenlabs_api_key()
    if not key:
        print("    [ElevenLabs] No API key — set ELEVENLABS_API_KEY in .env")
        return False

    payload = json.dumps({
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode()

    url = ELEVENLABS_TTS_URL.format(voice_id=voice_id)
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            mp3_bytes = resp.read()
    except urllib.error.HTTPError as e:
        print(f"    [ElevenLabs] HTTP {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f"    [ElevenLabs error] {e}")
        return False

    try:
        decoded = miniaudio.decode(mp3_bytes, output_format=miniaudio.SampleFormat.SIGNED16)
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(decoded.nchannels)
            wf.setsampwidth(2)
            wf.setframerate(decoded.sample_rate)
            wf.writeframes(decoded.samples.tobytes())
        return True
    except Exception as e:
        print(f"    [ElevenLabs decode error] {e}")
        return False


# ── Engine ────────────────────────────────────────────────────────────────────

class TTSEngine:
    def __init__(self, engine: str = None):
        if engine:
            self.engine = engine
        else:
            self.engine = self._detect()
        self.assigner = VoiceAssigner(engine=self.engine)
        print(f"[TTS] Engine: {self.engine}")
        if self.engine == 'elevenlabs':
            test_elevenlabs_connection()

    def load_voice_map(self, voice_map: dict):
        """Pass a saved {speaker: voice_id} map to the assigner before rendering."""
        self.assigner.load_voice_map(voice_map)

    def _detect(self) -> str:
        # ElevenLabs is highest priority — if API key is present, use it
        if os.environ.get("ELEVENLABS_API_KEY", "").strip():
            return 'elevenlabs'
        try:
            import subprocess
            r = subprocess.run(['piper', '--help'], capture_output=True, timeout=3)
            if r.returncode == 0:
                return 'piper'
        except Exception:
            pass
        try:
            import subprocess
            r = subprocess.run(['say', '-v', '?'], capture_output=True, timeout=3)
            if r.returncode == 0:
                return 'say'
        except Exception:
            pass
        try:
            from gtts import gTTS
            return 'gtts'
        except ImportError:
            pass
        return 'stub'

    def _cache_key(self, text: str, voice_cfg: dict) -> str:
        payload = text + json.dumps(voice_cfg, sort_keys=True) + self.engine
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def synthesize_segment(self, segment: dict, out_path: str) -> bool:
        """Synthesize audio for a segment dict, updating audioVariants in place.

        Skips synthesis if the standard variant is already cached.
        Computes and stores cacheKey, url, and cached flag on success.
        """
        speaker = segment.get("speaker") or "NARRATOR"
        if segment.get("unresolved"):
            speaker = "NARRATOR"
        text = segment.get("text", "")
        if not text.strip():
            return False

        voice_cfg = self.assigner.get_voice(speaker)
        cache_key = self._cache_key(text, voice_cfg)

        # Skip synthesis only when the file exists AND the cache key matches the
        # current engine+voice config.  A stale key (e.g. switching from say →
        # elevenlabs) forces re-synthesis even if the file is present.
        variant = segment.get("audioVariants", {}).get("standard", {})
        if (variant.get("cached")
                and variant.get("url")
                and os.path.exists(variant["url"])
                and segment.get("cacheKey") == cache_key):
            return True

        ok = self.synthesize(text, speaker, out_path)
        if ok:
            segment.setdefault("audioVariants", {
                "standard": {"url": None, "cached": False},
                "premium":  {"url": None, "cached": False},
            })
            segment["audioVariants"]["standard"]["url"] = out_path
            segment["audioVariants"]["standard"]["cached"] = True
            segment["cacheKey"] = cache_key
        return ok

    def synthesize(self, text: str, speaker: str, out_path: str) -> bool:
        voice_cfg = self.assigner.get_voice(speaker)
        if self.engine == 'stub':
            _write_stub_wav(out_path)
            return True
        elif self.engine == 'elevenlabs':
            return _synthesize_elevenlabs(text, voice_cfg, out_path)
        elif self.engine == 'gtts':
            return _synthesize_gtts(text, voice_cfg, out_path)
        elif self.engine == 'piper':
            return _synthesize_piper(text, voice_cfg, out_path)
        elif self.engine == 'say':
            return _synthesize_say(text, voice_cfg, out_path)
        return False
