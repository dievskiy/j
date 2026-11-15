"""Rasterise the deck's own SVG charts with Pillow.

Only the small SVG subset that make_charts.py emits is supported (rect, line, circle,
polyline, text, and the rounded-bar path), which is enough to put the charts on the
slide images without a browser or an SVG library.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
REGULAR = FONT_DIR + "DejaVuSans.ttf"
BOLD = FONT_DIR + "DejaVuSans-Bold.ttf"
BAR_PATH = re.compile(r"M([\d.]+),([\d.]+) h([\d.]+) a4,4 0 0 1 4,4 v([\d.]+)")


def _colour(value: str | None, opacity: float = 1.0) -> tuple | None:
    if not value or value == "none":
        return None
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) + (round(255 * opacity),)


def _dashed_line(draw: ImageDraw.ImageDraw, start: tuple, end: tuple, colour: tuple, width: int,
                 dash: float, gap: float):
    length = math.dist(start, end)
    ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
    position = 0.0
    while position < length:
        stop = min(position + dash, length)
        draw.line([start[0] + ux * position, start[1] + uy * position,
                   start[0] + ux * stop, start[1] + uy * stop], fill=colour, width=width)
        position += dash + gap


def _arrow_head(draw: ImageDraw.ImageDraw, start: tuple, end: tuple, colour: tuple, size: float):
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    left = (end[0] - size * math.cos(angle - 0.45), end[1] - size * math.sin(angle - 0.45))
    right = (end[0] - size * math.cos(angle + 0.45), end[1] - size * math.sin(angle + 0.45))
    draw.polygon([end, left, right], fill=colour)


def rasterise(svg_path: str, scale: float) -> Image.Image:
    """The SVG drawn on a transparent image, `scale` pixels per SVG unit."""
    root = ET.parse(svg_path).getroot()
    width, height = float(root.get("width")), float(root.get("height"))
    image = Image.new("RGBA", (round(width * scale), round(height * scale)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def s(value) -> float:
        return float(value) * scale

    for element in root.iter():
        tag, get = element.tag.split("}")[1], element.get
        stroke_width = max(1, round(s(get("stroke-width") or 1)))
        if tag == "rect":
            x, y, w, h = s(get("x")), s(get("y")), s(get("width")), s(get("height"))
            fill = _colour(get("fill"), float(get("opacity") or 1))
            if get("stroke-dasharray"):
                corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
                for a, b in zip(corners, corners[1:]):
                    _dashed_line(draw, a, b, _colour(get("stroke")), stroke_width, s(7), s(6))
            else:
                draw.rounded_rectangle([x, y, x + w, y + h], radius=s(get("rx") or 0), fill=fill,
                                       outline=_colour(get("stroke")), width=stroke_width)
        elif tag == "line":
            start, end = (s(get("x1")), s(get("y1"))), (s(get("x2")), s(get("y2")))
            colour = _colour(get("stroke"))
            if get("stroke-dasharray"):
                _dashed_line(draw, start, end, colour, stroke_width, s(8), s(6))
            else:
                draw.line([start, end], fill=colour, width=stroke_width)
            if get("marker-end"):
                _arrow_head(draw, start, end, colour, s(16))
        elif tag == "circle":
            x, y, r = s(get("cx")), s(get("cy")), s(get("r"))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=_colour(get("fill")),
                         outline=_colour(get("stroke")), width=stroke_width)
        elif tag == "polyline":
            points = [tuple(s(v) for v in point.split(",")) for point in get("points").split()]
            draw.line(points, fill=_colour(get("stroke")), width=stroke_width, joint="curve")
        elif tag == "path":
            match = BAR_PATH.match(get("d"))
            if not match:                       # arrow-head marker definitions
                continue
            x, y, w, h = (s(v) for v in match.groups())
            draw.rounded_rectangle([x, y, x + w + s(4), y + h + s(8)], radius=s(4),
                                   fill=_colour(get("fill")), corners=(False, True, True, False))
        elif tag == "text":
            size = s(get("font-size"))
            font = ImageFont.truetype(BOLD if int(get("font-weight") or 400) >= 600 else REGULAR,
                                      round(size))
            anchor = {"middle": "ms", "end": "rs"}.get(get("text-anchor"), "ls")
            draw.text((s(get("x")), s(get("y"))), element.text, font=font, fill=_colour(get("fill")),
                      anchor=anchor)
    return image
