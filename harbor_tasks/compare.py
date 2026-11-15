"""Paired comparison of two policies on the same evaluation tasks.

    .venv/bin/python -m harbor_tasks.compare 'jobs/eval-qwen-base-*' 'jobs/eval-qwen-tuned-*' [names...]

Pairs trials by task (mean over attempts when a task has several), then reports per
environment: mean reward of each policy, the mean paired difference with a 95% bootstrap
confidence interval over tasks, and delivery discordances with an exact McNemar p-value.
Infrastructure failures are left out exactly as in `results.py`.
"""
from __future__ import annotations

import glob
import json
import random
import statistics as st
import sys
from math import comb
from pathlib import Path

from .results import EVAL_SET, load_trials

BOOTSTRAP_SAMPLES = 10000


def per_task(pattern: str, env_of: dict[str, str]) -> dict[str, tuple[float, bool]]:
    """Task -> (mean reward, delivered in a majority of attempts)."""
    trials = load_trials([Path(p) for p in sorted(glob.glob(pattern))], env_of)
    by_task: dict[str, list] = {}
    for trial in trials:
        by_task.setdefault(trial.task, []).append(trial)
    return {task: (st.mean(t.reward for t in ts), sum(t.delivered for t in ts) * 2 > len(ts))
            for task, ts in by_task.items()}


def bootstrap_interval(differences: list[float], seed: int = 0) -> tuple[float, float]:
    generator = random.Random(seed)
    means = sorted(st.mean(generator.choices(differences, k=len(differences)))
                   for _ in range(BOOTSTRAP_SAMPLES))
    return means[int(0.025 * BOOTSTRAP_SAMPLES)], means[int(0.975 * BOOTSTRAP_SAMPLES) - 1]


def mcnemar_exact(only_first: int, only_second: int) -> float:
    """Two-sided exact binomial test on the discordant pairs."""
    n = only_first + only_second
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(only_first, only_second) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def main(argv: list[str]):
    first_pattern, second_pattern = argv[0], argv[1]
    first_name, second_name = (argv[2], argv[3]) if len(argv) >= 4 else ("first", "second")
    env_of = {t["task"]: t["env"] for t in json.loads(EVAL_SET.read_text())}
    first, second = per_task(first_pattern, env_of), per_task(second_pattern, env_of)
    shared = sorted(set(first) & set(second))
    print(f"{len(shared)} tasks scored by both ({len(first)} {first_name}, {len(second)} {second_name})\n")
    print(f"| Env | Tasks | {first_name} | {second_name} | Difference [95% CI] | "
          f"Delivered only by {first_name} / only by {second_name} | McNemar p |")
    print("|---|---|---|---|---|---|---|")
    for env in ("rover", "winch", "all"):
        tasks = [t for t in shared if env == "all" or env_of[t] == env]
        if not tasks:
            continue
        differences = [second[t][0] - first[t][0] for t in tasks]
        low, high = bootstrap_interval(differences)
        only_first = sum(first[t][1] and not second[t][1] for t in tasks)
        only_second = sum(second[t][1] and not first[t][1] for t in tasks)
        print(f"| {env} | {len(tasks)} | {st.mean(first[t][0] for t in tasks):.3f} | "
              f"{st.mean(second[t][0] for t in tasks):.3f} | {st.mean(differences):+.3f} "
              f"[{low:+.3f}, {high:+.3f}] | {only_first} / {only_second} | "
              f"{mcnemar_exact(only_first, only_second):.3f} |")


if __name__ == "__main__":
    main(sys.argv[1:])
