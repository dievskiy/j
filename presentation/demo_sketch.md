# Demo video sketch: 2 minutes

Working title: **"Test, then act": where frontier agents break on unfamiliar machines**

- Length: about 120 s, 8 scenes. Narration is about 290 words at about 2.5 words per
  second, so it suits a human voice or ElevenLabs.
- Final numbers are placeholders like `[INKLING_MEAN ± SPREAD]`. Interim values are in
  brackets as "(interim: ...)" and come from completed trials on 2026-11-15 at 01:31 UTC
  (see `presentation/analysis.md`). Regenerate them with the commands in that file once
  all three runs finish.
- Rubric map: the gap → scene 5. Meaningful difficulty → scenes 6a and 6b. Reward
  integrity → scenes 4 and 7. Craft and reproduction → scenes 4 and 7.
- Visual style: dark background and one accent colour per policy. Use these colours in
  every scene: Reference = green, DeepSeek = blue, Inkling = orange, baselines = grey.

---

## Scene 1: Hook (0:00–0:09, 9 s)

**Title on screen:** *Frontier agents can solve hard problems. Can they test before they act?*

**On-screen content**
- Full-bleed b-roll: the rover rolling over, slowed down. TODO: render it from Inkling
  trial A (see Assets).
- Lower third, last 3 s: "Inkling · fork_mud_ice · reward 0 · rollover at 75 s"

**Narration (~27 words)**
> Frontier models do well on benchmarks. Put one in charge of a machine it has never
> seen, where it must test before it acts, and it fails.

**Assets**
- TODO: video of `jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90000__VZreTPB`.
  The eval trials have no video. To make one, copy the trial dir into an empty scratch
  dir and run `.venv/bin/python harbor_tasks/replay_video.py <scratch dir>`. Don't point
  it at the full job dir: it would try every trial there, and the replay supports rover
  only.

---

## Scene 2: The challenge (0:09–0:31, 22 s)

**Title:** *Same map. Hidden physics. A cheap test. A fixed budget.*

**On-screen content: two panels side by side. Build them as simple vector schematics.**

Left panel: **Rover**, top-down. Draw boxes for surfaces. The pad is grey, roads are
dark grey, the mud strip is brown, the ice strip is light blue and the lookout is a
ring.

```
   START PAD (safe test area)                      three lanes, ONE passable
  +------------------------------+          north: ICE  ==================+
  | (o) lookout                  |         /                               \
  |        [ice sample]          |  road  /   mid: MUD  ==================== \  merge -> ( GOAL )
  |  rover>        [crate sample]|=======<                                   >======
  |        [mud sample]          |  fork  \   south: hidden WALL? ========== /
  +------------------------------+         \________________________________/
   cheap tests: drive onto a sample strip · push the sample crate · stop at the lookout
```

Callouts with arrows:
- On the lanes: "Hidden: which lane is passable (mud too thick? ice too slick? wind too
  strong? crate too heavy? wall?)"
- On the pad: "Test costs a few seconds"
- Top-right badge: "Budget: 64–92 s · 21 kJ"

Right panel: **Hoist yard**, side view.

```
  ================ rail ==================================
        [trolley]--->
            |   elastic cable (stiffness hidden)
            J   hook                                   +---------+
     [A]   [B]   [C]   identical crates                | PLATFORM| <- goal
  ------------------------------------------------------+---------+----
  hidden: crate masses (too light / right / too heavy), cable stiffness, sensor offset
  cheap test: slack reading -> offset · 1 cm pull -> stiffness · slow pull with a tension stop -> weight
```

- Badge: "12 variations: worn cable, stuck crate, unknown sensor gain, ..."
- Bottom strip spanning both panels: **Test too little → crash or snap. Test too much →
  clock runs out.**

**Narration (~58 words)**
> We built two MuJoCo worlds. A rover carries fragile cargo to a fork where only one
> lane is passable: mud, ice, wind, a heavy crate or a hidden wall decides which. The
> map looks the same either way. A hoist must pick the one crate its cable can lift.
> Cheap tests reveal the truth, but every second spent testing comes out of a fixed
> budget.

