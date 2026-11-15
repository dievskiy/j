#!/bin/bash
# Serve Qwen3.6-27B (or a merged checkpoint) locally with vLLM 0.32; identical flags for base and tuned.
# Listens on the Docker bridge so only local Harbor containers can reach it.
#   serve_qwen.sh <model path or id> <served name>
: "${QWEN_API_KEY:?set QWEN_API_KEY}"
export PATH=${VLLM_VENV:-/root/vllm-venv}/bin:/usr/local/cuda/bin:$PATH CUDA_HOME=/usr/local/cuda
exec ${VLLM_VENV:-/root/vllm-venv}/bin/vllm serve "$1" --served-model-name "$2" \
  --host 172.17.0.1 --port 8000 --api-key "$QWEN_API_KEY" \
  --max-model-len 65536 --language-model-only --reasoning-parser qwen3 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --attention-backend FLASHINFER
