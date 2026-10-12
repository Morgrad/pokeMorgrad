"""SimpleHeuristics pilot, real team opponents."""
import asyncio, glob, os, random, sys
from pathlib import Path
sys.path.insert(0, os.path.expanduser("~/project"))
from poke_env import AccountConfiguration
from poke_env.player import SimpleHeuristicsPlayer
from poke_env.ps_client import ServerConfiguration

FORMAT = "gen9championsvgc2026regmc"
CONCURRENCY = 3
TIMEOUT = 25

async def run_battle(team_str, opp_str, uid, sem, server_cfg):
    async with sem:
        bot = opp = None
        try:
            bot = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=team_str,
                max_concurrent_battles=1, server_configuration=server_cfg,
                account_configuration=AccountConfiguration.generate(f"V3{uid}", rand=True))
            opp = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=opp_str,
                max_concurrent_battles=1, server_configuration=server_cfg,
                account_configuration=AccountConfiguration.generate(f"V3O{uid}", rand=True))
            await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout=TIMEOUT)
            if bot.n_finished_battles == 0: return None
            try:
                turns = getattr(list(bot.battles.values())[-1], "turn", 0)
            except Exception:
                turns = 0
            if turns < 3: return None
            return 1 if bot.n_won_battles > 0 else 0
        except Exception:
            return None
        finally:
            for p in (bot, opp):
                try:
                    if p: await p.ps_client.stop_listening()
                except Exception: pass

async def main():
    team_file = sys.argv[1]
    n = int(sys.argv[2]); b = int(sys.argv[3])
    port = int(sys.argv[4]); seed = int(sys.argv[5])
    random.seed(seed)
    team_str = Path(team_file).read_text()
    files = glob.glob(os.path.expanduser("~/project/real_teams/*.txt"))
    real = [open(f).read().strip() for f in files]
    real = [t for t in real if t and t.count("@") >= 6]
    if not real:
        print("No real teams found"); return
    server_cfg = ServerConfiguration(
        f"ws://localhost:{port}/showdown/websocket",
        "https://play.pokemonshowdown.com/action.php?")
    opps = random.sample(real, min(n, len(real)))
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [run_battle(team_str, o, random.randint(1, 10**9), sem, server_cfg)
             for o in opps for _ in range(b)]
    outcomes = await asyncio.gather(*tasks)
    valid = [o for o in outcomes if o is not None]
    wins = sum(valid)
    print(f"Valid battles: {len(valid)}")
    print(f"Wins:          {wins}")
    if valid:
        print(f"Win rate:      {wins/len(valid)*100:.1f}%")

asyncio.run(main())
