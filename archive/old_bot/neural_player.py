import json
import torch
import torch.nn as nn
import random
import sys
from poke_env.player import Player
from poke_env.player.battle_order import DoubleBattleOrder
from poke_env.battle.move import Move
from tactical_rules import RuleEngine


class MovePredictor(nn.Module):
    def __init__(self, n_species, n_moves, embed_dim=32):
        super().__init__()
        self.species_emb = nn.Embedding(n_species, embed_dim)
        self.opp_emb = nn.Embedding(n_species, embed_dim)
        self.turn_emb = nn.Embedding(21, 8)
        self.net = nn.Sequential(
            nn.Linear(embed_dim * 2 + 8, 256), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(256, 256), nn.ReLU(),
            nn.Linear(256, n_moves),
        )

    def forward(self, x):
        my = self.species_emb(x[:, 0])
        opp = self.opp_emb(x[:, 1])
        turn = self.turn_emb(x[:, 2])
        return self.net(torch.cat([my, opp, turn], dim=-1))


def _active_list(field):
    if field is None:
        return []
    return field if isinstance(field, list) else [field]


def _first_mon(field):
    if field is None:
        return None
    if isinstance(field, list):
        for p in field:
            if p is not None and not getattr(p, "fainted", False):
                return p
        return None
    return field


def _can_mega(battle, mon):
    if mon is None:
        return False
    try:
        if not getattr(battle, "can_mega_evolve", False):
            return False
        item = getattr(mon, "item", None)
        if not item:
            return False
        return "ite" in str(item).lower().replace(" ", "").replace("-", "")
    except Exception:
        return False


