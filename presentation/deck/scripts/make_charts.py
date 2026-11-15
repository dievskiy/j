"""Write the deck's charts and diagrams as SVG files into presentation/deck/assets/.

    python3 presentation/deck/scripts/make_charts.py

Headline numbers are the final ones from README.md / results/final_table.md and
presentation/analysis.md. The path map and the tension chart read the replay states that
render_all.sh writes to presentation/deck/work/states/, so run that first.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DECK = Path(__file__).resolve().parent.parent
ASSETS = DECK / "assets"
STATES = DECK / "work" / "states"
WORK = DECK / "work"

from deck_data import (BASELINE, DEEPSEEK, GRID, INK, INK_MUTED, INK_SECONDARY, INKLING, PANEL,
                       REFERENCE, ROUND_2_MEAN, ROUND_2_TEXT, TUNED)

FONT = "'DejaVu Sans', Verdana, 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', 'DejaVu Sans Mono', Menlo, Consolas, monospace"


def svg(width: int, height: int, body: list[str]) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" font-family="{FONT}">\n' + "\n".join(body) + "\n</svg>\n")


def text(x: float, y: float, content: str, size: int = 22, fill: str = INK, anchor: str = "start",
         weight: int = 400, family: str | None = None) -> str:
    family_attr = f' font-family="{family}"' if family else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}"{family_attr}>{content}</text>')


# ------------------------------------------------------------------ results bar chart
RESULTS = [  # label, sublabel, mean, run means, delivery, colour
    ("Reference", "scripted, same MCP tools", 0.748, [0.748], "100% delivered", REFERENCE),
    ("DeepSeek 4.1 Flash", "3 runs × 75 tasks", 0.332, [0.372, 0.271, 0.352], "45% delivered", DEEPSEEK),
    ("Inkling", "3 runs × 75 tasks", 0.082, [0.075, 0.085, 0.085], "12% delivered", INKLING),
    ("Do-nothing", "Harbor nop agent", 0.0, [], "0 on all 75", BASELINE),
    ("Stop-early", "finish at once / half the reference", 0.0, [], "0 on all 75", BASELINE),
]


def results_chart() -> str:
    width, height = 1240, 600
    left, right, top, row = 380, 940, 40, 96
    scale = (right - left) / 0.8
    body = []
    for tick in (0, 0.2, 0.4, 0.6, 0.8):
        x = left + tick * scale
        body.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top + row * len(RESULTS)}" stroke="{GRID}" stroke-width="1"/>')
        body.append(text(x, top + row * len(RESULTS) + 32, f"{tick:.1f}", 20, INK_MUTED, "middle"))
    body.append(text((left + right) / 2, height - 12, "mean reward on the 75 frozen tasks (0 = failed, 1 = perfect)",
                     20, INK_MUTED, "middle"))
    for i, (label, sublabel, mean, runs, delivery, colour) in enumerate(RESULTS):
        y = top + i * row + row / 2
        body.append(text(left - 24, y - 4, label, 27, INK, "end", 600))
        body.append(text(left - 24, y + 24, sublabel, 18, INK_MUTED, "end"))
        bar = max(mean * scale, 3)
        body.append(f'<path d="M{left},{y - 19} h{bar - 4:.1f} a4,4 0 0 1 4,4 v30 a4,4 0 0 1 -4,4 h-{bar - 4:.1f} z" fill="{colour}"/>'
                    if mean > 0 else f'<rect x="{left}" y="{y - 19}" width="3" height="38" fill="{colour}"/>')
        if len(runs) > 1:
            low, high = left + min(runs) * scale, left + max(runs) * scale
            body.append(f'<line x1="{low:.1f}" y1="{y}" x2="{high:.1f}" y2="{y}" stroke="{INK}" stroke-width="2"/>')
            for run in runs:
                body.append(f'<circle cx="{left + run * scale:.1f}" cy="{y}" r="6" fill="{INK}" stroke="#0d1119" stroke-width="2"/>')
        label_x = left + max([mean] + runs) * scale + 18
        body.append(text(label_x, y + 4, f"{mean:.3f}" if mean else "0", 30, INK, weight=700))
        body.append(text(label_x + (118 if mean else 34), y + 2, delivery, 21, INK_SECONDARY))
    body.append(f'<circle cx="{right - 150}" cy="{top + row * 1.5 + 34}" r="6" fill="{INK}"/>')
    body.append(text(right - 136, top + row * 1.5 + 41, "= one run's mean", 19, INK_SECONDARY))
    return svg(width, height, body)


# ------------------------------------------------------------------ rover path map
SURFACE_FILL = {"ice": "#a9d8ee", "mud": "#8a5a2b", "wind": "#d8c878"}


def rover_map() -> dict:
    trajectory = json.load(open(next((WORK / "rover").glob("rover-fork_mud_ice_wind-*iGPKtYU"))
                                / "agent" / "trajectory.json"))
    for step in trajectory["steps"]:
        for call, result in zip(step.get("tool_calls") or [], (step.get("observation") or {}).get("results", [])):
            if call["function_name"] == "rover_get_map":
                content = json.loads(result["content"])
                return content.get("map", content)
    raise ValueError("no get_map result in the trajectory")


def rover_paths_chart() -> str:
    width, height = 1240, 560
    course = rover_map()
    scale = 16.0
    origin_x, origin_y = 150, height / 2

    def px(x: float, y: float) -> tuple[float, float]:
        return origin_x + x * scale, origin_y - y * scale

    def rect(spec: dict, fill: str, opacity: float = 1.0) -> str:
        x0, y1 = px(spec["x"][0], spec["y"][1])
        return (f'<rect x="{x0:.1f}" y="{y1:.1f}" width="{(spec["x"][1] - spec["x"][0]) * scale:.1f}" '
                f'height="{(spec["y"][1] - spec["y"][0]) * scale:.1f}" fill="{fill}" opacity="{opacity}"/>')

    def path(name: str, colour: str) -> str:
        states = json.load(open(STATES / f"{name}.json"))["snapshots"]
        points = " ".join(f"{a:.1f},{b:.1f}" for a, b in (px(*s["qpos"][:2]) for s in states[::3]))
        return (f'<polyline points="{points}" fill="none" stroke="#0d1119" stroke-width="8" stroke-linejoin="round"/>'
                f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')

    body = [rect(s, "#3a4356") for s in course["drivable_surfaces"]]
    body += [rect(p, SURFACE_FILL[p["surface"]], 0.9) for p in course["surface_patches"]]
    goal_x, goal_y = px(course["goal"]["x"], course["goal"]["y"])
    body.append(f'<circle cx="{goal_x:.1f}" cy="{goal_y:.1f}" r="{course["goal"]["radius"] * scale:.1f}" fill="{REFERENCE}"/>')
    body.append(path("rover_deepseek", DEEPSEEK))
    body.append(path("rover_inkling", INKLING))
    end_x, end_y = px(21.84, -0.09)
    body.append(f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="9" fill="{INKLING}" stroke="#0d1119" stroke-width="2"/>')
    body.append(f'<circle cx="{goal_x:.1f}" cy="{goal_y:.1f}" r="9" fill="{DEEPSEEK}" stroke="#0d1119" stroke-width="2"/>')

    def label(x: float, y: float, content: str, size: int = 20, fill: str = INK_SECONDARY, anchor: str = "start",
              weight: int = 400) -> str:
        a, b = px(x, y)
        return text(a, b, content, size, fill, anchor, weight)

    body += [
        label(-8, 10.7, "start pad with sample strips", 19, INK_SECONDARY),
        label(5.5, -5.4, "mud", 18, "#f3e6d6", "middle", 600),
        label(5.5, 3.4, "ice", 18, "#0d1119", "middle", 600),
        label(-5, 6.6, "wind", 18, "#0d1119", "middle", 600),
        label(30.5, 14.5, "ice lane: the only passable one (hidden)", 20, INK, "middle", 600),
        label(42.5, -3.4, "mud lane: too thick (hidden)", 20, INK, "end", 600),
        label(30.5, -15.4, "wind lane: too strong (hidden)", 20, INK_SECONDARY, "middle"),
        label(51.4, 4.3, "goal", 20, INK, "middle", 600),
        label(22.9, 2.5, "Inkling stalls here, 5 s left", 20, INK, "start", 600),
        label(-8, -11.6, "Inkling: 52 s in the mud sample", 20, INK, "start", 600),
        label(56.0, 0.9, "DeepSeek:", 20, INK, "start", 600),
        label(56.0, -0.9, "delivered at 59 s", 20, INK, "start", 600),
    ]
    legend_y = height - 14
    for i, (name, colour) in enumerate((("Inkling path", INKLING), ("DeepSeek path", DEEPSEEK))):
        x = 20 + i * 220
        body.append(f'<line x1="{x}" y1="{legend_y - 6}" x2="{x + 36}" y2="{legend_y - 6}" stroke="{colour}" stroke-width="4"/>')
        body.append(text(x + 46, legend_y, name, 20, INK_SECONDARY))
    return svg(width, height, body)


# ------------------------------------------------------------------ winch tension chart
def weighing_pull(name: str, first_pull_label: str, seconds: float) -> list[tuple]:
    """True cable tension over the first `seconds` after the agent's first weighing pull began."""
    replay = json.load(open(STATES / f"{name}.json"))
    snapshots = replay["snapshots"]
    first = next(i for i, s in enumerate(snapshots) if s["label"].startswith(first_pull_label))
    start = snapshots[first - 1]["t"]          # the pull began when the previous call ended
    return [(t - start, tension) for t, tension in replay["tension"] if 0 <= t - start <= seconds]


