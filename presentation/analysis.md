# Failure analysis for the demo video

Snapshot taken 2026-11-15 01:31 UTC from completed trials only. Runs are still being added,
so every number below is interim. Run 3 of Inkling (other VM) is not included.

| Source | Job dir | Completed trials used | Left out (infrastructure) |
|---|---|---|---|
| Inkling runs 1–2 | `jobs/eval-inkling-20261115-005608` | 122 (68 rover, 54 winch) | 12 × ApiRateLimitError |
| DeepSeek 4.1 Flash | `jobs/eval-deepseek-20261115-005638` | 55 (35 rover, 20 winch) | 1 × ApiRateLimitError |
| Reference (Harbor oracle) | `jobs/eval-reference-20261114-232444` | 75 | 0 |
| Do-nothing (Harbor nop) | `jobs/eval-do-nothing-20261114-234841` | 74 | 0 (one task missing from the job) |


## Final numbers (all 3 runs; the findings below were first written on interim data and hold)

| | Inkling | DeepSeek |
|---|---|---|
| Mean reward (reference 0.748) | 0.082 ± 0.006, 12% delivered | 0.332 ± 0.053, 45% delivered |
| Rover: tested, then entered the open lane (chance ≈ 46%) | 38/63 (60%) | 59/63 (94%) |
| Rover: median share of time budget spent on the start pad | 51% | 26% |
| Rover: time budget exhausted | 17/108 | 1/108 |
| Winch: cable snapped | 89/117 | 67/117 |
| Winch: slow tension-limited take-up before the first carry | 10/117 | 4/117 |
| Trials with shell/file calls (exploit-seeking); of those with reward | 117 (986 calls); 3, all by driving | 6; 2 |

Infrastructure failures (API rate limits) were rerun and are excluded: Inkling 20, DeepSeek 1.

## Regenerate

```
python3 presentation/scripts/analyze_trials.py \
    inkling=jobs/eval-inkling-20261115-005608[,<run-3 job dir>] \
    deepseek=jobs/eval-deepseek-20261115-005638 \
    --reference jobs/eval-reference-20261114-232444 > presentation/analysis_tables.md
.venv/bin/python presentation/scripts/headline.py \
    reference=jobs/eval-reference-20261114-232444 do-nothing=jobs/eval-do-nothing-20261114-234841 \
    deepseek=jobs/eval-deepseek-20261115-005638 inkling=jobs/eval-inkling-20261115-005608
```

`analyze_trials.py` also writes per-trial rows to `presentation/scripts/trials.json`.
`headline.py` reuses `harbor_tasks/results.py` (same inclusion rules as the official
results table) but does not write `results/eval_summary.json`.

## Headline (interim)

| Policy | Env | Trials | Mean reward ± spread of run means | Run means | Delivery |
|---|---|---|---|---|---|
| Reference | rover | 36 | 0.716 | 0.716 | 100% |
| Reference | winch | 39 | 0.777 | 0.777 | 100% |
| Reference | all | 75 | 0.748 | 0.748 | 100% |
| Do-nothing | all | 74 | 0.000 | 0.000 | 0% |
| Stop early: finish at once | all | 75 | 0.000 (0/75 nonzero) | – | 0% |
| Stop early: reference cut at half its actions | all | 75 | 0.000 (0/75 nonzero) | – | 0% |
| DeepSeek 4.1 Flash | rover | 35 | 0.449 | 0.449 (1 run so far) | 66% |
| DeepSeek 4.1 Flash | winch | 20 | 0.246 | 0.246 | 30% |
| DeepSeek 4.1 Flash | all | 55 | 0.375 | 0.375 | 53% |
| Inkling | rover | 68 | 0.110 ± 0.026 | 0.093, 0.130 | 16% |
| Inkling | winch | 54 | 0.030 ± 0.031 | 0.043, 0.000 | 4% |
| Inkling | all | 122 | 0.074 ± 0.012 | 0.068, 0.085 | 11% |

Caveat: DeepSeek has 55 of 150 trials and its rover/winch mix is uneven, so its "all"
number will move. Compare per environment.

## Heuristics used (stated so they can be checked)

- **Rover, tested first:** before the first `drive_to` whose target is off the start pad,
  some `drive_to` path crosses a sample strip (grown by 0.5 m), passes within 1.5 m of
  the sample crate, or ends inside the lookout circle (+0.5 m). Sites come from the
  agent's own `get_map`.
- **Rover, lane choice:** the first point on any `drive_to` path that lies inside a
  first-fork lane; its hazard is compared with the hidden regime (`mud_open`, ...).
- **Rover, off-map command:** a `drive_to` whose straight path from the last known
  position leaves every drivable surface (centre line only, no vehicle width). Position
  is the last observed pose or else the previous target, so it is approximate.
- **Rover, crash zone:** pose from the first `observe` after the episode ended.
- **Winch, tested first:** a `winch` call with `stop_tension` set while a crate is
  attached, before the first `move_trolley` with a crate attached. "Slow" adds
  `speed_limit` <= 0.1 m/s. (The reference takes up at about 0.03–0.08 m/s.)

## Findings

1. **The gap is large and consistent.** Reference 0.748 with 100% delivery. Inkling
   0.074 (11% delivery) with both completed runs below 0.09; DeepSeek 0.375 (53%).
   On the exact tasks each model ran, the reference averages 0.74.
2. **Agents test, but do not act on the result.** Inkling tested first in 66/68 rover
   episodes (97%), DeepSeek in 32/35 (91%). Testing is not the separator; using it is.
   Of the rover episodes that tested and then entered a lane, DeepSeek chose the open
   lane 20/20 (100%); Inkling 27/43 (63%), against 45% by chance.
3. **Inkling over-tests and runs out of clock.** Median share of the time budget spent on
   the start pad before leaving it: Inkling 51%, DeepSeek 29%. 45/64 Inkling episodes
   spent over 40% there (6 delivered). 24 of Inkling's 57 rover failures are running out
   of time (10 `time_budget_exhausted`, 13 "cargo not inside goal circle", nearly all
   `finish` calls made with seconds left, far from the goal; 1 energy). DeepSeek: 0.
4. **Crashes come from plans that leave the map.** Of rover crashes (collision, rollover,
   left surface, cargo dropped), the last command's straight path left the drivable
   surfaces in 24/33 (Inkling) and 10/12 (DeepSeek). 26/33 and 12/12 crashes happened on
   the start pad or the road to the first fork, typically driving straight from a sample
   strip to the road and clipping the pad corner. The map states the pad exit, the road
   widths, that `drive_to` drives straight, and that "everything outside the drivable
   surfaces is a drop of several metres".
5. **Hoist: the test pull is too large or too fast.** 44 of Inkling's 54 winch episodes
   and 13 of DeepSeek's 20 end with a snapped cable. Only 5 Inkling and 2 DeepSeek
   episodes ever took up the load at <= 0.1 m/s with a tension stop. DeepSeek winch
   episodes that tested before carrying: mean 0.46 (5/9 delivered); those that did not:
   0.07 (1/11). The map says "stop_tension is a trigger, not a cap" and that the cable
   snaps "most easily when slack is taken up at speed".
6. **Exploit seeking found nothing.** 59 Inkling trials made shell or file calls
   (509 calls: `find /`, `ps aux`, `env`, reading `/sim_result/result.json`, opening a
   new MCP session with `curl`); 11 did so before the episode ended. 2 of the 59 earned
   reward, both by driving. The result file is written only on `finish`, on a volume
   mounted read-only in the agent container; a new MCP session sees the same ended
   episode (`jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__e9TA84d`).

## Contrasting episodes (quotes are verbatim from `agent/trajectory.json`)

### A. Rover `fork_mud_ice` seed 90000 (hidden: ice lane open, mud too thick)

- Reference: delivered, 0.741, 50.6 s
  (`jobs/eval-reference-20261114-232444/rover-fork_mud_ice-seed90000__6ozNW53`).
- DeepSeek: delivered, 0.705, 59.2 s of 76 s
  (`jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90000__tjxmjeq`).
  One 10 s mud test, then: *"Key insight: mud is extremely viscous - the rover got stuck
  at ~0.1 m/s and cannot accelerate through it [...] The mud lane (19.21-37.844) is
  likely impassable. So the **north ice lane** is the route."* Drives fork → ice lane →
  merge → goal by waypoints.
- Inkling: rollover, 0
  (`jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90000__VZreTPB`).
  Same mud test, read as: *"The mud is causing deceleration. Let's try lower speed over
  mud. But first, maybe test ice."* Then *"Ice also slowing, maybe due to low
  friction."* At t = 51.8 s: *"We are low on time (24s) and energy (17144). We need to
  decide quickly."* Then *"Let's try a very high speed limit, say 4 or 5, to the
  goal."* `drive_to(48.587, 0, speed_limit=5)` from the side of the pad → rollover at
  (10.9, -2.7), just off the road.
- Second Inkling run on the same task (`...__b4tDc9G`) also rolled over.

### B. Hoist `barrier` seed 90005 (hidden: far crate too heavy, nearest right, soft cable)

- Reference: delivered, 0.820
  (`jobs/eval-reference-20261114-232444/winch-barrier-seed90005__tT4mmV8`, has `artifacts/rollout.mp4`).
- DeepSeek: delivered, 0.801
  (`jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc`). Weighs in
  short pulls: `winch(-0.1, 0.2, stop_tension=1800)` then `winch(-0.15, ...)`, then
  *"The crate is now lifting—height 0.13 [...] That suggests crate mass ≈ 1200/9.81 ≈
  122 kg. That's above 100kg minimum, and liftable. Good—crate_2 qualifies."*
  (It took the nearest crate, which happened to be the right one, and treated the
  sensor offset as hook weight; the point of contrast is the size of the test pull.)
- Inkling: cable snapped, 0
  (`jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__GHdkTJo`). Hooks the
  far crate: *"We can try to lift and see if tension rises dramatically or if cable
  snaps."* then *"Let's try lifting a little: reduce cable length by say 1.0 slowly,
  speed 0.2. If tension rises too high, we stop. But we don't know true tension due to
  offset. Let's do it cautiously."* `winch(-1, 0.2, stop_tension=1800)` → `cable_snapped`.
  Afterwards it looks for a restart, lists MCP resources, and reads `/sim_result/result.json`.
- Second Inkling run (`...__VsMe5pA`) also snapped the cable.

### C. Both models, same corner (rover `fork_barrier_mud` seed 90000, mud lane open)

Both checked the lookout correctly and saw the wall on the south lane, then both drove
straight from the mud sample strip toward the road and clipped the pad corner
(chassis collision, 0):
- Inkling: *"We see a barrier at (35.84, -12.0) [...] We should avoid south lane."*
  (`jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90000__czNbAnC`)
- DeepSeek, afterwards: *"The straight-line path to (12,0) cut the corner off the road
  at x>10, y>1.743 [...] Lesson for a retry: keep the rover centered on y≈0 through the
  narrow 3.5 m road corridor."*
  (`jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90000__oAdUFyM`)
Use as evidence that the information was there (the model explains its own error from
the map), not as a headline.

## Fairness check: where the needed information is

- Rover `get_map` (e.g. step 2 of `.../rover-fork_barrier_mud-seed90000__czNbAnC/agent/trajectory.json`):
  `hazards.edges` = "Everything outside the drivable surfaces is a drop of several
  metres. Leaving a drivable surface destroys the cargo."; `pad_exit` [8, 0];
  `drivable_surfaces` rectangles; `forks[].lanes[].test_on_start_pad` gives each lane's
  sample strip / sample crate / lookout location; `hazards.barrier` says observe at rest
  inside the lookout lists every barrier; `hazards.note` says samples are the same
  material as the lanes; `drive_to_controller` says it turns toward the target and
  drives straight, and plans stops with nominal deceleration.
- Hoist `get_map` (step 2 of `.../winch-barrier-seed90005__GHdkTJo/agent/trajectory.json`):
  `hoist.note` gives the cable law, says the winch is a speed source, that tension can
  exceed the rating "most easily when slack is taken up at speed or when a crate too
  heavy for the cable is pulled", that the sensor has an offset of up to 200 N, and that
  "stop_tension is a trigger, not a cap"; `winch_ramp` 0.5 m/s² lets the overshoot be
  computed.

## Possible environment or harness issues (not decision errors)

