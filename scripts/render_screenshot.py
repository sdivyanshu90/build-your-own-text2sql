#!/usr/bin/env python
"""Render captured terminal output to a PNG "screenshot" for the README.

This does NOT invent output — it takes a real captured run (stdin or a file) and
draws it verbatim into a terminal-styled image, colourising PASS/FAIL and headers
so the result is readable at a glance in the README.

Usage:
    python scripts/run_edge_cases.py > /tmp/out.txt
    python scripts/render_screenshot.py /tmp/out.txt docs/assets/edge-cases.png \
        --title "Text-to-SQL Engine — edge cases (live Gemini)"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# GitHub-dark-ish palette so the image reads well on both README themes.
BG = (13, 17, 23)
CHROME = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (201, 209, 217)
DIM = (110, 118, 129)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
CYAN = (57, 197, 207)
BLUE = (88, 166, 255)
PURPLE = (188, 140, 255)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
]
BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/UbuntuMono-B.ttf",
]


def _load(paths: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _segments(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    """Split a line into coloured segments (verbatim text, only colour added)."""
    stripped = line.strip()

    # Rule / separator lines.
    if stripped and set(stripped) <= set("=-"):
        return [(line, BORDER)]

    # Banner / title lines.
    if "Text-to-SQL Engine" in line or "PERFORMANCE BENCHMARK" in line.upper():
        return [(line, CYAN)]

    # Column header row.
    if re.match(r"\s*#\s+EDGE CASE", line) or line.lstrip().startswith("| Provider"):
        return [(line, DIM)]

    # Summary line.
    if "edge cases passed" in line or "cases passed" in line:
        segs: list[tuple[str, tuple[int, int, int]]] = []
        m = re.search(r"(\d+)/(\d+)", line)
        if m and m.group(1) == m.group(2):
            idx = line.index(m.group(0))
            segs.append((line[:idx], FG))
            segs.append((m.group(0), GREEN))
            segs.append((line[idx + len(m.group(0)) :], FG))
            return segs
        return [(line, YELLOW)]

    # Result rows: colour the PASS/FAIL token and the trailing note.
    if " PASS " in line or line.rstrip().endswith("PASS"):
        i = line.rindex("PASS")
        return [(line[:i], FG), ("PASS", GREEN), (line[i + 4 :], DIM)]
    if " FAIL " in line or line.rstrip().endswith("FAIL"):
        i = line.rindex("FAIL")
        return [(line[:i], FG), ("FAIL", RED), (line[i + 4 :], RED)]

    # Metric lines "  name: value"
    m = re.match(r"^(\s*[\w_ ]+:)(.*)$", line)
    if m and not line.startswith("|"):
        return [(m.group(1), DIM), (m.group(2), FG)]

    # Shell prompt line.
    if line.startswith("$"):
        return [("$", GREEN), (line[1:], PURPLE)]

    return [(line, FG)]


def render(text: str, out_path: Path, title: str, font_size: int = 15) -> None:
    lines = text.rstrip("\n").split("\n")
    font = _load(FONT_CANDIDATES, font_size)
    bold = _load(BOLD_CANDIDATES, font_size)
    title_font = _load(BOLD_CANDIDATES, font_size - 1)

    # Measure with a reference glyph (monospace ⇒ uniform advance).
    probe = Image.new("RGB", (10, 10))
    d0 = ImageDraw.Draw(probe)
    cw = d0.textlength("M", font=font)
    line_h = font_size + 7

    pad = 22
    chrome_h = 38
    max_cols = max((len(ln) for ln in lines), default = 80)
    width = int(cw * max_cols) + pad * 2
    width = max(width, 760)
    height = chrome_h + pad * 2 + line_h * len(lines)

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    # Window chrome with traffic lights + title.
    d.rectangle([0, 0, width, chrome_h], fill=CHROME)
    d.line([0, chrome_h, width, chrome_h], fill=BORDER)
    for i, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 18 + i * 18
        d.ellipse([cx - 6, chrome_h // 2 - 6, cx + 6, chrome_h // 2 + 6], fill=colour)
    tw = d.textlength(title, font=title_font)
    d.text(((width - tw) / 2, chrome_h / 2 - font_size / 2), title, font=title_font, fill=DIM)

    y = chrome_h + pad
    for line in lines:
        x = pad
        for seg_text, colour in _segments(line):
            if not seg_text:
                continue
            use = bold if colour in (GREEN, RED, CYAN) else font
            d.text((x, y), seg_text, font=use, fill=colour)
            x += d.textlength(seg_text, font=use)
        y += line_h

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    print(f"wrote {out_path} ({width}x{height})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="text file (default: stdin)")
    ap.add_argument("output")
    ap.add_argument("--title", default="terminal")
    ap.add_argument("--font-size", type=int, default=15)
    args = ap.parse_args()

    text = Path(args.input).read_text() if args.input else sys.stdin.read()
    render(text, Path(args.output), args.title, args.font_size)


if __name__ == "__main__":
    main()
