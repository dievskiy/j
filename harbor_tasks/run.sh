#!/bin/bash
# Run a Harbor job on one rover task, then publish its rollout video where the Harbor
# viewer plays it (the trial page's Recording tab).
#   harbor_tasks/run.sh <job-name> <course> <seed> [harbor run args...]
set -e
cd "$(dirname "$0")/.."
JOB=$1; COURSE=$2; SEED=$3; shift 3
TASK=$(python3 harbor_tasks/make_tasks.py --course "$COURSE" "$SEED")
/root/harbor-venv/bin/harbor run -p "$TASK" -o jobs --job-name "$JOB" -y "$@"
harbor_tasks/publish_videos.sh "jobs/$JOB"
