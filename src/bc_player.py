"""BC pilot — wraps a trained BC model as a poke_env Player.

Design notes:
  * All name lookups normalize through `_to_sd_id` (lowercase alphanumeric),
    matching both Showdown's `mv.id` format and poke_env's species display.
  * Move masking prefers the LIVE moveset (all 4 moves known for our own mon)
    over species priors. Falls back to priors only if `battle_mon` isn't given.
  * In doubles, move orders MUST include a target (Showdown rejects otherwise).
    Slot 0 targets opponent slot 1; slot 1 targets opponent slot 2.
  * `choose_move` returns a proper `DoubleBattleOrder` when both slots succeed.
    If either slot fails, it returns a single random double-order for the whole
    turn — never a nested DoubleBattleOrder (which Showdown rejects).
"""
import json
import os

import torch
import torch.nn.functional as F

from poke_env.player import Player
from poke_env.battle import DoubleBattle
from poke_env.player.battle_order import DoubleBattleOrder

from src.state_encoder import StateEncoder
from src.bc_model import (
    BCModel, build_move_mask, load_checkpoint,
    NEG_INF, TYPE_MOVE, TYPE_SWITCH,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(_REPO_ROOT, "output", "models", "bc_best.pt")
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

        self.move_mask = build_move_mask(
            self.priors, self.encoder, verbose=False
        ).to(DEVICE)

        # Reverse maps: index -> canonical name
        self._move_by_idx = {v: k for k, v in self.encoder.move_idx.items()}
        self._species_by_idx = {v: k for k, v in self.encoder.species_idx.items()}
        # SD-id -> canonical name (for species display matching)
        self._species_by_sd_id = {_to_sd_id(k): k for k in self.encoder.species_idx}
        # SD-id -> encoder index (fast live-move masking)
        self._move_sd_to_idx = {_to_sd_id(k): v for k, v in self.encoder.move_idx.items()}

        super().__init__(*args, **kwargs)

    # ---- name normalization ----

    def _canonical_species(self, raw: str) -> str:
        if raw in self.encoder.species_idx:
            return raw
        return self._species_by_sd_id.get(_to_sd_id(raw), raw)

    def _canonical_move(self, sd_id: str):
        return self._move_by_idx.get(self._move_sd_to_idx.get(sd_id, 0))

    # ---- state conversion ----

    def _state_to_dict(self, battle: DoubleBattle):
        def mon_view(mon, is_opp=False):
            if mon is None or mon.species is None:
                return None
            revealed = []
            for mv in mon.moves.values():
                if mv is None or not mv.id:
                    continue
                name = self._canonical_move(mv.id)
                if name:
                    revealed.append(name)
            return {
                "species": self._canonical_species(str(mon.species)),
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

    # ---- prediction ----

    def _live_moveset_mask(self, battle_mon):
        """Fast: O(4) lookups. Only moves with PP>0 that the mon actually knows."""
        mask = torch.zeros((1, self.encoder.n_moves), dtype=torch.float32, device=DEVICE)
        if battle_mon is None or not battle_mon.moves:
            return mask
        for mv in battle_mon.moves.values():
            if mv is None or not mv.id:
                continue
            if getattr(mv, "current_pp", 1) <= 0:
                continue
            idx = self._move_sd_to_idx.get(mv.id)
            if idx:
                mask[0, idx] = 1.0
        return mask

    def _predict_action(self, state_dict, slot_idx, battle_mon=None):
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
        if sid == 0:
            return None

        if battle_mon is not None and battle_mon.moves:
            lm = self._live_moveset_mask(battle_mon)
            m_masked = move_logits + (1 - lm) * NEG_INF
        else:
            m_masked = move_logits + (1 - self.move_mask[sid].unsqueeze(0)) * NEG_INF

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

    # ---- order construction ----

    def _build_slot_order(self, slot_idx, mon, state, battle):
        if mon is None or mon.fainted:
            return None
        action = self._predict_action(state, slot_idx, battle_mon=mon)
        if action is None:
            return None
        kind, name = action

        if kind == "move":
            sd_id = _to_sd_id(name)
            chosen = next(
                (mv for mv in mon.moves.values()
                 if mv is not None and mv.id == sd_id
                 and getattr(mv, "current_pp", 1) > 0),
                None,
            )
            if chosen is None:
                avail = [mv for mv in mon.moves.values()
                         if mv is not None and getattr(mv, "current_pp", 1) > 0]
                chosen = avail[0] if avail else None
            if chosen is None:
                return None

            # Decide target based on move type and live opponent slots.
            from src.regmc_db import get_move
            canonical = self._canonical_move(chosen.id) or name
            move_data = get_move(canonical) or {}
            target_type = move_data.get("target", "normal")
            needs_target = target_type in (
                "normal", "adjacentAlly", "adjacentAllyOrSelf",
            )
            if not needs_target:
                return self.create_order(chosen)

            # Slot numbers in Showdown doubles:
            #   1 = opp left, 2 = opp right, -1 = our left ally, -2 = our right ally
            if target_type in ("adjacentAlly", "adjacentAllyOrSelf"):
                # Target ally (or self if no ally)
                ally_slot = -1 if slot_idx == 1 else -2
                return self.create_order(chosen, move_target=ally_slot)

            # Single-target move: pick a live opponent slot
            opp_actives = battle.opponent_active_pokemon
            live_slots = [i + 1 for i, m in enumerate(opp_actives)
                          if m is not None and not m.fainted]
            if not live_slots:
                return self.create_order(chosen)  # let Showdown pick; rare
            preferred = slot_idx + 1
            target = preferred if preferred in live_slots else live_slots[0]
            return self.create_order(chosen, move_target=target)

    def choose_move(self, battle):
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        state = self._state_to_dict(battle)

        # If EITHER slot fails, issue a single random double-order for the
        # whole turn. poke_env's choose_random_move() already returns a
        # DoubleBattleOrder, and nesting that inside another DoubleBattleOrder
        # produces a malformed 3-part command that Showdown rejects.
        orders = []
        failed = False
        for slot_idx, mon in enumerate(battle.active_pokemon):
            order = self._build_slot_order(slot_idx, mon, state, battle)
            if order is None:
                failed = True
                break
            orders.append(order)

        if failed or len(orders) != 2:
            return self.choose_random_move(battle)

        return DoubleBattleOrder(orders[0], orders[1])