**Assets**
- Schematic: draw it new. Take coordinates from any `get_map` result, for example step
  2 of `jobs/eval-inkling-20261115-005608/rover-fork_barrier_mud-seed90000__czNbAnC/agent/trajectory.json`
  and step 2 of `jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__GHdkTJo/agent/trajectory.json`.
- Optional b-roll behind the panels: `jobs/eval-reference-20261114-232444/rover-fork_crate_barrier_mud-see__aD9PizZ/artifacts/rollout.mp4`
  (a three-lane course) and `jobs/eval-reference-20261114-232444/winch-five_way-seed90000__8YXCPwt/artifacts/rollout.mp4`.
- TODO: screenshot of the rover playground (`MUJOCO_GL=egl .venv/bin/python -m rover_env.play --host 0.0.0.0 --port 8081`)
  and of the winch playground at `/winch/`. The winch playground has a "reveal hidden
  values" button, which suits a quick before/after shot.

---

## Scene 3: How it is built (0:31–0:52, 21 s)

**Title:** *Physics in, reward out, nothing in between*

**On-screen content: boxes-and-arrows pipeline, left to right**

```
 +-------------------- Harbor task (docker compose) ----------------------------+
 |                                                                              |
 |  [ Agent container ]      MCP over HTTP       [ Simulator sidecar ]          |
 |  OpenCode + model   <-------------------->    MuJoCo episode                 |
 |  (no seed, no source)   observe / drive_to /  seed + hidden physics          |
 |                         winch / attach / finish  live here only              |
 |                                                      |                       |
 |                                                      | writes on finish      |
 |                                                      v                       |
 |                                          [ result volume ] -- read-only --> agent
 |                                                      |                       |
 |                                                      v                       |
 |                                          [ Verifier ] -> reward.txt          |
 +------------------------------------------------------------------------------+
   Reference = scripted policy using the SAME MCP tools (Harbor oracle, solution/solve.sh)
```

Formula card, bottom left:
`reward = 0` unless the cargo is delivered intact, within the time and energy budgets,
with no hard-constraint violation. Otherwise `reward = 0.5 + 0.5 × efficiency`.
Efficiency comes from time used, energy used and cargo damage.

Spec card, bottom right:
- 75 frozen tasks (seeds 90000+)
- 36 rover (9 courses × 4) + 39 hoist (13 tasks × 3)
- Balanced across hidden regimes
- `harbor_tasks/run_eval.sh <policy> [attempts]`

**Narration (~52 words)**
> The simulator runs as an MCP server inside Harbor. The agent sees only tools: observe,
> drive, winch, finish. Reward comes from simulator state alone: zero unless the cargo
> arrives intact and within budget, then one half plus half the efficiency. A scripted
> reference plays through the same tools. Seventy-five frozen tasks, one command.

**Assets**
- `harbor_tasks/eval_tasks/rover-fork_barrier_mud-seed90000/environment/docker-compose.yaml`
  shows the sidecar, the result volume and the `:ro` mount. Use it for an optional
  code-snippet overlay.
- `harbor_tasks/eval_tasks/<task>/tests/test.sh`: the reward comes only from `/sim_result/result.json`.
- `harbor_tasks/run_eval.sh`, `harbor_tasks/eval_set.json`.

---

## Scene 4: The reference works (0:52–0:58, 6 s)

**Title:** *The reference: test, decide, deliver*

**On-screen content**
- Split screen. Left: the reference rover on `fork_mud_ice` seed 90000 (tests the mud,
  takes the ice lane, delivers). Right: the reference hoist on `barrier` seed 90005
  (weighs, carries, sets the crate down).
- Caption: "Reference: 75/75 delivered · mean 0.748 · deterministic"

**Narration (~12 words)**
> The reference tests, decides and delivers: all seventy-five tasks, every time.

