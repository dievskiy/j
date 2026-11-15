"""Episode: MuJoCo simulation, vehicle model, agent tools and reward.

Agent-facing tools (the ONLY interface policies/agents use):
    observe(include_image=False) -> dict
    drive_to(x, y, speed_limit, max_duration) -> dict
    brake() -> dict
    wait(duration) -> dict
    finish() -> dict

Harness-only (not agent tools): reward(), outcome(), render_png().
"""
from __future__ import annotations

import io
import math
import os

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
import mujoco  # noqa: E402

from .world import G, NOMINAL, generate  # noqa: E402
from .env_constants import BARRIER_STANDOFF, SENSOR_RANGE  # noqa: E402

PHYS_DT = 0.005
SUBSTEPS = 4                     # control period = 0.02 s
CTRL_DT = PHYS_DT * SUBSTEPS
TRACE_EVERY = 5                  # trace sample every 0.1 s
MAX_CALL_DURATION = 60.0
MAX_TRACE = 300


def _r(v, n=3):
    return round(float(v), n)

# vehicle model constants (not hidden; part of the nominal model)
K_V = 3.0          # speed loop gain (1/s)
K_LAT = 10.0       # lateral tyre stiffness (1/s)
K_YAW = 6.0        # yaw-rate loop gain (1/s)
K_HEAD = 2.0       # heading -> yaw-rate gain (1/s)
C_RR = 0.015       # rolling resistance coefficient
IZ = 30.0          # yaw inertia used by the yaw loop
TRACK_HALF = 0.55
ETA = 0.8          # drivetrain efficiency
P_IDLE = 40.0      # W, electronics: charged whenever simulated time advances
ARRIVE_TOL = 0.35
# 1-sigma noise of each reading in observe() and in command traces (published to the agent)
SENSOR_NOISE_STD = {"position_m": 0.05, "heading_rad": 0.01, "pitch_roll_rad": 0.005,
                    "speed_m_s": 0.03, "yaw_rate_rad_s": 0.01,
                    "note": "readings are fixed for a given simulated time; a rover at rest "
                            "still shows speeds of this size"}
STOP_SPEED = 0.1      # m/s horizontal: one threshold for every "at rest" decision
STOP_YAW_RATE = 0.05  # rad/s
CARGO_HARSH_ACC = 7.0     # m/s^2 horizontal cargo accel above which damage accrues
CARGO_DAMAGE_RATE = 0.08  # damage per (m/s^2 above threshold) per second


