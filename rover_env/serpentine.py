"""Serpentine course: a zig-zag track over a pit with a mud shortcut and an icy leg.

    start pad ── P1 ══ mud A ══ J ══ mud B ══ P6 ── goal pad
                  │              ║              │
                  P2 ─────────── P3             │      (north side,  y = +L)
                                 ║ ice          │
                                 P4 ─────────── P5     (south side,  y = -L)

The straight line P1 → J → P6 is the shortcut and is all mud. The serpentine
P1 → P2 → P3 → J → P4 → P5 → P6 is paved except the P3 → P4 leg, which is ice.
Mud drag and ice friction are hidden and differ per seed; the start pad carries a
sample strip of each material so they can be measured before committing.
Everything is a pure function of (seed, difficulty).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .world import (Budgets, CourseLayout, DRIVE_TO_CONTROLLER, HiddenDynamics, NOMINAL,
                    Scenario, mjcf_document)

# Each seed is one of two regimes that look identical on the map but need different routes.
MODES = ("shortcut_open", "serpentine_open")
TRAIN_MODES = MODES
HELDOUT_MODES = ()

PAD_X = (-8.0, 10.0)
PAD_HALF_WIDTH = 8.0
GOAL_PAD_LENGTH = 9.0
PIT_Z = -4.0
COLORS = {"paved": "0.45 0.45 0.45 1", "mud": "0.42 0.27 0.13 1", "ice": "0.7 0.88 0.98 1"}


@dataclass(frozen=True)
class Rect:
    """Axis-aligned drivable rectangle with a surface type."""
    name: str
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    surface: str = "paved"

    def contains(self, x: float, y: float) -> bool:
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax


@dataclass
class SerpentineLayout(CourseLayout):
    width: float             # road width
    reach: float             # L: how far the serpentine extends north and south of y = 0
    x1: float                # x of the first column (P1, P2)
    x2: float                # x of the middle column (P3, J, P4)
    x3: float                # x of the last column (P5, P6)
    start: tuple = (-4.0, 0.0, 0.0)
    goal_radius: float = 1.5
    # derived
    goal: tuple = (0.0, 0.0)
    bounds: tuple = (0, 0, 0, 0)
    slabs: list = field(default_factory=list)      # drivable geometry (all paved underneath)
    patches: list = field(default_factory=list)    # mud / ice areas laid over the slabs

    def derive(self):
        h, L = self.width / 2, self.reach
        x1, x2, x3 = self.x1, self.x2, self.x3
        goal_end = x3 + GOAL_PAD_LENGTH
        self.goal = (x3 + 5.5, 0.0)
        self.bounds = (PAD_X[0] - 4.0, goal_end + 6.0, -L - 8.0, L + 8.0)
        self.slabs = [
            Rect("start_pad", PAD_X[0], PAD_X[1], -PAD_HALF_WIDTH, PAD_HALF_WIDTH),
            Rect("exit_road", PAD_X[1], x1 + h, -h, h),
            Rect("leg_P1_P2", x1 - h, x1 + h, -h, L + h),
            Rect("leg_P2_P3", x1 - h, x2 + h, L - h, L + h),
            Rect("leg_P3_P4", x2 - h, x2 + h, -L - h, L + h),
            Rect("leg_P4_P5", x2 - h, x3 + h, -L - h, -L + h),
            Rect("leg_P5_P6", x3 - h, x3 + h, -L - h, h),
            Rect("shortcut", x1 + h, x3 - h, -h, h),
            Rect("goal_pad", x3 + h, goal_end, -3.5, 3.5),
        ]
        self.patches = [
            Rect("mud_sample_strip", -6.0, 8.0, 4.0, 7.0, "mud"),
            Rect("ice_sample_strip", -6.0, 8.0, -7.0, -4.0, "ice"),
            Rect("mud_A", x1 + h, x2 - h, -h, h, "mud"),
            Rect("mud_B", x2 + h, x3 - h, -h, h, "mud"),
            Rect("ice_north", x2 - h, x2 + h, h, L - h, "ice"),
            Rect("ice_south", x2 - h, x2 + h, -L - h, -h, "ice"),
        ]
        return self

    # --- course interface used by Episode and Recorder
    def surface_at(self, x: float, y: float) -> str:
        for patch in self.patches:
            if patch.contains(x, y):
                return patch.surface
        return "paved"

    @property
    def overview_camera(self) -> dict:
        centre_x = (PAD_X[0] + self.x3 + GOAL_PAD_LENGTH) / 2
        return {"lookat": (centre_x, 0.0, 0.0), "distance": 62.0, "elevation": -62.0,
                "azimuth": 90.0}

    def nodes(self) -> dict:
        L = self.reach
        return {"P1": (self.x1, 0.0), "P2": (self.x1, L), "P3": (self.x2, L),
                "J": (self.x2, 0.0), "P4": (self.x2, -L), "P5": (self.x3, -L),
                "P6": (self.x3, 0.0), "goal": self.goal}

    def mjcf(self) -> str:
        geoms = []
        for s in self.slabs:
            geoms.append(_box(s.name, s, PIT_Z, 0.0, COLORS["paved"], collide=True))
        for p in self.patches:
            geoms.append(_box(p.name, p, 0.001, 0.004, COLORS[p.surface], collide=False))
        gx, gy = self.goal
        geoms.append(f'<geom name="goal_marker" type="cylinder" pos="{gx:.4f} {gy:.4f} 0.006" '
                     f'size="{self.goal_radius} 0.002" rgba="0.1 0.9 0.1 0.6" contype="0" conaffinity="0"/>')
        return mjcf_document("".join(geoms), self.start, deck_z=0.0, pit_z=PIT_Z)

    def public_map(self) -> dict:
        def r(v):
            return round(float(v), 3)

        def rect(q: Rect) -> dict:
            return {"name": q.name, "surface": q.surface,
                    "x": [r(q.xmin), r(q.xmax)], "y": [r(q.ymin), r(q.ymax)]}

        n = {k: [r(v[0]), r(v[1])] for k, v in self.nodes().items()}
        return {
            "units": "metres, radians; z is up; heading 0 = +x; all drivable surfaces are flat at z = 0",
            "world_bounds": {"xmin": r(self.bounds[0]), "xmax": r(self.bounds[1]),
                             "ymin": r(self.bounds[2]), "ymax": r(self.bounds[3])},
            "road_width": r(self.width),
            "drivable_surfaces": [rect(s) for s in self.slabs],
            "surface_patches": [rect(p) for p in self.patches],
            "surface_types": {
                "paved": "nominal tyre friction, no drag",
                "mud": "viscous: adds a deceleration of k * speed opposing motion (k in 1/s is "
                       "unknown and differs between episodes); friction is nominal",
                "ice": "low tyre friction (coefficient unknown, differs between episodes): limits "
                       "acceleration, braking and cornering; no drag",
                "note": "all mud in an episode is the same material, and all ice is the same "
                        "material, including the two sample strips on the start pad",
            },
            "hazards": "Everything outside the drivable surfaces is a drop of several metres. "
                       "Leaving a drivable surface destroys the cargo. Roads end half a road "
                       "width beyond their end node.",
            "calibration_area": {
                "x": [r(PAD_X[0]), r(PAD_X[1])], "y": [-PAD_HALF_WIDTH, PAD_HALF_WIDTH],
                "note": "flat, safe start pad for test manoeuvres; it carries one sample strip "
                        "of mud and one of ice (see surface_patches)"},
            "start": {"x": self.start[0], "y": self.start[1], "heading": self.start[2]},
            "goal": {"x": r(self.goal[0]), "y": r(self.goal[1]), "radius": self.goal_radius,
                     "note": "the CARGO must come to rest inside this circle, not destroyed; "
                             "cargo damage lowers the score"},
            "drive_to_controller": DRIVE_TO_CONTROLLER,
            "nodes": n,
            "routes": {
                "shortcut": [n["P1"], n["J"], n["P6"], n["goal"]],
                "serpentine": [n["P1"], n["P2"], n["P3"], n["J"], n["P4"], n["P5"], n["P6"], n["goal"]],
                "note": "centre-line waypoints. The shortcut is mud between P1 and P6 (paved at "
                        "the junction J). The serpentine is paved except P3 -> P4, which is ice "
                        "(paved at J). Routes may be mixed at J; any path that stays on drivable "
                        "surfaces is allowed.",
            },
        }


def _box(name: str, q: Rect, zmin: float, zmax: float, rgba: str, collide: bool) -> str:
    cx, cy, cz = (q.xmin + q.xmax) / 2, (q.ymin + q.ymax) / 2, (zmin + zmax) / 2
    hx, hy, hz = (q.xmax - q.xmin) / 2, (q.ymax - q.ymin) / 2, (zmax - zmin) / 2
    contact = 'class="terrain"' if collide else 'contype="0" conaffinity="0"'
    return (f'<geom name="{name}" type="box" pos="{cx:.4f} {cy:.4f} {cz:.4f}" '
            f'size="{hx:.4f} {hy:.4f} {hz:.4f}" rgba="{rgba}" {contact}/>')


def mode_for_seed(seed: int) -> str:
    r = np.random.default_rng([int(seed), 7927])
    return MODES[int(r.integers(len(MODES)))]


def _draw_hidden(seed: int, difficulty: float) -> HiddenDynamics:
    """Thin mud with slick ice (take the shortcut) or thick mud with mild ice (take the
    serpentine). The passable material is easy; the other one is not passable in budget."""
    mode = mode_for_seed(seed)
    r = np.random.default_rng([seed, 12])
    if mode == "shortcut_open":
        mud_drag, ice_friction = r.uniform(0.3, 0.8), r.uniform(0.03, 0.07)
    else:
        mud_drag, ice_friction = r.uniform(16.0, 26.0), r.uniform(0.25, 0.4)
    return HiddenDynamics(mode=mode, tire_friction=NOMINAL["tire_friction"],
                          brake_decel=NOMINAL["max_brake_decel"], steering_bias=0.0,
                          mud_drag=float(mud_drag), ice_friction=float(ice_friction))


def generate_serpentine(seed: int, difficulty: float) -> Scenario:
    r = np.random.default_rng([seed, 11])
    d = difficulty
    x1 = PAD_X[1] + float(r.uniform(5.0, 7.0))
    x2 = x1 + float(r.uniform(10.0, 13.0))
    x3 = x2 + float(r.uniform(10.0, 13.0))
    layout = SerpentineLayout(width=float(r.uniform(3.4, 3.8) - 0.5 * d),
                              reach=float(r.uniform(15.0, 19.0)), x1=x1, x2=x2, x3=x3).derive()
    # Sized so the right route fits with its calibration, while crawling the ice or trying
    # the wrong route and retreating does not.
    budgets = Budgets(time_s=88.0 - 8.0 * d, energy_j=18000.0 - 2000.0 * d)
    return Scenario(seed=seed, difficulty=d, layout=layout, hidden=_draw_hidden(seed, d),
                    budgets=budgets, course="serpentine")


def split_seeds(n_per_split: int = 50, start: int = 0) -> dict:
    """{'train': [...], 'heldout': [...]}: disjoint seed ranges (both regimes in each)."""
    return {"train": list(range(start, start + n_per_split)),
            "heldout": list(range(start + n_per_split, start + 2 * n_per_split))}
