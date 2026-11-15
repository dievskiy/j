"""Save a few PNG frames of a scenario to rover_env/renders/ (offscreen EGL).

    MUJOCO_GL=egl python -m rover_env.render --seed 6
Rendering is optional and never used by the reward.
"""
from __future__ import annotations

import argparse
import os

from .env import Episode

OUT = os.path.join(os.path.dirname(__file__), "renders")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=6)
    a = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    ep = Episode(a.seed)
    m = ep.observe()["map"]
    saved = []

    def snap(name, cam="chase"):
        png = ep.render_png(cam, 960, 720)
        if png is None:
            print("render failed:", getattr(ep, "_render_error", "?"))
            return
        p = os.path.join(OUT, f"seed{a.seed}_{name}.png")
        with open(p, "wb") as f:
            f.write(png)
        saved.append(p)

    snap("overview", "overview")
    snap("start")
    top = m["routes"]["short"][0]
    ep.drive_to(top[0], top[1], 3.0, 30.0)
    snap("short_ramp_top")
    ep.drive_to(m["goal"]["x"], m["goal"]["y"], 2.0, 3.0)   # stop mid-descent
    snap("on_short_ramp")
    ep.drive_to(m["goal"]["x"], m["goal"]["y"], 2.0, 30.0)
    snap("at_goal")
    snap("at_goal_overview", "overview")
    print("\n".join(saved))
    print("mode was", ep.scenario.hidden.mode, "| finish:", ep.finish())


if __name__ == "__main__":
    main()
