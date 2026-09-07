"""
TTS Engine — ProseCast

Supports: elevenlabs (premium, API), chatterbox (local, devnen server, voice cloning),
piper (local), say (macOS), gtts (Google TTS), stub (silent WAV)
"""

import hashlib
import json
import os
import wave
from pathlib import Path

from prosecast.tag_mapper import map_tags

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

    # Piper resolves `<name>.onnx` from the CURRENT WORKING DIRECTORY (see
    # _synthesize_piper), so these files live in the ProseCast folder itself.
    # Download them with `python -m piper.download_voices <name>`; the Setup
    # page prints the exact lines for whichever are missing.
    #
    # Index 0 is the narrator. Three female, three male, so a cast of five has
    # something to match on — with four voices and no gender, the first Windows
    # run put Elizabeth on `ryan` and Jane on `kusal` (both men) and gave
    # Bingley Elizabeth's voice.
    PIPER_VOICES = [
        'en_US-lessac-medium',
        'en_US-ryan-medium',
        'en_GB-alan-medium',
        'en_US-kusal-medium',
        'en_US-hfc_female-medium',
        'en_GB-jenny_dioco-medium',
    ]

    # Shipped defaults for the overlay in voice_meta.json — that file stays the
    # place a person's own labels live, and anything it says wins (server.py's
    # `_lookup_meta` layers them). Piper's own catalogue carries no gender
    # field, so each of these was read off the dataset the voice was trained
    # on, named in its MODEL_CARD on huggingface.co/rhasspy/piper-voices:
    #
    #   lessac      Blizzard 2013 Lessac corpus — Catherine Byers, female
    #   ryan        RyanSpeech (Kaggle, roholazandie) — male
    #   alan        Mimic3 en_UK apope — Alan Pope, male
    #   kusal       Mimic2 kusal — male
    #   hfc_female  NICT Hi-Fi-Captain, the en-US *female* speaker
    #   jenny_dioco Jenny TTS dataset (dioco-group) — Jenny, female
    #
    # Licence is deliberately absent: these are per-dataset (CC BY-NC-SA for
    # ryan and hfc_female, "see URL" for the rest) and ProseCast does not
    # redistribute the models. The Voices tab says "see the Piper voices page"
    # rather than asserting one.
    PIPER_VOICE_META = {
        'en_US-lessac-medium':      {'gender': 'f', 'notes': 'US · the default narrator'},
        'en_US-ryan-medium':        {'gender': 'm', 'notes': 'US'},
        'en_GB-alan-medium':        {'gender': 'm', 'notes': 'British'},
        'en_US-kusal-medium':       {'gender': 'm', 'notes': 'US'},
        'en_US-hfc_female-medium':  {'gender': 'f', 'notes': 'US'},
        'en_GB-jenny_dioco-medium': {'gender': 'f', 'notes': 'British'},
    }

    SAY_VOICES = [
        'Samantha',
        'Daniel',
        'Karen',
        'Moira',
        'Tessa',
    ]

    # Chatterbox clone-mode reference filenames (uploaded to the devnen server).
    # Index 0 is reserved for NARRATOR; the rest round-robin for characters.
    # This is a static fallback — when the server is reachable the pool is
    # repopulated from GET /get_reference_files at construction time.
    CHATTERBOX_VOICES = [
        'Gianna.wav',
        'Robert.wav',
    ]

    def __init__(self, engine: str = 'stub'):
        self.engine = engine
        self._map = {}        # speaker → voice config
        self._pool_idx = 0    # next index for character voices (skip index 0 = narrator)
        self._voice_map = {}  # explicit speaker → voice_id overrides from voice_map.json
        # Per-instance chatterbox pool (starts from the static fallback; refreshed
        # from the live server below). Instance-scoped so it never mutates the class.
        self._chatterbox_pool = list(self.CHATTERBOX_VOICES)
        if engine == 'chatterbox':
            live = fetch_chatterbox_references()
            if live:
                self._chatterbox_pool = live

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
        elif self.engine == 'chatterbox':
            # "predefined:<file>" → built-in server voice; bare filename → clone
            # mode with a reference clip (the original behavior).
            if voice_id.startswith('predefined:'):
                return {'voice_mode': 'predefined',
                        'predefined_voice_id': voice_id.split(':', 1)[1]}
            return {'voice_mode': 'clone', 'reference_audio_filename': voice_id}
        return {}

    def get_voice(self, speaker: str) -> dict:
        if speaker in self._map:
            return self._map[speaker]

        # Explicit override from voice_map.json takes priority over auto-assign.
        # Dict entries are engine-specific configs and pass through untouched;
        # string entries go through the per-engine voice_id translation.
        if speaker in self._voice_map:
            entry = self._voice_map[speaker]
            cfg = dict(entry) if isinstance(entry, dict) else self._voice_id_to_cfg(entry)
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
        elif self.engine == 'chatterbox':
            pool = self._chatterbox_pool
            if speaker == 'NARRATOR' or len(pool) < 2:
                ref = pool[0]
            else:
                idx = (self._pool_idx % (len(pool) - 1)) + 1
                ref = pool[idx]
                self._pool_idx += 1
            cfg = {'voice_mode': 'clone', 'reference_audio_filename': ref}
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
            elif self.engine == 'chatterbox':
                parts.append(f"{speaker}→{cfg.get('reference_audio_filename') or cfg.get('predefined_voice_id', '?')}")
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
    from prosecast import config as _cfg
    return _cfg.get("elevenlabs_api_key")


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


