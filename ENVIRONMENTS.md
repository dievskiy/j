# Environments

A register of every environment, grouped by category. Update it when an environment is
added, changed or re-measured.

**Shared design.** Every environment has a hidden physical property that changes the best
action, a cheap test that reveals it, and budgets that fit the right action plus testing
but not a cautious crawl or a wrong attempt followed by a retreat. Reward is 0 unless the
task is completed within budget, otherwise 0.5 + 0.5 × efficiency.

**Status values.** `ready`: reference delivers 100% and clearly beats every non-testing
plan. `weak gap`: works, but a non-testing plan gets close. `planned`: not built.

## Rover (MuJoCo)

A wheeled rover delivers fragile cargo to a goal circle. Tools: `get_map`, `observe`,
`drive_to`, `brake`, `wait`, `finish`. Code in `rover_env/`; course name is the `course`
argument everywhere.

| Course | Status | Routes and hazards | Hidden | Test available | Regimes |
|---|---|---|---|---|---|
| `ramp` | weak gap | short steep ramp or long gentle road | brake, traction or steering fault (7 modes) | launch-and-brake in the calibration area | 7 |
| `serpentine` | ready | mud shortcut or zig-zag with an icy leg; routes can be mixed at a junction | mud drag, ice friction | mud and ice sample strips | 2 |
| `fork_mud_ice` | ready | mid lane mud, north lane ice | mud drag, ice friction | sample strips | 2 |
| `fork_wind_mud` | ready | mid lane wind-exposed, south lane mud | wind strength, mud drag | sample strips | 2 |
| `fork_crate_ice` | ready | mid lane blocked by a crate, north lane ice | crate mass, ice friction | sample crate, sample strip | 2 |
| `fork_barrier_mud` | ready | mid lane mud, south lane may be walled off | mud drag, barrier present | sample strip, lookout | 2 |
| `fork_crate_wind` | ready | mid lane crate, north lane wind | crate mass, wind strength | sample crate, sample strip | 2 |
| `fork_mud_ice_wind` | ready | three lanes: ice, mud, wind | all three | three sample strips | 3 |
| `fork_crate_barrier_mud` | ready | three lanes: barrier, crate, mud | all three | lookout, sample crate, sample strip | 3 |
| `fork_replan` | ready | mud or ice, then a second fork (crate or barrier) | all four | strips for the first fork; none for the second, the rover must look on arrival | 4 |

In `serpentine` and the `fork_*` courses exactly one lane per fork is passable, and the map
is identical whichever it is. The vehicle is nominal there; vehicle faults exist only on
`ramp`.

### Scripted results

Mean reward, with delivery rate in brackets. Fork courses: 40 seeds. Serpentine: 60.
Ramp: 70. Difficulty 0.5.

| Course | Reference | Best non-testing plan | Cautious plan | Do-nothing family |
|---|---|---|---|---|
| `ramp` | 0.800 (100%) | 0.579 (93%) | 0.478 (64%) | 0 |
| `serpentine` | 0.668 (100%) | 0.491 (58%) | 0 | 0 |
| `fork_mud_ice` | 0.750 (100%) | 0.446 (55%) | 0.052 | 0 |
| `fork_wind_mud` | 0.777 (100%) | 0.517 (60%) | 0.353 | 0 |
| `fork_crate_ice` | 0.715 (100%) | 0.500 (62%) | 0 | 0 |
| `fork_barrier_mud` | 0.747 (100%) | 0.441 (55%) | 0.017 | 0 |
| `fork_crate_wind` | 0.705 (100%) | 0.396 (53%) | 0 | 0 |
| `fork_mud_ice_wind` | 0.731 (100%) | 0.331 (40%) | 0 | 0 |
| `fork_crate_barrier_mud` | 0.685 (100%) | 0.329 (42%) | 0 | 0 |
| `fork_replan` | 0.698 (100%) | 0.239 (33%) | 0 | 0 |

Reproduce a row with `.venv/bin/python -m rover_env.evaluate --course <course> --seeds 40`.

### Model runs so far

Single trials through Harbor and OpenCode; one seed each, so these are observations, not
measurements. Runs marked *old* used an earlier version of the course (different hidden
values and budgets for the same seed) and are not comparable with the table above.

| Course | Seed | Model | Reward | Tested first? | What happened |
|---|---|---|---|---|---|
| `fork_crate_wind` | 0 | DeepSeek 4.1 Flash | 0.758 | yes (crate) | pushed the sample crate, judged it light, took the crate lane |
| `fork_mud_ice_wind` | 0 | Sonnet 5.5 | 0.847 | no | drove straight down the mud lane, which happened to be the open one |
| `serpentine` *old* | 9 | Sonnet 5.5 | 0 | no | stuck in thick mud, then rolled on ice |
| `serpentine` *old* | 9 | DeepSeek 4.1 Flash | 0 | no | tried mud, retreated, slid off ice |
| `serpentine` *old* | 9 | Inkling | 0 | yes | cut a corner of the start pad |
| `serpentine` *old* | 333 | Sonnet 5.5 | 0.821 | no | shortcut through thin mud |
| `ramp` | 1 | DeepSeek 4.1 Flash | 0.906 | no | slow descent of the short ramp |
| `ramp` | 1 | Inkling | 0.896 | no | short ramp, one overshoot |


