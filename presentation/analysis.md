# Failure analysis for the demo video (interim)

Snapshot taken 2026-11-15 01:31 UTC from completed trials only. Runs are still being added,
so every number below is interim. Run 3 of Inkling (other VM) is not included.

| Source | Job dir | Completed trials used | Left out (infrastructure) |
|---|---|---|---|
| Inkling runs 1–2 | `jobs/eval-inkling-20261115-005608` | 122 (68 rover, 54 winch) | 12 × ApiRateLimitError |
| DeepSeek 4.1 Flash | `jobs/eval-deepseek-20261115-005638` | 55 (35 rover, 20 winch) | 1 × ApiRateLimitError |
| Reference (Harbor oracle) | `jobs/eval-reference-20261114-232444` | 75 | 0 |
| Do-nothing (Harbor nop) | `jobs/eval-do-nothing-20261114-234841` | 74 | 0 (one task missing from the job) |

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
| inkling | 122 | 68 | 54 | {'ApiRateLimitError': 12} |
| deepseek | 55 | 35 | 20 | {'ApiRateLimitError': 1} |


## Headline (interim, completed trials only)

| Model | Env | Trials | Mean reward | Delivery | Reference on same tasks | Mean sim time (s) | Mean env tool calls |
|---|---|---|---|---|---|---|---|
| inkling | rover | 68 | 0.110 | 16% | 0.716 | 62.4 | 16.9 |
| inkling | winch | 54 | 0.030 | 4% | 0.773 | 43.4 | 31.7 |
| inkling | all | 122 | 0.074 | 11% | 0.741 | 54.2 | 23.5 |
| deepseek | rover | 35 | 0.449 | 66% | 0.717 | 48.8 | 17.0 |
| deepseek | winch | 20 | 0.246 | 30% | 0.771 | 26.8 | 18.8 |
| deepseek | all | 55 | 0.375 | 53% | 0.737 | 40.8 | 17.6 |


## Outcome reasons

| Env | Reason | inkling | deepseek |
|---|---|---|---|
| rover | cargo not inside goal circle | 13 | 0 |
| rover | cargo_dropped | 1 | 2 |
| rover | chassis_collision | 21 | 7 |
| rover | delivered | 11 | 23 |
| rover | energy_budget_exhausted | 1 | 0 |
| rover | left_drivable_surface | 3 | 2 |
| rover | rollover | 8 | 1 |
| rover | time_budget_exhausted | 10 | 0 |
| winch | cable snapped | 44 | 13 |
| winch | delivered | 2 | 6 |
| winch | delivered crate is below the required payload | 2 | 1 |
| winch | never adjudicated (agent stopped without finish) | 3 | 0 |
| winch | no crate has sat still on the goal, released, for long enough | 2 | 0 |
| winch | time_budget_exhausted | 1 | 0 |


## Per course / variation (mean reward, delivered/trials)

| Env | Course / variation | inkling | deepseek | Reference |
|---|---|---|---|---|
| rover | fork_barrier_mud | 0.10 (1/7) | 0.51 (3/4) | 0.75 |
| rover | fork_crate_barrier_mud | 0.00 (0/8) | 0.32 (2/4) | 0.69 |
| rover | fork_crate_ice | 0.19 (2/7) | 0.37 (2/4) | 0.71 |
| rover | fork_crate_wind | 0.10 (1/7) | 0.36 (2/4) | 0.71 |
| rover | fork_mud_ice | 0.09 (1/7) | 0.51 (3/4) | 0.74 |
| rover | fork_mud_ice_wind | 0.09 (1/8) | 0.48 (2/3) | 0.72 |
| rover | fork_replan | 0.00 (0/8) | 0.46 (3/4) | 0.69 |
| rover | fork_wind_mud | 0.27 (3/8) | 0.34 (2/4) | 0.78 |
| rover | serpentine | 0.17 (2/8) | 0.71 (4/4) | 0.66 |
| winch | barrier | 0.00 (0/5) | 0.80 (3/3) | 0.80 |
| winch | base | 0.19 (1/4) | 0.00 (0/1) | 0.75 |
| winch | crowded | 0.00 (0/5) | 0.27 (1/3) | 0.82 |
| winch | five_way | 0.00 (0/5) | 0.00 (0/3) | 0.80 |
| winch | gain_reference | 0.00 (0/5) | 0.42 (1/2) | 0.75 |
| winch | heaviest | 0.00 (0/6) | 0.00 (0/3) | 0.74 |
| winch | high_stack | 0.00 (0/6) | 0.43 (1/2) | 0.80 |
| winch | left_bank | 0.00 (0/5) | 0.00 (0/2) | 0.79 |
| winch | short_pair | 0.28 (1/3) | – | 0.77 |
| winch | stuck_crate | 0.00 (0/2) | 0.00 (0/1) | 0.75 |
| winch | total_payload | 0.00 (0/3) | – | 0.72 |
| winch | weight_window | 0.00 (0/2) | – | 0.79 |
| winch | worn_cable | 0.00 (0/3) | – | 0.77 |


## Did the agent test before committing?

| Model | Env | Trials | Tested first | Tested: mean reward / delivered | Committed untested | Untested: mean reward / delivered | Never committed |
|---|---|---|---|---|---|---|---|
| inkling | rover | 68 | 66 (97%) | 0.10 / 10/66 | 2 | 0.32 / 1/2 | 0 |
| inkling | winch | 54 | 28 (52%) | 0.06 / 2/28 | 21 | 0.00 / 0/21 | 5 |
| deepseek | rover | 35 | 32 (91%) | 0.43 / 20/32 | 3 | 0.68 / 3/3 | 0 |
| deepseek | winch | 20 | 9 (45%) | 0.46 / 5/9 | 11 | 0.07 / 1/11 | 0 |


Winch, tension-limited take-up at <= 0.1 m/s before the first carry:

| Model | Winch trials | Slow tension-limited test | Their mean reward | Cable snapped |
|---|---|---|---|---|
| inkling | 54 | 5 | 0.00 | 44 |
| deepseek | 20 | 2 | 0.82 | 13 |


## Failure modes among rover failures (reward 0)

| Model | Rover failures | Reasons | Ended within 45 s of sim time | Mean env calls |
|---|---|---|---|---|
| inkling | 57 | chassis_collision 21, cargo not inside goal circle 13, time_budget_exhausted 10, rollover 8, left_drivable_surface 3, cargo_dropped 1, energy_budget_exhausted 1 | 17 | 16.8 |
| deepseek | 12 | chassis_collision 7, cargo_dropped 2, left_drivable_surface 2, rollover 1 | 11 | 12.1 |


## Rover: lane choice and off-map commands

Lane choice = hazard of the first point on a drive_to path that lies inside a first-fork lane, compared with the hidden open lane. Off-map command = a drive_to whose straight path from the last known position leaves every drivable surface.


