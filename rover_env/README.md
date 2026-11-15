# rover_env: deliver fragile cargo when the vehicle's dynamics are uncertain

A MuJoCo 3D rover carries a cargo box from a plateau to a goal pad. Two routes lead there:

* **Short route**: a narrow, steep ramp (15.5 to 19 degrees, about 3 m wide, drops on both sides) that ends on a
  5 m landing pad with a ditch beyond it. You need working brakes and traction to stop on the pad.
* **Long route**: a gentle 4.5 degree ramp plus roads (about 100 m). It is slower and costs more energy, and
  long straight legs are a problem if the steering is biased.

Each seed draws a hidden dynamics mode (`nominal`, `traction`, `steering`, `braking`, or one of the
two-fault combinations) and how strong the fault is. The agent is told only that *dynamics may differ from
nominal*. A safe calibration area next to the start lets it test the vehicle first.

## Install / run

```bash
python3 -m venv .venv && .venv/bin/pip install -r rover_env/requirements.txt   # Python 3.14 tested
.venv/bin/python -m rover_env.evaluate            # main table: 13 policies x 70 seeds + reference rerun (~50 s on 22 cores)
.venv/bin/python -m rover_env.test_env            # determinism + integrity tests (~20 s)
.venv/bin/python -m rover_env.oracle              # hindsight: best open-loop plan per hidden mode
MUJOCO_GL=egl .venv/bin/python -m rover_env.render --seed 6   # PNGs -> rover_env/renders/
ROVER_SEED=6 .venv/bin/python -m rover_env.mcp_server          # MCP over stdio (5 tools)
```
The options are `--seeds N --start S --difficulty D --workers W --policies a,b --json out.json`.
`world.split_seeds(n)` returns `{"train": [...], "heldout": [...]}`. Train covers nominal, traction and
steering. Held-out covers braking and every two-fault combination.

## Tool contract (`env.Episode`, mirrored 1:1 by `mcp_server.py`)
| tool | effect | returns |
|---|---|---|
| `observe(include_image=False)` | Does not advance time. Returns the same sample at the same simulated time. | t, noisy pose (x, y, z, heading, pitch, roll), velocity (forward, lateral, yaw rate), time and energy remaining, budgets, cargo {on_board, condition, damage}, static `map` (surfaces, hazards, calibration area, goal, suggested routes, **drive_to controller description**), `vehicle_nominal_spec`, `last_command` (tool, args, termination, plus a 10 Hz trace of commanded vs measured speed, yaw rate and longitudinal accel with noisy x, y). Optional base64 PNG. |
| `drive_to(x, y, speed_limit, max_duration)` | Pure-pursuit-like P controller that plans its stops with the *nominal* 1.5 m/s² deceleration and does not compensate for faults. | `termination` ∈ arrived, overshot_target, max_duration_reached, hard_constraint_violated:\*, time_budget_exhausted, energy_budget_exhausted, invalid_input, episode_over |
| `brake()` | Requests 4.5 m/s². Gets min(hidden brake capacity, μ·N). | stopped / … |
| `wait(duration)` | Holds position with the brakes. Time and idle power are charged. | waited / … |
| `finish()` | Adjudicates once and ends the episode. Later calls return `episode_over`. | delivered, reward |

Validation rejects non-numbers, bools, NaN/inf, coordinates outside the world bounds, speed outside
[0.05, 5], and durations outside [0.02, 60]. A rejected call does not advance time.
Budgets (time, and energy at 40 W idle plus motor power over 0.8 efficiency, with no regeneration) and hard
constraints (leaving a drivable surface, rollover, chassis contact with terrain, out of bounds,
cargo touching terrain or falling off) are checked **every physics step (5 ms)**.

## Reward (computed only from simulator state, `Episode._adjudicate`)
The reward is 0 unless `finish()` was called, no hard constraint was violated, both budgets held, the cargo
body's xy is within 1.5 m of the goal, the cargo is resting on the rover at ground level, the rover is moving
slower than 0.3 m/s, and the cargo is not destroyed. If all of that holds:
`reward = 0.5 + 0.5 * eff`, where `eff = (1 - damage) * [0.5 (1 - t/T_budget) + 0.5 (1 - E/E_budget)]`.
The budgets are fixed absolutes: T = 110 - 20·difficulty s and E = 13000 - 2000·difficulty J
(100 s and 12 kJ at the default difficulty of 0.5). Doing nothing, finishing immediately, or finishing
early all give 0.

## Vehicle model (simplified, and stated here so nothing is hidden)
* The chassis is a MuJoCo free body. Four *frictionless* sphere "wheels" provide contact and normal forces.
  The cargo is a separate free box with real friction against the deck. Gravity, slopes, edges, falls and
  cargo sliding are all simulated by MuJoCo.
