"""Scripted policies for the winch yard. Each sees only the agent tools."""
from __future__ import annotations

import math
import random
import statistics as stats

G = 9.81
STOP_FRACTION = 0.90     # tension stop as a fraction of the rating: above any liftable crate, below the limit
BRAKING_OVERSHOOT_N = 40.0  # tension the reference allows to build while the drum brakes
WORN_SAFE_STOP_N = 1200.0  # below a worn cable's strength even with braking overshoot
LIFT_OFF_HEIGHT_M = 0.03   # a weighed crate rises about 0.08 m; position noise is 0.01 m
CREEP_DETECTION_MARGIN_N = 25.0  # settled tension this far below the stop means creep
TUG_OFFSET_M = 0.8         # trolley offset for a sideways tug
TUG_TENSION_N = 900.0      # below any right crate's weight: about 100 N sideways at TUG_OFFSET_M
TOTAL_SLOT_OFFSET = 0.65   # m either side of the goal centre: two 1 m crates with a 0.3 m gap


class ToolProxy:
    """Exposes only the agent tool surface of an Episode."""
    __slots__ = ("_tools",)

    def __init__(self, episode):
        object.__setattr__(self, "_tools", {name: getattr(episode, name) for name in episode.TOOLS})

    def __getattr__(self, name):
        try:
            return self._tools[name]
        except KeyError:
            raise AttributeError(name)


# ----------------------------------------------------------------- shared steps
def _hook_onto(env, m, crate: dict) -> bool:
    """Put the hook on a crate's lug and attach."""
    env.move_trolley(crate["x"], m["hoist"]["trolley_max_speed"], 30.0)
    o = env.observe()
    drop = o["hook"]["height"] - crate["lug_height"]
    env.winch(drop, m["hoist"]["winch_max_speed"], 30.0)
    return env.attach()["termination"] == "attached"


def _let_go(env, slack: float):
    """Pay out until the cable is slack, then unhook."""
    env.winch(slack, 0.3, 20.0)
    env.release()


def _wait_for_swing_to_settle(env, limit_s: float = 12.0):
    """Wait until the hook hangs steadily under the trolley."""
    for _ in range(int(limit_s)):
        env.wait(1.0)
        trace = env.observe()["last_command"]["trace"]
        offsets = [s["hook_x"] - s["trolley_x"] for s in trace]
        if max(offsets) - min(offsets) < 0.12 and abs(offsets[-1]) < 0.15:
            return


def _carry_to_goal(env, m):
    """Set the hooked crate down on the goal, then finish."""
    _set_down(env, m, m["goal"]["x"])
    return env.finish()


def _set_down(env, m, x: float) -> bool:
    """Raise the hooked crate clear of the platform, traverse to `x`, set it down on the
    platform and unhook. Returns False if no crate was hooked."""
    hoist, goal = m["hoist"], m["goal"]
    o = env.observe()
    if o["attached"] is None:
        return False
    crate = o["crates"][o["attached"]]
    clearance = max(goal["height"], (m.get("obstacle") or {}).get("top_height", 0)) + 0.7 - crate["height"]
    env.winch(-clearance, hoist["winch_max_speed"], 30.0)
    direction = 1 if x > o["hook"]["x"] else -1
    env.move_trolley(x - direction * 3.0, hoist["trolley_max_speed"], 30.0)
    env.move_trolley(x, 0.7, 30.0)                        # arrive gently to limit the swing
    _wait_for_swing_to_settle(env)
    o = env.observe()
    if o["attached"] is None:
        return False
    lower = o["crates"][o["attached"]]["height"] - goal["height"]
    env.winch(lower + 0.02, 0.4, 20.0)
    env.winch(0.5, 0.3, 20.0)                             # slack off completely
    env.release()
    env.wait(1.0)                                         # let it sit still on the goal
    return True


# ----------------------------------------------------------------- reference: weigh, then choose
def read_sensor_offset(env) -> float:
    """With the cable slack the true tension is zero, so the reading is the offset."""
    env.wait(0.5)
    return stats.median(s["tension"] for s in env.observe()["last_command"]["trace"])


def estimate_stiffness(env) -> float:
    """Reel in one centimetre on a hooked crate and read how much the tension rises."""
    before = env.observe()["tension"]
    env.winch(-0.01, 0.02, 5.0)
    trace = env.observe()["last_command"]["trace"]
    after = stats.median(s["tension"] for s in trace[-4:])
    return max((after - before) / 0.01, 1000.0)


