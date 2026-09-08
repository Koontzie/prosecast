"""
Suite-wide fixtures.

Hermetic config: every test runs against an empty, throwaway config.json so
results never depend on the developer's real one (Tyler's points at Gideon,
which made test_default_is_localhost fail on his Mac while passing in CI-like
containers). Tests that want a file write to the same tmp path via
`prosecast.config.set_many()`.
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import config as _config  # noqa: E402


# Nothing listens here, on any platform: a connect to it is refused instantly.
# The point is to be *closed*, not to be a stub — a test that wants a Chatterbox
# or a whisper mocks the call itself.
NOWHERE = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROSECAST_CONFIG", str(tmp_path / "config.json"))
    _config.invalidate()

    # ...and the URLs that were already bound before this fixture could exist.
    # `tts_engine`, `word_aligner` and `tag_generator` each resolve their service
    # URL at IMPORT time, from whatever config.json was there then — Tyler's,
    # pointing at Gideon across Tailscale. Any test that let the engine
    # auto-detect therefore probed a real home server, and `_chatterbox_reachable`
    # is 8 s, a 1 s pause and 8 s again by design (a 2 s probe once demoted the
    # engine to `say` for a whole process). With that machine asleep on
    # 2026-09-07 it cost 17 s per call and turned a 20 s suite into a ten-minute
    # one that looked exactly like a hang. Tests must never reach for it.
    for module, attrs in (
            ("prosecast.tts_engine", ("CHATTERBOX_BASE_URL", "CHATTERBOX_TTS_URL",
                                      "CHATTERBOX_MODEL_INFO_URL",
                                      "CHATTERBOX_REFERENCE_FILES_URL",
                                      "CHATTERBOX_PREDEFINED_VOICES_URL")),
            ("prosecast.word_aligner", ("WHISPER_BASE", "TRANSCRIBE_URL")),
            ("prosecast.tag_generator", ("OLLAMA_BASE", "OLLAMA_TAGS_URL"))):
        try:
            mod = importlib.import_module(module)
        except Exception:                     # an optional dependency is missing
            continue
        for attr in attrs:
            if hasattr(mod, attr):
                suffix = str(getattr(mod, attr)).split("/", 3)[3:]
                monkeypatch.setattr(
                    mod, attr, NOWHERE + ("/" + suffix[0] if suffix else ""))

    yield
    _config.invalidate()
