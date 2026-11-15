"""Freeze the task splits: regime-balanced seeds, evaluation from 90000 up, training
(Qwen rollouts only) from 50000 up. The two ranges never overlap.

    .venv/bin/python -m harbor_tasks.eval_set                   # writes harbor_tasks/eval_set.json
    .venv/bin/python -m harbor_tasks.eval_set --make            # also generates the Harbor tasks
    .venv/bin/python -m harbor_tasks.eval_set --split train --make

A blind guess wins some regimes by luck, so each task's seeds cycle through its hidden
regimes instead of repeating one seed.
"""
from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import dataclass
from pathlib import Path

from rover_env import fork
from rover_env.env import Episode as RoverEpisode
from winch_env.env import Episode as WinchEpisode
from winch_env.world import VARIATIONS

from .make_tasks import WINCH_COURSE, make, task_name

ROVER_COURSES = ["serpentine", *fork.WORLDS]      # ramp left out: its gap is weak
WINCH_VARIATIONS = ["", *VARIATIONS]              # "" is the base yard
DIFFICULTY = 0.5
HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Split:
    first_seed: int
    rover_seeds_per_course: int
    winch_seeds_per_task: int


SPLITS = {"eval": Split(90000, 4, 3), "train": Split(50000, 2, 2)}


def rover_regime(course: str, seed: int) -> str:
    return RoverEpisode(seed, DIFFICULTY, course).outcome()["mode"]


def winch_regime(variation: str, seed: int) -> str:
    """The cable and trap part of the mode; the crate ordering is left out, since every
    policy that weighs crates handles any ordering the same way."""
    mode = WinchEpisode(seed, DIFFICULTY, variation or None).outcome()["mode"]
    return mode.split("_", 1)[1] if "_" in mode else mode


def balanced_seeds(regime_of, count: int, first_seed: int) -> list[dict]:
    """Take seeds in order, cycling through the regimes."""
    by_regime: dict[str, list[int]] = {}
    for seed in itertools.islice(itertools.count(first_seed), 400):
        by_regime.setdefault(regime_of(seed), []).append(seed)
    picked: list[dict] = []
    for round_robin in itertools.zip_longest(*by_regime.values()):
        picked += [{"seed": s, "regime": regime_of(s)} for s in round_robin if s is not None]
        if len(picked) >= count:
            break
    return picked[:count]


def build(split: Split) -> list[dict]:
    tasks = []
    for course in ROVER_COURSES:
        for item in balanced_seeds(lambda s: rover_regime(course, s), split.rover_seeds_per_course,
                                   split.first_seed):
            tasks.append({"env": "rover", "course": course, "variation": "", **item})
    for variation in WINCH_VARIATIONS:
        for item in balanced_seeds(lambda s: winch_regime(variation, s), split.winch_seeds_per_task,
                                   split.first_seed):
            tasks.append({"env": "winch", "course": WINCH_COURSE, "variation": variation, **item})
    for task in tasks:
        task["task"] = task_name(task["seed"], task["course"], task["variation"])
    return tasks


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=SPLITS, default="eval")
    parser.add_argument("--make", action="store_true", help="generate the Harbor task directories")
    args = parser.parse_args(argv)
    tasks = build(SPLITS[args.split])
    out = HERE / f"{args.split}_set.json"
    out.write_text(json.dumps(tasks, indent=1) + "\n")
    print(f"{len(tasks)} tasks -> {out}")
    if args.make:
        dataset = HERE / f"{args.split}_tasks"      # symlinks Harbor runs as one dataset
        dataset.mkdir(exist_ok=True)
        for task in tasks:
            directory = make(task["seed"], DIFFICULTY, task["course"], task["variation"], video=False)
            link = dataset / task["task"]
            if not link.exists():
                link.symlink_to(directory)


if __name__ == "__main__":
    main()
