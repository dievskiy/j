"""Scripted policies for the fork worlds.

Every policy sees only the agent tools through a `ToolProxy` and reads the course
from the public map, so the same code runs on every fork world.
"""
from __future__ import annotations

import math
import statistics as stats

from .policies import (RR, _settle_and_finish, do_nothing, immediate_finish, invalid_inputs,
                       random_actions, wait_spam)

PLANNED_DECEL = 1.5       # what drive_to assumes when it plans a stop (published in the map)
MAX_DRIVE_ACCEL = 2.5     # nominal motor-limited acceleration (published vehicle spec)
CRUISE = 3.0
PUSH_SPEED = 1.2          # speed for approaching and pushing a crate
OK = ("arrived", "overshot_target")


# ----------------------------------------------------------------- driving helpers
def _pose(env):
    p = env.observe()["pose"]
    return p["x"], p["y"]


def _drive(env, points, speed):
    """Follow points in order; stop at the first command that does not end normally."""
    result = {"termination": "arrived"}
    for x, y in points:
        result = env.drive_to(x, y, speed, 60.0)
        if result["termination"] not in OK:
            break
    return result


def _lane_speed(lane):
    return PUSH_SPEED if lane["hazard"] == "crate" else CRUISE


def _finish(env, m):
    return _settle_and_finish(env, (m["goal"]["x"], m["goal"]["y"]), m["goal"]["radius"])


def _take_lane(env, lane, speed=None):
    return _drive(env, lane["waypoints"], speed or _lane_speed(lane))


def _goal(m):
    return (m["goal"]["x"], m["goal"]["y"])


# ----------------------------------------------------------------- tests on the start pad
def test_mud(env, sample) -> bool:
    """Edge into the sample strip in short steps and stop as soon as the drag can be
    read, so that thick mud is not entered deeply. Passable if full throttle still
    gives a useful speed."""
    y_lo, y_hi = sample["y"]
    x = (sample["x"][0] + sample["x"][1]) / 2
    edge, inward = (y_lo, 1.0) if y_lo > 0 else (y_hi, -1.0)     # approach from the pad centre
    env.drive_to(x, edge - inward * 1.6, 2.0, 20.0)
    in_mud = []
    for _ in range(12):
        env.drive_to(x, edge + inward * 2.2, 1.5, 0.4)
        trace = env.observe()["last_command"]["trace"]
        in_mud += [s for s in trace if inward * (s["y"] - edge) > 0.15 and s["meas_speed"] > 0.05]
        if len(in_mud) >= 4:
            break
    env.drive_to(x, edge - inward * 1.6, 2.0, 20.0)
    if not in_mud:
        return False
    drag = stats.median((s["cmd_accel"] - s["meas_accel"] - RR) / s["meas_speed"] for s in in_mud)
    return (MAX_DRIVE_ACCEL - RR) / max(drag, 1e-6) > 1.2


def test_ice(env, sample) -> bool:
    """Enter the sample strip at speed and brake; passable if the ice can deliver the
    deceleration drive_to plans its stops with."""
    x_lo, x_hi = sample["x"]
    y = (sample["y"][0] + sample["y"][1]) / 2
    env.drive_to(x_lo - 4.5, y, 2.0, 20.0)
    env.drive_to(x_lo - 3.0, y, 1.0, 20.0)         # now facing along the strip
    for _ in range(12):                            # run in until just inside the strip
        env.drive_to(x_hi + 3.0, y, 2.0, 0.3)
        if _pose(env)[0] > x_lo + 0.8:
            break
    env.brake()
    trace = env.observe()["last_command"]["trace"]
    decel = [-s["meas_accel"] for s in trace
             if s["brake"] and s["meas_speed"] > 0.3 and x_lo < s["x"] < x_hi]
    return bool(decel) and 0.8 * stats.median(decel) >= PLANNED_DECEL


def test_wind(env, sample) -> bool:
    """Creep into the sample strip in short steps and watch the sideways movement per
    step. A strong wind shows within a step or two, before the rover has picked up
    enough sideways speed to throw the cargo; a light one never does."""
    x_lo, x_hi = sample["x"]
    y = (sample["y"][0] + sample["y"][1]) / 2
    x_now, _ = _pose(env)
    # enter from whichever end of the strip the rover is nearer to
    entry, direction = (x_lo, 1.0) if abs(x_now - x_lo) < abs(x_now - x_hi) else (x_hi, -1.0)
    env.drive_to(entry - direction * 2.0, y, 2.0, 20.0)
    _, y_before = _pose(env)
    for _ in range(20):
        env.drive_to(entry + direction * 4.0, y, 1.0, 0.4)
        x_now, y_now = _pose(env)
        if abs(y_now - y_before) > 0.35:
            return False
        if direction * (x_now - entry) > 2.5:
            return True
        y_before = y_now
    return False


def test_crate(env, sample) -> bool:
    """Push the sample crate for a moment; passable if it actually moves."""
    cx, cy = sample["x"], sample["y"]
    env.drive_to(cx - 3.0, cy, 2.0, 20.0)
    start = env.observe()["crates"]["crate_sample"]["x"]
    env.drive_to(cx + 2.0, cy, PUSH_SPEED, 4.0)
    moved = env.observe()["crates"]["crate_sample"]["x"] - start
    env.drive_to(cx - 3.0, cy, 2.0, 20.0)          # back off so the crate is not in the way
    return moved > 0.5


