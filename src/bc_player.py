"""BC pilot — wraps a trained BC model as a poke_env Player."""
import json
import os

import numpy as np
import torch
import torch.nn.functional as F

from poke_env.player import Player
from poke_env.battle import DoubleBattle

from src.state_encoder import StateEncoder
from src.bc_model import (
    BCModel, build_move_mask, load_checkpoint,
    NEG_INF, TYPE_MOVE, TYPE_SWITCH,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(_REPO_ROOT, "output", "models", "bc_v4_best.pt")
PRIORS_PATH = os.path.join(_REPO_ROOT, "data", "species_move_priors.json")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _to_sd_id(name: str) -> str:
    """Match Pokémon Showdown's toID(): lowercase, alphanumeric only."""
    return "".join(c for c in name.lower() if c.isalnum())


class BCPlayer(Player):
    def __init__(self, *args, **kwargs):
        # Build everything BEFORE super().__init__() so the async listener
        # never fires against a half-constructed object.
        self.encoder = StateEncoder()
        self.priors = json.load(open(PRIORS_PATH))

        self.model = BCModel(
            self.encoder.n_species, self.encoder.n_moves,
            self.encoder.n_items, self.encoder.n_abilities,
        ).to(DEVICE)
        ckpt = load_checkpoint(MODEL_PATH, self.model, DEVICE)
        print(f"BC pilot loaded: epoch={ckpt.get('epoch')} "
              f"vlm={ckpt.get('val_move_acc'):.3f}", flush=True)

        self.move_mask = build_move_mask(self.priors, self.encoder, verbose=False).to(DEVICE)

        # Reverse maps for name lookup (id -> canonical name)
        self._move_by_idx = {v: k for k, v in self.encoder.move_idx.items()}
        self._species_by_idx = {v: k for k, v in self.encoder.species_idx.items()}

        super().__init__(*args, **kwargs)

    def _state_to_dict(self, battle: DoubleBattle):
        def mon_view(mon, is_opp=False):
            if mon is None or mon.species is None:
                return None
            revealed = []
            for mv in mon.moves.values():
                if mv is not None and mv.id:
                    revealed.append(mv.id.capitalize())
            return {
                "species": str(mon.species).replace(" ", "-"),
                "gender": getattr(mon, "gender", None),
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

        my_active = [mon_view(m) for m in battle.active_pokemon]
        my_bench = [mon_view(m) for m in battle.team.values()
                    if m not in battle.active_pokemon and not m.fainted]
        opp_active = [mon_view(m, True) for m in battle.opponent_active_pokemon]
        opp_seen = [mon_view(m, True) for m in battle.opponent_team.values()]

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

    def _predict_action(self, state_dict, slot_idx):
        enc = self.encoder.encode(state_dict)
        with torch.no_grad():
            ta, ma, sa, tb, mb, sb = self.model(
                enc["species_ids"].unsqueeze(0).to(DEVICE),
                enc["move_ids"].unsqueeze(0).to(DEVICE),
                enc["item_ids"].unsqueeze(0).to(DEVICE),
                enc["ability_ids"].unsqueeze(0).to(DEVICE),
                enc["continuous"].unsqueeze(0).to(DEVICE),
                enc["field"].unsqueeze(0).to(DEVICE),
            )

        if slot_idx == 0:
            type_logits, move_logits, switch_logits = ta, ma, sa
        else:
            type_logits, move_logits, switch_logits = tb, mb, sb

        my_active = state_dict["my_active"]
        acting = my_active[slot_idx] if slot_idx < len(my_active) else None
        if acting is None:
            return None
        sid = self.encoder.species_idx.get(acting["species"], 0)

        m_masked = move_logits + (1 - self.move_mask[sid]) * NEG_INF

        bench = state_dict["my_bench"]
        bench_mask = torch.zeros(self.encoder.n_species, device=DEVICE)
        for m in bench:
            if m is None:
                continue
            bid = self.encoder.species_idx.get(m["species"], 0)
            if bid:
                bench_mask[bid] = 1.0
        s_masked = switch_logits + (1 - bench_mask) * NEG_INF

        type_probs = F.softmax(type_logits, dim=-1)[0]
        p_move = type_probs[TYPE_MOVE].item() * F.softmax(m_masked, dim=-1).max().item()
        p_switch = type_probs[TYPE_SWITCH].item() * F.softmax(s_masked, dim=-1).max().item()

        if p_move >= p_switch:
            mid = m_masked.argmax().item()
            name = self._move_by_idx.get(mid)
            return ("move", name) if name else None

        sid_target = s_masked.argmax().item()
        name = self._species_by_idx.get(sid_target)
        return ("switch", name) if name else None

    def choose_move(self, battle):
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        state = self._state_to_dict(battle)
        orders = []

        for slot_idx, mon in enumerate(battle.active_pokemon):
            if mon is None or mon.fainted:
                orders.append(self.choose_random_move(battle))
                continue
            action = self._predict_action(state, slot_idx)
            if action is None:
                orders.append(self.choose_random_move(battle))
                continue

            kind, name = action
            if kind == "move":
                sd_id = _to_sd_id(name)
                chosen = next(
                    (mv for mv in mon.moves.values() if mv is not None and mv.id == sd_id),
                    None,
                )
                if chosen is None:
                    avail = [mv for mv in mon.moves.values() if mv is not None]
                    chosen = avail[0] if avail else None
                orders.append(self.create_order(chosen) if chosen
                              else self.choose_random_move(battle))
            else:
                target = next(
                    (m for m in battle.team.values()
                     if m.species and str(m.species).replace(" ", "-") == name),
                    None,
                )
                orders.append(self.create_order(target) if target
                              else self.choose_random_move(battle))

        from poke_env.player.battle_order import DoubleBattleOrder
        if len(orders) == 2:
            return DoubleBattleOrder(orders[0], orders[1])
        if len(orders) == 1:
            return orders[0]
        return self.choose_random_move(battle)