def winch_tension_chart() -> str:
    width, height = 1000, 520
    left, right, top, bottom = 96, 960, 30, 440
    seconds, max_tension = 4.0, 2200.0
    x_scale, y_scale = (right - left) / seconds, (bottom - top) / max_tension

    def px(t: float, tension: float) -> tuple[float, float]:
        return left + t * x_scale, bottom - tension * y_scale

    def line(series: list, colour: str) -> str:
        points = " ".join(f"{a:.1f},{b:.1f}" for a, b in (px(*p) for p in series[::5]))
        return f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="3.5" stroke-linejoin="round"/>'

    inkling = weighing_pull("winch_inkling", "winch(length_change=-1", seconds)
    deepseek = weighing_pull("winch_deepseek", "winch(length_change=-0.1", seconds)
    body = []
    for tick in (0, 500, 1000, 1500, 2000):
        _, y = px(0, tick)
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        body.append(text(left - 12, y + 7, f"{tick}", 19, INK_MUTED, "end"))
    for tick in range(0, 5):
        x, _ = px(tick, 0)
        body.append(text(x, bottom + 30, f"{tick} s", 19, INK_MUTED, "middle"))
    body.append(text((left + right) / 2, height - 14, "time since the first weighing pull began", 20, INK_MUTED, "middle"))
    body.append(text(left - 70, top + 4, "cable tension [N]", 19, INK_MUTED))
    _, rating_y = px(0, 2000)
    body.append(f'<line x1="{left}" y1="{rating_y:.1f}" x2="{right}" y2="{rating_y:.1f}" stroke="{INK}" stroke-width="2" stroke-dasharray="8 6"/>')
    body.append(text(right, rating_y - 10, "cable rating 2000 N", 20, INK, "end", 600))
    body.append(line(deepseek, DEEPSEEK))
    body.append(line(inkling, INKLING))
    snap_t, snap_tension = max(inkling, key=lambda p: p[1])
    trip = next(p for p in inkling if p[1] >= 1800 - 110.5)           # reading = true tension + 110.5 N offset
    for (t, tension), caption, dy in ((trip, "stop_tension trips; drum starts braking", 8),
                                      ((snap_t, snap_tension), f"cable snaps {snap_t:.2f} s into the pull", 32)):
        x, y = px(t, tension)
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{INKLING}" stroke="#0d1119" stroke-width="2"/>')
        body.append(text(x + 16, y + dy, caption, 20, INK, weight=600))
        label_x, label_y = px(4.0, 760)
    body.append(text(label_x, label_y, "DeepSeek: 0.10 m, then 0.15 m; the crate lifts at ~1200 N", 20, INK, "end", 600))
    label_x, label_y = px(0.04, 1790)
    body.append(text(label_x, label_y, "Inkling: one 1 m pull", 20, INK, weight=600))
    return svg(width, height, body)


