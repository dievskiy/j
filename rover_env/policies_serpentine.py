"""Scripted policies for the serpentine course.

Like `policies.py`, every policy sees only the five agent tools through a
`ToolProxy` and never reads the seed, the hidden parameters or the simulator.
"""
from __future__ import annotations

import math
import statistics as stats

from .policies import (RR, _settle_and_finish, _subdivide, do_nothing, estimate,
                       immediate_finish, invalid_inputs, random_actions, wait_spam)

PLANNED_DECEL = 1.5      # what drive_to assumes when it plans a stop (published in the map)
SPEED_GAIN = 3.0         # drive_to speed-loop gain (published in the map)
HEADING_GAIN = 2.0       # drive_to heading gain (published in the map)
MAX_HEADING_OFFSET = 0.1 # rad: largest steady heading error the reference accepts
MAX_DRIVE_ACCEL = 2.5    # nominal motor-limited acceleration (published vehicle spec)
UNKNOWN_THICK_MUD = 20.0  # assumed drag (1/s) when the mud probe yields no usable samples
OK = ("arrived", "overshot_target")


# ----------------------------------------------------------------- shared helpers
def _nodes(m):
    return {k: tuple(v) for k, v in m["nodes"].items()}


def _pose(env):
    p = env.observe()["pose"]
    return p["x"], p["y"]


def _drive_legs(env, points, speed, max_leg=100.0):
    """Follow centre-line points, splitting long legs. Stops at the first failure."""
    result = None
    for target in _subdivide(_pose(env), points, max_leg):
        result = env.drive_to(target[0], target[1], speed, 60.0)
        if result["termination"] not in OK:
            break
    return result


def _pad_exit(m):
    """Point on the start pad in line with the exit road, so no leg cuts a pad corner."""
    return (m["calibration_area"]["x"][1] - 2.0, 0.0)


def _finish(env, m):
    return _settle_and_finish(env, tuple(m["goal"][k] for k in ("x", "y")), m["goal"]["radius"])


# ----------------------------------------------------------------- fixed (non-diagnosing) plans
def shortcut_fast(env):
    m = env.observe()["map"]
    n = _nodes(m)
    _drive_legs(env, [n["P1"], n["J"], n["P6"], n["goal"]], 3.0)
    return _finish(env, m)


def _serpentine(env, paved_speed, ice_speed):
    m = env.observe()["map"]
    n = _nodes(m)
    r = _drive_legs(env, [n["P1"], n["P2"], n["P3"]], paved_speed)
    if r["termination"] in OK:
        r = _drive_legs(env, [n["J"], n["P4"]], ice_speed)
    if r["termination"] in OK:
        _drive_legs(env, [n["P5"], n["P6"], n["goal"]], paved_speed)
    return _finish(env, m)


def serpentine_fast(env):
    return _serpentine(env, 3.0, 3.0)


def serpentine_medium(env):
    return _serpentine(env, 2.0, 2.0)


def serpentine_slow(env):
    return _serpentine(env, 1.2, 1.2)


def serpentine_crawl_ice(env):
    """Strongest fixed plan: full speed on pavement, crawl on the ice."""
    return _serpentine(env, 3.0, 0.7)


def try_shortcut_then_retreat(env):
    """Adapts without calibrating: enter the mud, and if progress is poor after a few
    seconds turn back and take the serpentine with a crawl on the ice."""
    m = env.observe()["map"]
    n = _nodes(m)
    env.drive_to(n["P1"][0], n["P1"][1], 3.0, 30.0)
    x_before = _pose(env)[0]
    env.drive_to(n["J"][0], n["J"][1], 3.0, 4.0)
    if _pose(env)[0] - x_before > 4.0:           # mud is thin enough: keep going
        _drive_legs(env, [n["J"], n["P6"], n["goal"]], 3.0)
        return _finish(env, m)
    env.drive_to(n["P1"][0], n["P1"][1], 3.0, 30.0)
    r = _drive_legs(env, [n["P2"], n["P3"]], 3.0)
    if r["termination"] in OK:
        r = _drive_legs(env, [n["J"], n["P4"]], 0.7)
    if r["termination"] in OK:
        _drive_legs(env, [n["P5"], n["P6"], n["goal"]], 3.0)
    return _finish(env, m)


