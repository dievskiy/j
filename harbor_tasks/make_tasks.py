"""Generate one Harbor task directory per seed under harbor_tasks/tasks/.

    python harbor_tasks/make_tasks.py 1 2 5
    python harbor_tasks/make_tasks.py --course serpentine 1 2 5
    python harbor_tasks/make_tasks.py --course winch_yard --variation worn_cable 0 1

Layout per task: the simulator runs in a sidecar container (`rover-sim`) that the
agent can reach only over MCP. The sidecar writes the authoritative result to a
volume that is mounted read-only in the agent container, where the verifier reads it.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGES = ("rover_env", "winch_env")     # both go into the simulator image
WINCH_COURSE = "winch_yard"

INSTRUCTION = """# Rover cargo delivery

You control a wheeled rover carrying fragile cargo in a physics simulation. The rover
is reachable only through the `rover` MCP server (tools: `get_map`, `observe`, `drive_to`,
`brake`, `wait`, `finish`).

Deliver the cargo so that it comes to rest inside the goal circle, not destroyed, within the
time and energy budgets. Cargo damage lowers the score. Faster and more energy-efficient
deliveries score higher; a failed delivery scores zero.

Vehicle dynamics, surface properties and obstacles may differ from what you expect;
`get_map` describes what is known and what is not. Simulated time advances only during `drive_to`, `brake` and
`wait`. `get_map` returns the static map, the nominal vehicle specification, a description
of the onboard controller and the sensor noise levels. `observe` returns the current
readings and the commanded-versus-measured trace of your last command.

Call `finish` once, when you want the delivery adjudicated. It ends the episode.
"""

WINCH_INSTRUCTION = """# Hoist delivery

You operate a gantry hoist in a physics simulation. It is reachable only through the
`hoist` MCP server (tools: `get_map`, `observe`, `move_trolley`, `winch`, `attach`,
`release`, `wait`, `finish`).

Deliver one crate of at least the required payload to the goal on the platform. It must
sit there released from the hook, upright and still, undamaged, with the cable whole,
within the time and energy budgets. Faster and more energy-efficient deliveries score
higher; a failed delivery scores zero.

The crates' masses, the cable's stiffness and the tension sensor's offset are unknown;
`get_map` describes what is known and how the hoist behaves. Simulated time advances only
during `move_trolley`, `winch`, `attach`, `release` and `wait`. `observe` returns the
current readings and the trace of your last command.

Call `finish` once, when you want the delivery adjudicated. It ends the episode.
"""

WINCH_VARIATION_INSTRUCTION = """# Hoist delivery

You operate a gantry hoist in a physics simulation. It is reachable only through the
`hoist` MCP server (tools: `get_map`, `observe`, `move_trolley`, `winch`, `attach`,
`release`, `wait`, `finish`).

Deliver cargo to the goal on the platform as the `task` entry of `get_map` describes.
Delivered crates must sit there released from the hook, upright and still, undamaged,
with the cable whole, within the time and energy budgets. Faster and more
energy-efficient deliveries score higher; a failed delivery scores zero.

Some properties of the crates, the cable and the tension sensor are unknown; `get_map`
describes what is known and how the hoist behaves. Simulated time advances only during
`move_trolley`, `winch`, `attach`, `release` and `wait`. `observe` returns the current
readings and the trace of your last command.

Call `finish` once, when you want the delivery adjudicated. It ends the episode.
"""

TASK_TOML = """schema_version = "1.1"
artifacts = [{{ source = "/result/rollout.mp4", destination = "rollout.mp4", service = "rover-sim" }}]

[task]
name = "{category}/{course}-seed{seed}"
description = "{description}"
authors = []
keywords = ["mujoco", "{category}", "diagnosis"]

[metadata]
seed = {seed}
difficulty = {difficulty}
course = "{course}"
variation = "{variation}"

[verifier]
timeout_sec = 120.0

