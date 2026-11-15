"""Reward-filtered fine-tuning data: Qwen's own successful steps, exactly as it saw them.

    .venv/bin/python rft_data.py --log data/rollouts/requests.jsonl [more logs...] \
        --jobs ../hackathon_project/jobs/train-qwen-* --out data/rft_tokens.jsonl

Each logged completion is joined to its Harbor trial through the tool-call ids the
server generated (they also appear in the trial's trajectory). Steps from trials whose
verified reward is above zero become training examples: the exact request (messages and
tool definitions) as the prompt, the model's own reasoning and tool call as the target.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from transformers import AutoTokenizer

from merge_lora import MODEL, REVISION


def string_values(value) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(string_values(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(string_values(v) for v in value)) if value else set()
    return set()


def trial_rewards(job_dirs: list[Path]) -> dict[str, tuple[float, set[str]]]:
    """Trial name -> (verified reward, every string in its trajectory)."""
    trials = {}
    for job in job_dirs:
        for trial in sorted(p for p in job.iterdir() if (p / "agent" / "trajectory.json").exists()):
            reward_file = trial / "verifier" / "reward.txt"
            reward = float(reward_file.read_text().strip() or 0) if reward_file.exists() else 0.0
            trajectory = json.loads((trial / "agent" / "trajectory.json").read_text())
            trials[f"{job.name}/{trial.name}"] = (reward, string_values(trajectory))
    return trials


def join(records: list[dict], trials: dict) -> list[dict]:
    """Attach each completion that made a tool call to the trial containing its call id."""
    owner = {}
    for name, (_, strings) in trials.items():
        for value in strings:
            owner.setdefault(value, name)
    joined = []
    for record in records:
        ids = [c["id"] for c in record["message"].get("tool_calls", []) if c.get("id")]
        names = {owner[i] for i in ids if i in owner}
        if len(names) == 1:
            name = names.pop()
            joined.append({**record, "trial": name, "reward": trials[name][0]})
    return joined


def with_parsed_arguments(message: dict) -> dict:
    """vLLM parses JSON-string tool arguments into objects before templating; do the same."""
    if not message.get("tool_calls"):
        return message
    calls = []
    for call in message["tool_calls"]:
        arguments = call["function"].get("arguments")
        if isinstance(arguments, str):
            arguments = json.loads(arguments or "{}")
        calls.append({**call, "function": {**call["function"], "arguments": arguments}})
    return {**message, "tool_calls": calls}


def encode(tokenizer, record: dict, max_tokens: int) -> dict | None:
    """Prompt exactly as vLLM rendered it; target is the model's own message."""
    messages = [with_parsed_arguments(m) for m in record["request"]["messages"]]
    tools = record["request"].get("tools")
    prefix = tokenizer.apply_chat_template(messages, tools=tools, tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages + [with_parsed_arguments(record["message"])],
                                         tools=tools, tokenize=False)
    if not full.startswith(prefix):
        raise ValueError("chat template target does not extend the generation prompt")
    prefix_ids = tokenizer.encode(prefix, add_special_tokens=False)
    target_ids = tokenizer.encode(full[len(prefix):], add_special_tokens=False)
    if len(prefix_ids) + len(target_ids) > max_tokens:
        return None
    return {"input_ids": prefix_ids + target_ids, "target_start": len(prefix_ids),
            "target_tokens": len(target_ids)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", nargs="+", required=True, help="one or more proxy logs")
    parser.add_argument("--jobs", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-tokens", type=int, default=16384)
    args = parser.parse_args()
    records = [json.loads(line) for log in args.log
               for line in Path(log).read_text().splitlines() if line.strip()]
    records = [r for r in records if r["message"].get("tool_calls") and r["finish_reason"] != "length"]
    trials = trial_rewards([Path(j) for j in args.jobs])
    joined = join(records, trials)
    successful = [r for r in joined if r["reward"] > 0]
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
    written, too_long, tools = 0, 0, collections.Counter()
    with Path(args.out).open("w") as output:
        for record in successful:
            example = encode(tokenizer, record, args.max_tokens)
            if example is None:
                too_long += 1
                continue
            tool = record["message"]["tool_calls"][0]["function"]["name"]
            example.update(case_id=record["trial"], tool=tool)
            tools[tool] += 1
            output.write(json.dumps(example, separators=(",", ":")) + "\n")
            written += 1
    rewards = {name: reward for name, (reward, _) in trials.items()}
    summary = {"logged_tool_steps": len(records), "joined_steps": len(joined),
               "trials": len(rewards), "successful_trials": sum(r > 0 for r in rewards.values()),
               "successful_trials_used": len({r["trial"] for r in successful}),
               "examples": written, "dropped_over_context": too_long, "tools": dict(tools),
               "mean_trial_reward": sum(rewards.values()) / max(len(rewards), 1)}
    Path("results").mkdir(exist_ok=True)
    Path("results/rft_data.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
