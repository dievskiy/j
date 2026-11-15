"""Failure analysis of Harbor evaluation trials for the demo video.

    python3 presentation/scripts/analyze_trials.py \
        inkling=jobs/eval-inkling-20261115-005608 deepseek=jobs/eval-deepseek-20261115-005638 \
        --reference jobs/eval-reference-20261114-232444 > presentation/analysis.md

Each positional argument is model=job_dir[,job_dir...]. Only completed trials (those with
result.json and a finished_at time) are used; trials whose exception is an
infrastructure error (rate limit, cancelled, setup timeout) are left out, as in
harbor_tasks/results.py. A trial without verifier/sim_result.json never had its episode
adjudicated (no finish, agent timeout) and scores 0.

Testing heuristics (applied to the agent's own tool-call arguments and its get_map):
  rover  "commit" = the first drive_to whose target lies outside the start pad.
         "tested" = before that commit, a drive_to whose straight path from the previous
         target crosses a sample strip (rectangle grown by 0.5 m) or passes within 1.5 m
         of the sample crate, or whose target lies inside the lookout circle (+0.5 m).
  winch  "commit" = the first move_trolley issued while a crate is attached.
         "tested" = before that commit, at least one winch call with stop_tension set
         (a tension-limited take-up); "slow test" additionally needs speed_limit <= 0.1 m/s.
"""
from __future__ import annotations

import collections
import json
import re
import statistics as st
import sys
from dataclasses import dataclass, field
from pathlib import Path

INFRASTRUCTURE_ERRORS = {"RuntimeError", "CancelledError", "AgentSetupTimeoutError",
                         "EnvironmentStartTimeoutError", "ApiRateLimitError"}
ENV_TOOL_PREFIXES = ("rover_", "hoist_")
LANES_AT_FIRST_FORK = {"fork_mud_ice_wind": 3, "fork_crate_barrier_mud": 3}   # every other course has 2
CRASHES = {"chassis_collision", "rollover", "left_drivable_surface", "cargo_dropped"}
SHELL_TOOLS = {"bash", "read", "glob", "grep", "webfetch", "task", "list_mcp_resources",
               "list_mcp_resource_templates"}


@dataclass
class Trial:
    model: str
    path: Path
    task: str
    env: str
    group: str            # rover course or winch variation
    regime: str
    reward: float
    delivered: bool
    reason: str
    sim_time: float | None
    env_calls: int
    shell_calls: int
    shell_before_end: int
    tested: bool | None
    slow_tested: bool | None = None
    lane_choice: str | None = None        # rover: "open", "closed" or None (never entered a lane)
    off_map_commands: int = 0             # rover: drive_to calls whose straight path leaves the drivable surfaces
    last_command_off_map: bool = False    # rover: the last drive_to before the episode ended did
    pad_time_share: float | None = None   # rover: share of the time budget spent before leaving the start pad
    end_pose: tuple | None = None         # rover: (x, y) from the first observe after the episode ended, if any
    notes: list[str] = field(default_factory=list)


def tool_calls(trajectory: dict):
    """Yield (step, call, result_text) for every tool call in order."""
    for step in trajectory["steps"]:
        results = (step.get("observation") or {}).get("results") or []
        for index, call in enumerate(step.get("tool_calls") or []):
            text = results[index]["content"] if index < len(results) else ""
            yield step, call, text


def short_name(call: dict) -> str:
    name = call["function_name"]
    for prefix in ENV_TOOL_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def find_map(trajectory: dict) -> dict | None:
    for _, call, text in tool_calls(trajectory):
        if short_name(call) == "get_map":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            game_map = dict(data.get("map", data))
            game_map.setdefault("budgets", data.get("budgets"))
            return game_map
    return None


# ------------------------------------------------------------------ rover heuristic
def _segment_points(a, b, n=40):
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


def _in_rect(p, rect, grow=0.5):
    return rect["x"][0] - grow <= p[0] <= rect["x"][1] + grow and rect["y"][0] - grow <= p[1] <= rect["y"][1] + grow


