"""Unified team evaluation.

Scores one or more teams against an opponent pool, over several RNG seeds, with
either the fast heuristic pilot or the neural BC pilot (or both, side by side).
The heuristic path never imports torch — BC is pulled in lazily — so a plain
`--pilot heuristic` run stays light.

Usage:
  python -m src.eval                                # defaults: baseline, both pilots
  python -m src.eval team1.txt team2.txt            # specific teams
  python -m src.eval --pilot heuristic              # fast (no torch / no BC)
  python -m src.eval --pilot bc                     # real eval with the neural pilot
  python -m src.eval --opponents all                # use all 300 training teams
  python -m src.eval --seeds 100 200 300 400 500    # more seeds
"""
import argparse
import asyncio
import os
import random

from src import ga_core as G
from src import battle as B

FORMAT = G.FORMAT          # canonical format registry (defined in ga_core)
CONCURRENCY = int(os.environ.get("GA_CONCURRENCY", "3"))   # simultaneous battles per server
TIMEOUT = 20              # seconds before a battle is abandoned as hung (→ None)
UID_MAX = 10**9          # upper bound of the random per-battle account id space
DEFAULT_SEEDS = [100, 200, 300]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p(*parts):
    return os.path.join(_REPO_ROOT, *parts)


def wilson_ci(wins: int, games: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion.

    Preferred over naive p ± z·sqrt(p(1-p)/n): the Wilson interval stays inside
    [0, 1] for small n and doesn't collapse to a point at 0% or 100%. With 100
    battles (the 1-seed case), the naive interval is wrong enough to mislead —
    Wilson is the standard fix.

    Returns (lo, hi) as fractions in [0, 1]. Caller multiplies by 100 for print.
    """
    if games == 0:
        return (0.0, 0.0)
    p = wins / games
    denom = 1 + z * z / games
    center = (p + z * z / (2 * games)) / denom
    half = (z * (p * (1 - p) / games + z * z / (4 * games * games)) ** 0.5) / denom
    return (max(0.0, center - half), min(1.0, center + half))


async def evaluate_team(pilot, team_str, opponents, seeds, concurrency):
    """Return (total_wins, total_games) for a team across all seeds × opponents.

    Each seed re-seeds the RNG so account ids / any sampling are reproducible per
    seed. Battles returning None (timeout/error) are excluded from both totals, so
    the win rate is over *completed* games only. Seeds run sequentially.
    """
    total_w, total_g = 0, 0
    # One semaphore for the whole call, not one per seed. Correct today because
    # seeds run strictly sequentially — a seed's battles all finish (the gather
    # below) before the next seed starts, so the counter is always back at full
    # when reused. If seeds are ever parallelized, a single shared semaphore would
    # cap total in-flight battles across all seeds (under-utilizing concurrency) —
    # move it back inside the loop (per seed) at that point.
    sem = asyncio.Semaphore(concurrency)
    for seed in seeds:
        random.seed(seed)
        tasks = [
            B.run_battle(team_str, o, random.randint(1, UID_MAX), sem, FORMAT,
                         pilot=pilot, timeout=TIMEOUT, min_turns=0)
            for o in opponents
        ]
        outs = await asyncio.gather(*tasks)
        valid = [o for o in outs if o is not None]
        total_w += sum(valid)
        total_g += len(valid)
    return total_w, total_g


async def main_async(args):
    """Resolve teams/opponents/pilots from args, run every combo, print a table.

    Defaults to the baseline team vs the held-out pool with both pilots. With two
    pilots it also prints a per-team HEUR/BC/Delta comparison.
    """
    teams = args.teams or [_p("data", "baseline_team.txt")]

    if args.opponents == "all":
        opponents = G.regional_pool()
        opp_label = f"training pool ({len(opponents)})"
    else:
        opponents = G.heldout_pool()
        opp_label = f"held-out ({len(opponents)})"

    pilots = ["heuristic", "bc"] if args.pilot == "both" else [args.pilot]

    print("=" * 72)
    print(f"Opponents:   {opp_label}")
    print(f"Seeds:       {args.seeds}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Pilots:      {pilots}")
    print("=" * 72)

    results = {}

    for pilot in pilots:
        print(f"\n--- Pilot: {pilot.upper()} ---")
        results[pilot] = {}
        for team_path in teams:
            if not os.path.exists(team_path):
                print(f"  MISSING: {team_path}")
                continue
            team_str = open(team_path).read()
            w, g = await evaluate_team(pilot, team_str, opponents, args.seeds,
                                       args.concurrency)
            results[pilot][os.path.basename(team_path)] = (w, g)
            pct = (w / g * 100) if g else 0.0
            lo, hi = wilson_ci(w, g)
            ci_str = f"[{lo*100:4.1f}-{hi*100:4.1f}]" if g else "[   n/a   ]"
            print(f"  {os.path.basename(team_path):40s} {w:4d}/{g:4d} = "
                  f"{pct:5.1f}%  95% CI {ci_str}")

    if len(pilots) > 1:
        print("\n" + "=" * 92)
        print(f"{'Team':32s} {'HEURISTIC':>20s} {'BC':>20s} {'Delta':>8s}")
        print("-" * 92)
        all_teams = set()
        for r in results.values():
            all_teams.update(r.keys())
        for name in sorted(all_teams):
            h = results.get("heuristic", {}).get(name)
            b = results.get("bc", {}).get(name)

            def _fmt(res):
                if not res or not res[1]:
                    return "-", None
                w, g = res
                pct = w / g * 100
                lo, hi = wilson_ci(w, g)
                return f"{pct:.1f}% [{lo*100:.0f}-{hi*100:.0f}]", pct

            h_str, h_pct = _fmt(h)
            b_str, b_pct = _fmt(b)
            d_str = (f"{b_pct - h_pct:+.1f}"
                     if h_pct is not None and b_pct is not None else "-")
            print(f"{name:32s} {h_str:>20s} {b_str:>20s} {d_str:>8s}")


def main():
    parser = argparse.ArgumentParser(description="Unified team evaluation.")
    parser.add_argument("teams", nargs="*",
                        help="Team .txt paths. Defaults to data/baseline_team.txt.")
    parser.add_argument("--opponents", choices=["heldout", "all"], default="heldout",
                        help="heldout = 100 eval teams, all = 300 training teams")
    parser.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS)
    parser.add_argument("--pilot", choices=["heuristic", "bc", "both"], default="both")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()