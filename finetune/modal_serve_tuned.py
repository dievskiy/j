"""Serve the reward-filtered Qwen (LoRA delta merged into the base shards by rft_modal.py).

    /root/modal-venv/bin/modal deploy modal_serve_tuned.py

A separate app from the base server, so deploying it never restarts the base container.
Endpoint https://<workspace>--qwen-vllm-tuned-serve.modal.run/v1, model `qwen-tuned`.
"""
import subprocess

import modal

from modal_serve import PORT, SERVER, vllm_command

TUNED_CHECKPOINT = "/adapters/rft-h200/merged"
app = modal.App("qwen-vllm-tuned")
# The container imports this module, which imports modal_serve: ship that file too.
TUNED_SERVER = {**SERVER, "image": SERVER["image"].add_local_python_source("modal_serve")}


@app.function(**TUNED_SERVER)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=PORT, startup_timeout=40 * 60)
def serve():
    subprocess.Popen(vllm_command(TUNED_CHECKPOINT, "qwen-tuned"))
