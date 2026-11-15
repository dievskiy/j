"""Evaluate all scripted policies through the agent tool interface.

    python -m rover_env.evaluate                 # 70 seeds, difficulty 0.5
    python -m rover_env.evaluate --seeds 30 --difficulty 0.5 --workers 16
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from . import fork, policies, policies_fork, policies_serpentine, serpentine, world
from .env import Episode
from .policies import ToolProxy

# per course: (policies, policies that diagnose, all modes, training modes)
COURSES = {
    "ramp": (policies.POLICIES, ("reference", "probe_lookup_table"), world.MODES, world.TRAIN_MODES),
    "serpentine": (policies_serpentine.POLICIES, policies_serpentine.DIAGNOSING,
                   serpentine.MODES, serpentine.TRAIN_MODES),
}
for _name in fork.WORLDS:
    COURSES[_name] = (policies_fork.POLICIES, policies_fork.DIAGNOSING,
                      fork.modes(_name), fork.modes(_name))


def run_one(args):
    policy, seed, difficulty, course = args
    ep = Episode(seed, difficulty, course)
    err = None
    try:
        COURSES[course][0][policy](ToolProxy(ep))
    except Exception as e:  # a crashing policy scores whatever the env says (0 if no finish)
        err = repr(e)
    o = ep.outcome()
    o.update(policy=policy, seed=seed, error=err)
    return o


def fmt_table(rows, modes):
    head = ["policy", "mean", "deliv", "train", "heldout"] + [m.replace("+", "+") for m in modes]
    w = [20, 6, 6, 6, 7] + [max(9, len(m)) for m in modes]
    line = "  ".join(h.ljust(x) for h, x in zip(head, w))
    out = [line, "-" * len(line)]
    for r in rows:
        out.append("  ".join(str(c).ljust(x) for c, x in zip(r, w)))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=70)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--difficulty", type=float, default=0.5)
    ap.add_argument("--workers", type=int, default=min(32, os.cpu_count() or 4))
    ap.add_argument("--course", default="ramp", choices=sorted(COURSES))
    ap.add_argument("--policies", default=None, help="comma-separated; default: all for the course")
    ap.add_argument("--json", default=None, help="write per-episode results here")
    a = ap.parse_args(argv)
    course_policies, diagnosing, MODES, TRAIN_MODES = COURSES[a.course]
    seeds = list(range(a.start, a.start + a.seeds))
    pols = a.policies.split(",") if a.policies else list(course_policies)
    t0 = time.time()
    tasks = [(p, s, a.difficulty, a.course) for p in pols for s in seeds]
    # second, independent run of the reference on the same seeds (reproducibility)
    tasks += [("reference", s, a.difficulty, a.course) for s in seeds]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(run_one, tasks, chunksize=2))
    main_res, rerun = res[:len(seeds) * len(pols)], res[len(seeds) * len(pols):]

    modes = [m for m in MODES if any(r["mode"] == m for r in main_res)]
    rows = []
    for p in pols:
        rs = [r for r in main_res if r["policy"] == p]
        mean = st.mean(r["reward"] for r in rs)
        deliv = st.mean(1.0 if r["reward"] > 0 else 0.0 for r in rs)
        tr = [r["reward"] for r in rs if r["mode"] in TRAIN_MODES]
        ho = [r["reward"] for r in rs if r["mode"] not in TRAIN_MODES]
        row = [p, f"{mean:.3f}", f"{deliv:.2f}", f"{st.mean(tr):.3f}" if tr else "-",
               f"{st.mean(ho):.3f}" if ho else "-"]
        for m in modes:
            mr = [r for r in rs if r["mode"] == m]
            row.append(f"{st.mean(x['reward'] for x in mr):.3f}/{st.mean(1.0 if x['reward'] > 0 else 0.0 for x in mr):.1f}")
        rows.append(row)
    counts = {m: sum(1 for s in seeds if main_res[seeds.index(s)]["mode"] == m) for m in modes}
    print(f"course={a.course}, seeds {seeds[0]}..{seeds[-1]} (n={len(seeds)}), difficulty={a.difficulty}, "
          f"wall {time.time() - t0:.0f}s")
    print("per-mode cells: mean_reward/delivery_rate;  episodes per mode: " +
          ", ".join(f"{m}={c}" for m, c in counts.items()))
    print(fmt_table(rows, modes))

    ref1 = {r["seed"]: r["reward"] for r in main_res if r["policy"] == "reference"}
    ref2 = {r["seed"]: r["reward"] for r in rerun}
    if ref1:
        diffs = [abs(ref1[s] - ref2[s]) for s in seeds]
        print(f"\nreference rerun: run1 mean={st.mean(ref1.values()):.4f}  "
              f"run2 mean={st.mean(ref2.values()):.4f}  max |per-seed diff|={max(diffs):.2e}  "
              f"seeds differing={sum(d > 0 for d in diffs)}")
        safe = {r["seed"]: r["reward"] for r in main_res if r["policy"] == "always_safe_route"}
        if safe:
            print(f"reference - always_safe_route = {st.mean(ref1.values()) - st.mean(safe.values()):+.3f}")
        best_trivial = max((st.mean(r["reward"] for r in main_res if r["policy"] == p), p)
                           for p in pols if p not in diagnosing)
        print(f"best non-diagnosing baseline: {best_trivial[1]} = {best_trivial[0]:.3f} "
              f"(gap to reference {st.mean(ref1.values()) - best_trivial[0]:+.3f})")
    errs = [r for r in main_res if r["error"]]
    if errs:
        print(f"\npolicy exceptions: {len(errs)}; first: {errs[0]['policy']} seed {errs[0]['seed']}: {errs[0]['error']}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(main_res + [dict(r, policy="reference_rerun") for r in rerun], f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
