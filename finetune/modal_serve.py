"""Serve Qwen3.6-27B (and later its tuned LoRA adapter) with vLLM on Modal.

    /root/modal-venv/bin/modal deploy modal_serve.py

OpenAI-compatible endpoints, guarded by the `qwen-vllm-key` secret:
  https://<workspace>--qwen-vllm-serve.modal.run/v1        model `qwen-base`
The tuned model is served by `modal_serve_tuned.py` with identical flags, so the two
differ only in weights.
"""
import os
import subprocess

import modal

MODEL = "Qwen/Qwen3.6-27B"
VLLM_VERSION = "0.32.0"
MAX_MODEL_LEN = 65536
PORT = 8000

image = (modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.12")
         .entrypoint([])
         .uv_pip_install(f"vllm=={VLLM_VERSION}", "huggingface_hub[hf_transfer]")
         .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "VLLM_ALLOW_RUNTIME_LORA_UPDATING": "True"}))
weights = modal.Volume.from_name("qwen-hf-cache", create_if_missing=True)
adapters = modal.Volume.from_name("qwen-adapters", create_if_missing=True)
app = modal.App("qwen-vllm")


def vllm_command(model_path: str, served_name: str) -> list[str]:
    """Identical server flags for the base and the tuned model."""
    return ["vllm", "serve", model_path, "--served-model-name", served_name,
               "--host", "0.0.0.0", "--port", str(PORT),
               "--api-key", os.environ["VLLM_API_KEY"],
               "--max-model-len", str(MAX_MODEL_LEN), "--language-model-only",
               "--reasoning-parser", "qwen3",
               "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder",
               # FlashAttention-3 crashed while capturing CUDA graphs at engine start.
               "--attention-backend", "FLASHINFER"]


SERVER = dict(image=image, gpu="H100", timeout=24 * 3600, scaledown_window=20 * 60,
              volumes={"/root/.cache/huggingface": weights, "/adapters": adapters},
              secrets=[modal.Secret.from_name("qwen-vllm-key")])


@app.function(**SERVER)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=PORT, startup_timeout=40 * 60)
def serve():
    subprocess.Popen(vllm_command(MODEL, "qwen-base"))