# ------------------------------------------------------------------ harness diagram
def box(x: float, y: float, w: float, h: float, title: str, lines: list[str], stroke: str = GRID,
        fill: str = PANEL) -> list[str]:
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="2"/>',
             text(x + 24, y + 42, title, 25, INK, weight=700)]
    parts += [text(x + 24, y + 78 + 30 * i, line, 20, INK_SECONDARY) for i, line in enumerate(lines)]
    return parts


def arrow(x1: float, y1: float, x2: float, y2: float, colour: str = INK_SECONDARY, dashed: bool = False) -> str:
    dash = ' stroke-dasharray="7 6"' if dashed else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" stroke-width="3"{dash} '
            f'marker-end="url(#head-{colour.strip("#")})"/>')


def marker(colour: str) -> str:
    return (f'<marker id="head-{colour.strip("#")}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{colour}"/></marker>')


def harness_diagram() -> str:
    width, height = 1680, 560
    body = [f"<defs>{marker(INK_SECONDARY)}{marker(REFERENCE)}</defs>"]
    body += box(20, 20, 470, 250, "Agent container", [
        "Harbor runs OpenCode with the model", "sees the map, readings and traces",
        "no sim code, seed or hidden values", "has a shell (and uses it)"], stroke=DEEPSEEK)
    body += box(605, 20, 470, 250, "MCP tools", [
        "get_map · observe · finish", "rover: drive_to · brake · wait",
        "hoist: move_trolley · winch · attach", "the only way to touch the simulator"])
    body += box(1190, 20, 470, 250, "Simulator sidecar", [
        "MuJoCo episode, hidden physics", "time and energy budgets",
        "reward from simulator state only:", "0, or 0.5 + 0.5 × efficiency"], stroke=REFERENCE)
    body.append(arrow(492, 110, 603, 110))
    body.append(arrow(603, 180, 492, 180))
    body.append(arrow(1077, 110, 1188, 110))
    body.append(arrow(1188, 180, 1077, 180))
    body.append(text(547, 96, "calls", 19, INK_MUTED, "middle"))
    body.append(text(547, 212, "readings", 19, INK_MUTED, "middle"))
    body += box(1190, 380, 470, 150, "result.json", [
        "written by the simulator, on finish", "agent container mounts it read-only"], stroke=REFERENCE)
    body.append(arrow(1425, 272, 1425, 378, REFERENCE))
    body += box(605, 380, 470, 150, "Harbor verifier", ["reads the reward from the file;", "never asks the agent"])
    body.append(arrow(1188, 455, 1077, 455, REFERENCE))
    body += box(20, 380, 470, 150, "Baselines", ["do-nothing: 0 on all 75 tasks", "stop-early: 0 on all 75 tasks"])
    return svg(width, height, body)


