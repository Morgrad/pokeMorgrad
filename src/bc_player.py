"""BC pilot — uses poke_env's valid_orders for action legality.

Supports v2 (MLP, 6 heads) and v3 (transformer, 8 heads with target head).
Checkpoint `arch` field decides which. Override the model via
BC_PILOT_PATH env var (default: output/models/bc_best.pt).

For v3, the target head contributes to option scoring so that
"move X targeting opp-left" and "move X targeting opp-right" get
different scores instead of being arbitrary tie-breaks.
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
    BCModel, BCModelV3, build_move_mask,
    TYPE_MOVE, TYPE_SWITCH,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_PATH = os.path.join(_REPO_ROOT, "output", "models", "bc_best.pt")
MODEL_PATH = os.environ.get("BC_PILOT_PATH", DEFAULT_MODEL_PATH)
PRIORS_PATH = os.path.join(_REPO_ROOT, "data", "species_move_priors.json")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_MODEL_CACHE = {}

# Showdown SingleBattleOrder.move_target → training-time target_idx
#   0  = no target (self / spread)  → 2
#   -1 = our left ally              → 1
#   -2 = our right ally             → 0
#   1  = opponent left              → 3
#   2  = opponent right             → 4
_TARGET_MAP = {0: 2, -1: 1, -2: 0, 1: 3, 2: 4}


def _get_shared_model():
    """Load encoder + model + priors + move mask once; cache by DEVICE.

    This is the LIVE checkpoint read site. The keys read from the saved payload
    — `arch`, `model_state`, `val_target_acc`, `val_move_acc`, `epoch` — are the
    checkpoint contract (see bc_model.save_checkpoint). `arch` decides the class
    (v3 -> BCModelV3 else BCModel); instantiating the wrong one makes
    load_state_dict fail. Never rename these keys. Cached per DEVICE because
    poke_env may spin up many BCPlayer instances per run and the GPU load is
    expensive — all of them share one model.
    """
    if DEVICE not in _MODEL_CACHE:
        encoder = StateEncoder()
        priors = json.load(open(PRIORS_PATH))

        raw = torch.load(MODEL_PATH, map_location=DEVICE)
        arch = raw.get("arch") or "v2"   # `or`: bc_best.pt stores arch=None (pre-arch ckpt)

        if arch == "v3":
            model = BCModelV3(encoder.n_species, encoder.n_moves,
                              encoder.n_items, encoder.n_abilities)
        else:
            model = BCModel(encoder.n_species, encoder.n_moves,
                            encoder.n_items, encoder.n_abilities)
        model = model.to(DEVICE)
        model.load_state_dict(raw["model_state"])
        model.eval()

        mask = build_move_mask(priors, encoder, verbose=False).to(DEVICE)
        _MODEL_CACHE[DEVICE] = (encoder, model, priors, mask, arch)

        tgt = raw.get("val_target_acc")
        tgt_str = f" vltg={tgt:.3f}" if tgt is not None else ""
        vlm = raw.get("val_move_acc", float("nan"))
        print(f"BC pilot loaded ({arch}): epoch={raw.get('epoch')} "
              f"vlm={vlm:.3f}{tgt_str}", flush=True)
    return _MODEL_CACHE[DEVICE]


def _to_sd_id(name: str) -> str:
    """Match Pokémon Showdown's toID(): lowercase, alphanumeric only."""
    return "".join(c for c in name.lower() if c.isalnum())


