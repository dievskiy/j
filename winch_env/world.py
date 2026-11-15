"""Winch yard: world generation.

A gantry hoist must deliver one crate to a raised platform. Three crates look the
same but differ in mass: one is too light to count as a delivery, one is too heavy
for the cable, and one is right. Which is which is hidden, and so is the stiffness
of the cable. Everything is a pure function of (seed, difficulty).
"""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass

import numpy as np

G = 9.81
RAIL_Z = 8.0                  # height of the trolley rail
CRATE_HALF = 0.5
PLATFORM = (8.0, 12.0, 2.0)   # x from, x to, top height
GOAL_X = 10.0
GOAL_HALF = 1.2               # the crate centre must come to rest within this of GOAL_X

# published hoist specification
SPEC = dict(
    cable_rated_tension_n=2000.0,   # the cable snaps above this
    required_payload_kg=100.0,      # a delivered crate must weigh at least this
    winch_max_speed=1.0,            # m/s
    winch_ramp=0.5,                 # m/s^2, how fast the drum changes speed
    trolley_max_speed=2.0,          # m/s
    trolley_ramp=1.0,               # m/s^2
    trolley_range=(-8.0, 12.0),
    cable_length_range=(0.5, 7.8),
    attach_radius=0.35,             # hook must be this close to a crate's lug to attach
    attach_time_s=1.0,              # hooking on or off takes this long
    drum_height=RAIL_Z - 0.15,      # the cable leaves the trolley at this height
    tension_sensor_max_offset_n=200.0,  # the tension sensor reads true tension + a constant offset
    cable_damping_ratio=0.08,       # of critical damping for a 100 kg load
    goal_rest_time_s=0.5,           # a delivered crate must sit still on the goal this long
    max_touchdown_speed=1.5,        # m/s; a crate that lands faster is destroyed
)

MASS_RANGES = {"light": (40.0, 75.0), "right": (110.0, 170.0), "heavy": (235.0, 300.0)}
STIFFNESS_RANGES = {"soft": (6000.0, 10000.0), "stiff": (30000.0, 50000.0)}   # N/m
ORDERS = ["".join(p) for p in itertools.permutations("LRH")]   # which crate is which
MODES = tuple(f"{order}_{cable}" for order in ORDERS for cable in STIFFNESS_RANGES)
_KIND = {"L": "light", "R": "right", "H": "heavy", "M": "medium"}
REFERENCE_MASS_KG = 90.0


@dataclass
class Scenario:
    seed: int
    difficulty: float
    mode: str
    crate_x: tuple            # x position of each crate on the yard floor
    crate_mass: tuple         # hidden
    cable_stiffness: float    # hidden, N/m
    sensor_offset: float      # hidden, N: constant error of the tension sensor
    time_s: float
    energy_j: float
    trolley_start_x: float = 0.0
    cable_start_length: float = 4.0
    variation: str | None = None
    platform: tuple = PLATFORM
    goal_x: float = GOAL_X
    goal_half: float = GOAL_HALF
    obstacle_height: float = 0.0
    task: str = "qualifying"
    window: tuple = (100.0, 200.0)
    sensor_gain: float = 1.0
    reference_index: int | None = None
    cable_strength_n: float = SPEC["cable_rated_tension_n"]   # hidden: the cable snaps above this
    creep_onset_n: float | None = None   # hidden: above this the cable lengthens permanently; None = never
    stuck_index: int | None = None       # hidden: crate held to the floor until pulled sideways


def _hidden_salt() -> int:
    """Hidden values come from a stream salted by WINCH_HIDDEN_SALT, so that knowing the
    source and the seed of an evaluation is not enough to reconstruct them. The default
    (0) keeps local runs reproducible; an evaluator sets its own private value."""
    return int(os.environ.get("WINCH_HIDDEN_SALT", "0"))


def mode_for_seed(seed: int) -> str:
    r = np.random.default_rng([int(seed), 8111, _hidden_salt()])
    return MODES[int(r.integers(len(MODES)))]