def weigh(env, m, stiffness: float, offset: float, gain: float = 1.0,
          stop: float | None = None) -> float | None:
    """Take up the load slowly with a tension stop (true tension, newtons). Returns the
    crate's mass, or None if the stop tripped before the crate left the ground."""
    hoist = m["hoist"]
    if stop is None:
        stop = (0.96 if m.get("task", {}).get("type") in ("heaviest", "window") else STOP_FRACTION) * hoist["cable_rated_tension_n"]
    # slow enough that braking the drum after the stop trips adds little tension
    speed = min(0.3, math.sqrt(2.0 * hoist["winch_ramp"] * BRAKING_OVERSHOOT_N / stiffness))
    take_up = stop / stiffness + 0.08
    result = env.winch(-take_up, speed, 60.0, stop_tension=stop * gain + offset)
    if result["termination"] != "done":
        return None
    env.wait(0.6)
    trace = env.observe()["last_command"]["trace"]
    return (stats.median(s["tension"] for s in trace) - offset) / (G * gain)


def reference(env):
    m = env.observe()["map"]
    if "task" in m:
        return variation_reference(env, m)
    """Read the tension sensor's offset, then weigh crates, nearest to the platform first,
    until one is both liftable and heavy enough. If the first two are ruled out the
    third is carried on the map's word that exactly one qualifies, but still taken up
    with the same slow, tension-limited pull."""
    m = env.observe()["map"]
    required = m["hoist"]["required_payload_kg"]
    offset = read_sensor_offset(env)
    crates = sorted(m["crates"], key=lambda c: -c["x"])
    stiffness = None
    for index, crate in enumerate(crates):
        if not _hook_onto(env, m, crate):
            continue
        if stiffness is None:
            stiffness = estimate_stiffness(env)
        mass = weigh(env, m, stiffness, offset)
        slack = STOP_FRACTION * m["hoist"]["cable_rated_tension_n"] / stiffness + 0.15
        last = index == len(crates) - 1
        if mass is not None and (mass >= required or last):
            return _carry_to_goal(env, m)
        if last:
            break
        _let_go(env, slack)
    return env.finish()


def variation_reference(env, m):
    """Calibrate any reference load, weigh candidates and select according to the public task."""
    offset = read_sensor_offset(env)
    gain = 1.0
    stiffness = None
    reference_crates = [c for c in m["crates"] if not c.get("cargo", True)]
    if reference_crates:
        if not _hook_onto(env, m, reference_crates[0]):
            return env.finish()
        stiffness = estimate_stiffness(env)
        # 90 kg reference is safely below the cable rating even at full sensor gain.
        env.winch(-0.35, 0.04, 30.0)
        env.wait(0.7)
        gain = (stats.median(s["tension"] for s in env.observe()["last_command"]["trace"])
                - offset) / (reference_crates[0]["known_mass_kg"] * G)
        _let_go(env, 0.6)
    crates = [c for c in m["crates"] if c not in reference_crates]
    crates.sort(key=lambda c: abs(c["x"] - m["goal"]["x"]))
    task = m["task"]["type"]
    if m["hoist"].get("cable_condition") == "possibly worn":
        return _deliver_heaviest_on_possibly_worn_cable(env, m, crates, offset)
    if task == "total":
        return _deliver_total(env, m, crates, stiffness, offset, gain)
    best = None
    too_heavy = []
    for crate in crates:
        if not _hook_onto(env, m, crate):
            continue
        if stiffness is None:
            stiffness = estimate_stiffness(env) / gain
        mass = weigh(env, m, stiffness, offset, gain)
        if mass is None:
            too_heavy.append(crate)
        if task == "heaviest":
            if mass is not None and (best is None or mass > best[0]):
                best = (mass, crate)
        elif mass is not None and (task == "qualifying" and mass >= m["hoist"]["required_payload_kg"]
                                   or task == "window" and
                                   m["task"]["weight_window_kg"][0] <= mass <= m["task"]["weight_window_kg"][1]):
            return _carry_to_goal(env, m)
        _let_go(env, STOP_FRACTION * m["hoist"]["cable_rated_tension_n"] / stiffness + 0.15)
    if "stuck_release_sideways_n" in m["hoist"]:
        # a crate that would not lift may be stuck rather than heavy: tug it, weigh again
        for crate in too_heavy:
            _tug_sideways(env, m, crate, offset)
            if not _hook_onto(env, m, crate):
                continue
            mass = weigh(env, m, stiffness, offset, gain)
            if mass is not None and mass >= m["hoist"]["required_payload_kg"]:
                return _carry_to_goal(env, m)
            _let_go(env, STOP_FRACTION * m["hoist"]["cable_rated_tension_n"] / stiffness + 0.15)
    if best is not None and _hook_onto(env, m, best[1]):
        # Staging a weighed load does not count as delivery; lift it again.
        if weigh(env, m, stiffness, offset, gain) is not None:
            return _carry_to_goal(env, m)
    return env.finish()


