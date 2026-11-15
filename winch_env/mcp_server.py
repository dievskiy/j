"""MCP server exposing the winch yard's agent tools for one episode.

    WINCH_SEED=3 python -m winch_env.mcp_server                       # stdio
    python -m winch_env.mcp_server --seed 3 --transport streamable-http

Hidden values never leave the simulator. When the agent calls finish(), the
authoritative outcome is written to $WINCH_RESULT_PATH (if set) for the grader.
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
    "You operate a gantry hoist. Deliver one crate of at least the required payload to the "
    "goal on the platform: it must sit there released, upright and still, undamaged, with "
    "the cable whole, within the time and energy budgets. Crate masses, cable stiffness "
    "and the tension sensor's offset are unknown. Simulated time only advances during "
    "move_trolley, winch, attach, release and wait. get_map() returns everything static; "
    "observe() returns current readings and the trace of your last command. Call finish() "
    "once to have the delivery adjudicated."
)
VARIATION_INSTRUCTIONS = (
    "You operate a gantry hoist. Deliver cargo to the goal on the platform as the map's "
    "`task` describes: delivered crates must sit there released, upright and still, "
    "undamaged, with the cable whole, within the time and energy budgets. Hidden "
    "properties of the crates, cable and sensor are unknown; get_map() says what is "
    "known and how the hoist behaves. Simulated time only advances during move_trolley, "
    "winch, attach, release and wait. observe() returns current readings and the trace "
    "of your last command. Call finish() once to have the delivery adjudicated."
)
STATIC_KEYS = ("map",)
MAX_TRACE_SAMPLES = 40


def _thin_trace(last_command: dict | None) -> dict | None:
    """Evenly thin a long command trace; the first and last samples are always kept."""
    if not last_command or len(last_command["trace"]) <= MAX_TRACE_SAMPLES:
        return last_command
    trace = last_command["trace"]
    step = (len(trace) - 1) / (MAX_TRACE_SAMPLES - 1)
    return dict(last_command, trace=[trace[round(i * step)] for i in range(MAX_TRACE_SAMPLES)],
                trace_note=f"{len(trace)} samples thinned evenly to {MAX_TRACE_SAMPLES}; "
                           "use shorter commands for finer detail")


def build_server(seed: int, difficulty: float, result_path: str | None = None,
                 variation: str | None = None):
    ep = Episode(seed, difficulty, variation)
    srv = _Server("winch-yard", instructions=VARIATION_INSTRUCTIONS if variation else INSTRUCTIONS)

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
        """Static information: yard geometry, crate positions, the goal, the hoist
        specification (ratings, speeds, ramps, cable and sensor behaviour), sensor noise
        and budgets. Call once."""
        return ep.observe()["map"]

    @tool
    def observe() -> dict:
        """Current readings: trolley position, cable length, hook position, tension sensor
        reading, what is attached, crate positions, budgets remaining, and the trace of
        the last command. Does not advance time."""
        o = ep.observe()
        return {k: _thin_trace(v) if k == "last_command" else v
                for k, v in o.items() if k not in STATIC_KEYS}

    @tool
    def move_trolley(x: float, speed_limit: float, max_duration: float) -> dict:
        """Move the trolley along the rail to x [m], never faster than speed_limit [m/s].
        Returns when arrived or after max_duration [s, <= 60]."""
        return ep.move_trolley(x, speed_limit, max_duration)

    @tool
    def winch(length_change: float, speed_limit: float, max_duration: float,
              stop_tension: float | None = None) -> dict:
        """Pay out cable (positive length_change, metres) or reel it in (negative), never
        faster than speed_limit [m/s]. If stop_tension [N] is given, the drum starts
        braking as soon as the tension sensor reading reaches it."""
        return ep.winch(length_change, speed_limit, max_duration, stop_tension)

    @tool
    def attach() -> dict:
        """Hook onto the crate whose lug is within reach of the hook."""
        return ep.attach()

    @tool
    def release() -> dict:
        """Unhook the attached crate. A crate released in the air falls."""
        return ep.release()

    @tool
    def wait(duration: float) -> dict:
        """Let duration seconds (0.02..60) pass."""
        return ep.wait(duration)

    @tool
    def finish() -> dict:
        """Request adjudication of the delivery. Ends the episode; counted once."""
        result = ep.finish()
        if result_path:
            with open(result_path, "w") as f:
                json.dump({"reward": ep.reward(), "outcome": ep.outcome(), "seed": seed,
                           "difficulty": difficulty, "course": "winch_yard",
                           "variation": variation}, f)
        return result

    return srv, ep


def winch_views(ep, data) -> list:
    """The whole yard from the side, and a closer view that follows the hook."""
    hook = data.mocap_pos[1]
    return [{"lookat": (2.0, 0.0, 3.5), "distance": 26.0, "elevation": -12.0, "azimuth": 90.0},
            {"lookat": (hook[0], 0.0, max(hook[2] - 0.5, 1.0)), "distance": 9.0,
             "elevation": -15.0, "azimuth": 70.0}]


def record(ep: Episode, path: str):
    """Attach a background video recorder to the episode."""
    from rover_env.recorder import Recorder
    return Recorder(ep, path, step_method="_physics_step",
                    tools=("move_trolley", "winch", "attach", "release", "wait", "finish"),
                    steps_per_frame=50, views=winch_views)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=int(os.environ.get("WINCH_SEED", "0")))
    parser.add_argument("--difficulty", type=float,
                        default=float(os.environ.get("WINCH_DIFFICULTY", "0.5")))
    parser.add_argument("--transport", default=os.environ.get("WINCH_TRANSPORT", "stdio"))
    parser.add_argument("--variation", default=os.environ.get("WINCH_VARIATION") or None)
    args = parser.parse_args(argv)
    srv, _ = build_server(args.seed, args.difficulty, os.environ.get("WINCH_RESULT_PATH"),
                          args.variation)
    srv.run(transport=args.transport)


if __name__ == "__main__":
    main()