# ── Chatterbox backend ───────────────────────────────────────────────────────
#
# Local devnen Chatterbox-TTS-Server (voice cloning + exaggeration/speed).
# Contract captured in docs/chatterbox-contract.md. Field names come straight
# from the server's /openapi.json — do NOT trust the tag_mapper's older keys:
# the mapper emits {"exaggeration", "cfg_weight", "speed"}; the server's speed
# field is named "speed_factor". We translate at the payload boundary below.

from prosecast import config as _config

CHATTERBOX_BASE_URL = _config.get("chatterbox_url")   # config.json / CHATTERBOX_URL env
CHATTERBOX_TTS_URL = CHATTERBOX_BASE_URL + "/tts"
CHATTERBOX_MODEL_INFO_URL = CHATTERBOX_BASE_URL + "/api/model-info"
CHATTERBOX_REFERENCE_FILES_URL = CHATTERBOX_BASE_URL + "/get_reference_files"
CHATTERBOX_PREDEFINED_VOICES_URL = CHATTERBOX_BASE_URL + "/get_predefined_voices"


def _chatterbox_reachable(timeout: int = 8) -> bool:
    """Quiet reachability probe used by engine auto-detect (no printing).

    Retries once: the shared server answers one request at a time, so a probe
    landing mid-synthesis can time out on a perfectly healthy box. A 2s
    one-shot probe silently demoted the engine to macOS `say` for the whole
    process lifetime — the engine choice is cached at startup.
    """
    import time as _time
    import urllib.request
    for attempt in range(2):
        try:
            with urllib.request.urlopen(CHATTERBOX_MODEL_INFO_URL, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        if attempt == 0:
            _time.sleep(1)
    return False


def fetch_chatterbox_references(timeout: int = 5):
    """GET the server's clone-mode reference filenames.

    Returns a list of filename strings, or None if the server is unreachable /
    returns nothing usable (caller keeps the static fallback pool).
    """
    import urllib.request
    try:
        with urllib.request.urlopen(CHATTERBOX_REFERENCE_FILES_URL, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode())
        # Server returns a bare JSON array of filenames.
        files = [f for f in data if isinstance(f, str)] if isinstance(data, list) else None
        return files or None
    except Exception:
        return None


def fetch_chatterbox_predefined(timeout: int = 5):
    """GET the server's built-in (predefined) voices.

    Returns a list of {display_name, filename} dicts, or None on failure.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(CHATTERBOX_PREDEFINED_VOICES_URL, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode())
        return data if isinstance(data, list) and data else None
    except Exception:
        return None


def test_chatterbox_connection() -> bool:
    """Connectivity + model check for the Chatterbox server.

    Mirrors test_elevenlabs_connection(): GETs a cheap route (/api/model-info)
    and prints a clear OK/failure line. Also fires the Turbo guard — on a turbo
    model the exaggeration/cfg controls are ignored, which is a silent-failure
    trap, so we warn LOUDLY.
    """
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(CHATTERBOX_MODEL_INFO_URL, timeout=8) as resp:
            if resp.status != 200:
                print(f"[Chatterbox] Connection check returned HTTP {resp.status}")
                return False
            info = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[Chatterbox] Connection failed: HTTP {e.code} — {CHATTERBOX_BASE_URL}")
        return False
    except Exception as e:
        print(f"[Chatterbox] Connection failed: {e} — is {CHATTERBOX_BASE_URL} reachable (Tailscale)?")
        return False

    print("[Chatterbox] Connection OK ✓")
    model_type = str(info.get("type", "")).lower()
    class_name = str(info.get("class_name", ""))
    if "turbo" in model_type or "turbo" in class_name.lower():
        print("[Chatterbox] WARNING: turbo model loaded — exaggeration/cfg are IGNORED; "
              "emotion tags will not affect delivery. Switch the server to base "
              "ResembleAI/chatterbox.")
    return True


def _synthesize_chatterbox(text: str, voice_cfg: dict, out_path: str) -> bool:
    """Render one block via the devnen Chatterbox server (POST /tts).

    voice_cfg carries the voice identity (clone reference filename or predefined
    voice id) plus, optionally, a '_tag_params' dict of mapped emotion params
    ({exaggeration, cfg_weight, speed}) produced by map_tags(tags, "chatterbox").
    The server returns WAV bytes directly (output_format=wav), which we write
    straight to out_path — no MP3 decode needed.
    """
    import urllib.request
    import urllib.error

    voice_mode = voice_cfg.get("voice_mode", "clone")
    payload = {
        "text": text,
        "voice_mode": voice_mode,
        "output_format": "wav",
        "stream": False,
    }
    if voice_mode == "clone":
        ref = voice_cfg.get("reference_audio_filename")
        if not ref:
            print("    [Chatterbox] No reference_audio_filename in config for clone mode")
            return False
        payload["reference_audio_filename"] = ref
    else:  # predefined
        pv = voice_cfg.get("predefined_voice_id")
        if not pv:
            print("    [Chatterbox] No predefined_voice_id in config for predefined mode")
            return False
        payload["predefined_voice_id"] = pv

    # Emotion params from the tag mapper. Note the speed → speed_factor rename.
    tag_params = voice_cfg.get("_tag_params") or {}
    if "exaggeration" in tag_params:
        payload["exaggeration"] = tag_params["exaggeration"]
    if "cfg_weight" in tag_params:
        payload["cfg_weight"] = tag_params["cfg_weight"]
    if "speed" in tag_params:
        payload["speed_factor"] = tag_params["speed"]

    req = urllib.request.Request(
        CHATTERBOX_TTS_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )
    # Timeout scales with text length: the server chunk-renders long text and a
    # ~15k-char block legitimately takes several minutes on the 3090 Ti. A flat
    # 120s made every block over ~4k chars fail deterministically, every run.
    # Observed throughput is roughly 25-40 synthesized chars/sec end-to-end.
    timeout_s = max(120, min(1800, len(text) // 10))
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            audio_bytes = resp.read()
    except urllib.error.HTTPError as e:
        # Never swallow the error — surface the server body so failures are debuggable.
        try:
            body = e.read().decode(errors="replace")
        except Exception:
            body = "(no body)"
        print(f"    [Chatterbox] HTTP {e.code}: {e.reason}\n    body: {body[:500]}")
        return False
    except Exception as e:
        print(f"    [Chatterbox error] {e}")
        return False

    if not audio_bytes:
        print("    [Chatterbox] Empty response body")
        return False
    try:
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        return True
    except Exception as e:
        print(f"    [Chatterbox write error] {e}")
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
        elif self.engine == 'chatterbox':
            test_chatterbox_connection()

    def load_voice_map(self, voice_map: dict):
        """Pass a saved {speaker: voice_id} map to the assigner before rendering."""
        self.assigner.load_voice_map(voice_map)

    def _detect(self) -> str:
        # ElevenLabs is highest priority — if API key is present, use it
        if _elevenlabs_api_key().strip():
            return 'elevenlabs'
        # Chatterbox is the preferred local default when the server answers.
        if _chatterbox_reachable():
            return 'chatterbox'
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

        ok = self.synthesize(text, speaker, out_path, tags=segment.get("tags"))
        if ok:
            segment.setdefault("audioVariants", {
                "standard": {"url": None, "cached": False},
                "premium":  {"url": None, "cached": False},
            })
            segment["audioVariants"]["standard"]["url"] = out_path
            segment["audioVariants"]["standard"]["cached"] = True
            segment["cacheKey"] = cache_key
        return ok

    def synthesize(self, text: str, speaker: str, out_path: str, tags: dict = None) -> bool:
        voice_cfg = self.assigner.get_voice(speaker)
        if self.engine == 'stub':
            _write_stub_wav(out_path)
            return True
        elif self.engine == 'elevenlabs':
            return _synthesize_elevenlabs(text, voice_cfg, out_path)
        elif self.engine == 'chatterbox':
            # Fold the mapped emotion params into a per-call copy of voice_cfg so
            # the 3-arg backend signature (text, voice_cfg, out_path) stays intact.
            cfg = dict(voice_cfg)
            cfg["_tag_params"] = map_tags(tags, "chatterbox")
            return _synthesize_chatterbox(text, cfg, out_path)
        elif self.engine == 'gtts':
            return _synthesize_gtts(text, voice_cfg, out_path)
        elif self.engine == 'piper':
            return _synthesize_piper(text, voice_cfg, out_path)
        elif self.engine == 'say':
            return _synthesize_say(text, voice_cfg, out_path)
        return False
