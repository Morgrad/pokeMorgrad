"""Ladder-like opponent: the vanilla heuristic, plus Protect / Fake Out at human rates.

SimpleHeuristicsPlayer never Protects and never leads with Fake Out, so teams and pilots tuned
against it learn nothing about either. This wrapper keeps the heuristic's decision for every slot
and, for a mon that really carries Protect (or Fake Out, while it is its first turn out), swaps
that move in with the probability src.opp_actions measured on real ladder replays (the mon's own
moves count as revealed, so the rate is P(uses it | carries it)).
"""
from __future__ import annotations

import logging
import random
from typing import Optional

from poke_env.battle import DoubleBattle, Move
from poke_env.player import SimpleHeuristicsPlayer
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from src import opp_actions
from src.battle_memory import PROTECT_FAMILY, BattleMemoryMixin

logger = logging.getLogger(__name__)


def _variants(valid, base: SingleBattleOrder, move_ids) -> list:
    """Orders in `valid` using one of `move_ids`, keeping the base order's Mega flag."""
    return [o for o in valid if isinstance(getattr(o, "order", None), Move) and o.order.id in move_ids
            and o.mega == base.mega and not o.terastallize and not o.dynamax and not o.z_move]


class LadderOpponent(BattleMemoryMixin, SimpleHeuristicsPlayer):
    def __init__(self, *args, rng: Optional[random.Random] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.rng = rng or random.Random()
        self.stats_counter = {"turns": 0, "protect": 0, "fakeout": 0, "errors": 0}

    def choose_move(self, battle):
        base = super().choose_move(battle)
        if (not isinstance(battle, DoubleBattle) or not isinstance(base, DoubleBattleOrder)
                or any(battle.force_switch) or not battle.valid_orders):
            return base
        self.stats_counter["turns"] += 1
        try:
            return self._humanise(battle, base)
        except Exception:
            self.stats_counter["errors"] += 1
            logger.exception("LadderOpponent fell back to the heuristic order")
            return base

    def _humanise(self, battle: DoubleBattle, base: DoubleBattleOrder):
        mem = self.memory_for(battle)
        orders = [base.first_order, base.second_order]
        changed = False
        for slot, mon in enumerate(battle.active_pokemon):
            bo = orders[slot]
            if mon is None or mon.fainted or not isinstance(getattr(bo, "order", None), Move):
                continue
            valid = battle.valid_orders[slot]
            protects = _variants(valid, bo, PROTECT_FAMILY)
            fakeouts = _variants(valid, bo, {"fakeout"}) if mon.first_turn else []
            if not (protects or fakeouts):
                continue
            ctx = opp_actions.foe_ctx(mem, battle.player_role, mon.name, mem.turn,
                                      known_moves=[m.id for m in mon.moves.values()],
                                      moves_complete=True, hp_frac=mon.current_hp_fraction)
            p = opp_actions.action_probs(ctx)
            u = self.rng.random()
            if fakeouts and u < p.fakeout:
                orders[slot] = self.rng.choice(fakeouts)
                self.stats_counter["fakeout"] += 1
            elif protects and p.fakeout <= u < p.fakeout + p.protect:
                orders[slot] = protects[0]
                self.stats_counter["protect"] += 1
            else:
                continue
            changed = True
        return DoubleBattleOrder(orders[0], orders[1]) if changed else base
