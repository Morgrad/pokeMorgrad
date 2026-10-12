"""
Per-opponent win rate for a team vs every team in real_teams/.
Outputs a sorted list of the worst matchups.
"""
import asyncio, glob, os, random, sys
from pathlib import Path
sys.path.insert(0, os.path.expanduser("~/project/src"))
from poke_env import AccountConfiguration
from poke_env.player import SimpleHeuristicsPlayer
from poke_env.ps_client import ServerConfiguration

FORMAT = "gen9championsvgc2026regmc"
CONCURRENCY = 3
TIMEOUT = 20
BATTLES_PER_OPP = 2

async def run_battle(team_str, opp_str, uid, sem, server_cfg):
    async with sem:
        bot = opp = None
        try:
            bot = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=team_str,
                max_concurrent_battles=1, server_configuration=server_cfg,
                account_configuration=AccountConfiguration.generate(f"OP{uid}", rand=True))
            opp = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=opp_str,
                max_concurrent_battles=1, server_configuration=server_cfg,
                account_configuration=AccountConfiguration.generate(f"OO{uid}", rand=True))
            await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout=TIMEOUT)
            if bot.n_finished_battles == 0:
                return None
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
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42
    random.seed(seed)

    team_str = Path(team_file).read_text()
    files = sorted(glob.glob(os.path.expanduser("~/project/data/real_teams/*.txt")))
    teams = [(os.path.basename(f), open(f).read().strip()) for f in files]
    teams = [(n, t) for n, t in teams if t and t.count("@") >= 6]
    print(f"Evaluating {team_file} vs {len(teams)} opponents, {BATTLES_PER_OPP} battles each")

    server_cfg = ServerConfiguration(
        f"ws://localhost:{port}/showdown/websocket",
        "https://play.pokemonshowdown.com/action.php?")
    sem = asyncio.Semaphore(CONCURRENCY)

    results = []
    async def per_opp(name, opp_text):
        tasks = [run_battle(team_str, opp_text, random.randint(1, 10**9), sem, server_cfg)
                 for _ in range(BATTLES_PER_OPP)]
        outcomes = await asyncio.gather(*tasks)
        valid = [o for o in outcomes if o is not None]
        if not valid:
            return (name, None, 0, 0)
        return (name, sum(valid) / len(valid), sum(valid), len(valid))

    # process in batches of 50 so we get progress
    batch_size = 50
    all_results = []
    for i in range(0, len(teams), batch_size):
        batch = teams[i:i + batch_size]
        batch_results = await asyncio.gather(*[per_opp(n, t) for n, t in batch])
        all_results.extend(batch_results)
        print(f"  progress: {i + len(batch)}/{len(teams)}", flush=True)

    # Filter and sort
    scored = [(n, wr, w, g) for (n, wr, w, g) in all_results if wr is not None]
    scored.sort(key=lambda x: x[1])

    print()
    print("=== WORST 25 MATCHUPS ===")
    for name, wr, w, g in scored[:25]:
        print(f"  {wr*100:5.1f}%  ({w}W/{g})  {name}")

    print()
    print("=== BEST 15 MATCHUPS ===")
    for name, wr, w, g in scored[-15:]:
        print(f"  {wr*100:5.1f}%  ({w}W/{g})  {name}")

    overall = sum(r[2] for r in scored) / sum(r[3] for r in scored)
    print()
    print(f"Overall: {overall*100:.1f}% over {sum(r[3] for r in scored)} battles")

    # Write full results
    out = os.path.expanduser("~/project/docs/opponent_analysis.txt")
    with open(out, "w") as f:
        f.write(f"Team: {team_file}\n")
        f.write(f"Overall: {overall*100:.1f}% ({sum(r[2] for r in scored)}W/{sum(r[3] for r in scored)})\n\n")
        f.write("All opponents sorted worst-to-best:\n")
        for name, wr, w, g in scored:
            f.write(f"{wr*100:6.1f}%  {w}W/{g}  {name}\n")
    print(f"Full results: {out}")

asyncio.run(main())
