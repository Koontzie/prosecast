"""
Book Parser — ProseCast Phase 1

Parses EPUB or plain-text files into a list of chapter dicts:
  [{"title": str, "text": str}, ...]
"""

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


CHAPTER_HEADING_RE = re.compile(
    r'^\s*(chapter\s+\w+|part\s+\w+)\s*[:\.\-]?\s*(.*)?$',
    re.IGNORECASE
)

EPUB_SKIP_FILES = {
    "cover.xhtml",
    "title-page.xhtml",
    "copyright.xhtml",
    "contents.xhtml",
    "toc.xhtml",
    "about-the-author.xhtml",
    "also-by-matt-dinniman.xhtml",
    "mailing-list-patreon-reddit-twitter-spotify.xhtml",
}

HEADING_TAGS = {"h1", "h2", "h3"}
TEXT_BLOCK_TAGS = HEADING_TAGS | {"p", "li", "blockquote", "pre"}


def _local_name(tag: str) -> str:
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _collapse_ws(text: str) -> str:
    text = text.replace('\xa0', ' ')
    lines = []
    for line in text.splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if line:
            line = re.sub(r'\s+([,.;:!?])', r'\1', line)
            lines.append(line)
    return '\n'.join(lines).strip()


def _element_text(elem) -> str:
    parts = []
    for text in elem.itertext():
        text = text.strip()
        if text:
            parts.append(text)
    return _collapse_ws(' '.join(parts))


def _iter_text_blocks(elem):
    tag = _local_name(elem.tag)
    if tag in TEXT_BLOCK_TAGS:
        text = _element_text(elem)
        if text:
            yield tag, text
        return

    for child in elem:
        yield from _iter_text_blocks(child)


def _chapter_title(title_parts: list, doc_title: str, fallback_title: str) -> str:
    if not title_parts:
        return doc_title or fallback_title

    base = title_parts[0]
    if re.fullmatch(r'[IVXLCM\d]+', base, re.IGNORECASE) and doc_title:
        base = doc_title

    extras = [part for part in title_parts[1:] if part.lower() != base.lower()]
    if extras:
        return f"{base}: {' - '.join(extras)}"
    return base


def _parse_xhtml_document(raw: bytes, fallback_title: str) -> list:
    root = ET.fromstring(raw)
    body = next((node for node in root.iter() if _local_name(node.tag) == "body"), None)
    if body is None:
        return []

    title_node = next((node for node in root.iter() if _local_name(node.tag) == "title"), None)
    doc_title = _collapse_ws(' '.join(title_node.itertext())) if title_node is not None else fallback_title

    chapters = []
    current_lines = []
    title_parts = []
    current_title = doc_title or fallback_title

    for tag, text in _iter_text_blocks(body):
        if tag in HEADING_TAGS:
            if current_lines:
                chapters.append({
                    "title": _chapter_title(title_parts, doc_title, current_title),
                    "text": '\n\n'.join(current_lines).strip(),
                })
                current_lines = []
                title_parts = [text]
            else:
                title_parts.append(text)
            continue

        if title_parts:
            current_title = _chapter_title(title_parts, doc_title, fallback_title)
            title_parts = []
        current_lines.append(text)

    if current_lines:
        chapters.append({
            "title": _chapter_title(title_parts, doc_title, current_title),
            "text": '\n\n'.join(current_lines).strip(),
        })

    if chapters:
        return chapters

    text = _element_text(body)
    if not text:
        return []
    return [{"title": doc_title or fallback_title, "text": text}]


def _opf_path(epub_zip: zipfile.ZipFile) -> str:
    container = ET.fromstring(epub_zip.read("META-INF/container.xml"))
    rootfile = next((node for node in container.iter() if _local_name(node.tag) == "rootfile"), None)
    if rootfile is None:
        raise ValueError("EPUB container.xml does not contain a rootfile entry")
    return rootfile.attrib["full-path"]


def _parse_txt(path: str) -> list:
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()
    chapters = []
    current_title = "Chapter 1"
    current_lines = []

    for line in lines:
        if CHAPTER_HEADING_RE.match(line) and len(line.strip()) < 80:
            if current_lines:
                body = '\n'.join(current_lines).strip()
                if body:
                    chapters.append({"title": current_title, "text": body})
            current_title = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        body = '\n'.join(current_lines).strip()
        if body:
            chapters.append({"title": current_title, "text": body})

    if not chapters:
        chapters = [{"title": "Chapter 1", "text": text.strip()}]

    return chapters