**Assets**
- `jobs/eval-reference-20261114-232444/rover-fork_mud_ice-seed90000__6ozNW53/artifacts/rollout.mp4` (reward 0.741, 50.6 s)
- `jobs/eval-reference-20261114-232444/winch-barrier-seed90005__tT4mmV8/artifacts/rollout.mp4` (reward 0.820)

---

## Scene 5: Results (0:58–1:18, 20 s)

**Title:** *A large gap that holds in every run*

**On-screen content: bar chart**

- X axis, in this order: Reference · DeepSeek 4.1 Flash · Inkling · Do-nothing ·
  Stop-early (finish at once) · Stop-early (reference cut at half).
- Y axis: mean reward, 0 to 1. Add a dashed line at 0.5, labelled "minimum for any
  delivery".
- Each model bar is the mean over 3 runs. Show each run as a small dot on the bar and a
  thin error bar for the spread across runs.
- Under each bar: delivery rate.
- Small multiples underneath: the same chart split into Rover and Hoist.

| Bar | Value to plot | Delivery |
|---|---|---|
| Reference | 0.748 (rover 0.716, hoist 0.777) | 100% |
| DeepSeek 4.1 Flash | `[DS_MEAN ± SPREAD]` (interim: 0.375 over 55 trials, 1 run; rover 0.449, hoist 0.246) | `[DS_DELIV]` (interim: 53%) |
| Inkling | `[INKLING_MEAN ± SPREAD]` (interim: 0.074 ± 0.012 over 2 runs, 122 trials; run means 0.068, 0.085; rover 0.110, hoist 0.030) | `[INKLING_DELIV]` (interim: 11%) |
| Do-nothing | 0.000 (74 tasks) | 0% |
| Finish at once | 0.000 (0/75 nonzero) | 0% |
| Reference cut at half | 0.000 (0/75 nonzero) | 0% |

**Narration (~50 words)**
> Doing nothing, or stopping early, scores zero. DeepSeek 4.1 Flash reaches
> [DS_MEAN] and delivers about half the tasks. Inkling averages [INKLING_MEAN] across
> three runs and delivers about one in [ten]. The gap holds in both worlds and in every
> run.

**Assets**
- Numbers: `presentation/scripts/headline.py` (reuses `harbor_tasks/results.py`) and
  `results/stop_early.json`.
- Job dirs: `jobs/eval-reference-20261114-232444`, `jobs/eval-do-nothing-20261114-234841`,
  `jobs/eval-deepseek-20261115-005638`, `jobs/eval-inkling-20261115-005608`, plus the
  run-3 Inkling job from the other VM (TODO: copy it in and add it to `inkling=`).
- Build the chart from those tables. Don't take a screenshot.

---

## Scene 6a: Why agents fail, rover (1:18–1:38, 20 s)

**Title:** *They run the test. They don't use the answer.*

**On-screen content**

Top: two timelines on the same 0–76 s axis (the budget for this task). Both are the
same task, `fork_mud_ice` seed 90000, where the mud is too thick and the ice lane is
open.

```
DeepSeek  |mud test|back|fork|---- ice lane ----|merge|goal ✓ 59 s   reward 0.705
          0       10   20   28                  47    54    59

Inkling   |pad|-- mud test --|-- ice test --|-- back to mud --|reposition|5 m/s at goal ✗ ROLLOVER 75 s
          0   7              22             37                52         62           75
```

Quote cards under each timeline. Fade in on cue; keep them short.
- DeepSeek (blue): *"mud is extremely viscous … The mud lane is likely impassable. So
  the north ice lane is the route."*
- Inkling (orange): *"The mud is causing deceleration … But first, maybe test ice."*
  then, at 52 s: *"We are low on time … Let's try a very high speed limit, say 4 or 5,
  to the goal."*

Stat strip along the bottom (interim, completed rover trials):

| | Inkling | DeepSeek |
|---|---|---|
| Tested before committing | 97% (66/68) | 91% (32/35) |
| Entered the open lane after testing (chance ≈ 45%) | 63% (27/43) | 100% (20/20) |
| Median share of time budget spent on the pad | 51% | 29% |
| Rover failures from running out of time | 24 of 57 | 0 of 12 |