# Before artifacts are collected, let the sidecar finish rendering the rollout video.
[[verifier.collect]]
service = "rover-sim"
timeout_sec = 400.0
command = "touch /result/rollout.mp4.stop; for i in $(seq 1 380); do [ -f /result/rollout.mp4.done ] && exit 0; sleep 1; done; exit 1"

[agent]
timeout_sec = 1200.0

[environment]
build_timeout_sec = 900.0
cpus = 2
memory_mb = 4096
storage_mb = 10240
gpus = 0

[[environment.mcp_servers]]
name = "{server}"
transport = "streamable-http"
url = "http://rover-sim:8000/mcp"
"""

# Node and OpenCode are preinstalled at the versions Harbor would install (Node 22,
# OpenCode 1.19.5), so Harbor skips its per-trial install, which takes minutes under load.
MAIN_DOCKERFILE = """FROM ubuntu:24.04
RUN apt-get update && apt-get install -y curl python3 ca-certificates git xz-utils && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://nodejs.org/dist/v22.23.4/node-v22.23.4-linux-x64.tar.xz \\
      | tar -xJ -C /usr/local --strip-components=1 \\
    && npm install -g --no-audit --no-fund opencode-ai@1.19.5 && opencode --version
RUN mkdir -p /logs/agent /logs/verifier /logs/artifacts
WORKDIR /app
"""

COMPOSE = """services:
  main:
    depends_on:
      rover-sim:
        condition: service_healthy
    volumes:
      - sim_result:/sim_result:ro

  rover-sim:
    build:
      context: ./sim
    environment:
      ROVER_SEED: "{seed}"
      ROVER_DIFFICULTY: "{difficulty}"
      ROVER_COURSE: "{course}"
      ROVER_VARIATION: "{variation}"
      ROVER_RESULT_PATH: /result/result.json
      ROVER_VIDEO_PATH: /result/rollout.mp4
      MUJOCO_GL: egl
    volumes:
      - sim_result:/result
    expose:
      - "8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; s=socket.create_connection(('localhost',8000),timeout=2); s.close()"]
      interval: 2s
      timeout: 5s
      retries: 30
      start_period: 5s

volumes:
  sim_result:
"""

SIM_DOCKERFILE = """FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends libegl1 libgl1 libgles2 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY rover_env/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt imageio==2.38.1 imageio-ffmpeg==0.8.1
COPY rover_env /srv/rover_env
COPY winch_env /srv/winch_env
COPY serve.py /srv/serve.py
CMD ["python", "/srv/serve.py"]
"""

SERVE = '''"""Sidecar entrypoint: one episode, served over streamable HTTP."""
import os

from mcp.server.transport_security import TransportSecuritySettings

seed = int(os.environ["ROVER_SEED"])
difficulty = float(os.environ.get("ROVER_DIFFICULTY", "0.5"))
course = os.environ.get("ROVER_COURSE", "ramp")
result_path = os.environ.get("ROVER_RESULT_PATH")
video_path = os.environ.get("ROVER_VIDEO_PATH")

# Recording renders in the background and never affects the reward.
if course == "winch_yard":
    from winch_env.mcp_server import build_server, record
    srv, ep = build_server(seed, difficulty, result_path, os.environ.get("ROVER_VARIATION") or None)
    if video_path:
        record(ep, video_path)
else:
    from rover_env.mcp_server import build_server
    from rover_env.recorder import Recorder
    srv, ep = build_server(seed, difficulty, result_path, course)
    if video_path:
        Recorder(ep, video_path)
srv.run(transport="streamable-http", host="0.0.0.0", port=8000,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
'''

SOLVE_SH = """#!/bin/bash
# Reference run: the scripted reference policy plays through the same MCP tools as an agent.
set -e
cd /solution
PYTHONPATH=/solution python3 oracle.py --course {course}
"""

TEST_SH = """#!/bin/bash
# Reward comes only from the simulator sidecar's result file (read-only mount).
mkdir -p /logs/verifier
R=/sim_result/result.json
if [ -f "$R" ]; then
  cp "$R" /logs/verifier/sim_result.json
  python3 -c "import json; print(json.load(open('$R'))['reward'])" > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
