# Winch yard

A gantry hoist must deliver one crate to a raised platform. It is the second
environment category, built on the same skeleton as the rover courses.

- **Hidden:** the mass of each of three identical-looking crates, the stiffness of the
  elastic cable, and a constant offset of up to 200 N on the tension sensor. Exactly one
  crate is both heavy enough to count (100 kg or more) and light enough for the cable
  (rated 2000 N); the others are too light or too heavy.
- **Tests:** with the cable slack, the tension reading is the sensor's offset. A
  one-centimetre pull on a hooked crate shows the cable stiffness. Taking up the load
  slowly with a tension stop then weighs the crate: if it leaves the ground the steady
  tension is its weight, and if the stop trips first it is too heavy.
- **Commitment:** carrying a crate to the platform takes most of the remaining time.
  A crate below the required payload does not count, and pulling a crate that is too
  heavy, taking up slack at speed, or trusting an uncorrected tension stop can snap the
  cable.
- **Reward:** 0 unless a qualifying crate has sat on the platform's goal area, released,
  upright and still, for half a second, undamaged, with the cable whole and within the
  time and energy budgets; otherwise 0.5 + 0.5 × efficiency.

Tools: `observe`, `move_trolley(x, speed_limit, max_duration)`,
`winch(length_change, speed_limit, max_duration, stop_tension=None)`, `attach`, `release`,
`wait(duration)`, `finish`.

MuJoCo simulates the crates. The trolley and free hook move kinematically, and the cable
is a one-sided spring from the drum to the hooked crate's lug, applied as an external
force each step. The winch is a speed source, so tension is whatever the physics makes it.

```
.venv/bin/python -m winch_env.evaluate --seeds 72
.venv/bin/python -m winch_env.test_env
```

Results over 72 seeds: the reference delivers 100% (mean reward 0.735); the best plan
that does not weigh delivers 47% (0.356); single-crate gambles 28-36%; do-nothing,
random, invalid-input and drop-on-goal policies score 0.

Hidden values are drawn from a stream salted by the `WINCH_HIDDEN_SALT` environment
variable (default 0), so an evaluator can make them unrecoverable from the seed and the
source.

## Playground

Operate any yard by hand in a browser through the agent's tools, with a side view, the
rendered scene, the last command's trace and a button that reveals the hidden values:

```
MUJOCO_GL=egl .venv/bin/python -m winch_env.play --host 0.0.0.0 --port 8082
```

The rover playground also serves it under `/winch/`.

## Named yard variations

`Episode(seed, difficulty, variation="short_pair")` selects a named yard. Omitting
`variation` retains the original yard and its policy results above. The map reports
layout, task, test instructions and budgets; hidden masses, stiffness, offset and
(where applicable) gain come from the `WINCH_HIDDEN_SALT` stream. Reference weights
are marked in the map with `"cargo": false` and `known_mass_kg` (90 kg) and never count
as a delivery. The map states facts only (the cable law, sensor model and task), never
the procedure: finding that weighing, offset reading or gain calibration is needed is
part of the task. `Scenario.mode` records the hidden regime (`<bands>_<cable>`, e.g.
`RLH_soft`) so results can be broken down by it.

| Variation | Layout and task |
|---|---|
| `short_pair` | Two cargo crates, deliver the qualifying one |
| `high_stack` | Three cargo crates, higher platform |
| `left_bank` | Three cargo crates, platform on the left |
| `crowded` | Four cargo crates, two too light |
| `five_way` | Five cargo crates, two too light and two overloaded |
| `barrier` | Three cargo crates, wall requires extra clearance |
| `weight_window` | Three liftable crates, deliver one within the stated window |
| `heaviest` | Three liftable crates, weigh all and deliver the heaviest |
| `gain_reference` | Three cargo crates plus a known weight; sensor gain is unknown |
| `worn_cable` | Four cargo crates; the cable is intact or worn (hidden). Deliver the heaviest crate the cable can lift: a medium crate if intact, a lighter one if worn. A worn cable creeps above 85% of its strength, so a held pull on an unliftable crate relaxes |
| `stuck_crate` | Three cargo crates; in half the episodes the right crate is stuck to the floor and looks too heavy until a sideways pull of 60 N frees it |
| `total_payload` | Four cargo crates, one overloaded; deliver at least 200 kg in total, which only the two right crates together reach |

Validation at difficulty 0.5 on seeds 0..47:

```
.venv/bin/python -m winch_env.evaluate --variation all --seeds 48
variation        reference  delivery  best non-test  gap    integrity  status
short_pair          0.789  100.00%  nearest_careful  0.342      0.000  PASS
high_stack          0.779  100.00%  first_that_lifts 0.400      0.000  PASS
left_bank           0.795  100.00%  first_that_lifts 0.423      0.000  PASS
crowded             0.799  100.00%  middle_careful   0.590      0.000  PASS
five_way            0.822  100.00%  first_that_lifts 0.555      0.000  PASS
barrier             0.776  100.00%  first_that_lifts 0.398      0.000  PASS
weight_window       0.785  100.00%  first_that_lifts 0.463      0.000  PASS
heaviest            0.734  100.00%  farthest_careful 0.517      0.000  PASS
gain_reference      0.733  100.00%  first_that_lifts 0.412      0.000  PASS
total_payload       0.727  100.00%  first_that_lifts 0.573      0.000  PASS
worn_cable          0.764  100.00%  middle_careful   0.531      0.000  PASS
stuck_crate         0.765  100.00%  farthest_careful 0.609      0.000  PASS
```

`--variation a,b` validates a subset. On `total_payload` the `first_that_lifts`
baseline fills both goal slots with the first two crates that lift.

Proposed split: train on `short_pair`, `high_stack`, `left_bank`, `crowded`,
`five_way`, `barrier`, `weight_window`; hold out `heaviest` (task type) and
`gain_reference` (hidden gain and calibration weight). Use disjoint seeds and a
private nonzero hidden salt on evaluation.

On `worn_cable`, replacing the reference's creep check with a fixed assumption
delivers on 6 of 12 seeds either way: assuming intact snaps worn cables, assuming worn
misses the medium crate on intact ones. No separate anchor ring is needed: an
unliftable crate serves as the proof-pull anchor.

On `stuck_crate`, the reference without its sideways tug fails every stuck episode.

Limitations: There is no energy-tight variant: energy here is dominated by idle power and trolley
travel, which scale with time, so a tight energy budget could not fail a wasteful
plan without also failing the reference. Validation covers only 48 seeds at
one difficulty and one salt, not all possible regimes. The cautious baseline is a
single slow take-up and may itself reveal liftability; its name is historical.

Not built yet: a Harbor task for this category and video recording.