Single trials on four variations (Harbor, OpenCode, difficulty 0.5). Observations, not
measurements. The worn-cable trials ran before the creep fix in `8255238`; neither
outcome depends on it.

| Variation, seed (hidden regime) | DeepSeek 4.1 Flash | Sonnet 5.5 |
|---|---|---|
| `worn_cable` 0 (worn, strength 1294 N) | 0: stop at 1600 N, above the worn cable's strength; snapped | 0.792: delivered |
| `stuck_crate` 1 (right crate stuck) | 0.699: delivered | 0.871: noticed the crate held at high tension without rising, tugged it sideways, delivered (beats the reference's 0.775) |
| `gain_reference` 0 (gain 0.97, stiff) | 0.796: delivered | 0: took up at 0.2 m/s on the stiff cable; braking overshoot snapped it |
| `total_payload` 1 (stiff) | 0: reeled in at 0.4 m/s with no tension stop; snapped | 0: stop at 1600 N at 0.3 m/s on the stiff cable; overshoot snapped it |

Three of the four snaps are the braking overshoot the map warns about: a stop is a
trigger, not a cap. Only DeepSeek's worn-cable snap is the variation's intended trap.

### Known issues

- `ramp`: a slow, cautious route still delivers 93% of seeds, so the gap is small.
- A single blind gamble succeeds one time in two or three by design; score over a
  balanced set of seeds per course.
- No model has been run over multiple seeds on any current course.
- The sample crate can slide sideways when pushed off-centre, which makes the crate test
  harder to read than intended.
- Strong wind tips the rover over more often than it slides it off the bridge.
- Astra's review items not yet fixed: collision checks use contact data from before each
  physics step; delivery does not verify the cargo is resting on the rover; cargo damage
  is sampled once per control tick.

## Winch yard (MuJoCo)

A gantry hoist delivers one crate to a raised platform. Tools: `observe`,
`move_trolley`, `winch`, `attach`, `release`, `wait`, `finish`. Code in `winch_env/`.

| Environment | Status | Options and hazards | Hidden | Test available | Regimes |
|---|---|---|---|---|---|
| `winch_yard` | ready (scripted only) | three identical-looking crates: one too light to count, one too heavy for the cable, one right | each crate's mass; cable stiffness (soft or stiff); tension-sensor offset | slack reading shows the offset; a 1 cm pull shows the stiffness; a slow tension-limited take-up weighs a crate | 12 (6 orderings × 2 cables) |

### Scripted results

72 seeds, difficulty 0.5. Reproduce with `.venv/bin/python -m winch_env.evaluate --seeds 72`.

| Policy | Mean reward | Delivery |
|---|---|---|
| Reference (calibrate, weigh, then choose) | 0.735 | 100% |
| Carry the first crate that lifts | 0.356 | 47% |
| Take one fixed crate, careful take-up | 0.21–0.27 | 29–36% |
| Haul the nearest crate at full speed | 0.228 | 28% |
| Do-nothing, random, invalid input, drop on goal | 0 | 0% |

### Model runs so far

Single trials through Harbor and OpenCode on seed 3 (nearest crate light, middle too
heavy, farthest right; stiff cable; sensor offset +54 N). Observations, not measurements.

| Model | Reward | Calibrated and weighed? | What happened |
|---|---|---|---|
| DeepSeek 4.1 Flash | 0.655 | yes | read the offset from the slack reading, weighed all three crates with tension stops, delivered the right one with 2.5 s to spare |
| Sonnet 5.5 | 0 | partly | weighed the light crate correctly, then took up the heavy one at 0.4 m/s on the stiff cable; the tension stop tripped too late and the cable snapped |

### Known issues

- An earlier Sonnet trial died with tool timeouts when the model issued two tool calls
  at once; tool calls are now serialised in both MCP servers. Not yet re-verified under
  Harbor with a model that does this.
- `harbor_tasks/replay_video.py` only replays rover trials.
- Reviewed by GPT-6 Astra. Fixed since: delivery now needs platform contact and half a
  second at rest after release; impacts are checked every physics step; hidden values
  use a separately salted random stream; the cable law, drum height and tension-stop
  behaviour are published; trolley work against the load and hook-on time are charged;
  the tension sensor has an unknown offset that must be calibrated.
- Still open from that review: impact damage uses the crate's centre speed, not the
  contact-point speed; no frontier model has been run, so the gap is against scripts only.

## Other categories

Candidates not yet built, in the order recommended after consulting GPT-6 Astra:

| Category | Status | Idea | Why it is a good next step |
|---|---|---|---|
| Puck launcher | planned | slide a puck so it stops in a narrow zone; hidden friction and table tilt; practice shots on a side lane | no cautious option: too little power undershoots, too much overshoots |
| Spacecraft docking | planned | dock within a speed tolerance before a deadline; hidden mass or weak thruster; short test burns | braking early misses the deadline, braking late exceeds docking speed |
| Gantry crane | planned (reserve) | carry a swinging load through a gate; hidden cable length | swing timing depends on cable length |

Considered and set aside: ballistic launcher (duplicates the puck), ferry (continuous
steering correction removes the need to test), tilting tray, drone and conveyor (too
much control or contact work), cabinet-opening arm (contact-rich), balance beam (mostly
symbolic).