@dataclass(frozen=True)
class Variation:
    """A named yard. Geometry, task and budgets are public; masses and sensor
    calibration come from the salted hidden stream."""
    population: str           # weight band of each cargo crate: L light, R right, H heavy
    task: str = "qualifying"  # qualifying | window | heaviest | total
    platform: tuple = PLATFORM
    obstacle_height: float = 0.0
    reference_weight: bool = False
    worn_cable: bool = False      # the cable may be worn: true strength hidden, creep above a fraction of it
    stuck_crate: bool = False     # in half the episodes the right crate is stuck to the floor


VARIATIONS = {
    "short_pair": Variation("LR"),
    "high_stack": Variation("LRH", platform=(8., 12., 3.)),
    "left_bank": Variation("LRH", platform=(-8., -4., 2.)),
    "crowded": Variation("LLRH"),
    "five_way": Variation("LLRHH"),
    "barrier": Variation("LRH", obstacle_height=2.8),
    "weight_window": Variation("LRH", task="window"),
    "heaviest": Variation("LRH", task="heaviest"),
    "gain_reference": Variation("LRH", reference_weight=True),
    "total_payload": Variation("LRRH", task="total"),
    "worn_cable": Variation("LRMH", task="heaviest", worn_cable=True),
    "stuck_crate": Variation("LRH", stuck_crate=True),
}
WORN_STRENGTH_N = (1250.0, 1350.0)   # a worn cable's true strength, well below the rating
CREEP_ONSET_FRACTION = 0.85         # of true strength: above it the cable creeps
STUCK_RELEASE_SIDEWAYS_N = 60.0     # horizontal cable pull that frees a stuck crate
TOTAL_PAYLOAD_KG = 200.0      # the total task: the two right crates together, never one with a light one


def generate(seed: int, difficulty: float = 0.5, variation: str | None = None) -> Scenario:
    if not 0.0 <= difficulty <= 1.0:
        raise ValueError("difficulty must be in [0, 1]")
    if variation is not None and variation not in VARIATIONS:
        raise ValueError(f"unknown variation: {variation}")
    if variation is not None:
        return _generate_variation(int(seed), difficulty, variation)
    seed = int(seed)
    mode = mode_for_seed(seed)
    order, cable = mode.split("_")
    layout_rng = np.random.default_rng([seed, 31])                      # visible geometry
    hidden_rng = np.random.default_rng([seed, 37, _hidden_salt()])      # hidden values
    crate_x = tuple(float(x + layout_rng.uniform(-0.6, 0.6)) for x in (-6.0, -2.5, 1.0))
    crate_mass = tuple(float(hidden_rng.uniform(*MASS_RANGES[_KIND[k]])) for k in order)
    stiffness = float(hidden_rng.uniform(*STIFFNESS_RANGES[cable]))
    offset_limit = SPEC["tension_sensor_max_offset_n"]
    sensor_offset = float(hidden_rng.uniform(-offset_limit, offset_limit))
    # Enough time to weigh two crates and deliver one, not to haul a wrong crate first.
    return Scenario(seed=seed, difficulty=difficulty, mode=mode, crate_x=crate_x,
                    crate_mass=crate_mass, cable_stiffness=stiffness, sensor_offset=sensor_offset,
                    time_s=85.0 - 15.0 * difficulty, energy_j=30000.0 - 6000.0 * difficulty)


