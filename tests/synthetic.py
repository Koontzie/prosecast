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
