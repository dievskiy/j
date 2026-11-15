"""Merge a LoRA adapter trained on Qwen3_5ForCausalLM into the original Qwen3.6 shards.

    .venv/bin/python merge_lora.py --adapter outputs/rft_h200/adapter --out outputs/rft_merged

Writes a full checkpoint (same files, same tensor names and dtypes) with
W += (alpha / r) * B @ A for every adapted module, so vLLM serves the tuned model with
exactly the flags it uses for the base model.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import save_file

MODEL = "Qwen/Qwen3.6-27B"
REVISION = "8f33b98937c6031bb49e713dee3e8e185aafd26f"
ADAPTER_PREFIX = "base_model.model.model."      # PEFT on the text-only CausalLM
CHECKPOINT_PREFIX = "model.language_model."     # the multimodal checkpoint vLLM loads


def load_deltas(adapter_dir: Path) -> tuple[dict[str, dict[str, torch.Tensor]], float]:
    """Checkpoint weight name -> {"A": lora_A, "B": lora_B}, and the LoRA scale."""
    config = json.loads((adapter_dir / "adapter_config.json").read_text())
    deltas: dict[str, dict[str, torch.Tensor]] = {}
    with safe_open(str(adapter_dir / "adapter_model.safetensors"), "pt") as adapter:
        for key in adapter.keys():
            module, part = key.removeprefix(ADAPTER_PREFIX).rsplit(".lora_", 1)
            deltas.setdefault(f"{CHECKPOINT_PREFIX}{module}.weight", {})[part.split(".")[0]] = \
                adapter.get_tensor(key)
    return deltas, config["lora_alpha"] / config["r"]


def merge_into_shards(source_dir: Path, adapter_dir: Path, output_dir: Path) -> int:
    deltas, scale = load_deltas(adapter_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    merged = 0
    for path in sorted(source_dir.iterdir()):
        if path.suffix != ".safetensors":
            shutil.copy(path, output_dir / path.name)
            continue
        tensors = {}
        with safe_open(str(path), "pt") as shard:
            metadata = shard.metadata()
            for key in shard.keys():
                tensor = shard.get_tensor(key)
                if key in deltas:
                    a, b = deltas[key]["A"].float(), deltas[key]["B"].float()
                    tensor = (tensor.float() + scale * (b @ a)).to(tensor.dtype)
                    merged += 1
                tensors[key] = tensor
        save_file(tensors, str(output_dir / path.name), metadata=metadata)
    if merged != len(deltas):
        raise RuntimeError(f"merged {merged} of {len(deltas)} adapted weights")
    return merged


def local_snapshot() -> Path:
    return Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3.6-27B/snapshots" / REVISION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source", default=str(local_snapshot()))
    args = parser.parse_args()
    merged = merge_into_shards(Path(args.source), Path(args.adapter), Path(args.out))
    print(json.dumps({"merged_weights": merged, "out": args.out}))


if __name__ == "__main__":
    main()
