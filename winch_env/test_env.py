"""Tests for the winch yard.

    python -m winch_env.test_env        (or: python -m pytest winch_env/test_env.py)
"""
from __future__ import annotations

import json

from .env import Episode
from .policies import POLICIES, ToolProxy
from .world import MODES, REFERENCE_MASS_KG, SPEC, VARIATIONS, generate, mode_for_seed, public_map


def _run(policy: str, seed: int) -> Episode:
    episode = Episode(seed)
    POLICIES[policy](ToolProxy(episode))
    return episode


def test_deterministic():
    assert _run("reference", 3).outcome() == _run("reference", 3).outcome()


def test_hidden_values_never_reach_the_agent():
    episode = _run("nearest_careful", 1)
    seen = json.dumps(episode.observe())
    scenario = episode.scenario
    assert scenario.mode not in seen
    assert f"{scenario.cable_stiffness:.1f}" not in seen
    assert "sensor_offset" not in seen
    for mass in scenario.crate_mass:
        assert f"{mass:.2f}" not in seen
    assert "crate_mass" not in seen and "cable_stiffness" not in seen


def test_every_regime_occurs():
    assert {mode_for_seed(seed) for seed in range(300)} == set(MODES)


def test_overloading_snaps_the_cable():
    episode = _run("nearest_fast", next(s for s in range(50) if mode_for_seed(s)[2] == "H"))
    assert episode.cable_snapped and episode.reward() == 0.0


def test_light_crate_does_not_count():
    seed = next(s for s in range(50) if mode_for_seed(s)[2] == "L")     # nearest crate is light
    episode = _run("nearest_careful", seed)
    assert episode.reward() == 0.0
    assert episode.outcome()["reason"] == "delivered crate is below the required payload"


def test_tension_reading_matches_weight():
    episode = Episode(0)
    tools = ToolProxy(episode)
    m = tools.observe()["map"]
    crate = m["crates"][2]
    tools.move_trolley(crate["x"], 2.0, 30.0)
    tools.winch(tools.observe()["hook"]["height"] - crate["lug_height"], 1.0, 30.0)
    assert tools.attach()["termination"] == "attached"
    tools.winch(-0.6, 0.05, 30.0, stop_tension=0.9 * SPEC["cable_rated_tension_n"])
    tools.wait(1.0)
    expected = episode.scenario.crate_mass[2] * 9.81 + episode.scenario.sensor_offset
    assert abs(tools.observe()["tension"] - expected) < 60.0


def test_slack_reading_is_the_sensor_offset():
    episode = Episode(4)
    assert abs(episode.observe()["tension"] - episode.scenario.sensor_offset) < 40.0


def test_releasing_a_hovering_crate_and_finishing_scores_zero():
    """A crate must sit on the platform, released and still, before it counts."""
    seed = next(s for s in range(60) if mode_for_seed(s)[2] == "R")      # nearest crate is right
    episode = Episode(seed)
    tools = ToolProxy(episode)
    m = tools.observe()["map"]
    crate = max(m["crates"], key=lambda c: c["x"])
    tools.move_trolley(crate["x"], 2.0, 30.0)
    tools.winch(tools.observe()["hook"]["height"] - crate["lug_height"], 1.0, 30.0)
    tools.attach()
    tools.winch(-0.5, 0.03, 60.0)
    tools.winch(-2.2, 1.0, 30.0)
    tools.move_trolley(m["goal"]["x"], 0.5, 40.0)
    tools.wait(8.0)
    tools.finish()                       # still on the hook, hovering over the goal
    assert episode.reward() == 0.0


def test_hidden_salt_changes_hidden_values_only():
    import os
    from .world import generate
    plain = generate(7)
    os.environ["WINCH_HIDDEN_SALT"] = "12345"
    try:
        salted = generate(7)
    finally:
        del os.environ["WINCH_HIDDEN_SALT"]
    assert plain.crate_x == salted.crate_x
    assert plain.crate_mass != salted.crate_mass


def test_integrity_baselines_score_zero():
    for policy in ("do_nothing", "immediate_finish", "wait_spam", "random_actions",
                   "invalid_inputs", "drop_on_goal"):
        for seed in (0, 1, 2):
            assert _run(policy, seed).reward() == 0.0, (policy, seed)


def test_reference_delivers():
    for seed in range(12):
        assert _run("reference", seed).reward() > 0.5, seed