# ------------------------------------------------------------------ fine-tuning chart
def finetune_chart() -> str:
    width, height = 1000, 350
    left, right, row, top = 320, 760, 84, 30
    scale = (right - left) / 0.8
    rows = [("Qwen3.6-27B untuned", 0.319, BASELINE), ("Fine-tuned, round 1", 0.297, TUNED)]
    if ROUND_2_MEAN is not None:
        rows.append(("Fine-tuned, round 2", ROUND_2_MEAN, TUNED))
    body = []
    for tick in (0, 0.2, 0.4, 0.6, 0.8):
        x = left + tick * scale
        body.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top + row * 3}" stroke="{GRID}"/>')
        body.append(text(x, top + row * 3 + 30, f"{tick:.1f}", 19, INK_MUTED, "middle"))
    for i, (label, mean, colour) in enumerate(rows):
        y = top + i * row + row / 2
        body.append(text(left - 20, y + 8, label, 23, INK, "end", 600))
        bar = mean * scale
        body.append(f'<path d="M{left},{y - 17} h{bar - 4:.1f} a4,4 0 0 1 4,4 v26 a4,4 0 0 1 -4,4 h-{bar - 4:.1f} z" fill="{colour}"/>')
        body.append(text(left + bar + 16, y + 10, f"{mean:.3f}", 28, INK, weight=700))
    if ROUND_2_MEAN is None:
        y = top + 2 * row + row / 2
        body.append(text(left - 20, y + 8, "Fine-tuned, round 2", 23, INK_SECONDARY, "end", 600))
        body.append(f'<rect x="{left}" y="{y - 17}" width="{0.3 * scale:.1f}" height="34" rx="4" fill="none" stroke="{INK_MUTED}" stroke-width="2" stroke-dasharray="7 6"/>')
        body.append(text(left + 0.3 * scale + 16, y + 9, ROUND_2_TEXT, 24, INK_SECONDARY, weight=700))
    body.append(text((left + right) / 2, height - 6, "mean reward, same 75 frozen tasks", 19, INK_MUTED, "middle"))
    return svg(width, height, body)


def main():
    ASSETS.mkdir(exist_ok=True)
    charts = {"results_bar.svg": results_chart, "rover_paths.svg": rover_paths_chart,
              "winch_tension.svg": winch_tension_chart, "harness.svg": harness_diagram,
              "qwen_finetune.svg": finetune_chart}
    for name, make in charts.items():
        (ASSETS / name).write_text(make())
        print("wrote", ASSETS / name)


if __name__ == "__main__":
    main()
