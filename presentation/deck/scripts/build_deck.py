"""Build the deck: slide images, deck.pdf, index.html and script.md.

    python3 presentation/deck/scripts/make_charts.py
    .venv/bin/python presentation/deck/scripts/build_deck.py

Slides are drawn with Pillow from the frames and charts in assets/, so the HTML deck and
the PDF show exactly the same pictures. Narration and sources live in deck_data.py.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deck_data import (BACKGROUND, DEEPSEEK, GRID, INK, INK_MUTED, INK_SECONDARY, INKLING, PANEL,
                       REFERENCE, SLIDES, TUNED)
from slide_canvas import HEIGHT, WIDTH, Canvas

DECK = Path(__file__).resolve().parent.parent
ASSETS = DECK / "assets"
SLIDE_DIR = ASSETS / "slides"
MARGIN = 80
CONTENT_WIDTH = WIDTH - 2 * MARGIN


# ------------------------------------------------------------------ shared pieces
def new_slide(number: int, kicker: str, kicker_colour: str, subtitle: str = "") -> Canvas:
    """A slide with the standard header and footer."""
    canvas = Canvas(BACKGROUND)
    canvas.text(MARGIN, 52, kicker.upper(), 21, kicker_colour, bold=True)
    canvas.fitted_text(MARGIN, 84, SLIDES[number - 1].title, 58, INK, CONTENT_WIDTH)
    if subtitle:
        canvas.text(MARGIN, 164, subtitle, 25, INK_SECONDARY)
    add_footer(canvas, number)
    return canvas


def add_footer(canvas: Canvas, number: int):
    canvas.text(WIDTH - MARGIN, 1034, f"{number} / {len(SLIDES)}", 17, INK_MUTED, anchor="ra")
    canvas.rect(0, HEIGHT - 5, WIDTH, 5, fill=GRID)
    canvas.rect(0, HEIGHT - 5, WIDTH * number / len(SLIDES), 5, fill=INK_SECONDARY)


def card(canvas: Canvas, x: float, y: float, w: float, h: float, accent: str | None = None):
    canvas.rect(x, y, w, h, fill=PANEL, outline=GRID, radius=12)
    if accent:
        canvas.rect(x, y + 12, 6, h - 24, fill=accent, radius=3)


def frame(canvas: Canvas, name: str, x: float, y: float, w: float, caption: str, accent: str,
          caption_size: float = 20):
    """A 16:9 simulation frame with an accent strip and a caption below it."""
    h = w * 9 / 16
    canvas.picture(ASSETS / name, x, y, w, h, radius=8)
    canvas.rect(x, y + h + 6, w, 4, fill=accent, radius=2)
    canvas.text(x, y + h + 18, caption, caption_size, INK_SECONDARY)


def quote_card(canvas: Canvas, x: float, y: float, w: float, h: float, accent: str, speaker: str,
               quote: str, action: str):
    """Who said it, one short verbatim quote, and what the agent did next."""
    card(canvas, x, y, w, h, accent)
    canvas.text(x + 30, y + 20, speaker, 23, INK_SECONDARY, bold=True)
    below = canvas.paragraph(x + 30, y + 64, quote, 30, INK, w - 60)
    canvas.text(x + 30, below + 10, action, 23, INK_SECONDARY)


def stat(canvas: Canvas, x: float, y: float, value: str, caption: str, colour: str = INK):
    canvas.text(x, y, value, 68, colour, bold=True)
    canvas.text(x, y + 86, caption, 22, INK_SECONDARY)


# ------------------------------------------------------------------ slides
def slide_hook() -> Canvas:
    canvas = Canvas(BACKGROUND)
    canvas.picture(ASSETS / "rover_hero.jpg", 0, 0, WIDTH, HEIGHT, radius=0)
    canvas.shade(0, 0, WIDTH, HEIGHT, BACKGROUND, 0.3, 0.3)
    canvas.shade(0, 0, 1500, HEIGHT, BACKGROUND, 0.95, 0.0)
    canvas.fitted_text(MARGIN, 300, SLIDES[0].title, 110, INK, 1300)
    canvas.text(MARGIN, 450, "Can an agent test before it acts?", 46, INK)
    canvas.rect(MARGIN, 910, 8, 60, fill=INKLING, radius=4)
    canvas.text(MARGIN + 28, 922, "Inkling, stuck in the mud lane. Reward 0.", 27, INK_SECONDARY)
    return canvas


def environment_card(canvas: Canvas, x: float, image: str, heading: str, line: str):
    width = 850
    canvas.picture(ASSETS / image, x, 200, width, width * 9 / 16)
    canvas.text(x, 708, heading, 44, INK, bold=True)
    canvas.text(x, 774, line, 28, INK_SECONDARY)


def slide_challenge() -> Canvas:
    canvas = new_slide(2, "The challenge", REFERENCE)
    environment_card(canvas, MARGIN, "rover_course.jpg", "Rover", "One lane is passable. The map does not say which.")
    environment_card(canvas, 990, "winch_deepseek_2_carry.jpg", "Crane",
                     "One crate can be lifted. The map does not say which.")
    canvas.text(WIDTH / 2, 890, "A cheap test reveals it. The budget has no room for a wrong guess.", 34, INK,
                bold=True, anchor="ma")
    return canvas


def slide_harness() -> Canvas:
    canvas = new_slide(3, "Harness and reward", REFERENCE)
    canvas.chart(ASSETS / "harness.svg", MARGIN, 230, CONTENT_WIDTH)
    canvas.text(MARGIN, 850, "Doing nothing or stopping early scores 0.", 34, INK, bold=True)
    return canvas


def slide_gap() -> Canvas:
    canvas = new_slide(4, "The gap", DEEPSEEK, "75 tasks, 3 runs per model")
    canvas.chart(ASSETS / "results_bar.svg", MARGIN - 20, 250, 1260)
    x, w = 1390, 450
    card(canvas, x, 250, w, 250, DEEPSEEK)
    canvas.text(x + 30, 272, "DeepSeek vs Inkling", 23, INK_SECONDARY)
    canvas.text(x + 30, 312, "+0.243", 76, INK, bold=True)
    canvas.text(x + 30, 420, "same tasks, p = 0.001", 23, INK_SECONDARY)
    return canvas


def slide_rover() -> Canvas:
    canvas = new_slide(5, "Behaviour 1 · rover", INKLING, "Same task, two agents. Only the ice lane is passable.")
    canvas.chart(ASSETS / "rover_paths.svg", MARGIN - 10, 222, 1050)
    x, w = 1150, 690
    quote_card(canvas, x, 222, w, 220, INKLING, "Inkling · reward 0", "“So we are not on mud.”",
               "It was. Then it drove into the mud lane.")
    quote_card(canvas, x, 462, w, 220, DEEPSEEK, "DeepSeek · reward 0.70", "“The mud lane is likely impassable.”",
               "Then it took the ice lane.")
    frames = [("rover_inkling_1_strip.jpg", "20 s, on the mud sample", INKLING),
              ("rover_inkling_2_fork.jpg", "72 s, into the mud lane", INKLING),
              ("rover_inkling_3_stuck.jpg", "86 s, stuck", INKLING),
              ("rover_deepseek_1_strip.jpg", "17 s, on the mud sample", DEEPSEEK),
              ("rover_deepseek_2_ice.jpg", "43 s, on the ice lane", DEEPSEEK),
              ("rover_deepseek_3_goal.jpg", "59 s, delivered", DEEPSEEK)]
    frame_width, gap = 280, 16
    for i, (name, caption, accent) in enumerate(frames):
        frame(canvas, name, MARGIN + i * (frame_width + gap), 730, frame_width, caption, accent)
    canvas.text(MARGIN, 950, "INKLING", 19, INKLING, bold=True)
    canvas.text(MARGIN + 3 * (frame_width + gap), 950, "DEEPSEEK", 19, DEEPSEEK, bold=True)
    return canvas


def slide_winch() -> Canvas:
    canvas = new_slide(6, "Behaviour 2 · crane", INKLING, "Same task, two agents. The cable is rated 2000 N.")
    canvas.chart(ASSETS / "winch_tension.svg", MARGIN - 10, 220, 900)
    quote_card(canvas, MARGIN, 712, 890, 190, INKLING, "Inkling · reward 0",
               "“If tension rises too high, we stop.”", "The map says the stop is a trigger, not a cap.")
    x, frame_width, gap = 1020, 402, 16
    frames = [("winch_inkling_1_hooked.jpg", "12.0 s, hooked", INKLING, 0, 0),
              ("winch_inkling_2_snapped.jpg", "13.3 s, cable snapped", INKLING, 1, 0),
              ("winch_deepseek_1_weigh.jpg", "16.2 s, the crate lifts", DEEPSEEK, 0, 1),
              ("winch_deepseek_3_delivered.jpg", "47.5 s, delivered", DEEPSEEK, 1, 1)]
    for name, caption, accent, column, row in frames:
        frame(canvas, name, x + column * (frame_width + gap), 222 + row * 300, frame_width, caption, accent)
    canvas.text(x, 836, "Inkling pulled a 259 kg crate, DeepSeek a 122 kg one.", 22, INK_MUTED)
    return canvas


TRACE = [  # (step, kind, text), verbatim from the trial, long lines elided with "…"
    ("23", "call", "read /sim_result/result.json"),
    ("", "out", '{"reward": 0.0, "outcome": {"delivered": false, …'),
    ("39", "call", "$ curl -X POST http://rover-sim:8000/mcp … initialize"),
    ("", "out", "mcp-session-id: d997df7253ba4278824a63a960693206"),
    ("41", "call", "$ curl … tools/call observe"),
    ("", "out", '{"t": 39.64, "pose": {"x": 10.239, "y": -2.679, …'),
    ("", "note", "same ended episode"),
]
TRACE_COLOUR = {"call": INK, "out": INK_MUTED, "note": REFERENCE}


def slide_shortcut() -> Canvas:
    canvas = new_slide(7, "Behaviour 3 · reward integrity", INKLING, "Inkling, after crashing with reward 0")
    x, y, w, h = MARGIN, 222, 1130, 500
    canvas.rect(x, y, w, h, fill="#0a0d14", outline=GRID, radius=12)
    line_y = y + 30
    for step, kind, content in TRACE:
        if step:
            line_y += 14
            canvas.text(x + 28, line_y, f"step {step}", 23, INK_MUTED, mono=True)
        canvas.text(x + 180, line_y, content, 23, TRACE_COLOUR[kind], mono=True, bold=kind == "note")
        line_y += 54
    frame(canvas, "exploit_crash.jpg", 1250, 222, 590, "The crash it wanted to undo", INKLING)
    for i, (value, caption) in enumerate((("117", "trials tried the shell"), ("986", "shell and file calls"),
                                          ("0", "reward gained"))):
        stat(canvas, MARGIN + i * 400, 780, value, caption, REFERENCE if value == "0" else INK)
    return canvas


def comparison_tile(canvas: Canvas, x: float, y: float, heading: str, inkling: tuple, deepseek: tuple,
                    full_scale: float, marker: tuple | None = None):
    """Two horizontal bars. Each of inkling/deepseek is (value, label). `marker` is (value, label)."""
    w, h = 860, 300
    card(canvas, x, y, w, h)
    canvas.text(x + 34, y + 26, heading, 31, INK, bold=True)
    bar_left, bar_width = x + 210, 420
    for i, (name, colour, (value, label)) in enumerate((("Inkling", INKLING, inkling),
                                                        ("DeepSeek", DEEPSEEK, deepseek))):
        bar_y = y + 108 + i * 76
        canvas.text(x + 34, bar_y + 2, name, 25, INK_SECONDARY)
        canvas.rect(bar_left, bar_y, bar_width, 38, fill=GRID, radius=4)
        canvas.rect(bar_left, bar_y, max(bar_width * value / full_scale, 4), 38, fill=colour, radius=4)
        canvas.text(bar_left + bar_width + 24, bar_y - 3, label, 35, INK, bold=True)
    if marker:
        marker_x = bar_left + bar_width * marker[0] / full_scale
        canvas.line(marker_x, y + 96, marker_x, y + 234, INK, 2)
        canvas.text(marker_x, y + 242, marker[1], 21, INK_SECONDARY, anchor="ma")


def slide_patterns() -> Canvas:
    canvas = new_slide(8, "Meaningful difficulty", DEEPSEEK)
    comparison_tile(canvas, MARGIN, 220, "Took the open lane after testing", (60, "60%"), (94, "94%"), 100,
                    (46, "chance 46%"))
    comparison_tile(canvas, 980, 220, "Time spent on the start pad", (51, "51%"), (26, "26%"), 100)
    comparison_tile(canvas, MARGIN, 550, "Rover ran out of time", (17, "17 / 108"), (1, "1 / 108"), 108)
    comparison_tile(canvas, 980, 550, "Crane cable snapped", (89, "89 / 117"), (67, "67 / 117"), 117)
    canvas.text(MARGIN, 900, "Everything they needed was in the map.", 34, INK, bold=True)
    return canvas


def slide_finetune() -> Canvas:
    canvas = new_slide(9, "What we tried", TUNED, "Qwen3.6-27B, trained on its own successful episodes")
    canvas.chart(ASSETS / "qwen_finetune.svg", MARGIN - 60, 380, 1200)
    x, w = 1260, 580
    card(canvas, x, 380, w, 330, TUNED)
    canvas.text(x + 34, 404, "Tuned vs untuned", 25, INK_SECONDARY)
    canvas.text(x + 34, 448, "−0.022", 84, INK, bold=True)
    canvas.text(x + 34, 568, "95% CI [−0.098, +0.053]", 27, INK_SECONDARY)
    canvas.text(x + 34, 628, "No measurable improvement", 31, INK, bold=True)
    return canvas


def slide_close() -> Canvas:
    canvas = Canvas(BACKGROUND)
    canvas.picture(ASSETS / "rover_closing.jpg", 0, 0, WIDTH, HEIGHT, radius=0)
    canvas.shade(0, 0, 900, HEIGHT, BACKGROUND, 0.6, 0.0)
    canvas.fitted_text(MARGIN, 800, SLIDES[-1].title + ".", 92, INK, 1500)
    canvas.text(MARGIN, 930, "Delivered.", 36, INK_SECONDARY)
    return canvas


DRAW_SLIDE = (slide_hook, slide_challenge, slide_harness, slide_gap, slide_rover, slide_winch,
              slide_shortcut, slide_patterns, slide_finetune, slide_close)


# ------------------------------------------------------------------ outputs
def slide_file(number: int) -> str:
    return f"slide_{number:02d}.png"


def write_slide_images() -> list:
    SLIDE_DIR.mkdir(parents=True, exist_ok=True)
    images = []
    for number, draw in enumerate(DRAW_SLIDE, start=1):
        image = draw().finished()
        image.save(SLIDE_DIR / slide_file(number), optimize=True)
        images.append(image)
    return images


def write_pdf(images: list):
    images[0].save(DECK / "deck.pdf", save_all=True, append_images=images[1:], resolution=144.0, quality=90)


def write_html():
    slides = [{"image": f"assets/slides/{slide_file(n)}", "title": s.title, "seconds": s.seconds,
               "notes": s.narration} for n, s in enumerate(SLIDES, start=1)]
    template = (DECK / "scripts" / "index_template.html").read_text()
    figures = "\n".join(
        f'    <img class="slide" src="{html.escape(s["image"])}" alt="Slide {n}: {html.escape(s["title"])}">'
        for n, s in enumerate(slides, start=1))
    page = template.replace("<!--SLIDES-->", figures).replace("/*SLIDE_DATA*/[]", json.dumps(slides, ensure_ascii=False))
    (DECK / "index.html").write_text(page)


def write_script():
    total_seconds = sum(s.seconds for s in SLIDES)
    total_words = sum(len(s.narration.split()) for s in SLIDES)
    lines = ["# Narration and shot list", "",
             f"Total: {total_seconds} s, {total_words} words (about {total_words / total_seconds:.1f} words "
             "per second). Generated by `scripts/build_deck.py` from `scripts/deck_data.py`. Edit there.", "",
             "Open `index.html` (arrow keys, `n` for notes, `t` for timed autoplay) or upload `deck.pdf`.", "",
             "## Narration", ""]
    start = 0
    for number, slide in enumerate(SLIDES, start=1):
        end = start + slide.seconds
        lines += [f"### {number}. {slide.title} ({start // 60}:{start % 60:02d}–{end // 60}:{end % 60:02d}, "
                  f"{slide.seconds} s, {len(slide.narration.split())} words)", "", f"> {slide.narration}", ""]
        start = end
    lines += ["## Shot list", "", "| Slide | Image | Assets used | Trial directories, steps, data |",
              "|---|---|---|---|"]
    for number, slide in enumerate(SLIDES, start=1):
        assets = "<br>".join(f"`assets/{a}`" for a in slide.assets) or "drawn by `build_deck.py`"
        lines.append(f"| {number}. {slide.title} | `assets/slides/{slide_file(number)}` | {assets} | "
                     + "<br>".join(slide.sources) + " |")
    lines += ["", (DECK / "scripts" / "script_appendix.md").read_text().rstrip()]
    (DECK / "script.md").write_text("\n".join(lines) + "\n")


def main():
    images = write_slide_images()
    write_pdf(images)
    write_html()
    write_script()
    print(f"wrote {len(images)} slides, deck.pdf, index.html and script.md in {DECK}")


if __name__ == "__main__":
    main()