class NeuralPlayer(Player):
    def __init__(self, model_path="bc_model.pt", vocab_path="vocab.json",
                 temperature=1.0, rules_enabled=None, **kwargs):
        with open(vocab_path) as f:
            v = json.load(f)
        self.species_vocab = v["species"]
        self.move_vocab = v["moves"]

        def _norm(x):
            return x.lower().replace(" ", "").replace("-", "").replace("'", "")

        self.move_vocab_n = {_norm(k): i for k, i in self.move_vocab.items()}
        self.species_vocab_n = {_norm(k): i for k, i in self.species_vocab.items()}
        self.temperature = temperature
        self._mega_done = set()
        self.rules = RuleEngine(enabled=rules_enabled)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.device = device
        self.model = MovePredictor(len(self.species_vocab), len(self.move_vocab)).to(device)
        self.model.load_state_dict(torch.load(model_path, map_location=device))
        self.model.eval()
        super().__init__(**kwargs)

    def _species_idx(self, name):
        if name is None:
            return 0
        key = name.lower().replace(" ", "").replace("-", "").replace("'", "")
        if key in self.species_vocab_n:
            return self.species_vocab_n[key]
        for suf in ["megay", "megax", "mega", "alola", "hisui", "galar"]:
            if key.endswith(suf):
                k2 = key[: -len(suf)]
                if k2 in self.species_vocab_n:
                    return self.species_vocab_n[k2]
        return 0

    def _predict_probs(self, my_mon, opp_mon, turn):
        x = torch.tensor([[
            self._species_idx(str(my_mon.species)),
            self._species_idx(str(opp_mon.species) if opp_mon else "None"),
            min(turn, 20),
        ]], dtype=torch.long, device=self.device)
        with torch.no_grad():
            logits = self.model(x)[0]
            return torch.softmax(logits / self.temperature, dim=-1).cpu().numpy()

    def _best_action(self, battle, me, opp, turn, legal_moves, legal_switches, slot_idx):
        """Score moves AND switches, apply tactical rules, return winner (Move or Pokemon)."""
        if me is None:
            return random.choice(legal_moves) if legal_moves else None

        # Get NN probs
        probs = None
        try:
            probs = self._predict_probs(me, opp, turn)
        except Exception:
            pass

        best, best_score = None, -1.0

        # Score moves
        if probs is not None and legal_moves:
            for m in legal_moves:
                n = m.id.lower().replace(" ", "").replace("-", "").replace("'", "")
                idx = self.move_vocab_n.get(n)
                if idx is None:
                    continue
                base = float(probs[idx])
                mult = self.rules.move_multiplier(battle, me, m.id, slot_idx=slot_idx)
                score = base * mult
                if score > best_score:
                    best_score = score
                    best = m

        # Score switches (only when rules say we should consider)
        switch_score = self.rules.switch_base_score(battle, me, slot_idx)
        if switch_score > 0 and legal_switches:
            # Pick the healthiest switch-in
            best_switch = max(legal_switches,
                              key=lambda p: (getattr(p, "current_hp_fraction", 0) or 0))
            if switch_score > best_score:
                best_score = switch_score
                best = best_switch

        # Fallback
        if best is None and legal_moves:
            best = random.choice(legal_moves)
        return best

    def _target_slot_for(self, battle, move):
        """For foe-targeting moves, pick the opponent with lower HP."""
        opps = getattr(battle, "opponent_active_pokemon", None)
        if opps is None:
            return 1
        if not isinstance(opps, list):
            return 1
        if len(opps) < 2:
            return 1
        p1, p2 = opps[0], opps[1]
        hp1 = (getattr(p1, "current_hp_fraction", 1.0) or 1.0) if p1 is not None else 1.0
        hp2 = (getattr(p2, "current_hp_fraction", 1.0) or 1.0) if p2 is not None else 1.0
        return 1 if hp1 <= hp2 else 2

    def _make_order(self, battle, move, mega):
        if move is None:
            return self.choose_random_move(battle)
        try:
            if not isinstance(battle.active_pokemon, list):
                return self.create_order(move, mega=mega)
            t_obj = getattr(move, "target", None)
            candidates = []
            if t_obj is not None:
                if hasattr(t_obj, "name"):
                    candidates.append(str(t_obj.name))
                if hasattr(t_obj, "value"):
                    candidates.append(str(t_obj.value))
                candidates.append(str(t_obj))
            normed = [c.lower().replace("_", "").replace("-", "").replace(" ", "")
                      for c in candidates]
            if any(c in ("adjacentally", "adjacentallyorself", "ally", "allies") for c in normed):
                return self.create_order(move, mega=mega, move_target=-1)
            if any(c in ("normal", "any", "adjacentfoe") for c in normed):
                target = self._target_slot_for(battle, move)
                return self.create_order(move, mega=mega, move_target=target)
            return self.create_order(move, mega=mega)
        except Exception as e:
            print(f"[ORDER-FAIL] {type(e).__name__}: {e} | move={getattr(move,'id','?')}",
                  file=sys.stderr)
            return self.choose_random_move(battle)

    def choose_move(self, battle):
        if getattr(battle, "teampreview", False):
            return self.choose_random_move(battle)

        # Sync rule state
        self.rules.observe(battle)

        moves_field = battle.available_moves
        if not moves_field:
            return self.choose_random_move(battle)

        switches_field = battle.available_switches or []
        actives = _active_list(battle.active_pokemon)
        opps = _active_list(battle.opponent_active_pokemon)
        tag = getattr(battle, "battle_tag", None)
        already_mega = tag in self._mega_done

        if len(self._mega_done) > 200:
            self._mega_done = set(list(self._mega_done)[-100:])

        # ---------- Singles ----------
        if not isinstance(moves_field[0], list):
            me = _first_mon(battle.active_pokemon)
            opp = _first_mon(battle.opponent_active_pokemon)
            if me is None:
                return self.choose_random_move(battle)
            slot_switches = switches_field if switches_field else []
            chosen = self._best_action(battle, me, opp, battle.turn,
                                       moves_field, slot_switches, 0)
            if chosen is None:
                return self.choose_random_move(battle)
            self.rules.record_move(battle, me, chosen)

            if isinstance(chosen, Move):
                do_mega = (not already_mega) and _can_mega(battle, me)
                if do_mega and tag:
                    self._mega_done.add(tag)
                return self._make_order(battle, chosen, do_mega)
            return self.create_order(chosen)

        # ---------- Doubles ----------
        slot_orders = []
        mega_used_this_turn = already_mega

        for slot_idx, slot_moves in enumerate(moves_field):
            if not slot_moves:
                slot_orders.append(None)
                continue

            me = actives[slot_idx] if slot_idx < len(actives) else None

            # Opponent for this slot
            opp_slot = None
            if slot_idx == 0 and len(opps) >= 1:
                opp_slot = opps[0]
            elif slot_idx == 1 and len(opps) >= 2:
                opp_slot = opps[1]
            elif len(opps) >= 1:
                opp_slot = opps[0]

            slot_switches = []
            if switches_field and isinstance(switches_field[0], list):
                slot_switches = switches_field[slot_idx] if slot_idx < len(switches_field) else []
            elif switches_field:
                slot_switches = switches_field

            chosen = self._best_action(battle, me, opp_slot, battle.turn,
                                       slot_moves, slot_switches, slot_idx)
            if chosen is None:
                slot_orders.append(None)
                continue

            self.rules.record_move(battle, me, chosen)

            if isinstance(chosen, Move):
                do_mega = (not mega_used_this_turn) and _can_mega(battle, me)
                if do_mega:
                    mega_used_this_turn = True
                    if tag:
                        self._mega_done.add(tag)
                slot_orders.append(self._make_order(battle, chosen, do_mega))
            else:
                # Switch
                slot_orders.append(self.create_order(chosen))

        valid = [o for o in slot_orders if o is not None]
        if len(valid) == 0:
            return self.choose_random_move(battle)
        if len(valid) == 1:
            return valid[0]
        return DoubleBattleOrder(valid[0], valid[1])
