"""Stop-early baselines on the frozen evaluation set, run directly against the simulator.

    .venv/bin/python -m harbor_tasks.baselines

`finish_at_once`: call finish before doing anything. `reference_cut_short`: play the
reference, but call finish after half of its actions. Both should earn ~0.
"""
from __future__ import annotations

import json
import statistics as st
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from rover_env.env import Episode as RoverEpisode
from rover_env.evaluate import COURSES
from winch_env import policies as winch_policies
from winch_env.env import Episode as WinchEpisode

from .eval_set import DIFFICULTY, HERE
from .make_tasks import WINCH_COURSE


class StopEarly(Exception):
    pass


class CutShort:
    """Tool surface that calls finish once `limit` actions have been taken."""

    def __init__(self, episode, limit: int):
        self._episode, self._limit, self.actions = episode, limit, 0

    def __getattr__(self, name):
        tool = getattr(self._episode, name)
        if name in ("observe", "finish"):
            return tool

        def act(*args, **kwargs):
            if self.actions >= self._limit:
                self._episode.finish()
                raise StopEarly
            self.actions += 1
            return tool(*args, **kwargs)
        return act


def episode_and_reference(task: dict):
    if task["course"] == WINCH_COURSE:
        return (WinchEpisode(task["seed"], DIFFICULTY, task["variation"] or None),
                winch_policies.POLICIES["reference"])
    return (RoverEpisode(task["seed"], DIFFICULTY, task["course"]),
            COURSES[task["course"]][0]["reference"])


def run(task: dict) -> dict:
    episode, reference = episode_and_reference(task)
    counter = CutShort(episode, 10**6)
    reference(counter)
    full_actions = counter.actions

    episode, _ = episode_and_reference(task)
    episode.finish()
    at_once = episode.reward()

    episode, reference = episode_and_reference(task)
    try:
        reference(CutShort(episode, full_actions // 2))
    except StopEarly:
        pass
    return {"task": task["task"], "env": task["env"], "finish_at_once": at_once,
            "reference_cut_short": episode.reward(), "reference_actions": full_actions}


def main():
    tasks = json.loads((HERE / "eval_set.json").read_text())
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(run, tasks))
    Path("results").mkdir(exist_ok=True)
    Path("results/stop_early.json").write_text(json.dumps(rows, indent=1) + "\n")
    for policy in ("finish_at_once", "reference_cut_short"):
        rewards = [r[policy] for r in rows]
        print(f"{policy}: mean {st.mean(rewards):.3f}, max {max(rewards):.3f}, "
              f"nonzero {sum(r > 0 for r in rewards)}/{len(rewards)}")


if __name__ == "__main__":
    main()
