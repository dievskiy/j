"""Replay a copied Harbor trial (rover or winch) and render high-resolution stills.

    .venv/bin/python presentation/deck/scripts/replay_frames.py <trial copy> \
        --sheet sheet.png                         # contact sheet to pick moments
    .venv/bin/python presentation/deck/scripts/replay_frames.py <trial copy> \
        --frame out.png:31.5:overview --frame out2.png:86.5:chase [--clip clip.mp4:20:40:chase]

The simulators are deterministic, so replaying the recorded MCP tool calls on a fresh
Episode reproduces the trial. The replayed reward and end time are checked against
verifier/sim_result.json and the result is printed. Nothing is written into the trial
directory. Run it on a COPY of the trial, never on jobs/.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
os.environ.setdefault("MUJOCO_GL", "egl")

import mujoco
import numpy as np
from PIL import Image

SNAPSHOT_SECONDS = 0.1
ROVER_TOOLS = ("drive_to", "brake", "wait", "finish")
WINCH_TOOLS = ("move_trolley", "winch", "attach", "release", "wait", "finish")


def load_trial(trial_dir: str) -> tuple[dict, list]:
    """The verifier's result and the ordered (tool, arguments) calls of the trial."""
    expected = json.load(open(os.path.join(trial_dir, "verifier", "sim_result.json")))
    trajectory = json.load(open(os.path.join(trial_dir, "agent", "trajectory.json")))
    calls = [(call["function_name"], call.get("arguments") or {})
             for step in trajectory.get("steps", []) for call in step.get("tool_calls") or []]
    return expected, calls


def make_episode(expected: dict):
    """A fresh episode of the trial's task, its time-advancing tools and step method."""
    if expected["course"] == "winch_yard":
        from winch_env.env import Episode
        episode = Episode(expected["seed"], expected["difficulty"], expected.get("variation"))
        return episode, "hoist_", WINCH_TOOLS, "_physics_step"
    from rover_env.env import Episode
    episode = Episode(expected["seed"], expected["difficulty"], expected["course"])
    return episode, "rover_", ROVER_TOOLS, "_substep"


def replay(trial_dir: str) -> tuple[object, list, list, bool]:
    """Replay the trial. Returns the episode, state snapshots, the winch's true cable
    tension per physics step as (t, newtons) (empty for the rover), and whether the
    replay matched the recorded outcome."""
    expected, calls = load_trial(trial_dir)
    episode, prefix, tools, step_method = make_episode(expected)
    snapshots: list[dict] = []
    tension: list[tuple] = []
    label = {"text": "start"}

    def snap():
        data = episode.data
        snapshots.append({"t": episode.t, "label": label["text"], "qpos": data.qpos.copy(),
                          "qvel": data.qvel.copy(), "mocap": data.mocap_pos.copy(),
                          "tendon_rgba": episode.model.tendon_rgba.copy()})

    original_step = getattr(episode, step_method)

    def step(*args, **kwargs):
        result = original_step(*args, **kwargs)
        if hasattr(episode, "tension"):
            tension.append((round(episode.t, 4), round(float(episode.tension), 1)))
        if episode.t - snapshots[-1]["t"] >= SNAPSHOT_SECONDS - 1e-9:
            snap()
        return result

    snap()
    setattr(episode, step_method, step)
    for name, arguments in calls:
        tool = name.removeprefix(prefix)
        if tool in tools:
            label["text"] = f"{tool}({', '.join(f'{k}={v}' for k, v in arguments.items())})"
            getattr(episode, tool)(**arguments)
            snap()
    outcome = episode.outcome()
    matched = (abs(episode.reward() - expected["reward"]) < 1e-9
               and outcome["t"] == expected["outcome"]["t"]
               and outcome.get("reason") == expected["outcome"].get("reason"))
    return episode, snapshots, tension, matched


def camera_views(episode, data) -> dict:
    """Named cameras for the episode's current state."""
    if hasattr(episode, "_rover"):
        x, y, z = data.qpos[:3]
        rotation = data.xmat[episode._rover].reshape(3, 3)
        yaw = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))
        return {
            "overview": episode._lay.overview_camera,
            "chase": {"lookat": (x, y, z), "distance": 10.0, "elevation": -35.0, "azimuth": yaw},
            "close": {"lookat": (x, y, z), "distance": 7.0, "elevation": -22.0, "azimuth": yaw + 35},
            "side": {"lookat": (x, y, z), "distance": 9.0, "elevation": -18.0, "azimuth": 90.0},
            "high": {"lookat": (x, y, z), "distance": 22.0, "elevation": -50.0, "azimuth": 90.0},
        }
    hook = data.mocap_pos[1]
    return {
        "overview": {"lookat": (2.0, 0.0, 3.5), "distance": 26.0, "elevation": -12.0, "azimuth": 90.0},
        "chase": {"lookat": (hook[0], 0.0, max(hook[2] - 0.5, 1.0)), "distance": 9.0,
                  "elevation": -15.0, "azimuth": 70.0},
        "close": {"lookat": (hook[0], 0.0, max(hook[2] - 0.6, 0.9)), "distance": 6.0,
                  "elevation": -10.0, "azimuth": 75.0},
        "side": {"lookat": (hook[0] + 3.0, 0.0, 3.0), "distance": 16.0, "elevation": -10.0,
                 "azimuth": 90.0},
    }