| Model | Rover trials | Entered open lane first | Entered closed lane first | Never reached a lane | Mean reward when open lane chosen | Trials with >= 1 off-map drive_to | Crashes whose last drive_to was off-map |
|---|---|---|---|---|---|---|---|
| inkling | 68 | 28 | 17 | 23 | 0.24 | 31 | 24/33 |
| deepseek | 35 | 21 | 2 | 12 | 0.69 | 11 | 10/12 |


Acting on the test: among rover trials that tested first and then entered a lane, how often was it the open lane? Chance = mean of 1 / number of lanes at the first fork.


| Model | Tested, then entered a lane | Entered the open lane | Chance |
|---|---|---|---|
| inkling | 43 | 27 (63%) | 45% |
| deepseek | 20 | 20 (100%) | 47% |


Where rover crashes happened (pose from the first observe after the episode ended):


| Model | Crashes | start pad / road to first fork | lanes | merge / goal approach | unknown |
|---|---|---|---|---|---|
| inkling | 33 | 26 | 5 | 2 | 0 |
| deepseek | 12 | 12 | 0 | 0 | 0 |


Time spent on the start pad (testing and positioning) before the first drive_to off the pad, as a share of the time budget (rover trials that left the pad):


| Model | Trials | Median share on pad | Spent > 40% on pad | Those: mean reward / delivered | Time budget exhausted |
|---|---|---|---|---|---|
| inkling | 64 | 51% | 45 | 0.09 / 6/45 | 10 |
| deepseek | 33 | 29% | 7 | 0.57 / 6/7 | 0 |


## Shell / filesystem use (exploit-seeking or restart attempts)

| Model | Trials with shell/file tool calls | ...before the episode ended | Total such calls | Of those trials, reward > 0 |
|---|---|---|---|---|
| inkling | 59 | 11 | 509 | 2 |
| deepseek | 1 | 1 | 1 | 0 |


## Same task: Inkling 0 vs DeepSeek delivered