def _generate_variation(seed: int, difficulty: float, variation: str) -> Scenario:
    spec = VARIATIONS[variation]
    population, task, platform = spec.population, spec.task, spec.platform
    obstacle, reference = spec.obstacle_height, spec.reference_weight
    layout_rng = np.random.default_rng([seed, 31])
    hidden_rng = np.random.default_rng([seed, 37, _hidden_salt()])
    letters = list(population)
    hidden_rng.shuffle(letters)
    left = platform[0] < 0
    positions = ([-1., 2.5, 6., 9., 12.] if left else
                 [-6., -4., -2., 0., 2.])[:len(letters)]
    if reference:
        positions.append(-7.5)
    crate_x = tuple(float(x + layout_rng.uniform(-0.15, 0.15)) for x in positions)
    ranges = dict(MASS_RANGES)
    if task in ("window", "heaviest"):
        ranges = {"light": (45., 65.), "right": (110., 125.), "heavy": (155., 175.)}
    if spec.worn_cable:
        # medium lifts on an intact cable but snaps a worn one; right stays below a worn cable's creep onset
        ranges = {"light": (55., 75.), "right": (95., 105.), "medium": (145., 152.), "heavy": (240., 280.)}
    elif task == "total":
        ranges = {"light": (45., 65.), "right": (110., 125.), "heavy": MASS_RANGES["heavy"]}
    masses = tuple(float(hidden_rng.uniform(*ranges[_KIND[c]]))
                   for c in letters)
    if reference:
        masses += (REFERENCE_MASS_KG,)
    cable = "soft" if int(hidden_rng.integers(2)) == 0 else "stiff"
    goal_x = (platform[0] + platform[1]) / 2
    mode = f"{''.join(letters)}_{cable}"     # hidden regime: weight band of each crate, cable class
    strength, creep_onset = SPEC["cable_rated_tension_n"], None
    if spec.worn_cable:
        worn = int(hidden_rng.integers(2)) == 1
        strength = float(hidden_rng.uniform(*WORN_STRENGTH_N)) if worn else strength
        creep_onset = CREEP_ONSET_FRACTION * strength
        mode += "_worn" if worn else "_intact"
    stuck_index = None
    if spec.stuck_crate:
        stuck = int(hidden_rng.integers(2)) == 1
        stuck_index = letters.index("R") if stuck else None
        mode += "_stuck" if stuck else "_free"
    return Scenario(seed, difficulty, mode, crate_x, masses,
                    float(hidden_rng.uniform(*STIFFNESS_RANGES[cable])),
                    float(hidden_rng.uniform(-200., 200.)),
                    105. - 12. * difficulty + 13. * max(0, len(letters) - 3) + (30. if task == "heaviest" else 0.) + (50. if task == "total" else 0.) + (12. if reference else 0.) + (50. if spec.stuck_crate else 0.),
                    33000. - 3000. * difficulty + 9000. * max(0, len(letters) - 3),
                    variation=variation, platform=platform, goal_x=goal_x,
                    obstacle_height=obstacle, task=task, window=(105., 145.),
                    sensor_gain=float(hidden_rng.uniform(0.8, 1.2)) if reference else 1.,
                    reference_index=len(letters) if reference else None,
                    cable_strength_n=strength, creep_onset_n=creep_onset, stuck_index=stuck_index)


def split_seeds(n_per_split: int = 50, start: int = 0) -> dict:
    return {"train": list(range(start, start + n_per_split)),
            "heldout": list(range(start + n_per_split, start + 2 * n_per_split))}


def public_map(sc: Scenario) -> dict:
    """Static description given to the agent. Contains no hidden value."""
    if sc.variation is not None:
        return _variation_map(sc)
    return {
        "units": "metres, seconds, newtons, kilograms; x is along the rail, z is up",
        "rail_height": RAIL_Z,
        "crates": [{"name": f"crate_{i}", "x": round(x, 2), "size": 2 * CRATE_HALF,
                    "lug_height": 2 * CRATE_HALF,
                    "note": "mass unknown; all three look the same"}
                   for i, x in enumerate(sc.crate_x)],
        "platform": {"x": [PLATFORM[0], PLATFORM[1]], "top_height": PLATFORM[2]},
        "goal": {"x": GOAL_X, "half_width": GOAL_HALF, "height": PLATFORM[2],
                 "note": "one crate of at least the required payload must rest here, "
                         "released from the hook and not destroyed"},
        "hoist": dict(SPEC, note=(
            "The cable is elastic with unknown stiffness k. Its tension is "
            "k * stretch + c * stretch_rate, never negative and zero when slack, with "
            "c = 2 * cable_damping_ratio * sqrt(k * 100 kg). Cable length is measured from "
            "the drum (at drum_height) to the hook with no stretch. The winch is a speed "
            "source: it reels at the commanded speed whatever the tension, so tension can "
            "exceed the rating and snap the cable, most easily when slack is taken up at "
            "speed or when a crate too heavy for the cable is pulled. "
            "The tension sensor reads true tension plus a constant unknown offset of at "
            "most tension_sensor_max_offset_n either way, plus noise; every tension you "
            "see, and stop_tension, use that reading. stop_tension is a trigger, not a "
            "cap: when the reading reaches it the drum brakes at winch_ramp, and tension "
            "keeps rising while it slows. "
            "A command that ends on max_duration leaves the trolley and drum moving at "
            "their current speeds; the next command (wait included) ramps them from there. "
            "Exactly one crate is both heavy enough to count and light enough to lift. A "
            "hanging crate swings when the trolley speeds up or slows down; the swing dies "
            "down over several seconds. Hooking on or off takes attach_time_s.")),
        "start": {"trolley_x": sc.trolley_start_x, "cable_length": sc.cable_start_length},
        "sensor_noise_std": {"tension_n": 10.0, "position_m": 0.01},
        "budgets": {"time_s": sc.time_s, "energy_j": sc.energy_j},
    }


