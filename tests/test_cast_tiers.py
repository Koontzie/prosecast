"""
Character tiers: heuristic default, manual override endpoint, /cast exposure.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from prosecast import library as lib  # noqa: E402


def _ir(speakers):
    blocks = []
    i = 0
    for name, n in speakers.items():
        for _ in range(n):
            blocks.append({"segmentId": f"s{i}", "type": "dialogue",
                           "text": f'"line {i}"', "speaker": name,
                           "confidence": 0.9, "unresolved": False,
                           "attribution_method": "context_tag"})
            i += 1
    return {"title": "T", "characters": list(speakers), "user_characters": [],
            "chapters": [{"title": "Ch 1", "blocks": blocks}]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path)
    book = tmp_path / "tier_test"
    book.mkdir()
    (book / "ir.json").write_text(
        json.dumps(_ir({"Fern": 40, "Quillin": 7})), encoding="utf-8")
    return TestClient(server.app)


def _tiers(client):
    chars = client.get("/ir/tier_test/cast").json()["characters"]
    return {c["name"]: (c["tier"], c["tier_source"]) for c in chars}


def test_heuristic_tiers(client):
    t = _tiers(client)
    assert t["Fern"] == ("main", "auto")          # 40 >= 25
    assert t["Quillin"] == ("supporting", "auto")  # 7 < 25


def test_manual_override_persists_and_journals(client, tmp_path):
    r = client.post("/ir/tier_test/cast/tier",
                    json={"name": "Quillin", "tier": "main"})
    assert r.status_code == 200
    assert _tiers(client)["Quillin"] == ("main", "manual")

    events = [json.loads(l) for l in
              (tmp_path / "tier_test" / "corrections.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "tier_set"
    assert events[-1]["name"] == "Quillin" and events[-1]["tier"] == "main"


def test_auto_clears_override(client):
    client.post("/ir/tier_test/cast/tier", json={"name": "Fern", "tier": "supporting"})
    assert _tiers(client)["Fern"] == ("supporting", "manual")
    client.post("/ir/tier_test/cast/tier", json={"name": "Fern", "tier": "auto"})
    assert _tiers(client)["Fern"] == ("main", "auto")


def test_invalid_tier_rejected(client):
    r = client.post("/ir/tier_test/cast/tier",
                    json={"name": "Fern", "tier": "hero"})
    assert r.status_code == 400