def _parse_epub(path: str) -> list:
    chapters = []
    with zipfile.ZipFile(path) as epub_zip:
        opf_path = _opf_path(epub_zip)
        opf_dir = posixpath.dirname(opf_path)
        opf_root = ET.fromstring(epub_zip.read(opf_path))

        manifest = {}
        spine = []
        for node in opf_root.iter():
            tag = _local_name(node.tag)
            if tag == "item":
                manifest[node.attrib["id"]] = node.attrib
            elif tag == "itemref":
                spine.append(node.attrib["idref"])

        for item_id in spine:
            item = manifest.get(item_id)
            if not item:
                continue

            href = item.get("href", "")
            media_type = item.get("media-type", "")
            properties = set(item.get("properties", "").split())
            basename = posixpath.basename(href).lower()

            if media_type not in {"application/xhtml+xml", "text/html"}:
                continue
            if "nav" in properties or basename in EPUB_SKIP_FILES:
                continue

            item_path = posixpath.normpath(posixpath.join(opf_dir, href))
            fallback_title = Path(basename).stem.replace('-', ' ').title()
            for chapter in _parse_xhtml_document(epub_zip.read(item_path), fallback_title):
                if chapter["text"]:
                    chapters.append(chapter)

    return chapters


def parse_book(path: str) -> list:
    """Parse an EPUB or TXT file into a list of chapter dicts."""
    ext = Path(path).suffix.lower()
    if ext == '.epub':
        return _parse_epub(path)
    return _parse_txt(path)


# ── Sample book ───────────────────────────────────────────────────────────────

SAMPLE_TEXT = '''\
Chapter 1: The Meeting

The morning light fell across the study as Elizabeth sat reading by the window.
She had not expected visitors so early, but a knock at the door interrupted her thoughts.

"Come in," she called, setting down her book.

Mr. Darcy entered, his expression unreadable as always.
He glanced around the room before settling his gaze on her.

"Miss Elizabeth," said Darcy, "I hope I am not disturbing you at this hour."

"Not at all," Elizabeth replied with a slight smile. "I was only reading.
Please sit down, Mr. Darcy."

Darcy took the chair by the fireplace. A silence stretched between them,
comfortable enough for Elizabeth, though she sensed something was troubling him.

"I wished to speak to you," said Darcy at last,
"about the matter we discussed at Netherfield."

Elizabeth set her book aside entirely now. "I remember it well," she said.
"You were rather direct on that occasion."

"Perhaps too direct," Darcy admitted.

Jane appeared at the doorway, her cheeks pink from the cold outside.

"Elizabeth, I did not know we had a visitor," Jane said, stepping inside.

"Mr. Darcy called just a few minutes ago," said Elizabeth.
She watched her sister's surprise give way to a polite smile.

"Mr. Darcy," said Jane warmly, "what a pleasant surprise."

Darcy rose and bowed. "Miss Bennet."

Elizabeth looked between the two of them, a quiet amusement rising in her chest.
"I shall ring for tea," she said.

Chapter 2: The Conversation

Later that afternoon, Bingley arrived at the house, his good cheer evident
the moment he stepped through the door.

"Darcy! I had no idea you were here," Bingley exclaimed.

"I came to return a book," Darcy said, though the book sat untouched
on the table beside him.

Bingley laughed. "Of course you did."

Jane smiled at Bingley. "Will you stay for dinner, Mr. Bingley?"

"Nothing would please me more," said Bingley at once.

Elizabeth poured the tea, watching Darcy watch Jane.
She had grown rather skilled at reading him over the past months.

"Tell me," said Darcy quietly, addressing only Elizabeth,
"do you still hold the same opinion of me as you did at Netherfield?"

Elizabeth handed him his cup. "My opinions on most things have changed
since Netherfield," she said.

"Most things," Darcy repeated.

"Most things," said Elizabeth.
'''


def write_sample_book(path: str):
    """Write the built-in sample book to the given path."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(SAMPLE_TEXT, encoding='utf-8')
    print(f"[Parser] Sample book written → {path}")
