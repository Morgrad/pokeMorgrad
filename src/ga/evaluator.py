"""
Genome evaluation: play one genome against a list of opponents and score it.

Battles go through src/battle.py (shared with eval); the Evaluator owns the
concurrency semaphore and the fitness-environment settings (GAConfig), so nothing
here depends on module-global state set up elsewhere.

Outcomes are always gathered in opponents order (asyncio.gather): the fitness
pairs outcome i with opponent i's meta weight, so completion order must never
leak in (see tests/test_ga_eval_order.py).
"""
import asyncio
import random
import time

from src import battle as B
from src import regmc_db as DB
from src.ga import config as C
from src.ga.fitness import weighted_fitness
from src.ga.genome import genome_to_text


def _log_score(idx, total, fit, wins, valid_n, mons, tag=""):
    """One-line progress print. `tag` is an optional suffix like 'early-abort'."""
    ts = time.strftime("%H:%M:%S")
    species = ' / '.join(m['species'] for m in mons)
    suffix = f"  {tag}" if tag else ""
    print(f"  [{ts}] {idx+1:>2}/{total}  {fit*100:5.1f}%  ({wins}W/{valid_n}){suffix}  {species}",
          flush=True)


class Evaluator:
    """Scores genomes for one GA run. `concurrency` = simultaneous battles."""

    def __init__(self, config, concurrency):
        self.config = config
        self.sem = asyncio.Semaphore(concurrency)

    def _fitness(self, outcomes, opponents):
        return weighted_fitness(outcomes, opponents, self.config.meta_weights)

    def _start_battle(self, text, opp, **save):
        """Coroutine for one battle (the per-battle account id is drawn now)."""
        c = self.config
        return B.run_battle(text, opp, random.randint(1, C.UID_MAX), self.sem, C.FORMAT,
                            pilot=c.fitness_pilot, timeout=c.battle_timeout,
                            min_turns=c.min_turns, opp_pilot=c.fitness_opp, **save)

    async def evaluate(self, mons, opponents, idx, total, save_filter=None, save_callback=None):
        """Fitness = win rate of one genome across all `opponents`, run concurrently.

        Two-phase: play early_stop_min_battles first; if that head score is below
        early_stop_win_rate, skip the tail and return the partial score. Partial (not
        0.0) so the genome still ranks correctly against other bad genomes — useful
        in early generations when the whole population is weak.

        Invalid genomes score 0.0 immediately. Battles returning None (timeout /
        desync) are dropped from the denominator, not counted as losses.

        Small pools (<= early_stop_min_battles, e.g. smoke tests) skip the split and
        play everything in one batch.
        """
        text = genome_to_text(mons)
        ok, errs = DB.validate_team(text)
        if not ok:
            print(f"  [{idx+1}/{total}] INVALID: {errs[:2]}")
            return 0.0

        async def _battle(opp):
            return await self._start_battle(text, opp, save_filter=save_filter,
                                            save_callback=save_callback)

        head_size = self.config.early_stop_min_battles

        # Small pools: no early-stop possible, one batch.
        if len(opponents) <= head_size:
            outcomes = await asyncio.gather(*[_battle(o) for o in opponents])
            fit, wins, valid_n = self._fitness(outcomes, opponents)
            if not valid_n:
                return 0.0
            _log_score(idx, total, fit, wins, valid_n, mons)
            print()  # New line at end
            return fit

        # Phase 1 — head batch; abort if it scores below early_stop_win_rate.
        head, tail = opponents[:head_size], opponents[head_size:]
        head_results = await asyncio.gather(*[_battle(o) for o in head])
        head_fit, head_wins, head_n = self._fitness(head_results, head)
        if head_n and head_fit < self.config.early_stop_win_rate:
            _log_score(idx, total, head_fit, head_wins, head_n, mons, tag="early-abort")
            print()
            return head_fit

        # Phase 2 — tail batch.
        tail_results = await asyncio.gather(*[_battle(o) for o in tail])
        all_results = list(head_results) + list(tail_results)
        fit, wins, valid_n = self._fitness(all_results, opponents)
        if not valid_n:
            return 0.0
        _log_score(idx, total, fit, wins, valid_n, mons)
        print()  # New line at end
        return fit

    async def eval_on_subset(self, genome, opponents):
        """One-shot fitness on a specific opponent list. No early-stop, no retry, no logging."""
        text = genome_to_text(genome)
        ok, _ = DB.validate_team(text)
        if not ok:
            return 0.0
        outcomes = await asyncio.gather(*[self._start_battle(text, o) for o in opponents])
        return self._fitness(outcomes, opponents)[0]
