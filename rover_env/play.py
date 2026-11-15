"""Drive the rover by hand in a browser, through the same five tools an agent gets.

    MUJOCO_GL=egl .venv/bin/python -m rover_env.play --port 8081 [--host 0.0.0.0]

Click the map to pick a drive_to target. The winch yard playground is served under
/winch/. The server is single-threaded on purpose: the MuJoCo renderer must stay on
one thread.
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("MUJOCO_GL", "egl")

from winch_env.play import Routes as WinchRoutes  # noqa: E402

from .env import Episode  # noqa: E402
from .world import course_names, scenario_summary  # noqa: E402

PAGE = os.path.join(os.path.dirname(__file__), "play.html")


class Session:
    """One episode at a time, replaced on reset."""

    def __init__(self):
        self.reset("serpentine", 0, 0.5)

    def reset(self, course: str, seed: int, difficulty: float) -> dict:
        self.course, self.seed, self.difficulty = course, seed, difficulty
        self.episode = Episode(seed, difficulty, course)
        return self.state()

    def state(self, last_result: dict | None = None) -> dict:
        observation = self.episode.observe()
        return {"course": self.course, "seed": self.seed, "difficulty": self.difficulty,
                "observation": observation, "last_result": last_result}

    def call(self, tool: str, args: dict) -> dict:
        if tool not in ("drive_to", "brake", "wait", "finish"):
            raise ValueError(f"unknown tool {tool!r}")
        return self.state(getattr(self.episode, tool)(**args))

    def hidden(self) -> dict:
        return scenario_summary(self.episode.scenario)


SESSION = Session()
WINCH = WinchRoutes()
WINCH_PREFIX = "/winch"


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200):
        self._send(json.dumps(payload).encode(), "application/json", status)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == WINCH_PREFIX:                 # relative links need the trailing slash
            self.send_response(301)
            self.send_header("Location", WINCH_PREFIX + "/")
            self.end_headers()
            return
        if url.path.startswith(WINCH_PREFIX + "/"):
            response = WINCH.get(url.path.removeprefix(WINCH_PREFIX))
            return self._send(*response) if response else self._json({"error": "not found"}, 404)
        if url.path == "/":
            with open(PAGE, "rb") as f:
                return self._send(f.read(), "text/html; charset=utf-8")
        if url.path == "/frame.png":
            camera = parse_qs(url.query).get("cam", ["chase"])[0]
            png = SESSION.episode.render_png("overview" if camera == "overview" else "chase", 640, 480)
            return self._send(png or b"", "image/png", 200 if png else 500)
        if url.path == "/api/state":
            return self._json(SESSION.state())
        if url.path == "/api/hidden":
            return self._json(SESSION.hidden())
        if url.path == "/api/courses":
            return self._json({"courses": course_names()})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            path = urlparse(self.path).path
            if path.startswith(WINCH_PREFIX + "/"):
                return self._send(*WINCH.post(path.removeprefix(WINCH_PREFIX), body))
            tool = path.removeprefix("/api/")
            if tool == "reset":
                if body.get("course") not in course_names():
                    raise ValueError(f"course must be one of {course_names()}")
                return self._json(SESSION.reset(body["course"], int(body["seed"]),
                                                float(body.get("difficulty", 0.5))))
            return self._json(SESSION.call(tool, body))
        except (ValueError, TypeError, KeyError) as error:
            self._json({"error": str(error)}, 400)

    def log_message(self, *args):   # keep the terminal quiet
        pass


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args(argv)
    print(f"rover playground on http://{args.host}:{args.port}/, winch yard on /winch/")
    HTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
