"""Procedural world generation: layout, hidden dynamics mode, MJCF model.

Everything here is a pure function of (seed, difficulty). The hidden part of
the scenario (`HiddenDynamics`) is never exposed through the agent tools.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np

G = 9.81

# Nominal vehicle spec (published to the agent).
NOMINAL = dict(
    mass_kg=110.0,            # rover + cargo
    max_speed=5.0,            # m/s
    max_drive_accel=2.5,      # m/s^2, motor-limited on flat ground
    max_brake_decel=4.5,      # m/s^2, brake-limited on flat ground
    tire_friction=0.9,        # nominal tire/ground friction coefficient
    planned_decel=1.5,        # m/s^2, deceleration the drive_to controller plans with
    steering_bias=0.0,        # 1/m, yaw-rate offset per m/s of speed
    max_turn_rate=1.0,        # rad/s
)

MODES = ("nominal", "traction", "steering", "braking",
         "traction+steering", "braking+steering", "traction+braking")
TRAIN_MODES = ("nominal", "traction", "steering")
HELDOUT_MODES = ("braking", "traction+steering", "braking+steering", "traction+braking")


@dataclass
class HiddenDynamics:
    mode: str
    tire_friction: float
    brake_decel: float
    steering_bias: float   # 1/m (yaw-rate offset = bias * forward speed)
    mud_drag: float = 0.0  # 1/s, viscous deceleration per m/s of speed on mud surfaces
    wind_accel: float = 0.0  # m/s^2, sideways acceleration on wind-exposed surfaces
    ice_friction: float = NOMINAL["tire_friction"]  # friction coefficient on ice surfaces


class CourseLayout:
    """What Episode and Recorder need from any course. Subclasses must provide `start`,
    `goal`, `goal_radius`, `bounds`, `mjcf()`, `public_map()` and `overview_camera`;
    the members below are optional features with neutral defaults."""

    barriers: tuple = ()        # (x, y) centres of obstacles that are NOT on the map
    lookout: tuple | None = None  # (x, y, radius): at rest inside it, every barrier is detected
    wind_direction: tuple = (0.0, 0.0)  # unit vector of the wind acting on "wind" surfaces
    crate_bodies: tuple = ()    # names of pushable crate bodies in the MJCF

    def surface_at(self, x: float, y: float) -> str:
        return "paved"


@dataclass
class Layout(CourseLayout):
    H: float                 # plateau height
    xe: float                # plateau east edge (top of short ramp)
    ys: float                # lateral position of short ramp
    short_slope_deg: float
    short_width: float
    pad_len: float           # length of the landing pad (in x) before the ditch
    xl: float                # x centre of long (gentle) ramp
    ysouth: float            # plateau south edge (|y|)
    long_slope_deg: float
    long_width: float
    road_width: float
    calib: tuple             # (xmin, xmax, ymin, ymax)
    start: tuple             # (x, y, yaw)
    goal_radius: float
    # derived
    short_len: float = 0.0
    long_len: float = 0.0
    x0: float = 0.0          # x of ramp bottom / road strip west edge
    goal: tuple = (0.0, 0.0)
    y_road: float = 0.0      # y centre of the south road
    bounds: tuple = (0, 0, 0, 0)

    def derive(self):
        self.short_len = self.H / math.tan(math.radians(self.short_slope_deg))
        self.long_len = self.H / math.tan(math.radians(self.long_slope_deg))
        self.x0 = self.xe + self.short_len
        self.goal = (self.x0 + 0.5 * self.pad_len, self.ys)
        self.y_road = -self.ysouth - self.long_len - 0.5 * self.road_width
        self.bounds = (-15.0, self.x0 + self.pad_len + 12.0,
                       self.y_road - self.road_width - 12.0, 20.0)
        return self

    # --- course interface used by Episode and Recorder
    def mjcf(self) -> str:
        return build_mjcf(self)

    def public_map(self) -> dict:
        return public_map(self)

    @property
    def overview_camera(self) -> dict:
        return {"lookat": ((self.x0 + self.xe) / 2 - 4, (self.y_road + 4) / 2, 0.0),
                "distance": 75.0, "elevation": -55.0, "azimuth": 120.0}


@dataclass
class Budgets:
    time_s: float
    energy_j: float


@dataclass
class Scenario:
    seed: int
    difficulty: float
    layout: object           # Layout or SerpentineLayout (same course interface)
    hidden: HiddenDynamics
    budgets: Budgets
    course: str = "ramp"


def _mode_for_seed(seed: int) -> str:
    # mode is drawn from a dedicated stream so the split is cheap to compute
    r = np.random.default_rng([seed, 7919])
    return MODES[int(r.integers(len(MODES)))]


def course_names() -> tuple:
    """Every course that generate() accepts."""
    from .fork import WORLDS
    return ("ramp", "serpentine") + tuple(WORLDS)


def generate(seed: int, difficulty: float = 0.5, course: str = "ramp") -> Scenario:
    if not (0.0 <= difficulty <= 1.0):
        raise ValueError("difficulty must be in [0, 1]")
    seed = int(seed)
    if course == "serpentine":
        from .serpentine import generate_serpentine
        return generate_serpentine(seed, difficulty)
    if course.startswith("fork_"):
        from .fork import generate_fork
        return generate_fork(course, seed, difficulty)
    if course != "ramp":
        raise ValueError(f"unknown course {course!r}")
    rng = np.random.default_rng([seed, 1])
    d = difficulty
    lay = Layout(
        H=float(rng.uniform(2.8, 3.3)),
        xe=float(rng.uniform(16.0, 20.0)),
        ys=float(rng.uniform(-2.0, 2.0)),
        short_slope_deg=float(rng.uniform(15.5, 17.5) + 1.5 * d),
        short_width=float(rng.uniform(2.9, 3.4) - 0.5 * d),
        pad_len=float(rng.uniform(5.0, 6.0) - 0.8 * d),
        xl=0.0,
        ysouth=float(rng.uniform(8.0, 10.0)),
        long_slope_deg=4.5,
        long_width=5.0,
        road_width=8.0,
        calib=(-6.0, 8.0, -6.0, 6.0),
        start=(0.0, 0.0, 0.0),
        goal_radius=1.5,
    )
    lay.xl = float(lay.xe - rng.uniform(4.0, 8.0))
    lay.derive()

    mode = _mode_for_seed(seed)
    hr = np.random.default_rng([seed, 2])
    mu = NOMINAL["tire_friction"]
    brake = NOMINAL["max_brake_decel"]
    bias = 0.0
    if "traction" in mode:
        # severe end (low mu) makes the short ramp impossible
        mu = float(hr.uniform(0.11, 0.36))
    if "braking" in mode:
        brake = float(hr.uniform(1.2, 3.3))
    if "steering" in mode:
        bias = float(hr.choice([-1.0, 1.0]) * hr.uniform(0.05, 0.14 + 0.04 * d))
    hidden = HiddenDynamics(mode=mode, tire_friction=mu, brake_decel=brake,
                            steering_bias=bias)
    budgets = Budgets(time_s=110.0 - 20.0 * d, energy_j=13000.0 - 2000.0 * d)
    return Scenario(seed=seed, difficulty=d, layout=lay, hidden=hidden, budgets=budgets)


def split_seeds(n_per_split: int = 50, start: int = 0) -> dict:
    """Return {'train': [...], 'heldout': [...]} seed lists.

    train   = nominal, degraded traction, steering bias
    heldout = degraded braking and all two-fault combinations
    """
    out = {"train": [], "heldout": []}
    s = start
    while len(out["train"]) < n_per_split or len(out["heldout"]) < n_per_split:
        m = _mode_for_seed(s)
        key = "train" if m in TRAIN_MODES else "heldout"
        if len(out[key]) < n_per_split:
            out[key].append(s)
        s += 1
    return out


def public_map(lay: Layout) -> dict:
    """Static map of known geometry, as given to the agent."""
    def r(v):
        return round(float(v), 3)
    xe, H, ys = lay.xe, lay.H, lay.ys
    x0, P = lay.x0, lay.pad_len
    yS = -lay.ysouth
    yb = yS - lay.long_len
    road_s = (yb - lay.road_width, yb)
    return {
        "units": "metres, radians; z is up; heading 0 = +x",
        "world_bounds": {"xmin": r(lay.bounds[0]), "xmax": r(lay.bounds[1]),
                         "ymin": r(lay.bounds[2]), "ymax": r(lay.bounds[3])},
        "drivable_surfaces": [
            {"name": "upper_plateau", "type": "flat", "z": r(H),
             "x": [-12.0, r(xe)], "y": [r(yS), 12.0]},
            {"name": "short_ramp", "type": "slope_down_+x", "x": [r(xe), r(x0)],
             "y": [r(ys - lay.short_width / 2), r(ys + lay.short_width / 2)],
             "z_top": r(H), "z_bottom": 0.0, "slope_deg": r(lay.short_slope_deg)},
            {"name": "long_ramp", "type": "slope_down_-y",
             "x": [r(lay.xl - lay.long_width / 2), r(lay.xl + lay.long_width / 2)],
             "y": [r(yb), r(yS)], "z_top": r(H), "z_bottom": 0.0,
             "slope_deg": r(lay.long_slope_deg)},
            {"name": "south_road", "type": "flat", "z": 0.0,
             "x": [r(lay.xl - lay.long_width / 2), r(x0 + P)],
             "y": [r(road_s[0]), r(road_s[1])]},
            {"name": "east_road_and_landing_pad", "type": "flat", "z": 0.0,
             "x": [r(x0), r(x0 + P)], "y": [r(road_s[0]), r(ys + 3.0)]},
        ],
        "hazards": "Everything outside the drivable surfaces is a drop of several metres "
                   "(the ramp sides, the plateau edges, and the ditch east and north of the "
                   "landing pad). Leaving a drivable surface destroys the cargo.",
        "calibration_area": {"x": list(lay.calib[:2]), "y": list(lay.calib[2:]),
                             "note": "flat, safe area on the plateau for test manoeuvres"},
        "start": {"x": lay.start[0], "y": lay.start[1], "heading": lay.start[2]},
        "goal": {"x": r(lay.goal[0]), "y": r(lay.goal[1]), "radius": lay.goal_radius,
                 "note": "the CARGO must come to rest inside this circle, not destroyed; cargo damage lowers the score"},
        "drive_to_controller": DRIVE_TO_CONTROLLER,
        "routes": {
            "short": [[r(xe - 2.0), r(ys)], [r(lay.goal[0]), r(ys)]],
            "long": [[r(lay.xl), r(yS + 2.0)], [r(lay.xl), r(yb - lay.road_width / 2)],
                     [r(lay.goal[0]), r(yb - lay.road_width / 2)],
                     [r(lay.goal[0]), r(ys)]],
            "note": "suggested centre-line waypoints after leaving the start; any path "
                    "that stays on drivable surfaces is allowed",
        },
    }


DRIVE_TO_CONTROLLER = {
            "description": "drive_to turns toward the target (turning in place if the heading "
                           "error exceeds 0.6 rad), commands yaw_rate = heading_gain * heading_error "
                           "(clipped to max_turn_rate), and commands speed = min(speed_limit, "
                           "sqrt(2 * planned_decel * distance)), i.e. it plans its stop assuming "
                           "nominal deceleration. It stops at the target (arrival tolerance 0.35 m); "
                           "if it is carried past the target during a call it stops and returns "
                           "'overshot_target' (it does not turn around on its own); a target that is "
                           "beside or behind the rover when a call starts is reached by turning in "
                           "place first. "
                           "It holds position against slopes using brakes. It does not adapt to "
                           "dynamics that differ from nominal.",
            "heading_gain": 2.0, "planned_decel": NOMINAL["planned_decel"],
            "arrival_tolerance": 0.35, "speed_gain": 3.0}


# ---------------------------------------------------------------- MJCF
def build_mjcf(lay: Layout) -> str:
    H = lay.H
    PIT = -4.0
    boxes = []  # (name, center, half, euler_y_deg or None, euler_x_deg, rgba)

    def box(name, xmin, xmax, ymin, ymax, zmin, zmax, rgba):
        c = ((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2)
        h = ((xmax - xmin) / 2, (ymax - ymin) / 2, (zmax - zmin) / 2)
        boxes.append(f'<geom name="{name}" type="box" pos="{c[0]:.4f} {c[1]:.4f} {c[2]:.4f}" '
                     f'size="{h[0]:.4f} {h[1]:.4f} {h[2]:.4f}" rgba="{rgba}" class="terrain"/>')

    yS = -lay.ysouth
    yb = yS - lay.long_len
    x0, P = lay.x0, lay.pad_len
    box("plateau", -12.0, lay.xe, yS, 12.0, PIT, H, "0.55 0.5 0.42 1")
    box("south_road", lay.xl - lay.long_width / 2, x0 + P, yb - lay.road_width, yb, PIT, 0.0,
        "0.45 0.45 0.45 1")
    box("east_road", x0, x0 + P, yb, lay.ys + 3.0, PIT, 0.0, "0.45 0.45 0.45 1")

    # Ramps: thin tilted slabs whose top surface spans exactly the ramp line.
    th = 0.3
    ang = math.radians(lay.short_slope_deg)
    L = math.hypot(lay.short_len, H)
    cx = lay.xe + lay.short_len / 2 - math.sin(ang) * th
    cz = H / 2 - math.cos(ang) * th
    boxes.append(f'<geom name="short_ramp" type="box" pos="{cx:.4f} {lay.ys:.4f} {cz:.4f}" '
                 f'size="{L/2 + 0.02:.4f} {lay.short_width/2:.4f} {th:.4f}" '
                 f'euler="0 {lay.short_slope_deg:.4f} 0" rgba="0.75 0.45 0.25 1" class="terrain"/>')
    ang2 = math.radians(lay.long_slope_deg)
    L2 = math.hypot(lay.long_len, H)
    cy = yS - lay.long_len / 2 + math.sin(ang2) * th
    cz2 = H / 2 - math.cos(ang2) * th
    boxes.append(f'<geom name="long_ramp" type="box" pos="{lay.xl:.4f} {cy:.4f} {cz2:.4f}" '
                 f'size="{lay.long_width/2:.4f} {L2/2 + 0.02:.4f} {th:.4f}" '
                 f'euler="{lay.long_slope_deg:.4f} 0 0" rgba="0.35 0.6 0.35 1" class="terrain"/>')
    gx, gy = lay.goal
    sx, sy, syaw = lay.start
    c = lay.calib
    markers = (
        f'<geom name="calib_marker" type="box" pos="{(c[0]+c[1])/2} {(c[2]+c[3])/2} {H+0.001}" '
        f'size="{(c[1]-c[0])/2} {(c[3]-c[2])/2} 0.001" rgba="0.3 0.5 0.9 0.35" contype="0" conaffinity="0"/>'
        f'<geom name="goal_marker" type="cylinder" pos="{gx:.4f} {gy:.4f} 0.002" size="{lay.goal_radius} 0.002" '
        f'rgba="0.1 0.9 0.1 0.5" contype="0" conaffinity="0"/>')
    return mjcf_document("".join(boxes) + markers, lay.start, deck_z=H, pit_z=PIT)


def mjcf_document(terrain_xml: str, start: tuple, deck_z: float, pit_z: float = -4.0,
                  extra_bodies_xml: str = "") -> str:
    """Full MJCF: options, pit floor, the given terrain/marker geoms, rover and cargo.
    `start` is (x, y, yaw); the rover is placed on a deck whose top is at deck_z.
    `extra_bodies_xml` (e.g. pushable crates) goes after the cargo so that the rover and
    cargo keep the first two free joints."""
    sx, sy, syaw = start
    H, PIT = deck_z, pit_z
    return f"""