def test_barrier(env, sample, lane) -> bool:
    """Look from the lookout; passable if no barrier is reported in the lane."""
    env.drive_to(sample["x"], sample["y"], 2.5, 20.0)
    barriers = env.observe()["detected_barriers"]
    lane_y = lane["waypoints"][len(lane["waypoints"]) // 2][1]
    return not any(abs(b["y"] - lane_y) < 2.0 for b in barriers)


def lane_is_passable(env, lane) -> bool:
    sample = lane["test_on_start_pad"]
    hazard = lane["hazard"]
    if hazard == "barrier":
        return test_barrier(env, sample, lane)
    return {"mud": test_mud, "ice": test_ice, "wind": test_wind, "crate": test_crate}[hazard](env, sample)


# ----------------------------------------------------------------- reference
def _route_length(lane) -> float:
    w = lane["waypoints"]
    return sum(math.dist(a, b) for a, b in zip(w, w[1:]))


def _choose_tested_lane(env, lanes):
    """Test lanes shortest-first and return the first passable one. The last candidate is
    taken untested: the map says at least one lane is passable."""
    ordered = sorted(lanes, key=_route_length)
    for lane in ordered[:-1]:
        if lane_is_passable(env, lane):
            return lane
    return ordered[-1]


def _choose_unsampled_lane(env, lanes):
    """At a fork without samples: look for barriers from where the rover stands, and
    prefer a lane the sensors show to be clear."""
    barriers = env.observe()["detected_barriers"]
    barrier_lanes = [lane for lane in lanes if lane["hazard"] == "barrier"]
    for lane in barrier_lanes:
        lane_y = lane["waypoints"][len(lane["waypoints"]) // 2][1]
        if not any(abs(b["y"] - lane_y) < 2.0 for b in barriers):
            return lane
    others = [lane for lane in lanes if lane["hazard"] != "barrier"]
    return sorted(others or lanes, key=_route_length)[0]


def reference(env):
    """Test hazards on the start pad, take the lane the evidence supports; at a fork
    without samples, look before choosing."""
    m = env.observe()["map"]
    forks = m["forks"]
    first = _choose_tested_lane(env, forks[0]["lanes"])
    result = _drive(env, [tuple(m["pad_exit"])], CRUISE)
    if result["termination"] in OK:
        result = _take_lane(env, first)
    for fork in forks[1:]:
        if result["termination"] not in OK:
            break
        result = _drive(env, [tuple(fork["fork_node"])], CRUISE)
        if result["termination"] in OK:
            result = _take_lane(env, _choose_unsampled_lane(env, fork["lanes"]))
    if result["termination"] in OK:
        _drive(env, [_goal(m)], CRUISE)
    return _finish(env, m)


# ----------------------------------------------------------------- non-diagnosing plans
def _fixed_lane(index, speed=None):
    def policy(env):
        m = env.observe()["map"]
        result = _drive(env, [tuple(m["pad_exit"])], CRUISE)
        for fork in m["forks"]:
            if result["termination"] not in OK:
                break
            lanes = fork["lanes"]
            result = _take_lane(env, lanes[min(index, len(lanes) - 1)], speed)
        if result["termination"] in OK:
            _drive(env, [_goal(m)], speed or CRUISE)
        return _finish(env, m)
    return policy


def try_then_retreat(env):
    """Adapts without testing: enter the shortest lane, and if little progress is made in
    six seconds go back to the fork and try the next one."""
    m = env.observe()["map"]
    result = _drive(env, [tuple(m["pad_exit"])], CRUISE)
    for fork in m["forks"]:
        if result["termination"] not in OK:
            break
        for lane in sorted(fork["lanes"], key=_route_length):
            first_leg = lane["waypoints"][1] if len(lane["waypoints"]) > 2 else lane["waypoints"][-1]
            env.drive_to(lane["waypoints"][0][0], lane["waypoints"][0][1], CRUISE, 30.0)
            env.drive_to(first_leg[0], first_leg[1], _lane_speed(lane), 30.0)
            target = lane["waypoints"][2] if len(lane["waypoints"]) > 2 else lane["waypoints"][-1]
            at_entry = _pose(env)
            result = env.drive_to(target[0], target[1], _lane_speed(lane), 6.0)
            if result["termination"] not in OK + ("max_duration_reached",):
                break
            if math.dist(_pose(env), at_entry) > 5.0 or result["termination"] in OK:
                result = _take_lane(env, lane)
                break
            result = _drive(env, [tuple(fork["fork_node"])], CRUISE)      # retreat
        if result["termination"] not in OK:
            break
    if result["termination"] in OK:
        _drive(env, [_goal(m)], CRUISE)
    return _finish(env, m)


POLICIES = {
    "reference": reference,
    "lane_1_fast": _fixed_lane(0),
    "lane_2_fast": _fixed_lane(1),
    "lane_3_fast": _fixed_lane(2),
    "lane_1_cautious": _fixed_lane(0, 0.8),
    "lane_2_cautious": _fixed_lane(1, 0.8),
    "try_then_retreat": try_then_retreat,
    "do_nothing": do_nothing,
    "immediate_finish": immediate_finish,
    "wait_spam": wait_spam,
    "random_actions": random_actions,
    "invalid_inputs": invalid_inputs,
}
DIAGNOSING = ("reference",)