class Episode:
    TOOLS = ("observe", "drive_to", "brake", "wait", "finish")

    def __init__(self, seed: int, difficulty: float = 0.5, course: str = "ramp"):
        self.scenario = generate(seed, difficulty, course)
        self._lay = self.scenario.layout
        self._hid = self.scenario.hidden
        self._bud = self.scenario.budgets
        self.model = mujoco.MjModel.from_xml_string(self._lay.mjcf())
        self.data = mujoco.MjData(self.model)
        m = self.model
        self._rover = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "rover")
        self._cargo = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "cargo")
        self._wheels = {mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, n)
                        for n in ("w_fl", "w_fr", "w_rl", "w_rr")}
        self._chassis = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "chassis")
        self._cargo_geom = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "cargo")
        self._terrain = {i for i in range(m.ngeom)
                         if m.geom_bodyid[i] == 0 and m.geom_contype[i] != 0}
        self._mass = float(m.body_subtreemass[self._rover] + m.body_subtreemass[self._cargo])
        self._map = self._lay.public_map()
        self._crates = {name: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, name)
                        for name in self._lay.crate_bodies}
        self._renderer = None

        self.step_count = 0
        self.energy = 0.0
        self.cargo_damage = 0.0
        self.cargo_destroyed = False
        self.violation = None        # hard-constraint violation string
        self.terminated = None       # reason the episode ended (sim side)
        self.finished = False
        self._reward = 0.0
        self._outcome = {"delivered": False, "reason": "finish() not called"}
        self._last_cmd = None
        self._call_log = []
        self._n_ground = 0.0
        self._prev_cargo_v = np.zeros(3)
        # settle physics (not charged; happens before the episode starts)
        for _ in range(200):
            mujoco.mj_step(m, self.data)
        self.data.time = 0.0
        self._prev_cargo_v = self.data.qvel[6:9].copy()

    # ------------------------------------------------------------ state helpers
    @property
    def t(self) -> float:
        return self.step_count * PHYS_DT

    def _pose(self):
        q = self.data.qpos
        R = self.data.xmat[self._rover].reshape(3, 3)
        yaw = math.atan2(R[1, 0], R[0, 0])
        pitch = -math.asin(max(-1.0, min(1.0, R[2, 0])))
        roll = math.atan2(R[2, 1], R[2, 2])
        return float(q[0]), float(q[1]), float(q[2]), yaw, pitch, roll, R

    def _body_vel(self):
        R = self.data.xmat[self._rover].reshape(3, 3)
        v = self.data.qvel[0:3]
        w_local = self.data.qvel[3:6]
        return float(v @ R[:, 0]), float(v @ R[:, 1]), float(w_local[2])

    def _contacts(self):
        """Return (wheel normal force sum, chassis-terrain contact, cargo-terrain contact)."""
        d, m = self.data, self.model
        n_sum = 0.0
        chassis_hit = cargo_hit = False
        f6 = np.zeros(6)
        for i in range(d.ncon):
            c = d.contact[i]
            g1, g2 = c.geom1, c.geom2
            if g1 in self._wheels or g2 in self._wheels:
                other = g2 if g1 in self._wheels else g1
                if other in self._terrain:
                    mujoco.mj_contactForce(m, d, i, f6)
                    n_sum += abs(f6[0])
            if (g1 == self._chassis and g2 in self._terrain) or \
               (g2 == self._chassis and g1 in self._terrain):
                chassis_hit = True
            if (g1 == self._cargo_geom and g2 in self._terrain) or \
               (g2 == self._cargo_geom and g1 in self._terrain):
                cargo_hit = True
        return n_sum, chassis_hit, cargo_hit

    def _noise(self, k, n):
        r = np.random.default_rng([self.scenario.seed, 99, int(k)])
        return r.standard_normal(n)

    # ------------------------------------------------------------ physics core
    def _substep(self, v_d, r_cmd, brake_mode):
        """Apply vehicle model forces for one physics step and integrate.
        Returns the commanded longitudinal accel (what the controller asked for)."""
        hid = self._hid
        R = self.data.xmat[self._rover].reshape(3, 3)
        f, l, u = R[:, 0], R[:, 1], R[:, 2]
        v_long, v_lat, r = self._body_vel()
        N = self._n_ground
        m = self._mass
        g_long = -G * f[2]  # gravity accel along forward axis
        if brake_mode:
            a_cmd = -NOMINAL["max_brake_decel"] * math.tanh(v_long / 0.05)
        else:
            a_cmd = float(np.clip(K_V * (v_d - v_long), -NOMINAL["max_brake_decel"],
                                  NOMINAL["max_drive_accel"]))
        F = m * (a_cmd - g_long)   # tyre force needed (gravity feed-forward)
        # regime: braking if the requested force opposes motion (or holding still)
        if abs(v_long) > 0.05:
            braking = F * v_long < 0
        else:
            braking = brake_mode or v_d == 0.0
        if braking:
            cap = m * hid.brake_decel          # hidden brake fault applies here
        else:
            cap = m * NOMINAL["max_drive_accel"]
        F = float(np.clip(F, -cap, cap))
        F_lat = -m * K_LAT * v_lat
        # surface under the rover: ice lowers friction, mud adds viscous drag (both hidden)
        surface = self._lay.surface_at(float(self.data.qpos[0]), float(self.data.qpos[1]))
        friction = min(hid.tire_friction, hid.ice_friction) if surface == "ice" else hid.tire_friction
        drag = hid.mud_drag if surface == "mud" else 0.0
        # friction circle (hidden traction fault applies here)
        fmax = friction * N
        mag = math.hypot(F, F_lat)
        if mag > fmax:
            s = fmax / mag if mag > 1e-9 else 0.0
            F *= s
            F_lat *= s
        F_rr = -C_RR * N * math.tanh(v_long / 0.05)
        # yaw: hidden steering bias adds a speed-proportional yaw-rate offset
        r_target = r_cmd + hid.steering_bias * v_long
        tau = IZ * K_YAW * (r_target - r)
        tmax = friction * N * TRACK_HALF
        tau = float(np.clip(tau, -tmax, tmax))
        force = (F + F_rr - m * drag * v_long) * f + (F_lat - m * drag * v_lat) * l
        if surface == "wind":
            wx, wy = self._lay.wind_direction
            force = force + m * hid.wind_accel * np.array([wx, wy, 0.0])
        self.data.xfrc_applied[self._rover, 0:3] = force
        self.data.xfrc_applied[self._rover, 3:6] = tau * u
        # energy: motor power (no regeneration) + yaw actuation + idle
        p = P_IDLE
        if not braking:
            p += max(F * v_long, 0.0) / ETA
        p += abs(tau * r) / ETA * 0.5
        self.energy += p * PHYS_DT
        mujoco.mj_step(self.model, self.data)
        self.step_count += 1
        return a_cmd

    def _check_constraints(self, chassis_hit, cargo_hit):
        x, y, z, yaw, pitch, roll, R = self._pose()
        b = self._lay.bounds
        if cargo_hit:
            self.cargo_destroyed = True
            return "cargo_dropped"
        if z < -0.5:
            return "left_drivable_surface"
        if R[2, 2] < 0.5:
            return "rollover"
        if chassis_hit:
            return "chassis_collision"
        if not (b[0] <= x <= b[1] and b[2] <= y <= b[3]):
            return "out_of_bounds"
        cz = self.data.xpos[self._cargo][2]
        if cz < z - 0.3:
            self.cargo_destroyed = True
            return "cargo_fell_off"
        return None

    def _run(self, controller, max_duration, tool, args):
        """Advance simulated time with `controller(state)->(v_d, r_cmd, brake_mode, done_reason)`.
        Budgets and hard constraints are enforced every physics step."""
        trace = []
        t0 = self.t
        reason = None
        n_ctrl = int(_r(max_duration / CTRL_DT))
        stats = {"cmd_speed": [], "meas_speed": [], "cmd_yaw_rate": [], "meas_yaw_rate": []}
        for k in range(max(n_ctrl, 0)):
            st = self._state()
            v_d, r_cmd, brake_mode, done = controller(st)
            if done:
                reason = done
                break
            for _ in range(SUBSTEPS):
                self._n_ground, chassis_hit, cargo_hit = self._contacts()
                a_cmd = self._substep(v_d, r_cmd, brake_mode)
                viol = self._check_constraints(chassis_hit, cargo_hit)
                if viol:
                    self.violation = viol
                    self.terminated = "hard_constraint_violated:" + viol
                elif self.t >= self._bud.time_s - 1e-9:
                    self.terminated = "time_budget_exhausted"
                elif self.energy >= self._bud.energy_j:
                    self.terminated = "energy_budget_exhausted"
                if self.terminated:
                    break
            self._update_cargo()
            if self.terminated:
                reason = self.terminated
                break
            v_long, v_lat, r = self._body_vel()
            stats["cmd_speed"].append(v_d)
            stats["meas_speed"].append(v_long)
            stats["cmd_yaw_rate"].append(r_cmd)
            stats["meas_yaw_rate"].append(r)
            if k % TRACE_EVERY == 0 and len(trace) < MAX_TRACE:
                trace.append(self._trace_sample(v_d, r_cmd, a_cmd, brake_mode))
        else:
            reason = "max_duration_reached"
        if reason is None:
            reason = "max_duration_reached"
        if not trace or trace[-1]["t"] != _r(self.t, 3):
            if len(trace) < MAX_TRACE + 1 and not self.terminated:
                trace.append(self._trace_sample(0.0, 0.0, 0.0, False))
        dur = self.t - t0
        self._last_cmd = {
            "tool": tool, "args": args, "termination": reason,
            "start_t": _r(t0, 3), "duration": _r(dur, 3),
            "trace_note": "samples every 0.1 s: commanded speed / yaw-rate / longitudinal "
                          "accel vs measured (noisy) values",
            "trace": trace,
        }
        return reason

    def _trace_sample(self, v_d, r_cmd, a_cmd, brake_mode):
        v_long, v_lat, r = self._body_vel()
        # IMU-like measured longitudinal accel (including gravity along the axis, like a
        # real accelerometer would NOT — we report kinematic accel only)
        a = self.data.qacc[0:3] @ self.data.xmat[self._rover].reshape(3, 3)[:, 0]
        n = self._noise(self.step_count, 4)
        x, y, z, yaw, pitch, roll, _ = self._pose()
        return {
            "t": _r(self.t, 3),
            "cmd_speed": _r(float(v_d), 3),
            "meas_speed": _r(v_long + 0.03 * n[0], 3),
            "cmd_yaw_rate": _r(float(r_cmd), 3),
            "meas_yaw_rate": _r(r + 0.01 * n[1], 4),
            "cmd_accel": _r(float(a_cmd), 3),
            "meas_accel": _r(float(a) + 0.08 * n[2], 3),
            "brake": bool(brake_mode),
            "x": _r(x + 0.03 * n[3], 2), "y": _r(y + 0.03 * self._noise(self.step_count + 7, 1)[0], 2),
        }

    def _update_cargo(self):
        v = self.data.qvel[6:9].copy()
        a = (v - self._prev_cargo_v) / CTRL_DT
        self._prev_cargo_v = v
        ah = math.hypot(a[0], a[1])
        if ah > CARGO_HARSH_ACC:
            self.cargo_damage += CARGO_DAMAGE_RATE * (ah - CARGO_HARSH_ACC) * CTRL_DT
        if self.cargo_damage >= 1.0:
            self.cargo_damage = 1.0
            self.cargo_destroyed = True

    def _state(self):
        x, y, z, yaw, pitch, roll, _ = self._pose()
        v_long, v_lat, r = self._body_vel()
        return dict(x=x, y=y, z=z, yaw=yaw, v=v_long, v_lat=v_lat, r=r, t=self.t)

    # ------------------------------------------------------------ validation
    def _over(self):
        if self.finished:
            return {"ok": False, "termination": "episode_over", "detail": "finish() already called"}
        if self.terminated:
            return {"ok": False, "termination": "episode_over", "detail": self.terminated}
        return None

    @staticmethod
    def _num(name, v, lo, hi):
        if isinstance(v, bool):
            raise ValueError(f"{name} must be a number")
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(f):
            raise ValueError(f"{name} must be finite")
        if not (lo <= f <= hi):
            raise ValueError(f"{name} must be in [{lo}, {hi}]")
        return f

    def _result(self, reason):
        return {"ok": not reason.startswith(("hard_constraint", "time_budget", "energy_budget")),
                "termination": reason, "t": _r(self.t, 3),
                "cargo_in_goal_circle": self._cargo_in_goal(),
                "time_remaining": _r(max(self._bud.time_s - self.t, 0.0), 3),
                "energy_remaining": _r(max(self._bud.energy_j - self.energy, 0.0), 1)}

    def _detected_barriers(self, x: float, y: float) -> list:
        """Barriers the rover's sensors can see: those within SENSOR_RANGE, or all of them
        while it is at rest inside the lookout."""
        lookout = self._lay.lookout
        v_long, v_lat, _ = self._body_vel()
        at_lookout = (lookout is not None and math.hypot(x - lookout[0], y - lookout[1]) <= lookout[2]
                      and math.hypot(v_long, v_lat) < STOP_SPEED)
        return [b for b in self._lay.barriers
                if at_lookout or math.hypot(b[0] - x, b[1] - y) <= SENSOR_RANGE]

    def _cargo_in_goal(self) -> bool:
        cx, cy, _ = self.data.xpos[self._cargo]
        gx, gy = self._lay.goal
        return bool(math.hypot(cx - gx, cy - gy) <= self._lay.goal_radius)

    def _log(self, tool, args, res):
        self._call_log.append((tool, args, res.get("termination")))
        return res

    # ------------------------------------------------------------ agent tools
    def observe(self, include_image: bool = False) -> dict:
        x, y, z, yaw, pitch, roll, _ = self._pose()
        v_long, v_lat, r = self._body_vel()
        n = self._noise(self.step_count, 8)  # same sample for the same sim time
        cargo_on = (self.data.xpos[self._cargo][2] > z) and not self.cargo_destroyed
        obs = {
            "t": _r(self.t, 3),
            "pose": {"x": _r(x + 0.05 * n[0], 3), "y": _r(y + 0.05 * n[1], 3),
                     "z": _r(z + 0.05 * n[2], 3), "heading": _r(yaw + 0.01 * n[3], 4),
                     "pitch": _r(pitch + 0.005 * n[4], 4), "roll": _r(roll + 0.005 * n[5], 4)},
            "velocity": {"forward": _r(v_long + 0.03 * n[6], 3),
                         "lateral": _r(v_lat + 0.03 * n[7], 3),
                         "yaw_rate": _r(r + 0.01 * self._noise(self.step_count + 3, 1)[0], 4)},
            "time_remaining": _r(max(self._bud.time_s - self.t, 0.0), 3),
            "energy_remaining": _r(max(self._bud.energy_j - self.energy, 0.0), 1),
            "budgets": {"time_s": self._bud.time_s, "energy_j": self._bud.energy_j},
            "cargo": {"on_board": bool(cargo_on), "in_goal_circle": self._cargo_in_goal(),
                      "condition": "destroyed" if self.cargo_destroyed else
                      ("damaged" if self.cargo_damage > 0.0 else "intact"),
                      "damage": _r(self.cargo_damage, 3),
                      "note": "damage in [0,1] lowers the score proportionally; only destroyed "
                              "cargo (damage 1.0, or dropped) fails the delivery"},
            "episode": {"finished": self.finished, "ended": self.terminated},
            "detected_barriers": [{"x": _r(bx, 2), "y": _r(by, 2)}
                                  for bx, by in self._detected_barriers(x, y)],
            "crates": {name: {"x": _r(self.data.xpos[body][0], 2), "y": _r(self.data.xpos[body][1], 2)}
                       for name, body in self._crates.items()},
            "last_command": self._last_cmd,
            "vehicle_nominal_spec": dict(NOMINAL, note="actual dynamics may differ from nominal"),
            "sensor_noise_std": SENSOR_NOISE_STD,
            "map": self._map,
        }
        if include_image:
            import base64
            png = self.render_png()
            obs["image_png_base64"] = base64.b64encode(png).decode() if png else None
        return obs

    def drive_to(self, x, y, speed_limit, max_duration) -> dict:
        args = {"x": x, "y": y, "speed_limit": speed_limit, "max_duration": max_duration}
        o = self._over()
        if o:
            return self._log("drive_to", args, o)
        b = self._lay.bounds
        try:
            x = self._num("x", x, b[0], b[1])
            y = self._num("y", y, b[2], b[3])
            speed_limit = self._num("speed_limit", speed_limit, 0.05, NOMINAL["max_speed"])
            max_duration = self._num("max_duration", max_duration, CTRL_DT, MAX_CALL_DURATION)
        except ValueError as e:
            return self._log("drive_to", args, {"ok": False, "termination": "invalid_input", "detail": str(e)})
        tx, ty = x, y
        a_plan = NOMINAL["planned_decel"]

        approaching, passed, blocked = [False], [False], [False]

        def at_rest(st):
            return math.hypot(st["v"], st["v_lat"]) < STOP_SPEED and abs(st["r"]) < STOP_YAW_RATE

        def ctrl(st):
            dx, dy = tx - st["x"], ty - st["y"]
            D = math.hypot(dx, dy)
            if D < ARRIVE_TOL and not passed[0]:
                # inside tolerance: brake until at rest (horizontal speed and spin)
                if at_rest(st):
                    return 0.0, 0.0, True, "arrived"
                return 0.0, 0.0, True, None
            e = math.atan2(dy, dx) - st["yaw"]
            e = (e + math.pi) % (2 * math.pi) - math.pi
            # Overshoot: only if, during THIS call, the rover was driving toward the target
            # and then carried past it. It then stops and reports instead of turning around
            # (turning in place where it ended up, e.g. on a ramp, could be unsafe).
            # A target that is already beside/behind the rover when the call starts is not an
            # overshoot: the rover turns in place and drives to it.
            if abs(e) < math.pi / 2 and st["v"] > 0.3:
                approaching[0] = True
            elif approaching[0] and abs(e) > math.pi / 2 and st["v"] > STOP_SPEED:
                passed[0] = True
            if passed[0]:
                if at_rest(st):
                    return 0.0, 0.0, False, "overshot_target"
                return 0.0, 0.0, False, None
            if blocked[0] or self._barrier_ahead(st):
                blocked[0] = True
                if at_rest(st):
                    return 0.0, 0.0, True, "obstacle_ahead"
                return 0.0, 0.0, True, None
            v_d = min(speed_limit, math.sqrt(2 * a_plan * max(D - ARRIVE_TOL * 0.5, 0.0)))
            if abs(e) > 0.6:
                v_d = 0.0
            else:
                v_d *= math.cos(e)
            r_cmd = float(np.clip(K_HEAD * e, -NOMINAL["max_turn_rate"], NOMINAL["max_turn_rate"]))
            return v_d, r_cmd, False, None

        reason = self._run(ctrl, max_duration, "drive_to", args)
        res = self._result(reason)
        x_now, y_now = self._pose()[:2]
        res["distance_to_target"] = _r(math.hypot(tx - x_now, ty - y_now), 2)
        if reason == "arrived" and self._last_cmd["duration"] == 0.0:
            res["detail"] = "already at rest within the arrival tolerance of the target; no motion"
        if reason == "overshot_target":
            res["detail"] = ("carried past the target and stopped; a new drive_to to a point "
                             "behind the rover will turn in place and drive back")
        return self._log("drive_to", args, res)

    def _barrier_ahead(self, st) -> bool:
        """True if a barrier lies within BARRIER_STANDOFF in the direction of travel."""
        for bx, by in self._lay.barriers:
            dx, dy = bx - st["x"], by - st["y"]
            ahead = dx * math.cos(st["yaw"]) + dy * math.sin(st["yaw"])
            side = -dx * math.sin(st["yaw"]) + dy * math.cos(st["yaw"])
            if 0.0 < ahead < BARRIER_STANDOFF and abs(side) < 2.0:
                return True
        return False

    def brake(self) -> dict:
        o = self._over()
        if o:
            return self._log("brake", {}, o)

        def ctrl(st):
            if math.hypot(st["v"], st["v_lat"]) < STOP_SPEED and abs(st["r"]) < STOP_YAW_RATE:
                return 0.0, 0.0, True, "stopped"
            return 0.0, 0.0, True, None

        reason = self._run(ctrl, 15.0, "brake", {})
        return self._log("brake", {}, self._result(reason))

    def wait(self, duration) -> dict:
        args = {"duration": duration}
        o = self._over()
        if o:
            return self._log("wait", args, o)
        try:
            duration = self._num("duration", duration, CTRL_DT, MAX_CALL_DURATION)
        except ValueError as e:
            return self._log("wait", args, {"ok": False, "termination": "invalid_input", "detail": str(e)})
        reason = self._run(lambda st: (0.0, 0.0, False, None), duration, "wait", args)
        if reason == "max_duration_reached":
            reason = "waited"
        return self._log("wait", args, self._result(reason))

    def finish(self) -> dict:
        o = self._over()
        if o and self.finished:
            return self._log("finish", {}, o)
        self.finished = True
        self._reward, self._outcome = self._adjudicate()
        res = {"ok": True, "termination": "finished", "delivered": self._outcome["delivered"],
               "detail": self._outcome["reason"], "reward": _r(self._reward, 4)}
        return self._log("finish", {}, res)

    # ------------------------------------------------------------ reward (harness)
    def _adjudicate(self):
        if self.violation:
            return 0.0, {"delivered": False, "reason": "hard constraint violated: " + self.violation}
        if self.terminated:
            return 0.0, {"delivered": False, "reason": self.terminated}
        if self.t > self._bud.time_s or self.energy > self._bud.energy_j:
            return 0.0, {"delivered": False, "reason": "over budget"}
        if self.cargo_destroyed or self.cargo_damage >= 1.0:
            return 0.0, {"delivered": False, "reason": "cargo destroyed"}
        cx, cy, cz = self.data.xpos[self._cargo]
        rz = self.data.xpos[self._rover][2]
        gx, gy = self._lay.goal
        if math.hypot(cx - gx, cy - gy) > self._lay.goal_radius:
            return 0.0, {"delivered": False, "reason": "cargo not inside goal circle"}
        if not (cz > rz and abs(cz - 0.0) < 1.5):
            return 0.0, {"delivered": False, "reason": "cargo not resting on rover at goal level"}
        v_long, v_lat, r = self._body_vel()
        if math.hypot(v_long, v_lat) > 0.3:
            return 0.0, {"delivered": False, "reason": "rover still moving"}
        eff = 0.5 * max(0.0, 1.0 - self.t / self._bud.time_s) + \
            0.5 * max(0.0, 1.0 - self.energy / self._bud.energy_j)
        # fragile cargo: damage reduces efficiency credit, not the delivery floor
        eff *= (1.0 - self.cargo_damage)
        return 0.5 + 0.5 * eff, {"delivered": True, "reason": "delivered", "efficiency": eff}

    def reward(self) -> float:
        """Authoritative reward. 0 unless finish() was called and delivery succeeded."""
        return float(self._reward) if self.finished else 0.0

    def outcome(self) -> dict:
        return dict(self._outcome, t=_r(self.t, 3), energy=_r(self.energy, 1),
                    cargo_damage=_r(self.cargo_damage, 4), violation=self.violation,
                    terminated=self.terminated, finished=self.finished, reward=self.reward(),
                    mode=self._hid.mode, n_calls=len(self._call_log))

    # ------------------------------------------------------------ rendering (optional)
    def render_png(self, camera: str = "chase", width: int = 640, height: int = 480):
        try:
            if self._renderer is None:
                self._renderer = mujoco.Renderer(self.model, height, width)
            cam = mujoco.MjvCamera()
            x, y, z, yaw, *_ = self._pose()
            if camera == "overview":
                view = self._lay.overview_camera
                cam.lookat[:] = view["lookat"]
                cam.distance, cam.elevation, cam.azimuth = (
                    view["distance"], view["elevation"], view["azimuth"])
            else:
                cam.lookat[:] = [x, y, z]
                cam.distance = 10
                cam.elevation = -35
                cam.azimuth = math.degrees(yaw)
            self._renderer.update_scene(self.data, cam)
            img = self._renderer.render()
            from PIL import Image
            buf = io.BytesIO()
            Image.fromarray(img).save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:  # rendering is optional and never affects reward
            self._render_error = repr(e)
            return None
