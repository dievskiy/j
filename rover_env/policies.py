"""Scripted policies. Every policy receives a `ToolProxy` exposing ONLY the five
agent tools (observe, drive_to, brake, wait, finish), exactly as an agent over MCP
would see them. No policy reads the seed, the hidden mode, or the simulator.
"""
from __future__ import annotations

import math
import random
import statistics as stats

G = 9.81
RR = 0.15   # rolling-resistance decel the reference assumes (≈ nominal flat accel shortfall)


class ToolProxy:
    """Exposes only the agent tool surface of an Episode."""
    __slots__ = ("_tools",)

    def __init__(self, episode):
        object.__setattr__(self, "_tools", {n: getattr(episode, n) for n in episode.TOOLS})

    def __getattr__(self, name):
        try:
            return self._tools[name]
        except KeyError:
            raise AttributeError(name)


# ----------------------------------------------------------------- helpers
def _follow(env, pts, speed, max_dur=45.0):
    for p in pts:
        r = env.drive_to(p[0], p[1], speed, max_dur)
        if r["termination"] not in ("arrived", "overshot_target"):
            return r
    return r


def _subdivide(start, pts, max_leg):
    out, prev = [], start
    for p in pts:
        d = math.hypot(p[0] - prev[0], p[1] - prev[1])
        n = max(1, int(math.ceil(d / max_leg)))
        for k in range(1, n + 1):
            out.append((prev[0] + (p[0] - prev[0]) * k / n, prev[1] + (p[1] - prev[1]) * k / n))
        prev = p
    return out


def _settle_and_finish(env, goal, r_goal):
    """Check (noisy) pose against the goal; one corrective move if clearly outside."""
    o = env.observe()
    if o["episode"]["ended"]:
        return env.finish()
    p = o["pose"]
    if math.hypot(p["x"] - goal[0], p["y"] - goal[1]) > r_goal - 0.4:
        env.drive_to(goal[0], goal[1], 0.8, 30.0)
    return env.finish()


# ----------------------------------------------------------------- probing / estimation
def probe(env, m):
    """~4 s manoeuvre in the calibration area: full-throttle launch, then full brake.
    Returns estimates derived only from commanded-vs-measured traces."""
    cal = m["calibration_area"]
    o = env.observe()
    x0, y0 = o["pose"]["x"], o["pose"]["y"]
    # launch toward a far point straight ahead; cut the command at ~1.6 s while at speed
    r1 = env.drive_to(x0 + 25.0, y0, 3.0, 1.6)
    tr1 = env.observe()["last_command"]["trace"]
    r2 = env.brake()
    tr2 = env.observe()["last_command"]["trace"]
    return estimate(tr1, tr2), (r1, r2)


def estimate(tr_drive, tr_brake):
    acc = [s["meas_accel"] for s in tr_drive if s["cmd_accel"] >= 2.49 and 0.3 < s["meas_speed"]]
    a_drive = stats.median(acc) if acc else None
    bias_s = [(s["meas_yaw_rate"] - s["cmd_yaw_rate"]) / s["meas_speed"]
              for s in tr_drive if s["meas_speed"] > 1.0]
    bias = stats.median(bias_s) if bias_s else 0.0
    dec = [-s["meas_accel"] for s in tr_brake if s["brake"] and s["meas_speed"] > 0.4]
    decel = stats.median(dec) if dec else None
    # traction-limited if launch accel is clearly below the motor limit (~2.35 measured)
    mu_g = (a_drive + RR) if (a_drive is not None and a_drive < 2.2) else 9.0 * 0.9
    cap = (decel - RR) if decel is not None else 4.5     # min(brake, mu*g)
    brake = cap   # conservative: only min(brake, mu*g) is observable on flat ground
    return {"a_drive": a_drive, "mu_g": mu_g, "decel_cap": cap, "brake": brake, "bias": bias}


