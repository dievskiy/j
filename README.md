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

## Results on the frozen evaluation set

75 tasks (36 rover, 39 winch), seeds 90000+, balanced across hidden regimes
([`harbor_tasks/eval_set.json`](harbor_tasks/eval_set.json)). Mean reward ± spread of
the three run means; delivery rate in brackets.

| Policy | Rover | Winch | All |
|---|---|---|---|
| Reference (scripted, same MCP tools) | 0.716 (100%) | 0.777 (100%) | **0.748** (100%) |
| DeepSeek 4.1 Flash, 3 runs | [TBD] | [TBD] | [TBD] |
| Inkling, 3 runs | [TBD] | [TBD] | [TBD] |
| Do-nothing (Harbor `nop`) | 0 | 0 | **0** |
| Stop-early: finish at once / reference cut at half its actions | 0 | 0 | **0** (0/75 nonzero) |

Why the agents fall short: [`presentation/analysis.md`](presentation/analysis.md).

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
| `presentation/` | demo sketch and failure analysis |
| `ENVIRONMENTS.md` | register of environments, scripted results, single-trial model notes |
