from __future__ import annotations

import logging
import os
from typing import Dict, FrozenSet, List, Optional

from poke_env.battle import DoubleBattle, Field, Move
from poke_env.player import SimpleHeuristicsPlayer
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from src import doubles_eval as DE
from src import support_value as SV
from src import turn_sim
from src.pilot_actions import PilotActionsMixin
from src.pilot_sim_input import PilotSimInputMixin
from src.pilot_world import PilotWorldMixin, _is_attack_candidate
from src.smart_player import _terrain_name, _weather_name

logger = logging.getLogger(__name__)

class DoublesPilot(PilotSimInputMixin, PilotActionsMixin, PilotWorldMixin, SimpleHeuristicsPlayer):

    effects: FrozenSet[str] = frozenset()      # support-move layer (src.support_value); empty = off
    lookahead: bool = False                    # state-delta continuation (DOUBLES_LOOKAHEAD)

    def __init__(self, *args, ko_bonus: Optional[float] = None, min_gain: Optional[float] = None,
                 use_turn_sim: Optional[bool] = None, support: Optional[str] = None,
                 lookahead: Optional[bool] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.effects = SV.parse_effects(support)
        self.lookahead = SV.lookahead_enabled(lookahead) and bool(self.effects)
        # env overrides let eval sweeps tune without code edits
        self.ko_bonus = ko_bonus if ko_bonus is not None else float(
            os.environ.get("DOUBLES_KO_BONUS", DE.KO_BONUS))
        self.min_gain = min_gain if min_gain is not None else float(
            os.environ.get("DOUBLES_MIN_GAIN", DE.MIN_GAIN))
        self.use_turn_sim = use_turn_sim if use_turn_sim is not None else (
            os.environ.get("DOUBLES_TURN_SIM", "1") == "1")
        self.stats_counter = {"turns": 0, "overrides": 0, "errors": 0, "sim_turns": 0,
                              "sim_protect": 0, "sim_switch": 0, "sim_fakeout": 0,
                              **{f"sup_{e}": 0 for e in SV.EFFECTS}}

    def choose_move(self, battle):
        base = super().choose_move(battle)
        if not isinstance(battle, DoubleBattle):
            return base
        self.stats_counter["turns"] += 1
        try:
            improved = self._improve(battle, base)
        except Exception:
            self.stats_counter["errors"] += 1
            logger.exception("DoublesPilot fell back to vanilla order")
            return base
        if improved is not base:
            self.stats_counter["overrides"] += 1
        return improved

    # ---- world construction -------------------------------------------------













    def _improve(self, battle: DoubleBattle, base):
        if (any(battle.force_switch) or not isinstance(base, DoubleBattleOrder)
                or not battle.valid_orders):
            return base

        world: Dict[str, DE.Combatant] = {}
        for i, mon in enumerate(battle.opponent_active_pokemon):
            if mon is not None and not mon.fainted:
                c = self._foe(mon, battle if self.use_turn_sim else None)
                if c is None:
                    return base
                world[f"o{i}"] = c
        if not world:
            return base
        attackers: Dict[int, DE.Attacker] = {}
        for i, mon in enumerate(battle.active_pokemon):
            if mon is not None and not mon.fainted:
                a = self._attacker(mon)
                if a is not None:
                    attackers[i] = a
                c = self._ally(mon)
                if c is not None:
                    world[f"a{i}"] = c

        if self.use_turn_sim:
            return self._improve_sim(battle, base, world, attackers)

        base_orders = [base.first_order, base.second_order]
        cand_orders: List[List[SingleBattleOrder]] = []
        cand_actions: List[List[Optional[DE.Action]]] = []
        for slot in (0, 1):
            bo = base_orders[slot]
            free = (slot in attackers and isinstance(bo.order, Move)
                    and _is_attack_candidate(bo.order, self.effects))
            if not free:
                cand_orders.append([bo])
                cand_actions.append([None])
                continue
            # baseline action is None when vanilla aimed at an ally / dead slot: any real attack beats it
            orders, actions, seen = [bo], [self._action(slot, bo, world)], {bo.message}
            for o in battle.valid_orders[slot]:
                if (not isinstance(o.order, Move) or o.message in seen
                        or o.mega != bo.mega or o.terastallize != bo.terastallize
                        or o.dynamax != bo.dynamax or o.z_move != bo.z_move):
                    continue
                act = self._action(slot, o, world)
                if act is not None:
                    seen.add(o.message)
                    orders.append(o)
                    actions.append(act)
            cand_orders.append(orders)
            cand_actions.append(actions)

        if len(cand_orders[0]) == 1 and len(cand_orders[1]) == 1:
            return base

        ev = DE.Evaluator(attackers, world, _weather_name(battle), _terrain_name(battle),
                          ko_bonus=self.ko_bonus, effects=self.effects)
        ia, ib, _, _ = DE.choose_pair(ev, cand_actions[0], cand_actions[1], self.min_gain)
        if (ia, ib) == (0, 0):
            return base
        return DoubleBattleOrder(cand_orders[0][ia], cand_orders[1][ib])

    # ---- turn_sim decision: attacks plus Fake Out / Protect / switch --------------------------



    def _log_lookahead(self, battle, la, fine, coarse, cand_orders, cand_actions, picked, best_v, base_v) -> None:
        """Diagnostic (env DOUBLES_LA_LOG=path): replay the decision without the lookahead, count and log differences."""
        import json
        fine.disable_lookahead()
        coarse.disable_lookahead()
        ja, jb, alt_v, alt_base = turn_sim.choose_pair_refined(coarse, fine, cand_actions[0], cand_actions[1],
                                                               self.min_gain, turn_sim.TOP_K)
        fine.enable_lookahead(la)
        coarse.enable_lookahead(la)
        differs = (ja, jb) != picked
        self.stats_counter["la_diff"] = self.stats_counter.get("la_diff", 0) + int(differs)
        if not differs:
            return
        name = lambda ia, ib: [cand_orders[0][ia].message, cand_orders[1][ib].message]  # noqa: E731
        row = {"turn": battle.turn, "with": name(*picked), "without": name(ja, jb),
               "v_with": [round(best_v, 3), round(base_v, 3)], "v_without": [round(alt_v, 3), round(alt_base, 3)],
               "dv": {str(k): round(v, 3) for k, v in la._dv.items()},
               "v1": {str(k): round(v, 3) for k, v in la._v1.items()},
               "foes": {f: round(i.trickroom, 2) for f, i in fine.foes.items()},
               "hp": {t: [round(h.cur_hp / max(h.max_hp, 1), 2) for h in c.hyps][:1] for t, c in fine.world.items()}}
        with open(os.environ["DOUBLES_LA_LOG"], "a") as f:
            f.write(json.dumps(row) + "\n")

    def _populate_bench(self, battle: DoubleBattle, world: Dict[str, DE.Combatant]) -> Dict[str, str]:
        bench: Dict[str, str] = {}
        for slot_switches in battle.available_switches or []:
            for m in slot_switches:
                c = self._ally(m) if m.species not in bench else None
                if c is not None:
                    bench[m.species] = f"b{len(bench)}"
                    world[bench[m.species]] = c
        return bench

    def _improve_sim(self, battle: DoubleBattle, base, world: Dict[str, DE.Combatant],
                     attackers: Dict[int, DE.Attacker]):
        bench = self._populate_bench(battle, world)

        base_orders = [base.first_order, base.second_order]
        cand_orders: List[List[SingleBattleOrder]] = []
        cand_actions: List[List[Optional[DE.Action]]] = []
        for slot in (0, 1):
            bo, mon = base_orders[slot], battle.active_pokemon[slot]
            kind = self._sim_kind(bo)
            base_act = self._sim_action(slot, bo, mon, world, bench) if kind else None
            if not (slot in attackers and kind and (base_act is not None or kind == "attack")):
                cand_orders.append([bo])
                cand_actions.append([None])
                continue
            orders, actions, seen = [bo], [base_act], {bo.message}
            for o in battle.valid_orders[slot]:
                k = self._sim_kind(o)
                if (k is None or o.message in seen or o.mega != bo.mega or o.terastallize != bo.terastallize
                        or o.dynamax != bo.dynamax or o.z_move != bo.z_move
                        or (k == "protect" and getattr(mon, "protect_counter", 0))
                        or (k == "fakeout" and not mon.first_turn)):
                    continue
                act = self._sim_action(slot, o, mon, world, bench)
                if act is not None:
                    seen.add(o.message)
                    orders.append(o)
                    actions.append(act)
            cand_orders.append(orders)
            cand_actions.append(actions)

        if len(cand_orders[0]) == 1 and len(cand_orders[1]) == 1:
            return base

        ours = {i: self._our_speed(battle.active_pokemon[i], battle) for i in attackers}
        ours = {i: v for i, v in ours.items() if v is not None}
        foes = {f"o{i}": self._foe_info(mon, battle, world[f"o{i}"])
                for i, mon in enumerate(battle.opponent_active_pokemon) if f"o{i}" in world}
        args = (attackers, world, ours, foes, Field.TRICK_ROOM in battle.fields, _weather_name(battle),
                _terrain_name(battle))
        tr_left = self._trick_room_left(battle)
        fine = turn_sim.TurnSim(*args, ko_bonus=self.ko_bonus, effects=self.effects, tr_left=tr_left)
        coarse = turn_sim.TurnSim(*args, ko_bonus=self.ko_bonus, max_hyps=turn_sim.COARSE_HYPS,
                                  min_outcome_p=turn_sim.COARSE_OUTCOME_P, effects=self.effects,
                                  tr_left=tr_left)
        for ev in (fine, coarse):
            ev.set_candidates({0: cand_actions[0], 1: cand_actions[1]})
        if self.lookahead and any(a is not None and (turn_sim.is_support(a) or SV.foe_drop(a.move) is not None)
                                  for acts in cand_actions for a in acts):
            la = turn_sim.LookAhead(coarse)
            fine.enable_lookahead(la)
            coarse.enable_lookahead(la)
            self.stats_counter["sim_lookahead"] = self.stats_counter.get("sim_lookahead", 0) + 1
        for slot in (0, 1):
            keep = fine.shortlist(cand_actions[slot], turn_sim.SHORTLIST)
            cand_orders[slot] = [cand_orders[slot][i] for i in keep]
            cand_actions[slot] = [cand_actions[slot][i] for i in keep]
        self.stats_counter["sim_turns"] += 1
        ia, ib, best_v, base_v = turn_sim.choose_pair_refined(coarse, fine, cand_actions[0], cand_actions[1],
                                                              self.min_gain, turn_sim.TOP_K)
        if coarse.la is not None and os.environ.get("DOUBLES_LA_LOG"):
            self._log_lookahead(battle, coarse.la, fine, coarse, cand_orders, cand_actions, (ia, ib), best_v, base_v)
        if (ia, ib) == (0, 0):
            return base
        for slot, i in ((0, ia), (1, ib)):
            o = cand_orders[slot][i].order
            eff = SV.effect_of(o.id) if isinstance(o, Move) else None
            if eff in self.effects:
                self.stats_counter[f"sup_{eff}"] = self.stats_counter.get(f"sup_{eff}", 0) + 1
            if i:
                key = {"switch": "sim_switch", "fakeout": "sim_fakeout", "protect": "sim_protect"}.get(
                    self._sim_kind(cand_orders[slot][i]))
                if key:
                    self.stats_counter[key] = self.stats_counter.get(key, 0) + 1
        return DoubleBattleOrder(cand_orders[0][ia], cand_orders[1][ib])
