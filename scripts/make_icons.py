#!/usr/bin/env python3
"""Render docs/assets/prosecast-icon.svg into the three shortcut icon formats.

    .venv/bin/python scripts/make_icons.py

Writes, into the repo root:

    icon.png    512, for the Linux .desktop file and anything else
    icon.ico    16/32/48/64/128/256, for the Windows .lnk
    icon.icns   16..1024 with @2x, for the macOS .app bundle

The SVG is the source of truth; these three are generated. Edit the SVG and
re-run this, never hand-edit a raster.

Rasterizing is done with Playwright's chromium, which is already a dependency
of the tests/ui/ checks — the alternative was adding rsvg/cairo/Pillow to
requirements.txt for a file that changes about once a year. If chromium is not
installed the script says so and stops; the generated icons are committed, so
nobody needs this unless they are changing the mark.

The .ico is written by hand rather than by Pillow. An ICO directory may point
at PNG data directly (Vista and newer read it), so the whole format here is a
6-byte header, a 16-byte entry per size, and the PNGs end to end.
"""
from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "docs" / "assets" / "prosecast-icon.svg"

ICO_SIZES = [16, 32, 48, 64, 128, 256]
# iconutil wants these exact names, and every one of them present.
ICNS_SET = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def render(sizes: list[int]) -> dict[int, bytes]:
    """Rasterize the SVG once per size. Returns {size: png bytes}."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright is not installed: pip install playwright "
                 "&& playwright install chromium")

    svg = SVG.read_text(encoding="utf-8")
    out: dict[int, bytes] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for size in sorted(set(sizes)):
            page = browser.new_page(viewport={"width": size, "height": size},
                                    device_scale_factor=1)
            # The size comes from the viewport and CSS, never from rewriting
            # the SVG's width/height attributes: the background rect carries
            # the same `width="512" height="512"` pair, and a str.replace hits
            # that too, shrinking the ground to a blob in the corner.
            page.set_content(
                "<style>html,body{margin:0;padding:0}"
                "svg{display:block;width:100%;height:100%}</style>"
                "<body>" + svg + "</body>")
            # omit_background keeps the corners the rounded rect leaves out
            # transparent, which is what both .ico and .icns want.
            out[size] = page.screenshot(omit_background=True)
            page.close()
        browser.close()
    return out


def write_ico(path: Path, pngs: dict[int, bytes], sizes: list[int]) -> None:
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(header) + 16 * len(sizes)
    entries, blobs = b"", b""
    for size in sizes:
        data = pngs[size]
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # 0 means 256 in this field
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    path.write_bytes(header + entries + blobs)


def write_icns(path: Path, pngs: dict[int, bytes]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "prosecast.iconset"
        iconset.mkdir()
        for name, size in ICNS_SET:
            (iconset / name).write_bytes(pngs[size])
        r = subprocess.run(["iconutil", "-c", "icns", str(iconset),
                            "-o", str(path)], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"iconutil failed: {r.stderr.strip()}")


def main() -> None:
    if not SVG.exists():
        sys.exit(f"missing {SVG}")
    wanted = sorted({512} | set(ICO_SIZES) | {s for _n, s in ICNS_SET})
    pngs = render(wanted)

    (ROOT / "icon.png").write_bytes(pngs[512])
    print("  wrote icon.png (512)")

    write_ico(ROOT / "icon.ico", pngs, ICO_SIZES)
    print(f"  wrote icon.ico ({', '.join(str(s) for s in ICO_SIZES)})")

    if sys.platform == "darwin":
        write_icns(ROOT / "icon.icns", pngs)
        print("  wrote icon.icns (16-1024, with @2x)")
    else:
        print("  skipped icon.icns - iconutil is macOS-only "
              "(the committed one is still good)")


if __name__ == "__main__":
    main()
