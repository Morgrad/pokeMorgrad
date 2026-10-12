"""
Evaluate a champion team against all 400 regional teams (held-out).
Compare to baseline.
"""
import asyncio, os, sys, random
sys.path.insert(0, os.path.expanduser("~/project/src"))
from poke_env.player import SimpleHeuristicsPlayer
from poke_env import AccountConfiguration
import regmc_db as DB
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

async def eval_team(team_file, opponents, seed):
    sem = asyncio.Semaphore(CONCURRENCY)
    random.seed(seed)
    team_str = open(team_file).read()
    tasks = [run_battle(team_str, o, random.randint(1, 10**9), sem) for o in opponents]
    outcomes = await asyncio.gather(*tasks)
    valid = [o for o in outcomes if o is not None]
    return sum(valid), len(valid)

async def main():
    champ = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/project/output/champions/latest_ga.txt")
    baseline = os.path.expanduser("~/project/data/baseline_team.txt")
    opps = G.regional_pool()

    for label, path in [("CHAMPION", champ), ("BASELINE", baseline)]:
        total_w, total_g = 0, 0
        for seed in [100, 200, 300]:
            w, g = await eval_team(path, opps, seed)
            total_w += w; total_g += g
        print(f"{label}: {total_w}/{total_g} = {total_w/total_g*100:.1f}%  ({path})")

asyncio.run(main())
