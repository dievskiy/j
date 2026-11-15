"""Facts shared by the deck's scripts: palette, the pending round-2 result, and each
slide's narration, timing and sources. Edit here, then rerun make_charts.py and
build_deck.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Fine-tuning round 2 is still being evaluated. When it is in, set the mean reward
# (a float, drawn as a bar) and the text shown on slide 9.
ROUND_2_MEAN: float | None = None
ROUND_2_TEXT = "[ROUND 2: TBD]"

BACKGROUND = "#0d1119"
PANEL = "#151b28"
GRID = "#2a3345"
INK = "#eef1f6"
INK_SECONDARY = "#aab2c2"
INK_MUTED = "#7b869b"
REFERENCE = "#199e70"
DEEPSEEK = "#3987e5"
INKLING = "#d95926"
BASELINE = "#7d8696"
TUNED = "#9085e9"

JOBS_INKLING = "jobs/eval-inkling-20261115-005608"
JOBS_DEEPSEEK = "jobs/eval-deepseek-20261115-005638"
ROVER_INKLING = f"{JOBS_INKLING}/rover-fork_mud_ice_wind-seed9000__iGPKtYU"
ROVER_DEEPSEEK = f"{JOBS_DEEPSEEK}/rover-fork_mud_ice_wind-seed9000__W5vkMLh"
WINCH_INKLING = f"{JOBS_INKLING}/winch-barrier-seed90005__GHdkTJo"
WINCH_DEEPSEEK = f"{JOBS_DEEPSEEK}/winch-barrier-seed90005__RSrt5rc"
EXPLOIT_INKLING = f"{JOBS_INKLING}/rover-fork_mud_ice-seed90002__e9TA84d"


@dataclass(frozen=True)
class Slide:
    title: str
    seconds: int
    narration: str
    assets: tuple = ()
    sources: tuple = field(default_factory=tuple)   # trial directories, step ids, data files


SLIDES = (
    Slide(
        "Test, then act", 8,
        "Frontier agents ace benchmarks. Put one in charge of an unfamiliar machine, and it "
        "must test before it acts.",
        ("rover_hero.jpg",),
        (f"{ROVER_INKLING}: replayed, frame at t = 86.5 s (after step 10, the last drive_to)",),
    ),
    Slide(
        "Same map. Hidden physics. A cheap test. A fixed budget.", 14,
        "Two MuJoCo worlds. A rover must find the one passable lane; a hoist, the one "
        "liftable crate. The map never says which. A cheap test does, and the budget allows "
        "that test, not a wrong guess.",
        ("rover_course.jpg", "winch_deepseek_2_carry.jpg"),
        (f"{ROVER_INKLING}: course at t = 0",
         f"{WINCH_DEEPSEEK}: frame at t = 26.5 s (step 17, move_trolley)",
         "README.md, ENVIRONMENTS.md: hidden properties, tests, reward rule"),
    ),
    Slide(
        "The agent touches the simulator only through tools", 10,
        "Agents reach the simulator only through MCP tools, under Harbor and OpenCode. "
        "Reward comes from simulator state alone. Doing nothing, or stopping early, scores "
        "zero.",
        ("harness.svg",),
        ("README.md (Reward); results/stop_early.json; jobs/eval-do-nothing-*",),
    ),
    Slide(
        "Every run lands far below the reference", 12,
        "On seventy-five frozen tasks, our scripted reference, using the same tools, "
        "delivers every time. DeepSeek delivers forty-five percent. Inkling, twelve. Three "
        "runs each, and every run is far below the reference.",
        ("results_bar.svg",),
        ("results/final_table.md; harbor_tasks/compare.py (paired difference, McNemar)",),
    ),
    Slide(
        "Tests, then ignores the evidence", 19,
        "Why? Same task, two agents. Inkling crawls across the mud sample for fifty "
        "seconds, decides it is not on mud, then drives into the mud lane and stalls. "
        "DeepSeek gets stuck on the same sample, calls the mud impassable, and takes the "
        "ice lane home.",
        ("rover_paths.svg", "rover_inkling_1_strip.jpg", "rover_inkling_2_fork.jpg",
         "rover_inkling_3_stuck.jpg", "rover_deepseek_1_strip.jpg", "rover_deepseek_2_ice.jpg",
         "rover_deepseek_3_goal.jpg"),
        (f"{ROVER_INKLING}: frames at t = 20 s (step 4), 72.6 s (step 10), 86.5 s (step 10); "
         "quotes from steps 7, 8 and 10",
         f"{ROVER_DEEPSEEK}: frames at t = 17 s (step 10), 43 s (step 21), 59.36 s (step 26); "
         "quote from step 12",
         "task: harbor_tasks/eval_tasks/rover-fork_mud_ice_wind-seed90001 (hidden mode ice_open)"),
    ),
    Slide(
        "The test that breaks the thing it measures", 17,
        "On the hoist, a careless test breaks what it measures. Inkling weighs a crate with "
        "one long pull. The tension stop is a trigger, not a cap, and the cable snaps in "
        "under two seconds. DeepSeek weighs in short pulls and delivers.",
        ("winch_tension.svg", "winch_inkling_1_hooked.jpg", "winch_inkling_2_snapped.jpg",
         "winch_deepseek_1_weigh.jpg", "winch_deepseek_3_delivered.jpg"),
        (f"{WINCH_INKLING}: frames at t = 12.0 s and 13.33 s (step 9, the winch call); "
         "quote from step 9; map note from step 2",
         f"{WINCH_DEEPSEEK}: frames at t = 16.2 s (step 15) and 47.5 s (step 28); "
         "weighing pulls are steps 11 and 13",
         "task: harbor_tasks/eval_tasks/winch-barrier-seed90005 (hidden mode HLR_soft)"),
    ),
    Slide(
        "Looking for a shortcut instead of solving the task", 13,
        "After failing, Inkling hunts for a shortcut. It reads the result file, then opens "
        "a fresh session with curl. Same ended episode; read-only result. Nearly a thousand "
        "such calls, and none earned reward.",
        ("exploit_crash.jpg",),
        (f"{EXPLOIT_INKLING}: trace from steps 22, 23, 34, 36, 39 and 41; frame at "
         "t = 39.64 s (step 11, the crash)",
         "presentation/analysis.md: shell / filesystem use table (117 trials, 986 calls)"),
    ),
    Slide(
        "Not one-offs: the failures are decisions", 11,
        "These are not one-offs. After testing, DeepSeek enters the open lane ninety-four "
        "percent of the time; Inkling, sixty. Chance is forty-six. The map held everything "
        "they needed.",
        (),
        ("presentation/analysis.md: final numbers table; map quotes from get_map (step 2 of "
         f"{ROVER_INKLING} and {WINCH_INKLING})",),
    ),
    Slide(
        "Fine-tuning a smaller model did not help", 9,
        "We also fine-tuned a small Qwen model on its own successful episodes. Honestly, it "
        "did not improve. A second round is being evaluated.",
        ("qwen_finetune.svg",),
        ("README.md (Training a smaller model); finetune/README.md",),
    ),
    Slide(
        "Test before you commit", 7,
        "One command reproduces all of it. Test before you commit: a gap that comes from "
        "decisions, not tricks.",
        ("rover_deepseek_3_goal.jpg",),
        (f"{ROVER_DEEPSEEK}: frame at t = 59.36 s; README.md (Reproduce)",),
    ),
)