def test_variation_maps_are_independent_of_hidden_salt():
    import os
    for name in VARIATIONS:
        plain = generate(3, variation=name)
        old_salt = os.environ.get("WINCH_HIDDEN_SALT")
        os.environ["WINCH_HIDDEN_SALT"] = "721"
        try:
            salted = generate(3, variation=name)
        finally:
            if old_salt is None:
                os.environ.pop("WINCH_HIDDEN_SALT", None)
            else:
                os.environ["WINCH_HIDDEN_SALT"] = old_salt
        assert public_map(plain) == public_map(salted), name
        assert plain.crate_mass != salted.crate_mass, name
        seen = json.dumps(Episode(3, variation=name).observe())
        for mass in plain.crate_mass:
            if mass != REFERENCE_MASS_KG:  # the reference mass is deliberately public
                assert f"{mass:.3f}" not in seen, name
        assert f"{plain.cable_stiffness:.3f}" not in seen
        assert f"{plain.sensor_gain:.5f}" not in seen or plain.sensor_gain == 1.


def test_variations_record_their_hidden_regime():
    for name in VARIATIONS:
        for seed in range(6):
            sc = generate(seed, variation=name)
            bands, cable, *condition = sc.mode.split("_")
            assert condition in ([], ["worn"], ["intact"], ["stuck"], ["free"]), (name, sc.mode)
            assert cable in ("soft", "stiff"), (name, sc.mode)
            assert len(bands) == sum(1 for c in public_map(sc)["crates"] if c["cargo"]), (name, sc.mode)
            assert set(bands) <= set("LRMH"), (name, sc.mode)


def test_variation_maps_state_no_procedure():
    for name in VARIATIONS:
        text = json.dumps(public_map(generate(0, variation=name))).lower()
        for hint in ("slow, tension-limited", "calibrate", "with slack cable before"):
            assert hint not in text, (name, hint)


def test_only_a_worn_cable_creeps():
    """Holding 1200 N on a crate too heavy to lift relaxes a worn cable's tension (creep)
    but not an intact one's; the default yard never creeps."""
    from .policies import WORN_SAFE_STOP_N, _held_tension_relaxed, _hook_onto, estimate_stiffness, read_sensor_offset, weigh
    assert generate(0).creep_onset_n is None
    seen = set()
    for seed in range(12):
        sc = generate(seed, variation="worn_cable")
        worn = sc.mode.endswith("_worn")
        if worn in seen:
            continue
        seen.add(worn)
        env = ToolProxy(Episode(seed, variation="worn_cable"))
        m = env.observe()["map"]
        offset = read_sensor_offset(env)
        assert _hook_onto(env, m, m["crates"][sc.mode.index("H")])
        assert weigh(env, m, estimate_stiffness(env), offset, stop=WORN_SAFE_STOP_N) is None
        assert _held_tension_relaxed(env, offset) == worn, seed
        assert env.observe()["episode"]["ended"] is None
    assert seen == {True, False}


def test_a_stuck_crate_lifts_only_after_a_sideways_tug():
    from .policies import _hook_onto, _let_go, _tug_sideways, estimate_stiffness, read_sensor_offset, weigh
    seed = next(s for s in range(12) if generate(s, variation="stuck_crate").mode.endswith("_stuck"))
    sc = generate(seed, variation="stuck_crate")
    env = ToolProxy(Episode(seed, variation="stuck_crate"))
    m = env.observe()["map"]
    crate = m["crates"][sc.stuck_index]
    offset = read_sensor_offset(env)
    assert _hook_onto(env, m, crate)
    stiffness = estimate_stiffness(env)
    assert weigh(env, m, stiffness, offset) is None              # held down: looks too heavy
    _let_go(env, 0.4)
    _tug_sideways(env, m, crate, offset)
    assert _hook_onto(env, m, crate)
    mass = weigh(env, m, stiffness, offset)
    assert mass is not None and abs(mass - sc.crate_mass[sc.stuck_index]) < 5.0


def test_variations_are_deterministic_and_reference_delivers():
    for name in VARIATIONS:
        first = Episode(0, variation=name)
        second = Episode(0, variation=name)
        POLICIES["reference"](ToolProxy(first))
        POLICIES["reference"](ToolProxy(second))
        assert first.outcome() == second.outcome(), name
        assert first.reward() > 0.5, name


def test_variation_integrity():
    for name in VARIATIONS:
        for policy in ("do_nothing", "immediate_finish", "random_actions",
                       "invalid_inputs", "drop_on_goal"):
            episode = Episode(0, variation=name)
            POLICIES[policy](ToolProxy(episode))
            assert episode.reward() == 0., (name, policy)


def _all():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print("ok  ", test.__name__)
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    _all()
