"""A small drawing surface for 1920x1080 slides, rendered with Pillow.

Coordinates are in slide pixels. Everything is drawn at twice the size and scaled down
when saved, which gives smooth edges without an external renderer.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from svg_raster import rasterise

WIDTH, HEIGHT = 1920, 1080
SUPERSAMPLE = 2
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT_FILES = {("sans", False): "DejaVuSans.ttf", ("sans", True): "DejaVuSans-Bold.ttf",
              ("mono", False): "DejaVuSansMono.ttf", ("mono", True): "DejaVuSansMono-Bold.ttf"}


@lru_cache(maxsize=None)
def font(size: float, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    name = FONT_FILES[("mono" if mono else "sans", bold)]
    return ImageFont.truetype(str(FONT_DIR / name), round(size * SUPERSAMPLE))


def rgba(colour: str, alpha: float = 1.0) -> tuple:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4)) + (round(255 * alpha),)


def text_width(content: str, size: float, bold: bool = False, mono: bool = False) -> float:
    return font(size, bold, mono).getlength(content) / SUPERSAMPLE


def wrap(content: str, size: float, max_width: float, bold: bool = False, mono: bool = False) -> list[str]:
    """Greedy word wrap to a pixel width."""
    lines, current = [], ""
    for word in content.split():
        candidate = f"{current} {word}".strip()
        if current and text_width(candidate, size, bold, mono) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + [current] if current else lines


class Canvas:
    def __init__(self, background: str):
        self.image = Image.new("RGBA", (WIDTH * SUPERSAMPLE, HEIGHT * SUPERSAMPLE), rgba(background))
        self.draw = ImageDraw.Draw(self.image)

    @staticmethod
    def _px(*values: float) -> list[float]:
        return [v * SUPERSAMPLE for v in values]

    def rect(self, x: float, y: float, w: float, h: float, fill: str | None = None,
             outline: str | None = None, radius: float = 0, line_width: float = 2, alpha: float = 1.0):
        self.draw.rounded_rectangle(self._px(x, y, x + w, y + h), radius=radius * SUPERSAMPLE,
                                    fill=rgba(fill, alpha) if fill else None,
                                    outline=rgba(outline) if outline else None,
                                    width=round(line_width * SUPERSAMPLE))

    def line(self, x1: float, y1: float, x2: float, y2: float, colour: str, line_width: float = 2):
        self.draw.line(self._px(x1, y1, x2, y2), fill=rgba(colour), width=round(line_width * SUPERSAMPLE))

    def text(self, x: float, y: float, content: str, size: float, colour: str, bold: bool = False,
             mono: bool = False, anchor: str = "la"):
        """`anchor` is a Pillow text anchor: 'la' left/top, 'ma' centred, 'ra' right."""
        self.draw.text(self._px(x, y), content, font=font(size, bold, mono), fill=rgba(colour), anchor=anchor)

    def paragraph(self, x: float, y: float, content: str, size: float, colour: str, max_width: float,
                  bold: bool = False, mono: bool = False, line_height: float = 1.4) -> float:
        """Wrapped text; returns the y just below the last line."""
        for line in wrap(content, size, max_width, bold, mono):
            self.text(x, y, line, size, colour, bold, mono)
            y += size * line_height
        return y

    def fitted_text(self, x: float, y: float, content: str, size: float, colour: str, max_width: float,
                    bold: bool = True):
        """One line, shrunk until it fits the width."""
        while text_width(content, size, bold) > max_width:
            size -= 1
        self.text(x, y, content, size, colour, bold)

    def picture(self, path: Path, x: float, y: float, w: float, h: float, radius: float = 10):
        """An image cropped to fill the box, with rounded corners."""
        source = Image.open(path).convert("RGB")
        box_ratio, source_ratio = w / h, source.width / source.height
        if source_ratio > box_ratio:
            crop_width = round(source.height * box_ratio)
            left = (source.width - crop_width) // 2
            source = source.crop((left, 0, left + crop_width, source.height))
        else:
            crop_height = round(source.width / box_ratio)
            top = (source.height - crop_height) // 2
            source = source.crop((0, top, source.width, top + crop_height))
        size = (round(w * SUPERSAMPLE), round(h * SUPERSAMPLE))
        source = source.resize(size, Image.LANCZOS).convert("RGBA")
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1],
                                               radius=radius * SUPERSAMPLE, fill=255)
        self.image.paste(source, (round(x * SUPERSAMPLE), round(y * SUPERSAMPLE)), mask)

    def chart(self, svg_path: Path, x: float, y: float, w: float) -> float:
        """An SVG chart scaled to width w; returns its drawn height."""
        probe = rasterise(str(svg_path), 1)
        scale = w / probe.width
        chart = rasterise(str(svg_path), scale * SUPERSAMPLE)
        self.image.alpha_composite(chart, (round(x * SUPERSAMPLE), round(y * SUPERSAMPLE)))
        return probe.height * scale

    def shade(self, x: float, y: float, w: float, h: float, colour: str, alpha_left: float, alpha_right: float):
        """A horizontal gradient overlay, for text over a photo."""
        width, height = round(w * SUPERSAMPLE), round(h * SUPERSAMPLE)
        gradient = Image.linear_gradient("L").rotate(90, expand=True).resize((width, height))
        low, high = round(255 * alpha_left), round(255 * alpha_right)
        alpha = gradient.point(lambda value: round(low + (high - low) * value / 255))
        overlay = Image.new("RGBA", (width, height), rgba(colour))
        overlay.putalpha(alpha)
        self.image.alpha_composite(overlay, (round(x * SUPERSAMPLE), round(y * SUPERSAMPLE)))

    def finished(self) -> Image.Image:
        return self.image.resize((WIDTH, HEIGHT), Image.LANCZOS).convert("RGB")
