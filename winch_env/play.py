"""Operate the winch yard by hand in a browser, through the same tools an agent gets.

    MUJOCO_GL=egl .venv/bin/python -m winch_env.play --port 8082 [--host 0.0.0.0]

The rover playground also serves this page under /winch. Click the side view to pick
a trolley target. The server is single-threaded on purpose: the MuJoCo renderer must
stay on one thread.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

os.environ.setdefault("MUJOCO_GL", "egl")

from .env import Episode  # noqa: E402
from .world import VARIATIONS  # noqa: E402

PAGE = os.path.join(os.path.dirname(__file__), "play.html")
TOOLS = ("move_trolley", "winch", "attach", "release", "wait", "finish")
DEFAULT_YARD = "default"


class Session:
    """One episode at a time, replaced on reset."""

    def __init__(self):
        self.reset(DEFAULT_YARD, 0, 0.5)

    def reset(self, variation: str, seed: int, difficulty: float) -> dict:
        if variation != DEFAULT_YARD and variation not in VARIATIONS:
            raise ValueError(f"variation must be one of {yard_names()}")
        self.variation, self.seed, self.difficulty = variation, seed, difficulty
        self.episode = Episode(seed, difficulty, None if variation == DEFAULT_YARD else variation)
        return self.state()

    def state(self, last_result: dict | None = None) -> dict:
        return {"variation": self.variation, "seed": self.seed, "difficulty": self.difficulty,
                "observation": self.episode.observe(), "last_result": last_result}

    def call(self, tool: str, args: dict) -> dict:
        if tool not in TOOLS:
            raise ValueError(f"unknown tool {tool!r}")
        return self.state(getattr(self.episode, tool)(**args))

    def hidden(self) -> dict:
        """Everything the agent is not told, plus the outcome so far."""
        return dict(asdict(self.episode.scenario), outcome=self.episode.outcome())


def yard_names() -> list:
    return [DEFAULT_YARD, *VARIATIONS]


class Routes:
    """The playground's HTTP routes, relative to wherever it is mounted."""

    def __init__(self):
        self.session = Session()

    def get(self, path: str) -> tuple[bytes, str, int] | None:
        """Returns (body, content type, status), or None if the path is not ours."""
        if path == "/":
            with open(PAGE, "rb") as f:
                return f.read(), "text/html; charset=utf-8", 200
        if path == "/frame.png":
            png = self.session.episode.render_png(800, 450)
            return png or b"", "image/png", 200 if png else 500
        if path == "/api/state":
            return _json(self.session.state())
        if path == "/api/hidden":
            return _json(self.session.hidden())
        if path == "/api/yards":
            return _json({"yards": yard_names()})
        return None

    def post(self, path: str, body: dict) -> tuple[bytes, str, int]:
        try:
            tool = path.removeprefix("/api/")
            if tool == "reset":
                return _json(self.session.reset(body["variation"], int(body["seed"]),
                                                float(body.get("difficulty", 0.5))))
            return _json(self.session.call(tool, body))
        except (ValueError, TypeError, KeyError) as error:
            return _json({"error": str(error)}, 400)


def _json(payload: dict, status: int = 200) -> tuple[bytes, str, int]:
    return json.dumps(payload).encode(), "application/json", status


def make_handler(routes: Routes):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, response: tuple[bytes, str, int]):
            body, content_type, status = response
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(routes.get(urlparse(self.path).path) or _json({"error": "not found"}, 404))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as error:
                return self._send(_json({"error": str(error)}, 400))
            self._send(routes.post(urlparse(self.path).path, body))

        def log_message(self, *args):   # keep the terminal quiet
            pass

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args(argv)
    print(f"winch playground on http://{args.host}:{args.port}/")
    HTTPServer((args.host, args.port), make_handler(Routes())).serve_forever()


if __name__ == "__main__":
    main()
