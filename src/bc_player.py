"""BC pilot — uses poke_env's valid_orders for action legality.

Design (v2, 2026-10-13):
  Rather than hand-filtering moves for PP/disabled/target-type (which was
  continuously producing Showdown rejections), the pilot asks poke_env for
  `battle.valid_orders` — the per-slot list of every legal SingleBattleOrder
  (moves with all valid targets, plus switches). The model scores each option;
  the argmax per slot becomes the choice. This eliminates the entire class of
  bugs around disabled moves, wrong targets, and malformed orders.

Cached model: encoder + model + priors + move mask are loaded once and shared
across all BCPlayer instances (eval loops create hundreds).
"""
import json
import os

import numpy as np
import torch
import torch.nn.functional as F

from poke_env.player import Player
from poke_env.battle import DoubleBattle
from poke_env.battle.pokemon import Pokemon
from poke_env.battle.move import Move
from poke_env.player.battle_order import DoubleBattleOrder

from src.state_encoder import StateEncoder
from src.bc_model import (
    BCModel, build_move_mask, load_checkpoint,
    TYPE_MOVE, TYPE_SWITCH,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(_REPO_ROOT, "output", "models", "bc_best.pt")
PRIORS_PATH = os.path.join(_REPO_ROOT, "data", "species_move_priors.json")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_MODEL_CACHE = {}


def _get_shared_model():
    """Load encoder + model + priors + move mask once, share across instances."""
    if DEVICE not in _MODEL_CACHE:
        encoder = StateEncoder()
        priors = json.load(open(PRIORS_PATH))
        model = BCModel(
            encoder.n_species, encoder.n_moves,
            encoder.n_items, encoder.n_abilities,
        ).to(DEVICE)
        ckpt = load_checkpoint(MODEL_PATH, model, DEVICE)
        mask = build_move_mask(priors, encoder, verbose=False).to(DEVICE)
        _MODEL_CACHE[DEVICE] = (encoder, model, priors, mask)
        print(f"BC pilot loaded (shared): epoch={ckpt.get('epoch')} "
              f"vlm={ckpt.get('val_move_acc'):.3f}", flush=True)
    return _MODEL_CACHE[DEVICE]


def _to_sd_id(name: str) -> str:
    """Match Pokémon Showdown's toID(): lowercase, alphanumeric only."""
    return "".join(c for c in name.lower() if c.isalnum())


class BCPlayer(Player):
    def __init__(self, *args, **kwargs):
        self.encoder, self.model, self.priors, self.move_mask = _get_shared_model()

        # Reverse/lookup maps
        self._species_by_sd_id = {_to_sd_id(k): k for k in self.encoder.species_idx}
        self._move_sd_to_idx = {_to_sd_id(k): v for k, v in self.encoder.move_idx.items()}

        super().__init__(*args, **kwargs)

    # ---- name normalization ----

    def _canonical_species(self, raw: str) -> str:
        if raw in self.encoder.species_idx:
            return raw
        return self._species_by_sd_id.get(_to_sd_id(raw), raw)

    def _canonical_move(self, sd_id: str):
        idx = self._move_sd_to_idx.get(sd_id, 0)
        return {v: k for k, v in self.encoder.move_idx.items()}.get(idx)

    # ---- state conversion (unchanged) ----

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

    # ---- scoring ----

    def _score_options(self, options, type_logits, move_logits, switch_logits):
        """Return a score per SingleBattleOrder option.

        Score = log P(type | state) + log P(action | type, state).
        Higher = model thinks this action is more likely.
        """
        type_lp = F.log_softmax(type_logits, dim=-1)
        move_lp = F.log_softmax(move_logits, dim=-1)
        switch_lp = F.log_softmax(switch_logits, dim=-1)

        scores = []
        for opt in options:
            order = opt.order
            if isinstance(order, Pokemon):
                sp = self._canonical_species(str(order.species))
                sid = self.encoder.species_idx.get(sp, 0)
                if sid == 0:
                    scores.append(float("-inf"))
                    continue
                score = (type_lp[TYPE_SWITCH] + switch_lp[sid]).item()
            elif isinstance(order, Move):
                idx = self._move_sd_to_idx.get(order.id, 0)
                if idx == 0:
                    scores.append(float("-inf"))
                    continue
                score = (type_lp[TYPE_MOVE] + move_lp[idx]).item()
            else:
                scores.append(float("-inf"))
                continue
            scores.append(score)
        return scores

    # ---- move selection ----

    def choose_move(self, battle):
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        valid = getattr(battle, "valid_orders", None)
        if not valid or len(valid) != 2 or not valid[0] or not valid[1]:
            return self.choose_random_move(battle)

        state = self._state_to_dict(battle)
        enc = self.encoder.encode(state)

        with torch.no_grad():
            ta, ma, sa, tb, mb, sb = self.model(
                enc["species_ids"].unsqueeze(0).to(DEVICE),
                enc["move_ids"].unsqueeze(0).to(DEVICE),
                enc["item_ids"].unsqueeze(0).to(DEVICE),
                enc["ability_ids"].unsqueeze(0).to(DEVICE),
                enc["continuous"].unsqueeze(0).to(DEVICE),
                enc["field"].unsqueeze(0).to(DEVICE),
            )

        scores_a = self._score_options(valid[0], ta[0], ma[0], sa[0])
        scores_b = self._score_options(valid[1], tb[0], mb[0], sb[0])

        ia = int(np.argmax(scores_a))
        ib = int(np.argmax(scores_b))
        best_a = valid[0][ia]
        best_b = valid[1][ib]

        # Handle switch collision: both slots want the same species.
        if (isinstance(best_a.order, Pokemon) and isinstance(best_b.order, Pokemon)
                and str(best_a.order.species) == str(best_b.order.species)):
            if scores_a[ia] >= scores_b[ib]:
                loser_valid, loser_scores, loser_i = valid[1], scores_b, ib
                loser_is_a = False
            else:
                loser_valid, loser_scores, loser_i = valid[0], scores_a, ia
                loser_is_a = True

            # Prefer a move; else a different switch; else keep original.
            move_idxs = [i for i, o in enumerate(loser_valid)
                         if isinstance(o.order, Move)]
            alt_switch_idxs = [
                i for i, o in enumerate(loser_valid)
                if isinstance(o.order, Pokemon)
                and str(o.order.species) != str(loser_valid[loser_i].order.species)
            ]
            if move_idxs:
                new_i = max(move_idxs, key=lambda i: loser_scores[i])
            elif alt_switch_idxs:
                new_i = max(alt_switch_idxs, key=lambda i: loser_scores[i])
            else:
                new_i = loser_i

            if loser_is_a:
                best_a = loser_valid[new_i]
            else:
                best_b = loser_valid[new_i]

        return DoubleBattleOrder(best_a, best_b)
