import asyncio, time, logging, sys
from neural_player import NeuralPlayer
from opponent_gen import team_to_showdown
from poke_env import AccountConfiguration
import json

# Capture everything from a single battle
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
logging.getLogger("websockets").setLevel(logging.WARNING)

async def main():
    # Load one team from the pool
    with open("opponent_pool.json") as f:
        pool = json.load(f)
    
    # Try the first 3 teams
    for i, team_species in enumerate(pool[:3]):
        team_str = team_to_showdown(team_species)
        if team_str is None:
            print(f"[team {i}] UNBUILDABLE — skipped by GA")
            continue
        
        seed = open("seed_team_v2.txt").read()
        
        bot = NeuralPlayer(
            battle_format="gen9championsvgc2026regmc",
            team=seed,
            max_concurrent_battles=1,
            account_configuration=AccountConfiguration.generate(f"Diag{i}A", rand=True),
        )
        opp = NeuralPlayer(
            battle_format="gen9championsvgc2026regmc",
            team=team_str,
            max_concurrent_battles=1,
            account_configuration=AccountConfiguration.generate(f"Diag{i}B", rand=True),
        )
        
        print(f"\n=== Battle {i} — opponent: {team_species} ===")
        t0 = time.time()
        await bot.battle_against(opp, n_battles=1)
        elapsed = time.time() - t0
        print(f"Duration: {elapsed:.2f}s  |  bot won: {bot.n_won_battles}  lost: {bot.n_lost_battles}")
        
        # Print the battle log
        if bot.battles:
            tag = list(bot.battles.keys())[0]
            b = bot.battles[tag]
            if hasattr(b, "_battle_log"):
                for line in b._battle_log[:25]:
                    print(f"  {line}")
        
        await asyncio.sleep(1)

asyncio.run(main())
