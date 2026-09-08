"""SETUP.sh, SETUP.ps1, and the launchers they write.

E10 is the parity chapter: before it, a Windows user got a scripted install
that ended in working audio and a file to double-click, and everyone else got
a uvicorn command to type. These tests hold the two scripts to the same shape.

Most of it is static — SETUP.ps1 cannot be executed here (no PowerShell on a
Mac) and running SETUP.sh for real means a venv, ~400 MB of Piper voices and
several minutes. What CAN be executed is executed: the shell is asked to parse
SETUP.sh, and `ask()` — the one function standing between this script and
someone's Desktop — is lifted out and driven through a real pty.
"""
import os
import pty
import re
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SETUP_SH = ROOT / "SETUP.sh"
SETUP_PS1 = ROOT / "SETUP.ps1"
GITIGNORE = ROOT / ".gitignore"


def sh() -> str:
    return SETUP_SH.read_text(encoding="utf-8")


def ps1() -> str:
    return SETUP_PS1.read_text(encoding="utf-8")


def heredoc(text: str, tag: str) -> str:
    """The body of a `cat > x <<TAG ... TAG` block, quoted tag or not."""
    opener = next((o for o in (f"<<{tag}\n", f"<<'{tag}'\n") if o in text), None)
    assert opener, f"no heredoc opens with {tag}"
    body = text.split(opener, 1)[1].split(f"\n{tag}", 1)[0]
    assert body.strip(), f"{tag} heredoc is empty"
    return body


# ── the shell parses ─────────────────────────────────────────────────────────

def test_setup_sh_is_valid_bash():
    r = subprocess.run(["bash", "-n", str(SETUP_SH)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_setup_sh_is_executable():
    assert os.access(SETUP_SH, os.X_OK), (
        "SETUP.sh lost its executable bit — `sed -i` on a mounted file does "
        "this; chmod 755 it back")


# ── ask(): nothing happens to your machine without you ───────────────────────
#
# Three things this script can do that a person has to agree to first: a
# ~400 MB download, a file on their Desktop, and starting a server. All three
# go through ask(), so ask() is the one piece of shell worth executing rather
# than reading.

def _ask_fn() -> str:
    lines = sh().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("ask() {"))
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


def _run_ask(default: str, typed: bytes | None) -> str:
    """Drive ask() through a pty. `typed` is None for 'no terminal at all'."""
    script = (_ask_fn() + "\n"
              + f'if ask "q?" {default}; then echo RESULT_YES; '
                'else echo RESULT_NO; fi\n')
    if typed is None:
        r = subprocess.run(["bash", "-c", script], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True)
        return "YES" if "RESULT_YES" in r.stdout else "NO"

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("bash", ["bash", "-c", script])
    out, deadline = "", time.time() + 10
    os.write(fd, typed)
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.5)
        if not r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk.decode("utf-8", "replace")
        if "RESULT_" in out:
            break
    os.close(fd)
    os.waitpid(pid, 0)
    return "YES" if "RESULT_YES" in out else "NO"


needs_pty = pytest.mark.skipif(sys.platform == "win32",
                               reason="pty is POSIX-only")


@needs_pty
def test_ask_says_no_when_there_is_no_terminal():
    """A pipe or a CI job is not a person. Even the [Y/n] prompt answers no,
    because 'yes' there means starting a server nobody asked to start."""
    assert _run_ask("y", None) == "NO"
    assert _run_ask("n", None) == "NO"


@needs_pty
def test_enter_takes_the_stated_default():
    assert _run_ask("y", b"\n") == "YES"
    assert _run_ask("n", b"\n") == "NO"


@needs_pty
def test_an_explicit_answer_beats_the_default():
    assert _run_ask("n", b"y\n") == "YES"
    assert _run_ask("y", b"n\n") == "NO"


@needs_pty
def test_anything_else_is_a_no():
    """Not a yes-unless-you-object prompt: only y or Y is consent."""
    for typed in (b"maybe\n", b"later\n", b"1\n"):
        assert _run_ask("n", typed) == "NO", typed


# ── the engine has to actually speak ─────────────────────────────────────────

def test_setup_sh_proves_piper_can_speak_before_it_downloads_the_voices():
    """A green Setup page in front of a mute engine is the worst thing an
    installer can produce, and piper-tts's macOS wheel produces exactly that:
    it installs, the voices download, the probe counts six files, and every
    render writes a zero-byte wav because the bundled espeak-ng looks for its
    data on the machine it was built on.

    Phonemizing needs no voice model, so the check costs a second and runs
    BEFORE the 400 MB.
    """
    text = sh()
    check = heredoc(text, "PIPER_CHECK_EOF")
    assert "EspeakPhonemizer" in check
    assert ".onnx" not in check, "must not need a voice model to answer"
    assert text.index("if ! piper_can_speak") < text.index("piper.download_voices"), \
        "check first, download second"


def test_a_mute_piper_is_fatal_on_linux_and_a_warning_on_macos():
    """On macOS Piper is an upgrade over `say`, so a broken wheel is a shrug.
    On Linux it is the only built-in engine, so it is a failed install."""
    text = sh()
    block = text.split("if ! piper_can_speak", 1)[1].split("ok \"Piper can", 1)[0]
    mac, rest = block.split("else", 1)
    assert "warn " in mac and "bad " not in mac
    assert "bad " in rest


# ── the launcher ─────────────────────────────────────────────────────────────

def test_setup_sh_writes_a_launcher_named_for_its_platform():
    """macOS hands .command files to Terminal on a double-click; Linux has no
    such convention, so there it is a plain .sh."""
    text = sh()
    assert "start-prosecast.command" in text
    assert "start-prosecast.sh" in text
    assert 'chmod 755 "$LAUNCHER"' in text


def test_the_launcher_names_the_venv_python_and_never_activates():
    """The rule the Windows launcher already follows, and the reason Piper is
    run as a module: no launcher activates a venv, so nothing may rely on the
    venv's bin/ being on PATH."""
    body = heredoc(sh(), "LAUNCHER_EOF")
    assert "./.venv/bin/python -m uvicorn server:app --port 8000" in body
    assert "PYTHONUTF8=1" in body
    code = [l for l in body.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in code if "activate" in l], code
    assert not [l for l in code if re.search(r"(^|/)uvicorn\s", l)], (
        "the venv's uvicorn script, not the module — that needs PATH", code)


def test_both_launchers_serve_the_same_url_on_the_same_port():
    body = heredoc(sh(), "LAUNCHER_EOF")
    assert "http://localhost:8000" in body
    assert "uvicorn server:app --port 8000" in ps1()
    assert "http://localhost:8000" in ps1()


def test_the_generated_launchers_are_gitignored():
    """Written for one machine, with that machine's paths in the shortcut it
    feeds. Committing one would hand the next person a broken file."""
    ignored = GITIGNORE.read_text(encoding="utf-8")
    for name in ("start-prosecast.ps1", "start-prosecast.command",
                 "start-prosecast.sh"):
        assert name in ignored, name


def test_setup_sh_prints_the_command_before_it_offers_to_run_it():
    """The prompt is a convenience; the printed command is the thing someone
    needs tomorrow. Print it first, or the offer replaces the knowledge —
    the same rule test_piper_voices.py holds SETUP.ps1 to."""
    text = sh()
    printed = text.index("Copy and run this:")
    asked = text.index("Start ProseCast now?")
    assert printed < asked
    assert 'ask "Start ProseCast now? [Y/n]" y' in text
