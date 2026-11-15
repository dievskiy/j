"""Reward-filtered fine-tuning of Qwen3.6-27B on Modal, then a merged checkpoint for vLLM.

    /root/modal-venv/bin/modal volume put qwen-adapters data/rft_tokens.jsonl rft/rft_tokens.jsonl
    /root/modal-venv/bin/modal run rft_modal.py --steps 160

Same recipe as the A100 pilots (BF16 LoRA rank 16 on attention, linear-attention and
MLP projections; loss only on the model's own tokens), on an H200 so long OpenCode
prompts fit. The LoRA delta is added straight into the original weight shards (`merge_lora.py`, here
with --merge or locally), so vLLM serves the tuned model exactly like the base one.
"""
import modal

MODEL = "Qwen/Qwen3.6-27B"
REVISION = "8f33b98937c6031bb49e713dee3e8e185aafd26f"
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
                  "in_proj_qkv", "in_proj_z", "in_proj_b", "in_proj_a", "out_proj"]
RANK = 16
TAG = "rft-h200-r2"   # output folder on the qwen-adapters volume; round 1 was rft-h200

# The CUDA devel base provides nvcc, which FLA needs before it will use tilelang.
image = (modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12")
         .entrypoint([])
         .uv_pip_install("torch==2.10.0", "transformers==5.23.0", "peft==0.21.3",
                         "flash-linear-attention==0.6.0", "fla-core==0.6.0", "accelerate==1.15.0",
                         "safetensors==0.8.0", "kernels==0.18.3", "einops==0.8.2",
                         "huggingface_hub[hf_transfer]==2.4.0", "triton==3.6.0",
                         "tilelang==0.1.15")  # FLA needs it for a correct backward pass on Hopper
         .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
         .add_local_python_source("merge_lora"))
weights = modal.Volume.from_name("qwen-hf-cache", create_if_missing=True)
adapters = modal.Volume.from_name("qwen-adapters", create_if_missing=True)
app = modal.App("qwen-rft")


def enable_fast_kernels():
    """Bind the version-pinned FLA and causal-conv kernels, as the A100 runs did."""
    import kernels
    from fla.ops.gated_delta_rule import chunk_gated_delta_rule, fused_recurrent_gated_delta_rule
    from transformers.models.qwen3_5 import modeling_qwen3_5 as implementation
    implementation.torch_chunk_gated_delta_rule = chunk_gated_delta_rule
    implementation.torch_recurrent_gated_delta_rule = fused_recurrent_gated_delta_rule
    convolution = kernels.get_kernel("kernels-community/mamba-ssm",
                                     revision="61f43db7f576380e5504d55f61146460baa3abc8")
    implementation.causal_conv1d_fn = convolution.layers.causal_conv1d_fn()
    implementation.causal_conv1d_update = convolution.layers.causal_conv1d_update()


def train(examples: list[dict], steps: int, learning_rate: float, seed: int, log) -> "torch.nn.Module":
    import random
    import time

    import torch
    import torch.nn.functional as functional
    from peft import LoraConfig, get_peft_model
    from transformers import Qwen3_5ForCausalLM

    enable_fast_kernels()
    model = Qwen3_5ForCausalLM.from_pretrained(MODEL, revision=REVISION, dtype=torch.bfloat16,
                                               device_map={"": 0}, attn_implementation="sdpa")
    model = get_peft_model(model, LoraConfig(r=RANK, lora_alpha=2 * RANK, lora_dropout=0.0,
                                             target_modules=TARGET_MODULES, bias="none",
                                             task_type="CAUSAL_LM"))
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.config.use_cache = False
    model.train()
    parameters = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=learning_rate, weight_decay=0.01)

    # Sample a successful trial, then one of its steps: long trials do not dominate.
    by_trial: dict[str, list[dict]] = {}
    for example in examples:
        by_trial.setdefault(example["case_id"], []).append(example)
    trials, generator = sorted(by_trial), random.Random(seed)
    started = time.monotonic()
    for step in range(steps):
        example = generator.choice(by_trial[generator.choice(trials)])
        ids = torch.tensor([example["input_ids"]], device="cuda")
        start = example["target_start"]
        positions = torch.arange(start - 1, ids.shape[1] - 1, device="cuda")
        logits = model(input_ids=ids, attention_mask=torch.ones_like(ids),
                       logits_to_keep=positions, use_cache=False).logits
        loss = functional.cross_entropy(logits[0].float(), ids[0, start:])
        loss.backward()
        norm = float(torch.nn.utils.clip_grad_norm_(parameters, 1.0))
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        log({"step": step + 1, "loss": float(loss.detach()), "gradient_norm": norm,
             "tokens": ids.shape[1], "target_tokens": example["target_tokens"],
             "peak_gib": torch.cuda.max_memory_allocated() / 2**30,
             "elapsed_s": round(time.monotonic() - started, 1)})
        del loss, logits, ids
    return model


def train_and_merge(tag: str, steps: int, learning_rate: float, seed: int, max_tokens: int,
                    merge: bool):
    """Train on /adapters/rft/rft_tokens.jsonl; write /adapters/<tag>/{adapter,merged}."""
    import json
    from pathlib import Path

    rows = [json.loads(line) for line in Path("/adapters/rft/rft_tokens.jsonl").read_text().splitlines()]
    examples = [r for r in rows if len(r["input_ids"]) <= max_tokens]
    print(json.dumps({"examples": len(examples), "dropped_over_max_tokens": len(rows) - len(examples),
                      "trials": len({e["case_id"] for e in examples})}), flush=True)
    history = []

    def log(row):
        history.append(row)
        print(json.dumps(row), flush=True)

    model = train(examples, steps, learning_rate, seed, log)
    output = Path("/adapters") / tag
    model.save_pretrained(str(output / "adapter"))
    (output / "training.jsonl").write_text("".join(json.dumps(r) + "\n" for r in history))
    adapters.commit()
    del model
    if merge:
        from huggingface_hub import snapshot_download
        from merge_lora import merge_into_shards
        source = Path(snapshot_download(MODEL, revision=REVISION))
        merged = merge_into_shards(source, output / "adapter", output / "merged")
        adapters.commit()
        print(json.dumps({"merged_weights": merged}), flush=True)


RUNNER = dict(image=image, timeout=6 * 3600, memory=200 * 1024,
              volumes={"/root/.cache/huggingface": weights, "/adapters": adapters})


@app.function(gpu="H200", **RUNNER)
def train_h200(steps: int, learning_rate: float, seed: int, max_tokens: int, merge: bool):
    """141 GB: long OpenCode prompts fit. FLA's backward runs through tilelang on Hopper."""
    train_and_merge(TAG, steps, learning_rate, seed, max_tokens, merge)


@app.function(gpu="A100-80GB", **RUNNER)
def train_a100(steps: int, learning_rate: float, seed: int, max_tokens: int, merge: bool):
    """The GPU the earlier pilots used; shorter prompts only."""
    train_and_merge("rft-a100", steps, learning_rate, seed, max_tokens, merge)


@app.local_entrypoint()
def main(gpu: str = "h200", steps: int = 160, learning_rate: float = 1e-4, seed: int = 42,
         max_tokens: int = 40000, merge: bool = True):
    runner = {"h200": train_h200, "a100": train_a100}[gpu]
    runner.remote(steps, learning_rate, seed, max_tokens, merge)
