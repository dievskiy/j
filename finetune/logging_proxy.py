"""Record every chat completion OpenCode exchanges with the Qwen endpoint.

    QWEN_API_KEY=... .venv/bin/python logging_proxy.py --upstream https://...modal.run/v1 \
        --log data/rollouts/requests.jsonl --port 9100

Forwards /v1/* unchanged (streaming included) and appends one JSON line per completion:
the exact request body and the reassembled assistant message. These are the on-policy
training examples; `rollout_dataset.py` joins them to Harbor rewards by tool-call id.
"""
from __future__ import annotations

import argparse
import json
import os
import time

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route


class AssistantMessage:
    """Reassembles an assistant message from streamed chat-completion chunks."""

    def __init__(self):
        self.content, self.reasoning = [], []
        self.tool_calls: dict[int, dict] = {}
        self.finish_reason = None
        self.usage = None

    def add_chunk(self, chunk: dict):
        self.usage = chunk.get("usage") or self.usage
        for choice in chunk.get("choices", []):
            self.finish_reason = choice.get("finish_reason") or self.finish_reason
            delta = choice.get("delta") or choice.get("message") or {}
            self.content.append(delta.get("content") or "")
            self.reasoning.append(delta.get("reasoning_content") or delta.get("reasoning") or "")
            for call in delta.get("tool_calls") or []:
                slot = self.tool_calls.setdefault(call.get("index", len(self.tool_calls)),
                                                  {"id": "", "type": "function",
                                                   "function": {"name": "", "arguments": ""}})
                slot["id"] = call.get("id") or slot["id"]
                function = call.get("function") or {}
                slot["function"]["name"] += function.get("name") or ""
                slot["function"]["arguments"] += function.get("arguments") or ""

    def to_dict(self) -> dict:
        message = {"role": "assistant", "content": "".join(self.content)}
        if any(self.reasoning):
            message["reasoning_content"] = "".join(self.reasoning)
        if self.tool_calls:
            message["tool_calls"] = [self.tool_calls[i] for i in sorted(self.tool_calls)]
        return {"message": message, "finish_reason": self.finish_reason, "usage": self.usage}


def make_app(upstream: str, upstream_key: str, client_key: str, log_path: str) -> Starlette:
    # Modal answers 303 when a request waits over ~150 s (e.g. a cold start); follow it.
    client = httpx.AsyncClient(timeout=httpx.Timeout(1800.0, connect=60.0), follow_redirects=True)

    def record(body: dict, reply: AssistantMessage, started: float):
        with open(log_path, "a") as log:
            log.write(json.dumps({"time": started, "seconds": time.time() - started,
                                  "request": body, **reply.to_dict()}) + "\n")

    async def forward(request: Request):
        if request.headers.get("authorization") != f"Bearer {client_key}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        path = request.path_params["path"]
        headers = {"Authorization": f"Bearer {upstream_key}", "Content-Type": "application/json"}
        if request.method == "GET":
            reply = await client.get(f"{upstream}/{path}", headers=headers)
            return Response(reply.content, reply.status_code, media_type="application/json")
        body = await request.json()
        started = time.time()
        if not body.get("stream"):
            reply = await client.post(f"{upstream}/{path}", headers=headers, json=body)
            if path.endswith("chat/completions") and reply.status_code == 200:
                message = AssistantMessage()
                message.add_chunk(reply.json())
                record(body, message, started)
            return Response(reply.content, reply.status_code, media_type="application/json")

        upstream_request = client.build_request("POST", f"{upstream}/{path}", headers=headers, json=body)
        reply = await client.send(upstream_request, stream=True)
        if reply.status_code != 200:
            content = await reply.aread()
            await reply.aclose()
            return Response(content, reply.status_code, media_type="application/json")

        async def relay():
            message, buffer = AssistantMessage(), ""
            try:
                async for text in reply.aiter_text():
                    yield text
                    buffer += text
                    *lines, buffer = buffer.split("\n")
                    for line in lines:
                        data = line[len("data:"):].strip() if line.startswith("data:") else ""
                        if data and data != "[DONE]":
                            message.add_chunk(json.loads(data))
            finally:
                await reply.aclose()
                record(body, message, started)

        return StreamingResponse(relay(), media_type="text/event-stream")

    return Starlette(routes=[Route("/v1/{path:path}", forward, methods=["GET", "POST"])])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
    key = os.environ["QWEN_API_KEY"]
    uvicorn.run(make_app(args.upstream.rstrip("/"), key, key, args.log), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
