"""Harbor reference run: play a scripted policy through the task's MCP server.

    python3 oracle.py --course fork_mud_ice [--url http://rover-sim:8000/mcp] [--policy reference]

The policy sees exactly what an agent sees: the MCP tools, nothing else. Uses only the
standard library, so it runs in the bare agent container.
"""
from __future__ import annotations

import argparse
import itertools
import json
import urllib.request

WINCH_COURSE = "winch_yard"
PROTOCOL_VERSION = "2025-06-18"


class McpSession:
    """Minimal JSON-RPC client for one streamable-HTTP MCP session."""

    def __init__(self, url: str):
        self.url = url
        self.session_id: str | None = None
        self._ids = itertools.count(1)
        self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": "initialize",
                    "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                               "clientInfo": {"name": "reference", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name: str, arguments: dict) -> dict:
        reply = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": "tools/call",
                            "params": {"name": name, "arguments": arguments}})
        if "error" in reply:
            raise RuntimeError(f"{name}: {reply['error']}")
        result = reply["result"]
        if result.get("isError"):
            raise RuntimeError(f"{name}: {result['content']}")
        if "structuredContent" in result:
            content = result["structuredContent"]
            return content.get("result", content) if set(content) == {"result"} else content
        return json.loads(result["content"][0]["text"])

    def _post(self, message: dict) -> dict:
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(self.url, json.dumps(message).encode(), headers)
        with urllib.request.urlopen(request, timeout=600) as response:
            self.session_id = response.headers.get("Mcp-Session-Id") or self.session_id
            body = response.read().decode()
        return _parse_body(body)


def _parse_body(body: str) -> dict:
    """A reply is plain JSON or an SSE stream whose last data line holds the JSON."""
    body = body.strip()
    if not body:
        return {}
    if body.startswith("{"):
        return json.loads(body)
    data = [line[len("data:"):].strip() for line in body.splitlines() if line.startswith("data:")]
    return json.loads(data[-1]) if data else {}


class McpTools:
    """The tool surface the scripted policies expect. Their `observe()` returns the map
    together with the readings, so it merges `get_map` (fetched once) into `observe`."""

    def __init__(self, session: McpSession):
        self._session = session
        self._static: dict | None = None

    def observe(self) -> dict:
        if self._static is None:
            self._static = self._session.call_tool("get_map", {})
        readings = self._session.call_tool("observe", {})
        static = self._static if "map" in self._static else {"map": self._static}
        return {**readings, **static}

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            if args:
                raise TypeError(f"{name}: pass tool arguments by keyword")
            return self._session.call_tool(name, {k: v for k, v in kwargs.items() if v is not None})
        return call


class _PositionalTools:
    """Maps the policies' positional calls onto named MCP arguments."""
    PARAMETERS = {
        "drive_to": ("x", "y", "speed_limit", "max_duration"),
        "wait": ("duration",),
        "move_trolley": ("x", "speed_limit", "max_duration"),
        "winch": ("length_change", "speed_limit", "max_duration", "stop_tension"),
    }

    def __init__(self, tools: McpTools):
        self._tools = tools

    def observe(self) -> dict:
        return self._tools.observe()

    def __getattr__(self, name: str):
        names = self.PARAMETERS.get(name, ())

        def call(*args, **kwargs):
            kwargs.update(zip(names, args))
            return getattr(self._tools, name)(**kwargs)
        return call


def policy_for(course: str, name: str):
    if course == WINCH_COURSE:
        from winch_env import policies
        return policies.POLICIES[name]
    if course == "ramp":
        from rover_env import policies
    elif course == "serpentine":
        from rover_env import policies_serpentine as policies
    else:
        from rover_env import policies_fork as policies
    return policies.POLICIES[name]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", required=True)
    parser.add_argument("--url", default="http://rover-sim:8000/mcp")
    parser.add_argument("--policy", default="reference")
    args = parser.parse_args(argv)
    tools = _PositionalTools(McpTools(McpSession(args.url)))
    result = policy_for(args.course, args.policy)(tools)
    print(json.dumps(result)[:2000])


if __name__ == "__main__":
    main()