| Task | Regime | Inkling outcome | Ink tested | DeepSeek reward | DS tested | Reference | Inkling trial | DeepSeek trial |
|---|---|---|---|---|---|---|---|---|
| rover-fork_barrier_mud-seed90001 | mud_open | time_budget_exhausted | True | 0.699 | True | 0.771 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90001__FgM9WHi | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90001__EP7tcSS |
| rover-fork_barrier_mud-seed90001 | mud_open | rollover | True | 0.699 | True | 0.771 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90001__kwiTpqU | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90001__EP7tcSS |
| rover-fork_barrier_mud-seed90006 | barrier_open | chassis_collision | True | 0.651 | True | 0.744 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90006__7g4vkzo | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90006__VQWHN6R |
| rover-fork_barrier_mud-seed90006 | barrier_open | chassis_collision | True | 0.651 | True | 0.744 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90006__u29xn4Y | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90006__VQWHN6R |
| rover-fork_barrier_mud-seed90010 | barrier_open | cargo not inside goal circle | True | 0.699 | True | 0.745 | jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90010__2SWWafz | jobs/eval-deepseek-20261115-005638/rover-fork_barrier_mud-seed90010__dw5hxuk |
| rover-fork_crate_barrier_mud-seed90001 | mud_open | chassis_collision | True | 0.551 | True | 0.653 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__5cWperh | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__5fFERCz |
| rover-fork_crate_barrier_mud-seed90000 | crate_open | time_budget_exhausted | True | 0.712 | True | 0.718 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__8BQ6z7v | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__XcQQT9J |
| rover-fork_crate_barrier_mud-seed90001 | mud_open | cargo not inside goal circle | True | 0.551 | True | 0.653 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__WnmyBTb | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__5fFERCz |
| rover-fork_crate_barrier_mud-seed90000 | crate_open | chassis_collision | True | 0.712 | True | 0.718 | jobs/eval-inkling-20261115-005608/rover-fork_crate_barrier_mud-see__rLCYx2x | jobs/eval-deepseek-20261115-005638/rover-fork_crate_barrier_mud-see__XcQQT9J |
| rover-fork_crate_ice-seed90000 | crate_open | chassis_collision | True | 0.769 | True | 0.676 | jobs/eval-inkling-20261115-005608/rover-fork_crate_ice-seed90000__XgLtevJ | jobs/eval-deepseek-20261115-005638/rover-fork_crate_ice-seed90000__iJj2H8J |
| rover-fork_crate_ice-seed90003 | ice_open | time_budget_exhausted | True | 0.697 | True | 0.736 | jobs/eval-inkling-20261115-005608/rover-fork_crate_ice-seed90003__3ZGhFay | jobs/eval-deepseek-20261115-005638/rover-fork_crate_ice-seed90003__UFfYK8E |
| rover-fork_crate_ice-seed90003 | ice_open | cargo not inside goal circle | True | 0.697 | True | 0.736 | jobs/eval-inkling-20261115-005608/rover-fork_crate_ice-seed90003__cy5hoyJ | jobs/eval-deepseek-20261115-005638/rover-fork_crate_ice-seed90003__UFfYK8E |
| rover-fork_crate_wind-seed90006 | crate_open | cargo not inside goal circle | True | 0.682 | True | 0.677 | jobs/eval-inkling-20261115-005608/rover-fork_crate_wind-seed90006__9VMe2rq | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90006__MLSqKFQ |
| rover-fork_crate_wind-seed90008 | crate_open | cargo_dropped | True | 0.744 | True | 0.688 | jobs/eval-inkling-20261115-005608/rover-fork_crate_wind-seed90008__L9JhUyo | jobs/eval-deepseek-20261115-005638/rover-fork_crate_wind-seed90008__EYE8D7j |
| rover-fork_mud_ice-seed90000 | ice_open | rollover | True | 0.705 | True | 0.741 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90000__VZreTPB | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90000__tjxmjeq |
| rover-fork_mud_ice-seed90000 | ice_open | rollover | True | 0.705 | True | 0.741 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90000__b4tDc9G | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90000__tjxmjeq |
| rover-fork_mud_ice-seed90002 | mud_open | chassis_collision | True | 0.677 | True | 0.734 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__FzcBPGr | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90002__Fmwd6K8 |
| rover-fork_mud_ice-seed90002 | mud_open | chassis_collision | True | 0.677 | True | 0.734 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__e9TA84d | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90002__Fmwd6K8 |
| rover-fork_mud_ice_wind-seed90004 | mud_open | rollover | True | 0.732 | True | 0.787 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice_wind-seed9000__VzLZKND | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__LLM2GV4 |
| rover-fork_mud_ice_wind-seed90001 | ice_open | cargo not inside goal circle | True | 0.702 | True | 0.703 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice_wind-seed9000__iGPKtYU | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__W5vkMLh |
| rover-fork_mud_ice_wind-seed90001 | ice_open | left_drivable_surface | True | 0.702 | True | 0.703 | jobs/eval-inkling-20261115-005608/rover-fork_mud_ice_wind-seed9000__sjAdZES | jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__W5vkMLh |
| rover-fork_replan-seed90000 | mud_open+crate_open | energy_budget_exhausted | True | 0.652 | True | 0.699 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90000__VDnVq8B | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90000__iVbhfzi |
| rover-fork_replan-seed90000 | mud_open+crate_open | rollover | True | 0.652 | True | 0.699 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90000__dhZZkKQ | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90000__iVbhfzi |
| rover-fork_replan-seed90001 | ice_open+barrier_open | chassis_collision | True | 0.545 | True | 0.691 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90001__ivjqWhN | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90001__5dRqWHS |
| rover-fork_replan-seed90001 | ice_open+barrier_open | time_budget_exhausted | True | 0.545 | True | 0.691 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90001__qsvJzXp | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90001__5dRqWHS |
| rover-fork_replan-seed90005 | ice_open+crate_open | chassis_collision | True | 0.649 | True | 0.704 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90005__P4XwQBo | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90005__PE9Thr9 |
| rover-fork_replan-seed90005 | ice_open+crate_open | cargo not inside goal circle | True | 0.649 | True | 0.704 | jobs/eval-inkling-20261115-005608/rover-fork_replan-seed90005__xPoiR87 | jobs/eval-deepseek-20261115-005638/rover-fork_replan-seed90005__PE9Thr9 |
| rover-fork_wind_mud-seed90004 | mud_open | chassis_collision | True | 0.659 | True | 0.723 | jobs/eval-inkling-20261115-005608/rover-fork_wind_mud-seed90004__66jkACS | jobs/eval-deepseek-20261115-005638/rover-fork_wind_mud-seed90004__sndSa4w |
| rover-fork_wind_mud-seed90004 | mud_open | rollover | True | 0.659 | True | 0.723 | jobs/eval-inkling-20261115-005608/rover-fork_wind_mud-seed90004__ZZMVmYK | jobs/eval-deepseek-20261115-005638/rover-fork_wind_mud-seed90004__sndSa4w |
| rover-serpentine-seed90001 | serpentine_open | time_budget_exhausted | False | 0.624 | False | 0.558 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90001__GLFTV5Z | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90001__hXFv6yZ |
| rover-serpentine-seed90001 | serpentine_open | time_budget_exhausted | True | 0.624 | False | 0.558 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90001__v4gLiFC | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90001__hXFv6yZ |
| rover-serpentine-seed90002 | shortcut_open | cargo not inside goal circle | True | 0.795 | True | 0.767 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90002__kTNygqV | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90002__ifQnVtL |
| rover-serpentine-seed90002 | shortcut_open | chassis_collision | True | 0.795 | True | 0.767 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90002__nxE79TY | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90002__ifQnVtL |
| rover-serpentine-seed90003 | serpentine_open | time_budget_exhausted | True | 0.569 | False | 0.552 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90003__T2ZqTxQ | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90003__MWLhetM |
| rover-serpentine-seed90003 | serpentine_open | cargo not inside goal circle | True | 0.569 | False | 0.552 | jobs/eval-inkling-20261115-005608/rover-serpentine-seed90003__bho3HGW | jobs/eval-deepseek-20261115-005638/rover-serpentine-seed90003__MWLhetM |
| winch-barrier-seed90000 | stiff | cable snapped | True | 0.772 | False | 0.741 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90000__QrwZi8e | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90000__dp8jJJQ |
| winch-barrier-seed90000 | stiff | time_budget_exhausted | True | 0.772 | False | 0.741 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90000__zbxTnAx | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90000__dp8jJJQ |
| winch-barrier-seed90001 | stiff | cable snapped | False | 0.819 | True | 0.826 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90001__RvfrmQR | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90001__LHhnWUs |
| winch-barrier-seed90005 | soft | cable snapped | True | 0.801 | True | 0.820 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__GHdkTJo | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc |
| winch-barrier-seed90005 | soft | cable snapped | False | 0.801 | True | 0.820 | jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__VsMe5pA | jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc |
| winch-crowded-seed90006 | stiff | cable snapped | False | 0.823 | True | 0.843 | jobs/eval-inkling-20261115-005608/winch-crowded-seed90006__WMJxQiK | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90006__A7n7Vh9 |
| winch-crowded-seed90006 | stiff | never adjudicated (agent stopped without finish) | None | 0.823 | True | 0.843 | jobs/eval-inkling-20261115-005608/winch-crowded-seed90006__qMpwoCB | jobs/eval-deepseek-20261115-005638/winch-crowded-seed90006__A7n7Vh9 |
| winch-gain_reference-seed90001 | stiff | cable snapped | True | 0.848 | True | 0.784 | jobs/eval-inkling-20261115-005608/winch-gain_reference-seed90001__DycWK7h | jobs/eval-deepseek-20261115-005638/winch-gain_reference-seed90001__g5opUsG |
| winch-gain_reference-seed90001 | stiff | cable snapped | True | 0.848 | True | 0.784 | jobs/eval-inkling-20261115-005608/winch-gain_reference-seed90001__TuPonLb | jobs/eval-deepseek-20261115-005638/winch-gain_reference-seed90001__g5opUsG |
| winch-high_stack-seed90001 | stiff | cable snapped | True | 0.855 | True | 0.829 | jobs/eval-inkling-20261115-005608/winch-high_stack-seed90001__UkjMo9E | jobs/eval-deepseek-20261115-005638/winch-high_stack-seed90001__2BzqGGM |
| winch-high_stack-seed90001 | stiff | cable snapped | True | 0.855 | True | 0.829 | jobs/eval-inkling-20261115-005608/winch-high_stack-seed90001__pCWUNT8 | jobs/eval-deepseek-20261115-005638/winch-high_stack-seed90001__2BzqGGM |


## All trials

