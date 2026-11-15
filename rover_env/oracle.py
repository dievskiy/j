"""Hindsight analysis: for each seed, try a fixed menu of open-loop plans and report
which plan is best per hidden mode. Answers "does the best route/speed depend on the
hidden mode?" (This is analysis only; the menu runs through the normal tools.)

    python -m rover_env.oracle --seeds 70
"""
from __future__ import annotations

import argparse
import collections
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor

from . import policies as P
from .env import Episode
from .world import MODES

MENU = [("short", v, None) for v in (1.0, 1.5, 2.0, 2.5, 3.0)] + \
       [("long", v, leg) for v in (2.0, 2.5, 3.0) for leg in (12.0, 100.0)]


def run_plan(args):
    seed, (route, v, leg), difficulty = args
    ep = Episode(seed, difficulty)
    env = P.ToolProxy(ep)
    m = env.observe()["map"]
    goal = (m["goal"]["x"], m["goal"]["y"])
    if route == "short":
        P._follow(env, m["routes"]["short"], v)
        P._settle_and_finish(env, goal, m["goal"]["radius"])
    else:
        wps = m["routes"]["long"]
        pts = P._subdivide((0.0, 0.0), wps[:-1] + [(goal[0], goal[1] - 4.0)], leg)
        r = P._follow(env, pts, v)
        if r["termination"] in ("arrived", "overshot_target"):
            env.drive_to(goal[0], goal[1], 1.0, 30.0)
        P._settle_and_finish(env, goal, m["goal"]["radius"])
    return seed, (route, v, leg), ep.reward(), ep.scenario.hidden.mode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=70)
    ap.add_argument("--difficulty", type=float, default=0.5)
    ap.add_argument("--workers", type=int, default=min(32, os.cpu_count() or 4))
    a = ap.parse_args(argv)
    tasks = [(s, p, a.difficulty) for s in range(a.seeds) for p in MENU]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(run_plan, tasks, chunksize=4))
    by_seed = collections.defaultdict(list)
    for s, p, r, mode in res:
        by_seed[s].append((r, p, mode))
    per_mode = collections.defaultdict(list)
    for s, lst in by_seed.items():
        best = max(lst, key=lambda x: x[0])
        per_mode[best[2]].append(best)
    print("best open-loop plan in hindsight, per hidden mode (route counts; mean best reward)")
    allbest = []
    for m in MODES:
        b = per_mode.get(m, [])
        if not b:
            continue
        cnt = collections.Counter(f"{p[0]}@{p[1]}" + (f"/leg{int(p[2])}" if p[2] and p[2] < 100 else "")
                                  for _, p, _ in b)
        allbest += [x[0] for x in b]
        print(f"  {m:18s} n={len(b):2d}  mean={st.mean(x[0] for x in b):.3f}  "
              f"delivered={st.mean(1.0 if x[0] > 0 else 0.0 for x in b):.2f}  best plans: {dict(cnt.most_common())}")
    print(f"  {'ALL':18s} hindsight-oracle mean={st.mean(allbest):.3f}")
    # best single fixed plan (no diagnosis)
    fixed = collections.defaultdict(list)
    for s, p, r, _ in res:
        fixed[p].append(r)
    bp = max(fixed, key=lambda p: st.mean(fixed[p]))
    print(f"  best single fixed plan from the menu: {bp} mean={st.mean(fixed[bp]):.3f}")


if __name__ == "__main__":
    main()