def rover_tested(trajectory: dict, game_map: dict) -> bool | None:
    pad = next(s for s in game_map["drivable_surfaces"] if s["name"] == "start_pad")
    strips = [p for p in game_map.get("surface_patches", []) if "sample" in p["name"]]
    lookout = game_map.get("lookout")
    crates = []
    for fork in game_map.get("forks", []):
        for lane in fork["lanes"]:
            test = lane.get("test_on_start_pad") or {}
            if test.get("kind") == "sample_crate":
                crates.append((test["x"], test["y"]))
    position = (game_map["start"]["x"], game_map["start"]["y"])
    for _, call, _ in tool_calls(trajectory):
        if short_name(call) != "drive_to":
            continue
        args = call["arguments"]
        try:
            target = (float(args["x"]), float(args["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not _in_rect(target, pad, grow=0.0):
            return False                      # committed before any test
        path = _segment_points(position, target)
        if any(_in_rect(p, strip) for strip in strips for p in path):
            return True
        if any(min((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 for p in path) <= 1.5 ** 2 for c in crates):
            return True
        if lookout and (target[0] - lookout["x"]) ** 2 + (target[1] - lookout["y"]) ** 2 <= (lookout["radius"] + 0.5) ** 2:
            return True
        position = target
    return None                                # never left the pad


def _on_surface(p, game_map) -> bool:
    return any(_in_rect(p, surface, grow=0.0) for surface in game_map["drivable_surfaces"])


def _distance_to_polyline(p, points) -> float:
    best = float("inf")
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy or 1e-9
        u = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
        best = min(best, ((p[0] - a[0] - u * dx) ** 2 + (p[1] - a[1] - u * dy) ** 2) ** 0.5)
    return best


def _lane_of(target, game_map) -> str | None:
    """The hazard of the first-fork lane a target lies in, or None if it is not in one."""
    if "forks" in game_map:
        fork = game_map["forks"][0]
        if not fork["fork_node"][0] + 1.0 < target[0] < fork["merge_node"][0] - 1.0:
            return None
        lane = min(fork["lanes"], key=lambda l: _distance_to_polyline(target, l["waypoints"]))
        return lane["hazard"]
    routes = game_map.get("routes")                      # serpentine
    if routes and 18.3 < target[0] < 35.6:
        return "shortcut" if abs(target[1]) < 1.8 else "serpentine"
    return None


def rover_pad_time_share(trajectory: dict, game_map: dict) -> float | None:
    """Simulated time already used when the first drive_to off the start pad is issued,
    as a share of the time budget."""
    pad = next(s for s in game_map["drivable_surfaces"] if s["name"] == "start_pad")
    budget = (game_map.get("budgets") or {}).get("time_s")
    now = 0.0
    for _, call, text in tool_calls(trajectory):
        if short_name(call) == "drive_to":
            try:
                target = (float(call["arguments"]["x"]), float(call["arguments"]["y"]))
            except (KeyError, TypeError, ValueError):
                target = None
            if target and not _in_rect(target, pad, grow=0.0):
                return now / budget if budget else None
        try:
            now = float(json.loads(text).get("t", now))
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            pass
    return None


def rover_end_pose(trajectory: dict) -> tuple | None:
    for _, call, text in tool_calls(trajectory):
        if short_name(call) != "observe":
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if (data.get("episode") or {}).get("ended"):
            return (data["pose"]["x"], data["pose"]["y"])
    return None


def crash_zone(pose, game_map) -> str:
    """Where a crash happened: leaving the start pad onto the first road, in a lane, or near the goal."""
    if pose is None:
        return "unknown"
    fork_x = game_map_fork_x(game_map)
    if pose[0] <= fork_x + 1.0:
        return "start pad / road to first fork"
    if pose[0] >= game_map["goal"]["x"] - 8.0:
        return "merge / goal approach"
    return "lanes"


def game_map_fork_x(game_map) -> float:
    if "forks" in game_map:
        return game_map["forks"][0]["fork_node"][0]
    return game_map["nodes"]["P1"][0]


def rover_geometry(trajectory: dict, game_map: dict, regime: str) -> tuple[str | None, int, bool]:
    """Lane choice versus the hidden regime, and drive_to commands whose straight path
    leaves the drivable surfaces (the map says everything outside them is a drop)."""
    open_hazard = regime.split("+")[0].replace("_open", "")
    position = (game_map["start"]["x"], game_map["start"]["y"])
    lane_choice, off_map, last_off = None, 0, False
    for _, call, text in tool_calls(trajectory):
        name = short_name(call)
        if name == "observe":
            try:
                pose = json.loads(text)["pose"]
                position = (pose["x"], pose["y"])
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
            continue
        if name != "drive_to":
            continue
        if "episode_over" in text or "episode_finished" in text:
            break
        try:
            target = (float(call["arguments"]["x"]), float(call["arguments"]["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        last_off = not all(_on_surface(p, game_map) for p in _segment_points(position, target, 80))
        off_map += last_off
        lane = next((l for l in (_lane_of(p, game_map) for p in _segment_points(position, target, 80)) if l), None)
        if lane_choice is None and lane is not None:
            lane_choice = "open" if lane == open_hazard else "closed"
        position = target
    return lane_choice, off_map, last_off


# ------------------------------------------------------------------ winch heuristic
def winch_tested(trajectory: dict) -> tuple[bool | None, bool | None]:
    attached = False
    tested = slow = False
    for _, call, text in tool_calls(trajectory):
        name = short_name(call)
        args = call.get("arguments") or {}
        if name == "attach" and '"attached"' in text:
            attached = True
        elif name == "release":
            attached = False
        elif name == "winch" and attached and args.get("stop_tension") is not None:
            tested = True
            try:
                slow = slow or abs(float(args.get("speed_limit", 1))) <= 0.1
            except (TypeError, ValueError):
                pass
        elif name == "move_trolley" and attached:
            return tested, slow
    return (tested, slow) if (tested or attached) else (None, None)


# ------------------------------------------------------------------ loading
def normalise_reason(reason: str) -> str:
    reason = re.sub(r"hard constraint violated: ", "", reason)
    return re.sub(r"[-+]?\d+(\.\d+)?", "N", reason)


def load(model: str, job_dirs: list[Path], eval_set: dict) -> tuple[list[Trial], collections.Counter]:
    trials, excluded = [], collections.Counter()
    for job in job_dirs:
        for trial_dir in sorted(p for p in job.iterdir() if p.is_dir() and (p / "result.json").exists()):
            result = json.loads((trial_dir / "result.json").read_text())
            if not result.get("finished_at"):
                continue
            error = (result.get("exception_info") or {}).get("exception_type")
            if error in INFRASTRUCTURE_ERRORS:
                excluded[error] += 1
                continue
            task = Path(json.loads((trial_dir / "config.json").read_text())["task"]["path"]).name
            if task not in eval_set:
                continue
            meta = eval_set[task]
            sim_file = trial_dir / "verifier" / "sim_result.json"
            reward_file = trial_dir / "verifier" / "reward.txt"
            reward = float(reward_file.read_text().strip() or 0) if reward_file.exists() else 0.0
            if sim_file.exists():
                outcome = json.loads(sim_file.read_text())["outcome"]
                reason, delivered, sim_time = normalise_reason(outcome["reason"]), bool(outcome.get("delivered")), outcome.get("t")
            else:
                reason, delivered, sim_time = f"never adjudicated ({error or 'agent stopped without finish'})", False, None
            trajectory_file = trial_dir / "agent" / "trajectory.json"
            trajectory = json.loads(trajectory_file.read_text()) if trajectory_file.exists() else {"steps": []}
            names = [short_name(c) for _, c, _ in tool_calls(trajectory)]
            env_calls = sum(1 for _, c, _ in tool_calls(trajectory) if c["function_name"].startswith(ENV_TOOL_PREFIXES))
            ended_at = next((i for i, (_, c, t) in enumerate(tool_calls(trajectory))
                             if short_name(c) == "finish" or "episode_over" in t or "episode_finished" in t
                             or "cable_snapped" in t), len(names))
            shell_before_end = sum(1 for n in names[:ended_at] if n in SHELL_TOOLS)
            shell_calls = sum(1 for n in names if n in SHELL_TOOLS)
            group = meta["course"] if meta["env"] == "rover" else (meta["variation"] or "base")
            trial = Trial(model, trial_dir, task, meta["env"], group, meta["regime"], reward, delivered,
                          reason, sim_time, env_calls, shell_calls, shell_before_end, None)
            if meta["env"] == "rover":
                game_map = find_map(trajectory)
                trial.tested = rover_tested(trajectory, game_map) if game_map else None
                if game_map:
                    trial.lane_choice, trial.off_map_commands, trial.last_command_off_map = \
                        rover_geometry(trajectory, game_map, meta["regime"])
                    trial.pad_time_share = rover_pad_time_share(trajectory, game_map)
                    trial.end_pose = rover_end_pose(trajectory)
                    if trial.reason in CRASHES:
                        trial.notes.append(crash_zone(trial.end_pose, game_map))
            else:
                trial.tested, trial.slow_tested = winch_tested(trajectory)
            trials.append(trial)
    return trials, excluded


# ------------------------------------------------------------------ reporting
def mean(values):
    values = list(values)
    return st.mean(values) if values else float("nan")


def table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def fmt(x, digits=3):
    return "–" if x != x else f"{x:.{digits}f}"


def report(all_trials: dict[str, list[Trial]], excluded: dict, reference: dict[str, float]) -> str:
    out = []
    out.append("## Trials used\n")
    out.append(table(["Model", "Completed trials used", "Rover", "Winch", "Left out (infrastructure)"],
                     [[m, len(t), sum(x.env == "rover" for x in t), sum(x.env == "winch" for x in t),
                       dict(excluded[m]) or "none"] for m, t in all_trials.items()]))

    out.append("\n\n## Headline (interim, completed trials only)\n")
    rows = []
    for m, trials in all_trials.items():
        for env in ("rover", "winch", "all"):
            sub = [t for t in trials if env == "all" or t.env == env]
            if not sub:
                continue
            ref = mean(reference[t.task] for t in sub if t.task in reference)
            rows.append([m, env, len(sub), fmt(mean(t.reward for t in sub)), f"{mean(t.delivered for t in sub):.0%}",
                         fmt(ref), fmt(mean(t.sim_time for t in sub if t.sim_time is not None), 1),
                         fmt(mean(t.env_calls for t in sub), 1)])
    out.append(table(["Model", "Env", "Trials", "Mean reward", "Delivery", "Reference on same tasks",
                      "Mean sim time (s)", "Mean env tool calls"], rows))

    out.append("\n\n## Outcome reasons\n")
    reasons = sorted({t.reason for ts in all_trials.values() for t in ts})
    rows = []
    for env in ("rover", "winch"):
        for r in reasons:
            counts = [sum(1 for t in ts if t.env == env and t.reason == r) for ts in all_trials.values()]
            if any(counts):
                rows.append([env, r] + counts)
    out.append(table(["Env", "Reason"] + list(all_trials), rows))

    out.append("\n\n## Per course / variation (mean reward, delivered/trials)\n")
    groups = sorted({(t.env, t.group) for ts in all_trials.values() for t in ts})
    rows = []
    for env, group in groups:
        row = [env, group]
        tasks_here = set()
        for ts in all_trials.values():
            sub = [t for t in ts if t.env == env and t.group == group]
            tasks_here |= {t.task for t in sub}
            row.append(f"{fmt(mean(t.reward for t in sub), 2)} ({sum(t.delivered for t in sub)}/{len(sub)})" if sub else "–")
        row.append(fmt(mean(reference[t] for t in tasks_here if t in reference), 2))
        rows.append(row)
    out.append(table(["Env", "Course / variation"] + list(all_trials) + ["Reference"], rows))

    out.append("\n\n## Did the agent test before committing?\n")
    rows = []
    for m, ts in all_trials.items():
        for env in ("rover", "winch"):
            sub = [t for t in ts if t.env == env]
            if not sub:
                continue
            tested = [t for t in sub if t.tested is True]
            untested = [t for t in sub if t.tested is False]
            never = [t for t in sub if t.tested is None]
            rows.append([m, env, len(sub), f"{len(tested)} ({len(tested) / len(sub):.0%})",
                         f"{fmt(mean(t.reward for t in tested), 2)} / {sum(t.delivered for t in tested)}/{len(tested)}",
                         len(untested),
                         f"{fmt(mean(t.reward for t in untested), 2)} / {sum(t.delivered for t in untested)}/{len(untested)}",
                         len(never)])
    out.append(table(["Model", "Env", "Trials", "Tested first", "Tested: mean reward / delivered",
                      "Committed untested", "Untested: mean reward / delivered", "Never committed"], rows))
    out.append("\n\nWinch, tension-limited take-up at <= 0.1 m/s before the first carry:\n")
    rows = []
    for m, ts in all_trials.items():
        sub = [t for t in ts if t.env == "winch"]
        slow = [t for t in sub if t.slow_tested]
        rows.append([m, len(sub), len(slow), f"{fmt(mean(t.reward for t in slow), 2)}",
                     sum(1 for t in sub if t.reason == "cable snapped")])
    out.append(table(["Model", "Winch trials", "Slow tension-limited test", "Their mean reward", "Cable snapped"], rows))

    out.append("\n\n## Failure modes among rover failures (reward 0)\n")
    rows = []
    for m, ts in all_trials.items():
        fails = [t for t in ts if t.env == "rover" and t.reward == 0]
        c = collections.Counter(t.reason for t in fails)
        early = [t for t in fails if t.sim_time is not None and t.sim_time <= 45]
        rows.append([m, len(fails), ", ".join(f"{k} {v}" for k, v in c.most_common()),
                     len(early), fmt(mean(t.env_calls for t in fails), 1)])
    out.append(table(["Model", "Rover failures", "Reasons", "Ended within 45 s of sim time", "Mean env calls"], rows))

    out.append("\n\n## Rover: lane choice and off-map commands\n")
    out.append("Lane choice = hazard of the first point on a drive_to path that lies inside a first-fork lane, compared "
               "with the hidden open lane. Off-map command = a drive_to whose straight path from the "
               "last known position leaves every drivable surface.\n\n")
    rows = []
    for m, ts in all_trials.items():
        sub = [t for t in ts if t.env == "rover"]
        if not sub:
            continue
        chose = collections.Counter(t.lane_choice for t in sub)
        crashes = [t for t in sub if t.reason in ("chassis_collision", "rollover", "left_drivable_surface", "cargo_dropped")]
        rows.append([m, len(sub), chose["open"], chose["closed"], chose[None],
                     f"{fmt(mean(t.reward for t in sub if t.lane_choice == 'open'), 2)}",
                     sum(t.off_map_commands > 0 for t in sub),
                     f"{sum(t.last_command_off_map for t in crashes)}/{len(crashes)}"])
    out.append(table(["Model", "Rover trials", "Entered open lane first", "Entered closed lane first",
                      "Never reached a lane", "Mean reward when open lane chosen",
                      "Trials with >= 1 off-map drive_to", "Crashes whose last drive_to was off-map"], rows))

    out.append("\n\nActing on the test: among rover trials that tested first and then entered a lane, how "
               "often was it the open lane? Chance = mean of 1 / number of lanes at the first fork.\n\n")
    rows = []
    for m, ts in all_trials.items():
        sub = [t for t in ts if t.env == "rover" and t.tested and t.lane_choice]
        if not sub:
            continue
        chance = mean(1 / LANES_AT_FIRST_FORK.get(t.group, 2) for t in sub)
        right = sum(t.lane_choice == "open" for t in sub)
        rows.append([m, len(sub), f"{right} ({right / len(sub):.0%})", f"{chance:.0%}"])
    out.append(table(["Model", "Tested, then entered a lane", "Entered the open lane", "Chance"], rows))

    out.append("\n\nWhere rover crashes happened (pose from the first observe after the episode ended):\n\n")
    zones = ["start pad / road to first fork", "lanes", "merge / goal approach", "unknown"]
    rows = []
    for m, ts in all_trials.items():
        crashes = [t for t in ts if t.env == "rover" and t.reason in CRASHES]
        rows.append([m, len(crashes)] + [sum(1 for t in crashes if zone in t.notes) for zone in zones])
    out.append(table(["Model", "Crashes"] + zones, rows))

    out.append("\n\nTime spent on the start pad (testing and positioning) before the first drive_to "
               "off the pad, as a share of the time budget (rover trials that left the pad):\n\n")
    rows = []
    for m, ts in all_trials.items():
        sub = [t for t in ts if t.env == "rover" and t.pad_time_share is not None]
        if not sub:
            continue
        over = [t for t in sub if t.pad_time_share > 0.4]
        rows.append([m, len(sub), f"{st.median(t.pad_time_share for t in sub):.0%}", len(over),
                     f"{fmt(mean(t.reward for t in over), 2)} / {sum(t.delivered for t in over)}/{len(over)}",
                     sum(1 for t in ts if t.env == "rover" and t.reason == "time_budget_exhausted")])
    out.append(table(["Model", "Trials", "Median share on pad", "Spent > 40% on pad",
                      "Those: mean reward / delivered", "Time budget exhausted"], rows))

    out.append("\n\n## Shell / filesystem use (exploit-seeking or restart attempts)\n")
    rows = []
    for m, ts in all_trials.items():
        rows.append([m, sum(t.shell_calls > 0 for t in ts), sum(t.shell_before_end > 0 for t in ts),
                     sum(t.shell_calls for t in ts),
                     sum(1 for t in ts if t.shell_calls > 0 and t.reward > 0)])
    out.append(table(["Model", "Trials with shell/file tool calls", "...before the episode ended",
                      "Total such calls", "Of those trials, reward > 0"], rows))

    out.append("\n\n## Same task: Inkling 0 vs DeepSeek delivered\n")
    if "inkling" in all_trials and "deepseek" in all_trials:
        ds = collections.defaultdict(list)
        for t in all_trials["deepseek"]:
            ds[t.task].append(t)
        rows = []
        for t in all_trials["inkling"]:
            wins = [d for d in ds.get(t.task, []) if d.delivered]
            if t.reward == 0 and wins:
                rows.append([t.task, t.regime, t.reason, t.tested, fmt(wins[0].reward, 3), wins[0].tested,
                             fmt(reference.get(t.task, float("nan")), 3),
                             str(t.path.relative_to(Path.cwd())) if t.path.is_absolute() else str(t.path),
                             str(wins[0].path)])
        out.append(table(["Task", "Regime", "Inkling outcome", "Ink tested", "DeepSeek reward", "DS tested",
                          "Reference", "Inkling trial", "DeepSeek trial"], rows))

    out.append("\n\n## All trials\n")
    rows = []
    for m, ts in all_trials.items():
        for t in sorted(ts, key=lambda x: x.task):
            rows.append([m, t.task, t.regime, fmt(t.reward, 3), t.reason, fmt(t.sim_time or float("nan"), 1),
                         t.env_calls, t.tested, t.lane_choice, t.off_map_commands, t.path.name])
    out.append(table(["Model", "Task", "Regime", "Reward", "Reason", "Sim t", "Env calls", "Tested", "Lane", "Off-map cmds", "Trial dir"], rows))
    return "\n".join(out) + "\n"


def reference_rewards(job: Path, eval_set: dict) -> dict[str, float]:
    rewards = {}
    for trial_dir in job.iterdir():
        sim = trial_dir / "verifier" / "sim_result.json"
        if trial_dir.is_dir() and sim.exists():
            task = Path(json.loads((trial_dir / "config.json").read_text())["task"]["path"]).name
            if task in eval_set:
                rewards[task] = json.loads(sim.read_text())["reward"]
    return rewards


def main(argv: list[str]):
    eval_set = {t["task"]: t for t in json.loads(Path("harbor_tasks/eval_set.json").read_text())}
    reference_job = None
    if "--reference" in argv:
        i = argv.index("--reference")
        reference_job = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    all_trials, excluded = {}, {}
    for argument in argv:
        model, dirs = argument.split("=", 1)
        all_trials[model], excluded[model] = load(model, [Path(d) for d in dirs.split(",")], eval_set)
    reference = reference_rewards(reference_job, eval_set) if reference_job else {}
    print(report(all_trials, excluded, reference))
    dump = [{k: (str(v) if isinstance(v, Path) else v) for k, v in t.__dict__.items()}
            for ts in all_trials.values() for t in ts]
    Path("presentation/scripts/trials.json").write_text(json.dumps(dump, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
