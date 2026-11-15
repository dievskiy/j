"""Fork worlds: one generator, many courses.

A flat track over a pit. From the start pad the road forks into two or three lanes
that merge again before the goal. Each lane carries one hazard:

    mud      viscous drag            benign: slows the rover      severe: bogs it down
    ice      low friction to a turn  benign: stops in time        severe: slides off the end
    wind     crosswind on a bridge   benign: slight drift         severe: blown off
    crate    a crate blocks the lane benign: light, push it along severe: too heavy to move
    barrier  a wall near the far end benign: not there            severe: lane is closed

In every episode exactly one lane per fork is benign; which one is hidden. The map
is the same either way. The start pad carries a way to test each hazard: a sample
strip (mud, ice, wind), a sample crate, or a lookout from which barriers can be seen.
A world may add a second, shorter fork with no samples, where the rover has to look
and re-plan on the spot.

Everything is a pure function of (course name, seed, difficulty).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .env_constants import SENSOR_RANGE
from .serpentine import COLORS, PIT_Z, Rect, _box
from .world import (Budgets, CourseLayout, DRIVE_TO_CONTROLLER, HiddenDynamics, NOMINAL,
                    Scenario, mjcf_document)

# course name -> stages; each stage is a list of (lane position, hazard)
WORLDS = {
    "fork_mud_ice": [[("mid", "mud"), ("north", "ice")]],
    "fork_wind_mud": [[("mid", "wind"), ("south", "mud")]],
    "fork_crate_ice": [[("mid", "crate"), ("north", "ice")]],
    "fork_barrier_mud": [[("mid", "mud"), ("south", "barrier")]],
    "fork_crate_wind": [[("mid", "crate"), ("north", "wind")]],
    "fork_mud_ice_wind": [[("north", "ice"), ("mid", "mud"), ("south", "wind")]],
    "fork_crate_barrier_mud": [[("north", "barrier"), ("mid", "crate"), ("south", "mud")]],
    "fork_replan": [[("mid", "mud"), ("north", "ice")],
                    [("mid", "crate"), ("south", "barrier")]],   # second fork: no samples
}

# hidden value ranges: (benign low, benign high), (severe low, severe high)
HAZARD_RANGES = {
    "mud": ((0.3, 0.8), (16.0, 26.0)),        # drag, 1/s
    "ice": ((0.25, 0.40), (0.03, 0.07)),      # friction coefficient
    "wind": ((0.4, 1.0), (11.0, 14.0)),       # sideways acceleration, m/s^2
    "crate": ((6.0, 12.0), (180.0, 260.0)),   # mass, kg
}
PATCH_HAZARDS = ("mud", "ice", "wind")

PAD_X = (-8.0, 10.0)
PAD_HALF_WIDTH = 10.0
# Places on the start pad for samples. The first two have a long clear run-up from the
# west, which the ice and crate tests need; the third is tucked into a corner.
SAMPLE_SLOTS = [Rect("slot", 2.0, 9.0, 3.0, 7.0), Rect("slot", 2.0, 9.0, -7.0, -3.0),
                Rect("slot", -7.5, -2.5, 5.0, 9.0)]
NEEDS_RUN_UP = ("ice", "crate")
LOOKOUT_RADIUS = 1.5
CRATE_HALF = 0.5
COLORS = dict(COLORS, wind="0.85 0.8 0.55 1")
OUTER_OFFSET = (12.0, 7.0)      # lateral offset of north/south lanes, per stage
LANE_LENGTH = ((26.0, 30.0), (12.0, 12.0))


@dataclass
class Lane:
    name: str
    hazard: str
    waypoints: list            # centre line from the fork node to the merge node
    zone: Rect | None          # where a patch hazard acts
    obstacle: tuple | None     # (x, y) of the crate or barrier
    sample: dict | None        # how to test this hazard on the start pad


@dataclass
class ForkLayout(CourseLayout):
    course: str
    width: float
    stages: list                                    # list of list[Lane]
    forks: list                                     # [(fork_node, merge_node), ...]
    slabs: list = field(default_factory=list)
    patches: list = field(default_factory=list)
    start: tuple = (-4.0, 0.0, 0.0)
    goal: tuple = (0.0, 0.0)
    goal_radius: float = 1.5
    bounds: tuple = (0, 0, 0, 0)
    # physical truth for this episode (never part of the public map)
    barriers: tuple = ()
    crates: tuple = ()          # (body name, x, y, mass)
    wind_direction: tuple = (0.0, 0.0)
    lookout: tuple | None = None

    @property
    def crate_bodies(self) -> tuple:
        return tuple(name for name, *_ in self.crates)

    def surface_at(self, x: float, y: float) -> str:
        for patch in self.patches:
            if patch.contains(x, y):
                return patch.surface
        return "paved"

    @property
    def overview_camera(self) -> dict:
        centre_x = (PAD_X[0] + self.goal[0] + 3.0) / 2
        return {"lookat": (centre_x, 0.0, 0.0), "distance": 34.0 + 0.75 * (self.goal[0] - PAD_X[0]),
                "elevation": -62.0, "azimuth": 90.0}

    def mjcf(self) -> str:
        h = self.width / 2
        geoms = [_box(s.name, s, PIT_Z, 0.0, COLORS["paved"], collide=True) for s in self.slabs]
        geoms += [_box(p.name, p, 0.001, 0.004, COLORS[p.surface], collide=False)
                  for p in self.patches]
        for i, (x, y) in enumerate(self.barriers):
            wall = Rect(f"barrier_{i}", x - 0.3, x + 0.3, y - h, y + h)
            geoms.append(_box(wall.name, wall, 0.0, 1.0, "0.8 0.15 0.15 1", collide=True))
        if self.lookout:
            lx, ly, radius = self.lookout
            geoms.append(f'<geom name="lookout" type="cylinder" pos="{lx} {ly} 0.006" '
                         f'size="{radius} 0.002" rgba="0.95 0.85 0.2 0.7" contype="0" conaffinity="0"/>')
        gx, gy = self.goal
        geoms.append(f'<geom name="goal_marker" type="cylinder" pos="{gx:.4f} {gy:.4f} 0.006" '
                     f'size="{self.goal_radius} 0.002" rgba="0.1 0.9 0.1 0.6" contype="0" conaffinity="0"/>')
        crates = "".join(
            f'<body name="{name}" pos="{x:.4f} {y:.4f} {CRATE_HALF + 0.01}"><freejoint/>'
            f'<geom name="{name}" type="box" size="{CRATE_HALF} {CRATE_HALF} {CRATE_HALF}" '
            f'mass="{mass:.3f}" rgba="0.6 0.45 0.25 1" contype="1" conaffinity="3" condim="3" '
            f'friction="0.6 0.005 0.0001" priority="1"/></body>'
            for name, x, y, mass in self.crates)
        return mjcf_document("".join(geoms), self.start, deck_z=0.0, pit_z=PIT_Z,
                             extra_bodies_xml=crates)

    def public_map(self) -> dict:
        def r(v):
            return round(float(v), 3)

        def rect(q: Rect) -> dict:
            return {"name": q.name, "surface": q.surface,
                    "x": [r(q.xmin), r(q.xmax)], "y": [r(q.ymin), r(q.ymax)]}

        def point(p) -> list:
            return [r(p[0]), r(p[1])]

        forks = []
        for index, (lanes, (fork, merge)) in enumerate(zip(self.stages, self.forks)):
            forks.append({
                "fork_node": point(fork), "merge_node": point(merge),
                "has_samples_on_start_pad": index == 0,
                "lanes": [{"name": lane.name, "hazard": lane.hazard,
                           "waypoints": [point(p) for p in lane.waypoints],
                           "hazard_zone": rect(lane.zone) if lane.zone else None,
                           "obstacle_position": point(lane.obstacle) if lane.hazard == "crate" else None,
                           "test_on_start_pad": lane.sample} for lane in lanes]})
        return {
            "units": "metres, radians; z is up; heading 0 = +x; all drivable surfaces are flat at z = 0",
            "world_bounds": {"xmin": r(self.bounds[0]), "xmax": r(self.bounds[1]),
                             "ymin": r(self.bounds[2]), "ymax": r(self.bounds[3])},
            "road_width": r(self.width),
            "drivable_surfaces": [rect(s) for s in self.slabs],
            "surface_patches": [rect(p) for p in self.patches],
            "hazards": {
                "edges": "Everything outside the drivable surfaces is a drop of several metres. "
                         "Leaving a drivable surface destroys the cargo. Roads end half a road "
                         "width beyond their end node.",
                "mud": "viscous: adds a deceleration of k * speed opposing motion; k (1/s) is unknown",
                "ice": "low tyre friction (coefficient unknown): limits acceleration, braking and "
                       "cornering; the icy lane ends in a turn where the rover must stop",
                "wind": "a steady crosswind of unknown strength pushes the rover sideways while "
                        "it is on a wind-exposed surface; the direction is the same everywhere",
                "crate": "a 1 m crate of unknown mass stands in the lane; the rover may push it "
                         "(it is not part of the terrain), if it is light enough",
                "barrier": "a wall may or may not close the lane near its far end; it is not on "
                           "this map. observe() lists barriers within sensor_range, or all of "
                           "them while the rover is at rest inside the lookout. Hitting one "
                           "ends the episode; drive_to stops short of a detected barrier and "
                           "returns 'obstacle_ahead'.",
                "note": "Hazard strength differs between episodes and cannot be seen. All mud in "
                        "an episode is the same material; likewise ice, wind and crates, "
                        "including the samples on the start pad. At every fork at least one "
                        "lane is passable within the budgets.",
            },
            "sensor_range": SENSOR_RANGE,
            "lookout": ({"x": self.lookout[0], "y": self.lookout[1], "radius": self.lookout[2]}
                        if self.lookout else None),
            "calibration_area": {"x": [PAD_X[0], PAD_X[1]], "y": [-PAD_HALF_WIDTH, PAD_HALF_WIDTH],
                                 "note": "flat, safe start pad for test manoeuvres"},
            "start": {"x": self.start[0], "y": self.start[1], "heading": self.start[2]},
            "goal": {"x": r(self.goal[0]), "y": r(self.goal[1]), "radius": self.goal_radius,
                     "note": "the CARGO must come to rest inside this circle, not destroyed; "
                             "cargo damage lowers the score"},
            "drive_to_controller": DRIVE_TO_CONTROLLER,
            "pad_exit": [PAD_X[1] - 2.0, 0.0],
            "forks": forks,
        }


# ----------------------------------------------------------------- generation
def modes(course: str) -> tuple:
    """Regime names: which hazard's lane is the passable one at each fork."""
    names = [""]
    for stage in WORLDS[course]:
        names = [f"{prefix}{'+' if prefix else ''}{hazard}_open" for prefix in names
                 for _, hazard in stage]
    return tuple(names)


