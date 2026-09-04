#!/usr/bin/env python3
"""PDF -> ProseCast-ingestible TXT, for any PDF (thin CLI over prosecast.pdf_ingest).

    python3 scripts/pdf_to_txt.py book.pdf --list                # show detected chapters, write nothing
    python3 scripts/pdf_to_txt.py book.pdf out.txt               # detect chapters + extract
    python3 scripts/pdf_to_txt.py book.pdf out.txt --toc toc.json  # use a hand-written chapter list
    python3 scripts/pdf_to_txt.py book.pdf out.txt --keep-tables

Chapters come from the PDF's bookmarks, else a printed contents page, else
large headings, else a fixed page split — printed with the source so you know
how much to trust it. Lines that repeat on most pages (copyright watermark,
running heads, page numbers) are dropped generically; nothing here is written
for one particular book.

toc.json (optional override, same shape as before):
    {"chapters": [{"page": 8, "title": "Introduction", "skip": false}, ...]}
    'page' = 1-based PDF page where the chapter starts.

Scanned PDFs (no text layer) are detected and refused with a pointer to OCR.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prosecast import pdf_ingest as pi  # noqa: E402


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); sys.exit(0)
    keep_tables = "--keep-tables" in argv
    list_only = "--list" in argv
    toc_path = None
    if "--toc" in argv:
        toc_path = argv[argv.index("--toc") + 1]
    args = [a for i, a in enumerate(argv)
            if not a.startswith("--") and (i == 0 or argv[i - 1] != "--toc")]
    pdf = args[0]
    out_path = args[1] if len(args) > 1 else None
    if not list_only and not out_path:
        print("need an output path (or --list)", file=sys.stderr); sys.exit(2)

    if not Path(pdf).is_file():
        print(f"No such file: {pdf}\n(tip: mdfind -name \"part of the name\" | grep -i '\\.pdf$' finds it)",
              file=sys.stderr)
        sys.exit(2)
    doc = pi.open_pdf(pdf)
    scan = pi.scan_report(doc)
    if scan["is_scan"]:
        print(f"'{pdf}' looks like a SCAN: {scan['avg_chars_per_page']} extractable chars/page "
              f"over {scan['pages']} pages. Run OCR first (tesseract / ocrmypdf) — the ingest "
              "wizard will do this for you in a later step.", file=sys.stderr)
        sys.exit(3)

    if toc_path:
        chapters = json.load(open(toc_path))["chapters"]
        det = None
        source, note = "toc.json", f"{len(chapters)} chapters from {toc_path}"
    else:
        det = pi.detect_chapters(doc)
        chapters, source, note = det.chapters, det.source, det.note

    print(f"{pdf}: {scan['pages']} pages, ~{scan['avg_chars_per_page']:.0f} chars/page", file=sys.stderr)
    print(f"chapters via {source}: {note}", file=sys.stderr)
    if det and det.repeated_lines:
        print(f"dropping {len(det.repeated_lines)} repeated line(s) (watermark / running heads):",
              file=sys.stderr)
        for l in det.repeated_lines[:8]:
            print(f"    · {l[:90]}", file=sys.stderr)
    for i, ch in enumerate(chapters, 1):
        d = ch.to_dict() if hasattr(ch, "to_dict") else ch
        flag = "  (skip)" if d.get("skip") else ""
        print(f"  {i:3d}. p{d['page']:<5} {str(d['title'])[:60]}{flag}", file=sys.stderr)
    if list_only:
        sys.exit(0)

    def progress(done, total, title):
        print(f"  [{done}/{total}] {title[:50]}", file=sys.stderr)

    result = pi.extract(doc, chapters, keep_tables=keep_tables,
                        repeated=det.repeated_lines if det else None, progress=progress)
    Path(out_path).write_text(result["text"], encoding="utf-8")
    for r in result["chapters"]:
        print(f"    {r['title'][:40]:<40} pages {r['pages'][0]}-{r['pages'][1]}  "
              f"{r['paragraphs']} paras ({r['chars']} chars)", file=sys.stderr)
    print(f"Wrote {out_path}; dropped {result['dropped_tables']} table-ish paragraphs", file=sys.stderr)


if __name__ == "__main__":
    main()
