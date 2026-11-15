"""Evaluate the scripted winch policies through the agent tool interface.

    python -m winch_env.evaluate --seeds 48
"""
from __future__ import annotations

import argparse
import os
import statistics as st
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from .env import Episode
from .policies import DIAGNOSING, POLICIES, ToolProxy
from .world import VARIATIONS


def run_one(task):
    policy, seed, difficulty, *variation = task
    episode = Episode(seed, difficulty, variation[0] if variation else None)
    error = None
    try:
        POLICIES[policy](ToolProxy(episode))
    except Exception as exc:      # a crashing policy scores whatever the env says
        error = repr(exc)
    return dict(episode.outcome(), policy=policy, seed=seed, error=error)


def validate(variation_names, seeds, difficulty, workers):
    names = ("reference", "nearest_careful", "middle_careful", "farthest_careful",
             "nearest_fast", "first_that_lifts", "do_nothing", "immediate_finish",
             "wait_spam", "random_actions", "invalid_inputs", "drop_on_goal")
    tasks = [(name, seed, difficulty, variation)
             for variation in variation_names for name in names for seed in seeds]
    with ProcessPoolExecutor(workers) as pool:
        rows = list(pool.map(run_one, tasks, chunksize=3))
    print("variation        reference  delivery  best non-test  gap    integrity  status")
    for variation in variation_names:
        data = [row for task, row in zip(tasks, rows) if task[3] == variation]
        ref = [r for r in data if r["policy"] == "reference"]
        mean = st.mean(r["reward"] for r in ref)
        delivery = st.mean(r["delivered"] for r in ref)
        best = max((st.mean(r["reward"] for r in data if r["policy"] == name), name)
                   for name in names[1:6])
        integrity = max(r["reward"] for r in data if r["policy"] in names[6:])
        status = "PASS" if delivery >= .95 and mean - best[0] >= .2 and integrity == 0 else "FAIL"
        print(f"{variation:16s} {mean:8.3f} {delivery:8.2%}  {best[1]:16s} "
              f"{mean - best[0]:5.3f}  {integrity:9.3f}  {status}")
        errors = [r for r in data if r["error"]]
        if errors:
            print(f"  exceptions: {errors[:2]}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=48)
    parser.add_argument("--variation", default=None,
                        help="variation name; 'all' or a comma-separated list prints the validation table")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--difficulty", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=min(32, os.cpu_count() or 4))
    parser.add_argument("--policies", default=",".join(POLICIES))
    args = parser.parse_args(argv)
    seeds = range(args.start, args.start + args.seeds)
    if args.variation == "all" or "," in (args.variation or ""):
        chosen = list(VARIATIONS) if args.variation == "all" else args.variation.split(",")
        unknown = [name for name in chosen if name not in VARIATIONS]
        if unknown:
            parser.error(f"unknown variation: {', '.join(unknown)}")
        validate(chosen, seeds, args.difficulty, args.workers)
        return
    if args.variation is not None and args.variation not in VARIATIONS:
        parser.error(f"unknown variation: {args.variation}")
    names = args.policies.split(",")
    started = time.time()
    tasks = [(p, s, args.difficulty, args.variation) for p in names for s in seeds]
    tasks += [("reference", s, args.difficulty, args.variation) for s in seeds]      # rerun for reproducibility
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(run_one, tasks, chunksize=2))
    main_results, rerun = results[:len(names) * len(seeds)], results[len(names) * len(seeds):]

    print(f"winch yard, seeds {seeds[0]}..{seeds[-1]} (n={len(seeds)}), "
          f"difficulty={args.difficulty}, wall {time.time() - started:.0f}s")
    print(f"{'policy':20s} {'mean':>6s} {'deliv':>6s}  most common outcomes")
    means = {}
    for name in names:
        rows = [r for r in main_results if r["policy"] == name]
        means[name] = st.mean(r["reward"] for r in rows)
        delivered = st.mean(1.0 if r["reward"] > 0 else 0.0 for r in rows)
        reasons = Counter(r["reason"] for r in rows).most_common(3)
        print(f"{name:20s} {means[name]:6.3f} {delivered:6.2f}  "
              + ", ".join(f"{reason} x{count}" for reason, count in reasons))
    if "reference" in means:
        first = {r["seed"]: r["reward"] for r in main_results if r["policy"] == "reference"}
        second = {r["seed"]: r["reward"] for r in rerun}
        print(f"\nreference rerun: max |per-seed diff| = "
              f"{max(abs(first[s] - second[s]) for s in seeds):.2e}")
        best = max((value, name) for name, value in means.items() if name not in DIAGNOSING)
        print(f"best non-weighing plan: {best[1]} = {best[0]:.3f} "
              f"(gap to reference {means['reference'] - best[0]:+.3f})")
    errors = [r for r in main_results if r["error"]]
    if errors:
        print(f"policy exceptions: {len(errors)}; first: {errors[0]['policy']} "
              f"seed {errors[0]['seed']}: {errors[0]['error']}")


if __name__ == "__main__":
    main()