cat /logs/verifier/reward.txt
"""


def task_name(seed: int, course: str, variation: str = "") -> str:
    if course == WINCH_COURSE:
        return f"winch-{variation}-seed{seed}" if variation else f"winch-seed{seed}"
    return f"rover-seed{seed}" if course == "ramp" else f"rover-{course}-seed{seed}"


def without_video(task_toml: str, compose: str) -> tuple[str, str]:
    """Bulk evaluation skips the rollout video: rendering, not simulation, is what limits
    how many trials run at once. Videos can be replayed later from the trajectory."""
    task_toml = task_toml.split("\n", 2)
    task_toml = task_toml[0] + "\n" + task_toml[2]                      # drop the artifacts line
    start = task_toml.index("# Before artifacts")
    task_toml = task_toml[:start] + task_toml[task_toml.index("[agent]"):]
    compose = "\n".join(line for line in compose.splitlines() if "ROVER_VIDEO_PATH" not in line) + "\n"
    return task_toml, compose


def make(seed: int, difficulty: float = 0.5, course: str = "ramp", variation: str = "",
         video: bool = True):
    d = ROOT / "tasks" / task_name(seed, course, variation)
    if d.exists():
        shutil.rmtree(d)
    (d / "environment" / "sim").mkdir(parents=True)
    (d / "tests").mkdir()
    winch = course == WINCH_COURSE
    instruction = (WINCH_VARIATION_INSTRUCTION if variation else WINCH_INSTRUCTION) if winch else INSTRUCTION
    (d / "instruction.md").write_text(instruction)
    task_toml = TASK_TOML.format(
        seed=seed, difficulty=difficulty, course=course, variation=variation,
        category="winch" if winch else "rover", server="hoist" if winch else "rover",
        description=(f"Hoist delivery in the {variation} winch yard." if variation else
                     "Deliver the one crate that is heavy enough and light enough with a hoist."
                     if winch else
                     "Deliver fragile cargo with a rover on a course with hidden hazards."))
    compose = COMPOSE.format(seed=seed, difficulty=difficulty, course=course, variation=variation)
    if not video:
        task_toml, compose = without_video(task_toml, compose)
    (d / "task.toml").write_text(task_toml)
    (d / "environment" / "Dockerfile").write_text(MAIN_DOCKERFILE)
    (d / "environment" / "docker-compose.yaml").write_text(compose)
    (d / "environment" / "sim" / "Dockerfile").write_text(SIM_DOCKERFILE)
    (d / "environment" / "sim" / "serve.py").write_text(SERVE)
    for package in PACKAGES:
        shutil.copytree(ROOT.parent / package, d / "environment" / "sim" / package,
                        ignore=shutil.ignore_patterns("__pycache__", "renders", "*.pyc"))
    solution = d / "solution"
    solution.mkdir()
    shutil.copy(ROOT / "oracle.py", solution / "oracle.py")
    for package in PACKAGES:
        shutil.copytree(ROOT.parent / package, solution / package,
                        ignore=shutil.ignore_patterns("__pycache__", "renders", "*.pyc"))
    solve = solution / "solve.sh"
    solve.write_text(SOLVE_SH.format(course=course))
    solve.chmod(0o755)
    t = d / "tests" / "test.sh"
    t.write_text(TEST_SH)
    t.chmod(0o755)
    return d


if __name__ == "__main__":
    args = sys.argv[1:]
    course, variation = "ramp", ""
    if args[:1] == ["--course"]:
        course, args = args[1], args[2:]
    if args[:1] == ["--variation"]:
        variation, args = args[1], args[2:]
    for s in args or ["1"]:
        print(make(int(s), course=course, variation=variation))
