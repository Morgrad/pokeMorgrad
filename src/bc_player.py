"""BC pilot: wraps trained v4 model as a poke_env Player."""
import json
import os
import sys

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, os.path.expanduser("~/project/tools"))
sys.path.insert(0, os.path.expanduser("~/project/src"))

from poke_env.player import Player
from poke_env.battle import DoubleBattle
from state_encoder_v2 import StateEncoderV2, N_SLOTS, N_MOVES_PER, CONT_DIM
from bc_train_v4 import BCModelV4, TYPE_MOVE, TYPE_SWITCH, TYPE_NONE, NEG_INF

MODEL_PATH = os.path.expanduser("~/project/output/models/bc_v4_best.pt")
PRIORS_PATH = os.path.expanduser("~/project/data/species_move_priors.json")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


class BCPlayer(Player):
    def __init__(self, *args, **kwargs):
        # Load everything BEFORE super().__init__() so no async handler
        # fires against a half-constructed object.
        self.encoder = StateEncoderV2()
        self.priors = json.load(open(PRIORS_PATH))

        self.model = BCModelV4(
            self.encoder.n_species, self.encoder.n_moves,
            self.encoder.n_items, self.encoder.n_abilities,
        ).to(DEVICE)
        ckpt = torch.load(MODEL_PATH, map_location=DEVICE)
        self.model.load_state_dict(ckpt["model_state"])
        self.model.eval()
        print(f"BC pilot loaded: epoch={ckpt.get('epoch')} "
              f"vlm={ckpt.get('val_move_acc'):.3f}", flush=True)

        self.move_mask = self._build_move_mask()

        # Now safe to start the async listener
        super().__init__(*args, **kwargs)

    def _build_move_mask(self):
        mask = np.ones((self.encoder.n_species, self.encoder.n_moves),
                       dtype=np.float32)
        for sp_name, entries in self.priors.items():
            sid = self.encoder.species_idx.get(sp_name)
            if not sid:
                continue
            mask[sid, :] = 0.0
            for e in entries:
                mid = self.encoder.move_idx.get(e["move"])
                if mid:
                    mask[sid, mid] = 1.0
        return torch.from_numpy(mask).to(DEVICE)

    def _state_to_dict(self, battle: DoubleBattle):
        """Convert live battle to the encoder's expected state format."""
        def mon_view(mon, is_opp=False):
            if mon is None or mon.species is None:
                return None
            moves = []
            if not is_opp:
                # Own moves: full set is known
                for mv in mon.moves.values():
                    if mv is not None and mv.id:
                        moves.append(mv.id.capitalize())  # best-effort; encoder uses names
            else:
                # Opp moves: only revealed
                for mv in mon.moves.values():
                    if mv is not None and mv.id:
                        moves.append(mv.id.capitalize())
            return {
                "species": str(mon.species).replace(" ", "-"),
                "gender": getattr(mon, "gender", None),
                "hp_now": int(mon.current_hp_fraction * 100) if mon.current_hp_fraction is not None else None,
                "hp_max": 100,
                "status": mon.status.name.lower() if mon.status else None,
                "boosts": {k: v for k, v in mon.boosts.items() if v != 0},
                "revealed_moves": moves[:4],
                "item": None,
                "ability": None,
                "is_mega": False,
            }

        my_active = [mon_view(m) for m in battle.active_pokemon]
        my_bench = [mon_view(m) for m in battle.team.values()
                    if m not in battle.active_pokemon and not m.fainted]
        opp_active = [mon_view(m, True) for m in battle.opponent_active_pokemon]
        opp_seen = [mon_view(m, True) for m in battle.opponent_team.values()]

        # Field
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

    def _predict_action(self, state_dict, slot_idx, battle):
        enc = self.encoder.encode(state_dict)
        batch = {
            "species_ids": enc["species_ids"].unsqueeze(0).to(DEVICE),
            "move_ids": enc["move_ids"].unsqueeze(0).to(DEVICE),
            "item_ids": enc["item_ids"].unsqueeze(0).to(DEVICE),
            "ability_ids": enc["ability_ids"].unsqueeze(0).to(DEVICE),
            "continuous": enc["continuous"].unsqueeze(0).to(DEVICE),
            "field": enc["field"].unsqueeze(0).to(DEVICE),
        }
        with torch.no_grad():
            ta, ma, sa, tb, mb, sb = self.model(
                batch["species_ids"], batch["move_ids"], batch["item_ids"],
                batch["ability_ids"], batch["continuous"], batch["field"],
            )

        # Pick head for this slot
        if slot_idx == 0:
            type_logits, move_logits, switch_logits = ta, ma, sa
        else:
            type_logits, move_logits, switch_logits = tb, mb, sb

        # Get acting mon's species for mask
        my_active = state_dict["my_active"]
        acting = my_active[slot_idx] if slot_idx < len(my_active) else None
        if acting is None:
            return None
        sid = self.encoder.species_idx.get(acting["species"], 0)

        # Mask move logits
        m_mask = self.move_mask[sid]
        m_masked = move_logits + (1 - m_mask) * NEG_INF

        # Mask switch logits to bench only
        bench = state_dict["my_bench"]
        bench_mask = torch.zeros(self.encoder.n_species, device=DEVICE)
        for m in bench:
            if m is None:
                continue
            bid = self.encoder.species_idx.get(m["species"], 0)
            if bid:
                bench_mask[bid] = 1.0
        s_masked = switch_logits + (1 - bench_mask) * NEG_INF

        # Pick argmax across (type, move, switch) — score each type by best option
        type_probs = F.softmax(type_logits, dim=-1)[0]
        p_move = type_probs[TYPE_MOVE].item() * F.softmax(m_masked, dim=-1).max().item()
        p_switch = type_probs[TYPE_SWITCH].item() * F.softmax(s_masked, dim=-1).max().item()

        if p_move >= p_switch:
            chosen_type = TYPE_MOVE
        else:
            chosen_type = TYPE_SWITCH

        if chosen_type == TYPE_MOVE:
            mid = m_masked.argmax().item()
            # Reverse-lookup from encoder: idx -> name
            move_name = self.encoder.move_list[mid - 1] if mid > 0 else None
            return ("move", move_name)

        sid_target = s_masked.argmax().item()
        species = self.encoder.species_list[sid_target - 1] if sid_target > 0 else None
        return ("switch", species)

    def choose_move(self, battle):
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        state = self._state_to_dict(battle)
        orders = []

        for slot_idx, mon in enumerate(battle.active_pokemon):
            if mon is None or mon.fainted:
                orders.append(self.choose_random_move(battle))
                continue
            action = self._predict_action(state, slot_idx, battle)
            if action is None:
                orders.append(self.choose_random_move(battle))
                continue
            kind, name = action
            if kind == "move":
                # Find matching move id
                chosen = None
                for mv in mon.moves.values():
                    if mv is None or mv.id is None:
                        continue
                    real_name = self.encoder.move_list[0] if False else None
                    # match by comparing to encoder's canonical name for this id
                    mid = self.encoder.move_idx.get(name)
                    if mid is None:
                        continue
                    # poke_env's mv.id is the lowercase id; check if our encoder has it
                    for canon_name, canon_idx in self.encoder.move_idx.items():
                        if canon_idx == mid and canon_name.lower().replace(" ", "").replace("-", "") == mv.id:
                            chosen = mv
                            break
                    if chosen:
                        break
                if chosen is None:
                    # Fall back to first available
                    avail = [mv for mv in mon.moves.values() if mv is not None]
                    chosen = avail[0] if avail else None
                if chosen is not None:
                    orders.append(self.create_order(chosen))
                else:
                    orders.append(self.choose_random_move(battle))
            else:
                # switch
                chosen_mon = None
                for m in battle.team.values():
                    if m.species and str(m.species).replace(" ", "-") == name:
                        chosen_mon = m
                        break
                if chosen_mon is not None:
                    orders.append(self.create_order(chosen_mon))
                else:
                    orders.append(self.choose_random_move(battle))

        # Combine — DoubleBattleOrder
        from poke_env.player.battle_order import DoubleBattleOrder
        if len(orders) == 2:
            return DoubleBattleOrder(orders[0], orders[1])
        elif len(orders) == 1:
            return orders[0]
        else:
            return self.choose_random_move(battle)