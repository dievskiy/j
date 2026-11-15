# Reward-filtered fine-tuning of Qwen3.6-27B

Train a smaller open model on its own successful experience in the environments, then
compare it with the untuned model on the frozen evaluation set. It is on-policy and
reward-filtered: the model plays training tasks, the simulator's verified reward selects
the episodes that delivered, and the model is fine-tuned on exactly what it saw and
produced in those episodes.

## Pipeline

| Step | Script | Where it ran |
|---|---|---|
| 1. Serve the untuned model with vLLM 0.32 | `serve_qwen.sh` (local A100) or `modal_serve.py` (Modal) | A100 80 GB |
| 2. Record every request and response between OpenCode and the model | `logging_proxy.py` | CPU |
| 3. Play training tasks (seeds 50000+, never evaluation seeds) | `harbor_tasks/run_eval.sh qwen <attempts> <concurrency> train` | Harbor + Docker |
| 4. Keep steps of episodes with verified reward > 0; render with the request's own tools | `rft_data.py` | CPU |
| 5. LoRA fine-tune (BF16, r 16, lr 1e-4, batch 1, prompts up to 40k tokens) | `rft_modal.py` | Modal H200 |
| 6. Merge the adapter into the original weight shards | `merge_lora.py` | CPU |
| 7. Serve tuned with identical flags; evaluate both on the 75 tasks | `serve_qwen.sh`, `harbor_tasks/run_eval.sh qwen` | A100 80 GB |
| 8. Paired comparison (bootstrap CI, exact McNemar) | `harbor_tasks/compare.py` | CPU |

Details that matter:

- **The training prompt is exactly what the model saw.** The proxy logs OpenCode's real
  requests (system prompt, tool definitions, thinking on); rendered prompt token counts
  match vLLM's `prompt_tokens` exactly (12 of 12 checked). The loss covers only the
  model's own reasoning and tool-call tokens.
- **Steps are joined to rewards by tool-call ids**, which vLLM generates randomly and
  Harbor stores in each trial's `trajectory.json`.
- **Sampling:** pick a successful episode uniformly, then one of its steps, so long
  episodes do not dominate.
- **Hopper:** FLA's linear-attention backward needs `tilelang` (and so `nvcc`) on H100/H200;
  `rft_modal.py` uses a CUDA devel image for that.
- **Serving:** both models use FlashInfer attention; FlashAttention-3 crashed vLLM while
  capturing CUDA graphs. The merge writes the base checkpoint with `W += (alpha/r)·B·A`, so
  the tuned model needs no LoRA support in vLLM.

## Results

| Round | Training data | Untuned | Tuned | Paired difference [95% CI] |
|---|---|---|---|---|
| 1 | 13 successful episodes (11 rover, 2 winch), 196 examples, 120 steps | 0.319 | 0.297 | −0.022 [−0.098, +0.053] |
| 2 | 32 successful episodes (+19 winch over 8 variations), 647 examples, 150 steps | | being evaluated | |

Round 1 showed no measurable improvement; per environment, rover −0.001 [−0.130, +0.129]
and winch −0.041 [−0.122, +0.039].

## Commands

```bash
QWEN_API_KEY=... finetune/serve_qwen.sh <model path> qwen-base            # needs vLLM 0.32 + ninja + nvcc
QWEN_API_KEY=... python finetune/logging_proxy.py --upstream http://172.17.0.1:8000/v1 \
    --log data/requests.jsonl --host 172.17.0.1 --port 9100
QWEN_API_KEY=... QWEN_MODEL=qwenlab/qwen-base QWEN_BASE_URL=http://172.17.0.1:9100/v1 \
    harbor_tasks/run_eval.sh qwen 4 12 train
python finetune/rft_data.py --log data/requests.jsonl --jobs jobs/train-qwen-* --out data/rft_tokens.jsonl
modal volume put qwen-adapters data/rft_tokens.jsonl rft/rft_tokens.jsonl
modal run finetune/rft_modal.py --gpu h200 --steps 150 --no-merge
modal volume get qwen-adapters rft-h200-r2/adapter adapter/
python finetune/merge_lora.py --adapter adapter --out merged
QWEN_API_KEY=... finetune/serve_qwen.sh merged qwen-tuned
python -m harbor_tasks.compare 'jobs/eval-qwen-base-*' 'jobs/eval-qwen-tuned-*' untuned tuned
```

Python dependencies: `transformers==5.23.0`, `peft==0.21.3`, `flash-linear-attention==0.6.0`,
`safetensors`, `httpx`, `starlette`, `uvicorn`, `modal`; vLLM 0.32.0 for serving.