def _variation_map(sc: Scenario) -> dict:
    # Reuse the published cable law and tool descriptions of the original yard.
    result = public_map(Scenario(sc.seed, sc.difficulty, sc.mode, sc.crate_x,
                                 sc.crate_mass, sc.cable_stiffness, sc.sensor_offset,
                                 sc.time_s, sc.energy_j))
    result["crates"] = [_variation_crate(sc, i, x) for i, x in enumerate(sc.crate_x)]
    result["platform"] = {"x": list(sc.platform[:2]), "top_height": sc.platform[2]}
    result["goal"] = {"x": sc.goal_x, "half_width": sc.goal_half,
                      "height": sc.platform[2], "note": "release cargo upright and still on the platform"}
    result["obstacle"] = {"x": 4., "top_height": sc.obstacle_height} if sc.obstacle_height else None
    result["task"] = {"type": sc.task, "weight_window_kg": list(sc.window) if sc.task == "window" else None,
                      "note": {"qualifying": "Exactly one cargo crate meets the 100 kg minimum and can be lifted safely.",
                               "window": "Deliver the only cargo crate in the inclusive weight window; all cargo can be lifted.",
                               "heaviest": "Deliver the heaviest cargo crate; all cargo can be lifted.",
                               "total": f"Deliver cargo crates whose masses add up to at least {TOTAL_PAYLOAD_KG:g} kg; "
                                        "every crate on the goal counts, and some cargo may be too heavy to lift."}[sc.task]}
    if sc.task == "total":
        result["task"]["total_payload_kg"] = TOTAL_PAYLOAD_KG
    if VARIATIONS[sc.variation].stuck_crate:
        result["hoist"]["stuck_release_sideways_n"] = STUCK_RELEASE_SIDEWAYS_N
        result["hoist"]["note"] += (
            " A crate may be stuck to the floor. A stuck crate cannot be lifted, whatever its "
            "weight, until the cable pulls it sideways with at least stuck_release_sideways_n "
            "of horizontal force; that frees it for good.")
    if sc.creep_onset_n is not None:
        result["task"]["note"] = "Deliver the heaviest cargo crate this cable can lift; some cargo may be too heavy for it."
        result["hoist"]["cable_condition"] = "possibly worn"
        result["hoist"]["creep_onset_fraction"] = CREEP_ONSET_FRACTION
        result["hoist"]["note"] += (
            " This cable has been in service and may be worn: a worn cable's true strength is "
            "well below cable_rated_tension_n, and it snaps above its true strength. Any cable "
            "creeps, stretching permanently, while tension exceeds creep_onset_fraction of its "
            "true strength, faster the larger the excess; creep lengthens the cable, so a held "
            "load's tension relaxes towards the onset.")
    if sc.task != "qualifying":
        result["hoist"]["note"] = result["hoist"]["note"].replace(
            "Exactly one crate is both heavy enough to count and light enough to lift. ", "")
    if sc.reference_index is not None:
        result["hoist"]["note"] = result["hoist"]["note"].replace(
            "The tension sensor reads true tension plus a constant unknown offset of at ",
            "The tension sensor reads an unknown gain times true tension plus a constant unknown offset of at ")
    if sc.obstacle_height:
        result["hoist"]["note"] += " The obstacle is solid; a load that hits it is stopped by it."
    result["hoist"]["sensor_gain"] = "unknown" if sc.reference_index is not None else 1.0
    result["budgets"] = {"time_s": sc.time_s, "energy_j": sc.energy_j}
    return result


def _variation_crate(sc: Scenario, index: int, x: float) -> dict:
    """Public entry for one crate. The reference weight is marked by a structured field."""
    crate = {"name": f"crate_{index}", "x": round(x, 2), "size": 2 * CRATE_HALF,
             "lug_height": 2 * CRATE_HALF, "cargo": index != sc.reference_index}
    if crate["cargo"]:
        crate["note"] = "mass unknown; all cargo crates look the same"
    else:
        crate["known_mass_kg"] = REFERENCE_MASS_KG
        crate["note"] = "reference weight of known mass; not cargo and never counts as a delivery"
    return crate


