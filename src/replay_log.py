"""
Replay logging for GA runs: keep a bounded, deterministic sample of full battle logs.

Enabled in run/ga_island.py with GA_REPLAY_LOG=1. Flow per generation and island:
  1. run_islands calls start_generation(island, gen).
  2. For every genome the Evaluator calls the callback from for_genome(island, gen, idx)
     once, after the genome is scored, with its real fitness and, per battle actually
     played, the outcome (1 / 0 / None) and the Showdown protocol log lines.
  3. Each battle is offered to `keep` (default src/replay_filters.py::default_ga_filter)
     with the real fitness, outcome and species. Kept battles are candidates.
  4. end_generation(island, gen) writes the first `max_per_gen` candidates in
     (genome index, opponent index) order to
     <out_dir>/<run_id>/<island>_gen<NNNN>.jsonl, one JSON object per battle.

Determinism: the random part of the filter (its 2% sample) uses a private
random.Random seeded from (seed, island, gen, genome index, opponent index), never the
global `random` module, so (a) the GA's random stream - and therefore its results - are
identical with logging on or off, and (b) which battles are saved does not depend on
which battles happened to finish first.

Replaces the 2026-10/11 hook (run_battle save_filter/save_callback + DecisionLogger),
which always received fitness 0.0, outcome "unknown", gen 0 and an empty history.
"""
import json
import os
import random

from src.replay_filters import default_ga_filter

OUTCOME = {1: "win", 0: "loss", None: "none"}


class ReplayLogger:
    """Collects candidate battles per (island, generation) and writes a capped sample."""

    def __init__(self, out_dir, run_id, max_per_gen=50, seed=0, keep=default_ga_filter):
        self.out_dir = os.path.join(out_dir, run_id)
        self.run_id = run_id
        self.max_per_gen = max_per_gen
        self.seed = seed
        self.keep = keep
        self._pending = {}          # (island, gen) -> sorted list of (genome_idx, opp_idx, row)
        self.written = {}           # (island, gen) -> rows written (for reporting / tests)

    def _rng(self, island, gen, genome_idx, opp_idx):
        # str seeds are hashed with SHA-512 by random.Random: stable across processes,
        # unaffected by PYTHONHASHSEED.
        return random.Random(f"{self.seed}:{island}:{gen}:{genome_idx}:{opp_idx}")

    def start_generation(self, island, gen):
        self._pending[(island, gen)] = []

    def for_genome(self, island, gen, genome_idx):
        """Callback for Evaluator.evaluate(on_battles=...)."""
        def on_battles(genome, fitness, outcomes, logs):
            self.record(island, gen, genome_idx, genome, fitness, outcomes, logs)
        return on_battles

    def record(self, island, gen, genome_idx, genome, fitness, outcomes, logs):
        """Offer every played battle of one genome to the filter; keep candidates."""
        pending = self._pending.setdefault((island, gen), [])
        species = [m.get("species") for m in genome or [] if m]
        for opp_idx, (result, lines) in enumerate(zip(outcomes, logs)):
            if not lines:
                continue                      # no log (timeout / dropped battle)
            outcome = OUTCOME.get(result, "none")
            rng = self._rng(island, gen, genome_idx, opp_idx)
            if not self.keep(fitness=fitness, outcome=outcome, genome_species=species,
                             battle_history=lines, rng=rng):
                continue
            row = {
                "run_id": self.run_id, "island": island, "gen": gen,
                "genome_index": genome_idx, "genome_fitness": fitness,
                "opponent_index": opp_idx, "outcome": outcome,
                "our_species": species, "log": lines,
            }
            pending.append((genome_idx, opp_idx, row))
        # Keep memory bounded: only the first max_per_gen in final order can be written.
        pending.sort(key=lambda t: (t[0], t[1]))
        del pending[self.max_per_gen:]

    def end_generation(self, island, gen):
        """Write this generation's sample; returns the number of rows written."""
        rows = self._pending.pop((island, gen), [])
        if not rows:
            self.written[(island, gen)] = 0
            return 0
        os.makedirs(self.out_dir, exist_ok=True)
        path = os.path.join(self.out_dir, f"{island}_gen{gen:04d}.jsonl")
        with open(path, "w") as f:
            for _, _, row in rows:
                f.write(json.dumps(row) + "\n")
        self.written[(island, gen)] = len(rows)
        return len(rows)