class StillRenderer:
    """Renders snapshots of one episode at a fixed resolution."""

    def __init__(self, episode, width: int, height: int):
        import copy
        self.episode = episode
        self.model = copy.copy(episode.model)
        self.model.vis.global_.offwidth = max(self.model.vis.global_.offwidth, width)
        self.model.vis.global_.offheight = max(self.model.vis.global_.offheight, height)
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, height, width)

    def render(self, snapshot: dict, view: str, overrides: dict | None = None) -> Image.Image:
        self.data.qpos[:], self.data.qvel[:] = snapshot["qpos"], snapshot["qvel"]
        self.data.mocap_pos[:] = snapshot["mocap"]
        self.model.tendon_rgba[:] = snapshot["tendon_rgba"]
        mujoco.mj_forward(self.model, self.data)
        spec = dict(camera_views(self.episode, self.data)[view], **(overrides or {}))
        camera = mujoco.MjvCamera()
        camera.lookat[:] = spec["lookat"]
        camera.distance, camera.elevation, camera.azimuth = (
            spec["distance"], spec["elevation"], spec["azimuth"])
        self.renderer.update_scene(self.data, camera)
        return Image.fromarray(self.renderer.render())


def snapshot_at(snapshots: list, t: float) -> dict:
    return min(snapshots, key=lambda s: abs(s["t"] - t))


def save_sheet(episode, snapshots: list, path: str, count: int, views: list):
    """A grid of small labelled frames, evenly spaced in time, to pick moments from."""
    from PIL import ImageDraw
    width, height = 400, 225
    renderer = StillRenderer(episode, width, height)
    end = snapshots[-1]["t"]
    columns = 4
    rows = math.ceil(count / columns)
    sheet = Image.new("RGB", (columns * width * len(views), rows * height))
    for i in range(count):
        snapshot = snapshot_at(snapshots, end * i / (count - 1))
        for j, view in enumerate(views):
            tile = renderer.render(snapshot, view)
            ImageDraw.Draw(tile).text((5, 5), f"t={snapshot['t']:.1f} {snapshot['label'][:52]}",
                                      fill=(255, 255, 0))
            sheet.paste(tile, (((i % columns) * len(views) + j) * width, (i // columns) * height))
    sheet.save(path)


def save_clip(renderer: StillRenderer, snapshots: list, path: str, start: float, end: float,
              view: str, speed: float):
    """A short mp4 between two simulated times, played `speed` times faster than real time."""
    import imageio.v2 as imageio
    fps = 20
    stride = max(1, round(speed * (1 / fps) / SNAPSHOT_SECONDS))
    chosen = [s for s in snapshots if start <= s["t"] <= end][::stride]
    with imageio.get_writer(path, fps=fps, quality=6, macro_block_size=8) as writer:
        for snapshot in chosen:
            writer.append_data(np.asarray(renderer.render(snapshot, view)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trial_dir")
    parser.add_argument("--sheet", help="write a contact sheet PNG here")
    parser.add_argument("--sheet-count", type=int, default=24)
    parser.add_argument("--sheet-views", default="overview,chase")
    parser.add_argument("--frame", action="append", default=[],
                        help="path:time:view[:json camera overrides], repeatable")
    parser.add_argument("--clip", action="append", default=[],
                        help="path:start:end:view[:speed], repeatable")
    parser.add_argument("--size", default="1600x900")
    parser.add_argument("--dump-states",
                        help="write the outcome, per-snapshot poses and the tension series as JSON")
    args = parser.parse_args()
    if "/jobs/" in os.path.abspath(args.trial_dir) + "/":
        sys.exit("refusing to run on jobs/: copy the trial directory first")

    episode, snapshots, tension, matched = replay(args.trial_dir)
    outcome = episode.outcome()
    print(f"{args.trial_dir}: replay matches recorded outcome = {matched} "
          f"(reward {episode.reward():.3f}, {outcome.get('reason')}, t = {outcome['t']})")

    if args.dump_states:
        rows = [{"t": round(s["t"], 3), "label": s["label"],
                 "qpos": [round(float(v), 3) for v in s["qpos"][:3]],
                 "mocap": [[round(float(v), 3) for v in m] for m in s["mocap"]]} for s in snapshots]
        json.dump({"matched": matched, "reward": episode.reward(), "outcome": outcome,
                   "snapshots": rows, "tension": tension}, open(args.dump_states, "w"))
    if args.sheet:
        save_sheet(episode, snapshots, args.sheet, args.sheet_count, args.sheet_views.split(","))
    if args.frame or args.clip:
        width, height = map(int, args.size.split("x"))
        renderer = StillRenderer(episode, width, height)
        for spec in args.frame:
            path, t, view, *rest = spec.split(":", 3)
            overrides = json.loads(rest[0]) if rest else None
            renderer.render(snapshot_at(snapshots, float(t)), view, overrides).save(path)
            print("wrote", path)
        for spec in args.clip:
            path, start, end, view, *rest = spec.split(":")
            save_clip(renderer, snapshots, path, float(start), float(end), view,
                      float(rest[0]) if rest else 4.0)
            print("wrote", path)


if __name__ == "__main__":
    main()
