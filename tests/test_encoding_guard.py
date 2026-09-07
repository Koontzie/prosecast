"""Every text read and write names its encoding. (E9.1)

Windows found this the hard way on 2026-09-06: `GET /` was
`html_path.read_text()` with no encoding, cp1252 is the Windows default, and
`static/index.html` is UTF-8 — so the very first request to a fresh Windows
install 500'd with `UnicodeDecodeError: 'charmap' codec`. `PYTHONUTF8=1` made
it go away, which is exactly the problem: the bug was invisible on the Mac and
the workaround was a thing a stranger had to be told.

A book is text in someone else's language. Curly quotes, accents, em dashes and
names are the *content*, not an edge case, so guessing the encoding from the
machine's locale is never right. This walks the four places ProseCast reads and
writes text and fails on any call that does not say `encoding=`.

Scope, and why it is not an allowlist: the builtin `open`, `Path.read_text` and
`Path.write_text` are the three text doors in this codebase. `wave.open` and
`pymupdf.open` are different functions that open binary formats and have no
`encoding` parameter at all — they are not text reads, so they are not in
scope. Binary modes (`"rb"`, `"wb"`) are skipped for the same reason. A mode
this test cannot read as a literal is treated as text: unknown means it must
say what it is.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The four places the brief names. Everything ProseCast itself reads or writes
# lives here; tests are free to be sloppy, the product is not.
SEARCH = ("server.py", "main.py", "prosecast", "scripts")


def _py_files() -> list[Path]:
    out: list[Path] = []
    for name in SEARCH:
        target = ROOT / name
        if target.is_dir():
            out.extend(sorted(p for p in target.rglob("*.py")))
        elif target.exists():
            out.append(target)
    return out


def _mode_of(call: ast.Call) -> str | None:
    """The mode string an `open()` call asks for.

    None means "could not be read as a literal" — the caller treats that as
    text on purpose, so a computed mode has to name its encoding too.
    """
    if len(call.args) >= 2:
        arg = call.args[1]
        return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
    for kw in call.keywords:
        if kw.arg == "mode":
            return (kw.value.value if isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str) else None)
    return "r"                      # open(path) is text mode, always


def _has_encoding(call: ast.Call) -> bool:
    # `**kwargs` could carry it; nothing in this codebase does that, and
    # assuming it does would be the allowlist this test refuses to have.
    return any(kw.arg == "encoding" for kw in call.keywords)


def _offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(ROOT)
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            mode = _mode_of(node)
            if mode is not None and "b" in mode:
                continue            # binary: no encoding to name
            if not _has_encoding(node):
                shown = "?" if mode is None else mode
                bad.append(f"{rel}:{node.lineno}  open(..., mode={shown!r}) has no encoding=")
        elif isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text"):
            if not _has_encoding(node):
                bad.append(f"{rel}:{node.lineno}  .{func.attr}() has no encoding=")
    return bad


def test_there_are_files_to_check():
    """A typo in SEARCH would make every other test here pass on nothing."""
    files = _py_files()
    assert len(files) > 20, f"only found {len(files)} files — SEARCH is wrong"
    assert (ROOT / "server.py") in files


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_text_io_names_its_encoding(path):
    bad = _offenders(path)
    assert not bad, (
        f"{len(bad)} text read/write without encoding=\"utf-8\" "
        f"(Windows reads these as cp1252):\n  " + "\n  ".join(bad))
