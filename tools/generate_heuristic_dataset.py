"""Generate a training dataset by recording heuristic-pilot decisions.

Runs N battles on the local Showdown server with SimpleHeuristicsPlayer on
both sides. Every `choose_move` call records (state, chosen_action) for the
side that moved. Output is JSONL in the same shape as
tools/build_training_data.py emits, so src/bc_train.py consumes it directly.

Usage:
  python tools/generate_heuristic_dataset.py --battles 500 --out data/training_data_heuristic.jsonl

The bot side uses a fresh random genome each battle (same distribution the GA
evaluates); the opponent is a random regional team. This matches the
distribution the eventual GA will actually face, so the trained pilot
generalizes to the GA loop.
"""
import argparse
import asyncio
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poke_env.player import SimpleHeuristicsPlayer
from poke_env import AccountConfiguration
from poke_env.battle.move import Move
from poke_env.battle.pokemon import Pokemon
from poke_env.player.battle_order import DoubleBattleOrder

from src import ga_core as G
from src.state_encoder import StateEncoder


FORMAT = G.FORMAT
TIMEOUT = 30

# poke_env SingleBattleOrder.move_target -> training-time target_idx
#   0  = no target (self / spread)  -> 2
#   -1 = our left ally              -> 1
#   -2 = our right ally             -> 0
#   1  = opponent left              -> 3
#   2  = opponent right             -> 4
TARGET_MAP_REV = {0: 2, -1: 1, -2: 0, 1: 3, 2: 4}


_ENCODER = None


def _get_encoder():
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = StateEncoder()
    return _ENCODER


