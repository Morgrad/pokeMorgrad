"""
The GA's fitness number: meta-weighted win rate over the battles that returned a result.

Shared by the GA (src/ga/evaluator.py) and src/eval.py so a holdout score is
comparable with GA scores.

Outcomes are paired with opponents BY INDEX: outcomes[i] must be the battle against
opponents[i]. Collect battle results in submission order (asyncio.gather), never in
completion order.
"""
from src import meta_weights as MW

_WEIGHT_CACHE = {}


def opp_weight(opp_text, meta_weights=True):
    """Ladder-usage weight of one opponent team (1.0 when meta weighting is off). Cached."""
    if not meta_weights:
        return 1.0
    w = _WEIGHT_CACHE.get(opp_text)
    if w is None:
        w = _WEIGHT_CACHE[opp_text] = MW.team_weight(opp_text)
    return w


def weighted_fitness(outcomes, opponents, meta_weights=True):
    """(fit, wins, valid_n): weighted win rate over non-None outcomes; (0.0, 0, 0) if none."""
    valid = [o for o in outcomes if o is not None]
    if not valid:
        return 0.0, 0, 0
    rate = MW.weighted_rate(outcomes, [opp_weight(t, meta_weights) for t in opponents])
    return rate, sum(valid), len(valid)
