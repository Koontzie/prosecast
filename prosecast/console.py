"""stdout and stderr that can carry the text of a book.

Windows, 2026-09-07. `SETUP.ps1`'s step 7 ran the smoke test as

    & $venvPy main.py --sample --tts stub *> $null

The redirect makes stdout a **pipe**, and Python on Windows encodes a pipe with
the ANSI code page (cp1252) no matter what the console itself is set to — so
`print("═" * 60)` in main.py's IR report raised `UnicodeEncodeError` and the
process exited 1. The identical command typed into the console passed, which is
exactly why the manual install worked and the script's own step did not.

E9.1 gave every *file* read and write in this repo an explicit encoding. This is
the other half: the streams. It is deliberately independent of `PYTHONUTF8` —
an environment variable a person has to remember is not a fix.
"""
import sys


def use_utf8_streams() -> None:
    """Make stdout and stderr carry UTF-8, whatever the platform picked.

    `errors="replace"` because this is diagnostic output: a character that
    cannot be encoded must never be the reason an install, a render or a CLI run
    fails. Guarded on `reconfigure` — pytest, some CI runners and anything that
    swaps in a `StringIO` replace these streams with objects that lack it.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass                    # a stream that refuses is not worth dying for