* Tyre forces are **not** MuJoCo friction. Every step, a friction-circle tyre model (|F| ≤ μ·N, where N is
  read from the MuJoCo wheel contact forces) produces the drive/brake force, lateral force, skid-steer yaw
  torque and rolling resistance. These are applied as an external wrench. The hidden faults act here:
  μ for traction, brake force capacity for braking, and a speed-proportional yaw-rate offset for steering.
* The onboard controller uses true state. The agent only sees noisy sensors, with noise keyed to
  (seed, simulation step).
* The physics is pinned to a 5 ms timestep, implicitfast integration, 50 iterations, a pyramidal friction
  cone and a dense Jacobian.

## Policies (all use only the 5 tools via `policies.ToolProxy`)
* **reference**: a 2.7 s launch-then-brake probe. From the commanded-vs-measured trace it estimates
  launch accel (which gives μg), braking decel (which gives min(brake, μg)) and steering bias. A point-mass
  model then picks the fastest short-route speed predicted to stop on the pad. If no speed works it takes
  the long route, with speed limited by predicted overshoot and leg length limited by the bias. It
  re-estimates the bias on the approach leg before committing to the ramp.
* **Difficulty baselines**: always_safe_route (long @3), always_short_route (@3), always_slow_short (@1),
  slow_safe_route (long @1.5), robust_safe_route (long @2.5 in legs of 12 m or less, the strongest
  non-diagnosing policy found), probe_lookup_table (same probe, categorical diagnosis, fixed table),
  direct_line.
* **Integrity baselines**: do_nothing, immediate_finish, wait_spam, random_actions, invalid_inputs.

## Results (`python -m rover_env.evaluate`, seeds 0..69, difficulty 0.5)
```
seeds 0..69 (n=70), difficulty=0.5, wall 51s
per-mode cells: mean_reward/delivery_rate;  episodes per mode: nominal=10, traction=9, steering=8, braking=15, traction+steering=9, braking+steering=11, traction+braking=8
policy                mean    deliv   train   heldout  nominal    traction   steering   braking    traction+steering  braking+steering  traction+braking
--------------------------------------------------------------------------------------------------------------------------------------------------------
reference             0.799   1.00    0.865   0.757    0.912/1.0  0.787/1.0  0.895/1.0  0.775/1.0  0.752/1.0          0.695/1.0         0.811/1.0       
always_safe_route     0.465   0.63    0.521   0.430    0.742/1.0  0.738/1.0  0.000/0.0  0.740/1.0  0.081/0.1          0.067/0.1         0.741/1.0       
always_short_route    0.409   0.44    0.549   0.321    0.926/1.0  0.412/0.4  0.231/0.2  0.309/0.3  0.410/0.4          0.246/0.3         0.347/0.4       
always_slow_short     0.569   0.64    0.715   0.477    0.878/1.0  0.391/0.4  0.877/1.0  0.537/0.6  0.592/0.7          0.325/0.4         0.445/0.5       
slow_safe_route       0.514   0.81    0.491   0.529    0.632/1.0  0.563/0.9  0.234/0.4  0.590/0.9  0.489/0.8          0.455/0.7         0.559/0.9       
robust_safe_route     0.613   1.00    0.610   0.615    0.627/1.0  0.614/1.0  0.585/1.0  0.619/1.0  0.607/1.0          0.608/1.0         0.623/1.0       
probe_lookup_table    0.698   0.99    0.834   0.613    0.912/1.0  0.681/1.0  0.909/1.0  0.681/1.0  0.502/0.9          0.562/1.0         0.683/1.0       
direct_line           0.308   0.33    0.487   0.196    0.939/1.0  0.417/0.4  0.000/0.0  0.313/0.3  0.104/0.1          0.000/0.0         0.351/0.4       
do_nothing            0.000   0.00    0.000   0.000    0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0          0.000/0.0         0.000/0.0       
immediate_finish      0.000   0.00    0.000   0.000    0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0          0.000/0.0         0.000/0.0       
wait_spam             0.000   0.00    0.000   0.000    0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0          0.000/0.0         0.000/0.0       
random_actions        0.000   0.00    0.000   0.000    0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0          0.000/0.0         0.000/0.0       
invalid_inputs        0.000   0.00    0.000   0.000    0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0  0.000/0.0          0.000/0.0         0.000/0.0       

reference rerun: run1 mean=0.7985  run2 mean=0.7985  max |per-seed diff|=0.00e+00  seeds differing=0
reference - always_safe_route = +0.334
best non-diagnosing baseline: robust_safe_route = 0.613 (gap to reference +0.186)
```

