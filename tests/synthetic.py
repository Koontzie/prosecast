"""Synthetic book material shared by the tests and by scripts/refresh_ui_fixtures.py.

One copy, because the fixtures the headless UI checks consume are generated from
the real endpoints fed with exactly this input. If a test and the generator each
kept their own near-copy, the fixture could match neither.

Nothing here is copyrighted: the prose is invented and the PDFs are built at
call time with PyMuPDF.
"""

LONG_LINE = ("It was a truth universally acknowledged that a single man in "
             "possession of a good fortune must be in want of a wife, and the "
             "neighbourhood took the matter as settled long before he had any "
             "say in it at all, which is how these things usually go. ") * 2

# (type, speaker, text, unresolved) — one small chapter with all four shapes.
BLOCKS = [
    ("narration", "NARRATOR", "The morning light fell across the study.", False),
    ("dialogue", "Darcy", "You have been avoiding me.", False),
    ("dialogue", "Elizabeth", LONG_LINE, False),
    ("dialogue", "UNKNOWN", "Then I shall wait.", True),
]

NOVEL = """Chapter 1: The Study

The morning light fell across the study as Elizabeth sat reading.

"You have been avoiding me," said Darcy.

"I have been reading," Elizabeth replied. "There is a difference."

"Then I shall wait," he said.
"""

PLAY = """SCENE ONE

(A basement. AGNES enters, holding a red box.)

AGNES. This is where it started.

TILLY. You never listened to me.

AGNES. I was fifteen. Nobody listens at fifteen.

TILLY. That is not an excuse.

AGNES. No. It is not.

(TILLY exits. AGNES sits alone.)

AGNES. Roll for initiative.

TILLY. Too late for that.

AGNES. It is never too late.

TILLY. Says the girl with the box.
"""

RULEBOOK = """Chapter 1: Running the Game

The Game Master describes the room. Players say what they do.

A check is rolled when the outcome is uncertain and failure is interesting.

Chapter 2: Combat

Initiative is rolled once per encounter. Ties go to the player.
"""

PDF_BODY = ("The rain had not stopped for three days and the town smelled of wet stone. "
            "Nobody went out unless they had to. ") * 6


def study_ir() -> dict:
    """The little one-chapter book behind the `study` fixtures.

    Shared so the drift tests and scripts/refresh_ui_fixtures.py feed the
    endpoints byte-identical input — a near-copy in each would match neither.
    """
    blocks = []
    for i, (kind, speaker, text, unresolved) in enumerate(BLOCKS):
        blocks.append({
            "segmentId": f"ch0_seg_{i:04d}", "type": kind, "text": text,
            "speaker": speaker, "confidence": 0.0 if unresolved else 0.9,
            "unresolved": unresolved, "attribution_method": "postfix",
            "cacheKey": None,
            "audioVariants": {"standard": {"url": None, "cached": False},
                              "premium": {"url": None, "cached": False}},
            "selectedVariant": "standard",
        })
    return {"book_title": "The Study", "unresolved_count": 1,
            "characters": ["Darcy", "Elizabeth", "O'Brien"],
            "chapters": [{"index": 0, "title": "One", "blocks": blocks}]}


def build_pdf(path, *, n_chapters: int = 3, pages_per: int = 2, scan: bool = False):
    """A small PDF with real bookmarks — or, with scan=True, image-only pages."""
    import pymupdf

    doc = pymupdf.open()
    toc = []
    for c in range(n_chapters):
        for k in range(pages_per):
            page = doc.new_page()
            if scan:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
                pix.clear_with(200)
                page.insert_image(pymupdf.Rect(72, 72, 400, 400), pixmap=pix)
                continue
            if k == 0:
                page.insert_text((72, 72), f"Chapter {c + 1}: Story {c + 1}", fontsize=11)
                toc.append([1, f"Chapter {c + 1}: Story {c + 1}", doc.page_count])
            page.insert_textbox(pymupdf.Rect(72, 110, 540, 700), PDF_BODY, fontsize=11)
    if toc:
        doc.set_toc(toc)
    doc.save(path)
    doc.close()
    return path


SCAN_PAGES = [
    ("Chapter 1: The Locked Room",
     "The rain had not stopped for three days and the town smelled of wet stone. "
     "Nobody went out unless they had to, and those who did came back quiet."),
    (None,
     "The second page carries on in much the same weather, with rather fewer "
     "people in it than the first one had."),
]


