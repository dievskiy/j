"""Quick tests: determinism, observation hygiene, budgets, integrity baselines.

    python -m rover_env.test_env        (or: python -m pytest rover_env/test_env.py)
"""
from __future__ import annotations

import json
import math

from . import policies as P
from .env import Episode
from .world import HELDOUT_MODES, TRAIN_MODES, generate, split_seeds


def _script(ep):
    m = ep.observe()["map"]
    out = [ep.drive_to(5.0, 1.0, 3.0, 2.0), ep.brake(), ep.wait(0.5)]
    top = m["routes"]["short"][0]
    out.append(ep.drive_to(top[0], top[1], 2.5, 20.0))
    out.append(ep.observe())
    return json.dumps(out, sort_keys=True)


def test_determinism_same_seed():
    for seed in (0, 5, 6):
        a, b = Episode(seed), Episode(seed)
        assert _script(a) == _script(b)
        assert a.energy == b.energy and a.t == b.t


def test_generation_deterministic_and_seed_dependent():
    assert generate(3) == generate(3)
    assert generate(3).layout != generate(4).layout


def test_reference_reproducible():
    for seed in (1, 3, 6):
        r = []
        for _ in range(2):
            ep = Episode(seed)
            P.reference(P.ToolProxy(ep))
            r.append(ep.reward())
        assert r[0] == r[1] and r[0] > 0.5, (seed, r)


def test_observe_is_time_locked_and_hides_mode():
    ep = Episode(5)  # traction+steering
    ep.drive_to(4.0, 0.0, 2.0, 1.0)
    o1, o2 = ep.observe(), ep.observe()
    assert o1 == o2, "repeated observe at the same sim time must return the same sample"
    s = json.dumps(o1).lower()
    h = ep.scenario.hidden
    for word in ("traction", "steering_bias\": %s" % h.steering_bias, "braking", "mode"):
        assert word not in s, word
    assert str(round(h.tire_friction, 3)) not in s


def test_proxy_exposes_only_tools():
    px = P.ToolProxy(Episode(0))
    for name in ("scenario", "_hid", "data", "model", "reward", "outcome", "render_png"):
        try:
            getattr(px, name)
        except AttributeError:
            continue
        raise AssertionError(f"proxy leaks {name}")


def test_invalid_inputs_rejected_without_side_effects():
    ep = Episode(2)
    for name, args in P.BAD_INPUTS:
        r = getattr(ep, name)(*args)
        assert r["termination"] == "invalid_input", (name, args, r)
    assert ep.t == 0.0 and ep.energy == 0.0


def test_integrity_baselines_score_zero():
    for seed in range(6):
        for pol in ("do_nothing", "immediate_finish", "wait_spam", "random_actions", "invalid_inputs"):
            ep = Episode(seed)
            P.POLICIES[pol](P.ToolProxy(ep))
            assert ep.reward() == 0.0, (pol, seed, ep.outcome())


def test_finish_counted_once_and_episode_frozen():
    ep = Episode(6)
    P.always_short(P.ToolProxy(ep))
    r1, t1, e1 = ep.reward(), ep.t, ep.energy
    assert r1 > 0.5
    assert ep.finish()["termination"] == "episode_over"
    assert ep.drive_to(0, 0, 1, 5)["termination"] == "episode_over"
    assert ep.wait(5)["termination"] == "episode_over"
    assert (ep.reward(), ep.t, ep.energy) == (r1, t1, e1)


def test_budget_enforced_inside_loop():
    ep = Episode(0)
    T = ep.scenario.budgets.time_s
    last = None
    for _ in range(10):
        last = ep.wait(60.0)
        if last["termination"] != "waited":
            break
    assert last["termination"] == "time_budget_exhausted"
    assert ep.t <= T + 1e-6
    assert ep.finish()["reward"] == 0.0


def test_energy_monotone_and_reward_in_range():
    ep = Episode(7)
    e_prev = 0.0
    for args in ((3, 0, 2, 2), (6, 2, 3, 3), (0, 0, 1, 5)):
        ep.drive_to(*args)
        assert ep.energy >= e_prev
        e_prev = ep.energy
    ep.finish()
    assert 0.0 <= ep.reward() <= 1.0


def test_splits_disjoint_and_correct():
    sp = split_seeds(40)
    assert not set(sp["train"]) & set(sp["heldout"])
    assert all(generate(s).hidden.mode in TRAIN_MODES for s in sp["train"])
    assert all(generate(s).hidden.mode in HELDOUT_MODES for s in sp["heldout"])


def test_delivery_requires_goal():
    ep = Episode(6)
    ep.drive_to(5.0, 0.0, 2.0, 10.0)   # move, but nowhere near the goal
    r = ep.finish()
    assert r["reward"] == 0.0 and not r["delivered"]


def _all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok  ", f.__name__)
    print(f"{len(fns)} tests passed")


if __name__ == "__main__":
    _all()
