# Test before you commit: physical-diagnosis environments for agents

Agents must **actively test an uncertain physical system, at a cost proportional to the
stakes, and then act on what the test showed**. Each episode hides a physical property
that changes the right action. A cheap test reveals it, and the budgets fit the right
action plus testing, but not a blind gamble followed by a retreat.

Two MuJoCo environment families, served to the agent over MCP and run with
[Harbor](https://github.com/laude-institute/harbor) + OpenCode:

| Environment | Task | Hidden | Cheap test |
|---|---|---|---|
| **Rover** (`rover_env/`) | drive fragile cargo to a goal; at each fork exactly one lane is passable and the map looks the same either way | mud drag, ice friction, wind, crate mass, barriers | sample strips, a sample crate and a lookout near the start |
| **Winch yard** (`winch_env/`) | deliver the right crate to a platform with a gantry hoist (12 variations) | crate masses, cable stiffness, sensor offset, worn cable, stuck crate | slack reading, a 1 cm pull, a slow tension-limited take-up |

Details, per-course tables and known issues: [`ENVIRONMENTS.md`](ENVIRONMENTS.md).

## Reward

`0` unless the cargo is delivered intact within the time and energy budgets with no
hard-constraint violation; otherwise `0.5 + 0.5 × efficiency`. It is computed only from
simulator state inside a sidecar container. The agent reaches the simulator only through
the MCP tools; the result file is written on `finish` to a volume the agent can only read.

## What the reference is

The **reference** is the stronger run the rubric asks for: a hand-written, scripted policy
per environment that plays *the same task through the same MCP tools as the agent*. It
does what we want agents to learn: run the cheap test, read the measurement, then act on it.

- **No hidden information.** It sees exactly the agent's tool surface (`get_map`,
  `observe` and the action tools); in the simulator code it runs behind a `ToolProxy` that
  exposes only the agent's tools, and in Harbor it talks to the task's MCP server like any
  agent. It branches only on what those tools return.
- **Rover** (`rover_env/policies_fork.py:reference`, `policies_serpentine.py`): test each
  hazard on the start pad (drive over the sample strips, push the sample crate, visit the
  lookout), take the lane the evidence supports, look again at a second fork, deliver.
- **Winch** (`winch_env/policies.py:reference`, `variation_reference`): read the tension
  sensor at slack to get its offset, make a 1 cm pull to estimate cable stiffness, weigh
  crates with slow tension-limited take-ups, then carry the right one (with variation-
  specific steps: a lower tension cap on a possibly worn cable, a sideways tug for a
  stuck crate).
- **In Harbor** it is the `oracle` agent: each task's `solution/solve.sh` runs
  [`harbor_tasks/oracle.py`](harbor_tasks/oracle.py), a small stdlib MCP client that plays
  the policy against the task's simulator sidecar. Its rewards match the direct
  simulator runs exactly, and it delivers on all 75 evaluation tasks.
- **It is not an upper bound.** It is one sound strategy, not the optimum: a single trial
  of Sonnet 5.5 beat it on a stuck-crate yard by freeing the crate sooner
  (`ENVIRONMENTS.md`). Scores above it are possible; scores near it require testing.

## Results on the frozen evaluation set

75 tasks (36 rover, 39 winch), seeds 90000+, balanced across hidden regimes
([`harbor_tasks/eval_set.json`](harbor_tasks/eval_set.json)). Mean reward ± spread of
the three run means; delivery rate in brackets.

| Policy | Rover | Winch | All |
|---|---|---|---|
| Reference (scripted, same MCP tools) | 0.716 (100%) | 0.777 (100%) | **0.748** (100%) |
| DeepSeek 4.1 Flash, 3 runs | 0.411 ± 0.064 (58%) | 0.259 ± 0.062 (32%) | **0.332 ± 0.053** (45%) |
| Inkling, 3 runs | 0.099 ± 0.030 (15%) | 0.066 ± 0.027 (9%) | **0.082 ± 0.006** (12%) |
| Do-nothing (Harbor `nop`) | 0 | 0 | **0** |
| Stop-early: finish at once / reference cut at half its actions | 0 | 0 | **0** (0/75 nonzero) |

Every run of both models is far below the reference (run means: DeepSeek 0.372, 0.271,
0.352; Inkling 0.075, 0.085, 0.085). 21 trials that hit API rate limits before finishing
were rerun and are excluded. Why the agents fall short:
[`presentation/analysis.md`](presentation/analysis.md).

## Training a smaller model

We fine-tuned **Qwen3.6-27B** on its own successful episodes (reward-filtered, on-policy;
training seeds 50000+, never the evaluation seeds) and evaluated it on the same 75 tasks
against the untuned model, both served by vLLM with identical flags. Pipeline and details:
[`finetune/`](finetune/README.md).

| | Rover | Winch | All |
|---|---|---|---|
| Qwen3.6-27B untuned | 0.415 | 0.231 | **0.319** |
| Fine-tuned (13 successful episodes, 196 examples) | 0.414 | 0.189 | **0.297** |
| Paired difference [95% bootstrap CI] | −0.001 [−0.130, +0.129] | −0.041 [−0.122, +0.039] | −0.022 [−0.098, +0.053] |

**No measurable improvement.** The training data was too small and almost all rover. A
second round with winch-heavy rollouts (32 successful episodes, 647 examples) is being
evaluated.

## Reproduce

Requirements: Docker, Python 3.12+, Harbor (`pip install harbor`; 0.26.0 tested).

```bash
python3 -m venv .venv && .venv/bin/pip install -r rover_env/requirements.txt

harbor_tasks/run_eval.sh reference              # reference run through Harbor's oracle agent
harbor_tasks/run_eval.sh do-nothing             # do-nothing baseline
MODEL=provider/model-id BASE_URL=https://.../v1 API_KEY_NAME=MY_API_KEY \
  harbor_tasks/run_eval.sh model 3              # any OpenAI-compatible model, 3 runs over 75 tasks
.venv/bin/python -m harbor_tasks.baselines      # stop-early baselines, directly on the simulator

.venv/bin/python -m harbor_tasks.results reference='jobs/eval-reference-*' agent='jobs/eval-model-*'
```

`run_eval.sh <policy> [attempts] [concurrency]` generates the 75 Harbor tasks on first use
(`harbor_tasks/eval_set.py --make`). Each task's `solution/solve.sh` plays the scripted
reference through the task's MCP server, so the oracle agent is an honest reference run.
`results.py` counts agent crashes and timeouts as 0 and leaves out only failures before
the agent acted (Docker errors, agent install timeouts, API rate limits), listing them.

Without Harbor, the scripted tables in `ENVIRONMENTS.md` reproduce with
`.venv/bin/python -m rover_env.evaluate --course <course> --seeds 40` and
`.venv/bin/python -m winch_env.evaluate --seeds 72`.

## Layout

| Path | What |
|---|---|
| `rover_env/`, `winch_env/` | simulators, MCP servers, scripted policies, evaluators, tests |
| `harbor_tasks/` | task generator, frozen splits, reference oracle, runner, results table |
| `finetune/` | reward-filtered fine-tuning of Qwen3.6-27B: logging proxy, data builder, Modal trainer, merge, serving |
| `presentation/` | demo sketch and failure analysis |
| `ENVIRONMENTS.md` | register of environments, scripted results, single-trial model notes |