| Model | Task | Regime | Reward | Reason | Sim t | Env calls | Tested | Lane | Off-map cmds | Trial dir |
|---|---|---|---|---|---|---|---|---|---|---|
| inkling | rover-fork_barrier_mud-seed90000 | mud_open | 0.000 | chassis_collision | 27.4 | 14 | True | None | 1 | rover-fork_barrier_mud-seed90000__czNbAnC |
| inkling | rover-fork_barrier_mud-seed90001 | mud_open | 0.000 | time_budget_exhausted | 65.5 | 18 | True | open | 0 | rover-fork_barrier_mud-seed90001__FgM9WHi |
| inkling | rover-fork_barrier_mud-seed90001 | mud_open | 0.000 | rollover | 22.0 | 13 | True | None | 1 | rover-fork_barrier_mud-seed90001__kwiTpqU |
| inkling | rover-fork_barrier_mud-seed90006 | barrier_open | 0.000 | chassis_collision | 14.9 | 10 | True | None | 1 | rover-fork_barrier_mud-seed90006__7g4vkzo |
| inkling | rover-fork_barrier_mud-seed90006 | barrier_open | 0.000 | chassis_collision | 72.3 | 17 | True | open | 1 | rover-fork_barrier_mud-seed90006__u29xn4Y |
| inkling | rover-fork_barrier_mud-seed90010 | barrier_open | 0.000 | cargo not inside goal circle | 77.2 | 17 | True | closed | 0 | rover-fork_barrier_mud-seed90010__2SWWafz |
| inkling | rover-fork_barrier_mud-seed90010 | barrier_open | 0.708 | delivered | 66.3 | 21 | True | open | 0 | rover-fork_barrier_mud-seed90010__TS8SFxZ |
| inkling | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.000 | time_budget_exhausted | 78.1 | 18 | True | open | 0 | rover-fork_crate_barrier_mud-see__8BQ6z7v |
| inkling | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.000 | chassis_collision | 72.2 | 20 | True | open | 0 | rover-fork_crate_barrier_mud-see__rLCYx2x |
| inkling | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.000 | chassis_collision | 80.9 | 20 | True | open | 1 | rover-fork_crate_barrier_mud-see__5cWperh |
| inkling | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.000 | cargo not inside goal circle | 89.7 | 20 | True | closed | 2 | rover-fork_crate_barrier_mud-see__WnmyBTb |
| inkling | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.000 | chassis_collision | 21.0 | 13 | True | None | 0 | rover-fork_crate_barrier_mud-see__Wcbd4pU |
| inkling | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.000 | cargo not inside goal circle | 89.8 | 20 | True | None | 1 | rover-fork_crate_barrier_mud-see__h7XZZoC |
| inkling | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.000 | cargo not inside goal circle | 79.1 | 18 | True | closed | 2 | rover-fork_crate_barrier_mud-see__7oDuUcw |
| inkling | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.000 | chassis_collision | 78.3 | 17 | True | open | 1 | rover-fork_crate_barrier_mud-see__VvA92HD |
| inkling | rover-fork_crate_ice-seed90000 | crate_open | 0.000 | chassis_collision | 29.0 | 12 | True | None | 1 | rover-fork_crate_ice-seed90000__XgLtevJ |
| inkling | rover-fork_crate_ice-seed90000 | crate_open | 0.647 | delivered | 62.6 | 17 | True | open | 0 | rover-fork_crate_ice-seed90000__hi5UVJE |
| inkling | rover-fork_crate_ice-seed90001 | crate_open | 0.648 | delivered | 62.3 | 16 | True | open | 0 | rover-fork_crate_ice-seed90001__BLGZmGP |
| inkling | rover-fork_crate_ice-seed90003 | ice_open | 0.000 | time_budget_exhausted | 76.5 | 20 | True | closed | 0 | rover-fork_crate_ice-seed90003__3ZGhFay |
| inkling | rover-fork_crate_ice-seed90003 | ice_open | 0.000 | cargo not inside goal circle | 76.1 | 22 | True | closed | 0 | rover-fork_crate_ice-seed90003__cy5hoyJ |
| inkling | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | time_budget_exhausted | 78.5 | 19 | True | closed | 0 | rover-fork_crate_ice-seed90004__2xykLDn |
| inkling | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | chassis_collision | 45.6 | 17 | True | open | 1 | rover-fork_crate_ice-seed90004__C6AR8r9 |
| inkling | rover-fork_crate_wind-seed90000 | wind_open | 0.000 | cargo not inside goal circle | 75.0 | 18 | True | None | 0 | rover-fork_crate_wind-seed90000__7DyYNkw |
| inkling | rover-fork_crate_wind-seed90000 | wind_open | 0.000 | cargo not inside goal circle | 74.3 | 20 | True | closed | 0 | rover-fork_crate_wind-seed90000__ktE8Xqm |
| inkling | rover-fork_crate_wind-seed90001 | wind_open | 0.000 | time_budget_exhausted | 77.5 | 19 | True | None | 0 | rover-fork_crate_wind-seed90001__6MZ5RDy |
| inkling | rover-fork_crate_wind-seed90001 | wind_open | 0.000 | chassis_collision | 45.0 | 15 | True | None | 0 | rover-fork_crate_wind-seed90001__JhTc6g7 |
| inkling | rover-fork_crate_wind-seed90006 | crate_open | 0.000 | cargo not inside goal circle | 64.9 | 12 | True | open | 0 | rover-fork_crate_wind-seed90006__9VMe2rq |
| inkling | rover-fork_crate_wind-seed90006 | crate_open | 0.669 | delivered | 47.4 | 20 | True | open | 0 | rover-fork_crate_wind-seed90006__SKyMphV |
| inkling | rover-fork_crate_wind-seed90008 | crate_open | 0.000 | cargo_dropped | 25.2 | 8 | True | None | 0 | rover-fork_crate_wind-seed90008__L9JhUyo |
| inkling | rover-fork_mud_ice-seed90000 | ice_open | 0.000 | rollover | 75.4 | 12 | True | closed | 0 | rover-fork_mud_ice-seed90000__VZreTPB |
| inkling | rover-fork_mud_ice-seed90000 | ice_open | 0.000 | rollover | 35.5 | 12 | True | None | 1 | rover-fork_mud_ice-seed90000__b4tDc9G |
| inkling | rover-fork_mud_ice-seed90001 | ice_open | 0.623 | delivered | 77.1 | 28 | True | open | 0 | rover-fork_mud_ice-seed90001__BSjiC56 |
| inkling | rover-fork_mud_ice-seed90002 | mud_open | 0.000 | chassis_collision | 40.2 | 19 | True | None | 1 | rover-fork_mud_ice-seed90002__FzcBPGr |
| inkling | rover-fork_mud_ice-seed90002 | mud_open | 0.000 | chassis_collision | 39.6 | 14 | True | None | 1 | rover-fork_mud_ice-seed90002__e9TA84d |
| inkling | rover-fork_mud_ice-seed90003 | mud_open | 0.000 | chassis_collision | 41.9 | 13 | True | None | 1 | rover-fork_mud_ice-seed90003__UtrsJvR |
| inkling | rover-fork_mud_ice-seed90003 | mud_open | 0.000 | chassis_collision | 27.0 | 17 | True | None | 1 | rover-fork_mud_ice-seed90003__eLeWVCW |
| inkling | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | left_drivable_surface | 89.1 | 23 | True | open | 1 | rover-fork_mud_ice_wind-seed9000__BeggGDW |
| inkling | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | chassis_collision | 81.0 | 16 | True | closed | 1 | rover-fork_mud_ice_wind-seed9000__dETwrwy |
| inkling | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.000 | cargo not inside goal circle | 86.5 | 14 | True | closed | 0 | rover-fork_mud_ice_wind-seed9000__iGPKtYU |
| inkling | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.000 | left_drivable_surface | 77.8 | 12 | True | closed | 1 | rover-fork_mud_ice_wind-seed9000__sjAdZES |
| inkling | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.000 | rollover | 32.7 | 11 | True | None | 1 | rover-fork_mud_ice_wind-seed9000__VzLZKND |
| inkling | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.703 | delivered | 60.5 | 11 | True | open | 0 | rover-fork_mud_ice_wind-seed9000__t72jb5k |
| inkling | rover-fork_mud_ice_wind-seed90008 | wind_open | 0.000 | chassis_collision | 86.0 | 21 | True | closed | 1 | rover-fork_mud_ice_wind-seed9000__6hkqbEf |
| inkling | rover-fork_mud_ice_wind-seed90008 | wind_open | 0.000 | chassis_collision | 57.4 | 14 | True | None | 1 | rover-fork_mud_ice_wind-seed9000__7ugfMhk |
| inkling | rover-fork_replan-seed90000 | mud_open+crate_open | 0.000 | energy_budget_exhausted | 76.5 | 27 | True | open | 0 | rover-fork_replan-seed90000__VDnVq8B |
| inkling | rover-fork_replan-seed90000 | mud_open+crate_open | 0.000 | rollover | 45.6 | 13 | True | None | 1 | rover-fork_replan-seed90000__dhZZkKQ |
| inkling | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.000 | chassis_collision | 54.4 | 14 | True | None | 0 | rover-fork_replan-seed90001__ivjqWhN |
| inkling | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.000 | time_budget_exhausted | 102.0 | 22 | True | closed | 0 | rover-fork_replan-seed90001__qsvJzXp |
| inkling | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | cargo not inside goal circle | 90.1 | 27 | True | open | 0 | rover-fork_replan-seed90002__6psMUGH |
| inkling | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | time_budget_exhausted | 90.5 | 22 | True | open | 0 | rover-fork_replan-seed90002__uwJRbRp |
| inkling | rover-fork_replan-seed90005 | ice_open+crate_open | 0.000 | chassis_collision | 42.6 | 13 | True | None | 1 | rover-fork_replan-seed90005__P4XwQBo |
| inkling | rover-fork_replan-seed90005 | ice_open+crate_open | 0.000 | cargo not inside goal circle | 91.9 | 24 | True | open | 0 | rover-fork_replan-seed90005__xPoiR87 |
| inkling | rover-fork_wind_mud-seed90000 | wind_open | 0.673 | delivered | 60.8 | 11 | True | open | 1 | rover-fork_wind_mud-seed90000__YvMqsAV |
| inkling | rover-fork_wind_mud-seed90000 | wind_open | 0.771 | delivered | 39.5 | 19 | True | open | 0 | rover-fork_wind_mud-seed90000__vGfofFP |
| inkling | rover-fork_wind_mud-seed90001 | wind_open | 0.687 | delivered | 59.2 | 15 | True | open | 0 | rover-fork_wind_mud-seed90001__TKVaVz8 |
| inkling | rover-fork_wind_mud-seed90001 | wind_open | 0.000 | left_drivable_surface | 46.6 | 25 | True | open | 1 | rover-fork_wind_mud-seed90001__dfugwgx |
| inkling | rover-fork_wind_mud-seed90004 | mud_open | 0.000 | chassis_collision | 65.4 | 12 | True | None | 0 | rover-fork_wind_mud-seed90004__66jkACS |
| inkling | rover-fork_wind_mud-seed90004 | mud_open | 0.000 | rollover | 25.5 | 10 | True | None | 1 | rover-fork_wind_mud-seed90004__ZZMVmYK |
| inkling | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | rollover | 17.6 | 8 | True | None | 1 | rover-fork_wind_mud-seed90005__TAcmPdw |
| inkling | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | rollover | 71.8 | 22 | True | closed | 0 | rover-fork_wind_mud-seed90005__hojqASc |
| inkling | rover-serpentine-seed90000 | shortcut_open | 0.710 | delivered | 46.9 | 18 | True | open | 0 | rover-serpentine-seed90000__5r3VgHX |
| inkling | rover-serpentine-seed90000 | shortcut_open | 0.647 | delivered | 79.0 | 18 | False | closed | 0 | rover-serpentine-seed90000__ikTy6LU |
| inkling | rover-serpentine-seed90001 | serpentine_open | 0.000 | time_budget_exhausted | 84.0 | 19 | False | open | 0 | rover-serpentine-seed90001__GLFTV5Z |
| inkling | rover-serpentine-seed90001 | serpentine_open | 0.000 | time_budget_exhausted | 84.0 | 27 | True | open | 1 | rover-serpentine-seed90001__v4gLiFC |
| inkling | rover-serpentine-seed90002 | shortcut_open | 0.000 | cargo not inside goal circle | 83.4 | 19 | True | closed | 0 | rover-serpentine-seed90002__kTNygqV |
| inkling | rover-serpentine-seed90002 | shortcut_open | 0.000 | chassis_collision | 39.5 | 14 | True | open | 1 | rover-serpentine-seed90002__nxE79TY |
| inkling | rover-serpentine-seed90003 | serpentine_open | 0.000 | time_budget_exhausted | 84.0 | 13 | True | open | 1 | rover-serpentine-seed90003__T2ZqTxQ |
| inkling | rover-serpentine-seed90003 | serpentine_open | 0.000 | cargo not inside goal circle | 78.8 | 12 | True | closed | 0 | rover-serpentine-seed90003__bho3HGW |
| inkling | winch-barrier-seed90000 | stiff | 0.000 | cable snapped | 31.0 | 31 | True | None | 0 | winch-barrier-seed90000__QrwZi8e |
| inkling | winch-barrier-seed90000 | stiff | 0.000 | time_budget_exhausted | 99.0 | 46 | True | None | 0 | winch-barrier-seed90000__zbxTnAx |
| inkling | winch-barrier-seed90001 | stiff | 0.000 | cable snapped | 84.2 | 30 | False | None | 0 | winch-barrier-seed90001__RvfrmQR |
| inkling | winch-barrier-seed90005 | soft | 0.000 | cable snapped | 13.3 | 17 | True | None | 0 | winch-barrier-seed90005__GHdkTJo |
| inkling | winch-barrier-seed90005 | soft | 0.000 | cable snapped | 18.1 | 13 | False | None | 0 | winch-barrier-seed90005__VsMe5pA |
| inkling | winch-crowded-seed90000 | stiff | 0.000 | no crate has sat still on the goal, released, for long enough | 101.4 | 77 | None | None | 0 | winch-crowded-seed90000__BJLv8Az |
| inkling | winch-crowded-seed90001 | soft | 0.000 | cable snapped | 49.3 | 44 | True | None | 0 | winch-crowded-seed90001__Uy6gLX6 |
| inkling | winch-crowded-seed90001 | soft | 0.000 | cable snapped | 95.5 | 79 | True | None | 0 | winch-crowded-seed90001__yEJhozR |
| inkling | winch-crowded-seed90006 | stiff | 0.000 | cable snapped | 31.8 | 26 | False | None | 0 | winch-crowded-seed90006__WMJxQiK |
| inkling | winch-crowded-seed90006 | stiff | 0.000 | never adjudicated (agent stopped without finish) | – | 16 | None | None | 0 | winch-crowded-seed90006__qMpwoCB |
| inkling | winch-five_way-seed90000 | soft | 0.000 | cable snapped | 11.2 | 21 | None | None | 0 | winch-five_way-seed90000__bfZzdAf |
| inkling | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 25.1 | 18 | False | None | 0 | winch-five_way-seed90001__ahCT7Bp |
| inkling | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 56.9 | 48 | False | None | 0 | winch-five_way-seed90001__wewbZc7 |
| inkling | winch-five_way-seed90003 | stiff | 0.000 | never adjudicated (agent stopped without finish) | – | 11 | None | None | 0 | winch-five_way-seed90003__FPhjn8m |
| inkling | winch-five_way-seed90003 | stiff | 0.000 | cable snapped | 68.9 | 50 | False | None | 0 | winch-five_way-seed90003__myXMC9p |
| inkling | winch-gain_reference-seed90000 | stiff | 0.000 | cable snapped | 35.7 | 25 | True | None | 0 | winch-gain_reference-seed90000__KxBmnhq |
| inkling | winch-gain_reference-seed90001 | stiff | 0.000 | cable snapped | 25.7 | 25 | True | None | 0 | winch-gain_reference-seed90001__DycWK7h |
| inkling | winch-gain_reference-seed90001 | stiff | 0.000 | cable snapped | 47.3 | 41 | True | None | 0 | winch-gain_reference-seed90001__TuPonLb |
| inkling | winch-gain_reference-seed90005 | soft | 0.000 | cable snapped | 30.9 | 26 | False | None | 0 | winch-gain_reference-seed90005__5XVrfHn |
| inkling | winch-gain_reference-seed90005 | soft | 0.000 | cable snapped | 39.6 | 18 | False | None | 0 | winch-gain_reference-seed90005__YQ48zpk |
| inkling | winch-heaviest-seed90000 | stiff | 0.000 | cable snapped | 33.6 | 26 | False | None | 0 | winch-heaviest-seed90000__UWiTKwk |
| inkling | winch-heaviest-seed90000 | stiff | 0.000 | delivered crate is below the required payload | 86.7 | 64 | True | None | 0 | winch-heaviest-seed90000__rh6fX7e |
| inkling | winch-heaviest-seed90001 | stiff | 0.000 | cable snapped | 27.8 | 24 | False | None | 0 | winch-heaviest-seed90001__2cYubkp |
| inkling | winch-heaviest-seed90001 | stiff | 0.000 | cable snapped | 25.9 | 27 | False | None | 0 | winch-heaviest-seed90001__YVYPfaV |
| inkling | winch-heaviest-seed90005 | soft | 0.000 | cable snapped | 57.8 | 40 | True | None | 0 | winch-heaviest-seed90005__Sctw6nu |
| inkling | winch-heaviest-seed90005 | soft | 0.000 | cable snapped | 17.2 | 18 | False | None | 0 | winch-heaviest-seed90005__vaDYpSz |
| inkling | winch-high_stack-seed90000 | stiff | 0.000 | cable snapped | 50.7 | 36 | False | None | 0 | winch-high_stack-seed90000__NfTpYCZ |
| inkling | winch-high_stack-seed90000 | stiff | 0.000 | cable snapped | 30.1 | 24 | False | None | 0 | winch-high_stack-seed90000__xgMSKrG |
| inkling | winch-high_stack-seed90001 | stiff | 0.000 | cable snapped | 45.2 | 39 | True | None | 0 | winch-high_stack-seed90001__UkjMo9E |
| inkling | winch-high_stack-seed90001 | stiff | 0.000 | cable snapped | 26.5 | 26 | True | None | 0 | winch-high_stack-seed90001__pCWUNT8 |
| inkling | winch-high_stack-seed90005 | soft | 0.000 | cable snapped | 13.2 | 14 | False | None | 0 | winch-high_stack-seed90005__KNHnbFW |
| inkling | winch-high_stack-seed90005 | soft | 0.000 | cable snapped | 26.2 | 21 | True | None | 0 | winch-high_stack-seed90005__NsM55xB |
| inkling | winch-left_bank-seed90000 | stiff | 0.000 | cable snapped | 32.1 | 28 | True | None | 0 | winch-left_bank-seed90000__7YX9Vy3 |
| inkling | winch-left_bank-seed90000 | stiff | 0.000 | cable snapped | 45.9 | 27 | True | None | 0 | winch-left_bank-seed90000__gPbRxr8 |
| inkling | winch-left_bank-seed90001 | stiff | 0.000 | cable snapped | 44.5 | 33 | True | None | 0 | winch-left_bank-seed90001__zYFWXmE |
| inkling | winch-left_bank-seed90005 | soft | 0.000 | never adjudicated (agent stopped without finish) | – | 38 | True | None | 0 | winch-left_bank-seed90005__7rz8mQe |
| inkling | winch-left_bank-seed90005 | soft | 0.000 | cable snapped | 22.0 | 21 | True | None | 0 | winch-left_bank-seed90005__UxfVB33 |
| inkling | winch-seed90000 | stiff | 0.763 | delivered | 53.1 | 30 | True | None | 0 | winch-seed90000__e3VRwv6 |
| inkling | winch-seed90001 | stiff | 0.000 | cable snapped | 63.8 | 32 | True | None | 0 | winch-seed90001__Uq6KfLB |
| inkling | winch-seed90001 | stiff | 0.000 | delivered crate is below the required payload | 67.7 | 43 | False | None | 0 | winch-seed90001__hADoxty |
| inkling | winch-seed90002 | soft | 0.000 | no crate has sat still on the goal, released, for long enough | 76.7 | 55 | None | None | 0 | winch-seed90002__RDdG7Jg |
| inkling | winch-short_pair-seed90000 | soft | 0.000 | cable snapped | 24.4 | 20 | True | None | 0 | winch-short_pair-seed90000__Yt3r39q |
| inkling | winch-short_pair-seed90001 | soft | 0.000 | cable snapped | 69.3 | 42 | True | None | 0 | winch-short_pair-seed90001__G96Mp78 |
| inkling | winch-short_pair-seed90003 | stiff | 0.834 | delivered | 42.8 | 29 | True | None | 0 | winch-short_pair-seed90003__7D7Hdso |
| inkling | winch-stuck_crate-seed90000 | stiff_stuck | 0.000 | cable snapped | 29.3 | 24 | False | None | 0 | winch-stuck_crate-seed90000__gGEcNfG |
| inkling | winch-stuck_crate-seed90002 | stiff_free | 0.000 | cable snapped | 16.2 | 20 | False | None | 0 | winch-stuck_crate-seed90002__kGyscAy |
| inkling | winch-total_payload-seed90000 | stiff | 0.000 | cable snapped | 14.6 | 18 | False | None | 0 | winch-total_payload-seed90000__envGJvP |
| inkling | winch-total_payload-seed90001 | soft | 0.000 | cable snapped | 75.9 | 46 | False | None | 0 | winch-total_payload-seed90001__HiWaCVD |
| inkling | winch-total_payload-seed90006 | stiff | 0.000 | cable snapped | 20.0 | 24 | True | None | 0 | winch-total_payload-seed90006__K9YGYBd |
| inkling | winch-weight_window-seed90000 | stiff | 0.000 | cable snapped | 32.2 | 28 | True | None | 0 | winch-weight_window-seed90000__CFupYjm |
| inkling | winch-weight_window-seed90001 | stiff | 0.000 | cable snapped | 28.6 | 28 | False | None | 0 | winch-weight_window-seed90001__a8T3q4E |
| inkling | winch-worn_cable-seed90000 | stiff_worn | 0.000 | cable snapped | 54.7 | 44 | True | None | 0 | winch-worn_cable-seed90000__rHrxSqE |
| inkling | winch-worn_cable-seed90001 | soft_intact | 0.000 | cable snapped | 54.5 | 30 | True | None | 0 | winch-worn_cable-seed90001__mLnQKVJ |
| inkling | winch-worn_cable-seed90003 | soft_worn | 0.000 | cable snapped | 38.4 | 32 | True | None | 0 | winch-worn_cable-seed90003__Lm7dH9o |
| deepseek | rover-fork_barrier_mud-seed90000 | mud_open | 0.000 | chassis_collision | 23.9 | 12 | True | None | 1 | rover-fork_barrier_mud-seed90000__oAdUFyM |
| deepseek | rover-fork_barrier_mud-seed90001 | mud_open | 0.699 | delivered | 44.2 | 13 | True | open | 0 | rover-fork_barrier_mud-seed90001__EP7tcSS |
| deepseek | rover-fork_barrier_mud-seed90006 | barrier_open | 0.651 | delivered | 63.0 | 16 | True | open | 0 | rover-fork_barrier_mud-seed90006__VQWHN6R |
| deepseek | rover-fork_barrier_mud-seed90010 | barrier_open | 0.699 | delivered | 58.4 | 16 | True | open | 0 | rover-fork_barrier_mud-seed90010__dw5hxuk |
| deepseek | rover-fork_crate_barrier_mud-seed90000 | crate_open | 0.712 | delivered | 56.8 | 18 | True | open | 0 | rover-fork_crate_barrier_mud-see__XcQQT9J |
| deepseek | rover-fork_crate_barrier_mud-seed90001 | mud_open | 0.551 | delivered | 80.6 | 19 | True | open | 0 | rover-fork_crate_barrier_mud-see__5fFERCz |
| deepseek | rover-fork_crate_barrier_mud-seed90003 | barrier_open | 0.000 | cargo_dropped | 35.5 | 10 | True | None | 0 | rover-fork_crate_barrier_mud-see__m3SSRQm |
| deepseek | rover-fork_crate_barrier_mud-seed90015 | crate_open | 0.000 | chassis_collision | 22.8 | 11 | True | None | 1 | rover-fork_crate_barrier_mud-see__apTvRT2 |
| deepseek | rover-fork_crate_ice-seed90000 | crate_open | 0.769 | delivered | 36.8 | 16 | True | open | 0 | rover-fork_crate_ice-seed90000__iJj2H8J |
| deepseek | rover-fork_crate_ice-seed90001 | crate_open | 0.000 | chassis_collision | 13.2 | 8 | True | None | 1 | rover-fork_crate_ice-seed90001__UYuMJEn |
| deepseek | rover-fork_crate_ice-seed90003 | ice_open | 0.697 | delivered | 64.0 | 16 | True | open | 0 | rover-fork_crate_ice-seed90003__UFfYK8E |
| deepseek | rover-fork_crate_ice-seed90004 | ice_open | 0.000 | chassis_collision | 49.8 | 14 | True | None | 2 | rover-fork_crate_ice-seed90004__9kjZ6aE |
| deepseek | rover-fork_crate_wind-seed90000 | wind_open | 0.000 | left_drivable_surface | 32.1 | 13 | True | None | 1 | rover-fork_crate_wind-seed90000__o7noW8A |
| deepseek | rover-fork_crate_wind-seed90001 | wind_open | 0.000 | chassis_collision | 36.7 | 12 | True | None | 2 | rover-fork_crate_wind-seed90001__teGnKjV |
| deepseek | rover-fork_crate_wind-seed90006 | crate_open | 0.682 | delivered | 53.9 | 26 | True | open | 0 | rover-fork_crate_wind-seed90006__MLSqKFQ |
| deepseek | rover-fork_crate_wind-seed90008 | crate_open | 0.744 | delivered | 42.3 | 21 | True | open | 0 | rover-fork_crate_wind-seed90008__EYE8D7j |
| deepseek | rover-fork_mud_ice-seed90000 | ice_open | 0.705 | delivered | 59.2 | 17 | True | open | 0 | rover-fork_mud_ice-seed90000__tjxmjeq |
| deepseek | rover-fork_mud_ice-seed90001 | ice_open | 0.663 | delivered | 64.6 | 24 | True | open | 0 | rover-fork_mud_ice-seed90001__jXXeoGz |
| deepseek | rover-fork_mud_ice-seed90002 | mud_open | 0.677 | delivered | 50.2 | 18 | True | open | 0 | rover-fork_mud_ice-seed90002__Fmwd6K8 |
| deepseek | rover-fork_mud_ice-seed90003 | mud_open | 0.000 | rollover | 39.6 | 20 | True | None | 1 | rover-fork_mud_ice-seed90003__6uikCMT |
| deepseek | rover-fork_mud_ice_wind-seed90000 | ice_open | 0.000 | cargo_dropped | 44.3 | 14 | True | None | 0 | rover-fork_mud_ice_wind-seed9000__Mwss7Uo |
| deepseek | rover-fork_mud_ice_wind-seed90001 | ice_open | 0.702 | delivered | 59.4 | 28 | True | open | 0 | rover-fork_mud_ice_wind-seed9000__W5vkMLh |
| deepseek | rover-fork_mud_ice_wind-seed90004 | mud_open | 0.732 | delivered | 47.7 | 18 | True | open | 1 | rover-fork_mud_ice_wind-seed9000__LLM2GV4 |
| deepseek | rover-fork_replan-seed90000 | mud_open+crate_open | 0.652 | delivered | 55.4 | 21 | True | open | 0 | rover-fork_replan-seed90000__iVbhfzi |
| deepseek | rover-fork_replan-seed90001 | ice_open+barrier_open | 0.545 | delivered | 101.5 | 34 | True | open | 0 | rover-fork_replan-seed90001__5dRqWHS |
| deepseek | rover-fork_replan-seed90002 | mud_open+barrier_open | 0.000 | chassis_collision | 21.8 | 10 | True | None | 2 | rover-fork_replan-seed90002__jPeP5Dp |
| deepseek | rover-fork_replan-seed90005 | ice_open+crate_open | 0.649 | delivered | 71.8 | 24 | True | open | 0 | rover-fork_replan-seed90005__PE9Thr9 |
| deepseek | rover-fork_wind_mud-seed90000 | wind_open | 0.685 | delivered | 51.0 | 18 | True | open | 0 | rover-fork_wind_mud-seed90000__vxqtNGL |
| deepseek | rover-fork_wind_mud-seed90001 | wind_open | 0.000 | left_drivable_surface | 25.5 | 10 | True | None | 1 | rover-fork_wind_mud-seed90001__9wZDK9f |
| deepseek | rover-fork_wind_mud-seed90004 | mud_open | 0.659 | delivered | 60.7 | 16 | True | open | 0 | rover-fork_wind_mud-seed90004__sndSa4w |
| deepseek | rover-fork_wind_mud-seed90005 | mud_open | 0.000 | chassis_collision | 25.2 | 11 | True | None | 1 | rover-fork_wind_mud-seed90005__wHfGAWz |
| deepseek | rover-serpentine-seed90000 | shortcut_open | 0.851 | delivered | 24.5 | 15 | False | open | 0 | rover-serpentine-seed90000__LvkR4ZN |
| deepseek | rover-serpentine-seed90001 | serpentine_open | 0.624 | delivered | 79.0 | 22 | False | closed | 0 | rover-serpentine-seed90001__hXFv6yZ |
| deepseek | rover-serpentine-seed90002 | shortcut_open | 0.795 | delivered | 36.7 | 12 | True | open | 0 | rover-serpentine-seed90002__ifQnVtL |
| deepseek | rover-serpentine-seed90003 | serpentine_open | 0.569 | delivered | 74.9 | 21 | False | closed | 0 | rover-serpentine-seed90003__MWLhetM |
| deepseek | winch-barrier-seed90000 | stiff | 0.772 | delivered | 57.8 | 33 | False | None | 0 | winch-barrier-seed90000__dp8jJJQ |
| deepseek | winch-barrier-seed90001 | stiff | 0.819 | delivered | 44.8 | 27 | True | None | 0 | winch-barrier-seed90001__LHhnWUs |
| deepseek | winch-barrier-seed90005 | soft | 0.801 | delivered | 47.5 | 29 | True | None | 0 | winch-barrier-seed90005__RSrt5rc |
| deepseek | winch-crowded-seed90000 | stiff | 0.000 | delivered crate is below the required payload | 41.6 | 21 | True | None | 0 | winch-crowded-seed90000__DfS9sjK |
| deepseek | winch-crowded-seed90001 | soft | 0.000 | cable snapped | 20.9 | 21 | False | None | 0 | winch-crowded-seed90001__qWNw3Xe |
| deepseek | winch-crowded-seed90006 | stiff | 0.823 | delivered | 55.4 | 28 | True | None | 0 | winch-crowded-seed90006__A7n7Vh9 |
| deepseek | winch-five_way-seed90000 | soft | 0.000 | cable snapped | 12.3 | 10 | False | None | 0 | winch-five_way-seed90000__dJkMbCj |
| deepseek | winch-five_way-seed90001 | soft | 0.000 | cable snapped | 19.3 | 18 | False | None | 0 | winch-five_way-seed90001__h3S7ABV |
| deepseek | winch-five_way-seed90003 | stiff | 0.000 | cable snapped | 7.2 | 9 | False | None | 0 | winch-five_way-seed90003__cNuGo5K |
| deepseek | winch-gain_reference-seed90000 | stiff | 0.000 | cable snapped | 41.5 | 34 | False | None | 0 | winch-gain_reference-seed90000__rnbwaNs |
| deepseek | winch-gain_reference-seed90001 | stiff | 0.848 | delivered | 42.5 | 24 | True | None | 0 | winch-gain_reference-seed90001__g5opUsG |
| deepseek | winch-heaviest-seed90000 | stiff | 0.000 | cable snapped | 10.9 | 11 | True | None | 0 | winch-heaviest-seed90000__Lz6R9Bm |
| deepseek | winch-heaviest-seed90001 | stiff | 0.000 | cable snapped | 31.0 | 19 | False | None | 0 | winch-heaviest-seed90001__74yHjWk |
| deepseek | winch-heaviest-seed90005 | soft | 0.000 | cable snapped | 12.0 | 11 | False | None | 0 | winch-heaviest-seed90005__8ZwvgCB |
| deepseek | winch-high_stack-seed90000 | stiff | 0.000 | cable snapped | 9.3 | 10 | False | None | 0 | winch-high_stack-seed90000__VyUKnPy |
| deepseek | winch-high_stack-seed90001 | stiff | 0.855 | delivered | 31.9 | 19 | True | None | 0 | winch-high_stack-seed90001__2BzqGGM |
| deepseek | winch-left_bank-seed90001 | stiff | 0.000 | cable snapped | 20.7 | 19 | True | None | 0 | winch-left_bank-seed90001__AaEoRaz |
| deepseek | winch-left_bank-seed90005 | soft | 0.000 | cable snapped | 9.0 | 10 | False | None | 0 | winch-left_bank-seed90005__mhgq2p9 |
| deepseek | winch-seed90001 | stiff | 0.000 | cable snapped | 9.0 | 12 | True | None | 0 | winch-seed90001__ZPXyf8P |
| deepseek | winch-stuck_crate-seed90000 | stiff_stuck | 0.000 | cable snapped | 11.5 | 10 | False | None | 0 | winch-stuck_crate-seed90000__znE3Dmt |

