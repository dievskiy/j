"""Winch yard episode: a gantry hoist with an elastic cable, driven through tools.

Agent tools: observe, move_trolley, winch, attach, release, wait, finish.
Harness-only: reward(), outcome(), render_png().

MuJoCo simulates the crates (gravity, contacts, tumbling). The trolley and the free
hook are moved kinematically, and the cable is a one-sided spring between the drum
and the attached crate's lug, applied as an external force each physics step. The
hidden values (crate masses, cable stiffness) act only there.
"""
from __future__ import annotations

import io
import math
import os

os.environ.setdefault("MUJOCO_GL", "egl")

import mujoco  # noqa: E402
import numpy as np  # noqa: E402

from .world import (CRATE_HALF, GOAL_HALF, GOAL_X, G, RAIL_Z, SPEC, STUCK_RELEASE_SIDEWAYS_N,  # noqa: E402
                    TOTAL_PAYLOAD_KG, build_mjcf, generate, public_map)

PHYS_DT = 0.002
SUBSTEPS = 10                    # control period 0.02 s
CTRL_DT = PHYS_DT * SUBSTEPS
TRACE_EVERY = 5                  # one trace sample per 0.1 s
MAX_TRACE = 300
MAX_CALL_DURATION = 60.0
DRUM_Z = SPEC["drum_height"]
CABLE_DAMPING_RATIO = SPEC["cable_damping_ratio"]
SWING_DRAG = 60.0                # N per m/s on a hanging crate
P_IDLE = 40.0                    # W, charged whenever simulated time advances
WINCH_EFFICIENCY = 0.8
TROLLEY_DRAG_N = 60.0            # rolling resistance of the trolley
REST_SPEED = 0.1                 # m/s: a crate slower than this counts as at rest
REST_SPIN = 0.2                  # rad/s
TENSION_NOISE = 10.0
POSITION_NOISE = 0.01
STUCK_HOLD_N = 5000.0            # extra downward force on a stuck crate
CREEP_RATE = 0.5                 # m/s of permanent lengthening per unit of relative excess tension


def _r(value, digits=3):
    return round(float(value), digits)


