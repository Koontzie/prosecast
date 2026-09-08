"""The streams, not the files: a redirected stdout must survive a book.

Windows, 2026-09-07 — the bug that made `SETUP.ps1`'s step 7 fail on a fresh
clone while the identical command typed into the console passed. The script runs

    & $venvPy main.py --sample --tts stub *> $null

and that redirect makes stdout a **pipe**. Python on Windows encodes a pipe with
the ANSI code page (cp1252), not the console's, so `print("═" * 60)` in main.py's
IR report raised UnicodeEncodeError and the process exited 1. E9.1's sweep had
fixed every *file* read and write and could not have caught this.

The Mac gives a pipe UTF-8 either way, so the failure mode is forced here with
`PYTHONIOENCODING=cp1252` in the child's environment — and `PYTHONUTF8` is
removed from it, because an environment variable someone has to remember is not
the property under test. Without `prosecast/console.py` these tests fail; that
is the whole point of them.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ═ and → are the two characters that actually did it: the IR report's rule and
# every "[IR] wrote → path" line. Neither exists in cp1252.
REPORT_CHARS = "═ → ✓"


def cp1252_env(**extra) -> dict:
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)             # the fix must not need it
    env["PYTHONIOENCODING"] = "cp1252"      # what Windows hands a pipe
    env.update(extra)
    return env


def run(code: str, *args, env=None) -> subprocess.CompletedProcess:
    """Always with stdout/stderr captured — a pipe, never a tty. That is the
    condition under test, so it is not optional here."""
    return subprocess.run([sys.executable, "-c", code, *args],
                          cwd=ROOT, env=env or cp1252_env(),
                          capture_output=True, text=True, timeout=180)


# ── the streams themselves ───────────────────────────────────────────────────

def test_a_cp1252_pipe_really_does_break_an_unfixed_python():
    """The premise. If this ever stops failing, the tests below prove nothing."""
    p = run(f"print({REPORT_CHARS!r})")
    assert p.returncode != 0, "cp1252 accepted ═ → ✓ — the failure mode is gone"
    assert "UnicodeEncodeError" in p.stderr


def test_importing_main_makes_stdout_carry_the_report():
    p = run(f"import main; print({REPORT_CHARS!r})")
    assert p.returncode == 0, p.stderr[-2000:]
    assert REPORT_CHARS in p.stdout


def test_importing_the_server_makes_the_log_carry_the_report():
    p = run(f"import server; print({REPORT_CHARS!r})")
    assert p.returncode == 0, p.stderr[-2000:]
    assert REPORT_CHARS in p.stdout


def test_stderr_too():
    p = run(f"import sys, main; print({REPORT_CHARS!r}, file=sys.stderr)")
    assert p.returncode == 0, p.stderr[-2000:]
    assert REPORT_CHARS in p.stderr


def test_a_character_that_cannot_be_encoded_never_kills_the_process():
    """`errors="replace"`: diagnostic output is not worth an exit code. Encode
    the stream back down to cp1252 first, then print something it cannot hold."""
    p = run("import main, sys; sys.stdout.reconfigure(encoding='cp1252', errors='replace');"
            f"print({REPORT_CHARS!r}); print('still here')")
    assert p.returncode == 0, p.stderr[-2000:]
    assert "still here" in p.stdout


def test_use_utf8_streams_survives_streams_that_cannot_reconfigure():
    """pytest's own captured streams are such objects, and so is a StringIO."""
    p = run("import io, sys;"
            "sys.stdout = io.StringIO(); sys.stderr = io.StringIO();"
            "from prosecast.console import use_utf8_streams; use_utf8_streams();"
            "sys.stdout = sys.__stdout__; print('survived')")
    assert p.returncode == 0, p.stderr[-2000:]
    assert "survived" in p.stdout


# ── the command that actually failed ─────────────────────────────────────────

# Runs the real CLI end to end (~1 s on stub), with the library and books dirs
# pointed at tmp_path in the child — `main.py --sample` writes both, and a test
# that wrote into the real library would rewrite Tyler's sample book.
BOOTSTRAP = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from prosecast import library as lib
lib.LIBRARY_DIR = Path(sys.argv[2]) / "library"
import main
main.BOOKS_DIR = Path(sys.argv[2]) / "books"
sys.argv = ["main.py", "--sample", "--tts", "stub"]
main.main()
"""


def test_the_smoke_test_survives_a_redirect(tmp_path):
    """`main.py --sample --tts stub` through a pipe under cp1252 — SETUP.ps1's
    step 7, and SETUP.sh's, exactly as they run it."""
    p = run(BOOTSTRAP, str(ROOT), str(tmp_path))
    assert p.returncode == 0, (p.stdout[-1500:], p.stderr[-2000:])
    assert "UnicodeEncodeError" not in p.stderr
    assert (tmp_path / "library" / "sample_book" / "ir.json").exists()
    assert "→" in p.stdout, "the report's arrows never reached the pipe"


def test_it_prints_the_ir_report_and_finishes(tmp_path):
    p = run(BOOTSTRAP, str(ROOT), str(tmp_path))
    assert "═" in p.stdout, "the IR report's rule is the line that used to kill it"
    assert p.returncode == 0


# ── SETUP.ps1's half (finding 1) ─────────────────────────────────────────────
#
# The script cannot be run on this machine, but the one line that has to be
# there is checkable. It covers every python the script starts that is not
# main.py or server.py — pip, spaCy, piper.download_voices.

def test_setup_ps1_puts_python_in_utf8_mode_before_it_runs_any_python():
    ps1 = (ROOT / "SETUP.ps1").read_text(encoding="utf-8")
    assert '$env:PYTHONUTF8 = "1"' in ps1, \
        "SETUP.ps1 must set PYTHONUTF8 — its step 7 redirects stdout to $null"
    at = ps1.index('$env:PYTHONUTF8 = "1"')
    starts_a_python = [ps1.index(m) for m in ("-m venv", "$venvPy") if m in ps1]
    assert starts_a_python, "SETUP.ps1 no longer starts a python — check this test"
    assert at < min(starts_a_python), \
        "PYTHONUTF8 is set after the first python this script starts"


def test_the_launcher_keeps_it_too():
    """`start-prosecast.ps1` is generated by SETUP.ps1 and gitignored, so the
    only place to check it is the here-string that writes it."""
    ps1 = (ROOT / "SETUP.ps1").read_text(encoding="utf-8")
    launcher = ps1[ps1.index("$launcher = @'"):]
    assert '$env:PYTHONUTF8 = "1"' in launcher
