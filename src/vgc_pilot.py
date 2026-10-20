"""VGC pilot (thin layer): DoublesPilot + battle memory + Mega logic.

Policy is predictive by default (opp_model priors); it never requires Open Team Sheets.
Own Mega: once per battle, as soon as a slot can (79% of real Megas happen on the first
opportunity; win rate shows no gain from delaying). When both slots can, the mon with the larger
offence gain goes first (humans do 74%). Foe Mega: src.mega_model gives P(Mega this turn) per
foe mon, and the damage hypotheses are split into pre/post-Mega stats with that probability.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from poke_env.battle import DoubleBattle, Move
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from src import opp_actions
from src.battle_memory import BattleMemoryMixin
from src.doubles_pilot import DoublesPilot
from src.mega_model import foe_mega_probs, mega_gain
from src.opp_model import resolve_species

logger = logging.getLogger(__name__)


def mega_variant(order: SingleBattleOrder, valid) -> Optional[SingleBattleOrder]:
    """The mega=True twin of `order` (same move, same target) among `valid`, if any."""
    if not isinstance(getattr(order, "order", None), Move) or order.mega:
        return None
    for o in valid:
        if (o.mega and isinstance(o.order, Move) and o.order.id == order.order.id
                and o.move_target == order.move_target):
            return o
    return None


def add_mega(battle: DoubleBattle, base, mega_free: bool, score=None):
    """Return (order, slot) with Mega added to one slot, else (base, None).

    Candidates are slots that can Mega and whose base order is a move with a Mega twin; the
    highest `score(slot)` wins (ties and no score: lower slot)."""
    if not mega_free or not isinstance(base, DoubleBattleOrder) or not battle.valid_orders:
        return base, None
    orders = [base.first_order, base.second_order]
    twins = {slot: mega_variant(orders[slot], battle.valid_orders[slot]) for slot in (0, 1)
             if battle.can_mega_evolve[slot]}
    twins = {slot: t for slot, t in twins.items() if t is not None}
    if not twins:
        return base, None
    slot = max(twins, key=lambda sl: ((score(sl) if score else 0), -sl))
    orders[slot] = twins[slot]
    return DoubleBattleOrder(orders[0], orders[1]), slot


class VGCPilot(BattleMemoryMixin, DoublesPilot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stats_counter.update({"mega_opportunities": 0, "mega_used": 0, "mega_errors": 0,
                                   "foe_mega_errors": 0, "foe_mega_turns": 0})
        self._foe_mega: dict = {}
        self.foe_actions = os.environ.get("DOUBLES_FOE_ACTIONS", "1") == "1"

    def _foe_probs(self, mon, battle) -> Optional[tuple]:
        if not self.foe_actions:
            return None
        side = "p2" if battle.player_role == "p1" else "p1"
        mem = self.memory_for(battle)
        sheet = mem.ots_set(mon.species, side)
        known = set(mon.moves) | set((sheet or {}).get("moves") or ())
        ctx = opp_actions.foe_ctx(mem, side, mon.name, mem.turn, known_moves=known,
                                  moves_complete=bool(sheet), hp_frac=mon.current_hp_fraction)
        return opp_actions.action_probs(ctx), mem.protect_success_prob(f"{side}a: {mon.name}", mem.turn)

    def _foe_action_probs(self, mon, battle) -> tuple:
        got = self._foe_probs(mon, battle)
        if got is None:
            return 0.0, 0.0, 1.0
        probs, ok = got
        return probs.fakeout, probs.protect, ok

    def _foe_trick_room_prob(self, mon, battle) -> float:
        got = self._foe_probs(mon, battle)
        return got[0].trickroom if got else 0.0

    def _mega_prob(self, mon) -> float:
        return self._foe_mega.get(mon.name, 0.0)

    @staticmethod
    def _mega_score(battle, slot):
        mon = battle.active_pokemon[slot]
        return mega_gain(resolve_species(mon.species) or "", mon.item or "") or (-1, -1)

    def choose_move(self, battle):
        self._foe_mega = {}
        if isinstance(battle, DoubleBattle):
            try:
                foe = "p2" if battle.player_role == "p1" else "p1"
                self._foe_mega = foe_mega_probs(self.memory_for(battle), foe)
                self.stats_counter["foe_mega_turns"] += bool(self._foe_mega)
            except Exception:
                self.stats_counter["foe_mega_errors"] += 1
                logger.exception("foe Mega prediction failed; assuming none")
        order = super().choose_move(battle)
        if not isinstance(battle, DoubleBattle) or any(battle.force_switch):
            return order
        try:
            mem = self.memory_for(battle)
            free = mem.mega_available(battle.player_role)
            if free and any(battle.can_mega_evolve):
                self.stats_counter["mega_opportunities"] += 1
            order, slot = add_mega(battle, order, free, lambda sl: self._mega_score(battle, sl))
            if slot is not None:
                self.stats_counter["mega_used"] += 1
        except Exception:
            self.stats_counter["mega_errors"] += 1
            logger.exception("VGCPilot Mega step failed; keeping base order")
        return order