Hindsight menu (`python -m rover_env.oracle`):
```
best open-loop plan in hindsight, per hidden mode (route counts; mean best reward)
  nominal            n=10  mean=0.927  delivered=1.00  best plans: {'short@2.5': 8, 'short@3.0': 2}
  traction           n= 9  mean=0.811  delivered=1.00  best plans: {'long@3.0': 5, 'short@2.5': 3, 'short@3.0': 1}
  steering           n= 8  mean=0.923  delivered=1.00  best plans: {'short@2.0': 4, 'short@2.5': 3, 'short@3.0': 1}
  braking            n=15  mean=0.856  delivered=1.00  best plans: {'long@3.0': 5, 'short@2.5': 5, 'short@2.0': 3, 'short@1.0': 2}
  traction+steering  n= 9  mean=0.836  delivered=1.00  best plans: {'short@2.0': 2, 'short@2.5': 2, 'long@2.0/leg12': 1, 'short@3.0': 1, 'short@1.5': 1, 'long@2.0': 1, 'long@3.0': 1}
  braking+steering   n=11  mean=0.796  delivered=1.00  best plans: {'long@2.0/leg12': 2, 'long@3.0': 2, 'short@2.5': 2, 'short@2.0': 2, 'short@3.0': 1, 'short@1.5': 1, 'long@2.0': 1}
  traction+braking   n= 8  mean=0.828  delivered=1.00  best plans: {'long@3.0': 4, 'short@2.5': 3, 'short@2.0': 1}
  ALL                hindsight-oracle mean=0.853
  best single fixed plan from the menu: ('long', 2.0, 12.0) mean=0.615
```

Probe identifiability (70 seeds, one 2.7 s probe costing about 690 J): steering bias error mean 0.002 and max 0.010 1/m
(the faults range from 0.05 to 0.16). Decel-capacity error mean 0.03 and max 0.09 m/s². μg error mean 0.02
when the launch is traction-limited (μ < 0.255). For μ > 0.255 a traction fault only shows up in braking
decel, so on flat ground it cannot be told apart from a brake fault. That does not matter for the
decision, which depends on min(brake, μg).

## Known limitations
* If an agent can read this source **and** the seed, it can recompute the hidden mode with
  `world.generate(seed)`. The MCP server must run where the agent cannot see the seed, the source or
  `ROVER_RESULT_PATH`.
* `ToolProxy` is a convention, not a sandbox: a Python policy could reach the Episode through a bound
  method's `__self__`. MCP agents cannot.
* The cargo-damage term (horizontal accel above 7 m/s²) almost never fires. In practice "fragile" means
  the cargo is destroyed if it drops or falls.
* The reference is conservative. It scores 0.799 against a hindsight-oracle score of 0.853, with most of
  the gap in braking-fault seeds where the short route was still feasible.
* Determinism was verified on one machine, both across processes and within one process. It was not
  verified across machines or MuJoCo versions.

## Courses

Ten courses share the same tools, reward and vehicle. Pass the name as `course`
(`Episode(seed, difficulty, course)`, `--course` for the evaluation, the playground's
course picker, or `harbor_tasks/run.sh <job> <course> <seed> ...`).

| Course | Lanes and hazards | What has to be found out |
|---|---|---|
| `ramp` | short steep ramp or long gentle road | brake, traction or steering fault |
| `serpentine` | mud shortcut or zig-zag with an icy leg | which of mud and ice is passable |
| `fork_mud_ice` | mud, ice | same, on parallel lanes |
| `fork_wind_mud` | wind-exposed bridge, mud | crosswind strength or mud drag |
| `fork_crate_ice` | crate in the lane, ice | crate mass or ice friction |
| `fork_barrier_mud` | mud, possible barrier | mud drag, or look from the lookout |
| `fork_crate_wind` | crate, wind | crate mass or wind strength |
| `fork_mud_ice_wind` | ice, mud, wind (three lanes) | which one of three is passable |
| `fork_crate_barrier_mud` | barrier, crate, mud (three lanes) | which one of three is passable |
| `fork_replan` | mud or ice, then a second fork (crate or barrier) with no samples | first fork by testing, second by looking on arrival |

In the serpentine and fork courses each seed is one regime: exactly one lane per fork is
passable within the budgets, and the map is the same whichever it is. The start pad has
a test for every first-fork hazard: sample strips of mud, ice and wind, a sample crate
of the same mass, and a lookout from which barriers are visible.

```
.venv/bin/python -m rover_env.evaluate --course fork_mud_ice_wind --seeds 40
.venv/bin/python -m rover_env.test_courses
MUJOCO_GL=egl .venv/bin/python -m rover_env.play --host 0.0.0.0 --port 8081
```

The playground also serves the winch yard playground under `/winch/`.

The MCP server exposes `get_map` (static information, call once), `observe`, `drive_to`,
`brake`, `wait` and `finish`.