def _deliver_heaviest_on_possibly_worn_cable(env, m, crates, offset):
    """Weigh every crate with a stop safe even on a worn cable. The first crate that does
    not lift doubles as a proof pull: if the held tension relaxes clearly below the stop,
    the cable crept, so it is worn. On an intact cable, weigh the crates that did not lift
    again with a stop just below an intact cable's creep onset. Deliver the heaviest that
    lifted."""
    intact_stop = (m["hoist"]["creep_onset_fraction"] * m["hoist"]["cable_rated_tension_n"]
                   - 2 * BRAKING_OVERSHOOT_N)
    stiffness, worn = None, None
    lifted, too_heavy = [], []
    for crate in crates:
        if not _hook_onto(env, m, crate):
            continue
        if stiffness is None:
            stiffness = estimate_stiffness(env)
        mass = weigh(env, m, stiffness, offset, stop=WORN_SAFE_STOP_N)
        if mass is not None and not _left_ground(env, crate):
            # the drum reached its target without lifting: the cable crept as fast as it reeled
            mass, worn = None, True
        if mass is None:
            too_heavy.append(crate)
            if worn is None:
                worn = _held_tension_relaxed(env, offset)
        else:
            lifted.append((mass, crate))
        _let_go(env, intact_stop / stiffness + 0.15)
    if worn is False:
        for crate in too_heavy:
            if _hook_onto(env, m, crate):
                mass = weigh(env, m, stiffness, offset, stop=intact_stop)
                if mass is not None:
                    lifted.append((mass, crate))
                _let_go(env, intact_stop / stiffness + 0.15)
    if not lifted:
        return env.finish()
    mass, crate = max(lifted, key=lambda pair: pair[0])
    stop = WORN_SAFE_STOP_N if worn else intact_stop
    if _hook_onto(env, m, crate) and weigh(env, m, stiffness, offset, stop=stop) is not None:
        return _carry_to_goal(env, m)
    return env.finish()


def _tug_sideways(env, m, crate, offset: float):
    """Pull a crate sideways without lifting it: hook on, slacken, move the trolley to
    one side, then reel in to a tension stop, so the horizontal pull does not depend on
    the cable's stiffness. Ends unhooked."""
    if not _hook_onto(env, m, crate):
        return
    env.winch(0.5, 0.3, 10.0)
    side = 1 if crate["x"] + TUG_OFFSET_M <= m["hoist"]["trolley_range"][1] else -1
    env.move_trolley(crate["x"] + side * TUG_OFFSET_M, 0.5, 20.0)
    env.winch(-1.5, 0.05, 60.0, stop_tension=TUG_TENSION_N + offset)
    env.winch(0.5, 0.3, 10.0)
    env.release()


def _left_ground(env, crate) -> bool:
    """Whether the hooked crate has risen clear of where it rests."""
    return env.observe()["crates"][crate["name"]]["height"] > LIFT_OFF_HEIGHT_M


def _held_tension_relaxed(env, offset: float) -> bool:
    """After a tension stop on a load that did not lift, hold and see whether the
    tension settles clearly below the stop: a creeping cable relaxes to its onset."""
    env.wait(1.5)
    trace = env.observe()["last_command"]["trace"]
    settled = stats.median(sample["tension"] for sample in trace[-5:]) - offset
    return settled < WORN_SAFE_STOP_N - CREEP_DETECTION_MARGIN_N


def _deliver_total(env, m, crates, stiffness, offset, gain):
    """Weigh crates nearest first and deliver each liftable one that carries at least its
    share of the remaining requirement over the free goal slots, until the total is
    reached."""
    remaining = m["task"]["total_payload_kg"]
    slots = _goal_slots(m)
    for crate in crates:
        if remaining <= 0 or not slots or not _hook_onto(env, m, crate):
            break
        if stiffness is None:
            stiffness = estimate_stiffness(env) / gain
        mass = weigh(env, m, stiffness, offset, gain)
        if mass is not None and mass * len(slots) >= remaining:
            if _set_down(env, m, slots.pop(0)):
                remaining -= mass
            continue
        _let_go(env, STOP_FRACTION * m["hoist"]["cable_rated_tension_n"] / stiffness + 0.15)
    return env.finish()


