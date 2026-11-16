from __future__ import annotations

from typing import Optional

from poke_env.battle import DoubleBattle, Effect, Field, Pokemon

from src import doubles_eval as DE
from src import opp_model, speed_model, turn_sim
from src.pilot_world import _is_attack_candidate


class PilotSimInputMixin:
    effects: frozenset
    def _our_speed(self, mon: Pokemon, battle: DoubleBattle) -> Optional[int]:
        spe = (mon.stats or {}).get("spe")
        if spe is None:
            return None
        scarf = opp_model.to_id(mon.item or "") == "choicescarf"
        ability = opp_model.to_id(mon.ability) if mon.ability else None
        return speed_model.effective_speed(int(spe), self._speed_mods(mon, battle, True, scarf), ability)


    def _foe_info(self, mon: Pokemon, battle: DoubleBattle, comb: DE.Combatant) -> turn_sim.FoeInfo:
        belief = speed_model.belief_for(mon.species, known_ability=mon.ability, item=mon.item,
                                        moves_seen=list(mon.moves))
        speeds = belief.speeds(self._speed_mods(mon, battle, False), self._mega_prob(mon)) \
            if belief else [(1.0, None)]
        moves = [m.id for m in mon.moves.values() if _is_attack_candidate(m, self.effects)]
        if not moves:      # nothing revealed: assume a neutral move off its better attacking stat
            st = comb.hyps[0].stats
            moves = ["bodyslam" if st["atk"] >= st["spa"] else "hypervoice"]
        fakeout, protect, protect_ok = self._foe_action_probs(mon, battle)
        abilities = opp_model.ability_distribution(mon.species, mon.ability) or None
        return turn_sim.FoeInfo(moves, speeds, fakeout, protect, protect_ok,
                                self._foe_trick_room_prob(mon, battle), abilities,
                                self._taunt_left(mon, battle))


    def _taunt_left(self, mon: Pokemon, battle: DoubleBattle) -> int:
        """Turns `mon` stays Taunted, counting this one (poke_env only knows presence: assume a full 3)."""
        return 3 if Effect.TAUNT in mon.effects else 0


    def _trick_room_left(self, battle: DoubleBattle) -> int:
        """Turns Trick Room lasts, counting this one; 0 = down."""
        start = battle.fields.get(Field.TRICK_ROOM)
        return 0 if start is None else max(5 - (battle.turn - start), 1)


    def _foe_trick_room_prob(self, mon: Pokemon, battle: DoubleBattle) -> float:
        """P(a foe sets Trick Room this turn); the base pilot has no action model."""
        return 0.0


    def _foe_action_probs(self, mon: Pokemon, battle: DoubleBattle) -> tuple:
        """(P(Fake Out), P(Protect-family), P(that Protect works)) for a foe this turn; the base
        pilot has no action model (VGCPilot fits one from replays)."""
        return 0.0, 0.0, 1.0