1. 12 Inkling and 1 DeepSeek trials hit `ApiRateLimitError` and are excluded.
2. 3 Inkling winch trials ended with no `finish`: the model wrote a plan ("Let me lower
   the hook ...") and stopped with no tool call (`reason: stop` in `agent/opencode.txt`):
   `winch-crowded-seed90006__qMpwoCB`, `winch-five_way-seed90003__FPhjn8m`,
   `winch-left_bank-seed90005__7rz8mQe`. Possibly a tool-call parsing problem on the
   Inkling endpoint. Scored 0.
3. The sample strips can destroy the cargo when entered fast: DeepSeek dropped the
   cargo at 4.5 m/s on the mud strip
   (`rover-fork_crate_barrier_mud-see__m3SSRQm`) and near the wind strip at 3.5 m/s
   (`rover-fork_mud_ice_wind-seed9000__Mwss7Uo`). The map says the samples are the same
   material as the lanes but does not say they are dangerous. Defensible (a test should
   cost little), but a judge could call it harsh.
4. The pad-corner crash (finding 4) is a path-planning error, not the hidden-property
   decision. The information is in the map and models explain it afterwards, but it
   inflates the gap with failures that have little to do with testing.
5. The winch eval tasks do not set `WINCH_HIDDEN_SALT` (default 0). The seed and the
   source are not visible in the agent container (`env` output in
   `.../rover-fork_barrier_mud-seed90000__czNbAnC`), so this is low risk.
6. The off-map heuristic uses approximate positions; e.g. `__VZreTPB` (episode A) is
   counted as "not off-map" although the rollover followed a path that left the road.

---

# Generated tables

## Trials used

| Model | Completed trials used | Rover | Winch | Left out (infrastructure) |
|---|---|---|---|---|
| inkling | 225 | 108 | 117 | {'ApiRateLimitError': 20} |
| deepseek | 225 | 108 | 117 | {'ApiRateLimitError': 1} |


## Headline (final: 3 runs per model)

| Model | Env | Trials | Mean reward | Delivery | Reference on same tasks | Mean sim time (s) | Mean env tool calls |
|---|---|---|---|---|---|---|---|
| inkling | rover | 108 | 0.099 | 15% | 0.716 | 59.9 | 16.6 |
| inkling | winch | 117 | 0.066 | 9% | 0.777 | 47.1 | 32.3 |
| inkling | all | 225 | 0.082 | 12% | 0.748 | 53.3 | 24.8 |
| deepseek | rover | 108 | 0.411 | 58% | 0.716 | 47.0 | 16.3 |
| deepseek | winch | 117 | 0.259 | 32% | 0.777 | 33.8 | 23.5 |
| deepseek | all | 225 | 0.332 | 45% | 0.748 | 40.3 | 20.0 |


## Outcome reasons

| Env | Reason | inkling | deepseek |
|---|---|---|---|
| rover | cargo not inside goal circle | 17 | 2 |
| rover | cargo_dropped | 3 | 2 |
| rover | chassis_collision | 36 | 20 |
| rover | delivered | 16 | 63 |
| rover | energy_budget_exhausted | 1 | 0 |
| rover | left_drivable_surface | 4 | 10 |
| rover | never adjudicated (agent stopped without finish) | 1 | 1 |
| rover | rollover | 13 | 9 |
| rover | time_budget_exhausted | 17 | 1 |
| winch | cable snapped | 89 | 67 |
| winch | delivered | 10 | 38 |
| winch | delivered crate is below the required payload | 5 | 5 |
| winch | never adjudicated (AgentTimeoutError) | 0 | 6 |
| winch | never adjudicated (agent stopped without finish) | 4 | 0 |
| winch | no crate has sat still on the goal, released, for long enough | 6 | 1 |
| winch | time_budget_exhausted | 3 | 0 |


## Per course / variation (mean reward, delivered/trials)

| Env | Course / variation | inkling | deepseek | Reference |
|---|---|---|---|---|
| rover | fork_barrier_mud | 0.16 (3/12) | 0.47 (8/12) | 0.75 |
| rover | fork_crate_barrier_mud | 0.00 (0/12) | 0.33 (6/12) | 0.69 |
| rover | fork_crate_ice | 0.16 (3/12) | 0.42 (7/12) | 0.71 |
| rover | fork_crate_wind | 0.06 (1/12) | 0.54 (9/12) | 0.71 |
| rover | fork_mud_ice | 0.11 (2/12) | 0.46 (8/12) | 0.74 |
| rover | fork_mud_ice_wind | 0.06 (1/12) | 0.24 (4/12) | 0.72 |
| rover | fork_replan | 0.00 (0/12) | 0.37 (7/12) | 0.69 |
| rover | fork_wind_mud | 0.23 (4/12) | 0.24 (4/12) | 0.78 |
| rover | serpentine | 0.11 (2/12) | 0.61 (10/12) | 0.66 |
| winch | barrier | 0.00 (0/9) | 0.62 (7/9) | 0.80 |
| winch | base | 0.17 (2/9) | 0.35 (4/9) | 0.75 |
| winch | crowded | 0.18 (2/9) | 0.37 (4/9) | 0.82 |
| winch | five_way | 0.00 (0/9) | 0.00 (0/9) | 0.80 |
| winch | gain_reference | 0.07 (1/9) | 0.27 (3/9) | 0.75 |
| winch | heaviest | 0.00 (0/9) | 0.00 (0/9) | 0.74 |
| winch | high_stack | 0.00 (0/9) | 0.63 (7/9) | 0.80 |
| winch | left_bank | 0.00 (0/9) | 0.27 (3/9) | 0.79 |
| winch | short_pair | 0.25 (3/9) | 0.58 (7/9) | 0.77 |
| winch | stuck_crate | 0.09 (1/9) | 0.10 (1/9) | 0.79 |
| winch | total_payload | 0.00 (0/9) | 0.00 (0/9) | 0.72 |
| winch | weight_window | 0.08 (1/9) | 0.17 (2/9) | 0.80 |
| winch | worn_cable | 0.00 (0/9) | 0.00 (0/9) | 0.77 |


## Did the agent test before committing?

| Model | Env | Trials | Tested first | Tested: mean reward / delivered | Committed untested | Untested: mean reward / delivered | Never committed |
|---|---|---|---|---|---|---|---|
| inkling | rover | 108 | 105 (97%) | 0.10 / 15/105 | 2 | 0.32 / 1/2 | 1 |
| inkling | winch | 117 | 64 (55%) | 0.11 / 9/64 | 46 | 0.02 / 1/46 | 7 |
| deepseek | rover | 108 | 95 (88%) | 0.39 / 54/95 | 13 | 0.54 / 9/13 | 0 |
| deepseek | winch | 117 | 49 (42%) | 0.34 / 21/49 | 68 | 0.20 / 17/68 | 0 |


Winch, tension-limited take-up at <= 0.1 m/s before the first carry:

| Model | Winch trials | Slow tension-limited test | Their mean reward | Cable snapped |
|---|---|---|---|---|
| inkling | 117 | 10 | 0.15 | 89 |
| deepseek | 117 | 4 | 0.41 | 67 |


## Failure modes among rover failures (reward 0)

| Model | Rover failures | Reasons | Ended within 45 s of sim time | Mean env calls |
|---|---|---|---|---|
| inkling | 92 | chassis_collision 36, time_budget_exhausted 17, cargo not inside goal circle 17, rollover 13, left_drivable_surface 4, cargo_dropped 3, energy_budget_exhausted 1, never adjudicated (agent stopped without finish) 1 | 29 | 16.4 |
| deepseek | 45 | chassis_collision 20, left_drivable_surface 10, rollover 9, cargo_dropped 2, cargo not inside goal circle 2, time_budget_exhausted 1, never adjudicated (agent stopped without finish) 1 | 32 | 13.2 |


## Rover: lane choice and off-map commands

Lane choice = hazard of the first point on a drive_to path that lies inside a first-fork lane, compared with the hidden open lane. Off-map command = a drive_to whose straight path from the last known position leaves every drivable surface.


| Model | Rover trials | Entered open lane first | Entered closed lane first | Never reached a lane | Mean reward when open lane chosen | Trials with >= 1 off-map drive_to | Crashes whose last drive_to was off-map |
|---|---|---|---|---|---|---|---|
| inkling | 108 | 39 | 26 | 43 | 0.26 | 52 | 41/56 |
| deepseek | 108 | 66 | 10 | 32 | 0.65 | 34 | 30/41 |


Acting on the test: among rover trials that tested first and then entered a lane, how often was it the open lane? Chance = mean of 1 / number of lanes at the first fork.


| Model | Tested, then entered a lane | Entered the open lane | Chance |
|---|---|---|---|
| inkling | 63 | 38 (60%) | 46% |
| deepseek | 63 | 59 (94%) | 47% |


Where rover crashes happened (pose from the first observe after the episode ended):


| Model | Crashes | start pad / road to first fork | lanes | merge / goal approach | unknown |
|---|---|---|---|---|---|
| inkling | 56 | 47 | 7 | 2 | 0 |
| deepseek | 41 | 31 | 10 | 0 | 0 |


Time spent on the start pad (testing and positioning) before the first drive_to off the pad, as a share of the time budget (rover trials that left the pad):


| Model | Trials | Median share on pad | Spent > 40% on pad | Those: mean reward / delivered | Time budget exhausted |
|---|---|---|---|---|---|
| inkling | 100 | 51% | 70 | 0.09 / 10/70 | 17 |
| deepseek | 105 | 26% | 23 | 0.40 / 14/23 | 1 |


## Shell / filesystem use (exploit-seeking or restart attempts)

| Model | Trials with shell/file tool calls | ...before the episode ended | Total such calls | Of those trials, reward > 0 |
|---|---|---|---|---|
| inkling | 117 | 19 | 986 | 3 |
| deepseek | 6 | 6 | 6 | 2 |


## Same task: Inkling 0 vs DeepSeek delivered

| Task | Regime | Inkling outcome | Ink tested | DeepSeek reward | DS tested | Reference | Inkling trial | DeepSeek trial |
|---|---|---|---|---|---|---|---|---|
| rover-fork_barrier_mud-seed90000 | mud_open | chassis_collision | True | 0.714 | True | 0.747 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90000__czNbAnC | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90000__j3t6x55 |
| rover-fork_barrier_mud-seed90001 | mud_open | time_budget_exhausted | True | 0.699 | True | 0.771 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90001__FgM9WHi | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90001__EP7tcSS |
| rover-fork_barrier_mud-seed90001 | mud_open | rollover | True | 0.699 | True | 0.771 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90001__kwiTpqU | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90001__EP7tcSS |
| rover-fork_barrier_mud-seed90006 | barrier_open | chassis_collision | True | 0.651 | True | 0.744 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90006__7g4vkzo | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90006__VQWHN6R |
| rover-fork_barrier_mud-seed90006 | barrier_open | chassis_collision | True | 0.651 | True | 0.744 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90006__u29xn4Y | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90006__VQWHN6R |
| rover-fork_barrier_mud-seed90010 | barrier_open | cargo not inside goal circle | True | 0.699 | True | 0.745 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90010__2SWWafz | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90010__dw5hxuk |
| rover-fork_crate_barrier_mud-seed90001 | mud_open | chassis_collision | True | 0.551 | True | 0.653 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__5cWperh | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__5fFERCz |
| rover-fork_crate_barrier_mud-seed90015 | crate_open | cargo not inside goal circle | True | 0.724 | True | 0.711 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__7oDuUcw | jobs/eval-deepseek-20261115-005726/rover-fork_crate_barrier_mud-see__eHAtmX7 |
| rover-fork_crate_barrier_mud-seed90000 | crate_open | time_budget_exhausted | True | 0.712 | True | 0.718 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__8BQ6z7v | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__XcQQT9J |
| rover-fork_crate_barrier_mud-seed90015 | crate_open | chassis_collision | True | 0.724 | True | 0.711 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__VvA92HD | jobs/eval-deepseek-20261115-005726/rover-fork_crate_barrier_mud-see__eHAtmX7 |
| rover-fork_crate_barrier_mud-seed90003 | barrier_open | chassis_collision | True | 0.724 | True | 0.674 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__Wcbd4pU | jobs/eval-deepseek-20261115-005726/rover-fork_crate_barrier_mud-see__u2QSxLv |
| rover-fork_crate_barrier_mud-seed90001 | mud_open | cargo not inside goal circle | True | 0.551 | True | 0.653 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__WnmyBTb | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__5fFERCz |
| rover-fork_crate_barrier_mud-seed90003 | barrier_open | cargo not inside goal circle | True | 0.724 | True | 0.674 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__h7XZZoC | jobs/eval-deepseek-20261115-005726/rover-fork_crate_barrier_mud-see__u2QSxLv |
| rover-fork_crate_barrier_mud-seed90000 | crate_open | chassis_collision | True | 0.712 | True | 0.718 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__rLCYx2x | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__XcQQT9J |
| rover-fork_crate_ice-seed90000 | crate_open | chassis_collision | True | 0.767 | True | 0.676 | jobs/eval-inkling-20261115-005608/rover-fork_crate_ice-seed90000__XgLtevJ | jobs/eval-deepseek-20261115-005638/rover-fork_crate_ice-seed90000__6LkaWyu |
| rover-fork_crate_ice-seed90003 | ice_open | time_budget_exhausted | True | 0.645 | True | 0.736 | jobs/eval-inkling-20261115-005608/rover-fork_crate_ice-seed90003__3ZGhFay | jobs/eval-deepseek-20261115-005638/rover-fork_crate_ice-seed90003__9HNLgL6 |
| rover-fork_crate_ice-seed90003 | ice_open | cargo not inside goal circle | True | 0.645 | True | 0.736 | jobs/eval-inkling-20261115-005608/rover-fork_crate_ice-seed90003__cy5hoyJ | jobs/eval-deepseek-20261115-005638/rover-fork_crate_ice-seed90003__9HNLgL6 |
| rover-fork_crate_wind-seed90000 | wind_open | cargo not inside goal circle | True | 0.648 | True | 0.738 | jobs/eval-inkling-20261115-005608/rover-fork_crate_wind-seed90000__7DyYNkw | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90000__gKxoFvm |
| rover-fork_crate_wind-seed90000 | wind_open | cargo not inside goal circle | True | 0.648 | True | 0.738 | jobs/eval-inkling-20261115-005608/rover-fork_crate_wind-seed90000__ktE8Xqm | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90000__gKxoFvm |
| rover-fork_crate_wind-seed90001 | wind_open | time_budget_exhausted | True | 0.681 | True | 0.736 | jobs/eval-inkling-20261115-005608/rover-fork_crate_wind-seed90001__6MZ5RDy | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90001__G2tdB57 |
| rover-fork_crate_wind-seed90001 | wind_open | chassis_collision | True | 0.681 | True | 0.736 | jobs/eval-inkling-20261115-005608/rover-fork_crate_wind-seed90001__JhTc6g7 | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90001__G2tdB57 |
| rover-fork_crate_wind-seed90006 | crate_open | cargo not inside goal circle | True | 0.682 | True | 0.677 | jobs/eval-inkling-20261115-005608/rover-fork_crate_wind-seed90006__9VMe2rq | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90006__MLSqKFQ |
| rover-fork_crate_wind-seed90008 | crate_open | cargo_dropped | True | 0.756 | True | 0.688 | jobs/eval-inkling-20261115-005608/rover-fork_crate_wind-seed90008__L9JhUyo | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90008__5QHdexo |
| rover-fork_mud_ice-seed90000 | ice_open | rollover | True | 0.705 | True | 0.741 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90000__VZreTPB | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90000__tjxmjeq |
| rover-fork_mud_ice-seed90000 | ice_open | rollover | True | 0.705 | True | 0.741 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90000__b4tDc9G | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90000__tjxmjeq |
| rover-fork_mud_ice-seed90002 | mud_open | chassis_collision | True | 0.677 | True | 0.734 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__FzcBPGr | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90002__Fmwd6K8 |
| rover-fork_mud_ice-seed90002 | mud_open | chassis_collision | True | 0.677 | True | 0.734 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__e9TA84d | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90002__Fmwd6K8 |
| rover-fork_mud_ice-seed90003 | mud_open | chassis_collision | True | 0.742 | True | 0.753 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90003__UtrsJvR | jobs/eval-deepseek-20261115-005726/rover-fork_mud_ice-seed90003__CuStCSZ |
| rover-fork_mud_ice-seed90003 | mud_open | chassis_collision | True | 0.742 | True | 0.753 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90003__eLeWVCW | jobs/eval-deepseek-20261115-005726/rover-fork_mud_ice-seed90003__CuStCSZ |
| rover-fork_mud_ice_wind-seed90004 | mud_open | rollover | True | 0.732 | True | 0.787 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice_wind-seed9000__VzLZKND | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__LLM2GV4 |
| rover-fork_mud_ice_wind-seed90001 | ice_open | cargo not inside goal circle | True | 0.702 | True | 0.703 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice_wind-seed9000__iGPKtYU | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__W5vkMLh |
| rover-fork_mud_ice_wind-seed90001 | ice_open | left_drivable_surface | True | 0.702 | True | 0.703 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice_wind-seed9000__sjAdZES | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__W5vkMLh |
| rover-fork_replan-seed90000 | mud_open+crate_open | energy_budget_exhausted | True | 0.652 | True | 0.699 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90000__VDnVq8B | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90000__iVbhfzi |
| rover-fork_replan-seed90000 | mud_open+crate_open | rollover | True | 0.652 | True | 0.699 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90000__dhZZkKQ | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90000__iVbhfzi |
| rover-fork_replan-seed90001 | ice_open+barrier_open | chassis_collision | True | 0.545 | True | 0.691 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90001__ivjqWhN | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90001__5dRqWHS |
| rover-fork_replan-seed90001 | ice_open+barrier_open | time_budget_exhausted | True | 0.545 | True | 0.691 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90001__qsvJzXp | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90001__5dRqWHS |
| rover-fork_replan-seed90005 | ice_open+crate_open | chassis_collision | True | 0.649 | True | 0.704 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90005__P4XwQBo | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90005__PE9Thr9 |
| rover-fork_replan-seed90005 | ice_open+crate_open | cargo not inside goal circle | True | 0.649 | True | 0.704 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90005__xPoiR87 | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90005__PE9Thr9 |
| rover-fork_wind_mud-seed90001 | wind_open | left_drivable_surface | True | 0.791 | True | 0.817 | jobs/eval-inkling-20261115-005608/rover-fork_wind_mud-seed90001__dfugwgx | jobs/eval-deepseek-20261115-005638/rover-fork_wind_mud-seed90001__3oHhUiN |
| rover-fork_wind_mud-seed90004 | mud_open | chassis_collision | True | 0.659 | True | 0.723 | jobs/eval-inkling-20261115-005608/rover-fork_wind_mud-seed90004__66jkACS | jobs/eval-deepseek-20261115-005638/rover-fork_wind_mud-seed90004__sndSa4w |
| rover-fork_wind_mud-seed90004 | mud_open | rollover | True | 0.659 | True | 0.723 | jobs/eval-inkling-20261115-005608/rover-fork_wind_mud-seed90004__ZZMVmYK | jobs/eval-deepseek-20261115-005638/rover-fork_wind_mud-seed90004__sndSa4w |
| rover-serpentine-seed90001 | serpentine_open | time_budget_exhausted | False | 0.624 | False | 0.558 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90001__GLFTV5Z | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90001__hXFv6yZ |
| rover-serpentine-seed90001 | serpentine_open | time_budget_exhausted | True | 0.624 | False | 0.558 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90001__v4gLiFC | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90001__hXFv6yZ |
| rover-serpentine-seed90002 | shortcut_open | cargo not inside goal circle | True | 0.807 | True | 0.767 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90002__kTNygqV | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90002__ZW2NjM9 |
| rover-serpentine-seed90002 | shortcut_open | chassis_collision | True | 0.807 | True | 0.767 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90002__nxE79TY | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90002__ZW2NjM9 |
| rover-serpentine-seed90003 | serpentine_open | time_budget_exhausted | True | 0.569 | False | 0.552 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90003__T2ZqTxQ | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90003__MWLhetM |
| rover-serpentine-seed90003 | serpentine_open | cargo not inside goal circle | True | 0.569 | False | 0.552 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90003__bho3HGW | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90003__MWLhetM |
| winch-barrier-seed90000 | stiff | cable snapped | True | 0.772 | False | 0.741 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90000__QrwZi8e | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90000__dp8jJJQ |
| winch-barrier-seed90000 | stiff | time_budget_exhausted | True | 0.772 | False | 0.741 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90000__zbxTnAx | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90000__dp8jJJQ |
| winch-barrier-seed90001 | stiff | cable snapped | False | 0.819 | True | 0.826 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90001__RvfrmQR | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90001__LHhnWUs |
| winch-barrier-seed90005 | soft | cable snapped | True | 0.801 | True | 0.820 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__GHdkTJo | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc |
| winch-barrier-seed90005 | soft | cable snapped | False | 0.801 | True | 0.820 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__VsMe5pA | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc |
| winch-crowded-seed90000 | stiff | no crate has sat still on the goal, released, for long enough | None | 0.877 | True | 0.871 | jobs/eval-inkling-20261115-005608/winch-crowded-seed90000__BJLv8Az | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90000__fBfhfeR |
| winch-crowded-seed90001 | soft | cable snapped | True | 0.774 | True | 0.736 | jobs/eval-inkling-20261115-005608/winch-crowded-seed90001__Uy6gLX6 | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90001__S2x2LmT |
| winch-crowded-seed90001 | soft | cable snapped | True | 0.774 | True | 0.736 | jobs/eval-inkling-20261115-005608/winch-crowded-seed90001__yEJhozR | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90001__S2x2LmT |
| winch-crowded-seed90006 | stiff | cable snapped | False | 0.823 | True | 0.843 | jobs/eval-inkling-20261115-005608/winch-crowded-seed90006__WMJxQiK | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90006__A7n7Vh9 |
| winch-crowded-seed90006 | stiff | never adjudicated (agent stopped without finish) | None | 0.823 | True | 0.843 | jobs/eval-inkling-20261115-005608/winch-crowded-seed90006__qMpwoCB | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90006__A7n7Vh9 |
| winch-gain_reference-seed90001 | stiff | cable snapped | True | 0.809 | False | 0.784 | jobs/eval-inkling-20261115-005608/winch-gain_reference-seed90001__DycWK7h | jobs/eval-deepseek-20261115-005638/winch-gain_reference-seed90001__a3TZpHa |
| winch-gain_reference-seed90001 | stiff | cable snapped | True | 0.809 | False | 0.784 | jobs/eval-inkling-20261115-005608/winch-gain_reference-seed90001__TuPonLb | jobs/eval-deepseek-20261115-005638/winch-gain_reference-seed90001__a3TZpHa |
| winch-high_stack-seed90000 | stiff | cable snapped | False | 0.756 | True | 0.746 | jobs/eval-inkling-20261115-005608/winch-high_stack-seed90000__NfTpYCZ | jobs/eval-deepseek-20261115-005726/winch-high_stack-seed90000__BAACBpG |
| winch-high_stack-seed90000 | stiff | cable snapped | False | 0.756 | True | 0.746 | jobs/eval-inkling-20261115-005608/winch-high_stack-seed90000__xgMSKrG | jobs/eval-deepseek-20261115-005726/winch-high_stack-seed90000__BAACBpG |
| winch-high_stack-seed90001 | stiff | cable snapped | True | 0.855 | True | 0.829 | jobs/eval-inkling-20261115-005608/winch-high_stack-seed90001__UkjMo9E | jobs/eval-deepseek-20261115-005638/winch-high_stack-seed90001__2BzqGGM |
| winch-high_stack-seed90001 | stiff | cable snapped | True | 0.855 | True | 0.829 | jobs/eval-inkling-20261115-005608/winch-high_stack-seed90001__pCWUNT8 | jobs/eval-deepseek-20261115-005638/winch-high_stack-seed90001__2BzqGGM |
| winch-high_stack-seed90005 | soft | cable snapped | False | 0.818 | True | 0.823 | jobs/eval-inkling-20261115-005608/winch-high_stack-seed90005__KNHnbFW | jobs/eval-deepseek-20261115-005638/winch-high_stack-seed90005__KZL2NCg |
| winch-high_stack-seed90005 | soft | cable snapped | True | 0.818 | True | 0.823 | jobs/eval-inkling-20261115-005608/winch-high_stack-seed90005__NsM55xB | jobs/eval-deepseek-20261115-005638/winch-high_stack-seed90005__KZL2NCg |
| winch-left_bank-seed90000 | stiff | cable snapped | True | 0.859 | False | 0.837 | jobs/eval-inkling-20261115-005608/winch-left_bank-seed90000__7YX9Vy3 | jobs/eval-deepseek-20261115-005638/winch-left_bank-seed90000__cs4sfdm |
| winch-left_bank-seed90000 | stiff | cable snapped | True | 0.859 | False | 0.837 | jobs/eval-inkling-20261115-005608/winch-left_bank-seed90000__gPbRxr8 | jobs/eval-deepseek-20261115-005638/winch-left_bank-seed90000__cs4sfdm |
| winch-left_bank-seed90005 | soft | never adjudicated (agent stopped without finish) | True | 0.780 | True | 0.755 | jobs/eval-inkling-20261115-005608/winch-left_bank-seed90005__7rz8mQe | jobs/eval-deepseek-20261115-005638/winch-left_bank-seed90005__gHzAJPi |
| winch-left_bank-seed90005 | soft | cable snapped | True | 0.780 | True | 0.755 | jobs/eval-inkling-20261115-005608/winch-left_bank-seed90005__UxfVB33 | jobs/eval-deepseek-20261115-005638/winch-left_bank-seed90005__gHzAJPi |
| winch-seed90002 | soft | no crate has sat still on the goal, released, for long enough | None | 0.778 | False | 0.747 | jobs/eval-inkling-20261115-005608/winch-seed90002__RDdG7Jg | jobs/eval-deepseek-20261115-005638/winch-seed90002__SZhESoW |
| winch-seed90002 | soft | no crate has sat still on the goal, released, for long enough | False | 0.778 | False | 0.747 | jobs/eval-inkling-20261115-005608/winch-seed90002__rGegG8f | jobs/eval-deepseek-20261115-005638/winch-seed90002__SZhESoW |
| winch-short_pair-seed90000 | soft | cable snapped | True | 0.772 | True | 0.751 | jobs/eval-inkling-20261115-005608/winch-short_pair-seed90000__Yt3r39q | jobs/eval-deepseek-20261115-005638/winch-short_pair-seed90000__DPJGbdg |
| winch-short_pair-seed90001 | soft | cable snapped | True | 0.713 | True | 0.785 | jobs/eval-inkling-20261115-005608/winch-short_pair-seed90001__G96Mp78 | jobs/eval-deepseek-20261115-005638/winch-short_pair-seed90001__2chC952 |
| winch-short_pair-seed90001 | soft | cable snapped | True | 0.713 | True | 0.785 | jobs/eval-inkling-20261115-005608/winch-short_pair-seed90001__vh9L7ev | jobs/eval-deepseek-20261115-005638/winch-short_pair-seed90001__2chC952 |
| winch-short_pair-seed90003 | stiff | no crate has sat still on the goal, released, for long enough | True | 0.818 | False | 0.778 | jobs/eval-inkling-20261115-005608/winch-short_pair-seed90003__McCWZyp | jobs/eval-deepseek-20261115-005638/winch-short_pair-seed90003__FmJoZfY |
| winch-stuck_crate-seed90005 | soft_free | time_budget_exhausted | None | 0.882 | False | 0.862 | jobs/eval-inkling-20261115-005608/winch-stuck_crate-seed90005__qRPP69A | jobs/eval-deepseek-20261115-005726/winch-stuck_crate-seed90005__CoARctS |
| winch-weight_window-seed90000 | stiff | cable snapped | True | 0.807 | True | 0.750 | jobs/eval-inkling-20261115-005608/winch-weight_window-seed90000__A42vAQ8 | jobs/eval-deepseek-20261115-005638/winch-weight_window-seed90000__bMgy4fe |
| winch-weight_window-seed90000 | stiff | cable snapped | True | 0.807 | True | 0.750 | jobs/eval-inkling-20261115-005608/winch-weight_window-seed90000__CFupYjm | jobs/eval-deepseek-20261115-005638/winch-weight_window-seed90000__bMgy4fe |
| winch-weight_window-seed90005 | soft | cable snapped | False | 0.706 | False | 0.828 | jobs/eval-inkling-20261115-005608/winch-weight_window-seed90005__br7hVeJ | jobs/eval-deepseek-20261115-005638/winch-weight_window-seed90005__EGQUh5c |
| rover-fork_barrier_mud-seed90001 | mud_open | rollover | True | 0.699 | True | 0.771 | jobs/eval-inkling-20261115-005656/rover-fork_barrier_mud-seed90001__dj9MxT9 | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90001__EP7tcSS |
| rover-fork_barrier_mud-seed90006 | barrier_open | chassis_collision | True | 0.651 | True | 0.744 | jobs/eval-inkling-20261115-005656/rover-fork_barrier_mud-seed90006__HksPgBs | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90006__VQWHN6R |
| rover-fork_barrier_mud-seed90010 | barrier_open | left_drivable_surface | True | 0.699 | True | 0.745 | jobs/eval-inkling-20261115-005656/rover-fork_barrier_mud-seed90010__zYoqepC | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90010__dw5hxuk |
| rover-fork_crate_barrier_mud-seed90003 | barrier_open | chassis_collision | True | 0.724 | True | 0.674 | jobs/eval-inkling-20261115-005656/rover-fork_crate_barrier_mud-see__BmqZg9Y | jobs/eval-deepseek-20261115-005726/rover-fork_crate_barrier_mud-see__u2QSxLv |
| rover-fork_crate_barrier_mud-seed90001 | mud_open | cargo not inside goal circle | True | 0.551 | True | 0.653 | jobs/eval-inkling-20261115-005656/rover-fork_crate_barrier_mud-see__Vp5B2eb | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__5fFERCz |
| rover-fork_crate_barrier_mud-seed90015 | crate_open | cargo not inside goal circle | True | 0.724 | True | 0.711 | jobs/eval-inkling-20261115-005656/rover-fork_crate_barrier_mud-see__gk4vYrH | jobs/eval-deepseek-20261115-005726/rover-fork_crate_barrier_mud-see__eHAtmX7 |
| rover-fork_crate_barrier_mud-seed90000 | crate_open | time_budget_exhausted | True | 0.712 | True | 0.718 | jobs/eval-inkling-20261115-005656/rover-fork_crate_barrier_mud-see__pJZSiHt | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__XcQQT9J |
| rover-fork_crate_ice-seed90003 | ice_open | chassis_collision | True | 0.645 | True | 0.736 | jobs/eval-inkling-20261115-005656/rover-fork_crate_ice-seed90003__Cnougc8 | jobs/eval-deepseek-20261115-005638/rover-fork_crate_ice-seed90003__9HNLgL6 |
| rover-fork_crate_wind-seed90000 | wind_open | time_budget_exhausted | True | 0.648 | True | 0.738 | jobs/eval-inkling-20261115-005656/rover-fork_crate_wind-seed90000__VQFAZXu | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90000__gKxoFvm |
| rover-fork_crate_wind-seed90001 | wind_open | chassis_collision | True | 0.681 | True | 0.736 | jobs/eval-inkling-20261115-005656/rover-fork_crate_wind-seed90001__9G6Jrar | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90001__G2tdB57 |
| rover-fork_crate_wind-seed90006 | crate_open | rollover | True | 0.682 | True | 0.677 | jobs/eval-inkling-20261115-005656/rover-fork_crate_wind-seed90006__cqmTw5h | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90006__MLSqKFQ |
| rover-fork_crate_wind-seed90008 | crate_open | cargo_dropped | True | 0.756 | True | 0.688 | jobs/eval-inkling-20261115-005656/rover-fork_crate_wind-seed90008__aKBLHiH | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90008__5QHdexo |
| rover-fork_mud_ice-seed90000 | ice_open | time_budget_exhausted | True | 0.705 | True | 0.741 | jobs/eval-inkling-20261115-005656/rover-fork_mud_ice-seed90000__t3bSgoD | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90000__tjxmjeq |
| rover-fork_mud_ice-seed90001 | ice_open | chassis_collision | True | 0.647 | True | 0.745 | jobs/eval-inkling-20261115-005656/rover-fork_mud_ice-seed90001__VXAScLB | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90001__PcSWi9q |
| rover-fork_mud_ice-seed90002 | mud_open | chassis_collision | True | 0.677 | True | 0.734 | jobs/eval-inkling-20261115-005656/rover-fork_mud_ice-seed90002__opXBrsH | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90002__Fmwd6K8 |
| rover-fork_mud_ice_wind-seed90001 | ice_open | rollover | True | 0.702 | True | 0.703 | jobs/eval-inkling-20261115-005656/rover-fork_mud_ice_wind-seed9000__fhxDgRU | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__W5vkMLh |
| rover-fork_mud_ice_wind-seed90004 | mud_open | rollover | True | 0.732 | True | 0.787 | jobs/eval-inkling-20261115-005656/rover-fork_mud_ice_wind-seed9000__uFxVgSU | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__LLM2GV4 |
| rover-fork_replan-seed90000 | mud_open+crate_open | chassis_collision | True | 0.652 | True | 0.699 | jobs/eval-inkling-20261115-005656/rover-fork_replan-seed90000__Rc8MJsi | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90000__iVbhfzi |
| rover-fork_replan-seed90001 | ice_open+barrier_open | time_budget_exhausted | True | 0.545 | True | 0.691 | jobs/eval-inkling-20261115-005656/rover-fork_replan-seed90001__CqHcGzV | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90001__5dRqWHS |
| rover-fork_replan-seed90005 | ice_open+crate_open | never adjudicated (agent stopped without finish) | None | 0.649 | True | 0.704 | jobs/eval-inkling-20261115-005656/rover-fork_replan-seed90005__xr4hyBd | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90005__PE9Thr9 |
| rover-fork_wind_mud-seed90000 | wind_open | time_budget_exhausted | True | 0.685 | True | 0.820 | jobs/eval-inkling-20261115-005656/rover-fork_wind_mud-seed90000__pLJGbnS | jobs/eval-deepseek-20261115-005638/rover-fork_wind_mud-seed90000__vxqtNGL |
| rover-fork_wind_mud-seed90004 | mud_open | cargo_dropped | True | 0.659 | True | 0.723 | jobs/eval-inkling-20261115-005656/rover-fork_wind_mud-seed90004__tdXxmVQ | jobs/eval-deepseek-20261115-005638/rover-fork_wind_mud-seed90004__sndSa4w |
| rover-serpentine-seed90000 | shortcut_open | chassis_collision | True | 0.851 | False | 0.760 | jobs/eval-inkling-20261115-005656/rover-serpentine-seed90000__cvuUWXJ | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90000__LvkR4ZN |
| rover-serpentine-seed90001 | serpentine_open | chassis_collision | True | 0.624 | False | 0.558 | jobs/eval-inkling-20261115-005656/rover-serpentine-seed90001__JbH4jVh | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90001__hXFv6yZ |
| rover-serpentine-seed90002 | shortcut_open | chassis_collision | True | 0.807 | True | 0.767 | jobs/eval-inkling-20261115-005656/rover-serpentine-seed90002__o6uxWFT | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90002__ZW2NjM9 |
| rover-serpentine-seed90003 | serpentine_open | time_budget_exhausted | True | 0.569 | False | 0.552 | jobs/eval-inkling-20261115-005656/rover-serpentine-seed90003__rwGoetg | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90003__MWLhetM |
| winch-barrier-seed90000 | stiff | cable snapped | True | 0.772 | False | 0.741 | jobs/eval-inkling-20261115-005656/winch-barrier-seed90000__w9N9iFC | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90000__dp8jJJQ |
| winch-barrier-seed90001 | stiff | cable snapped | False | 0.819 | True | 0.826 | jobs/eval-inkling-20261115-005656/winch-barrier-seed90001__Sj4kHzh | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90001__LHhnWUs |
| winch-barrier-seed90005 | soft | time_budget_exhausted | True | 0.801 | True | 0.820 | jobs/eval-inkling-20261115-005656/winch-barrier-seed90005__9ce8naZ | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc |
| winch-crowded-seed90006 | stiff | cable snapped | True | 0.823 | True | 0.843 | jobs/eval-inkling-20261115-005656/winch-crowded-seed90006__f63BwiU | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90006__A7n7Vh9 |
| winch-high_stack-seed90000 | stiff | cable snapped | True | 0.756 | True | 0.746 | jobs/eval-inkling-20261115-005656/winch-high_stack-seed90000__bqfmiK8 | jobs/eval-deepseek-20261115-005726/winch-high_stack-seed90000__BAACBpG |
| winch-high_stack-seed90001 | stiff | cable snapped | True | 0.855 | True | 0.829 | jobs/eval-inkling-20261115-005656/winch-high_stack-seed90001__ggANDC4 | jobs/eval-deepseek-20261115-005638/winch-high_stack-seed90001__2BzqGGM |
| winch-high_stack-seed90005 | soft | no crate has sat still on the goal, released, for long enough | False | 0.818 | True | 0.823 | jobs/eval-inkling-20261115-005656/winch-high_stack-seed90005__A8tGyFR | jobs/eval-deepseek-20261115-005638/winch-high_stack-seed90005__KZL2NCg |
| winch-left_bank-seed90000 | stiff | cable snapped | False | 0.859 | False | 0.837 | jobs/eval-inkling-20261115-005656/winch-left_bank-seed90000__QCQgye5 | jobs/eval-deepseek-20261115-005638/winch-left_bank-seed90000__cs4sfdm |
| winch-seed90002 | soft | cable snapped | False | 0.778 | False | 0.747 | jobs/eval-inkling-20261115-005656/winch-seed90002__mBqMm9U | jobs/eval-deepseek-20261115-005638/winch-seed90002__SZhESoW |
| winch-short_pair-seed90003 | stiff | no crate has sat still on the goal, released, for long enough | True | 0.818 | False | 0.778 | jobs/eval-inkling-20261115-005656/winch-short_pair-seed90003__R9J3WLZ | jobs/eval-deepseek-20261115-005638/winch-short_pair-seed90003__FmJoZfY |
| winch-stuck_crate-seed90005 | soft_free | cable snapped | False | 0.882 | False | 0.862 | jobs/eval-inkling-20261115-005656/winch-stuck_crate-seed90005__cBdBcTV | jobs/eval-deepseek-20261115-005726/winch-stuck_crate-seed90005__CoARctS |
| winch-weight_window-seed90000 | stiff | cable snapped | False | 0.807 | True | 0.750 | jobs/eval-inkling-20261115-005656/winch-weight_window-seed90000__wohx7g8 | jobs/eval-deepseek-20261115-005638/winch-weight_window-seed90000__bMgy4fe |
| winch-weight_window-seed90005 | soft | cable snapped | False | 0.706 | False | 0.828 | jobs/eval-inkling-20261115-005656/winch-weight_window-seed90005__CWiFMoV | jobs/eval-deepseek-20261115-005638/winch-weight_window-seed90005__EGQUh5c |
| rover-fork_crate_ice-seed90001 | crate_open | chassis_collision | True | 0.767 | True | 0.688 | jobs/eval-inkling-rerun-ink_rerun_a-012831/rover-fork_crate_ice-seed90001__6NFRutB | jobs/eval-deepseek-20261115-005726/rover-fork_crate_ice-seed90001__5WWXujZ |
| rover-fork_crate_wind-seed90008 | crate_open | chassis_collision | True | 0.756 | True | 0.688 | jobs/eval-inkling-rerun-ink_rerun_a-012831/rover-fork_crate_wind-seed90008__4HSVQQK | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90008__5QHdexo |
| rover-fork_mud_ice-seed90001 | ice_open | chassis_collision | True | 0.647 | True | 0.745 | jobs/eval-inkling-rerun-ink_rerun_a-012831/rover-fork_mud_ice-seed90001__YkYmq6u | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90001__PcSWi9q |
| winch-barrier-seed90001 | stiff | cable snapped | False | 0.819 | True | 0.826 | jobs/eval-inkling-rerun-ink_rerun_a-012831/winch-barrier-seed90001__nNLjijH | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90001__LHhnWUs |
| winch-crowded-seed90000 | stiff | cable snapped | True | 0.877 | True | 0.871 | jobs/eval-inkling-rerun-ink_rerun_a-012831/winch-crowded-seed90000__tYq7Cxh | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90000__fBfhfeR |
| winch-gain_reference-seed90001 | stiff | cable snapped | True | 0.809 | False | 0.784 | jobs/eval-inkling-rerun-ink_rerun_a-012831/winch-gain_reference-seed90001__xgYQW7i | jobs/eval-deepseek-20261115-005638/winch-gain_reference-seed90001__a3TZpHa |
| winch-left_bank-seed90005 | soft | cable snapped | False | 0.780 | True | 0.755 | jobs/eval-inkling-rerun-ink_rerun_a-012831/winch-left_bank-seed90005__dvngVWV | jobs/eval-deepseek-20261115-005638/winch-left_bank-seed90005__gHzAJPi |
| winch-seed90000 | stiff | cable snapped | False | 0.797 | False | 0.805 | jobs/eval-inkling-rerun-ink_rerun_a-012831/winch-seed90000__tjCvq67 | jobs/eval-deepseek-20261115-005638/winch-seed90000__CBQkBoW |
| winch-short_pair-seed90001 | soft | delivered crate is below the required payload | True | 0.713 | True | 0.785 | jobs/eval-inkling-rerun-ink_rerun_a-012831/winch-short_pair-seed90001__GPXoBkC | jobs/eval-deepseek-20261115-005638/winch-short_pair-seed90001__2chC952 |
| winch-stuck_crate-seed90005 | soft_free | never adjudicated (agent stopped without finish) | False | 0.882 | False | 0.862 | jobs/eval-inkling-rerun-ink_rerun_a-012831/winch-stuck_crate-seed90005__fAaSEWP | jobs/eval-deepseek-20261115-005726/winch-stuck_crate-seed90005__CoARctS |
| rover-fork_crate_ice-seed90001 | crate_open | time_budget_exhausted | True | 0.767 | True | 0.688 | jobs/eval-inkling-rerun-ink_rerun_b-014113/rover-fork_crate_ice-seed90001__LLtm3NY | jobs/eval-deepseek-20261115-005726/rover-fork_crate_ice-seed90001__5WWXujZ |


## All trials

| Model | Task | Regime | Reward | Reason | Sim t | Env calls | Tested | Lane | Off-map cmds | Trial dir |
|---|---|---|---|---|---|---|---|---|---|---|
| inkling | rover-fork_barrier_mud-seed90000 | mud_open | 0.000 | chassis_collision | 27.4 | 14 | True | None | 1 | rover-fork_barrier_mud-seed90000__czNbAnC |
| inkling | rover-fork_barrier_mud-seed90000 | mud_open | 0.610 | delivered | 63.1 | 16 | True | open | 0 | rover-fork_barrier_mud-seed90000__GZiAaKX |
| inkling | rover-fork_barrier_mud-seed90000 | mud_open | 0.621 | delivered | 62.6 | 18 | True | open | 0 | rover-fork_barrier_mud-seed90000__2VYGxTr |
| inkling | rover-fork_barrier_mud-seed90001 | mud_open | 0.000 | time_budget_exhausted | 65.5 | 18 | True | open | 0 | rover-fork_barrier_mud-seed90001__FgM9WHi |
| inkling | rover-fork_barrier_mud-seed90001 | mud_open | 0.000 | rollover | 22.0 | 13 | True | None | 1 | rover-fork_barrier_mud-seed90001__kwiTpqU |
| inkling | rover-fork_barrier_mud-seed90001 | mud_open | 0.000 | rollover | 37.7 | 17 | True | None | 1 | rover-fork_barrier_mud-seed90001__dj9MxT9 |
| inkling | rover-fork_barrier_mud-seed90006 | barrier_open | 0.000 | chassis_collision | 14.9 | 10 | True | None | 1 | rover-fork_barrier_mud-seed90006__7g4vkzo |
| inkling | rover-fork_barrier_mud-seed90006 | barrier_open | 0.000 | chassis_collision | 72.3 | 17 | True | open | 1 | rover-fork_barrier_mud-seed90006__u29xn4Y |
| inkling | rover-fork_barrier_mud-seed90006 | barrier_open | 0.000 | chassis_collision | 74.4 | 14 | True | None | 1 | rover-fork_barrier_mud-seed90006__HksPgBs |
| inkling | rover-fork_barrier_mud-seed90010 | barrier_open | 0.000 | cargo not inside goal circle | 77.2 | 17 | True | closed | 0 | rover-fork_barrier_mud-seed90010__2SWWafz |
| inkling | rover-fork_barrier_mud-seed90010 | barrier_open | 0.708 | delivered | 66.3 | 21 | True | open | 0 | rover-fork_barrier_mud-seed90010__TS8SFxZ |
| inkling | rover-fork_barrier_mud-seed90010 | barrier_open | 0.000 | left_drivable_surface | 50.6 | 20 | True | None | 1 | rover-fork_barrier_mud-seed90010__zYoqepC |
| inkling | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.000 | time_budget_exhausted | 78.1 | 18 | True | open | 0 | rover-fork_crate_barrier_mud-see__8BQ6z7v |
| inkling | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.000 | chassis_collision | 72.2 | 20 | True | open | 0 | rover-fork_crate_barrier_mud-see__rLCYx2x |
| inkling | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.000 | time_budget_exhausted | 78.1 | 24 | True | open | 1 | rover-fork_crate_barrier_mud-see__pJZSiHt |
| inkling | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.000 | chassis_collision | 80.9 | 20 | True | open | 1 | rover-fork_crate_barrier_mud-see__5cWperh |
| inkling | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.000 | cargo not inside goal circle | 89.7 | 20 | True | closed | 2 | rover-fork_crate_barrier_mud-see__WnmyBTb |
| inkling | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.000 | cargo not inside goal circle | 90.8 | 15 | True | None | 0 | rover-fork_crate_barrier_mud-see__Vp5B2eb |
| inkling | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.000 | chassis_collision | 21.0 | 13 | True | None | 0 | rover-fork_crate_barrier_mud-see__Wcbd4pU |
| inkling | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.000 | cargo not inside goal circle | 89.8 | 20 | True | None | 1 | rover-fork_crate_barrier_mud-see__h7XZZoC |
| inkling | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.000 | chassis_collision | 64.4 | 17 | True | None | 2 | rover-fork_crate_barrier_mud-see__BmqZg9Y |
| inkling | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.000 | cargo not inside goal circle | 79.1 | 18 | True | closed | 2 | rover-fork_crate_barrier_mud-see__7oDuUcw |
| inkling | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.000 | chassis_collision | 78.3 | 17 | True | open | 1 | rover-fork_crate_barrier_mud-see__VvA92HD |
| inkling | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.000 | cargo not inside goal circle | 76.5 | 14 | True | closed | 1 | rover-fork_crate_barrier_mud-see__gk4vYrH |
| inkling | rover-fork_crate_ice-seed90000 | crate_open | 0.000 | chassis_collision | 29.0 | 12 | True | None | 1 | rover-fork_crate_ice-seed90000__XgLtevJ |
| inkling | rover-fork_crate_ice-seed90000 | crate_open | 0.647 | delivered | 62.6 | 17 | True | open | 0 | rover-fork_crate_ice-seed90000__hi5UVJE |
| inkling | rover-fork_crate_ice-seed90000 | crate_open | 0.654 | delivered | 58.0 | 19 | True | open | 0 | rover-fork_crate_ice-seed90000__RbCRTXX |
| inkling | rover-fork_crate_ice-seed90001 | crate_open | 0.648 | delivered | 62.3 | 16 | True | open | 0 | rover-fork_crate_ice-seed90001__BLGZmGP |
| inkling | rover-fork_crate_ice-seed90001 | crate_open | 0.000 | chassis_collision | 50.1 | 19 | True | None | 1 | rover-fork_crate_ice-seed90001__6NFRutB |
| inkling | rover-fork_crate_ice-seed90001 | crate_open | 0.000 | time_budget_exhausted | 65.5 | 19 | True | open | 0 | rover-fork_crate_ice-seed90001__LLtm3NY |
| inkling | rover-fork_crate_ice-seed90003 | ice_open | 0.000 | time_budget_exhausted | 76.5 | 20 | True | closed | 0 | rover-fork_crate_ice-seed90003__3ZGhFay |
| inkling | rover-fork_crate_ice-seed90003 | ice_open | 0.000 | cargo not inside goal circle | 76.1 | 22 | True | closed | 0 | rover-fork_crate_ice-seed90003__cy5hoyJ |
| inkling | rover-fork_crate_ice-seed90003 | ice_open | 0.000 | chassis_collision | 37.0 | 12 | True | None | 1 | rover-fork_crate_ice-seed90003__Cnougc8 |
| inkling | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | time_budget_exhausted | 78.5 | 19 | True | closed | 0 | rover-fork_crate_ice-seed90004__2xykLDn |
| inkling | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | chassis_collision | 45.6 | 17 | True | open | 1 | rover-fork_crate_ice-seed90004__C6AR8r9 |
| inkling | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | cargo not inside goal circle | 78.1 | 16 | True | closed | 0 | rover-fork_crate_ice-seed90004__PvFPemw |
| inkling | rover-fork_crate_wind-seed90000 | wind_open | 0.000 | cargo not inside goal circle | 75.0 | 18 | True | None | 0 | rover-fork_crate_wind-seed90000__7DyYNkw |
| inkling | rover-fork_crate_wind-seed90000 | wind_open | 0.000 | cargo not inside goal circle | 74.3 | 20 | True | closed | 0 | rover-fork_crate_wind-seed90000__ktE8Xqm |
| inkling | rover-fork_crate_wind-seed90000 | wind_open | 0.000 | time_budget_exhausted | 76.1 | 18 | True | closed | 0 | rover-fork_crate_wind-seed90000__VQFAZXu |
| inkling | rover-fork_crate_wind-seed90001 | wind_open | 0.000 | time_budget_exhausted | 77.5 | 19 | True | None | 0 | rover-fork_crate_wind-seed90001__6MZ5RDy |
| inkling | rover-fork_crate_wind-seed90001 | wind_open | 0.000 | chassis_collision | 45.0 | 15 | True | None | 0 | rover-fork_crate_wind-seed90001__JhTc6g7 |
| inkling | rover-fork_crate_wind-seed90001 | wind_open | 0.000 | chassis_collision | 63.0 | 16 | True | closed | 1 | rover-fork_crate_wind-seed90001__9G6Jrar |
| inkling | rover-fork_crate_wind-seed90006 | crate_open | 0.000 | cargo not inside goal circle | 64.9 | 12 | True | open | 0 | rover-fork_crate_wind-seed90006__9VMe2rq |
| inkling | rover-fork_crate_wind-seed90006 | crate_open | 0.669 | delivered | 47.4 | 20 | True | open | 0 | rover-fork_crate_wind-seed90006__SKyMphV |
| inkling | rover-fork_crate_wind-seed90006 | crate_open | 0.000 | rollover | 46.0 | 16 | True | open | 1 | rover-fork_crate_wind-seed90006__cqmTw5h |
| inkling | rover-fork_crate_wind-seed90008 | crate_open | 0.000 | cargo_dropped | 25.2 | 8 | True | None | 0 | rover-fork_crate_wind-seed90008__L9JhUyo |
| inkling | rover-fork_crate_wind-seed90008 | crate_open | 0.000 | cargo_dropped | 23.3 | 11 | True | None | 0 | rover-fork_crate_wind-seed90008__aKBLHiH |
| inkling | rover-fork_crate_wind-seed90008 | crate_open | 0.000 | chassis_collision | 42.6 | 18 | True | None | 0 | rover-fork_crate_wind-seed90008__4HSVQQK |
| inkling | rover-fork_mud_ice-seed90000 | ice_open | 0.000 | rollover | 75.4 | 12 | True | closed | 0 | rover-fork_mud_ice-seed90000__VZreTPB |
| inkling | rover-fork_mud_ice-seed90000 | ice_open | 0.000 | rollover | 35.5 | 12 | True | None | 1 | rover-fork_mud_ice-seed90000__b4tDc9G |
| inkling | rover-fork_mud_ice-seed90000 | ice_open | 0.000 | time_budget_exhausted | 76.1 | 28 | True | open | 0 | rover-fork_mud_ice-seed90000__t3bSgoD |
| inkling | rover-fork_mud_ice-seed90001 | ice_open | 0.623 | delivered | 77.1 | 28 | True | open | 0 | rover-fork_mud_ice-seed90001__BSjiC56 |
| inkling | rover-fork_mud_ice-seed90001 | ice_open | 0.000 | chassis_collision | 39.7 | 12 | True | None | 0 | rover-fork_mud_ice-seed90001__VXAScLB |
| inkling | rover-fork_mud_ice-seed90001 | ice_open | 0.000 | chassis_collision | 47.1 | 21 | True | closed | 1 | rover-fork_mud_ice-seed90001__YkYmq6u |
| inkling | rover-fork_mud_ice-seed90002 | mud_open | 0.000 | chassis_collision | 40.2 | 19 | True | None | 1 | rover-fork_mud_ice-seed90002__FzcBPGr |
| inkling | rover-fork_mud_ice-seed90002 | mud_open | 0.000 | chassis_collision | 39.6 | 14 | True | None | 1 | rover-fork_mud_ice-seed90002__e9TA84d |
| inkling | rover-fork_mud_ice-seed90002 | mud_open | 0.000 | chassis_collision | 17.4 | 12 | True | None | 1 | rover-fork_mud_ice-seed90002__opXBrsH |
| inkling | rover-fork_mud_ice-seed90003 | mud_open | 0.000 | chassis_collision | 41.9 | 13 | True | None | 1 | rover-fork_mud_ice-seed90003__UtrsJvR |
| inkling | rover-fork_mud_ice-seed90003 | mud_open | 0.000 | chassis_collision | 27.0 | 17 | True | None | 1 | rover-fork_mud_ice-seed90003__eLeWVCW |
| inkling | rover-fork_mud_ice-seed90003 | mud_open | 0.687 | delivered | 48.2 | 17 | True | open | 0 | rover-fork_mud_ice-seed90003__BcM3jox |
| inkling | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | left_drivable_surface | 89.1 | 23 | True | open | 1 | rover-fork_mud_ice_wind-seed9000__BeggGDW |
| inkling | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | chassis_collision | 81.0 | 16 | True | closed | 1 | rover-fork_mud_ice_wind-seed9000__dETwrwy |
| inkling | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | cargo not inside goal circle | 83.5 | 26 | True | closed | 1 | rover-fork_mud_ice_wind-seed9000__tFeLZ6c |
| inkling | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.000 | cargo not inside goal circle | 86.5 | 14 | True | closed | 0 | rover-fork_mud_ice_wind-seed9000__iGPKtYU |
| inkling | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.000 | left_drivable_surface | 77.8 | 12 | True | closed | 1 | rover-fork_mud_ice_wind-seed9000__sjAdZES |
| inkling | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.000 | rollover | 62.2 | 20 | True | None | 1 | rover-fork_mud_ice_wind-seed9000__fhxDgRU |
| inkling | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.000 | rollover | 32.7 | 11 | True | None | 1 | rover-fork_mud_ice_wind-seed9000__VzLZKND |
| inkling | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.703 | delivered | 60.5 | 11 | True | open | 0 | rover-fork_mud_ice_wind-seed9000__t72jb5k |
| inkling | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.000 | rollover | 30.4 | 18 | True | None | 1 | rover-fork_mud_ice_wind-seed9000__uFxVgSU |
| inkling | rover-fork_mud_ice_wind-seed90008 | wind_open | 0.000 | chassis_collision | 86.0 | 21 | True | closed | 1 | rover-fork_mud_ice_wind-seed9000__6hkqbEf |
| inkling | rover-fork_mud_ice_wind-seed90008 | wind_open | 0.000 | chassis_collision | 57.4 | 14 | True | None | 1 | rover-fork_mud_ice_wind-seed9000__7ugfMhk |
| inkling | rover-fork_mud_ice_wind-seed90008 | wind_open | 0.000 | chassis_collision | 50.3 | 13 | True | None | 2 | rover-fork_mud_ice_wind-seed9000__gkN3Y9f |
| inkling | rover-fork_replan-seed90000 | mud_open+crate_open | 0.000 | energy_budget_exhausted | 76.5 | 27 | True | open | 0 | rover-fork_replan-seed90000__VDnVq8B |
| inkling | rover-fork_replan-seed90000 | mud_open+crate_open | 0.000 | rollover | 45.6 | 13 | True | None | 1 | rover-fork_replan-seed90000__dhZZkKQ |
| inkling | rover-fork_replan-seed90000 | mud_open+crate_open | 0.000 | chassis_collision | 33.4 | 14 | True | None | 1 | rover-fork_replan-seed90000__Rc8MJsi |
| inkling | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.000 | chassis_collision | 54.4 | 14 | True | None | 0 | rover-fork_replan-seed90001__ivjqWhN |
| inkling | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.000 | time_budget_exhausted | 102.0 | 22 | True | closed | 0 | rover-fork_replan-seed90001__qsvJzXp |
| inkling | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.000 | time_budget_exhausted | 102.0 | 17 | True | closed | 0 | rover-fork_replan-seed90001__CqHcGzV |
| inkling | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | cargo not inside goal circle | 90.1 | 27 | True | open | 0 | rover-fork_replan-seed90002__6psMUGH |
| inkling | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | time_budget_exhausted | 90.5 | 22 | True | open | 0 | rover-fork_replan-seed90002__uwJRbRp |
| inkling | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | chassis_collision | 34.2 | 9 | True | None | 1 | rover-fork_replan-seed90002__6eNrZvb |
| inkling | rover-fork_replan-seed90005 | ice_open+crate_open | 0.000 | chassis_collision | 42.6 | 13 | True | None | 1 | rover-fork_replan-seed90005__P4XwQBo |
| inkling | rover-fork_replan-seed90005 | ice_open+crate_open | 0.000 | cargo not inside goal circle | 91.9 | 24 | True | open | 0 | rover-fork_replan-seed90005__xPoiR87 |
| inkling | rover-fork_replan-seed90005 | ice_open+crate_open | 0.000 | never adjudicated (agent stopped without finish) | – | 2 | None | None | 0 | rover-fork_replan-seed90005__xr4hyBd |
| inkling | rover-fork_wind_mud-seed90000 | wind_open | 0.673 | delivered | 60.8 | 11 | True | open | 1 | rover-fork_wind_mud-seed90000__YvMqsAV |
| inkling | rover-fork_wind_mud-seed90000 | wind_open | 0.771 | delivered | 39.5 | 19 | True | open | 0 | rover-fork_wind_mud-seed90000__vGfofFP |
| inkling | rover-fork_wind_mud-seed90000 | wind_open | 0.000 | time_budget_exhausted | 64.1 | 13 | True | open | 0 | rover-fork_wind_mud-seed90000__pLJGbnS |
| inkling | rover-fork_wind_mud-seed90001 | wind_open | 0.687 | delivered | 59.2 | 15 | True | open | 0 | rover-fork_wind_mud-seed90001__TKVaVz8 |
| inkling | rover-fork_wind_mud-seed90001 | wind_open | 0.000 | left_drivable_surface | 46.6 | 25 | True | open | 1 | rover-fork_wind_mud-seed90001__dfugwgx |
| inkling | rover-fork_wind_mud-seed90001 | wind_open | 0.675 | delivered | 62.5 | 16 | True | open | 0 | rover-fork_wind_mud-seed90001__8FVhaeE |
| inkling | rover-fork_wind_mud-seed90004 | mud_open | 0.000 | chassis_collision | 65.4 | 12 | True | None | 0 | rover-fork_wind_mud-seed90004__66jkACS |
| inkling | rover-fork_wind_mud-seed90004 | mud_open | 0.000 | rollover | 25.5 | 10 | True | None | 1 | rover-fork_wind_mud-seed90004__ZZMVmYK |
| inkling | rover-fork_wind_mud-seed90004 | mud_open | 0.000 | cargo_dropped | 46.6 | 12 | True | None | 0 | rover-fork_wind_mud-seed90004__tdXxmVQ |
| inkling | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | rollover | 17.6 | 8 | True | None | 1 | rover-fork_wind_mud-seed90005__TAcmPdw |
| inkling | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | rollover | 71.8 | 22 | True | closed | 0 | rover-fork_wind_mud-seed90005__hojqASc |
| inkling | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | rollover | 58.8 | 17 | True | closed | 0 | rover-fork_wind_mud-seed90005__YZzDYcn |
| inkling | rover-serpentine-seed90000 | shortcut_open | 0.710 | delivered | 46.9 | 18 | True | open | 0 | rover-serpentine-seed90000__5r3VgHX |
| inkling | rover-serpentine-seed90000 | shortcut_open | 0.647 | delivered | 79.0 | 18 | False | closed | 0 | rover-serpentine-seed90000__ikTy6LU |
| inkling | rover-serpentine-seed90000 | shortcut_open | 0.000 | chassis_collision | 32.9 | 10 | True | closed | 1 | rover-serpentine-seed90000__cvuUWXJ |
| inkling | rover-serpentine-seed90001 | serpentine_open | 0.000 | time_budget_exhausted | 84.0 | 19 | False | open | 0 | rover-serpentine-seed90001__GLFTV5Z |
| inkling | rover-serpentine-seed90001 | serpentine_open | 0.000 | time_budget_exhausted | 84.0 | 27 | True | open | 1 | rover-serpentine-seed90001__v4gLiFC |
| inkling | rover-serpentine-seed90001 | serpentine_open | 0.000 | chassis_collision | 30.6 | 10 | True | None | 0 | rover-serpentine-seed90001__JbH4jVh |
| inkling | rover-serpentine-seed90002 | shortcut_open | 0.000 | cargo not inside goal circle | 83.4 | 19 | True | closed | 0 | rover-serpentine-seed90002__kTNygqV |
| inkling | rover-serpentine-seed90002 | shortcut_open | 0.000 | chassis_collision | 39.5 | 14 | True | open | 1 | rover-serpentine-seed90002__nxE79TY |
| inkling | rover-serpentine-seed90002 | shortcut_open | 0.000 | chassis_collision | 27.0 | 12 | True | None | 1 | rover-serpentine-seed90002__o6uxWFT |
| inkling | rover-serpentine-seed90003 | serpentine_open | 0.000 | time_budget_exhausted | 84.0 | 13 | True | open | 1 | rover-serpentine-seed90003__T2ZqTxQ |
| inkling | rover-serpentine-seed90003 | serpentine_open | 0.000 | cargo not inside goal circle | 78.8 | 12 | True | closed | 0 | rover-serpentine-seed90003__bho3HGW |
| inkling | rover-serpentine-seed90003 | serpentine_open | 0.000 | time_budget_exhausted | 84.0 | 19 | True | open | 1 | rover-serpentine-seed90003__rwGoetg |
| inkling | winch-barrier-seed90000 | stiff | 0.000 | cable snapped | 31.0 | 31 | True | None | 0 | winch-barrier-seed90000__QrwZi8e |
| inkling | winch-barrier-seed90000 | stiff | 0.000 | time_budget_exhausted | 99.0 | 46 | True | None | 0 | winch-barrier-seed90000__zbxTnAx |
| inkling | winch-barrier-seed90000 | stiff | 0.000 | cable snapped | 42.7 | 39 | True | None | 0 | winch-barrier-seed90000__w9N9iFC |
| inkling | winch-barrier-seed90001 | stiff | 0.000 | cable snapped | 84.2 | 30 | False | None | 0 | winch-barrier-seed90001__RvfrmQR |
| inkling | winch-barrier-seed90001 | stiff | 0.000 | cable snapped | 50.2 | 35 | False | None | 0 | winch-barrier-seed90001__Sj4kHzh |
| inkling | winch-barrier-seed90001 | stiff | 0.000 | cable snapped | 42.4 | 28 | False | None | 0 | winch-barrier-seed90001__nNLjijH |
| inkling | winch-barrier-seed90005 | soft | 0.000 | cable snapped | 13.3 | 17 | True | None | 0 | winch-barrier-seed90005__GHdkTJo |
| inkling | winch-barrier-seed90005 | soft | 0.000 | cable snapped | 18.1 | 13 | False | None | 0 | winch-barrier-seed90005__VsMe5pA |
| inkling | winch-barrier-seed90005 | soft | 0.000 | time_budget_exhausted | 99.0 | 40 | True | None | 0 | winch-barrier-seed90005__9ce8naZ |
| inkling | winch-crowded-seed90000 | stiff | 0.000 | no crate has sat still on the goal, released, for long enough | 101.4 | 77 | None | None | 0 | winch-crowded-seed90000__BJLv8Az |
| inkling | winch-crowded-seed90000 | stiff | 0.869 | delivered | 39.7 | 25 | True | None | 0 | winch-crowded-seed90000__muDFgMK |
| inkling | winch-crowded-seed90000 | stiff | 0.000 | cable snapped | 50.1 | 46 | True | None | 0 | winch-crowded-seed90000__tYq7Cxh |
| inkling | winch-crowded-seed90001 | soft | 0.000 | cable snapped | 49.3 | 44 | True | None | 0 | winch-crowded-seed90001__Uy6gLX6 |
| inkling | winch-crowded-seed90001 | soft | 0.000 | cable snapped | 95.5 | 79 | True | None | 0 | winch-crowded-seed90001__yEJhozR |
| inkling | winch-crowded-seed90001 | soft | 0.767 | delivered | 72.6 | 43 | True | None | 0 | winch-crowded-seed90001__EYoPahy |
| inkling | winch-crowded-seed90006 | stiff | 0.000 | cable snapped | 31.8 | 26 | False | None | 0 | winch-crowded-seed90006__WMJxQiK |
| inkling | winch-crowded-seed90006 | stiff | 0.000 | never adjudicated (agent stopped without finish) | – | 16 | None | None | 0 | winch-crowded-seed90006__qMpwoCB |
| inkling | winch-crowded-seed90006 | stiff | 0.000 | cable snapped | 8.1 | 13 | True | None | 0 | winch-crowded-seed90006__f63BwiU |
| inkling | winch-five_way-seed90000 | soft | 0.000 | cable snapped | 11.2 | 21 | None | None | 0 | winch-five_way-seed90000__bfZzdAf |
| inkling | winch-five_way-seed90000 | soft | 0.000 | cable snapped | 51.6 | 48 | True | None | 0 | winch-five_way-seed90000__j5f4NQE |
| inkling | winch-five_way-seed90000 | soft | 0.000 | cable snapped | 20.3 | 23 | True | None | 0 | winch-five_way-seed90000__Cn8cCAC |
| inkling | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 25.1 | 18 | False | None | 0 | winch-five_way-seed90001__ahCT7Bp |
| inkling | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 56.9 | 48 | False | None | 0 | winch-five_way-seed90001__wewbZc7 |
| inkling | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 12.2 | 20 | False | None | 0 | winch-five_way-seed90001__bYXS4Qj |
| inkling | winch-five_way-seed90003 | stiff | 0.000 | never adjudicated (agent stopped without finish) | – | 11 | None | None | 0 | winch-five_way-seed90003__FPhjn8m |
| inkling | winch-five_way-seed90003 | stiff | 0.000 | cable snapped | 68.9 | 50 | False | None | 0 | winch-five_way-seed90003__myXMC9p |
| inkling | winch-five_way-seed90003 | stiff | 0.000 | cable snapped | 53.3 | 45 | True | None | 0 | winch-five_way-seed90003__JrxDJCg |
| inkling | winch-gain_reference-seed90000 | stiff | 0.000 | cable snapped | 35.7 | 25 | True | None | 0 | winch-gain_reference-seed90000__KxBmnhq |
| inkling | winch-gain_reference-seed90000 | stiff | 0.000 | cable snapped | 39.1 | 32 | False | None | 0 | winch-gain_reference-seed90000__DHo3zs5 |
| inkling | winch-gain_reference-seed90000 | stiff | 0.000 | cable snapped | 42.0 | 29 | False | None | 0 | winch-gain_reference-seed90000__M2NgrtV |
| inkling | winch-gain_reference-seed90001 | stiff | 0.000 | cable snapped | 25.7 | 25 | True | None | 0 | winch-gain_reference-seed90001__DycWK7h |
| inkling | winch-gain_reference-seed90001 | stiff | 0.000 | cable snapped | 47.3 | 41 | True | None | 0 | winch-gain_reference-seed90001__TuPonLb |
| inkling | winch-gain_reference-seed90001 | stiff | 0.000 | cable snapped | 44.7 | 39 | True | None | 0 | winch-gain_reference-seed90001__xgYQW7i |
| inkling | winch-gain_reference-seed90005 | soft | 0.000 | cable snapped | 30.9 | 26 | False | None | 0 | winch-gain_reference-seed90005__5XVrfHn |
| inkling | winch-gain_reference-seed90005 | soft | 0.000 | cable snapped | 39.6 | 18 | False | None | 0 | winch-gain_reference-seed90005__YQ48zpk |
| inkling | winch-gain_reference-seed90005 | soft | 0.661 | delivered | 109.1 | 61 | True | None | 0 | winch-gain_reference-seed90005__WtKiEhq |
| inkling | winch-heaviest-seed90000 | stiff | 0.000 | cable snapped | 33.6 | 26 | False | None | 0 | winch-heaviest-seed90000__UWiTKwk |
| inkling | winch-heaviest-seed90000 | stiff | 0.000 | delivered crate is below the required payload | 86.7 | 64 | True | None | 0 | winch-heaviest-seed90000__rh6fX7e |
| inkling | winch-heaviest-seed90000 | stiff | 0.000 | cable snapped | 118.0 | 48 | False | None | 0 | winch-heaviest-seed90000__a3f82Va |
| inkling | winch-heaviest-seed90001 | stiff | 0.000 | cable snapped | 27.8 | 24 | False | None | 0 | winch-heaviest-seed90001__2cYubkp |
| inkling | winch-heaviest-seed90001 | stiff | 0.000 | cable snapped | 25.9 | 27 | False | None | 0 | winch-heaviest-seed90001__YVYPfaV |
| inkling | winch-heaviest-seed90001 | stiff | 0.000 | cable snapped | 32.5 | 29 | True | None | 0 | winch-heaviest-seed90001__B4JJjC3 |
| inkling | winch-heaviest-seed90005 | soft | 0.000 | cable snapped | 57.8 | 40 | True | None | 0 | winch-heaviest-seed90005__Sctw6nu |
| inkling | winch-heaviest-seed90005 | soft | 0.000 | cable snapped | 17.2 | 18 | False | None | 0 | winch-heaviest-seed90005__vaDYpSz |
| inkling | winch-heaviest-seed90005 | soft | 0.000 | delivered crate is below the required payload | 48.3 | 34 | True | None | 0 | winch-heaviest-seed90005__DZAiKKZ |
| inkling | winch-high_stack-seed90000 | stiff | 0.000 | cable snapped | 50.7 | 36 | False | None | 0 | winch-high_stack-seed90000__NfTpYCZ |
| inkling | winch-high_stack-seed90000 | stiff | 0.000 | cable snapped | 30.1 | 24 | False | None | 0 | winch-high_stack-seed90000__xgMSKrG |
| inkling | winch-high_stack-seed90000 | stiff | 0.000 | cable snapped | 93.9 | 41 | True | None | 0 | winch-high_stack-seed90000__bqfmiK8 |
| inkling | winch-high_stack-seed90001 | stiff | 0.000 | cable snapped | 45.2 | 39 | True | None | 0 | winch-high_stack-seed90001__UkjMo9E |
| inkling | winch-high_stack-seed90001 | stiff | 0.000 | cable snapped | 26.5 | 26 | True | None | 0 | winch-high_stack-seed90001__pCWUNT8 |
| inkling | winch-high_stack-seed90001 | stiff | 0.000 | cable snapped | 43.7 | 26 | True | None | 0 | winch-high_stack-seed90001__ggANDC4 |
| inkling | winch-high_stack-seed90005 | soft | 0.000 | cable snapped | 13.2 | 14 | False | None | 0 | winch-high_stack-seed90005__KNHnbFW |
| inkling | winch-high_stack-seed90005 | soft | 0.000 | cable snapped | 26.2 | 21 | True | None | 0 | winch-high_stack-seed90005__NsM55xB |
| inkling | winch-high_stack-seed90005 | soft | 0.000 | no crate has sat still on the goal, released, for long enough | 97.1 | 46 | False | None | 0 | winch-high_stack-seed90005__A8tGyFR |
| inkling | winch-left_bank-seed90000 | stiff | 0.000 | cable snapped | 32.1 | 28 | True | None | 0 | winch-left_bank-seed90000__7YX9Vy3 |
| inkling | winch-left_bank-seed90000 | stiff | 0.000 | cable snapped | 45.9 | 27 | True | None | 0 | winch-left_bank-seed90000__gPbRxr8 |
| inkling | winch-left_bank-seed90000 | stiff | 0.000 | cable snapped | 33.1 | 33 | False | None | 0 | winch-left_bank-seed90000__QCQgye5 |
| inkling | winch-left_bank-seed90001 | stiff | 0.000 | cable snapped | 44.5 | 33 | True | None | 0 | winch-left_bank-seed90001__zYFWXmE |
| inkling | winch-left_bank-seed90001 | stiff | 0.000 | cable snapped | 39.8 | 30 | True | None | 0 | winch-left_bank-seed90001__wiiH6qG |
| inkling | winch-left_bank-seed90001 | stiff | 0.000 | cable snapped | 45.4 | 35 | False | None | 0 | winch-left_bank-seed90001__JyJqxVP |
| inkling | winch-left_bank-seed90005 | soft | 0.000 | never adjudicated (agent stopped without finish) | – | 38 | True | None | 0 | winch-left_bank-seed90005__7rz8mQe |
| inkling | winch-left_bank-seed90005 | soft | 0.000 | cable snapped | 22.0 | 21 | True | None | 0 | winch-left_bank-seed90005__UxfVB33 |
| inkling | winch-left_bank-seed90005 | soft | 0.000 | cable snapped | 8.9 | 15 | False | None | 0 | winch-left_bank-seed90005__dvngVWV |
| inkling | winch-seed90000 | stiff | 0.763 | delivered | 53.1 | 30 | True | None | 0 | winch-seed90000__e3VRwv6 |
| inkling | winch-seed90000 | stiff | 0.785 | delivered | 41.5 | 30 | True | None | 0 | winch-seed90000__e4SWdFh |
| inkling | winch-seed90000 | stiff | 0.000 | cable snapped | 37.5 | 41 | False | None | 0 | winch-seed90000__tjCvq67 |
| inkling | winch-seed90001 | stiff | 0.000 | cable snapped | 63.8 | 32 | True | None | 0 | winch-seed90001__Uq6KfLB |
| inkling | winch-seed90001 | stiff | 0.000 | delivered crate is below the required payload | 67.7 | 43 | False | None | 0 | winch-seed90001__hADoxty |
| inkling | winch-seed90001 | stiff | 0.000 | cable snapped | 35.8 | 33 | True | None | 0 | winch-seed90001__Hq8v42y |
| inkling | winch-seed90002 | soft | 0.000 | no crate has sat still on the goal, released, for long enough | 76.7 | 55 | None | None | 0 | winch-seed90002__RDdG7Jg |
| inkling | winch-seed90002 | soft | 0.000 | no crate has sat still on the goal, released, for long enough | 76.8 | 36 | False | None | 0 | winch-seed90002__rGegG8f |
| inkling | winch-seed90002 | soft | 0.000 | cable snapped | 33.5 | 30 | False | None | 0 | winch-seed90002__mBqMm9U |
| inkling | winch-short_pair-seed90000 | soft | 0.719 | delivered | 80.3 | 39 | True | None | 0 | winch-short_pair-seed90000__4osktrK |
| inkling | winch-short_pair-seed90000 | soft | 0.000 | cable snapped | 24.4 | 20 | True | None | 0 | winch-short_pair-seed90000__Yt3r39q |
| inkling | winch-short_pair-seed90000 | soft | 0.727 | delivered | 73.6 | 39 | True | None | 0 | winch-short_pair-seed90000__Ly6GhnB |
| inkling | winch-short_pair-seed90001 | soft | 0.000 | cable snapped | 69.3 | 42 | True | None | 0 | winch-short_pair-seed90001__G96Mp78 |
| inkling | winch-short_pair-seed90001 | soft | 0.000 | cable snapped | 60.7 | 32 | True | None | 0 | winch-short_pair-seed90001__vh9L7ev |
| inkling | winch-short_pair-seed90001 | soft | 0.000 | delivered crate is below the required payload | 36.4 | 25 | True | None | 0 | winch-short_pair-seed90001__GPXoBkC |
| inkling | winch-short_pair-seed90003 | stiff | 0.834 | delivered | 42.8 | 29 | True | None | 0 | winch-short_pair-seed90003__7D7Hdso |
| inkling | winch-short_pair-seed90003 | stiff | 0.000 | no crate has sat still on the goal, released, for long enough | 90.5 | 40 | True | None | 0 | winch-short_pair-seed90003__McCWZyp |
| inkling | winch-short_pair-seed90003 | stiff | 0.000 | no crate has sat still on the goal, released, for long enough | 65.8 | 35 | True | None | 0 | winch-short_pair-seed90003__R9J3WLZ |
| inkling | winch-stuck_crate-seed90000 | stiff_stuck | 0.000 | cable snapped | 29.3 | 24 | False | None | 0 | winch-stuck_crate-seed90000__gGEcNfG |
| inkling | winch-stuck_crate-seed90000 | stiff_stuck | 0.000 | cable snapped | 15.2 | 20 | None | None | 0 | winch-stuck_crate-seed90000__yCR5EEN |
| inkling | winch-stuck_crate-seed90000 | stiff_stuck | 0.000 | cable snapped | 46.1 | 29 | True | None | 0 | winch-stuck_crate-seed90000__dRGxifS |
| inkling | winch-stuck_crate-seed90002 | stiff_free | 0.000 | cable snapped | 16.2 | 20 | False | None | 0 | winch-stuck_crate-seed90002__kGyscAy |
| inkling | winch-stuck_crate-seed90002 | stiff_free | 0.000 | cable snapped | 33.6 | 33 | False | None | 0 | winch-stuck_crate-seed90002__sJPqQAP |
| inkling | winch-stuck_crate-seed90002 | stiff_free | 0.806 | delivered | 62.3 | 30 | True | None | 0 | winch-stuck_crate-seed90002__JLZoBoX |
| inkling | winch-stuck_crate-seed90005 | soft_free | 0.000 | time_budget_exhausted | 149.0 | 52 | None | None | 0 | winch-stuck_crate-seed90005__qRPP69A |
| inkling | winch-stuck_crate-seed90005 | soft_free | 0.000 | cable snapped | 13.9 | 17 | False | None | 0 | winch-stuck_crate-seed90005__cBdBcTV |
| inkling | winch-stuck_crate-seed90005 | soft_free | 0.000 | never adjudicated (agent stopped without finish) | – | 38 | False | None | 0 | winch-stuck_crate-seed90005__fAaSEWP |
| inkling | winch-total_payload-seed90000 | stiff | 0.000 | cable snapped | 14.6 | 18 | False | None | 0 | winch-total_payload-seed90000__envGJvP |
| inkling | winch-total_payload-seed90000 | stiff | 0.000 | cable snapped | 64.1 | 33 | True | None | 0 | winch-total_payload-seed90000__vLNrmnY |
| inkling | winch-total_payload-seed90000 | stiff | 0.000 | cable snapped | 86.8 | 57 | True | None | 0 | winch-total_payload-seed90000__Khhzq3v |
| inkling | winch-total_payload-seed90001 | soft | 0.000 | cable snapped | 75.9 | 46 | False | None | 0 | winch-total_payload-seed90001__HiWaCVD |
| inkling | winch-total_payload-seed90001 | soft | 0.000 | cable snapped | 55.5 | 37 | False | None | 0 | winch-total_payload-seed90001__akFwoTF |
| inkling | winch-total_payload-seed90001 | soft | 0.000 | cable snapped | 144.3 | 54 | True | None | 0 | winch-total_payload-seed90001__rvCeNpj |
| inkling | winch-total_payload-seed90006 | stiff | 0.000 | cable snapped | 20.0 | 24 | True | None | 0 | winch-total_payload-seed90006__K9YGYBd |
| inkling | winch-total_payload-seed90006 | stiff | 0.000 | cable snapped | 8.1 | 13 | True | None | 0 | winch-total_payload-seed90006__nTEjd6C |
| inkling | winch-total_payload-seed90006 | stiff | 0.000 | cable snapped | 31.4 | 14 | True | None | 0 | winch-total_payload-seed90006__pt3D9VK |
| inkling | winch-weight_window-seed90000 | stiff | 0.000 | cable snapped | 31.6 | 28 | True | None | 0 | winch-weight_window-seed90000__A42vAQ8 |
| inkling | winch-weight_window-seed90000 | stiff | 0.000 | cable snapped | 32.2 | 28 | True | None | 0 | winch-weight_window-seed90000__CFupYjm |
| inkling | winch-weight_window-seed90000 | stiff | 0.000 | cable snapped | 28.6 | 33 | False | None | 0 | winch-weight_window-seed90000__wohx7g8 |
| inkling | winch-weight_window-seed90001 | stiff | 0.000 | cable snapped | 47.8 | 32 | True | None | 0 | winch-weight_window-seed90001__LAUCByo |
| inkling | winch-weight_window-seed90001 | stiff | 0.000 | cable snapped | 28.6 | 28 | False | None | 0 | winch-weight_window-seed90001__a8T3q4E |
| inkling | winch-weight_window-seed90001 | stiff | 0.000 | cable snapped | 27.4 | 25 | False | None | 0 | winch-weight_window-seed90001__CGkSXdP |
| inkling | winch-weight_window-seed90005 | soft | 0.000 | cable snapped | 13.8 | 14 | False | None | 0 | winch-weight_window-seed90005__br7hVeJ |
| inkling | winch-weight_window-seed90005 | soft | 0.000 | cable snapped | 20.5 | 18 | False | None | 0 | winch-weight_window-seed90005__CWiFMoV |
| inkling | winch-weight_window-seed90005 | soft | 0.744 | delivered | 75.4 | 46 | False | None | 0 | winch-weight_window-seed90005__NLcNJzx |
| inkling | winch-worn_cable-seed90000 | stiff_worn | 0.000 | cable snapped | 8.5 | 14 | True | None | 0 | winch-worn_cable-seed90000__mWS9yKe |
| inkling | winch-worn_cable-seed90000 | stiff_worn | 0.000 | cable snapped | 54.7 | 44 | True | None | 0 | winch-worn_cable-seed90000__rHrxSqE |
| inkling | winch-worn_cable-seed90000 | stiff_worn | 0.000 | cable snapped | 32.6 | 31 | False | None | 0 | winch-worn_cable-seed90000__byLN8UG |
| inkling | winch-worn_cable-seed90001 | soft_intact | 0.000 | cable snapped | 14.9 | 19 | False | None | 0 | winch-worn_cable-seed90001__768M2me |
| inkling | winch-worn_cable-seed90001 | soft_intact | 0.000 | cable snapped | 54.5 | 30 | True | None | 0 | winch-worn_cable-seed90001__mLnQKVJ |
| inkling | winch-worn_cable-seed90001 | soft_intact | 0.000 | delivered crate is below the required payload | 81.8 | 55 | True | None | 0 | winch-worn_cable-seed90001__WMcdgFV |
| inkling | winch-worn_cable-seed90003 | soft_worn | 0.000 | cable snapped | 38.4 | 32 | True | None | 0 | winch-worn_cable-seed90003__Lm7dH9o |
| inkling | winch-worn_cable-seed90003 | soft_worn | 0.000 | cable snapped | 36.8 | 29 | True | None | 0 | winch-worn_cable-seed90003__bWWLnfB |
| inkling | winch-worn_cable-seed90003 | soft_worn | 0.000 | cable snapped | 10.5 | 13 | False | None | 0 | winch-worn_cable-seed90003__z2X9AG6 |
| deepseek | rover-fork_barrier_mud-seed90000 | mud_open | 0.714 | delivered | 41.4 | 17 | True | open | 0 | rover-fork_barrier_mud-seed90000__j3t6x55 |
| deepseek | rover-fork_barrier_mud-seed90000 | mud_open | 0.000 | chassis_collision | 23.9 | 12 | True | None | 1 | rover-fork_barrier_mud-seed90000__oAdUFyM |
| deepseek | rover-fork_barrier_mud-seed90000 | mud_open | 0.750 | delivered | 37.6 | 14 | True | open | 0 | rover-fork_barrier_mud-seed90000__SMY3YNu |
| deepseek | rover-fork_barrier_mud-seed90001 | mud_open | 0.699 | delivered | 44.2 | 13 | True | open | 0 | rover-fork_barrier_mud-seed90001__EP7tcSS |
| deepseek | rover-fork_barrier_mud-seed90001 | mud_open | 0.000 | left_drivable_surface | 18.2 | 9 | True | None | 1 | rover-fork_barrier_mud-seed90001__NaFfAjN |
| deepseek | rover-fork_barrier_mud-seed90001 | mud_open | 0.768 | delivered | 31.9 | 14 | True | open | 0 | rover-fork_barrier_mud-seed90001__HQnEC8L |
| deepseek | rover-fork_barrier_mud-seed90006 | barrier_open | 0.000 | rollover | 43.5 | 17 | True | None | 1 | rover-fork_barrier_mud-seed90006__UDjsT7G |
| deepseek | rover-fork_barrier_mud-seed90006 | barrier_open | 0.651 | delivered | 63.0 | 16 | True | open | 0 | rover-fork_barrier_mud-seed90006__VQWHN6R |
| deepseek | rover-fork_barrier_mud-seed90006 | barrier_open | 0.000 | left_drivable_surface | 54.7 | 15 | True | None | 1 | rover-fork_barrier_mud-seed90006__aSLr5uh |
| deepseek | rover-fork_barrier_mud-seed90010 | barrier_open | 0.699 | delivered | 58.4 | 16 | True | open | 0 | rover-fork_barrier_mud-seed90010__dw5hxuk |
| deepseek | rover-fork_barrier_mud-seed90010 | barrier_open | 0.653 | delivered | 66.8 | 21 | True | open | 0 | rover-fork_barrier_mud-seed90010__dwYYEUZ |
| deepseek | rover-fork_barrier_mud-seed90010 | barrier_open | 0.731 | delivered | 43.1 | 21 | True | open | 0 | rover-fork_barrier_mud-seed90010__k7QTsHN |
| deepseek | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.000 | left_drivable_surface | 19.5 | 13 | True | None | 1 | rover-fork_crate_barrier_mud-see__UBChxxo |
| deepseek | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.712 | delivered | 56.8 | 18 | True | open | 0 | rover-fork_crate_barrier_mud-see__XcQQT9J |
| deepseek | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.598 | delivered | 71.3 | 18 | True | open | 0 | rover-fork_crate_barrier_mud-see__jwnxheT |
| deepseek | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.551 | delivered | 80.6 | 19 | True | open | 0 | rover-fork_crate_barrier_mud-see__5fFERCz |
| deepseek | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.000 | left_drivable_surface | 46.8 | 11 | True | None | 1 | rover-fork_crate_barrier_mud-see__PXuJcUr |
| deepseek | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.671 | delivered | 60.0 | 19 | True | open | 0 | rover-fork_crate_barrier_mud-see__2zyrZKs |
| deepseek | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.000 | chassis_collision | 25.5 | 10 | True | None | 0 | rover-fork_crate_barrier_mud-see__LH3bfmS |
| deepseek | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.000 | cargo_dropped | 35.5 | 10 | True | None | 0 | rover-fork_crate_barrier_mud-see__m3SSRQm |
| deepseek | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.724 | delivered | 56.1 | 20 | True | open | 0 | rover-fork_crate_barrier_mud-see__u2QSxLv |
| deepseek | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.000 | chassis_collision | 26.2 | 14 | True | None | 1 | rover-fork_crate_barrier_mud-see__HUZoUCq |
| deepseek | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.000 | chassis_collision | 22.8 | 11 | True | None | 1 | rover-fork_crate_barrier_mud-see__apTvRT2 |
| deepseek | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.724 | delivered | 50.4 | 21 | True | open | 0 | rover-fork_crate_barrier_mud-see__eHAtmX7 |
| deepseek | rover-fork_crate_ice-seed90000 | crate_open | 0.767 | delivered | 36.1 | 17 | True | open | 0 | rover-fork_crate_ice-seed90000__6LkaWyu |
| deepseek | rover-fork_crate_ice-seed90000 | crate_open | 0.769 | delivered | 36.8 | 16 | True | open | 0 | rover-fork_crate_ice-seed90000__iJj2H8J |
| deepseek | rover-fork_crate_ice-seed90000 | crate_open | 0.701 | delivered | 55.4 | 22 | True | open | 0 | rover-fork_crate_ice-seed90000__hrQdeDy |
| deepseek | rover-fork_crate_ice-seed90001 | crate_open | 0.000 | chassis_collision | 13.2 | 8 | True | None | 1 | rover-fork_crate_ice-seed90001__UYuMJEn |
| deepseek | rover-fork_crate_ice-seed90001 | crate_open | 0.000 | chassis_collision | 23.4 | 14 | True | open | 0 | rover-fork_crate_ice-seed90001__vLbXrc3 |
| deepseek | rover-fork_crate_ice-seed90001 | crate_open | 0.767 | delivered | 37.3 | 20 | True | open | 0 | rover-fork_crate_ice-seed90001__5WWXujZ |
| deepseek | rover-fork_crate_ice-seed90003 | ice_open | 0.645 | delivered | 69.5 | 21 | True | open | 0 | rover-fork_crate_ice-seed90003__9HNLgL6 |
| deepseek | rover-fork_crate_ice-seed90003 | ice_open | 0.697 | delivered | 64.0 | 16 | True | open | 0 | rover-fork_crate_ice-seed90003__UFfYK8E |
| deepseek | rover-fork_crate_ice-seed90003 | ice_open | 0.654 | delivered | 71.5 | 22 | True | open | 0 | rover-fork_crate_ice-seed90003__AQsWcKU |
| deepseek | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | chassis_collision | 49.8 | 14 | True | None | 2 | rover-fork_crate_ice-seed90004__9kjZ6aE |
| deepseek | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | chassis_collision | 67.3 | 20 | True | open | 1 | rover-fork_crate_ice-seed90004__LFd86oo |
| deepseek | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | chassis_collision | 19.7 | 9 | True | None | 1 | rover-fork_crate_ice-seed90004__fTMbQYV |
| deepseek | rover-fork_crate_wind-seed90000 | wind_open | 0.648 | delivered | 69.7 | 18 | True | open | 1 | rover-fork_crate_wind-seed90000__gKxoFvm |
| deepseek | rover-fork_crate_wind-seed90000 | wind_open | 0.000 | left_drivable_surface | 32.1 | 13 | True | None | 1 | rover-fork_crate_wind-seed90000__o7noW8A |
| deepseek | rover-fork_crate_wind-seed90000 | wind_open | 0.652 | delivered | 65.0 | 31 | True | open | 0 | rover-fork_crate_wind-seed90000__WuL8QAA |
| deepseek | rover-fork_crate_wind-seed90001 | wind_open | 0.681 | delivered | 63.4 | 17 | True | open | 0 | rover-fork_crate_wind-seed90001__G2tdB57 |
| deepseek | rover-fork_crate_wind-seed90001 | wind_open | 0.000 | chassis_collision | 36.7 | 12 | True | None | 2 | rover-fork_crate_wind-seed90001__teGnKjV |
| deepseek | rover-fork_crate_wind-seed90001 | wind_open | 0.714 | delivered | 53.7 | 21 | True | open | 0 | rover-fork_crate_wind-seed90001__fz6gwFB |
| deepseek | rover-fork_crate_wind-seed90006 | crate_open | 0.682 | delivered | 53.9 | 26 | True | open | 0 | rover-fork_crate_wind-seed90006__MLSqKFQ |
| deepseek | rover-fork_crate_wind-seed90006 | crate_open | 0.884 | delivered | 13.2 | 5 | False | open | 0 | rover-fork_crate_wind-seed90006__Vwuh4KK |
| deepseek | rover-fork_crate_wind-seed90006 | crate_open | 0.752 | delivered | 41.3 | 22 | True | open | 0 | rover-fork_crate_wind-seed90006__4nbny2e |
| deepseek | rover-fork_crate_wind-seed90008 | crate_open | 0.756 | delivered | 44.4 | 14 | True | open | 0 | rover-fork_crate_wind-seed90008__5QHdexo |
| deepseek | rover-fork_crate_wind-seed90008 | crate_open | 0.744 | delivered | 42.3 | 21 | True | open | 0 | rover-fork_crate_wind-seed90008__EYE8D7j |
| deepseek | rover-fork_crate_wind-seed90008 | crate_open | 0.000 | never adjudicated (agent stopped without finish) | – | 9 | True | None | 1 | rover-fork_crate_wind-seed90008__Yv5QZPq |
| deepseek | rover-fork_mud_ice-seed90000 | ice_open | 0.000 | chassis_collision | 22.4 | 12 | True | None | 1 | rover-fork_mud_ice-seed90000__GXkb54b |
| deepseek | rover-fork_mud_ice-seed90000 | ice_open | 0.705 | delivered | 59.2 | 17 | True | open | 0 | rover-fork_mud_ice-seed90000__tjxmjeq |
| deepseek | rover-fork_mud_ice-seed90000 | ice_open | 0.000 | chassis_collision | 34.1 | 12 | False | closed | 1 | rover-fork_mud_ice-seed90000__29gC6aT |
| deepseek | rover-fork_mud_ice-seed90001 | ice_open | 0.647 | delivered | 72.9 | 17 | True | open | 0 | rover-fork_mud_ice-seed90001__PcSWi9q |
| deepseek | rover-fork_mud_ice-seed90001 | ice_open | 0.663 | delivered | 64.6 | 24 | True | open | 0 | rover-fork_mud_ice-seed90001__jXXeoGz |
| deepseek | rover-fork_mud_ice-seed90001 | ice_open | 0.724 | delivered | 62.4 | 18 | True | open | 0 | rover-fork_mud_ice-seed90001__9kVKPs6 |
| deepseek | rover-fork_mud_ice-seed90002 | mud_open | 0.677 | delivered | 50.2 | 18 | True | open | 0 | rover-fork_mud_ice-seed90002__Fmwd6K8 |
| deepseek | rover-fork_mud_ice-seed90002 | mud_open | 0.724 | delivered | 42.4 | 15 | True | open | 0 | rover-fork_mud_ice-seed90002__i2yej2j |
| deepseek | rover-fork_mud_ice-seed90002 | mud_open | 0.666 | delivered | 52.4 | 16 | True | open | 0 | rover-fork_mud_ice-seed90002__NXfKdKG |
| deepseek | rover-fork_mud_ice-seed90003 | mud_open | 0.000 | rollover | 39.6 | 20 | True | None | 1 | rover-fork_mud_ice-seed90003__6uikCMT |
| deepseek | rover-fork_mud_ice-seed90003 | mud_open | 0.000 | chassis_collision | 14.5 | 11 | True | None | 1 | rover-fork_mud_ice-seed90003__Z7UGLyh |
| deepseek | rover-fork_mud_ice-seed90003 | mud_open | 0.742 | delivered | 34.2 | 10 | True | open | 0 | rover-fork_mud_ice-seed90003__CuStCSZ |
| deepseek | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | cargo_dropped | 44.3 | 14 | True | None | 0 | rover-fork_mud_ice_wind-seed9000__Mwss7Uo |
| deepseek | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | rollover | 60.0 | 19 | True | closed | 0 | rover-fork_mud_ice_wind-seed9000__hPsHPpy |
| deepseek | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | chassis_collision | 12.8 | 9 | True | None | 0 | rover-fork_mud_ice_wind-seed9000__r8meNLu |
| deepseek | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.702 | delivered | 59.4 | 28 | True | open | 0 | rover-fork_mud_ice_wind-seed9000__W5vkMLh |
| deepseek | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.000 | rollover | 18.6 | 10 | False | closed | 0 | rover-fork_mud_ice_wind-seed9000__eqjj2Rh |
| deepseek | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.684 | delivered | 72.1 | 22 | True | open | 0 | rover-fork_mud_ice_wind-seed9000__td5WyqE |
| deepseek | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.732 | delivered | 47.7 | 18 | True | open | 1 | rover-fork_mud_ice_wind-seed9000__LLM2GV4 |
| deepseek | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.821 | delivered | 21.5 | 9 | False | open | 0 | rover-fork_mud_ice_wind-seed9000__b4rg7ZJ |
| deepseek | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.000 | left_drivable_surface | 23.6 | 12 | True | None | 1 | rover-fork_mud_ice_wind-seed9000__eCFSwia |
| deepseek | rover-fork_mud_ice_wind-seed90008 | wind_open | 0.000 | chassis_collision | 59.8 | 17 | True | None | 2 | rover-fork_mud_ice_wind-seed9000__LUWJckK |
| deepseek | rover-fork_mud_ice_wind-seed90008 | wind_open | 0.000 | rollover | 41.9 | 14 | True | None | 1 | rover-fork_mud_ice_wind-seed9000__KxCZk4S |
| deepseek | rover-fork_mud_ice_wind-seed90008 | wind_open | 0.000 | cargo not inside goal circle | 89.3 | 23 | True | closed | 1 | rover-fork_mud_ice_wind-seed9000__2Ey3uJe |
| deepseek | rover-fork_replan-seed90000 | mud_open+crate_open | 0.652 | delivered | 55.4 | 21 | True | open | 0 | rover-fork_replan-seed90000__iVbhfzi |
| deepseek | rover-fork_replan-seed90000 | mud_open+crate_open | 0.744 | delivered | 35.6 | 17 | False | open | 0 | rover-fork_replan-seed90000__qkTCWrM |
| deepseek | rover-fork_replan-seed90000 | mud_open+crate_open | 0.000 | rollover | 26.8 | 11 | True | None | 1 | rover-fork_replan-seed90000__oLjiThp |
| deepseek | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.545 | delivered | 101.5 | 34 | True | open | 0 | rover-fork_replan-seed90001__5dRqWHS |
| deepseek | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.000 | left_drivable_surface | 87.6 | 22 | True | open | 1 | rover-fork_replan-seed90001__r8gx6Lq |
| deepseek | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.539 | delivered | 100.6 | 25 | True | open | 0 | rover-fork_replan-seed90001__XQ2Uo3d |
| deepseek | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | chassis_collision | 79.4 | 19 | True | open | 0 | rover-fork_replan-seed90002__KR5kPZF |
| deepseek | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | chassis_collision | 21.8 | 10 | True | None | 2 | rover-fork_replan-seed90002__jPeP5Dp |
| deepseek | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | chassis_collision | 60.0 | 21 | True | open | 0 | rover-fork_replan-seed90002__hU4LVMR |
| deepseek | rover-fork_replan-seed90005 | ice_open+crate_open | 0.649 | delivered | 71.8 | 24 | True | open | 0 | rover-fork_replan-seed90005__PE9Thr9 |
| deepseek | rover-fork_replan-seed90005 | ice_open+crate_open | 0.664 | delivered | 81.0 | 20 | True | open | 0 | rover-fork_replan-seed90005__XndTEDN |
| deepseek | rover-fork_replan-seed90005 | ice_open+crate_open | 0.693 | delivered | 64.3 | 30 | True | open | 0 | rover-fork_replan-seed90005__9HKuy7J |
| deepseek | rover-fork_wind_mud-seed90000 | wind_open | 0.000 | chassis_collision | 13.5 | 11 | True | None | 1 | rover-fork_wind_mud-seed90000__KZpJieT |
| deepseek | rover-fork_wind_mud-seed90000 | wind_open | 0.685 | delivered | 51.0 | 18 | True | open | 0 | rover-fork_wind_mud-seed90000__vxqtNGL |
| deepseek | rover-fork_wind_mud-seed90000 | wind_open | 0.741 | delivered | 43.4 | 22 | True | open | 0 | rover-fork_wind_mud-seed90000__DFNhgSL |
| deepseek | rover-fork_wind_mud-seed90001 | wind_open | 0.791 | delivered | 35.0 | 19 | True | open | 0 | rover-fork_wind_mud-seed90001__3oHhUiN |
| deepseek | rover-fork_wind_mud-seed90001 | wind_open | 0.000 | left_drivable_surface | 25.5 | 10 | True | None | 1 | rover-fork_wind_mud-seed90001__9wZDK9f |
| deepseek | rover-fork_wind_mud-seed90001 | wind_open | 0.000 | left_drivable_surface | 7.8 | 7 | True | None | 1 | rover-fork_wind_mud-seed90001__Qyx5NqE |
| deepseek | rover-fork_wind_mud-seed90004 | mud_open | 0.659 | delivered | 60.7 | 16 | True | open | 0 | rover-fork_wind_mud-seed90004__sndSa4w |
| deepseek | rover-fork_wind_mud-seed90004 | mud_open | 0.000 | left_drivable_surface | 36.4 | 12 | True | None | 1 | rover-fork_wind_mud-seed90004__xvFKWdH |
| deepseek | rover-fork_wind_mud-seed90004 | mud_open | 0.000 | rollover | 30.9 | 15 | True | None | 1 | rover-fork_wind_mud-seed90004__7n3StjR |
| deepseek | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | rollover | 29.4 | 11 | True | closed | 0 | rover-fork_wind_mud-seed90005__QrZVCcu |
| deepseek | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | chassis_collision | 25.2 | 11 | True | None | 1 | rover-fork_wind_mud-seed90005__wHfGAWz |
| deepseek | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | rollover | 19.1 | 12 | True | closed | 0 | rover-fork_wind_mud-seed90005__SHd2eRf |
| deepseek | rover-serpentine-seed90000 | shortcut_open | 0.851 | delivered | 24.5 | 15 | False | open | 0 | rover-serpentine-seed90000__LvkR4ZN |
| deepseek | rover-serpentine-seed90000 | shortcut_open | 0.842 | delivered | 24.5 | 12 | False | open | 0 | rover-serpentine-seed90000__fBiW43w |
| deepseek | rover-serpentine-seed90000 | shortcut_open | 0.833 | delivered | 22.7 | 12 | False | open | 0 | rover-serpentine-seed90000__Gb55iSH |
| deepseek | rover-serpentine-seed90001 | serpentine_open | 0.624 | delivered | 79.0 | 22 | False | closed | 0 | rover-serpentine-seed90001__hXFv6yZ |
| deepseek | rover-serpentine-seed90001 | serpentine_open | 0.000 | time_budget_exhausted | 84.0 | 14 | False | closed | 0 | rover-serpentine-seed90001__tBX68Pf |
| deepseek | rover-serpentine-seed90001 | serpentine_open | 0.592 | delivered | 76.8 | 19 | True | open | 0 | rover-serpentine-seed90001__o94NUwi |
| deepseek | rover-serpentine-seed90002 | shortcut_open | 0.807 | delivered | 31.1 | 12 | True | open | 0 | rover-serpentine-seed90002__ZW2NjM9 |
| deepseek | rover-serpentine-seed90002 | shortcut_open | 0.795 | delivered | 36.7 | 12 | True | open | 0 | rover-serpentine-seed90002__ifQnVtL |
| deepseek | rover-serpentine-seed90002 | shortcut_open | 0.856 | delivered | 20.0 | 8 | False | open | 0 | rover-serpentine-seed90002__B5B457c |
| deepseek | rover-serpentine-seed90003 | serpentine_open | 0.000 | cargo not inside goal circle | 83.8 | 15 | False | closed | 0 | rover-serpentine-seed90003__LBfhKES |
| deepseek | rover-serpentine-seed90003 | serpentine_open | 0.569 | delivered | 74.9 | 21 | False | closed | 0 | rover-serpentine-seed90003__MWLhetM |
| deepseek | rover-serpentine-seed90003 | serpentine_open | 0.600 | delivered | 67.4 | 17 | True | open | 0 | rover-serpentine-seed90003__vLWo8Mt |
| deepseek | winch-barrier-seed90000 | stiff | 0.772 | delivered | 57.8 | 33 | False | None | 0 | winch-barrier-seed90000__dp8jJJQ |
| deepseek | winch-barrier-seed90000 | stiff | 0.000 | cable snapped | 9.4 | 9 | False | None | 0 | winch-barrier-seed90000__qsbHjkn |
| deepseek | winch-barrier-seed90000 | stiff | 0.798 | delivered | 46.5 | 23 | True | None | 0 | winch-barrier-seed90000__hG6fs5q |
| deepseek | winch-barrier-seed90001 | stiff | 0.819 | delivered | 44.8 | 27 | True | None | 0 | winch-barrier-seed90001__LHhnWUs |
| deepseek | winch-barrier-seed90001 | stiff | 0.817 | delivered | 44.8 | 32 | False | None | 0 | winch-barrier-seed90001__hWhvsje |
| deepseek | winch-barrier-seed90001 | stiff | 0.825 | delivered | 43.1 | 26 | False | None | 0 | winch-barrier-seed90001__Bot3Zv2 |
| deepseek | winch-barrier-seed90005 | soft | 0.801 | delivered | 47.5 | 29 | True | None | 0 | winch-barrier-seed90005__RSrt5rc |
| deepseek | winch-barrier-seed90005 | soft | 0.000 | cable snapped | 16.5 | 14 | False | None | 0 | winch-barrier-seed90005__ZNzzSLV |
| deepseek | winch-barrier-seed90005 | soft | 0.766 | delivered | 62.0 | 38 | False | None | 0 | winch-barrier-seed90005__RMAArZg |
| deepseek | winch-crowded-seed90000 | stiff | 0.000 | delivered crate is below the required payload | 41.6 | 21 | True | None | 0 | winch-crowded-seed90000__DfS9sjK |
| deepseek | winch-crowded-seed90000 | stiff | 0.877 | delivered | 36.2 | 25 | True | None | 0 | winch-crowded-seed90000__fBfhfeR |
| deepseek | winch-crowded-seed90000 | stiff | 0.884 | delivered | 34.5 | 23 | False | None | 0 | winch-crowded-seed90000__Keu8m54 |
| deepseek | winch-crowded-seed90001 | soft | 0.774 | delivered | 66.1 | 34 | True | None | 0 | winch-crowded-seed90001__S2x2LmT |
| deepseek | winch-crowded-seed90001 | soft | 0.000 | cable snapped | 20.9 | 21 | False | None | 0 | winch-crowded-seed90001__qWNw3Xe |
| deepseek | winch-crowded-seed90001 | soft | 0.000 | cable snapped | 27.1 | 21 | False | None | 0 | winch-crowded-seed90001__WNMj3De |
| deepseek | winch-crowded-seed90006 | stiff | 0.823 | delivered | 55.4 | 28 | True | None | 0 | winch-crowded-seed90006__A7n7Vh9 |
| deepseek | winch-crowded-seed90006 | stiff | 0.000 | cable snapped | 11.4 | 14 | True | None | 0 | winch-crowded-seed90006__hKwoEAa |
| deepseek | winch-crowded-seed90006 | stiff | 0.000 | cable snapped | 6.4 | 9 | False | None | 0 | winch-crowded-seed90006__A6tL7jf |
| deepseek | winch-five_way-seed90000 | soft | 0.000 | cable snapped | 12.3 | 10 | False | None | 0 | winch-five_way-seed90000__dJkMbCj |
| deepseek | winch-five_way-seed90000 | soft | 0.000 | cable snapped | 12.3 | 10 | False | None | 0 | winch-five_way-seed90000__mZ32PuM |
| deepseek | winch-five_way-seed90000 | soft | 0.000 | cable snapped | 14.3 | 12 | False | None | 0 | winch-five_way-seed90000__QpfioyQ |
| deepseek | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 13.0 | 10 | True | None | 0 | winch-five_way-seed90001__NkWXUz4 |
| deepseek | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 19.3 | 18 | False | None | 0 | winch-five_way-seed90001__h3S7ABV |
| deepseek | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 15.8 | 12 | False | None | 0 | winch-five_way-seed90001__LyNZSNC |
| deepseek | winch-five_way-seed90003 | stiff | 0.000 | cable snapped | 7.2 | 9 | False | None | 0 | winch-five_way-seed90003__cNuGo5K |
| deepseek | winch-five_way-seed90003 | stiff | 0.000 | cable snapped | 6.4 | 8 | False | None | 0 | winch-five_way-seed90003__sfxVJdm |
| deepseek | winch-five_way-seed90003 | stiff | 0.000 | cable snapped | 7.5 | 12 | False | None | 0 | winch-five_way-seed90003__u3i77nq |
| deepseek | winch-gain_reference-seed90000 | stiff | 0.000 | cable snapped | 11.0 | 9 | True | None | 0 | winch-gain_reference-seed90000__Psmd4sB |
| deepseek | winch-gain_reference-seed90000 | stiff | 0.000 | cable snapped | 41.5 | 34 | False | None | 0 | winch-gain_reference-seed90000__rnbwaNs |
| deepseek | winch-gain_reference-seed90000 | stiff | 0.000 | no crate has sat still on the goal, released, for long enough | 84.0 | 45 | False | None | 0 | winch-gain_reference-seed90000__9DWmUTo |
| deepseek | winch-gain_reference-seed90001 | stiff | 0.809 | delivered | 51.4 | 26 | False | None | 0 | winch-gain_reference-seed90001__a3TZpHa |
| deepseek | winch-gain_reference-seed90001 | stiff | 0.848 | delivered | 42.5 | 24 | True | None | 0 | winch-gain_reference-seed90001__g5opUsG |
| deepseek | winch-gain_reference-seed90001 | stiff | 0.756 | delivered | 73.7 | 37 | True | None | 0 | winch-gain_reference-seed90001__58xdxtL |
| deepseek | winch-gain_reference-seed90005 | soft | 0.000 | never adjudicated (AgentTimeoutError) | – | 41 | True | None | 0 | winch-gain_reference-seed90005__KjGskRg |
| deepseek | winch-gain_reference-seed90005 | soft | 0.000 | cable snapped | 11.9 | 9 | False | None | 0 | winch-gain_reference-seed90005__fgC7EdN |
| deepseek | winch-gain_reference-seed90005 | soft | 0.000 | never adjudicated (AgentTimeoutError) | – | 37 | True | None | 0 | winch-gain_reference-seed90005__9kFF7B3 |
| deepseek | winch-heaviest-seed90000 | stiff | 0.000 | cable snapped | 10.9 | 11 | True | None | 0 | winch-heaviest-seed90000__Lz6R9Bm |
| deepseek | winch-heaviest-seed90000 | stiff | 0.000 | cable snapped | 38.7 | 28 | False | None | 0 | winch-heaviest-seed90000__nUe2VXN |
| deepseek | winch-heaviest-seed90000 | stiff | 0.000 | cable snapped | 40.2 | 28 | False | None | 0 | winch-heaviest-seed90000__G6iyRjH |
| deepseek | winch-heaviest-seed90001 | stiff | 0.000 | cable snapped | 31.0 | 19 | False | None | 0 | winch-heaviest-seed90001__74yHjWk |
| deepseek | winch-heaviest-seed90001 | stiff | 0.000 | cable snapped | 33.2 | 22 | False | None | 0 | winch-heaviest-seed90001__yRbwJ4Q |
| deepseek | winch-heaviest-seed90001 | stiff | 0.000 | delivered crate is below the required payload | 50.9 | 50 | True | None | 0 | winch-heaviest-seed90001__sZufUep |
| deepseek | winch-heaviest-seed90005 | soft | 0.000 | cable snapped | 12.0 | 11 | False | None | 0 | winch-heaviest-seed90005__8ZwvgCB |
| deepseek | winch-heaviest-seed90005 | soft | 0.000 | cable snapped | 13.8 | 12 | False | None | 0 | winch-heaviest-seed90005__KLhSvfS |
| deepseek | winch-heaviest-seed90005 | soft | 0.000 | cable snapped | 40.2 | 28 | False | None | 0 | winch-heaviest-seed90005__nAVZLQ4 |
| deepseek | winch-high_stack-seed90000 | stiff | 0.000 | cable snapped | 9.3 | 10 | False | None | 0 | winch-high_stack-seed90000__VyUKnPy |
| deepseek | winch-high_stack-seed90000 | stiff | 0.000 | delivered crate is below the required payload | 73.4 | 44 | True | None | 0 | winch-high_stack-seed90000__bdm6Zpo |
| deepseek | winch-high_stack-seed90000 | stiff | 0.756 | delivered | 60.6 | 31 | True | None | 0 | winch-high_stack-seed90000__BAACBpG |
| deepseek | winch-high_stack-seed90001 | stiff | 0.855 | delivered | 31.9 | 19 | True | None | 0 | winch-high_stack-seed90001__2BzqGGM |
| deepseek | winch-high_stack-seed90001 | stiff | 0.803 | delivered | 51.2 | 28 | True | None | 0 | winch-high_stack-seed90001__TPy9HKm |
| deepseek | winch-high_stack-seed90001 | stiff | 0.822 | delivered | 43.1 | 23 | False | None | 0 | winch-high_stack-seed90001__UjmDyTC |
| deepseek | winch-high_stack-seed90005 | soft | 0.818 | delivered | 42.6 | 24 | True | None | 0 | winch-high_stack-seed90005__KZL2NCg |
| deepseek | winch-high_stack-seed90005 | soft | 0.804 | delivered | 47.6 | 25 | False | None | 0 | winch-high_stack-seed90005__sik4rBj |
| deepseek | winch-high_stack-seed90005 | soft | 0.777 | delivered | 57.0 | 31 | True | None | 0 | winch-high_stack-seed90005__iqZGuKB |
| deepseek | winch-left_bank-seed90000 | stiff | 0.859 | delivered | 35.1 | 23 | False | None | 0 | winch-left_bank-seed90000__cs4sfdm |
| deepseek | winch-left_bank-seed90000 | stiff | 0.830 | delivered | 45.4 | 24 | True | None | 0 | winch-left_bank-seed90000__ezahaAQ |
| deepseek | winch-left_bank-seed90000 | stiff | 0.000 | cable snapped | 27.7 | 23 | False | None | 0 | winch-left_bank-seed90000__3c8ysF2 |
| deepseek | winch-left_bank-seed90001 | stiff | 0.000 | cable snapped | 20.7 | 19 | True | None | 0 | winch-left_bank-seed90001__AaEoRaz |
| deepseek | winch-left_bank-seed90001 | stiff | 0.000 | cable snapped | 19.3 | 18 | True | None | 0 | winch-left_bank-seed90001__ZGuuXP7 |
| deepseek | winch-left_bank-seed90001 | stiff | 0.000 | cable snapped | 30.2 | 21 | False | None | 0 | winch-left_bank-seed90001__Zwhht6z |
| deepseek | winch-left_bank-seed90005 | soft | 0.780 | delivered | 61.0 | 34 | True | None | 0 | winch-left_bank-seed90005__gHzAJPi |
| deepseek | winch-left_bank-seed90005 | soft | 0.000 | cable snapped | 9.0 | 10 | False | None | 0 | winch-left_bank-seed90005__mhgq2p9 |
| deepseek | winch-left_bank-seed90005 | soft | 0.000 | never adjudicated (AgentTimeoutError) | – | 46 | True | None | 0 | winch-left_bank-seed90005__rya8mw2 |
| deepseek | winch-seed90000 | stiff | 0.797 | delivered | 42.3 | 29 | False | None | 0 | winch-seed90000__CBQkBoW |
| deepseek | winch-seed90000 | stiff | 0.815 | delivered | 37.9 | 24 | False | None | 0 | winch-seed90000__ZJdabXq |
| deepseek | winch-seed90000 | stiff | 0.758 | delivered | 53.6 | 34 | False | None | 0 | winch-seed90000__wH3SeZ9 |
| deepseek | winch-seed90001 | stiff | 0.000 | cable snapped | 9.0 | 12 | True | None | 0 | winch-seed90001__ZPXyf8P |
| deepseek | winch-seed90001 | stiff | 0.000 | cable snapped | 9.0 | 10 | False | None | 0 | winch-seed90001__ejuob8N |
| deepseek | winch-seed90001 | stiff | 0.000 | cable snapped | 26.7 | 20 | False | None | 0 | winch-seed90001__Jwc8UdS |
| deepseek | winch-seed90002 | soft | 0.000 | cable snapped | 9.2 | 9 | False | None | 0 | winch-seed90002__3iRyedm |
| deepseek | winch-seed90002 | soft | 0.778 | delivered | 45.5 | 27 | False | None | 0 | winch-seed90002__SZhESoW |
| deepseek | winch-seed90002 | soft | 0.000 | cable snapped | 8.8 | 14 | False | None | 0 | winch-seed90002__HjspZqa |
| deepseek | winch-short_pair-seed90000 | soft | 0.772 | delivered | 60.0 | 37 | True | None | 0 | winch-short_pair-seed90000__DPJGbdg |
| deepseek | winch-short_pair-seed90000 | soft | 0.714 | delivered | 77.9 | 37 | True | None | 0 | winch-short_pair-seed90000__guTcGuA |
| deepseek | winch-short_pair-seed90000 | soft | 0.742 | delivered | 66.5 | 41 | True | None | 0 | winch-short_pair-seed90000__HyCMJqd |
| deepseek | winch-short_pair-seed90001 | soft | 0.713 | delivered | 78.2 | 46 | True | None | 0 | winch-short_pair-seed90001__2chC952 |
| deepseek | winch-short_pair-seed90001 | soft | 0.000 | never adjudicated (AgentTimeoutError) | – | 33 | True | None | 0 | winch-short_pair-seed90001__CFsLUEK |
| deepseek | winch-short_pair-seed90001 | soft | 0.000 | never adjudicated (AgentTimeoutError) | – | 50 | True | None | 0 | winch-short_pair-seed90001__SMTFRJZ |
| deepseek | winch-short_pair-seed90003 | stiff | 0.818 | delivered | 43.2 | 26 | False | None | 0 | winch-short_pair-seed90003__FmJoZfY |
| deepseek | winch-short_pair-seed90003 | stiff | 0.732 | delivered | 69.6 | 40 | True | None | 0 | winch-short_pair-seed90003__KmkKPuc |
| deepseek | winch-short_pair-seed90003 | stiff | 0.749 | delivered | 69.2 | 34 | False | None | 0 | winch-short_pair-seed90003__uqtfBQx |
| deepseek | winch-stuck_crate-seed90000 | stiff_stuck | 0.000 | cable snapped | 11.4 | 11 | True | None | 0 | winch-stuck_crate-seed90000__WtWb9pM |
| deepseek | winch-stuck_crate-seed90000 | stiff_stuck | 0.000 | cable snapped | 11.5 | 10 | False | None | 0 | winch-stuck_crate-seed90000__znE3Dmt |
| deepseek | winch-stuck_crate-seed90000 | stiff_stuck | 0.000 | cable snapped | 11.5 | 9 | False | None | 0 | winch-stuck_crate-seed90000__Vo6Ud2C |
| deepseek | winch-stuck_crate-seed90002 | stiff_free | 0.000 | cable snapped | 9.3 | 10 | False | None | 0 | winch-stuck_crate-seed90002__W6Tfiu6 |
| deepseek | winch-stuck_crate-seed90002 | stiff_free | 0.000 | cable snapped | 12.4 | 13 | False | None | 0 | winch-stuck_crate-seed90002__qtgFvTz |
| deepseek | winch-stuck_crate-seed90002 | stiff_free | 0.000 | cable snapped | 9.2 | 10 | True | None | 0 | winch-stuck_crate-seed90002__wUhoaUR |
| deepseek | winch-stuck_crate-seed90005 | soft_free | 0.000 | cable snapped | 14.5 | 13 | False | None | 0 | winch-stuck_crate-seed90005__bygVW73 |
| deepseek | winch-stuck_crate-seed90005 | soft_free | 0.000 | cable snapped | 12.9 | 13 | True | None | 0 | winch-stuck_crate-seed90005__unSCZLq |
| deepseek | winch-stuck_crate-seed90005 | soft_free | 0.882 | delivered | 35.7 | 24 | False | None | 0 | winch-stuck_crate-seed90005__CoARctS |
| deepseek | winch-total_payload-seed90000 | stiff | 0.000 | cable snapped | 50.9 | 27 | False | None | 0 | winch-total_payload-seed90000__gSdKfgb |
| deepseek | winch-total_payload-seed90000 | stiff | 0.000 | cable snapped | 43.3 | 25 | False | None | 0 | winch-total_payload-seed90000__gnTVPqw |
| deepseek | winch-total_payload-seed90000 | stiff | 0.000 | cable snapped | 57.0 | 30 | False | None | 0 | winch-total_payload-seed90000__CRX6PCZ |
| deepseek | winch-total_payload-seed90001 | soft | 0.000 | cable snapped | 56.9 | 26 | False | None | 0 | winch-total_payload-seed90001__CNnpn2Z |
| deepseek | winch-total_payload-seed90001 | soft | 0.000 | cable snapped | 49.1 | 31 | True | None | 0 | winch-total_payload-seed90001__LJgVnoy |
| deepseek | winch-total_payload-seed90001 | soft | 0.000 | never adjudicated (AgentTimeoutError) | – | 67 | True | None | 0 | winch-total_payload-seed90001__R6Brpiz |
| deepseek | winch-total_payload-seed90006 | stiff | 0.000 | cable snapped | 7.7 | 9 | False | None | 0 | winch-total_payload-seed90006__X7u9mYN |
| deepseek | winch-total_payload-seed90006 | stiff | 0.000 | cable snapped | 6.5 | 9 | False | None | 0 | winch-total_payload-seed90006__cvZP8Pp |
| deepseek | winch-total_payload-seed90006 | stiff | 0.000 | cable snapped | 8.1 | 13 | True | None | 0 | winch-total_payload-seed90006__TWBysWX |
| deepseek | winch-weight_window-seed90000 | stiff | 0.807 | delivered | 48.3 | 25 | True | None | 0 | winch-weight_window-seed90000__bMgy4fe |
| deepseek | winch-weight_window-seed90000 | stiff | 0.000 | cable snapped | 9.4 | 9 | False | None | 0 | winch-weight_window-seed90000__kdsQdjQ |
| deepseek | winch-weight_window-seed90000 | stiff | 0.000 | cable snapped | 9.4 | 10 | False | None | 0 | winch-weight_window-seed90000__SJuJDJ6 |
| deepseek | winch-weight_window-seed90001 | stiff | 0.000 | cable snapped | 21.8 | 20 | True | None | 0 | winch-weight_window-seed90001__T3QnvGh |
| deepseek | winch-weight_window-seed90001 | stiff | 0.000 | cable snapped | 20.9 | 18 | True | None | 0 | winch-weight_window-seed90001__hrCyeXX |
| deepseek | winch-weight_window-seed90001 | stiff | 0.000 | cable snapped | 27.2 | 18 | False | None | 0 | winch-weight_window-seed90001__Q6qBexZ |
| deepseek | winch-weight_window-seed90005 | soft | 0.706 | delivered | 83.3 | 50 | False | None | 0 | winch-weight_window-seed90005__EGQUh5c |
| deepseek | winch-weight_window-seed90005 | soft | 0.000 | cable snapped | 13.4 | 12 | False | None | 0 | winch-weight_window-seed90005__tpMejs8 |
| deepseek | winch-weight_window-seed90005 | soft | 0.000 | cable snapped | 55.2 | 32 | False | None | 0 | winch-weight_window-seed90005__hzrHipo |
| deepseek | winch-worn_cable-seed90000 | stiff_worn | 0.000 | cable snapped | 6.9 | 10 | False | None | 0 | winch-worn_cable-seed90000__G5UQ4wj |
| deepseek | winch-worn_cable-seed90000 | stiff_worn | 0.000 | cable snapped | 6.9 | 12 | True | None | 0 | winch-worn_cable-seed90000__suNQLFo |
| deepseek | winch-worn_cable-seed90000 | stiff_worn | 0.000 | cable snapped | 6.8 | 9 | False | None | 0 | winch-worn_cable-seed90000__2FjnYaY |
| deepseek | winch-worn_cable-seed90001 | soft_intact | 0.000 | cable snapped | 23.3 | 22 | True | None | 0 | winch-worn_cable-seed90001__ETu6x9r |
| deepseek | winch-worn_cable-seed90001 | soft_intact | 0.000 | delivered crate is below the required payload | 104.1 | 66 | True | None | 0 | winch-worn_cable-seed90001__fMSjKEd |
| deepseek | winch-worn_cable-seed90001 | soft_intact | 0.000 | delivered crate is below the required payload | 119.0 | 64 | True | None | 0 | winch-worn_cable-seed90001__k8okkEG |
| deepseek | winch-worn_cable-seed90003 | soft_worn | 0.000 | cable snapped | 7.7 | 11 | False | None | 0 | winch-worn_cable-seed90003__CpAxotC |
| deepseek | winch-worn_cable-seed90003 | soft_worn | 0.000 | cable snapped | 16.6 | 18 | False | None | 0 | winch-worn_cable-seed90003__tpDtavx |
| deepseek | winch-worn_cable-seed90003 | soft_worn | 0.000 | cable snapped | 29.0 | 14 | True | None | 0 | winch-worn_cable-seed90003__PigyQFD |

