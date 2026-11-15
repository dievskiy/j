"""Thin MCP server exposing exactly the five agent tools of one Episode.

    ROVER_SEED=6 ROVER_DIFFICULTY=0.5 python -m rover_env.mcp_server            # stdio
    python -m rover_env.mcp_server --seed 6 --transport streamable-http

The hidden dynamics are never exposed. When the agent calls finish(), the
authoritative outcome is also written to $ROVER_RESULT_PATH (if set) for the
harness/grader; the reward is computed only from simulator state.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import threading

from .env import Episode

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

INSTRUCTIONS = (
    "You control a wheeled rover carrying fragile cargo. Deliver the cargo so it comes to "
    "rest inside the goal circle, not destroyed, within the time and energy budgets. Cargo "
    "damage lowers the score. Vehicle dynamics and surface properties may differ from nominal. "
    "Simulated time only advances during drive_to, brake "
    "and wait. Call finish() exactly when you want the delivery adjudicated; it ends the "
    "episode. get_map() returns everything static (map, nominal vehicle spec, controller "
    "description, sensor noise); observe() returns the current readings and the "
    "commanded-vs-measured trace of your last command."
)


STATIC_KEYS = ("map", "vehicle_nominal_spec", "sensor_noise_std", "budgets")


MAX_TRACE_SAMPLES = 40   # keeps observe() small enough for an agent to read in one go


def _thin_trace(last_command: dict | None) -> dict | None:
    """Evenly thin a long command trace; the first and last samples are always kept."""
    if not last_command or len(last_command["trace"]) <= MAX_TRACE_SAMPLES:
        return last_command
    trace = last_command["trace"]
    step = (len(trace) - 1) / (MAX_TRACE_SAMPLES - 1)
    thinned = [trace[round(i * step)] for i in range(MAX_TRACE_SAMPLES)]
    return dict(last_command, trace=thinned,
                trace_note=f"{len(trace)} samples thinned evenly to {MAX_TRACE_SAMPLES}; "
                           "use shorter commands for finer detail")


def build_server(seed: int, difficulty: float, result_path: str | None = None,
                 course: str = "ramp"):
    ep = Episode(seed, difficulty, course)
    srv = _Server("rover-cargo", instructions=INSTRUCTIONS)

    def _write_result():
        if result_path:
            with open(result_path, "w") as f:
                json.dump({"reward": ep.reward(), "outcome": ep.outcome(), "seed": seed,
                           "difficulty": difficulty, "course": course}, f)

    lock = threading.Lock()

    def tool(fn):
        """Register a tool whose calls are serialised: an agent may issue several tool
        calls at once, and the simulator must only ever run one."""
        @functools.wraps(fn)
        def serialised(*args, **kwargs):
            with lock:
                return fn(*args, **kwargs)
        return srv.tool()(serialised)

    @tool
    def get_map() -> dict:
        """Static information that never changes during the episode: map geometry and
        surfaces, start, goal, calibration area, routes, drive_to controller description,
        nominal vehicle spec and sensor noise levels. Call once."""
        o = ep.observe()
        return {k: o[k] for k in STATIC_KEYS if k in o}

    @tool
    def observe() -> dict:
        """Sensor snapshot at the current simulated time: noisy pose and velocity, budgets
        remaining, cargo condition, and the commanded-vs-measured trace of the last
        command. Does not advance time; repeated calls return the same sample."""
        o = ep.observe()
        return {k: _thin_trace(v) if k == "last_command" else v
                for k, v in o.items() if k not in STATIC_KEYS}

    @tool
    def drive_to(x: float, y: float, speed_limit: float, max_duration: float) -> dict:
        """Drive toward (x, y) [m] with the onboard tracking controller, never exceeding
        speed_limit [m/s, 0.05..5]. Returns when arrived (at rest within 0.35 m), carried past the target (overshot_target),
        max_duration [s, <=60]
        elapsed, a budget ran out, or a hard constraint was violated."""
        return ep.drive_to(x, y, speed_limit, max_duration)

    @tool
    def brake() -> dict:
        """Apply full brakes until stopped (max 15 s)."""
        return ep.brake()

    @tool
    def wait(duration: float) -> dict:
        """Hold position (brakes) for duration seconds (0.02..60). Time and idle energy are charged."""
        return ep.wait(duration)

    @tool
    def finish() -> dict:
        """Request adjudication of the delivery. Ends the episode; counted once."""
        r = ep.finish()
        _write_result()
        return r

    return srv, ep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=int(os.environ.get("ROVER_SEED", "0")))
    ap.add_argument("--difficulty", type=float, default=float(os.environ.get("ROVER_DIFFICULTY", "0.5")))
    ap.add_argument("--transport", default=os.environ.get("ROVER_TRANSPORT", "stdio"))
    a = ap.parse_args(argv)
    srv, _ = build_server(a.seed, a.difficulty, os.environ.get("ROVER_RESULT_PATH"),
                          os.environ.get("ROVER_COURSE", "ramp"))
    srv.run(transport=a.transport)


if __name__ == "__main__":
    main()
