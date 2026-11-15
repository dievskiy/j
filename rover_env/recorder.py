"""Record an Episode to an mp4 without slowing the simulation.

The simulation thread only copies (qpos, qvel) snapshots into a queue; a background
thread renders them with its own MjData and GL context and streams frames to ffmpeg.
The file is a fragmented mp4, so it stays playable even if the episode is never
finished. Recording never touches the reward path.

Rendering can lag behind the simulation. The file is complete once `<path>.done`
exists; creating `<path>.stop` asks the renderer to finish what is queued and close,
which is how an episode that never called finish() gets a complete video.

    rec = Recorder(ep, "rollout.mp4")   # then use ep normally
    ...
    rec.close()                          # also called automatically after finish()

It works for any episode class that has `model`, `data`, `t`, `reward()`, `outcome()`,
a per-physics-step method and tool methods; the defaults suit the rover.
"""
from __future__ import annotations

import copy
import math
import os
import queue
import threading

FPS = 10
STEPS_PER_FRAME = 20          # 20 physics steps of 5 ms = 0.1 s of simulated time per frame
W, H = 480, 360
HOLD_AFTER_CALL = 5           # still frames after each tool call so its result is readable
ROVER_TOOLS = ("drive_to", "brake", "wait", "finish")


def rover_views(ep, data) -> list:
    """Overview of the course and a chase camera behind the rover."""
    x, y, z = data.qpos[:3]
    R = data.xmat[ep._rover].reshape(3, 3)
    yaw = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    return [ep._lay.overview_camera,
            {"lookat": (x, y, z), "distance": 10.0, "elevation": -35.0, "azimuth": yaw}]


class Recorder:
    def __init__(self, ep, path: str, step_method: str = "_substep", tools: tuple = ROVER_TOOLS,
                 steps_per_frame: int = STEPS_PER_FRAME, views=rover_views):
        """`step_method` is the episode method called once per physics step, `tools` the
        methods that advance time or end the episode (the last one must be finish), and
        `views(ep, data)` returns the two camera dicts to draw side by side."""
        self.ep, self.path = ep, path
        self._views = views
        self.error = None
        self._q: queue.Queue = queue.Queue()
        self._label = "start"
        self._n = 0
        self._closed = False
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

        original_step = getattr(ep, step_method)
        def step(*a, **k):
            r = original_step(*a, **k)
            self._n += 1
            if self._n % steps_per_frame == 0:
                self._snap()
            return r
        setattr(ep, step_method, step)

        for name in tools:
            setattr(ep, name, self._wrap(name, getattr(ep, name)))
        self._snap(HOLD_AFTER_CALL)

    def _wrap(self, name, fn):
        def call(*a, **k):
            args = ", ".join([f"{v}" for v in a] + [f"{kk}={vv}" for kk, vv in k.items()])
            self._label = f"{name}({args})"
            res = fn(*a, **k)
            extra = ""
            if name == "finish":
                o = self.ep.outcome()
                extra = f"  reward={self.ep.reward():.3f}  {o.get('reason', '')}"
            self._label = f"{name}({args}) -> {res.get('termination')}{extra}"
            self._snap(HOLD_AFTER_CALL * (4 if name == "finish" else 1))
            if name == "finish":
                self.close(wait_s=0.0)      # do not hold up the tool call; see `.done`
            return res
        return call

    def _snap(self, repeat: int = 1):
        if self._closed:
            return
        d = self.ep.data
        self._q.put((d.qpos.copy(), d.qvel.copy(), d.mocap_pos.copy(),
                     self.ep.model.tendon_rgba.copy(), self.ep.t, self._label, repeat))

    def close(self, wait_s: float = 60.0):
        """Flush and finalise the file. Waits up to wait_s for the renderer to catch up;
        if it has not, rendering continues in the background and `<path>.done` appears later."""
        if not self._closed:
            self._closed = True
            self._q.put(None)
        self._thread.join(wait_s)

    def _render_loop(self):
        try:
            import imageio.v2 as imageio
            import mujoco
            import numpy as np
            from PIL import Image, ImageDraw

            ep = self.ep
            model = copy.copy(ep.model)      # own copy: the simulation may recolour its model
            data = mujoco.MjData(model)
            renderer = mujoco.Renderer(model, H, W)
            writer = imageio.get_writer(
                self.path, fps=FPS, quality=7, macro_block_size=8,
                output_params=["-g", "20", "-movflags", "frag_keyframe+empty_moov+default_base_moof"])
            while True:
                try:
                    item = self._q.get(timeout=0.5)
                except queue.Empty:
                    if os.path.exists(self.path + ".stop"):
                        break
                    continue
                if item is None:
                    break
                qpos, qvel, mocap_pos, tendon_rgba, t, label, repeat = item
                data.qpos[:], data.qvel[:] = qpos, qvel
                data.mocap_pos[:] = mocap_pos
                model.tendon_rgba[:] = tendon_rgba
                mujoco.mj_forward(model, data)
                im = Image.new("RGB", (2 * W, H))
                for i, view in enumerate(self._views(ep, data)):
                    cam = mujoco.MjvCamera()
                    cam.lookat[:] = view["lookat"]
                    cam.distance, cam.elevation, cam.azimuth = (
                        view["distance"], view["elevation"], view["azimuth"])
                    renderer.update_scene(data, cam)
                    im.paste(Image.fromarray(renderer.render()), (W * i, 0))
                dr = ImageDraw.Draw(im)
                dr.rectangle([0, 0, 2 * W, 20], fill=(0, 0, 0))
                dr.text((6, 4), f"t={t:6.2f}s  {label}"[:150], fill=(255, 255, 255))
                frame = np.asarray(im)
                for _ in range(repeat):
                    writer.append_data(frame)
            writer.close()
        except Exception as e:  # recording is optional and never affects the episode
            self.error = repr(e)
        finally:
            try:
                with open(self.path + ".done", "w") as f:
                    f.write(self.error or "ok")
            except OSError:
                pass