<mujoco model="rover_cargo">
  <compiler angle="degree"/>
  <option timestep="0.005" integrator="implicitfast" gravity="0 0 -9.81"
          iterations="50" ls_iterations="20" cone="pyramidal" jacobian="dense">
    <flag warmstart="enable"/>
  </option>
  <visual><headlight ambient="0.35 0.35 0.35" diffuse="0.6 0.6 0.6"/>
          <global offwidth="960" offheight="720"/></visual>
  <asset>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.6 0.75 0.9" rgb2="0.95 0.95 1" width="64" height="64"/>
  </asset>
  <default>
    <default class="terrain"><geom contype="1" conaffinity="1" condim="1"/></default>
  </default>
  <worldbody>
    <light pos="10 -10 30" dir="-0.2 0.3 -1" diffuse="0.7 0.7 0.7"/>
    <geom name="pit_floor" type="plane" pos="0 0 {PIT}" size="200 200 1" rgba="0.2 0.15 0.12 1"
          contype="1" conaffinity="1" condim="1"/>
    {terrain_xml}
    <body name="rover" pos="{sx} {sy} {H + 0.3}" euler="0 0 {math.degrees(syaw)}">
      <freejoint name="rover_free"/>
      <geom name="chassis" type="box" size="0.8 0.5 0.12" pos="0 0 0.1" mass="95" rgba="0.85 0.75 0.1 1"
            contype="2" conaffinity="1" condim="3" friction="0.7 0.005 0.0001"/>
      <geom name="mast" type="box" size="0.05 0.05 0.2" pos="0.65 0 0.42" mass="1" rgba="0.2 0.2 0.2 1"
            contype="0" conaffinity="0"/>
      <geom name="w_fl" type="sphere" size="0.25" pos=" 0.6  0.55 0" mass="1" condim="1" rgba="0.1 0.1 0.1 1" contype="2" conaffinity="1"/>
      <geom name="w_fr" type="sphere" size="0.25" pos=" 0.6 -0.55 0" mass="1" condim="1" rgba="0.1 0.1 0.1 1" contype="2" conaffinity="1"/>
      <geom name="w_rl" type="sphere" size="0.25" pos="-0.6  0.55 0" mass="1" condim="1" rgba="0.1 0.1 0.1 1" contype="2" conaffinity="1"/>
      <geom name="w_rr" type="sphere" size="0.25" pos="-0.6 -0.55 0" mass="1" condim="1" rgba="0.1 0.1 0.1 1" contype="2" conaffinity="1"/>
      <site name="imu" pos="0 0 0.1"/>
    </body>
    <body name="cargo" pos="{sx - 0.2*math.cos(syaw)} {sy - 0.2*math.sin(syaw)} {H + 0.3 + 0.22 + 0.15 + 0.005}">
      <freejoint name="cargo_free"/>
      <geom name="cargo" type="box" size="0.25 0.25 0.15" mass="10" rgba="0.8 0.2 0.2 1"
            contype="4" conaffinity="3" condim="3" friction="0.7 0.005 0.0001"/>
    </body>
    {extra_bodies_xml}
  </worldbody>
</mujoco>
"""


def scenario_summary(sc: Scenario) -> dict:
    return {"seed": sc.seed, "difficulty": sc.difficulty, "hidden": asdict(sc.hidden),
            "budgets": asdict(sc.budgets)}