def short_route_speed(est, m):
    """Largest speed for which a simple point-mass model predicts the rover stops on
    the landing pad. None => short route judged infeasible."""
    ramp = next(s for s in m["drivable_surfaces"] if s["name"] == "short_ramp")
    pad = next(s for s in m["drivable_surfaces"] if s["name"] == "east_road_and_landing_pad")
    th = math.radians(ramp["slope_deg"])
    Ls = (ramp["x"][1] - ramp["x"][0]) / math.cos(th)
    P = pad["x"][1] - pad["x"][0]
    ramp_cap = min(est["brake"], est["mu_g"] * math.cos(th)) + RR - G * math.sin(th)
    flat_cap = min(est["brake"], est["mu_g"]) + RR
    vmax_bias = 3.0 if abs(est["bias"]) < 0.08 else max(0.8, 0.2 / abs(est["bias"]))
    for v0 in (3.0, 2.5, 2.0, 1.5, 1.0, 0.7):
        if v0 > vmax_bias:
            continue
        if ramp_cap >= 0.4:
            return v0
        vb2 = v0 * v0 + 2.0 * (-ramp_cap) * Ls
        stop = vb2 / (2.0 * flat_cap)
        if stop <= 0.5 * P + 0.6:
            return v0
    return None


def long_route_plan(est, m):
    """Speed and maximum leg length for the gentle route."""
    ramp = next(s for s in m["drivable_surfaces"] if s["name"] == "long_ramp")
    th = math.radians(ramp["slope_deg"])
    ramp_cap = min(est["brake"], est["mu_g"] * math.cos(th)) + RR - G * math.sin(th)
    a_plan = m["drive_to_controller"]["planned_decel"]
    k_head = m["drive_to_controller"]["heading_gain"]
    v = 3.0
    # overshoot past the bottom-of-ramp waypoint must stay well inside the 8 m road
    while v > 1.0 and ramp_cap < a_plan and \
            0.5 * v * v * (1.0 / max(ramp_cap, 0.05) - 1.0 / a_plan) > 2.0:
        v -= 0.25
    # limit overshoot past flat-ground waypoints to ~1 m
    cap_flat = 0.8 * (min(est["brake"], est["mu_g"]) + RR)
    while v > 1.0 and cap_flat < a_plan and \
            0.5 * v * v * (1.0 / cap_flat - 1.0 / a_plan) > 1.0:
        v -= 0.25
    # steering bias: steady-state heading offset alpha = |bias| * v / k_head; keep legs
    # short enough that the pursuit curve stays on the road
    alpha = abs(est["bias"]) * v / k_head
    leg = 100.0 if alpha < 0.02 else max(12.0, 2.5 / alpha)
    return v, leg


# ----------------------------------------------------------------- policies
def reference(env):
    o = env.observe()
    m = o["map"]
    goal = (m["goal"]["x"], m["goal"]["y"])
    est, _ = probe(env, m)
    v_short = short_route_speed(est, m)
    if v_short is not None:
        top = m["routes"]["short"][0]
        r = env.drive_to(top[0], top[1], min(3.0, max(v_short, 2.0)), 45.0)
        if r["termination"] not in ("arrived", "overshot_target"):
            return _settle_and_finish(env, goal, m["goal"]["radius"])
        # replan with the longer, richer trace from the approach leg (steering evidence)
        tr = env.observe()["last_command"]["trace"]
        bs = [(s["meas_yaw_rate"] - s["cmd_yaw_rate"]) / s["meas_speed"]
              for s in tr if s["meas_speed"] > 1.0]
        if bs:
            est["bias"] = 0.5 * est["bias"] + 0.5 * stats.median(bs)
        v_short = short_route_speed(est, m)
        if v_short is not None:
            env.drive_to(goal[0], goal[1], v_short, 45.0)
            return _settle_and_finish(env, goal, m["goal"]["radius"])
    # long route
    v, leg = long_route_plan(est, m)
    o = env.observe()
    start = (o["pose"]["x"], o["pose"]["y"])
    wps = m["routes"]["long"]
    pre_goal = (wps[-1][0], wps[-1][1] - 4.0)
    pts = _subdivide(start, wps[:-1] + [pre_goal], leg)
    r = _follow(env, pts, v)
    if r["termination"] in ("arrived", "overshot_target"):
        env.drive_to(goal[0], goal[1], 1.0, 30.0)
    return _settle_and_finish(env, goal, m["goal"]["radius"])


def _route_policy(route, speed, probe_first=False):
    def pol(env):
        m = env.observe()["map"]
        goal = (m["goal"]["x"], m["goal"]["y"])
        if probe_first:
            probe(env, m)
        _follow(env, m["routes"][route], speed)
        return env.finish()
    return pol


always_safe = _route_policy("long", 3.0)
always_short = _route_policy("short", 3.0)
always_slow = _route_policy("short", 1.0)
slow_safe = _route_policy("long", 1.5)


