"""
GA settings.

Two kinds live here:
  * plain module constants that other code imports (FORMAT, UID_MAX, output dirs);
  * GAConfig — the environment / tuning knobs of the fitness environment, read
    from the environment ONCE, at import, into DEFAULT (same timing as before the
    package split, so a variable must be set before the process starts).

Per-run parameters (population size, generations, migration cadence, ...) are
deliberately NOT here: they stay keyword arguments of run_islands.

Every tuning value was hand-tuned against the Reg M-C pool. Changing one changes
GA *behavior*, not correctness.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from src.paths import output_path, showdown_dir

FORMAT = "gen9championsvgc2026regmc"   # canonical format registry; battle.py callers pass this in
UID_MAX = 10**9   # upper bound of the random per-battle account id space

CHECKPOINT_DIR = output_path("checkpoints", "v6")
CHAMPION_DIR = output_path("champions")


@dataclass(frozen=True)
class GAConfig:
    # --- Battle harness ---
    # Seconds before a battle is abandoned as hung (returns None, not a loss).
    battle_timeout: int = 20
    # Battles ending < 3 turns are almost always a Showdown desync/forfeit, not a
    # real game — discard so they don't poison the fitness signal.
    # (The retry-uid stride lives in src/battle.py — RETRY_STRIDE there.)
    min_turns: int = 3

    # Who plays in the fitness battles. Our side: "vgc" = VGCPilot (turn_sim on by
    # default: +4.5 pts over the plain heuristic in paired runs); the opponent:
    # "ladder" = heuristic + Protect / Fake Out at replay rates.
    # GA_PILOT=heuristic GA_OPP=heuristic reproduces the pre-2026-10-16 environment
    # (scores are NOT comparable).
    fitness_pilot: str = "vgc"      # env GA_PILOT
    fitness_opp: str = "ladder"     # env GA_OPP

    # Fitness = win rate weighted by how much the ladder plays each opponent team
    # (src/meta_weights.py, data/species_ladder_usage.json). GA_META_WEIGHTS=0 gives
    # the plain win rate.
    meta_weights: bool = True       # env GA_META_WEIGHTS ("1" = on)

    # Per-generation opponent sample size. When the train pool is larger than this,
    # each generation samples train_sample_size opponents from the full pool. Keeps
    # per-gen fitness cost bounded as the pool grows.
    train_sample_size: int = 250    # env GA_TRAIN_SAMPLE

    # --- Early-stop ---
    # A genome plays early_stop_min_battles first; if that head score is below
    # early_stop_win_rate we skip the tail. Statistically: at 50 battles the Wilson
    # 95% CI is ~±10 pts, so a genome truly at 30%+ has <1% chance of showing <15%.
    # The abort catches the bottom third of a generation at negligible false-positive
    # risk and saves ~85% of the wall time for those genomes.
    early_stop_min_battles: int = 50    # only meaningful when the pool is larger than this.
    early_stop_win_rate: float = 0.15   # abort when head score < this.

    # --- Showdown server the GA bounces every `showdown_restart_every` gens ---
    showdown_port: int = 8000                              # env SHOWDOWN_PORT
    showdown_dir: str = field(default_factory=showdown_dir)  # env SHOWDOWN_DIR

    @classmethod
    def from_env(cls, env=None) -> GAConfig:
        """Build a config from environment variables (os.environ by default)."""
        env = os.environ if env is None else env
        return cls(
            fitness_pilot=env.get("GA_PILOT", "vgc"),
            fitness_opp=env.get("GA_OPP", "ladder"),
            meta_weights=env.get("GA_META_WEIGHTS", "1") == "1",
            train_sample_size=int(env.get("GA_TRAIN_SAMPLE", "250")),
            showdown_port=int(env.get("SHOWDOWN_PORT", "8000")),
            showdown_dir=env.get("SHOWDOWN_DIR") or showdown_dir(),
        )


DEFAULT = GAConfig.from_env()