def build_scanned_pdf(path, *, pages=SCAN_PAGES, blank: bool = False, dpi: int = 200):
    """A PDF that is only pictures — a real scan, not a stand-in.

    Text is laid out, rendered to a bitmap, and that bitmap becomes the page, so
    there is no text layer for pdf_ingest to find and tesseract has something it
    can genuinely read. ``blank=True`` produces pages with nothing on them, for
    the "OCR came back empty" path.
    """
    import pymupdf

    src = pymupdf.open()
    for heading, body in pages:
        page = src.new_page()
        if blank:
            continue
        y = 100
        if heading:
            page.insert_text((72, y), heading, fontsize=20)
            y += 40
        page.insert_textbox(pymupdf.Rect(72, y, 520, y + 300), body, fontsize=14)

    scan = pymupdf.open()
    for i in range(src.page_count):
        pix = src[i].get_pixmap(dpi=dpi)
        page = scan.new_page(width=pix.width * 72 / dpi, height=pix.height * 72 / dpi)
        page.insert_image(page.rect, pixmap=pix)
    scan.save(path)
    src.close()
    scan.close()
    return path


# ── pinned Setup probes (E3 pipeline fixtures, E6 first-run fixtures) ────────
#
# /setup/status and /pipeline/{slug} ask the network and the PATH whether
# things are there, so their answers differ between Tyler's Mac, the device VM
# and a CI container. The fixtures still have to come from the live endpoint
# (that is the rule this repo learned the hard way), so what gets pinned is the
# probe's *inputs* — OS, `which`, and the two network probes — and the row text
# is whatever the real probe code makes of them. `scripts/refresh_ui_fixtures.py`
# and the drift tests call this identically, so the two always agree.

OLLAMA_FIX = ("Install Ollama from ollama.com and start it, or point the URL at a machine "
              "that runs it.")
WHISPER_FIX = ("Optional. Without it the read-along highlights by sentence (estimated) "
               "instead of by word.")


def probe_row(key: str, label: str, ok: bool, fix: str = "") -> dict:
    return {"key": key, "label": label, "ok": ok, "state": "ok" if ok else "missing",
            "detail": f"{label} · http://localhost · " + ("ready" if ok else "not responding"),
            "fix": fix, "optional": True}


def pin_probes(sp, ollama_ok: bool, whisper_ok: bool) -> None:
    """Pin the two optional service probes to a fixed verdict."""
    sp.probe_ollama = lambda: probe_row(
        "ollama", "Who's speaking (local AI)", ollama_ok, "" if ollama_ok else OLLAMA_FIX)
    sp.probe_whisper = lambda: probe_row(
        "whisper", "Read-along timing (whisper)", whisper_ok,
        "" if whisper_ok else WHISPER_FIX)


PINNED_TOOLS = ("say", "ffmpeg", "tesseract")


def pin_machine(sp, *, os_name: str = "Darwin", have=PINNED_TOOLS,
                ollama_ok: bool = False, whisper_ok: bool = False) -> None:
    """Pin everything about the machine that /setup/status can see."""
    sp._OS = os_name
    sp._which = lambda binary: (f"/usr/local/bin/{binary}" if binary in have else None)
    pin_probes(sp, ollama_ok=ollama_ok, whisper_ok=whisper_ok)


def pin_status(payload: dict) -> dict:
    """The one field left that no pinning can fix: where config.json happens to
    live is a tmp path that differs every run."""
    out = dict(payload)
    out["config_path"] = "MACHINE"
    return out


def pin_config(payload: dict) -> dict:
    out = dict(payload)
    out["path"] = "MACHINE"
    return out


# Chatterbox is the one engine whose probe talks to a server. `_get_json` is
# the documented mock point, so pinning it gives a real probe row for "an
# engine is chosen and answering" without a Chatterbox anywhere.
def pin_chatterbox(sp, *, device: str = "cuda", voices: int = 40) -> None:
    def fake(url, timeout=4.0, headers=None):
        if url.endswith("/api/model-info"):
            return {"class_name": "ChatterboxTTS", "type": "original", "device": device}
        if url.endswith("/get_predefined_voices"):
            return [{"name": f"voice-{i}.wav"} for i in range(voices)]
        return None
    sp._get_json = fake
