#!/bin/bash
# Run one policy over a frozen task split (harbor_tasks/<split>_set.json; eval has 75 tasks).
#   harbor_tasks/run_eval.sh reference|do-nothing|model|inkling|deepseek|qwen [attempts] [concurrency] [eval|train]
#
# `model` runs OpenCode against any OpenAI-compatible endpoint:
#   MODEL=provider/model-id BASE_URL=https://.../v1 API_KEY_NAME=MY_KEY harbor_tasks/run_eval.sh model 3
# Harbor is taken from $HARBOR, else /root/harbor-venv, else PATH.
set -e
cd "$(dirname "$0")/.."
POLICY=$1; ATTEMPTS=${2:-1}; CONCURRENCY=${3:-8}; SPLIT=${4:-eval}
HARBOR=${HARBOR:-$( [ -x /root/harbor-venv/bin/harbor ] && echo /root/harbor-venv/bin/harbor || echo harbor )}
[ -d harbor_tasks/${SPLIT}_tasks ] || .venv/bin/python -m harbor_tasks.eval_set --split "$SPLIT" --make

load_keys() { [ -f "$1" ] && { set -a; . "$1"; set +a; }; return 0; }
opencode_agent() {  # model, key variable name, base URL
  AGENT=(-a opencode -m "$1" --api-key-name "$2" --api-format openai_chat_completions --base-url "$3")
}

case $POLICY in
  reference)  AGENT=(-a oracle) ;;
  do-nothing) AGENT=(-a nop) ;;
  model)      opencode_agent "$MODEL" "$API_KEY_NAME" "$BASE_URL" ;;
  inkling)    load_keys /root/.modal.env
              opencode_agent modal/thinkingmachines/Inkling-NVFP4 MODAL_API_KEY \
                "${INKLING_BASE_URL:?set INKLING_BASE_URL to the Inkling endpoint}" ;;
  deepseek)   load_keys /root/.verda.env
              opencode_agent verda/deepseek-4-1-flash-1017 VERDA_API_KEY https://inference.verda.com/v1 ;;
  qwen)       opencode_agent "$QWEN_MODEL" QWEN_API_KEY "$QWEN_BASE_URL" ;;
  *) echo "unknown policy $POLICY"; exit 1 ;;
esac
JOB=$SPLIT-$POLICY-$(date +%Y%m%d-%H%M%S)
"$HARBOR" run -p harbor_tasks/${SPLIT}_tasks -o jobs --job-name "$JOB" \
  -k "$ATTEMPTS" -n "$CONCURRENCY" --agent-setup-timeout-multiplier 4 -y "${AGENT[@]}"
echo "$JOB"
