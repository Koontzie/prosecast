from prosecast.book_parser import _parse_xhtml_document


def test_epub_keeps_chapter_headings_instead_of_document_title():
    chapters = _parse_xhtml_document(b'''<html><head><title>The whole book</title></head><body>
        <h1>Chapter 1</h1><h2>The Stopped Clock</h2><p>Nia brought a clock.</p>
        <h1>Chapter 2</h1><h2>The First Tick</h2><p>Oren opened the clock.</p>
        </body></html>''', 'chapter-file')
    assert [ch['title'] for ch in chapters] == ['Chapter 1: The Stopped Clock', 'Chapter 2: The First Tick']
    assert [ch['text'] for ch in chapters] == ['Nia brought a clock.', 'Oren opened the clock.']


def test_headingless_epub_still_uses_document_title():
    chapters = _parse_xhtml_document(b'<html><head><title>The Clock</title></head><body><p>One quiet tick.</p></body></html>', 'chapter-file')
    assert chapters == [{'title':'The Clock', 'text':'One quiet tick.'}]
