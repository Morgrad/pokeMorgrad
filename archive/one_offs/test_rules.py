"""Run A/B tests for each rule individually against v1 baseline."""
import asyncio
import os
import subprocess
import sys
from poke_env import AccountConfiguration

# Import v1 baseline (no extra rules)
os.environ["TACTICAL_RULES"] = ""
import importlib
import tactical_rules
importlib.reload(tactical_rules)
from neural_player import NeuralPlayer

# We'll subprocess each test so env var takes effect cleanly
RULE_IDS = ["A", "B", "C", "D", "F", "G"]  # skip E (no-op)
N_BATTLES = 60

async def run_ab(rule_id, n=60):
    # This runs inside a subprocess with the env var set
    from neural_player import NeuralPlayer as V1  # v1 baseline (no extras)
    # Force reload with new env
    os.environ["TACTICAL_RULES"] = rule_id
    importlib.reload(tactical_rules)
    import neural_player
    importlib.reload(neural_player)
    from neural_player import NeuralPlayer as Variant

    seed = open("seed_team_v2.txt").read()
    vw = v1w = 0
    for i in range(n):
        if i % 2 == 0:
            a = V1(battle_format="gen9championsvgc2026regmc", team=seed,
                  max_concurrent_battles=1,
                  account_configuration=AccountConfiguration.generate(f"A{i}", rand=True))
            b = Variant(battle_format="gen9championsvgc2026regmc", team=seed,
                       max_concurrent_battles=1,
                       account_configuration=AccountConfiguration.generate(f"B{i}", rand=True))
        else:
            b = Variant(battle_format="gen9championsvgc2026regmc", team=seed,
                       max_concurrent_battles=1,
                       account_configuration=AccountConfiguration.generate(f"B{i}", rand=True))
            a = V1(battle_format="gen9championsvgc2026regmc", team=seed,
                  max_concurrent_battles=1,
                  account_configuration=AccountConfiguration.generate(f"A{i}", rand=True))
        await a.battle_against(b, n_battles=1)
        if b.n_won_battles > 0: vw += 1
        else: v1w += 1
    return vw, v1w

if __name__ == "__main__":
    rule = sys.argv[1] if len(sys.argv) > 1 else "A"
    vw, v1w = asyncio.run(run_ab(rule))
    print(f"RULE_{rule}: Variant {vw} - Baseline {v1w}  ({100*vw/(vw+v1w):.1f}%)")
