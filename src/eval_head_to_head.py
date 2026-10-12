"""
Evaluate multiple teams vs the 400 regional teams, 3 seeds each.
Usage: python eval_head_to_head.py <team1.txt> <team2.txt> ...
"""
import asyncio, os, sys, random
sys.path.insert(0, os.path.expanduser("~/project/src"))
from poke_env.player import SimpleHeuristicsPlayer
from poke_env import AccountConfiguration
import ga_core as G

FORMAT = "gen9championsvgc2026regmc"
CONCURRENCY = 3
TIMEOUT = 20

async def run_battle(team_str, opp_str, uid, sem):
    async with sem:
        bot = opp = None
        try:
            bot = SimpleHeuristicsPlayer(battle_format=FORMAT, team=team_str,
                max_concurrent_battles=1,
                account_configuration=AccountConfiguration.generate(f"E{uid}", rand=True))
            opp = SimpleHeuristicsPlayer(battle_format=FORMAT, team=opp_str,
                max_concurrent_battles=1,
                account_configuration=AccountConfiguration.generate(f"EO{uid}", rand=True))
            await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout=TIMEOUT)
            if bot.n_finished_battles == 0: return None
            return 1 if bot.n_won_battles > 0 else 0
        except Exception:
            return None
        finally:
            for p in (bot, opp):
                try:
                    if p: await p.ps_client.stop_listening()
                except Exception: pass

async def eval_one(path, opps, seeds):
    sem = asyncio.Semaphore(CONCURRENCY)
    team_str = open(path).read()
    total_w, total_g = 0, 0
    for s in seeds:
        random.seed(s)
        tasks = [run_battle(team_str, o, random.randint(1, 10**9), sem) for o in opps]
        outs = await asyncio.gather(*tasks)
        valid = [o for o in outs if o is not None]
        total_w += sum(valid); total_g += len(valid)
    return total_w, total_g

async def main():
    paths = sys.argv[1:] or [
        os.path.expanduser("~/project/data/baseline_team.txt"),
        os.path.expanduser("~/project/output/champions/ga_umbreon.txt"),
        os.path.expanduser("~/project/output/champions/ga_free.txt"),
    ]
    opps = G.heldout_pool()  # eval uses held-out 100 teams, not training pool
    print(f"Opponents: {len(opps)} regional teams, seeds [100, 200, 300]")

    for path in paths:
        if not os.path.exists(path):
            print(f"MISSING: {path}")
            continue
        w, g = await eval_one(path, opps, [100, 200, 300])
        print(f"  {os.path.basename(path):30s}  {w:4d}/{g:4d} = {w/g*100:5.1f}%")

asyncio.run(main())
