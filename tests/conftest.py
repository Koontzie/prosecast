"""
Suite-wide fixtures.

Hermetic config: every test runs against an empty, throwaway config.json so
results never depend on the developer's real one (Tyler's points at Gideon,
which made test_default_is_localhost fail on his Mac while passing in CI-like
containers). Tests that want a file write to the same tmp path via
`prosecast.config.set_many()`.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import config as _config  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROSECAST_CONFIG", str(tmp_path / "config.json"))
    _config.invalidate()
    yield
    _config.invalidate()
