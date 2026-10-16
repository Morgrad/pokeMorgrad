"""VGC pilot (thin first layer): DoublesPilot + battle memory + Mega on first opportunity.

Policy is predictive by default (opp_model priors); it never requires Open Team Sheets.
Mega: our side may Mega once per battle, and 79% of real Megas happen on the mon's first
opportunity, so we Mega as soon as a slot can, on the order the base layer already chose.
"""
from __future__ import annotations

import logging
from typing import Optional

from poke_env.battle import DoubleBattle, Move
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from src.battle_memory import BattleMemoryMixin
from src.doubles_pilot import DoublesPilot

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


def add_mega(battle: DoubleBattle, base, mega_free: bool):
    """Return (order, slot) with Mega added to the first slot that can use it, else (base, None)."""
    if not mega_free or not isinstance(base, DoubleBattleOrder) or not battle.valid_orders:
        return base, None
    orders = [base.first_order, base.second_order]
    for slot in (0, 1):
        if not battle.can_mega_evolve[slot]:
            continue
        twin = mega_variant(orders[slot], battle.valid_orders[slot])
        if twin is None:
            continue
        orders[slot] = twin
        return DoubleBattleOrder(orders[0], orders[1]), slot
    return base, None


class VGCPilot(BattleMemoryMixin, DoublesPilot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stats_counter.update({"mega_opportunities": 0, "mega_used": 0, "mega_errors": 0})

    def choose_move(self, battle):
        order = super().choose_move(battle)
        if not isinstance(battle, DoubleBattle) or any(battle.force_switch):
            return order
        try:
            mem = self.memory_for(battle)
            free = mem.mega_available(battle.player_role)
            if free and any(battle.can_mega_evolve):
                self.stats_counter["mega_opportunities"] += 1
            order, slot = add_mega(battle, order, free)
            if slot is not None:
                self.stats_counter["mega_used"] += 1
        except Exception:
            self.stats_counter["mega_errors"] += 1
            logger.exception("VGCPilot Mega step failed; keeping base order")
        return order