def build_mjcf(sc: Scenario) -> str:
    px0, px1, ptop = sc.platform
    crates = "".join(
        f'<body name="crate_{i}" pos="{x:.4f} 0 {CRATE_HALF + 0.002}"><freejoint/>'
        f'<geom name="crate_{i}" type="box" size="{CRATE_HALF} {CRATE_HALF} {CRATE_HALF}" '
        f'mass="{mass:.3f}" rgba="0.62 0.45 0.25 1" friction="0.8 0.005 0.0001"/>'
        f'<site name="lug_{i}" pos="0 0 {CRATE_HALF}" size="0.06" rgba="0.9 0.9 0.2 1"/></body>'
        for i, (x, mass) in enumerate(zip(sc.crate_x, sc.crate_mass)))
    cables = '<spatial name="cable_free" width="0.02" rgba="0.1 0.1 0.1 1">' \
             '<site site="drum"/><site site="hook"/></spatial>' + "".join(
        f'<spatial name="cable_{i}" width="0.02" rgba="0.1 0.1 0.1 0">'
        f'<site site="drum"/><site site="lug_{i}"/></spatial>' for i in range(len(sc.crate_x)))
    return f"""
<mujoco model="winch_yard">
  <option timestep="0.002" integrator="implicitfast" gravity="0 0 -{G}"/>
  <visual><headlight ambient="0.4 0.4 0.4" diffuse="0.6 0.6 0.6"/>
          <global offwidth="960" offheight="720"/></visual>
  <worldbody>
    <light pos="2 -8 14" dir="0 0.5 -1" diffuse="0.7 0.7 0.7"/>
    <geom name="floor" type="plane" size="40 40 1" rgba="0.35 0.37 0.4 1" friction="0.8 0.005 0.0001"/>
    <geom name="platform" type="box" pos="{(px0 + px1) / 2} 0 {ptop / 2}"
          size="{(px1 - px0) / 2} 2 {ptop / 2}" rgba="0.5 0.5 0.55 1" friction="0.8 0.005 0.0001"/>
    <geom name="goal_marker" type="box" pos="{sc.goal_x} 0 {ptop + 0.003}" size="{sc.goal_half} 1.2 0.003"
          rgba="0.1 0.85 0.2 0.6" contype="0" conaffinity="0"/>
    {f'<geom name="obstacle" type="box" pos="4 0 {sc.obstacle_height / 2}" size="0.2 2 {sc.obstacle_height / 2}" rgba="0.3 0.3 0.4 1"/>' if sc.obstacle_height else ''}
    <geom name="rail" type="box" pos="2 0 {RAIL_Z + 0.25}" size="11 0.15 0.12" rgba="0.75 0.6 0.1 1"
          contype="0" conaffinity="0"/>
    <geom name="post_a" type="box" pos="-9 0 {RAIL_Z / 2}" size="0.15 0.15 {RAIL_Z / 2}" rgba="0.75 0.6 0.1 1"
          contype="0" conaffinity="0"/>
    <geom name="post_b" type="box" pos="13 0 {RAIL_Z / 2}" size="0.15 0.15 {RAIL_Z / 2}" rgba="0.75 0.6 0.1 1"
          contype="0" conaffinity="0"/>
    <body name="trolley" mocap="true" pos="{sc.trolley_start_x} 0 {RAIL_Z}">
      <geom type="box" size="0.4 0.3 0.15" rgba="0.8 0.2 0.2 1" contype="0" conaffinity="0"/>
      <site name="drum" pos="0 0 -0.15" size="0.05"/>
    </body>
    <body name="hook" mocap="true" pos="{sc.trolley_start_x} 0 {RAIL_Z - sc.cable_start_length}">
      <geom type="sphere" size="0.1" rgba="0.2 0.2 0.2 1" contype="0" conaffinity="0"/>
      <site name="hook" pos="0 0 0" size="0.05"/>
    </body>
    {crates}
  </worldbody>
  <tendon>{cables}</tendon>
</mujoco>
"""
