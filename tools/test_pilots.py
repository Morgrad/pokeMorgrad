"""Head-to-head: SmartPlayer vs SimpleHeuristicsPlayer on the SAME team.

Isolates pilot skill from team quality: both players pilot identical teams
in each battle. Score = smart wins / (smart + vanilla).

Usage:
    python3 tools/test_pilots.py [n_teams] [battles_per_team] [concurrency]

Port: 8001 (does not contend with GA on 8000).
"""
import argparse
import asyncio
import math
import sys
import time
from pathlib import Path

REPO = Path.home() / "project"
sys.path.insert(0, str(REPO))

from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.player import SimpleHeuristicsPlayer
from src.smart_player import SmartPlayer
from src.ga_core import heldout_pool

PORT = 8001
FORMAT = "gen9championsvgc2026regmc"


async def one_battle(i, team, server, sem):
    async with sem:
        vanilla = smart = None
        try:
            vanilla = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=team,
                max_concurrent_battles=1,
                server_configuration=server,
                account_configuration=AccountConfiguration.generate(
                    f"V{i:06d}", rand=False),
            )
            smart = SmartPlayer(
                battle_format=FORMAT, team=team,
                max_concurrent_battles=1,
                server_configuration=server,
                account_configuration=AccountConfiguration.generate(
                    f"S{i:06d}", rand=False),
            )
            await asyncio.wait_for(
                vanilla.battle_against(smart, n_battles=1), timeout=45)
            if vanilla.n_won_battles > 0:
                return "vanilla"
            elif smart.n_won_battles > 0:
                return "smart"
            else:
                return "tie"
        except Exception as e:
            return f"error:{type(e).__name__}"
        finally:
            for p in (vanilla, smart):
                try:
                    if p:
                        await p.ps_client.stop_listening()
                except Exception:
                    pass


async def main(n_teams, battles_per_team, concurrency):
    server = ServerConfiguration(
        f"ws://localhost:{PORT}/showdown/websocket",
        f"http://localhost:{PORT}/action.php?",
    )
    teams = heldout_pool()[:n_teams]
    total = n_teams * battles_per_team

    sem = asyncio.Semaphore(concurrency)
    start = time.time()

    tasks = []
    battle_id = 0
    for team in teams:
        for _ in range(battles_per_team):
            tasks.append(one_battle(battle_id, team, server, sem))
            battle_id += 1

    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start

    smart = sum(1 for r in results if r == "smart")
    vanilla = sum(1 for r in results if r == "vanilla")
    tie = sum(1 for r in results if r == "tie")
    errors = [r for r in results if isinstance(r, str) and r.startswith("error")]

    print(f"\n=== results ===")
    print(f"  teams: {n_teams}, battles/team: {battles_per_team}, total: {total}")
    print(f"  concurrency: {concurrency}, elapsed: {elapsed:.1f}s "
          f"({elapsed/total*1000:.0f} ms/battle)")
    print(f"  smart:   {smart}")
    print(f"  vanilla: {vanilla}")
    print(f"  tie:     {tie}")
    print(f"  errors:  {len(errors)}")
    if errors:
        from collections import Counter
        print(f"  error kinds: {dict(Counter(errors))}")

    played = smart + vanilla
    if played:
        p = smart / played
        n = played
        z = 1.96
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        lo = max(0.0, centre - half) * 100
        hi = min(1.0, centre + half) * 100
        print(f"  smart win rate: {p*100:.1f}%  95% CI [{lo:.1f}-{hi:.1f}]")
        if p > 0.5 and lo > 50:
            print(f"  -> SmartPlayer significantly better than vanilla")
        elif p < 0.5 and hi < 50:
            print(f"  -> SmartPlayer significantly WORSE than vanilla")
        else:
            print(f"  -> inconclusive at this sample size")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("n_teams", type=int, nargs="?", default=20)
    ap.add_argument("battles_per_team", type=int, nargs="?", default=10)
    ap.add_argument("concurrency", type=int, nargs="?", default=8)
    args = ap.parse_args()
    asyncio.run(main(args.n_teams, args.battles_per_team, args.concurrency))
