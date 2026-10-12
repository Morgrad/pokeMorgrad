"""Unified team evaluation.

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

from poke_env.player import SimpleHeuristicsPlayer
from poke_env import AccountConfiguration

from src import ga_core as G
from src import regmc_db as DB

FORMAT = G.FORMAT
CONCURRENCY = 3
TIMEOUT = 20
DEFAULT_SEEDS = [100, 200, 300]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p(*parts):
    return os.path.join(_REPO_ROOT, *parts)


def make_player(pilot, team_str, uid, prefix):
    """Construct a Player for the given pilot. BC import is lazy."""
    if pilot == "bc":
        from src.bc_player import BCPlayer
        cls = BCPlayer
    else:
        cls = SimpleHeuristicsPlayer
    return cls(
        battle_format=FORMAT,
        team=team_str,
        max_concurrent_battles=1,
        account_configuration=AccountConfiguration.generate(f"{prefix}{uid}", rand=True),
    )


async def run_battle(pilot, team_str, opp_str, uid, sem):
    async with sem:
        bot = opp = None
        try:
            bot = make_player(pilot, team_str, uid, "B")
            opp = make_player("heuristic", opp_str, uid, "O")
            await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout=TIMEOUT)
            if bot.n_finished_battles == 0:
                return None
            return 1 if bot.n_won_battles > 0 else 0
        except Exception:
            return None
        finally:
            for p in (bot, opp):
                try:
                    if p:
                        await p.ps_client.stop_listening()
                except Exception:
                    pass


async def evaluate_team(pilot, team_str, opponents, seeds, concurrency):
    total_w, total_g = 0, 0
    for seed in seeds:
        random.seed(seed)
        sem = asyncio.Semaphore(concurrency)
        tasks = [
            run_battle(pilot, team_str, o, random.randint(1, 10**9), sem)
            for o in opponents
        ]
        outs = await asyncio.gather(*tasks)
        valid = [o for o in outs if o is not None]
        total_w += sum(valid)
        total_g += len(valid)
    return total_w, total_g


async def main_async(args):
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
            print(f"  {os.path.basename(team_path):40s} {w:4d}/{g:4d} = {pct:5.1f}%")

    if len(pilots) > 1:
        print("\n" + "=" * 72)
        print(f"{'Team':40s} {'HEUR':>8s} {'BC':>8s} {'Delta':>8s}")
        print("-" * 72)
        all_teams = set()
        for r in results.values():
            all_teams.update(r.keys())
        for name in sorted(all_teams):
            h = results.get("heuristic", {}).get(name)
            b = results.get("bc", {}).get(name)
            h_pct = (h[0] / h[1] * 100) if h and h[1] else None
            b_pct = (b[0] / b[1] * 100) if b and b[1] else None
            h_str = f"{h_pct:.1f}%" if h_pct is not None else "-"
            b_str = f"{b_pct:.1f}%" if b_pct is not None else "-"
            d_str = (f"{b_pct - h_pct:+.1f}"
                     if h_pct is not None and b_pct is not None else "-")
            print(f"{name:40s} {h_str:>8s} {b_str:>8s} {d_str:>8s}")


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