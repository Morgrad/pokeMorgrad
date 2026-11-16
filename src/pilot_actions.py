from __future__ import annotations

from typing import Dict, Optional

from poke_env.battle import Move, Pokemon
from poke_env.player.battle_order import SingleBattleOrder

from src import damage, turn_sim
from src import doubles_eval as DE
from src import support_value as SV
from src.pilot_world import _is_attack_candidate


class PilotActionsMixin:
    effects: frozenset
    def _action(self, slot: int, order: SingleBattleOrder, world: Dict[str, DE.Combatant]) -> Optional[DE.Action]:
        move = getattr(order, "order", None)
        if not isinstance(move, Move) or not _is_attack_candidate(move, self.effects):
            return None
        return self._targeted(slot, order, move, world)

    @staticmethod

    def _targeted(slot: int, order: SingleBattleOrder, move: Move, world: Dict[str, DE.Combatant]) -> Optional[DE.Action]:
        target = (damage.DB.get_move(move.id).get("target") or "")
        foes = tuple(t for t in ("o0", "o1") if t in world)
        partner = f"a{1 - slot}"
        if target in ("normal", "any"):
            code = order.move_target
            if code not in (1, 2) or f"o{code - 1}" not in world:
                return None
            return DE.Action(slot, move.id, (f"o{code - 1}",))
        if target == "allAdjacentFoes":
            return DE.Action(slot, move.id, foes) if foes else None
        if target == "allAdjacent":
            tg = foes + ((partner,) if partner in world else ())
            return DE.Action(slot, move.id, tg) if foes else None
        return None

    # ---- decision -----------------------------------------------------------


    def _sim_kind(self, order: SingleBattleOrder) -> Optional[str]:
        o = getattr(order, "order", None)
        if isinstance(o, Pokemon):
            return "switch"
        if isinstance(o, Move):
            if _is_attack_candidate(o, self.effects):
                return "attack"
            if SV.pure_enabled(o.id, self.effects):
                return "support"
            if o.id in turn_sim.BLOCKING:
                return "protect"
            if o.id == turn_sim.FAKE_OUT:
                return "fakeout"
        return None


    def _sim_action(self, slot: int, order: SingleBattleOrder, mon: Pokemon, world: Dict[str, DE.Combatant],
                    bench: Dict[str, str]) -> Optional[DE.Action]:
        kind, o = self._sim_kind(order), order.order
        if kind == "attack":
            return self._action(slot, order, world)
        if kind == "protect":
            return DE.Action(slot, o.id, ())
        if kind == "support":
            pk = SV.pure_kind(o.id)
            if pk == "heal":
                return DE.Action(slot, o.id, ())
            if pk == "helpinghand":
                return DE.Action(slot, o.id, ()) if f"a{1 - slot}" in world else None
            # For taunt and other support moves that need targets (like Charm, Foul Play, etc.),
            # we use the same target resolution logic as attacks
            return self._targeted(slot, order, o, world)
        if kind == "switch":
            bid = bench.get(o.species)
            return DE.Action(slot, turn_sim.SWITCH, (bid,)) if bid else None
        if kind == "fakeout" and mon.first_turn and order.move_target in (1, 2) \
                and f"o{order.move_target - 1}" in world:
            return DE.Action(slot, turn_sim.FAKE_OUT, (f"o{order.move_target - 1}",))
        return None