**Narration (~62 words)**
> The agents do test. Inkling probes first in almost every rover episode. What fails is
> using the answer. Same course, same mud test. DeepSeek: "mud is extremely viscous; the
> ice lane is the route." Delivered. Inkling: "the mud is causing deceleration, maybe
> test ice." With two thirds of the clock gone, it drives at full speed at the goal and
> rolls over.

**Assets**
- DeepSeek: `jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90000__tjxmjeq/agent/trajectory.json`.
  The quote is in the message at `step_id` 5.
- Inkling: `jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90000__VZreTPB/agent/trajectory.json`.
  The quotes are in the reasoning at `step_id` 6 ("causing deceleration"), 7 ("Ice also
  slowing"), 9 ("low on time", t = 51.8 s) and 11 ("say 4 or 5", the 5 m/s `drive_to`).
- TODO: side-by-side videos of both trials, rendered with `harbor_tasks/replay_video.py`
  as in scene 1. The reference rollout of the same task is
  `jobs/eval-reference-20261114-232444/rover-fork_mud_ice-seed90000__6ozNW53/artifacts/rollout.mp4`.
- Stats: `presentation/analysis.md`, sections "Did the agent test before committing?",
  "Acting on the test" and "Time spent on the start pad".

---

## Scene 6b: Why agents fail, hoist (1:38–1:50, 12 s)

**Title:** *"A trigger, not a cap"*

**On-screen content**
- Left: an excerpt of the map text with the key sentence highlighted:
  `stop_tension is a trigger, not a cap: when the reading reaches it the drum brakes …
  and tension keeps rising while it slows.`
- Middle: two tension-versus-time sketches.
  - DeepSeek: pulls of 0.1 m, then 0.15 m. Tension 997 N, then about 1250 N, and the
    crate lifts: "≈122 kg ✓, carried, delivered 0.801".
  - Inkling: one pull of 1.0 m at 0.2 m/s with stop = 1800 N. The tension line shoots
    past the stop and past the 2000 N rating: "SNAP ✗".
- Right: counter "Cable snapped: Inkling 44/54 hoist episodes · DeepSeek 13/20"
  (interim). Sub-caption: "Slow pull with a tension stop (≤ 0.1 m/s) before carrying:
  Inkling 5/54, DeepSeek 2/20".

**Narration (~32 words)**
> On the hoist, Inkling pulls a full metre on an unknown crate and trusts the tension
> stop. The map says the stop is a trigger, not a cap. The cable snaps.

**Assets**
- Inkling: `jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__GHdkTJo/agent/trajectory.json`.
  Quotes: *"We can try to lift and see if tension rises dramatically or if cable snaps."*
  (`step_id` 8) and *"reduce cable length by say 1.0 slowly, speed 0.2 … But we don't know true
  tension due to offset."* (`step_id` 9). The call is `hoist_winch {"length_change": -1, "speed_limit":
  0.2, "stop_tension": 1800}`, which returns `cable_snapped`.
- DeepSeek: `jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc/agent/trajectory.json`.
  The quote is *"crate mass ≈ 1200/9.81 ≈ 122 kg. That's above 100kg minimum, and
  liftable."* (`step_id` 15).
- Map sentence: the `hoist.note` in step 2 of either trajectory.
- Reference video of the same task: `jobs/eval-reference-20261114-232444/winch-barrier-seed90005__tT4mmV8/artifacts/rollout.mp4`.
  TODO: there is no replay tool for winch trials, so the model episodes have no video.
  Use the tension sketch instead.
- Older b-roll of the same failure mode (single trials, not the eval set):
  `jobs/sonnet-winch-gain_reference-seed0/winch-gain_reference-seed0__Xo7uGxN/artifacts/rollout.mp4`
  (Sonnet 5.5 takes up slack at speed on a stiff cable, and the braking overshoot snaps
  it).

---

## Scene 7: Reward integrity and reproduction (1:50–1:57, 7 s)

**Title:** *No shortcuts. One command.*

**On-screen content: checklist with ticks**
- ✓ Do-nothing: 0 · Finish at once: 0/75 · Stopped at half the reference's actions: 0/75
- ✓ Reward is read only from the simulator. The result file is written on `finish` to
  a volume the agent can only read.
- ✓ Agents went looking. 59 Inkling episodes ran `find /`, `ps`, `env`, read the result
  file and opened a new MCP session with `curl`. None of it earned reward. A new
  session sees the same ended episode.
- ✓ The reference is deterministic and runs through the same tools as the agent.

Command card:
```
harbor_tasks/run_eval.sh reference
harbor_tasks/run_eval.sh do-nothing
harbor_tasks/run_eval.sh inkling 3
.venv/bin/python -m harbor_tasks.baselines        # stop-early
.venv/bin/python -m harbor_tasks.results reference=jobs/eval-reference-* inkling=jobs/eval-inkling-* ...
```

**Narration (~22 words)**
> Agents went looking for shortcuts: the file system, a fresh server session, a
> restart. None paid. Every number here reruns with one command.

**Assets**
- `results/stop_early.json`, `jobs/eval-do-nothing-20261114-234841`
- Exploit attempt with a new MCP session:
  `jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__e9TA84d/agent/trajectory.json`
  (the bash `curl` calls to `http://rover-sim:8000/mcp`)