class Episode:
    TOOLS = ("observe", "move_trolley", "winch", "attach", "release", "wait", "finish")

    def __init__(self, seed: int, difficulty: float = 0.5, variation: str | None = None):
        self.scenario = sc = generate(seed, difficulty, variation)
        self.model = mujoco.MjModel.from_xml_string(build_mjcf(sc))
        self.data = mujoco.MjData(self.model)
        m = self.model
        name2id = mujoco.mj_name2id
        self._crate_body = [name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"crate_{i}") for i in range(len(sc.crate_x))]
        self._crate_geom = [name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f"crate_{i}") for i in range(len(sc.crate_x))]
        self._geom_to_crate = {geom: i for i, geom in enumerate(self._crate_geom)}
        self._platform_geom = name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "platform")
        self._support_geoms = {self._platform_geom, name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "floor")}
        self._lug_site = [name2id(m, mujoco.mjtObj.mjOBJ_SITE, f"lug_{i}") for i in range(len(sc.crate_x))]
        self._cable_tendon = [name2id(m, mujoco.mjtObj.mjOBJ_TENDON, f"cable_{i}") for i in range(len(sc.crate_x))]
        self._free_tendon = name2id(m, mujoco.mjtObj.mjOBJ_TENDON, "cable_free")
        self._map = public_map(sc)
        self._renderer = None

        self.trolley_x = sc.trolley_start_x
        self.trolley_v = 0.0
        self.cable_length = sc.cable_start_length      # paid out by the drum, unstretched
        self.creep_extension = 0.0                     # permanent lengthening from creep
        self.winch_v = 0.0                             # d(cable_length)/dt
        self.attached = None                           # index of the attached crate
        self.tension = 0.0
        self.step_count = 0
        self.energy = 0.0
        self.destroyed = [False] * len(sc.crate_x)
        self.cable_snapped = False
        self.terminated = None
        self.finished = False
        self._reward = 0.0
        self._outcome = {"delivered": False, "reason": "finish() not called"}
        self._last_cmd = None
        self._call_log = []
        self._stuck = [i == sc.stuck_index for i in range(len(sc.crate_x))]
        self._supported = [True] * len(sc.crate_x)     # touching the floor or platform last step
        self._rest_time = [0.0] * len(sc.crate_x)        # how long each crate has sat still on the goal
        for _ in range(250):                           # let the crates settle (not charged)
            mujoco.mj_step(m, self.data)
        self.data.time = 0.0
        self._sync_kinematic_bodies()
        mujoco.mj_forward(m, self.data)

    # ------------------------------------------------------------ state helpers
    @property
    def t(self) -> float:
        return self.step_count * PHYS_DT

    def _drum(self) -> np.ndarray:
        return np.array([self.trolley_x, 0.0, DRUM_Z])

    def _lug(self, i: int) -> np.ndarray:
        return self.data.site_xpos[self._lug_site[i]].copy()

    def _hook(self) -> np.ndarray:
        if self.attached is not None:
            return self._lug(self.attached)
        return self._drum() - np.array([0.0, 0.0, self._unstretched_length()])

    def _tension_reading(self, noise: float = 0.0) -> float:
        """What the tension sensor shows: true tension plus its constant offset (plus noise)."""
        return self.tension * self.scenario.sensor_gain + self.scenario.sensor_offset + TENSION_NOISE * noise

    def _noise(self, key: int, n: int) -> np.ndarray:
        rng = np.random.default_rng([self.scenario.seed, 505, key])
        return rng.standard_normal(n)

    def _sync_kinematic_bodies(self):
        self.data.mocap_pos[0] = [self.trolley_x, 0.0, RAIL_Z]
        self.data.mocap_pos[1] = self._hook()
        for i, tendon in enumerate(self._cable_tendon):
            self.model.tendon_rgba[tendon][3] = 1.0 if self.attached == i else 0.0
        self.model.tendon_rgba[self._free_tendon][3] = 0.0 if self.attached is not None else 1.0

    # ------------------------------------------------------------ physics core
    def _cable_force(self) -> tuple:
        """Apply the cable's pull to the attached crate. Returns (tension, x component of
        the cable's pull on the trolley)."""
        self.data.qfrc_applied[:] = 0.0
        if self.attached is None:
            return 0.0, 0.0
        i = self.attached
        drum, lug = self._drum(), self._lug(i)
        offset = lug - drum
        distance = float(np.linalg.norm(offset))
        direction = offset / max(distance, 1e-9)
        stretch = distance - self._unstretched_length()
        if stretch <= 0.0:
            return 0.0, 0.0
        body = self._crate_body[i]
        velocity = np.zeros(6)
        mujoco.mj_objectVelocity(self.model, self.data, mujoco.mjtObj.mjOBJ_SITE,
                                 self._lug_site[i], velocity, 0)
        lug_v = velocity[3:6]
        stretch_rate = float((lug_v - np.array([self.trolley_v, 0.0, 0.0])) @ direction) - self.winch_v
        k = self.scenario.cable_stiffness
        damping = 2.0 * CABLE_DAMPING_RATIO * math.sqrt(k * 100.0)
        tension = max(0.0, k * stretch + damping * stretch_rate)
        if self._stuck[i] and tension * math.hypot(direction[0], direction[1]) >= STUCK_RELEASE_SIDEWAYS_N:
            self._stuck[i] = False
        # air drag on the hanging load, so a swing dies down over several seconds
        centre_v = self.data.cvel[body][3:6]
        mujoco.mj_applyFT(self.model, self.data, -tension * direction - SWING_DRAG * centre_v,
                          np.zeros(3), lug, body, self.data.qfrc_applied)
        return tension, tension * float(direction[0])

    def _physics_step(self):
        lo, hi = SPEC["trolley_range"]
        self.trolley_x = min(max(self.trolley_x + self.trolley_v * PHYS_DT, lo), hi)
        lo, hi = SPEC["cable_length_range"]
        new_length = min(max(self.cable_length + self.winch_v * PHYS_DT, lo), hi)
        reeled_in = self.cable_length - new_length           # actual cable motion this step
        self.cable_length = new_length
        self.tension, pull_on_trolley_x = self._cable_force()
        self._hold_stuck_crates()
        winch_work = max(self.tension * reeled_in, 0.0) / WINCH_EFFICIENCY
        # the trolley motor works against rolling resistance and the cable's sideways pull
        trolley_work = (TROLLEY_DRAG_N * abs(self.trolley_v)
                        + max(-pull_on_trolley_x * self.trolley_v, 0.0)) * PHYS_DT
        self.energy += P_IDLE * PHYS_DT + winch_work + trolley_work
        falling_speed = [-float(self.data.cvel[body][5]) for body in self._crate_body]
        mujoco.mj_step(self.model, self.data)
        self.step_count += 1
        self._update_crates(falling_speed)
        self._creep()
        if self.tension > self.scenario.cable_strength_n:
            self.cable_snapped = True
            self.attached = None
            self.tension = 0.0
            self.terminated = "cable_snapped"

    def _hold_stuck_crates(self):
        """A stuck crate is pressed to the floor far beyond any cable's strength."""
        for i, stuck in enumerate(self._stuck):
            if stuck:
                body = self._crate_body[i]
                mujoco.mj_applyFT(self.model, self.data, np.array([0.0, 0.0, -STUCK_HOLD_N]), np.zeros(3),
                                  self.data.xpos[body], body, self.data.qfrc_applied)

    def _creep(self):
        """Above the creep onset the cable lengthens permanently, at a rate proportional
        to the excess tension, so a held load's tension relaxes towards the onset."""
        onset = self.scenario.creep_onset_n
        if onset is None or self.tension <= onset:
            return
        self.creep_extension += CREEP_RATE * (self.tension - onset) / onset * PHYS_DT

    def _unstretched_length(self) -> float:
        """Drum to hook with no stretch: what the drum paid out plus any creep."""
        return self.cable_length + self.creep_extension

    def _update_crates(self, falling_speed_before: list):
        """Per physics step: a crate that lands on the floor or platform faster than the
        limit is destroyed, and time spent sitting still on the goal is accumulated."""
        supported = [False] * len(self._crate_body)
        on_platform = [False] * len(self._crate_body)
        for c in self.data.contact[:self.data.ncon]:
            i = self._geom_to_crate.get(c.geom1)
            other = c.geom2
            if i is None:
                i = self._geom_to_crate.get(c.geom2)
                other = c.geom1
            if i is not None and other in self._support_geoms:
                supported[i] = True
                on_platform[i] |= other == self._platform_geom
        for i, body in enumerate(self._crate_body):
            if supported[i] and not self._supported[i] and \
                    falling_speed_before[i] > SPEC["max_touchdown_speed"]:
                self.destroyed[i] = True
            self._supported[i] = supported[i]
            resting = (on_platform[i] and self.attached != i and self._still_on_goal(body))
            self._rest_time[i] = self._rest_time[i] + PHYS_DT if resting else 0.0

    def _still_on_goal(self, body: int) -> bool:
        x, y, _ = self.data.xpos[body]
        upright = self.data.xmat[body][8] > 0.98          # local z axis points up
        spin, speed = self.data.cvel[body][0:3], self.data.cvel[body][3:6]
        return (abs(x - self.scenario.goal_x) <= self.scenario.goal_half and abs(y) <= self.scenario.goal_half and upright
                and float(np.linalg.norm(speed)) < REST_SPEED
                and float(np.linalg.norm(spin)) < REST_SPIN)

    def _budget_exhausted(self) -> str | None:
        if self.t >= self.scenario.time_s - 1e-9:
            return "time_budget_exhausted"
        if self.energy >= self.scenario.energy_j:
            return "energy_budget_exhausted"
        return None

    def _run(self, controller, max_duration: float, tool: str, args: dict) -> str:
        """Advance time with `controller() -> (trolley_v_target, winch_v_target, done)`.
        Speeds follow their targets at the published ramp rates."""
        trace, t0, reason = [], self.t, "max_duration_reached"
        for k in range(int(round(max_duration / CTRL_DT))):
            trolley_target, winch_target, done = controller()
            if done:
                reason = done
                break
            self.trolley_v = _ramp(self.trolley_v, trolley_target, SPEC["trolley_ramp"] * CTRL_DT)
            self.winch_v = _ramp(self.winch_v, winch_target, SPEC["winch_ramp"] * CTRL_DT)
            for _ in range(SUBSTEPS):
                self._physics_step()
                self.terminated = self.terminated or self._budget_exhausted()
                if self.terminated:
                    break
            self._sync_kinematic_bodies()
            if k % TRACE_EVERY == 0 and len(trace) < MAX_TRACE:
                trace.append(self._trace_sample())
            if self.terminated:
                reason = self.terminated
                break
        if self.terminated:
            self.trolley_v = self.winch_v = 0.0
        self._last_cmd = {"tool": tool, "args": args, "termination": reason,
                          "start_t": _r(t0), "duration": _r(self.t - t0),
                          "trace_note": "samples every 0.1 s (noisy)", "trace": trace}
        return reason

    def _trace_sample(self) -> dict:
        n = self._noise(self.step_count, 3)
        hook = self._hook()
        return {"t": _r(self.t), "tension": _r(self._tension_reading(n[0]), 1),
                "cable_length": _r(self._unstretched_length()), "trolley_x": _r(self.trolley_x),
                "hook_x": _r(hook[0] + POSITION_NOISE * n[1]),
                "hook_height": _r(hook[2] + POSITION_NOISE * n[2])}

    # ------------------------------------------------------------ tool plumbing
    def _over(self) -> dict | None:
        if self.finished:
            return {"ok": False, "termination": "episode_finished"}
        if self.terminated:
            return {"ok": False, "termination": "episode_over", "detail": self.terminated}
        return None

    @staticmethod
    def _num(name: str, value, lo: float, hi: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        value = float(value)
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{name} must be finite and within [{lo}, {hi}]")
        return value

    def _result(self, reason: str, **extra) -> dict:
        ok = reason not in ("cable_snapped", "time_budget_exhausted", "energy_budget_exhausted")
        return dict({"ok": ok, "termination": reason, "t": _r(self.t),
                     "time_remaining": _r(max(self.scenario.time_s - self.t, 0.0)),
                     "energy_remaining": _r(max(self.scenario.energy_j - self.energy, 0.0), 1)},
                    **extra)

    def _log(self, tool: str, args: dict, result: dict) -> dict:
        self._call_log.append((tool, args, result.get("termination")))
        return result

    def _invalid(self, tool: str, args: dict, error: Exception) -> dict:
        return self._log(tool, args, {"ok": False, "termination": "invalid_input", "detail": str(error)})

    # ------------------------------------------------------------ agent tools
    def observe(self) -> dict:
        n = self._noise(self.step_count, 3)
        hook = self._hook()
        crates = {}
        for i, body in enumerate(self._crate_body):
            position = self.data.xpos[body]
            noise = self._noise(self.step_count + 10 + i, 2)
            crates[f"crate_{i}"] = {"x": _r(position[0] + POSITION_NOISE * noise[0], 2),
                                    "height": _r(position[2] - CRATE_HALF + POSITION_NOISE * noise[1], 2),
                                    "destroyed": self.destroyed[i]}
        return {
            "t": _r(self.t),
            "trolley_x": _r(self.trolley_x),
            "cable_length": _r(self._unstretched_length()),
            "hook": {"x": _r(hook[0] + POSITION_NOISE * n[1]), "height": _r(hook[2] + POSITION_NOISE * n[2])},
            "tension": _r(self._tension_reading(n[0]), 1),
            "attached": None if self.attached is None else f"crate_{self.attached}",
            "crates": crates,
            "time_remaining": _r(max(self.scenario.time_s - self.t, 0.0)),
            "energy_remaining": _r(max(self.scenario.energy_j - self.energy, 0.0), 1),
            "episode": {"finished": self.finished, "ended": self.terminated},
            "last_command": self._last_cmd,
            "map": self._map,
        }

    def move_trolley(self, x, speed_limit, max_duration) -> dict:
        args = {"x": x, "speed_limit": speed_limit, "max_duration": max_duration}
        if self._over():
            return self._log("move_trolley", args, self._over())
        try:
            target = self._num("x", x, *SPEC["trolley_range"])
            speed = self._num("speed_limit", speed_limit, 0.05, SPEC["trolley_max_speed"])
            duration = self._num("max_duration", max_duration, CTRL_DT, MAX_CALL_DURATION)
        except ValueError as error:
            return self._invalid("move_trolley", args, error)

        def controller():
            gap = target - self.trolley_x
            if abs(gap) < 0.02 and abs(self.trolley_v) < 0.05:
                return 0.0, 0.0, "arrived"
            # slow down in time to stop at the target with the published ramp
            v_stop = math.sqrt(2.0 * SPEC["trolley_ramp"] * abs(gap))
            return math.copysign(min(speed, v_stop), gap), 0.0, None

        reason = self._run(controller, duration, "move_trolley", args)
        self.trolley_v = 0.0 if reason == "arrived" else self.trolley_v
        return self._log("move_trolley", args, self._result(reason, trolley_x=_r(self.trolley_x)))

    def winch(self, length_change, speed_limit, max_duration, stop_tension=None) -> dict:
        """Pay out (positive length_change) or reel in (negative) cable."""
        args = {"length_change": length_change, "speed_limit": speed_limit,
                "max_duration": max_duration, "stop_tension": stop_tension}
        if self._over():
            return self._log("winch", args, self._over())
        try:
            change = self._num("length_change", length_change, -8.0, 8.0)
            speed = self._num("speed_limit", speed_limit, 0.01, SPEC["winch_max_speed"])
            duration = self._num("max_duration", max_duration, CTRL_DT, MAX_CALL_DURATION)
            limit = None if stop_tension is None else self._num("stop_tension", stop_tension, -1e4, 1e5)
        except ValueError as error:
            return self._invalid("winch", args, error)
        lo, hi = SPEC["cable_length_range"]
        target = min(max(self.cable_length + change, lo), hi)
        tripped = [False]

        def controller():
            if limit is not None and (tripped[0] or self._tension_reading() >= limit):
                tripped[0] = True                      # brake the drum, then report
                return 0.0, 0.0, "stop_tension_reached" if abs(self.winch_v) < 1e-6 else None
            gap = target - self.cable_length
            if abs(gap) < 0.005 and abs(self.winch_v) < 0.02:
                return 0.0, 0.0, "done"
            v_stop = math.sqrt(2.0 * SPEC["winch_ramp"] * abs(gap))
            return 0.0, math.copysign(min(speed, v_stop), gap), None

        reason = self._run(controller, duration, "winch", args)
        self.winch_v = 0.0 if reason in ("done", "stop_tension_reached") else self.winch_v
        return self._log("winch", args, self._result(
            reason, cable_length=_r(self._unstretched_length()), tension=self.observe()["tension"]))

    def attach(self) -> dict:
        if self._over():
            return self._log("attach", {}, self._over())
        if self.attached is not None:
            return self._log("attach", {}, self._result("already_attached"))
        hook = self._hook()
        for i in range(len(self._crate_body)):
            if np.linalg.norm(self._lug(i) - hook) <= SPEC["attach_radius"] and not self.destroyed[i]:
                self.attached = i
                # hooked on with the cable just taut: no stretch, no tension yet
                self.cable_length = float(np.linalg.norm(self._lug(i) - self._drum())) - self.creep_extension
                self._sync_kinematic_bodies()
                reason = self._run(lambda: (0.0, 0.0, None), SPEC["attach_time_s"], "attach", {})
                reason = "attached" if reason == "max_duration_reached" else reason
                return self._log("attach", {}, self._result(reason, crate=f"crate_{i}"))
        return self._log("attach", {}, self._result(
            "no_crate_in_reach", detail=f"hook must be within {SPEC['attach_radius']} m of a lug"))

    def release(self) -> dict:
        if self._over():
            return self._log("release", {}, self._over())
        if self.attached is None:
            return self._log("release", {}, self._result("nothing_attached"))
        crate = self.attached
        self.attached = None
        self.tension = 0.0
        self.cable_length = min(DRUM_Z - float(self._lug(crate)[2]) - self.creep_extension,
                                SPEC["cable_length_range"][1])
        self._sync_kinematic_bodies()
        reason = self._run(lambda: (0.0, 0.0, None), SPEC["attach_time_s"], "release", {})
        reason = "released" if reason == "max_duration_reached" else reason
        return self._log("release", {}, self._result(reason, crate=f"crate_{crate}"))

    def wait(self, duration) -> dict:
        args = {"duration": duration}
        if self._over():
            return self._log("wait", args, self._over())
        try:
            duration = self._num("duration", duration, CTRL_DT, MAX_CALL_DURATION)
        except ValueError as error:
            return self._invalid("wait", args, error)
        reason = self._run(lambda: (0.0, 0.0, None), duration, "wait", args)
        return self._log("wait", args, self._result("waited" if reason == "max_duration_reached" else reason))

    def finish(self) -> dict:
        if self.finished:
            return self._log("finish", {}, {"ok": False, "termination": "episode_finished"})
        self.finished = True
        self._reward, self._outcome = self._adjudicate()
        return self._log("finish", {}, {"ok": True, "termination": "finished",
                                        "delivered": self._outcome["delivered"],
                                        "detail": self._outcome["reason"]})

    # ------------------------------------------------------------ reward (harness)
    def _adjudicate(self):
        failed = lambda reason: (0.0, {"delivered": False, "reason": reason})  # noqa: E731
        if self.cable_snapped:
            return failed("cable snapped")
        if self.terminated:
            return failed(self.terminated)
        settled = [i for i in range(len(self._crate_body)) if self._rest_time[i] >= SPEC["goal_rest_time_s"]
                   and i != self.scenario.reference_index]
        if not settled:
            return failed("no crate has sat still on the goal, released, for long enough")
        intact = [i for i in settled if not self.destroyed[i]]
        if not intact:
            return failed("crate destroyed")
        if self.scenario.task == "heaviest":
            liftable = [mass for j, mass in enumerate(self.scenario.crate_mass)
                        if j != self.scenario.reference_index and mass * G < self.scenario.cable_strength_n]
            qualifies = any(self.scenario.crate_mass[i] == max(liftable) for i in intact)
        elif self.scenario.task == "total":
            qualifies = sum(self.scenario.crate_mass[i] for i in intact) >= TOTAL_PAYLOAD_KG
        elif self.scenario.task == "window":
            qualifies = any(self.scenario.window[0] <= self.scenario.crate_mass[i] <= self.scenario.window[1]
                            for i in intact)
        else:
            qualifies = any(self.scenario.crate_mass[i] >= SPEC["required_payload_kg"] for i in intact)
        if not qualifies:
            return failed("delivered crate is below the required payload")
        efficiency = 0.5 * max(0.0, 1.0 - self.t / self.scenario.time_s) + \
            0.5 * max(0.0, 1.0 - self.energy / self.scenario.energy_j)
        return 0.5 + 0.5 * efficiency, {"delivered": True, "reason": "delivered", "efficiency": efficiency}

    def reward(self) -> float:
        """Authoritative reward: 0 unless finish() was called and the delivery succeeded."""
        return float(self._reward) if self.finished else 0.0

    def outcome(self) -> dict:
        return dict(self._outcome, t=_r(self.t), energy=_r(self.energy, 1),
                    cable_snapped=self.cable_snapped, terminated=self.terminated,
                    finished=self.finished, reward=self.reward(), mode=self.scenario.mode,
                    n_calls=len(self._call_log))

    # ------------------------------------------------------------ rendering (optional)
    def render_png(self, width: int = 960, height: int = 540):
        try:
            if self._renderer is None:
                self._renderer = mujoco.Renderer(self.model, height, width)
            camera = mujoco.MjvCamera()
            camera.lookat[:] = [2.0, 0.0, 3.5]
            camera.distance, camera.elevation, camera.azimuth = 26.0, -12.0, 90.0
            self._renderer.update_scene(self.data, camera)
            from PIL import Image
            buffer = io.BytesIO()
            Image.fromarray(self._renderer.render()).save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception as error:      # rendering is optional and never affects reward
            self._render_error = repr(error)
            return None


def _ramp(current: float, target: float, max_step: float) -> float:
    return current + max(-max_step, min(max_step, target - current))