def mode_for_seed(course: str, seed: int) -> str:
    options = modes(course)
    r = np.random.default_rng([int(seed), 7933, len(course)])
    return options[int(r.integers(len(options)))]


def _lane_geometry(position: str, hazard: str, fork: tuple, merge: tuple, offset: float,
                   h: float) -> tuple:
    """Slabs, centre-line waypoints and hazard zone / obstacle position for one lane."""
    (xf, _), (xm, _) = fork, merge
    y = {"mid": 0.0, "north": offset, "south": -offset}[position]
    if position == "mid":
        slabs = [Rect(f"lane_{hazard}", xf + h, xm - h, -h, h)]
        waypoints = [fork, merge]
    else:
        lo, hi = min(0.0, y), max(0.0, y)
        slabs = [Rect(f"lane_{hazard}_in", xf - h, xf + h, lo - h, hi + h),
                 Rect(f"lane_{hazard}", xf - h, xm + h, y - h, y + h),
                 Rect(f"lane_{hazard}_out", xm - h, xm + h, lo - h, hi + h)]
        waypoints = [fork, (xf, y), (xm, y), merge]
    zone = obstacle = None
    if hazard == "ice":      # ice runs through the turn at the far end
        zone = Rect("ice_lane", xf + 4.0, xm + h, y - h, y + h, "ice")
    elif hazard in PATCH_HAZARDS:
        zone = Rect(f"{hazard}_lane", xf + 4.0, xm - 4.0, y - h, y + h, hazard)
    elif hazard == "crate":
        obstacle = (xf + 7.0, y)
    elif hazard == "barrier":
        obstacle = (xm - 6.0, y)
    return slabs, waypoints, zone, obstacle


