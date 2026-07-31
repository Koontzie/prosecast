"""
PROSECAST_OLLAMA_URL must steer BOTH LLM passes (attribution + tags).

Regression guard for the 2026-07-31 change: llm_attributor was hardcoded to
localhost (failed unless Ollama ran on the same machine) while tag_generator
was hardcoded to Tyler's home server IP (failed for everyone else). Both now
read one env var and default to localhost — the average-user setup.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import llm_attributor, tag_generator  # noqa: E402


def _reload_both():
    importlib.reload(llm_attributor)
    importlib.reload(tag_generator)


def test_env_var_overrides_both_passes(monkeypatch):
    monkeypatch.setenv("PROSECAST_OLLAMA_URL", "http://GIDEON_HOST:11434/")
    _reload_both()
    try:
        # trailing slash stripped, same base everywhere
        assert llm_attributor.OLLAMA_API == "http://GIDEON_HOST:11434/api/generate"
        assert llm_attributor.OLLAMA_TAGS == "http://GIDEON_HOST:11434/api/tags"
        assert tag_generator.OLLAMA_API == "http://GIDEON_HOST:11434/api/generate"
        assert tag_generator.OLLAMA_TAGS_URL == "http://GIDEON_HOST:11434/api/tags"
    finally:
        monkeypatch.delenv("PROSECAST_OLLAMA_URL")
        _reload_both()   # restore default state for other tests


def test_default_is_localhost(monkeypatch):
    monkeypatch.delenv("PROSECAST_OLLAMA_URL", raising=False)
    _reload_both()
    assert llm_attributor.OLLAMA_API == "http://localhost:11434/api/generate"
    assert tag_generator.OLLAMA_API == "http://localhost:11434/api/generate"