- `rover_env/mcp_server.py` (`_write_result` runs on finish), `winch_env/mcp_server.py` (`finish`)

---

## Scene 8: Close (1:57–2:00, 3–5 s)

**On screen:** *Test at a cost that fits the stakes. Then act on what the test showed.*
Add the repo name and team.

**Narration (~15 words)**
> Test at a cost that fits the stakes, then act on what you learned.

---

## Narration word budget

| Scene | Seconds | Words |
|---|---|---|
| 1 Hook | 9 | 27 |
| 2 Challenge | 22 | 58 |
| 3 Build | 21 | 52 |
| 4 Reference | 6 | 12 |
| 5 Results | 20 | 50 |
| 6a Rover failure | 20 | 62 |
| 6b Hoist failure | 12 | 32 |
| 7 Integrity | 7 | 22 |
| 8 Close | 3 | 13 |
| **Total** | **120** | **≈ 330** |

At ElevenLabs' default pace (about 2.6 words per second), 330 words is about 127 s. To
reach ≤ 300 words, cut the second half of scene 4 and shorten scene 2 to: "We built two
MuJoCo worlds. A rover must pick the one passable lane, and a hoist the one crate its
cable can lift. The map looks the same either way. Cheap tests reveal the truth, at a
cost to a fixed budget." That saves about 30 words.

---

## B-roll candidates (existing videos)

