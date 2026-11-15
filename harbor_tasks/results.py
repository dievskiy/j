"""Summarise Harbor evaluation jobs into one results table.

    .venv/bin/python -m harbor_tasks.results reference=jobs/eval-reference-* inkling=jobs/eval-inkling-* ...

Each argument is policy=job_dir[,job_dir...]. A trial without a verified reward (agent
crash, agent timeout, no finish) counts as 0, so unfinished episodes stay in the
denominator. Trials that failed before the agent acted (Docker errors, agent install
timeouts, trials we cancelled) are infrastructure failures and are left out; they are
reported so a rerun can replace them.
Per policy and environment: mean reward over all trials, the spread of the per-run means
(run = attempt index across the 75 tasks), and the delivery rate.
"""
from __future__ import annotations

import collections
import glob
import json
import statistics as st
import sys
from dataclasses import dataclass
from pathlib import Path

EVAL_SET = Path(__file__).resolve().parent / "eval_set.json"
INFRASTRUCTURE_ERRORS = {"RuntimeError", "CancelledError", "AgentSetupTimeoutError",
                         "EnvironmentStartTimeoutError", "ApiRateLimitError"}


@dataclass(frozen=True)
class Trial:
    task: str
    env: str
    attempt: int
    reward: float
    delivered: bool


infrastructure_failures: collections.Counter = collections.Counter()


def load_trials(job_dirs: list[Path], env_of: dict[str, str]) -> list[Trial]:
    trials, seen = [], collections.Counter()
    for job in job_dirs:
        for trial_dir in sorted(p for p in job.iterdir() if (p / "result.json").exists() and p.is_dir()):
            # Harbor truncates long names in the directory; the config keeps the task path.
            task = Path(json.loads((trial_dir / "config.json").read_text())["task"]["path"]).name
            if task not in env_of:
                continue
            error = (json.loads((trial_dir / "result.json").read_text()).get("exception_info") or {})
            if error.get("exception_type") in INFRASTRUCTURE_ERRORS:
                infrastructure_failures[job.name] += 1
                continue
            reward_file = trial_dir / "verifier" / "reward.txt"
            reward = float(reward_file.read_text().strip() or 0) if reward_file.exists() else 0.0
            sim = trial_dir / "verifier" / "sim_result.json"
            delivered = bool(json.loads(sim.read_text())["outcome"].get("delivered")) if sim.exists() else False
            trials.append(Trial(task, env_of[task], seen[task], reward, delivered))
            seen[task] += 1
    return trials


def summarise(trials: list[Trial]) -> dict:
    by_attempt = collections.defaultdict(list)
    for trial in trials:
        by_attempt[trial.attempt].append(trial.reward)
    run_means = [st.mean(v) for v in by_attempt.values()]
    return {"trials": len(trials), "tasks": len({t.task for t in trials}),
            "mean": st.mean(t.reward for t in trials),
            "run_means": run_means,
            "run_spread": st.stdev(run_means) if len(run_means) > 1 else 0.0,
            "delivery": sum(t.delivered for t in trials) / len(trials)}


def main(argv: list[str]):
    tasks = json.loads(EVAL_SET.read_text())
    env_of = {t["task"]: t["env"] for t in tasks}
    rows = {}
    for argument in argv:
        policy, patterns = argument.split("=", 1)
        jobs = [Path(p) for pattern in patterns.split(",") for p in sorted(glob.glob(pattern))]
        trials = load_trials(jobs, env_of)
        rows[policy] = {env: summarise([t for t in trials if t.env == env])
                        for env in ("rover", "winch") if any(t.env == env for t in trials)}
        rows[policy]["all"] = summarise(trials)
        rows[policy]["per_task"] = {task: st.mean(t.reward for t in trials if t.task == task)
                                    for task in sorted({t.task for t in trials})}
    print("| Policy | Env | Trials | Mean reward | Run means | Delivery |")
    print("|---|---|---|---|---|---|")
    for policy, by_env in rows.items():
        for env in ("rover", "winch", "all"):
            if env in by_env:
                s = by_env[env]
                runs = ", ".join(f"{m:.3f}" for m in s["run_means"])
                print(f"| {policy} | {env} | {s['trials']} | {s['mean']:.3f} ± {s['run_spread']:.3f} "
                      f"| {runs} | {s['delivery']:.0%} |")
    if infrastructure_failures:
        print(f"\nLeft out as infrastructure failures: {dict(infrastructure_failures)}")
    Path("results").mkdir(exist_ok=True)
    Path("results/eval_summary.json").write_text(json.dumps(rows, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