def _to_sd_id(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def _canonical_species(raw: str, encoder) -> str:
    if raw in encoder.species_idx:
        return raw
    sid = _to_sd_id(raw)
    for k in encoder.species_idx:
        if _to_sd_id(k) == sid:
            return k
    return raw


def _canonical_move(sd_id: str, encoder):
    if sd_id in encoder.move_idx:
        return sd_id
    for k in encoder.move_idx:
        if _to_sd_id(k) == sd_id:
            return k
    return None


def _mon_view(mon, encoder, is_opp=False):
    if mon is None or mon.species is None:
        return None
    revealed = []
    for mv in mon.moves.values():
        if mv is None or not mv.id:
            continue
        name = _canonical_move(mv.id, encoder)
        if name:
            revealed.append(name)
    return {
        "species": _canonical_species(str(mon.species), encoder),
        "gender": str(getattr(mon, "gender", None)) if getattr(mon, "gender", None) is not None else None,
        "hp_now": int(mon.current_hp_fraction * 100)
                  if mon.current_hp_fraction is not None else None,
        "hp_max": 100,
        "status": mon.status.name.lower() if mon.status else None,
        "boosts": {k: v for k, v in mon.boosts.items() if v != 0},
        "revealed_moves": revealed[:4],
        "item": None,
        "ability": None,
        "is_mega": False,
    }


def state_from_battle(battle, encoder):
    my_active = [_mon_view(m, encoder) for m in battle.active_pokemon]
    my_bench = [_mon_view(m, encoder) for m in battle.team.values()
                if m not in battle.active_pokemon and not m.fainted]
    opp_active = [_mon_view(m, encoder, True) for m in battle.opponent_active_pokemon]
    opp_seen = [_mon_view(m, encoder, True) for m in battle.opponent_team.values()]
    weather = None
    if battle.weather:
        weather = list(battle.weather.keys())[0].name
    field = {
        "weather": weather,
        "terrain": None,
        "trick_room": bool(battle.fields.get("trickroom")),
        "tailwind": {
            "p1": 1 if battle.side_conditions.get("tailwind") else 0,
            "p2": 1 if battle.opponent_side_conditions.get("tailwind") else 0,
        },
    }
    return {
        "my_active": my_active,
        "my_bench": my_bench,
        "opp_active": opp_active,
        "opp_seen": opp_seen,
        "field": field,
    }


class RecordingHeuristic(SimpleHeuristicsPlayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.decisions = []

    def choose_move(self, battle):
        encoder = _get_encoder()
        try:
            state = state_from_battle(battle, encoder)
        except Exception:
            state = None

        order = super().choose_move(battle)

        if state is not None:
            actions = self._order_to_actions(order, encoder)
            if actions:
                self.decisions.append({
                    "turn": battle.turn,
                    "state": state,
                    "actions": actions,
                })
        return order

    def _order_to_actions(self, order, encoder):
        if not isinstance(order, DoubleBattleOrder):
            return None
        slots = {}
        for slot_name, single in [("a", order.first_order), ("b", order.second_order)]:
            if single is None or single.order is None:
                slots[slot_name] = None
                continue
            o = single.order
            if isinstance(o, Move):
                name = _canonical_move(o.id, encoder)
                if not name:
                    slots[slot_name] = None
                    continue
                target = TARGET_MAP_REV.get(getattr(single, "move_target", 0), 2)
                slots[slot_name] = {"action": {"type": "move", "move": name},
                                    "target": target}
            elif isinstance(o, Pokemon):
                name = _canonical_species(str(o.species), encoder)
                slots[slot_name] = {"action": {"type": "switch", "to": name},
                                    "target": 2}
            else:
                slots[slot_name] = None
        return slots


def _format_row(d, side, side_won):
    actions = d.get("actions")
    if not actions:
        return None
    a = actions.get("a")
    b = actions.get("b")
    if a is None and b is None:
        return None
    chosen = {}
    if a:
        chosen["a"] = a["action"]
    if b:
        chosen["b"] = b["action"]
    return {
        "side": side,
        "state": d["state"],
        "turn": d["turn"],
        "chosen": {side: chosen},
        "target_a": a["target"] if a else 2,
        "target_b": b["target"] if b else 2,
        "side_won": side_won,
    }


async def run_one_battle(team_a, team_b, uid, sem):
    async with sem:
        p1 = p2 = None
        try:
            p1 = RecordingHeuristic(
                battle_format=FORMAT, team=team_a, max_concurrent_battles=1,
                account_configuration=AccountConfiguration.generate(f"HB{uid}", rand=False))
            p2 = RecordingHeuristic(
                battle_format=FORMAT, team=team_b, max_concurrent_battles=1,
                account_configuration=AccountConfiguration.generate(f"HO{uid}", rand=False))
            await asyncio.wait_for(p1.battle_against(p2, n_battles=1), timeout=TIMEOUT)
            if p1.n_finished_battles == 0:
                return []
            p1_won = p1.n_won_battles > 0
            rows = []
            for d in p1.decisions:
                r = _format_row(d, "p1", side_won=p1_won)
                if r:
                    rows.append(r)
            for d in p2.decisions:
                r = _format_row(d, "p2", side_won=not p1_won)
                if r:
                    rows.append(r)
            return rows
        except Exception:
            return []
        finally:
            for p in (p1, p2):
                try:
                    if p:
                        await p.ps_client.stop_listening()
                except Exception:
                    pass


async def main_async(args):
    random.seed(args.seed)
    sem = asyncio.Semaphore(args.concurrency)
    opponents = G.regional_pool()
    if not opponents:
        print("ERROR: no regional teams loaded")
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build battle list: fresh random genome vs random regional team.
    pairs = []
    for i in range(args.battles):
        bot_genome = G.build_random_genome({})
        if bot_genome is None:
            continue
        # Route through the same Showdown legality gate the GA uses.
        # Without this, ~1% of random genomes contain format-illegal forms
        # (Greninja-Bond) or transfer-only moves, and their battles fail at
        # team validation before they start.
        legal = G.filter_legal_genomes([bot_genome], {})
        if not legal:
            continue    # couldn't legalize in 20 rebuilds; skip this battle
        bot_genome = legal[0]
        bot_team = G.genome_to_text(bot_genome)
        opp_team = random.choice(opponents)
        pairs.append((bot_team, opp_team, i))

    print(f"Running {len(pairs)} battles at concurrency {args.concurrency}...")
    print(f"Output: {out_path}")

    n_rows = 0
    n_battles_ok = 0
    with open(out_path, "w") as f:
        chunk = 50
        for start in range(0, len(pairs), chunk):
            batch = pairs[start:start + chunk]
            tasks = [run_one_battle(a, b, uid, sem) for a, b, uid in batch]
            results = await asyncio.gather(*tasks)
            for rows in results:
                if rows:
                    n_battles_ok += 1
                for row in rows:
                    f.write(json.dumps(row) + "\n")
                    n_rows += 1
            print(f"  {start + len(batch)}/{len(pairs)} battles, "
                  f"{n_rows} rows ({n_battles_ok} ok)", flush=True)

    print(f"DONE: {n_rows} rows from {n_battles_ok}/{len(pairs)} battles")


def main():
    parser = argparse.ArgumentParser(description="Generate heuristic-imitation training data.")
    parser.add_argument("--battles", type=int, default=500, help="battles to run")
    parser.add_argument("--concurrency", type=int, default=8, help="concurrent battles")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument("--out", default="data/training_data_heuristic.jsonl")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