| Video | What it shows | Use |
|---|---|---|
| `jobs/eval-reference-20261114-232444/rover-fork_mud_ice-seed90000__6ozNW53/artifacts/rollout.mp4` | Reference on the contrast task A | Scenes 4 and 6a |
| `jobs/eval-reference-20261114-232444/winch-barrier-seed90005__tT4mmV8/artifacts/rollout.mp4` | Reference on the contrast task B | Scenes 4 and 6b |
| `jobs/eval-reference-20261114-232444/rover-fork_crate_barrier_mud-see__aD9PizZ/artifacts/rollout.mp4` | Three-lane course | Scene 2 |
| `jobs/eval-reference-20261114-232444/winch-stuck_crate-seed90002__c9GeAqS/artifacts/rollout.mp4` | Stuck-crate variation | Scene 2 badge |
| `jobs/eval-reference-20261114-232444/rover-fork_replan-seed90005__7zActSA/artifacts/rollout.mp4` | Second fork, look on arrival | Spare |
| `jobs/sonnet-winch-gain_reference-seed0/winch-gain_reference-seed0__Xo7uGxN/artifacts/rollout.mp4` | Sonnet snaps a stiff cable through braking overshoot | Scene 6b (older single trial) |
| `jobs/sonnet-winch-stuck_crate-seed1/winch-stuck_crate-seed1__hBhaVg9/artifacts/rollout.mp4` | Sonnet frees a stuck crate by tugging sideways (0.871, beats the reference's 0.775) | Spare: "better play exists" |
| `jobs/deepseek-winch-worn_cable-seed0/winch-worn_cable-seed0__YE5ybh8/artifacts/rollout.mp4` | DeepSeek stops at 1600 N on a worn cable and snaps it | Spare |
| `jobs/sonnet55-fork-mud-ice-wind-seed0/rover-fork_mud_ice_wind-seed0__mvWTd8x/artifacts/rollout.mp4` | Sonnet drives straight down the mud lane without testing and gets lucky | Spare: "why we score over balanced seeds" |
| `runs/harbor_inkling_seed1.mp4`, `runs/harbor_deepseek_seed1.mp4` | Old `ramp` course | Avoid: earlier environment version |

TODO renders, with no video yet: Inkling `__VZreTPB` and DeepSeek `__tjxmjeq` (scenes 1
and 6a, rover, via `replay_video.py` on a copy of each trial dir). Hoist model episodes
need a replay tool first.

---

## Evidence appendix

| Claim (as used on screen or in narration) | Source |
|---|---|
| Reference 0.748 mean, 100% delivery (rover 0.716, hoist 0.777) | `jobs/eval-reference-20261114-232444`; `results/eval_summary.json`; `presentation/scripts/headline.py` |
| Reference is deterministic (rerun spread 0) | `rover_env/README.md` (reference rerun, max per-seed diff 0); `rover_env/test_env.py::test_reference_reproducible`; `winch_env/test_env.py::test_deterministic` |
| Do-nothing scores 0 on 74 tasks | `jobs/eval-do-nothing-20261114-234841` via `headline.py` |
| Finish-at-once and reference-cut-at-half: 0/75 nonzero | `results/stop_early.json`; `harbor_tasks/baselines.py` |
| Inkling interim 0.074 ± 0.012 (run means 0.068, 0.085), 11% delivery, 122 trials; 12 rate-limit trials excluded | `jobs/eval-inkling-20261115-005608` via `headline.py` and `analyze_trials.py` |
| DeepSeek interim 0.375, 53% delivery, 55 trials (rover 0.449 / 66%) | `jobs/eval-deepseek-20261115-005638` via the same scripts |
| Inkling tested first in 66/68 rover episodes; DeepSeek 32/35 | `presentation/analysis.md`, "Did the agent test before committing?" |
| After testing, open lane chosen: Inkling 27/43 (63%), DeepSeek 20/20; chance ≈ 45% | `presentation/analysis.md`, "Acting on the test" |
| Median time-budget share spent on the pad: Inkling 51%, DeepSeek 29% | `presentation/analysis.md`, "Time spent on the start pad" |
| 24 of 57 Inkling rover failures ran out of time; DeepSeek 0 | `presentation/analysis.md`, "Outcome reasons" and finding 3 |
| Cable snapped in 44/54 Inkling and 13/20 DeepSeek hoist episodes; slow tension-limited pull 5/54 and 2/20 | `presentation/analysis.md`, winch tables |
| DeepSeek mud quote, delivery 0.705 | `jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice-seed90000__tjxmjeq/agent/trajectory.json`, `verifier/sim_result.json` |
| Inkling "maybe test ice", "low on time", "speed limit 4 or 5"; rollover at 75.4 s | `jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90000__VZreTPB/agent/trajectory.json`, `verifier/sim_result.json` |
| Inkling 1 m pull at 0.2 m/s with stop 1800 N, cable snapped | `jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__GHdkTJo/agent/trajectory.json` |
| DeepSeek weighed in 0.1 m / 0.15 m pulls, ≈122 kg, delivered 0.801 | `jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc/agent/trajectory.json` |
| "stop_tension is a trigger, not a cap"; snaps "most easily when slack is taken up at speed" | `hoist.note` in the `get_map` result (step 2) of either winch trajectory above; source `winch_env/world.py` |
| Map warns that leaving the drivable surfaces is a drop; gives pad exit, test locations and lookout rule | `hazards`, `pad_exit` and `forks[].lanes[].test_on_start_pad` in the rover `get_map` result (step 2 of `.../rover-fork_barrier_mud-seed90000__czNbAnC/agent/trajectory.json`) |
| Reward formula; scored only from simulator state | `rover_env/README.md` ("Reward"); `winch_env/README.md`; `harbor_tasks/eval_tasks/*/tests/test.sh` |
| Result written only on finish; volume mounted read-only in the agent container | `rover_env/mcp_server.py` (`_write_result`), `winch_env/mcp_server.py` (`finish`); `harbor_tasks/eval_tasks/*/environment/docker-compose.yaml` (`sim_result:/sim_result:ro`) |
| 59 Inkling trials used shell/file tools (509 calls); 2 of them earned reward, by driving | `presentation/analysis.md`, "Shell / filesystem use" |
| A new MCP session sees the same ended episode | `jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__e9TA84d/agent/trajectory.json` (curl `initialize`, then `tools/call observe` returns the ended episode) |
| 75 tasks: 36 rover (9 × 4) + 39 hoist (13 × 3), seeds 90000+, regime-balanced | `harbor_tasks/eval_set.json`; `final_plan.md` |
| One-command runner | `harbor_tasks/run_eval.sh` |

### Caveats to keep in mind when presenting

- All model numbers are interim: 2 of 3 Inkling runs (and not all of run 2), and part of
  1 DeepSeek run. The "3 runs" wording waits on the final numbers.
- The most common rover crash for both models is clipping the start-pad corner on the
  way from a sample strip to the road. Inkling: 26 of 33 crashes on the pad or first
  road. DeepSeek: 12 of 12. The map states everything needed, and DeepSeek explains the
  error itself afterwards. Still, it is a path-planning mistake, not the
  hidden-property decision, so the video leads with lane choice and time instead.
  Details are in `presentation/analysis.md`, "Possible environment or harness issues".
- 3 Inkling hoist trials stopped mid-plan with no tool call, which may be an endpoint
  tool-call problem. 2 DeepSeek rover trials dropped the cargo by entering a sample
  strip at 3.5–4.5 m/s. Both are listed in `analysis.md`.
- In contrast B, DeepSeek picked the nearest crate, which happened to be the right one.
  The narration contrasts the size of the test pull, not the choice of crate.
- There is no top-level `README.md` yet. The craft criterion needs one that holds the
  one-command reproduction.

---
---

## OPTIONAL: use only if the experiment succeeds. Not part of the 2-minute storyline.

### Optional scene: Training a smaller model (Qwen3.6-27B, reward-filtered fine-tuning)

**Slot:** insert between scenes 6b and 7 (about +12 s), or use as a standalone slide in
the live 10-minute demo.

**Title:** *Can a smaller model learn to test?*

**On-screen content**
- Loop diagram: `untuned Qwen plays train seeds` → `keep delivered episodes only` →
  `LoRA fine-tune on its own tool calls` → `evaluate on held-out rover eval seeds` (arrow
  back to the start for round 2).
- Before/after bars on the same rover eval seeds and the same runner: untuned
  `[QWEN_BASE_MEAN]` against tuned `[QWEN_TUNED_MEAN]`, with delivery rates and spread.
- One behaviour metric from `analyze_trials.py` on both runs, for example "entered the
  open lane after testing" or "share of budget spent on the pad".

**Narration (~30 words)**
> As a tiebreaker, we fine-tuned a smaller open model on its own successful episodes.
> On held-out seeds, reward rose from [BASE] to [TUNED], and it chose the open lane
> more often.

**Assets (to fill in)**
- Plan: `final_plan.md`, section "Qwen3.6-27B reward-filtered fine-tuning".
- Candidate job dirs: `jobs/train-qwen-*`, `jobs/qwen-harbor-vanilla-*`,
  `jobs/qwen-harbor-dpo-*`, `jobs/qwen-import-*`. Not analysed here.
- If the result is null, drop the scene. Don't present a null result as a gain.
