#!/usr/bin/env bash
# Regenerate every simulation still and replay-state file used by the deck.
# Copies the trials out of jobs/ first; jobs/ is never written to.
set -euo pipefail
cd "$(dirname "$0")/../../.."
DECK=presentation/deck
WORK=$DECK/work
ASSETS=$DECK/assets
REPLAY="env MUJOCO_GL=${MUJOCO_GL:-egl} .venv/bin/python $DECK/scripts/replay_frames.py"
mkdir -p "$WORK/rover" "$WORK/winch" "$WORK/states" "$ASSETS"

copy_trial() {  # copy_trial <trial dir under jobs/> <rover|winch>
  rsync -a --exclude 'agent/opencode' --exclude 'agent/setup' --exclude 'artifacts' "$1" "$WORK/$2/"
}
copy_trial jobs/eval-inkling-20261115-005608/rover-fork_mud_ice_wind-seed9000__iGPKtYU rover
copy_trial jobs/eval-deepseek-20261115-005638/rover-fork_mud_ice_wind-seed9000__W5vkMLh rover
copy_trial jobs/eval-inkling-20261115-005608/rover-fork_mud_ice-seed90002__e9TA84d rover
copy_trial jobs/eval-inkling-20261115-005608/winch-barrier-seed90005__GHdkTJo winch
copy_trial jobs/eval-deepseek-20261115-005638/winch-barrier-seed90005__RSrt5rc winch

INK_ROVER=$WORK/rover/rover-fork_mud_ice_wind-seed9000__iGPKtYU
DS_ROVER=$WORK/rover/rover-fork_mud_ice_wind-seed9000__W5vkMLh
EXPLOIT=$WORK/rover/rover-fork_mud_ice-seed90002__e9TA84d
INK_WINCH=$WORK/winch/winch-barrier-seed90005__GHdkTJo
DS_WINCH=$WORK/winch/winch-barrier-seed90005__RSrt5rc

# Behaviour 1: rover fork_mud_ice_wind seed 90001 (ice lane open, mud too thick)
$REPLAY $INK_ROVER --dump-states $WORK/states/rover_inkling.json \
  --frame $ASSETS/rover_course.png:0:overview:'{"distance":60,"elevation":-55}' \
  --frame $ASSETS/rover_inkling_1_strip.png:20:close \
  --frame $ASSETS/rover_inkling_2_fork.png:72.6:chase \
  --frame $ASSETS/rover_inkling_3_stuck.png:86.5:close
$REPLAY $DS_ROVER --dump-states $WORK/states/rover_deepseek.json \
  --frame $ASSETS/rover_deepseek_1_strip.png:17:close \
  --frame $ASSETS/rover_deepseek_2_ice.png:43:close \
  --frame $ASSETS/rover_deepseek_3_goal.png:59.36:close

# Behaviour 2: winch barrier seed 90005 (far crate 259 kg, too heavy for the 2000 N cable)
$REPLAY $INK_WINCH --dump-states $WORK/states/winch_inkling.json \
  --frame $ASSETS/winch_inkling_1_hooked.png:12.0:close \
  --frame $ASSETS/winch_inkling_2_snapped.png:13.33:close
$REPLAY $DS_WINCH --dump-states $WORK/states/winch_deepseek.json \
  --frame $ASSETS/winch_deepseek_1_weigh.png:16.2:close \
  --frame $ASSETS/winch_deepseek_2_carry.png:26.5:side \
  --frame $ASSETS/winch_deepseek_3_delivered.png:47.5:chase

# Behaviour 3: the episode behind the shortcut hunt (rover fork_mud_ice seed 90002)
$REPLAY $EXPLOIT --dump-states $WORK/states/rover_exploit.json \
  --frame $ASSETS/exploit_crash.png:39.64:close

# Title-slide hero at full slide resolution
$REPLAY $INK_ROVER --size 1920x1080 --frame $ASSETS/rover_hero.png:86.5:close:'{"lookat":[20.2,2.2,0.33],"distance":8.5}'

# PNG -> JPG keeps the deck small
.venv/bin/python - <<'PY'
import glob, os
from PIL import Image
for path in glob.glob("presentation/deck/assets/*.png"):
    if os.path.basename(path).split("_")[0] in ("rover", "winch", "exploit"):
        Image.open(path).convert("RGB").save(path[:-4] + ".jpg", quality=88)
        os.remove(path)
PY