def _assign_sample_slots(hazards: list) -> dict:
    """Give each testable hazard a place on the start pad; hazards whose test needs a
    run-up get the slots that have one."""
    free = list(SAMPLE_SLOTS)
    wanted = [h for h in hazards if h in PATCH_HAZARDS or h == "crate"]
    return {hazard: free.pop(0) for hazard in sorted(wanted, key=lambda h: h not in NEEDS_RUN_UP)}


def generate_fork(course: str, seed: int, difficulty: float) -> Scenario:
    if course not in WORLDS:
        raise ValueError(f"unknown course {course!r}")
    r = np.random.default_rng([seed, 21])
    d = difficulty
    width = float(r.uniform(3.4, 3.8) - 0.5 * d)
    h = width / 2
    mode = mode_for_seed(course, seed)
    open_hazards = [part.removesuffix("_open") for part in mode.split("+")]

    slabs = [Rect("start_pad", PAD_X[0], PAD_X[1], -PAD_HALF_WIDTH, PAD_HALF_WIDTH)]
    patches, stages, forks, crates, barriers = [], [], [], [], []
    hidden = {"mud": 0.0, "ice": NOMINAL["tire_friction"], "wind": 0.0}
    lookout = None
    wind_sign = 0.0
    slots = _assign_sample_slots([hazard for _, hazard in WORLDS[course][0]])
    x = PAD_X[1]
    route_length = 0.0
    for index, stage in enumerate(WORLDS[course]):
        fork = (x + float(r.uniform(5.0, 7.0)), 0.0)
        merge = (fork[0] + float(r.uniform(*LANE_LENGTH[index])), 0.0)
        slabs += [Rect(f"road_to_fork_{index}", x, fork[0] + h, -h, h),
                  Rect(f"merge_{index}", merge[0] - h, merge[0] + h, -h, h)]
        lanes = []
        for position, hazard in stage:
            lane_slabs, waypoints, zone, obstacle = _lane_geometry(
                position, hazard, fork, merge, OUTER_OFFSET[index], h)
            slabs += lane_slabs
            benign = hazard == open_hazards[index]
            if hazard in HAZARD_RANGES:
                value = float(r.uniform(*HAZARD_RANGES[hazard][0 if benign else 1]))
            sample = None
            if index == 0:                       # only the first fork has samples
                if hazard in slots:
                    slot = slots[hazard]
                    cy = (slot.ymin + slot.ymax) / 2
                if hazard in PATCH_HAZARDS:
                    strip = Rect(f"{hazard}_sample_strip", slot.xmin, slot.xmax, slot.ymin,
                                 slot.ymax, hazard)
                    patches.append(strip)
                    sample = {"kind": "sample_strip", "x": [strip.xmin, strip.xmax],
                              "y": [strip.ymin, strip.ymax]}
                elif hazard == "crate":
                    crates.append(("crate_sample", slot.xmin + 4.0, cy, value))
                    sample = {"kind": "sample_crate", "x": slot.xmin + 4.0, "y": cy,
                              "note": "same mass as the crate in the lane"}
                elif hazard == "barrier":
                    lookout = (-6.0, -8.0, LOOKOUT_RADIUS)
                    sample = {"kind": "lookout", "x": lookout[0], "y": lookout[1],
                              "radius": LOOKOUT_RADIUS,
                              "note": "at rest inside this circle, observe() lists every barrier"}
            if hazard in ("mud", "ice", "wind"):
                hidden[hazard] = value
                patches.append(zone)
                if hazard == "wind":   # blows toward the pad centre from its sample strip
                    wind_sign = -1.0 if (sample and sample["y"][0] > 0) else 1.0
            elif hazard == "crate":
                crates.append((f"crate_{index}", obstacle[0], obstacle[1], value))
            elif hazard == "barrier" and not benign:
                barriers.append(obstacle)
            lanes.append(Lane(f"{position}_{hazard}", hazard, waypoints, zone, obstacle, sample))
            if benign:
                route_length += sum(math.dist(a, b) for a, b in zip(waypoints, waypoints[1:]))
        route_length += fork[0] - x
        stages.append(lanes)
        forks.append((fork, merge))
        x = merge[0] + h
    goal = (x + 5.0, 0.0)
    slabs.append(Rect("goal_pad", x, x + 8.5, -3.5, 3.5))
    route_length += goal[0] - (x - h)

    reach = max(OUTER_OFFSET) + h
    layout = ForkLayout(
        course=course, width=width, stages=stages, forks=forks, slabs=slabs, patches=patches,
        goal=goal, bounds=(PAD_X[0] - 4.0, x + 8.5 + 6.0, -reach - 8.0, reach + 8.0),
        barriers=tuple(barriers), crates=tuple(crates), wind_direction=(0.0, wind_sign),
        lookout=lookout)
    hidden_dynamics = HiddenDynamics(
        mode=mode, tire_friction=NOMINAL["tire_friction"], brake_decel=NOMINAL["max_brake_decel"],
        steering_bias=0.0, mud_drag=hidden["mud"], ice_friction=hidden["ice"],
        wind_accel=hidden["wind"])
    # Time for the passable route at a brisk pace plus an allowance for testing; a wrong
    # first choice followed by a retreat should not fit.
    drive_time = route_length / 2.4 + 3.5 * (2 * len(stages) + 2)
    test_allowance = 14.0 * len(WORLDS[course][0])
    budgets = Budgets(time_s=(1.25 - 0.1 * d) * drive_time + test_allowance,
                      energy_j=22000.0 - 2000.0 * d)
    return Scenario(seed=seed, difficulty=d, layout=layout, hidden=hidden_dynamics,
                    budgets=budgets, course=course)
