"""bc_diagnostic.py — compare BC decisions against SimpleHeuristicsPlayer.

Runs N battles with DiagnosticBC (BCPlayer + logging) vs random heuristic
opponents. At every turn, calls a shadow SimpleHeuristicsPlayer on the SAME
battle object BC sees, so we compare "what BC chose" vs "what the heuristic
would have chosen" without running two battles.

Writes /tmp/bc_diag.jsonl and prints agreement-rate buckets by turn number
and by lowest-HP-on-our-side. Read-only, does not modify anything.

Usage: python3 bc_diagnostic.py [n_battles]
"""
import asyncio
import json
import random
import sys
from collections import Counter, defaultdict

from poke_env.player import SimpleHeuristicsPlayer
from poke_env import AccountConfiguration

from src.bc_player import BCPlayer
from src.ga_core import FORMAT, regional_pool


class DiagnosticBC(BCPlayer):
    def __init__(self, *args, **kwargs):
        self.log = []
        self.shadow = None
        super().__init__(*args, **kwargs)

    def _shadow_heuristic(self):
        if self.shadow is None:
            team = open("data/baseline_team.txt").read()
            kw = dict(battle_format=FORMAT, team=team, max_concurrent_battles=1,
                      account_configuration=AccountConfiguration.generate(
                          "SHADOW", rand=False))
            try:
                self.shadow = SimpleHeuristicsPlayer(start_listening=False, **kw)
            except TypeError:
                self.shadow = SimpleHeuristicsPlayer(**kw)
        return self.shadow

    def choose_move(self, battle):
        heur_msg = None
        try:
            order = self._shadow_heuristic().choose_move(battle)
            heur_msg = getattr(order, "message", None)
        except Exception as e:
            heur_msg = f"<shadow {type(e).__name__}>"

        bc_order = super().choose_move(battle)
        bc_msg = getattr(bc_order, "message", None)

        my_hp = [round(m.current_hp_fraction * 100)
                 if m and m.current_hp_fraction is not None else None
                 for m in battle.active_pokemon]
        self.log.append({
            "turn": battle.turn, "my_hp": my_hp,
            "bc": bc_msg, "heur": heur_msg,
            "agree": bc_msg == heur_msg,
        })
        return bc_order


async def run_battle(bot, opp_team, uid, timeout=45):
    opp = SimpleHeuristicsPlayer(
        battle_format=FORMAT, team=opp_team, max_concurrent_battles=1,
        account_configuration=AccountConfiguration.generate(f"OPP{uid}", rand=False))
    try:
        await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        for p in (bot, opp):
            try:
                await p.ps_client.stop_listening()
            except Exception:
                pass


async def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    random.seed(42)
    opps = regional_pool()
    all_log = []

    for i in range(n):
        bot = DiagnosticBC(
            battle_format=FORMAT,
            team=open("data/baseline_team.txt").read(),
            max_concurrent_battles=1,
            account_configuration=AccountConfiguration.generate(f"BC{i}", rand=False),
            start_listening=True)
        await run_battle(bot, random.choice(opps), i)
        all_log.extend(bot.log)
        ok = sum(1 for e in bot.log if e["agree"])
        print(f"  battle {i+1}/{n}: {len(bot.log)} decisions, {ok} agreed",
              flush=True)

    with open("/tmp/bc_diag.jsonl", "w") as f:
        for e in all_log:
            f.write(json.dumps(e) + "\n")

    total_ok = sum(1 for e in all_log if e["agree"])
    print(f"\n=== {len(all_log)} decisions, {total_ok} agreed "
          f"({total_ok / max(len(all_log), 1) * 100:.1f}%) ===\n")

    print("=== Agreement by turn ===")
    tb = defaultdict(lambda: [0, 0])
    for e in all_log:
        t = e["turn"]
        b = "turn1" if t == 1 else "turn2-3" if t <= 3 else "turn4-6" if t <= 6 else "turn7+"
        tb[b][1] += 1
        if e["agree"]:
            tb[b][0] += 1
    for b in ("turn1", "turn2-3", "turn4-6", "turn7+"):
        if b in tb:
            ok, tot = tb[b]
            print(f"  {b:8}  {ok:4}/{tot:4} = {ok / tot * 100:5.1f}%")

    print("\n=== Agreement by our lowest HP ===")
    hb = defaultdict(lambda: [0, 0])
    for e in all_log:
        vals = [h for h in e["my_hp"] if h is not None]
        if not vals:
            continue
        low = min(vals)
        b = "0-25%" if low <= 25 else "26-50%" if low <= 50 else "51-75%" if low <= 75 else "76-100%"
        hb[b][1] += 1
        if e["agree"]:
            hb[b][0] += 1
    for b in ("0-25%", "26-50%", "51-75%", "76-100%"):
        if b in hb:
            ok, tot = hb[b]
            print(f"  {b:8}  {ok:4}/{tot:4} = {ok / tot * 100:5.1f}%")

    print("\n=== BC-only picks (top 8) ===")
    for pick, n in Counter(
            e["bc"] for e in all_log if not e["agree"] and e["bc"]).most_common(8):
        print(f"  {n:4}x  {pick!r}")

    print("\n=== Heuristic-only picks (top 8) ===")
    for pick, n in Counter(
            e["heur"] for e in all_log if not e["agree"] and e["heur"]).most_common(8):
        print(f"  {n:4}x  {pick!r}")

    print("\nFull log: /tmp/bc_diag.jsonl")


if __name__ == "__main__":
    asyncio.run(main())
