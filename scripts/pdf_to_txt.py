#!/usr/bin/env python3
"""PDF -> ProseCast-ingestible TXT (single-narrator listening copy).

Extracts text with pdftotext (poppler), strips per-page noise (watermark,
page numbers, running heads, TOC leader lines), reflows hard-wrapped lines
into paragraphs, drops table/stat-block paragraphs, and emits one TXT with
'Chapter N: Title' delimiter lines that prosecast/book_parser.py splits on.

Usage:
  python3 scripts/pdf_to_txt.py book.pdf toc.json out.txt [--keep-tables]

toc.json: {"chapters": [{"page": 8, "title": "Introduction", "end": null}, ...]}
  'page' = 1-based PDF page where the chapter starts. Last chapter's 'end'
  defaults to the last page. A chapter with "skip": true is omitted entirely.
"""
import json, re, subprocess, sys

WATERMARK_RE = re.compile(r'Copyright Renegade Game Studios|Unauthorized distribution prohibited', re.I)
PAGENUM_RE   = re.compile(r'^\s*\d{1,3}\s*$')
LEADER_RE    = re.compile(r'\.{4,}')
DICE_RE      = re.compile(r'\b\d*d\d+\b')
STAT_BULLET  = re.compile(r'^\s*[•▪◦]?\s*[+−–-]\d')
CAPS_LINE    = re.compile(r'^[^a-z]{4,60}$')

def caps_ratio(s):
    letters = [c for c in s if c.isalpha()]
    if not letters: return 0.0
    return sum(c.isupper() for c in letters) / len(letters)

def digit_sym_ratio(s):
    core = [c for c in s if not c.isspace()]
    if not core: return 0.0
    return sum(c.isdigit() or c in '+−–%/()x×' for c in core) / len(core)

def extract(pdf, first, last):
    out = subprocess.run(
        ['pdftotext', '-f', str(first), '-l', str(last), pdf, '-'],
        capture_output=True, text=True, check=True)
    return out.stdout.split('\f')

def clean_page(page_text, chapter_title):
    lines, out = page_text.split('\n'), []
    title_up = chapter_title.upper()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s: out.append(''); continue
        if WATERMARK_RE.search(s): continue
        if PAGENUM_RE.match(s): continue
        if LEADER_RE.search(s): continue                     # TOC leader rows
        toks = s.split()
        if len(toks) >= 3 and sum(len(t) <= 2 for t in toks) / len(toks) > 0.7:
            continue                                          # divider-art letter salad
        if len(s) <= 2 and s.isupper():
            continue                                          # single stacked divider letters
        if i < 4 and (title_up in s.upper() or re.match(r'^CHAPTER \d', s.upper())):
            continue                                          # running head
        out.append(s)
    return out

def reflow(lines):
    """Join hard-wrapped lines into paragraphs; merge consecutive caps headers."""
    paras, cur = [], []
    def flush():
        if cur:
            p = ' '.join(cur)
            p = re.sub(r'(\w)[­-]\s+(\w)', r'\1\2', p)   # de-hyphenate
            p = re.sub(r'\s+', ' ', p).strip()
            for item in re.split(r'\s+[•▪◦]\s+', p):
                item = item.lstrip('•▪◦ ').strip()
                if item: paras.append(item)
            cur.clear()
    prev_caps = False
    for ln in lines:
        if not ln: flush(); prev_caps = False; continue
        is_caps = bool(CAPS_LINE.match(ln)) and caps_ratio(ln) > 0.8 and not DICE_RE.search(ln)
        if is_caps:
            if prev_caps and cur: cur.append(ln)             # multi-line header
            else: flush(); cur.append(ln)
            prev_caps = True
        else:
            if prev_caps: flush()                            # header done
            prev_caps = False
            cur.append(ln)
    flush()
    # Titlecase pure-caps headers so TTS doesn't spell/shout them; end with period.
    out = []
    for p in paras:
        if caps_ratio(p) > 0.8 and len(p) < 70 and not p.endswith(('.', '!', '?', ':')):
            out.append(p.title().rstrip(':') + '.')
        else:
            out.append(p)
    return out

def is_tableish(p):
    if re.match(r'^Table \d+', p): return True
    if digit_sym_ratio(p) > 0.22: return True                 # numeric grids
    if STAT_BULLET.match(p): return True                      # "+3 Strength" bonus rows
    words = p.split()
    if len(words) <= 6 and DICE_RE.search(p): return True     # bare dice cells
    return False

def main():
    keep_tables = '--keep-tables' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    pdf, toc_path, out_path = args
    toc = json.load(open(toc_path))['chapters']
    # figure last page per chapter
    for i, ch in enumerate(toc):
        if not ch.get('end'):
            ch['end'] = (toc[i+1]['page'] - 1) if i + 1 < len(toc) else None
    book_out, dropped = [], 0
    num = 0
    for ch in toc:
        if ch.get('skip'): continue
        num += 1
        pages = extract(pdf, ch['page'], ch['end'] or 10**6)
        lines = []
        for pg in pages:
            lines.extend(clean_page(pg, ch['title']))
            lines.append('')
        paras = reflow(lines)
        kept = []
        for p in paras:
            if len(p) < 5: continue                            # divider-page fragments
            if re.search(r'chapt', p[:20], re.I) and len(p) < 80: continue  # garbled chapter art
            if re.match(r'(?i)^chapt\S*\s+\S+', p):           # scrambled divider text w/ blurb
                p = re.sub(r'(?i)^chapt\S*(\s+\S+){0,4}?\.\s*', '', p)
                if len(p) < 5: continue
            if not keep_tables and is_tableish(p): dropped += 1; continue
            if re.match(r'(?i)^\s*(chapter|part)\s+\w+', p) and kept:
                kept[-1] = kept[-1] + ' ' + p                  # don't let body lines look like delimiters
                continue
            kept.append(p)
        book_out.append(f"Chapter {num}: {ch['title']}\n\n" + '\n\n'.join(kept))
        print(f"  ch{num:02d} {ch['title'][:40]:<40} pages {ch['page']}-{ch['end']}"
              f"  kept {len(kept)} paras ({sum(len(p) for p in kept)} chars)", file=sys.stderr)
    open(out_path, 'w').write('\n\n\n'.join(book_out) + '\n')
    print(f"Wrote {out_path}; dropped {dropped} table-ish paragraphs", file=sys.stderr)

if __name__ == '__main__':
    main()
