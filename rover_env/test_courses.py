"""Tests that every course keeps its promises.

    python -m rover_env.test_courses        (or: python -m pytest rover_env/test_courses.py)
"""
from __future__ import annotations

import json

from . import fork, policies_fork, policies_serpentine
from .env import Episode
from .policies import ToolProxy
from .world import course_names, scenario_summary

NEW_COURSES = [c for c in course_names() if c != "ramp"]
SECRET_KEYS = ("mud_drag", "ice_friction", "wind_accel", "mode")   # never published


def _policies(course):
    return policies_serpentine.POLICIES if course == "serpentine" else policies_fork.POLICIES


def _run(course, policy, seed):
    episode = Episode(seed, 0.5, course)
    _policies(course)[policy](ToolProxy(episode))
    return episode


def test_every_course_is_deterministic():
    for course in NEW_COURSES:
        first, second = _run(course, "reference", 3), _run(course, "reference", 3)
        assert first.outcome() == second.outcome(), course


def test_hidden_values_never_reach_the_agent():
    for course in NEW_COURSES:
        episode = Episode(1, 0.5, course)
        episode.drive_to(2.0, 0.0, 2.0, 3.0)
        seen = json.dumps(episode.observe())
        hidden = scenario_summary(episode.scenario)["hidden"]
        for key in SECRET_KEYS:
            assert f'"{key}"' not in seen, (course, key)
        assert hidden["mode"] not in seen, course
        for _, _, _, mass in getattr(episode.scenario.layout, "crates", ()):
            assert f"{mass:.3f}" not in seen, course


def test_map_is_identical_across_regimes():
    """Two seeds in different regimes must not be distinguishable from the map's hazard
    description: only geometry (which is seeded) may differ."""
    for course in fork.WORLDS:
        by_mode = {}
        for seed in range(40):
            episode = Episode(seed, 0.5, course)
            by_mode.setdefault(episode.scenario.hidden.mode, episode)
        assert len(by_mode) == len(fork.modes(course)), course
        descriptions = {json.dumps([episode.observe()["map"]["hazards"],
                                    [[lane["hazard"] for lane in f["lanes"]]
                                     for f in episode.observe()["map"]["forks"]]], sort_keys=True)
                        for episode in by_mode.values()}
        assert len(descriptions) == 1, course


def test_barriers_are_only_seen_in_range_or_from_the_lookout():
    course = "fork_barrier_mud"
    seed = next(s for s in range(40) if Episode(s, 0.5, course).scenario.layout.barriers)
    episode = Episode(seed, 0.5, course)
    assert episode.observe()["detected_barriers"] == []
    lookout = episode.observe()["map"]["lookout"]
    episode.drive_to(lookout["x"], lookout["y"], 2.5, 30.0)
    assert len(episode.observe()["detected_barriers"]) == 1


def test_integrity_baselines_score_zero_everywhere():
    for course in NEW_COURSES:
        for policy in ("do_nothing", "immediate_finish", "wait_spam", "random_actions",
                       "invalid_inputs"):
            assert _run(course, policy, 2).reward() == 0.0, (course, policy)


def test_reference_delivers_on_every_course():
    for course in NEW_COURSES:
        for seed in (0, 1, 2, 3):
            assert _run(course, "reference", seed).reward() > 0.5, (course, seed)


def _all():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print("ok  ", test.__name__)
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    _all()
