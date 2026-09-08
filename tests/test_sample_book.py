"""
Phase E6.1 — POST /books/sample: the built-in sample book as an ingest job.

The first-run wizard ends by reading the sample book aloud, and a fresh clone
has no books at all (`library/` and `books/` are gitignored). This endpoint is
the only way that book is created, so the things that matter are: it ingests on
the first call, does nothing at all on the second, and writes ir.json through
the atomic writer like every other IR write in the repo.

Offline and hermetic, like tests/test_ingest.py: tmp library, tmp books/.
"""
import builtins
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from prosecast import ingest  # noqa: E402
from prosecast import library as lib  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolate the library and books dirs; nothing touches Tyler's real ones."""
    monkeypatch.setattr(lib, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(ingest, "BOOKS_DIR", tmp_path / "books")
    monkeypatch.setattr(server, "BOOKS_DIR", tmp_path / "books")
    # The resolved engine is cached in a module global that PUT /config clears
    # in the app but nothing clears between tests — without this, whichever
    # engine an earlier test file left behind decides how this one casts.
    monkeypatch.setattr(server, "_active_engine", None)
    (tmp_path / "books").mkdir()
    yield tmp_path
    # An ingest job runs on its own daemon thread. If a test returns while one
    # is still going, monkeypatch puts LIBRARY_DIR back to the developer's real
    # library and the thread finishes writing into THAT. It happened: a run of
    # this file re-cast the real sample_book. Never leave one running.
    for t in threading.enumerate():
        if t.name.startswith("ingest-") and t.is_alive():
            t.join(timeout=120)


@pytest.fixture
def on_say(client):
    """Pin the engine, the way the wizard's step 1 does."""
    client.put("/config", json={"values": {"tts_engine": "say"}})
    return client


@pytest.fixture
def client(sandbox):
    return TestClient(server.app)


def _wait(client, job_id, timeout=90):
    t0 = time.time()
    job = None
    while time.time() - t0 < timeout:
        job = client.get(f"/render_status/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"sample ingest job {job_id} never finished: {job}")


# ── first call: it makes the book ────────────────────────────────────────────

def test_first_call_ingests_the_sample_as_a_job(client, sandbox):
    body = client.post("/books/sample").json()
    assert body["slug"] == "sample_book"
    assert body["exists"] is False
    assert body["job_id"]

    job = _wait(client, body["job_id"])
    assert job["status"] == "done", job
    assert job["kind"] == "ingest"           # polled like any upload
    assert job["book_slug"] == "sample_book"

    ir_path = lib.ir_path("sample_book")
    assert ir_path.exists()
    ir = json.loads(ir_path.read_text())
    assert len(ir["chapters"]) >= 2
    assert job["result"]["chapters"] == len(ir["chapters"])
    # rules-only: the wizard must work on rung 1 with nothing but `say`
    assert ir["ingest"]["mode"] == "novel"


def test_chapter_one_is_short_enough_to_wait_for(client, sandbox):
    """The wizard renders chapter 1 while a stranger watches a progress line,
    so its length is a product decision, not an accident of where a scene
    ended. Ten blocks; the rest of the sample is chapter 2."""
    _wait(client, client.post("/books/sample").json()["job_id"])
    chapters = json.loads(lib.ir_path("sample_book").read_text(encoding="utf-8"))["chapters"]
    assert len(chapters) == 2
    assert len(chapters[0]["blocks"]) <= 12, (
        f"chapter 1 has grown to {len(chapters[0]['blocks'])} blocks — that is the "
        "wait between '▶ Read me the sample' and the first sound anyone hears")
    assert len(chapters[1]["blocks"]) > len(chapters[0]["blocks"]), \
        "chapter 2 holds the rest of the book"


def test_the_split_did_not_cost_any_attribution(client, sandbox):
    """Moving a chapter break can strand the alternating heuristic, which seeds
    itself from the previous chapter's last speakers. It did not: the sample
    has the same 26 dialogue blocks and the same attribution as before."""
    _wait(client, client.post("/books/sample").json()["job_id"])
    chapters = json.loads(lib.ir_path("sample_book").read_text(encoding="utf-8"))["chapters"]
    blocks = [b for ch in chapters for b in ch["blocks"]]
    assert sum(1 for b in blocks if b["type"] == "dialogue") == 26


def test_the_text_file_is_written_where_books_live(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    assert (sandbox / "books" / "sample_book.txt").exists()


def test_the_book_shows_up_in_the_library_listing(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    slugs = [b["slug"] for b in client.get("/books").json()]
    assert "sample_book" in slugs


# ── second call: it does nothing ─────────────────────────────────────────────

def test_second_call_is_a_no_op(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    before = lib.ir_path("sample_book").read_bytes()

    body = client.post("/books/sample").json()
    assert body == {"slug": "sample_book", "exists": True, "recast": False,
                    "chapters": len(json.loads(before)["chapters"])}
    assert "job_id" not in body
    assert lib.ir_path("sample_book").read_bytes() == before


# ── ...unless the shipped text has moved on (E9.8) ───────────────────────────
#
# `git pull` does not touch library/, so an install that already had the sample
# book kept the sample book it had. The Windows laptop still held the 31-block
# chapter 1 that E9.7c replaced with a 10-block one, and only lost it because
# SETUP.ps1's smoke test happens to rewrite the book from scratch (2026-09-07).

def _stamp(value):
    """Forge the stored fingerprint, as an older ProseCast would have left it."""
    path = lib.ir_path("sample_book")
    ir = json.loads(path.read_text(encoding="utf-8"))
    if value is None:
        ir.get("ingest", {}).pop("sample_text_sha", None)
    else:
        ir.setdefault("ingest", {})["sample_text_sha"] = value
    path.write_text(json.dumps(ir), encoding="utf-8")


def test_the_ingest_records_which_shipped_text_it_read(client, sandbox):
    from prosecast.book_parser import sample_text_sha
    _wait(client, client.post("/books/sample").json()["job_id"])
    ir = json.loads(lib.ir_path("sample_book").read_text(encoding="utf-8"))
    assert ir["ingest"]["sample_text_sha"] == sample_text_sha()


def test_a_book_made_from_older_text_is_ingested_again(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    _stamp("0000deadbeef")                      # a sample from two versions ago

    body = client.post("/books/sample").json()
    assert body["reingested"] is True and "job_id" in body
    assert body["exists"] is True, "the book did exist — say so"
    _wait(client, body["job_id"])

    from prosecast.book_parser import sample_text_sha
    ir = json.loads(lib.ir_path("sample_book").read_text(encoding="utf-8"))
    assert ir["ingest"]["sample_text_sha"] == sample_text_sha()


def test_a_book_from_before_the_stamp_existed_is_ingested_again(client, sandbox):
    """Every install that predates E9.8 is in this state, once."""
    _wait(client, client.post("/books/sample").json()["job_id"])
    _stamp(None)
    body = client.post("/books/sample").json()
    assert body.get("reingested") is True
    _wait(client, body["job_id"])


def test_an_unreadable_ir_is_ingested_again(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    lib.ir_path("sample_book").write_text("{not json", encoding="utf-8")
    body = client.post("/books/sample").json()
    assert body.get("reingested") is True
    _wait(client, body["job_id"])
    assert json.loads(lib.ir_path("sample_book").read_text(encoding="utf-8"))["chapters"]


def test_audio_for_text_that_no_longer_exists_is_thrown_away(client, sandbox):
    """Block wavs are keyed by position, so a re-split leaves audio pointing at
    lines that have moved. Only renders/, and only this book."""
    _wait(client, client.post("/books/sample").json()["job_id"])
    blocks = lib.renders_dir("sample_book") / "ch0_blocks"
    blocks.mkdir(parents=True, exist_ok=True)
    stale = blocks / "block_0000.wav"
    stale.write_bytes(b"RIFFstale")
    keep = lib.book_dir("sample_book") / "corrections.jsonl"
    keep.write_text('{"kept": true}\n', encoding="utf-8")

    _stamp("0000deadbeef")
    body = client.post("/books/sample").json()
    _wait(client, body["job_id"])

    assert not stale.exists(), "audio from the old text survived the re-ingest"
    assert keep.read_text(encoding="utf-8") == '{"kept": true}\n', \
        "corrections are Tyler's labor and are append-only — never touched here"


def test_a_current_sample_is_never_re_ingested(client, sandbox):
    """The guard against a wizard that re-reads the book every time it opens."""
    _wait(client, client.post("/books/sample").json()["job_id"])
    before = lib.ir_path("sample_book").read_bytes()
    for _ in range(3):
        body = client.post("/books/sample").json()
        assert "job_id" not in body and "reingested" not in body
    assert lib.ir_path("sample_book").read_bytes() == before


def test_no_other_book_is_ever_re_ingested(client, sandbox):
    """`_discard_sample_audio` and the staleness check are scoped to one slug."""
    _wait(client, client.post("/books/sample").json()["job_id"])
    lib.ensure_book_dir("study")
    ir = lib.ir_path("study")
    ir.write_text(json.dumps({"book_title": "Study", "chapters": []}), encoding="utf-8")
    wav = lib.renders_dir("study") / "ch0.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    wav.write_bytes(b"RIFFkeep")

    _stamp("0000deadbeef")
    _wait(client, client.post("/books/sample").json()["job_id"])
    assert wav.read_bytes() == b"RIFFkeep"
    assert json.loads(ir.read_text(encoding="utf-8"))["book_title"] == "Study"


# ── the casting that makes it playable ───────────────────────────────────────
#
# The render preflight aborts on a book with no voice_map, and on one whose map
# was made for another engine. Both are right for a real book and both are dead
# ends for a wizard with no casting step — so the sample book, and only the
# sample book, is cast for you.

def test_the_voice_map_is_on_disk_before_the_job_says_done(on_say, sandbox):
    client = on_say
    """A poller that sees `done` fires POST /render next. If the casting is
    still running on the job's thread at that moment, preflight aborts with
    "No voice_map.json" — which is exactly what the first real run did, and how
    the escape into the developer's own library was found."""
    job = _wait(client, client.post("/books/sample").json()["job_id"])
    assert job["status"] == "done"
    assert lib.voice_map_path("sample_book").exists()
    assert job.get("recast") is True          # the job reports what it did


def test_the_sample_is_cast_for_the_active_engine(on_say, sandbox):
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    vm = json.loads(lib.voice_map_path("sample_book").read_text())
    assert vm["engine"] == "say"
    assert set(vm["map"]) >= {"NARRATOR", "Darcy", "Elizabeth"}
    pool = set(server._voice_pool("say"))
    assert all(v in pool for v in vm["map"].values()), vm["map"]


def test_a_cast_sample_passes_preflight(on_say, sandbox):
    client = on_say
    from prosecast import preflight
    _wait(client, client.post("/books/sample").json()["job_id"])
    rep = preflight.preflight("sample_book", server._get_active_engine())
    assert rep.ok, rep.summary()


def test_switching_engine_recasts_and_says_so(on_say, sandbox):
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    assert client.post("/books/sample").json()["recast"] is False

    client.put("/config", json={"values": {"tts_engine": "stub"}})
    body = client.post("/books/sample").json()
    assert body["recast"] is True, "a map from another engine must be replaced"
    vm = json.loads(lib.voice_map_path("sample_book").read_text())
    assert vm["engine"] == "stub"
    assert client.post("/books/sample").json()["recast"] is False   # now settled


def _write_map(engine, mapping):
    """A voice map put on disk by something other than the wizard."""
    lib.ensure_book_dir("sample_book")
    lib.voice_map_path("sample_book").write_text(
        json.dumps({"engine": engine, "map": mapping}), encoding="utf-8")


def test_a_book_made_from_the_terminal_gets_cast(on_say, sandbox):
    """The Windows case, 2026-09-06. `main.py --sample --tts stub` (which
    SETUP.sh runs as its smoke test) leaves ir.json and stub audio and NO voice
    map at all. E6.5 asked whether the wizard had made the book; the only
    question that matters is whether the map on disk fits."""
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    lib.voice_map_path("sample_book").unlink()          # as the CLI leaves it

    body = client.post("/books/sample").json()
    assert body["recast"] is True, "an uncast sample book must be cast"
    vm = json.loads(lib.voice_map_path("sample_book").read_text(encoding="utf-8"))
    assert vm["engine"] == "say"


def test_a_map_for_another_engine_is_replaced(on_say, sandbox):
    """Cast for stub, active engine is say → re-cast, and `recast: true` so the
    wizard renders past the wavs the other engine left behind."""
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    _write_map("stub", {"NARRATOR": "stub-voice", "Elizabeth": "stub-voice"})

    body = client.post("/books/sample").json()
    assert body["recast"] is True
    vm = json.loads(lib.voice_map_path("sample_book").read_text(encoding="utf-8"))
    assert vm["engine"] == "say"
    pool = set(server._voice_pool("say"))
    assert all(v in pool for v in vm["map"].values()), vm["map"]


def test_a_map_that_fits_is_left_alone(on_say, sandbox):
    """Cast for say, active engine is say → untouched. Never re-cast a real
    cast: this endpoint owns the sample book, not anyone's casting labor."""
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    before = lib.voice_map_path("sample_book").read_bytes()

    body = client.post("/books/sample").json()
    assert body["recast"] is False
    assert lib.voice_map_path("sample_book").read_bytes() == before


def test_a_map_naming_unknown_voices_is_replaced(on_say, sandbox):
    """Right engine name, voices this engine has never heard of — the same
    thing the render preflight aborts on ("voice_map entries not in the say
    pool"). The wizard has no casting step, so it must not be a dead end."""
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    _write_map("say", {"NARRATOR": "Rachel", "Elizabeth": "Bella"})

    assert client.post("/books/sample").json()["recast"] is True
    vm = json.loads(lib.voice_map_path("sample_book").read_text(encoding="utf-8"))
    assert set(vm["map"].values()) <= set(server._voice_pool("say"))


def test_a_map_of_engine_config_dicts_does_not_crash(on_say, sandbox):
    """voice_map entries may be engine-config dicts, not voice ids —
    VoiceAssigner.get_voice passes those straight through. `dict in set` is a
    TypeError, and this check runs inside the endpoint."""
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    _write_map("say", {"NARRATOR": {"voice": "Samantha"}})

    r = client.post("/books/sample")
    assert r.status_code == 200, r.text
    assert r.json()["recast"] is True


def test_an_unreadable_map_is_replaced(on_say, sandbox):
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    lib.voice_map_path("sample_book").write_text("{not json", encoding="utf-8")
    assert client.post("/books/sample").json()["recast"] is True


# ── the sample is cast by gender on rung 1, with nothing installed ───────────
#
# The fresh-clone Windows run still put Elizabeth and Jane on male voices. No
# titles in their IR names, no Ollama, so no gender hint reached the cast at
# all. Two fixes meet here: the sample ships its own cast profile, and the
# profiler's name table answers for common English given names without an LLM.

SAMPLE_CAST_GENDER = {"Elizabeth": "f", "Jane": "f", "Darcy": "m", "Bingley": "m"}


def test_every_one_of_the_samples_cast_is_gendered_without_ollama():
    """The claim, deterministically: on rung 1, with no AI pass and no spaCy,
    all four of the sample's characters reach the voice map with the right
    gender. Two come from the name table, two (surnames) from the shipped
    profile — see book_parser.SAMPLE_CHARACTER_PROFILES."""
    from prosecast.book_parser import SAMPLE_CHARACTER_PROFILES
    meta = server._voice_meta()
    labels = {v["id"]: v["name"] for v in server._raw_voices("piper")}
    vm = server._default_voice_map(
        ["NARRATOR", *SAMPLE_CAST_GENDER], "piper", SAMPLE_CHARACTER_PROFILES)
    for char, want in SAMPLE_CAST_GENDER.items():
        got = server._lookup_meta(meta, vm[char], labels.get(vm[char], ""))["gender"]
        assert got == want, f"{char} was cast {got!r}, wanted {want!r}: {vm}"
    assert vm["Elizabeth"] != vm["Jane"], "two women, two voices"
    assert vm["Darcy"] != vm["Bingley"], vm


@pytest.mark.parametrize("engine", ["piper", "say"])
def test_the_sample_casts_women_as_women_with_no_ollama(client, sandbox, engine):
    """The same thing through the endpoint, on the book it actually builds.

    Which characters exist here depends on spaCy: "Jane" is only ever found by
    the NER layer, so without `en_core_web_sm` the sample's cast is Elizabeth,
    Darcy and Bingley. Whoever IS in the cast must be cast correctly, so this
    checks the ones present rather than pretending to know.
    """
    client.put("/config", json={"values": {"tts_engine": engine}})
    _wait(client, client.post("/books/sample").json()["job_id"])

    ir = json.loads(lib.ir_path("sample_book").read_text(encoding="utf-8"))
    assert not ir.get("character_profiles"), \
        "this test is meaningless if something profiled the cast"

    vm = json.loads(lib.voice_map_path("sample_book").read_text(encoding="utf-8"))["map"]
    assert set(vm) >= {"NARRATOR", "Elizabeth", "Darcy", "Bingley"}, vm
    assert set(vm.values()) <= set(server._voice_pool(engine))

    if engine != "piper":
        return                # `say` ships no gender labels; nothing to assert
    meta = server._voice_meta()
    labels = {v["id"]: v["name"] for v in server._raw_voices(engine)}
    for char, want in SAMPLE_CAST_GENDER.items():
        if char not in vm:
            continue
        got = server._lookup_meta(meta, vm[char], labels.get(vm[char], ""))["gender"]
        assert got == want, f"{char} was cast {got!r}, wanted {want!r}: {vm}"
    assert vm["Darcy"] != vm["Bingley"], vm


def test_the_surnames_come_from_the_shipped_profile(client, sandbox):
    """Darcy and Bingley are surnames. No name table can resolve them, and no
    table should try — which is why the sample carries its own cast."""
    from prosecast.book_parser import SAMPLE_CHARACTER_PROFILES
    from prosecast.cast_profiler import guess_profile
    assert guess_profile("Darcy") is None
    assert guess_profile("Bingley") is None
    assert SAMPLE_CHARACTER_PROFILES["Darcy"]["gender"] == "masculine"
    assert SAMPLE_CHARACTER_PROFILES["Bingley"]["gender"] == "masculine"


def test_a_real_ai_pass_over_the_sample_still_wins(on_say, sandbox):
    """The shipped profile is a floor, not a ceiling."""
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    ir = _load = json.loads(lib.ir_path("sample_book").read_text(encoding="utf-8"))
    ir["character_profiles"] = {"Darcy": {"gender": "feminine", "confidence": 0.95,
                                          "age": "adult", "voice_hints": "",
                                          "evidence": "she said", "method": "llm"}}
    lib.write_json_atomic(lib.ir_path("sample_book"), ir)
    lib.voice_map_path("sample_book").unlink()

    client.put("/config", json={"values": {"tts_engine": "piper"}})
    client.post("/books/sample")
    vm = json.loads(lib.voice_map_path("sample_book").read_text(encoding="utf-8"))["map"]
    meta = server._voice_meta()
    labels = {v["id"]: v["name"] for v in server._raw_voices("piper")}
    assert server._lookup_meta(meta, vm["Darcy"], labels[vm["Darcy"]])["gender"] == "f"


def test_no_other_book_is_ever_cast(client, sandbox):
    lib.ensure_book_dir("someone_elses_book")
    lib.write_json_atomic(lib.ir_path("someone_elses_book"),
                          {"book_title": "Theirs", "chapters": [], "characters": []})
    _wait(client, client.post("/books/sample").json()["job_id"])
    assert not lib.voice_map_path("someone_elses_book").exists()


def test_a_second_call_never_makes_a_second_book(client, sandbox):
    _wait(client, client.post("/books/sample").json()["job_id"])
    client.post("/books/sample")
    assert lib.list_book_slugs() == ["sample_book"]


# ── the atomic-write rule ────────────────────────────────────────────────────

def test_ir_is_written_atomically(client, sandbox, monkeypatch):
    """Same guard as tests/test_pipeline.py: a plain `open(ir.json, 'w')` is how
    a crash mid-write destroys attribution labor, so no path may take it."""
    ir_path = str(lib.ir_path("sample_book"))
    real_open = builtins.open

    def guarded(file, mode="r", *a, **kw):
        if str(file) == ir_path and any(m in mode for m in "wxa"):
            raise AssertionError(f"plain write of ir.json: open({file!r}, {mode!r})")
        return real_open(file, mode, *a, **kw)

    calls = []
    real_atomic = lib.write_json_atomic
    monkeypatch.setattr(lib, "write_json_atomic",
                        lambda p, d: (calls.append(str(p)), real_atomic(p, d))[1])
    monkeypatch.setattr(builtins, "open", guarded)
    try:
        job = _wait(client, client.post("/books/sample").json()["job_id"])
    finally:
        monkeypatch.setattr(builtins, "open", real_open)
    assert job["status"] == "done", job
    assert ir_path in calls, "ir.json was never written through write_json_atomic"


# ── keeping the wizard's fixtures honest ─────────────────────────────────────
#
# tests/ui/check_first_run.py drives the overlay with these files. They are
# generated from the live endpoints by scripts/refresh_ui_fixtures.py, and the
# probe's machine-dependent inputs are pinned the same way on both sides (see
# tests/synthetic.py). Regenerate them when a response shape changes on
# purpose, rather than hand-editing, or the headless check goes back to testing
# a fiction.

FIXTURES = Path(__file__).parent / "fixtures"

from prosecast import config as _config      # noqa: E402
from prosecast import setup_probe as _sp     # noqa: E402
from synthetic import pin_config, pin_machine, pin_status  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch):
    """No env var from the developer's shell reaches the probes."""
    for env_var, _default, _secret in _config.SCHEMA.values():
        monkeypatch.delenv(env_var, raising=False)
    _config.invalidate()
    yield
    _config.invalidate()


@pytest.fixture
def pinned(clean_env):
    """Pin the machine the way the generator does, then put the module back."""
    real = (_sp._OS, _sp._which, _sp.probe_ollama, _sp.probe_whisper, _sp._tool_version)
    yield pin_machine
    (_sp._OS, _sp._which, _sp.probe_ollama, _sp.probe_whisper,
     _sp._tool_version) = real


def test_firstrun_fixtures_still_match_these_endpoints(client, sandbox, pinned):
    pinned(_sp, os_name="Darwin", ollama_ok=False, whisper_ok=False)
    live = pin_status(client.get("/setup/status").json())
    assert live == json.loads((FIXTURES / "setup_status_firstrun.json").read_text()), \
        "setup_status_firstrun.json has drifted from /setup/status — regenerate it"
    live_cfg = pin_config(client.get("/config").json())
    assert live_cfg == json.loads((FIXTURES / "config_firstrun.json").read_text()), \
        "config_firstrun.json has drifted from /config — regenerate it"


def test_ready_fixtures_still_match_these_endpoints(client, sandbox, pinned):
    client.put("/config", json={"values": {"tts_engine": "say"}})
    pinned(_sp, os_name="Darwin", ollama_ok=True, whisper_ok=True)
    live = pin_status(client.get("/setup/status").json())
    assert live == json.loads((FIXTURES / "setup_status_ready.json").read_text()), \
        "setup_status_ready.json has drifted from /setup/status — regenerate it"
    live_cfg = pin_config(client.get("/config").json())
    assert live_cfg == json.loads((FIXTURES / "config_ready.json").read_text()), \
        "config_ready.json has drifted from /config — regenerate it"


def test_setup_sh_fixture_still_matches_this_endpoint(client, sandbox, pinned):
    """The case that made E6.8 necessary: SETUP.sh copies config.example.json,
    so a config.json exists before anyone has chosen an engine. `config_exists`
    is true and `source` is "file" — only the value being "auto" says nobody
    has picked yet, which is what the wizard now fires on."""
    from prosecast import config as cfg_mod
    example = json.loads((Path(__file__).resolve().parent.parent / "config.example.json").read_text())
    assert example["tts_engine"] == "auto", "config.example.json must not pre-choose an engine"
    cfg_mod.config_path().write_text(json.dumps(example))
    cfg_mod.invalidate()

    pinned(_sp, os_name="Darwin", ollama_ok=False, whisper_ok=False)
    live = pin_status(client.get("/setup/status").json())
    assert live == json.loads((FIXTURES / "setup_status_setup_sh.json").read_text()), \
        "setup_status_setup_sh.json has drifted from /setup/status — regenerate it"
    assert live["config_exists"] is True
    engine_row = next(r for r in live["rows"] if r["key"] == "voice_engine")
    assert engine_row["engine"] == "auto" and engine_row["source"] == "file"


def test_chatterbox_fixture_still_matches_this_endpoint(client, sandbox, pinned):
    """An engine deliberately chosen and answering — the wizard must leave this
    person alone."""
    from synthetic import pin_chatterbox
    real_get = _sp._get_json
    try:
        client.put("/config", json={"values": {"tts_engine": "chatterbox"}})
        pinned(_sp, os_name="Darwin", ollama_ok=True, whisper_ok=True)
        pin_chatterbox(_sp)
        live = pin_status(client.get("/setup/status").json())
    finally:
        _sp._get_json = real_get
    assert live == json.loads((FIXTURES / "setup_status_chatterbox.json").read_text()), \
        "setup_status_chatterbox.json has drifted from /setup/status — regenerate it"
    engine_row = next(r for r in live["rows"] if r["key"] == "voice_engine")
    assert engine_row["engine"] == "chatterbox" and engine_row["source"] == "file"


def test_cast_candidates_fixtures_still_match_this_endpoint(on_say, sandbox):
    """tests/ui/check_first_run.py decides from these two whether the casting
    modal should have opened. `has_voice_map` false with more than one
    character IS the modal's trigger — if this endpoint ever stops saying that,
    the headless check would go on proving the modal stays shut for the wrong
    reason."""
    client = on_say
    _wait(client, client.post("/books/sample").json()["job_id"])
    vm = lib.voice_map_path("sample_book")
    cast_bytes = vm.read_bytes()

    vm.unlink()
    live = client.get("/ir/sample_book/cast_candidates").json()
    assert live == json.loads((FIXTURES / "cast_candidates_uncast.json").read_text()), \
        "cast_candidates_uncast.json has drifted — regenerate it"
    assert live["has_voice_map"] is False and len(live["characters"]) > 1

    vm.write_bytes(cast_bytes)
    live = client.get("/ir/sample_book/cast_candidates").json()
    assert live == json.loads((FIXTURES / "cast_candidates_cast.json").read_text()), \
        "cast_candidates_cast.json has drifted — regenerate it"
    assert live["has_voice_map"] is True


def test_sample_fixture_still_matches_this_endpoint(client, sandbox):
    live = client.post("/books/sample").json()
    live["job_id"] = "FIXTURE"
    assert live == json.loads((FIXTURES / "sample_book.json").read_text()), \
        "sample_book.json has drifted from /books/sample — regenerate it"


# ── the UI knows which book this is (E9.8) ───────────────────────────────────

def test_the_page_and_the_server_mean_the_same_book():
    """`loadBook` casts the sample book silently instead of showing the casting
    modal — the one book whose cast ProseCast owns. If the two slugs drift, that
    branch quietly stops firing and a stranger meets the casting modal again
    (Windows, 2026-09-07)."""
    html = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(encoding="utf-8")
    assert f"const SAMPLE_SLUG = '{server.SAMPLE_SLUG}';" in html, \
        f"static/index.html must declare SAMPLE_SLUG = '{server.SAMPLE_SLUG}'"

