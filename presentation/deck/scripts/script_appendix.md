## Replay check

Every simulation frame comes from replaying the trial's recorded MCP tool calls
(`agent/trajectory.json`) on a fresh episode, on a copy of the trial directory under
`presentation/deck/work/`. `scripts/replay_frames.py` compares the replayed reward, end time
and reason with `verifier/sim_result.json`.

| Trial (copied from `jobs/`) | Task | Recorded outcome | Replay matches |
|---|---|---|---|
| `eval-inkling-20261115-005608/rover-fork_mud_ice_wind-seed9000__iGPKtYU` | rover-fork_mud_ice_wind-seed90001 | reward 0, cargo not inside goal circle, t = 86.52 s | yes (also with `harbor_tasks/replay_video.py`) |
| `eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__W5vkMLh` | rover-fork_mud_ice_wind-seed90001 | reward 0.702, delivered, t = 59.36 s | yes (also with `harbor_tasks/replay_video.py`) |
| `eval-inkling-20261115-005608/winch-barrier-seed90005__GHdkTJo` | winch-barrier-seed90005 | reward 0, cable snapped, t = 13.332 s | yes |
| `eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc` | winch-barrier-seed90005 | reward 0.801, delivered, t = 47.5 s | yes |
| `eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__e9TA84d` | rover-fork_mud_ice-seed90002 | reward 0, chassis collision, t = 39.64 s | yes (also with `harbor_tasks/replay_video.py`) |

The tension chart on slide 6 plots the simulator's true cable tension during those two
replays. Inkling's `stop_tension=1800` is a sensor reading; the sensor offset in this episode
is +110.5 N, so the stop tripped at 1690 N true tension, 1.13 s into the pull.

## Regenerate

```bash
presentation/deck/scripts/render_all.sh                    # copy trials, replay, render frames (needs MUJOCO_GL=egl)
python3 presentation/deck/scripts/make_charts.py           # SVG charts and the harness diagram
.venv/bin/python presentation/deck/scripts/build_deck.py   # slide images, deck.pdf, index.html, script.md
```

`deck.pdf` is the file to upload (PDF, under 20 MB). If a second fine-tuning round should be
shown, set `ROUND_2_MEAN` in `scripts/deck_data.py` and rerun the last two commands.