# ----------------------------------------------------------------- non-weighing plans
def _gamble(position: int, careful: bool):
    """Take one crate without weighing it. `careful` takes the load up slowly with a
    tension stop (so a heavy crate is refused); otherwise it is hauled at full speed."""
    def policy(env):
        m = env.observe()["map"]
        hoist = m["hoist"]
        crates = [c for c in m["crates"] if c.get("cargo", True)]
        crate = sorted(crates, key=lambda c: abs(c["x"] - m["goal"]["x"]))[position % len(crates)]
        if not _hook_onto(env, m, crate):
            return env.finish()
        if careful:
            result = env.winch(-0.45, 0.04, 60.0, stop_tension=STOP_FRACTION * hoist["cable_rated_tension_n"])
            if result["termination"] != "done":
                return env.finish()
        return _carry_to_goal(env, m)
    return policy


def first_that_lifts(env):
    """Adapts without weighing: carry off the first crate the cable can lift, nearest
    first, ignoring the payload requirement. On the total task, fill both goal slots."""
    m = env.observe()["map"]
    hoist = m["hoist"]
    slots = _goal_slots(m)
    for crate in sorted((c for c in m["crates"] if c.get("cargo", True)),
                        key=lambda c: abs(c["x"] - m["goal"]["x"])):
        if not _hook_onto(env, m, crate):
            continue
        result = env.winch(-0.45, 0.04, 60.0, stop_tension=STOP_FRACTION * hoist["cable_rated_tension_n"])
        if result["termination"] == "done":
            if not _set_down(env, m, slots.pop(0)) or not slots:
                return env.finish()
            continue
        _let_go(env, 0.6)
    return env.finish()


def _goal_slots(m) -> list:
    """Where to set crates down: the goal centre, or on the total task two slots, far
    side first, so the second crate never passes over the first."""
    goal_x = m["goal"]["x"]
    if m.get("task", {}).get("type") != "total":
        return [goal_x]
    side = 1 if goal_x > m["crates"][0]["x"] else -1
    return [goal_x + side * TOTAL_SLOT_OFFSET, goal_x - side * TOTAL_SLOT_OFFSET]


# ----------------------------------------------------------------- integrity baselines
def do_nothing(env):
    return None


def immediate_finish(env):
    return env.finish()


def wait_spam(env):
    for _ in range(40):
        env.wait(5.0)
    return env.finish()


def random_actions(env):
    rng = random.Random(0)
    for _ in range(40):
        choice = rng.random()
        if choice < 0.35:
            env.move_trolley(rng.uniform(-8, 12), rng.uniform(0.2, 2.0), rng.uniform(0.5, 5))
        elif choice < 0.7:
            env.winch(rng.uniform(-3, 3), rng.uniform(0.05, 1.0), rng.uniform(0.5, 5))
        elif choice < 0.85:
            env.attach()
        else:
            env.release()
    return env.finish()


def invalid_inputs(env):
    for bad in (float("nan"), float("inf"), -1e9, 1e9, "x", None, True):
        env.move_trolley(bad, 1.0, 5.0)
        env.winch(bad, 0.5, 5.0)
        env.winch(-1.0, bad, 5.0)
        env.wait(bad)
    return env.finish()


def drop_on_goal(env):
    """Tries to score by dropping a crate onto the goal from height."""
    m = env.observe()["map"]
    crate = sorted((c for c in m["crates"] if c.get("cargo", True)),
                   key=lambda c: abs(c["x"] - m["goal"]["x"]))[0]
    if _hook_onto(env, m, crate):
        env.winch(-5.0, 1.0, 30.0)
        env.move_trolley(m["goal"]["x"], 2.0, 30.0)
        env.release()
        env.wait(3.0)
    return env.finish()


POLICIES = {
    "reference": reference,
    "nearest_careful": _gamble(0, True),
    "middle_careful": _gamble(1, True),
    "farthest_careful": _gamble(2, True),
    "nearest_fast": _gamble(0, False),
    "first_that_lifts": first_that_lifts,
    "do_nothing": do_nothing,
    "immediate_finish": immediate_finish,
    "wait_spam": wait_spam,
    "random_actions": random_actions,
    "invalid_inputs": invalid_inputs,
    "drop_on_goal": drop_on_goal,
}
DIAGNOSING = ("reference",)
