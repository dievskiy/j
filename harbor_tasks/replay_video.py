"""Re-render a Harbor trial's rollout video by replaying its tool calls.

    .venv/bin/python harbor_tasks/replay_video.py jobs/<job-name> [more job dirs...]

The simulation is deterministic, so replaying the recorded tool calls on a fresh
Episode reproduces the trial. The replayed outcome is checked against the verifier's
sim_result.json, and the video replaces artifacts/rollout.mp4 in each trial directory.
"""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MUJOCO_GL", "egl")

from rover_env.env import Episode
from rover_env.recorder import Recorder

MOTION_TOOLS = ("drive_to", "brake", "wait", "finish")


def replay(trial_dir: str) -> bool:
    """Replay one trial. Returns True if the replay matches the recorded outcome."""
    expected = json.load(open(os.path.join(trial_dir, "verifier", "sim_result.json")))
    trajectory = json.load(open(os.path.join(trial_dir, "agent", "trajectory.json")))
    video = os.path.join(trial_dir, "artifacts", "rollout.mp4")
    os.makedirs(os.path.dirname(video), exist_ok=True)
    for stale in (video + ".done", video + ".stop"):
        if os.path.exists(stale):
            os.remove(stale)

    episode = Episode(expected["seed"], expected["difficulty"], expected.get("course", "ramp"))
    Recorder(episode, video)
    for step in trajectory.get("steps", []):
        for call in step.get("tool_calls") or []:
            tool = call["function_name"].removeprefix("rover_")
            if tool in MOTION_TOOLS:
                getattr(episode, tool)(**(call.get("arguments") or {}))
    open(video + ".stop", "w").close()
    while not os.path.exists(video + ".done"):
        time.sleep(0.2)
    os.remove(video + ".done")
    os.remove(video + ".stop")

    outcome = episode.outcome()
    return (abs(episode.reward() - expected["reward"]) < 1e-9
            and outcome["t"] == expected["outcome"]["t"])


if __name__ == "__main__":
    for job_dir in sys.argv[1:]:
        for trial_dir in sorted(d for d in glob.glob(os.path.join(job_dir, "*")) if os.path.isdir(d)):
            if not os.path.exists(os.path.join(trial_dir, "verifier", "sim_result.json")):
                continue
            print(f"{trial_dir}: replay matches recorded outcome = {replay(trial_dir)}")