def robust_safe(env):
    """Strongest non-diagnosing baseline we found: gentle route, moderate speed, legs
    of <=12 m (tolerates steering bias), slow final approach."""
    m = env.observe()["map"]
    goal = (m["goal"]["x"], m["goal"]["y"])
    wps = m["routes"]["long"]
    pts = _subdivide((0.0, 0.0), wps[:-1] + [(goal[0], goal[1] - 4.0)], 12.0)
    r = _follow(env, pts, 2.5)
    if r["termination"] in ("arrived", "overshot_target"):
        env.drive_to(goal[0], goal[1], 1.0, 30.0)
    return _settle_and_finish(env, goal, m["goal"]["radius"])


def probe_lookup(env):
    """Same probe as the reference, but a categorical diagnosis + fixed lookup table
    (ignores fault magnitude)."""
    m = env.observe()["map"]
    goal = (m["goal"]["x"], m["goal"]["y"])
    est, _ = probe(env, m)
    traction = est["a_drive"] is not None and est["a_drive"] < 2.2
    braking = (not traction) and est["decel_cap"] < 4.0
    steering = abs(est["bias"]) > 0.03
    if not (traction or braking):
        route, v = "short", (2.0 if steering else 3.0)
        _follow(env, m["routes"][route], v)
    else:
        o = env.observe()
        pts = m["routes"]["long"]
        if steering:
            pts = _subdivide((o["pose"]["x"], o["pose"]["y"]), pts, 8.0)
        _follow(env, pts, 2.0)
    return env.finish()


def direct_line(env):
    m = env.observe()["map"]
    env.drive_to(m["goal"]["x"], m["goal"]["y"], 3.0, 60.0)
    return env.finish()


# ----------------------------------------------------------------- integrity baselines
def do_nothing(env):
    return None          # never calls finish()


def immediate_finish(env):
    return env.finish()


def wait_spam(env):
    for _ in range(10):
        r = env.wait(60.0)
        if r["termination"] != "waited":
            break
    return env.finish()


def random_actions(env, rng_seed=0):
    m = env.observe()["map"]
    b = m["world_bounds"]
    rng = random.Random(rng_seed)
    for _ in range(12):
        k = rng.random()
        if k < 0.6:
            r = env.drive_to(rng.uniform(b["xmin"], b["xmax"]), rng.uniform(b["ymin"], b["ymax"]),
                             rng.uniform(0.2, 5.0), rng.uniform(0.5, 15.0))
        elif k < 0.8:
            r = env.brake()
        else:
            r = env.wait(rng.uniform(0.1, 5.0))
        if r["termination"] == "episode_over" or r["termination"].startswith(("hard", "time_b", "energy_b")):
            break
    return env.finish()


BAD_INPUTS = [
    ("drive_to", (float("nan"), 0, 1, 1)), ("drive_to", (0, float("inf"), 1, 1)),
    ("drive_to", (1e9, 0, 1, 1)), ("drive_to", (5, 0, -1, 1)), ("drive_to", (5, 0, 1e6, 1)),
    ("drive_to", (5, 0, 1, -5)), ("drive_to", (5, 0, 1, 1e9)), ("drive_to", ("5", "x", 1, 1)),
    ("drive_to", (True, 0, 1, 1)), ("drive_to", (5, 0, float("nan"), 1)),
    ("wait", (-1,)), ("wait", (float("nan"),)), ("wait", (1e12,)), ("wait", (0,)),
]


def invalid_inputs(env):
    for name, args in BAD_INPUTS:
        r = getattr(env, name)(*args)
        assert r["termination"] == "invalid_input", (name, args, r)
    return env.finish()


def finish_twice_after_short(env):
    """Delivers via short route at 3 m/s and then calls finish() repeatedly (counted once)."""
    always_short(env)
    for _ in range(3):
        env.finish()


POLICIES = {
    "reference": reference,
    "always_safe_route": always_safe,
    "always_short_route": always_short,
    "always_slow_short": always_slow,
    "slow_safe_route": slow_safe,
    "robust_safe_route": robust_safe,
    "probe_lookup_table": probe_lookup,
    "direct_line": direct_line,
    "do_nothing": do_nothing,
    "immediate_finish": immediate_finish,
    "wait_spam": wait_spam,
    "random_actions": random_actions,
    "invalid_inputs": invalid_inputs,
}