# ----------------------------------------------------------------- reference: probe, estimate, choose
def _patch(m, name):
    return next(p for p in m["surface_patches"] if p["name"] == name)


def probe_vehicle(env):
    """Full-throttle launch then full brake on pavement: brake capacity and steering bias."""
    x, y = _pose(env)
    env.drive_to(x + 25.0, y, 3.0, 1.6)
    launch = env.observe()["last_command"]["trace"]
    env.brake()
    braking = env.observe()["last_command"]["trace"]
    return estimate(launch, braking)


def probe_mud(env, m):
    """Dip ~1.5 m into the mud sample strip and read the drag from the speed shortfall.
    Returns the drag coefficient k (1/s) in decel = k * speed."""
    strip = _patch(m, "mud_sample_strip")
    x, _ = _pose(env)
    x = min(max(x, strip["x"][0] + 1.5), strip["x"][1] - 1.5)
    edge = strip["y"][0]
    env.drive_to(x, edge - 1.6, 2.0, 20.0)                 # line up just outside the strip
    env.drive_to(x, edge + 2.2, 1.5, 3.5)
    trace = env.observe()["last_command"]["trace"]
    in_mud = [s for s in trace if s["y"] > edge + 0.15 and s["meas_speed"] > 0.05]
    steady = in_mud[len(in_mud) // 2:]                      # skip the entry transient
    samples = [(s["cmd_accel"] - s["meas_accel"] - RR) / s["meas_speed"] for s in steady]
    env.drive_to(x, edge - 1.6, 2.0, 20.0)                 # back out onto pavement
    return max(stats.median(samples), 0.0) if samples else UNKNOWN_THICK_MUD


def probe_ice(env, m):
    """Get up to speed on the ice sample strip and brake: returns usable decel (m/s^2)."""
    strip = _patch(m, "ice_sample_strip")
    y = (strip["y"][0] + strip["y"][1]) / 2
    env.drive_to(strip["x"][1] - 1.5, y, 2.0, 30.0)
    env.drive_to(strip["x"][0] + 1.0, y, 2.5, 3.0)
    env.brake()
    trace = env.observe()["last_command"]["trace"]
    decel = [-s["meas_accel"] for s in trace if s["brake"] and s["meas_speed"] > 0.3]
    return max(stats.median(decel), 0.05) if decel else 0.3


def _paved_speed(est):
    """Fastest speed whose corner overshoot (weak brakes vs planned decel) stays ~0.4 m."""
    cap = 0.85 * (est["brake"] + RR)
    v = 3.5
    while v > 1.0 and cap < PLANNED_DECEL and 0.5 * v * v * (1 / cap - 1 / PLANNED_DECEL) > 0.4:
        v -= 0.25
    # steering bias: the heading offset |bias| * v / gain grows with speed; cap it
    if abs(est["bias"]) > 0.02:
        v = min(v, max(1.5, MAX_HEADING_OFFSET * HEADING_GAIN / abs(est["bias"])))
    return v


def _max_leg(est, speed, m):
    """Steering bias gives a heading offset of |bias| * v / gain; keep legs short enough
    that the resulting drift stays well inside the road."""
    offset = abs(est["bias"]) * speed / m["drive_to_controller"]["heading_gain"]
    return 100.0 if offset < 0.02 else max(5.0, 0.7 / offset)


def _mud_speed(k):
    """Steady speed in mud at full throttle: drag k*v balances the motor limit."""
    return min(3.0, (MAX_DRIVE_ACCEL - RR) / max(k, 1e-6))


def _ice_leg_time(length, decel):
    peak = math.sqrt(decel * length)
    return 2.0 * peak / decel if peak < 3.0 else length / 3.0 + 3.0 / decel


def drive_on_ice(env, target, decel, est, m, margin=1.0):
    """Cross ice to `target` and stop there despite drive_to planning a firmer stop.

    Each hop cruises toward an earlier aim point chosen so that, when drive_to starts
    slowing for it and the ice only delivers `decel`, the rover comes to rest about
    `margin` short of the real target. Hops repeat until the rest is short enough to creep.
    """
    usable = 0.8 * decel
    result = None
    for _ in range(4):
        x, y = _pose(env)
        length = math.hypot(target[0] - x, target[1] - y)
        if length < margin + 1.5:
            break
        cruise = min(3.0, 0.8 * math.sqrt(usable * (length - margin)))
        overshoot = max(cruise * cruise / (2 * usable) - cruise * cruise / (2 * PLANNED_DECEL), 0.0)
        f = max(length - margin - overshoot, 0.5) / length
        aim = (x + (target[0] - x) * f, y + (target[1] - y) * f)
        result = _drive_legs(env, [aim], cruise, _max_leg(est, cruise, m))
        if result["termination"] not in OK:
            return result
    creep = max(0.4, min(1.0, math.sqrt(2 * usable * 0.3)))
    return _drive_legs(env, [target], creep, _max_leg(est, creep, m))


def reference(env):
    """Probe the vehicle and the mud; probe the ice only if the serpentine is in play;
    then take whichever route the estimates say is faster."""
    m = env.observe()["map"]
    n = _nodes(m)
    width = m["road_width"]
    est = probe_vehicle(env)
    mud_k = probe_mud(env, m)
    v_paved = _paved_speed(est)
    leg = _max_leg(est, v_paved, m)

    mud_length = (n["P6"][0] - n["P1"][0]) - 2 * width
    t_shortcut = mud_length / _mud_speed(mud_k) + (n["P6"][0] - n["P1"][0] - mud_length) / v_paved
    serp_paved = (2 * abs(n["P2"][1]) + (n["P3"][0] - n["P2"][0]) + (n["P5"][0] - n["P4"][0]))
    ice_length = 2 * abs(n["P4"][1])
    # optimistic bound for the serpentine (mild ice); if the shortcut beats even that, take it
    t_serp_best = serp_paved / v_paved + 4 * 3.0 + _ice_leg_time(ice_length, PLANNED_DECEL)
    if t_shortcut <= t_serp_best:
        _drive_legs(env, [_pad_exit(m), n["P1"], n["J"], n["P6"], n["goal"]], v_paved, leg)
        return _finish(env, m)

    ice_decel = probe_ice(env, m)
    t_serp = serp_paved / v_paved + 4 * 3.0 + _ice_leg_time(ice_length, 0.8 * ice_decel) + 12.0
    if t_shortcut <= t_serp:
        _drive_legs(env, [_pad_exit(m), n["P1"], n["J"], n["P6"], n["goal"]], v_paved, leg)
        return _finish(env, m)
    r = _drive_legs(env, [_pad_exit(m), n["P1"], n["P2"], n["P3"]], v_paved, leg)
    if r["termination"] in OK:
        if 0.8 * ice_decel >= PLANNED_DECEL:      # grippy enough for drive_to's own stop
            r = _drive_legs(env, [n["J"], n["P4"]], v_paved, leg)
        else:
            r = drive_on_ice(env, n["P4"], ice_decel, est, m)
    if r["termination"] in OK:
        _drive_legs(env, [n["P5"], n["P6"], n["goal"]], v_paved, leg)
    return _finish(env, m)


POLICIES = {
    "reference": reference,
    "shortcut_fast": shortcut_fast,
    "serpentine_fast": serpentine_fast,
    "serpentine_medium": serpentine_medium,
    "serpentine_slow": serpentine_slow,
    "serpentine_crawl_ice": serpentine_crawl_ice,
    "try_shortcut_then_retreat": try_shortcut_then_retreat,
    "do_nothing": do_nothing,
    "immediate_finish": immediate_finish,
    "wait_spam": wait_spam,
    "random_actions": random_actions,
    "invalid_inputs": invalid_inputs,
}
DIAGNOSING = ("reference",)