class BCPlayer(Player):
    """poke_env Player driven by the BC model.

    The model proposes; poke_env's `valid_orders` disposes — we only ever score
    and pick among orders poke_env already certified legal, so the pilot cannot
    emit an illegal command (the old loop bug; see STATE.md §5.1). Any time the
    state looks unexpected we fall back to choose_random_move rather than risk a
    reject/retry loop. The shared model/encoder/mask come from the module cache;
    the per-instance dicts below translate between Showdown ids and our vocab.
    """

    def __init__(self, *args, **kwargs):
        self.encoder, self.model, self.priors, self.move_mask, self.arch = \
            _get_shared_model()

        self._species_by_sd_id = {_to_sd_id(k): k for k in self.encoder.species_idx}
        self._move_sd_to_idx = {_to_sd_id(k): v for k, v in self.encoder.move_idx.items()}
        self._move_idx_to_name = {v: k for k, v in self.encoder.move_idx.items()}

        super().__init__(*args, **kwargs)

    def _canonical_species(self, raw: str) -> str:
        if raw in self.encoder.species_idx:
            return raw
        return self._species_by_sd_id.get(_to_sd_id(raw), raw)

    def _canonical_move(self, sd_id: str):
        idx = self._move_sd_to_idx.get(sd_id, 0)
        return self._move_idx_to_name.get(idx)

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

    # ---- scoring ----

    # Moves that legitimately target an ally in VGC doubles.
    # Everything else targeting -1/-2 is almost always a misclick and
    # we strongly discourage it. See docs/STATE.md §BC pilot notes.
    ALLY_TARGET_MOVES = {
        "helpinghand", "decorate", "coaching", "healpulse", "floralhealing",
        "lifedew", "junglehealing", "pollenpuff", "followme", "ragepowder",
        "afteryou", "instruct", "quash", "swagger", "flatter",
    }

    ALLY_TARGET_PENALTY = 5.0

    def _score_options(self, options, type_logits, move_logits, switch_logits,
                       target_logits=None):
        """Score each SingleBattleOrder option.

        Score = log P(type) + log P(move|type) [+ log P(target|move)]
              [+ ally-target penalty], or
              log P(type) + log P(switch|type) for switches.
        """
        type_lp = F.log_softmax(type_logits, dim=-1)
        move_lp = F.log_softmax(move_logits, dim=-1)
        switch_lp = F.log_softmax(switch_logits, dim=-1)
        target_lp = (F.log_softmax(target_logits, dim=-1)
                     if target_logits is not None else None)

        scores = []
        for opt in options:
            order = opt.order
            if isinstance(order, Pokemon):
                sp = self._canonical_species(str(order.species))
                sid = self.encoder.species_idx.get(sp, 0)
                if sid == 0:
                    scores.append(float("-inf"))
                    continue
                scores.append((type_lp[TYPE_SWITCH] + switch_lp[sid]).item())
            elif isinstance(order, Move):
                idx = self._move_sd_to_idx.get(order.id, 0)
                if idx == 0:
                    scores.append(float("-inf"))
                    continue
                s = (type_lp[TYPE_MOVE] + move_lp[idx]).item()
                if target_lp is not None:
                    tidx = _TARGET_MAP.get(opt.move_target, 2)
                    s += target_lp[tidx].item()

                # Discourage ally-targeting for moves that aren't actually
                # ally-targets. Without this, v2 (no target head) always
                # picked -2 (our right ally) for damaging moves because
                # poke_env lists it first in valid_orders.
                if opt.move_target in (-1, -2):
                    move_name = self._move_idx_to_name.get(idx, "")
                    sd = _to_sd_id(move_name)
                    if sd not in self.ALLY_TARGET_MOVES:
                        s -= self.ALLY_TARGET_PENALTY
                scores.append(s)
            else:
                scores.append(float("-inf"))
        return scores

    # ---- move selection ----

    def choose_move(self, battle):
        """Pick a double order: score each slot's legal options, resolve clashes.

        Guards first: singles battle or malformed valid_orders -> random. Then
        encode once, run the model once, score slot a and slot b independently,
        argmax each. The one subtle case is a SWITCH collision — both slots
        choosing the same bench mon is illegal — so the lower-scoring slot is
        rerouted to its best move (or an alternative switch) instead.
        """
        if not isinstance(battle, DoubleBattle):
            return self.choose_random_move(battle)

        valid = getattr(battle, "valid_orders", None)
        if not valid or len(valid) != 2 or not valid[0] or not valid[1]:
            return self.choose_random_move(battle)

        state = self._state_to_dict(battle)
        enc = self.encoder.encode(state)

        with torch.no_grad():
            outs = self.model(
                enc["species_ids"].unsqueeze(0).to(DEVICE),
                enc["move_ids"].unsqueeze(0).to(DEVICE),
                enc["item_ids"].unsqueeze(0).to(DEVICE),
                enc["ability_ids"].unsqueeze(0).to(DEVICE),
                enc["continuous"].unsqueeze(0).to(DEVICE),
                enc["field"].unsqueeze(0).to(DEVICE),
            )

        if self.arch == "v3":
            ta, ma, sa, tga, tb, mb, sb, tgb = outs
        else:
            ta, ma, sa, tb, mb, sb = outs
            tga = tgb = None

        scores_a = self._score_options(valid[0], ta[0], ma[0], sa[0],
                                       tga[0] if tga is not None else None)
        scores_b = self._score_options(valid[1], tb[0], mb[0], sb[0],
                                       tgb[0] if tgb is not None else None)

        ia = int(np.argmax(scores_a))
        ib = int(np.argmax(scores_b))
        best_a = valid[0][ia]
        best_b = valid[1][ib]

        # Switch collision: both slots want the same Pokémon.
        if (isinstance(best_a.order, Pokemon) and isinstance(best_b.order, Pokemon)
                and str(best_a.order.species) == str(best_b.order.species)):
            if scores_a[ia] >= scores_b[ib]:
                loser_valid, loser_scores, loser_i, loser_is_a = \
                    valid[1], scores_b, ib, False
            else:
                loser_valid, loser_scores, loser_i, loser_is_a = \
                    valid[0], scores_a, ia, True

            move_idxs = [i for i, o in enumerate(loser_valid)
                         if isinstance(o.order, Move)]
            alt_switch_idxs = [
                i for i, o in enumerate(loser_valid)
                if isinstance(o.order, Pokemon)
                and str(o.order.species) != str(loser_valid[loser_i].order.species)
            ]
            if move_idxs:
                new_i = max(move_idxs, key=lambda i: loser_scores[i])
                if loser_is_a:
                    best_a = loser_valid[new_i]
                else:
                    best_b = loser_valid[new_i]
            elif alt_switch_idxs:
                new_i = max(alt_switch_idxs, key=lambda i: loser_scores[i])
                if loser_is_a:
                    best_a = loser_valid[new_i]
                else:
                    best_b = loser_valid[new_i]
            else:
                # No alternative for the loser slot — every legal action is a
                # switch to the same Pokemon. Showdown rejects double-same-
                # switch and we'd loop forever. Bail out to a random legal
                # double-order for the whole turn instead.
                return self.choose_random_move(battle)

        return DoubleBattleOrder(best_a, best_b)
