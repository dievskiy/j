"""Headline numbers for the results slide, reusing harbor_tasks/results.py without writing
results/eval_summary.json.

    .venv/bin/python presentation/scripts/headline.py \
        reference=jobs/eval-reference-20261114-232444 do-nothing=jobs/eval-do-nothing-20261114-234841 \
        deepseek=jobs/eval-deepseek-20261115-005638 inkling=jobs/eval-inkling-20261115-005608

Each argument is policy=job_dir[,job_dir...] (globs allowed). Add the run-3 job dirs to the
model's list when they are copied over. Also prints the stop-early baselines from
results/stop_early.json.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from harbor_tasks import results  # noqa: E402


def main(argv: list[str]):
    tasks = json.loads(results.EVAL_SET.read_text())
    env_of = {t["task"]: t["env"] for t in tasks}
    print("| Policy | Env | Trials | Mean reward ± spread of run means | Run means | Delivery |")
    print("|---|---|---|---|---|---|")
    for argument in argv:
        policy, patterns = argument.split("=", 1)
        jobs = [Path(p) for pattern in patterns.split(",") for p in sorted(glob.glob(pattern))]
        trials = results.load_trials(jobs, env_of)
        for env in ("rover", "winch", "all"):
            subset = [t for t in trials if env == "all" or t.env == env]
            if not subset:
                continue
            s = results.summarise(subset)
            runs = ", ".join(f"{m:.3f}" for m in s["run_means"])
            print(f"| {policy} | {env} | {s['trials']} | {s['mean']:.3f} ± {s['run_spread']:.3f} | {runs} | {s['delivery']:.0%} |")
    if results.infrastructure_failures:
        print(f"\nLeft out as infrastructure failures: {dict(results.infrastructure_failures)}")
    stop_early = Path("results/stop_early.json")
    if stop_early.exists():
        rows = json.loads(stop_early.read_text())
        for key in ("finish_at_once", "reference_cut_short"):
            nonzero = sum(1 for r in rows if r[key] > 0)
            print(f"\nStop-early `{key}`: {nonzero}/{len(rows)} tasks nonzero, max {max(r[key] for r in rows):.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
