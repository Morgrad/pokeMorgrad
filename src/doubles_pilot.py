"""Doubles pilot: vanilla decisions, joint-optimised attack allocation.

Layering (deliberately conservative):
  1. SimpleHeuristicsPlayer decides what each slot does (switch / status / attack).
  2. For slots where it chose a plain damaging move, we re-pick the move + target of
     *both* attackers together, scoring the pair with src.doubles_eval against
     estimated opposing builds (src.opp_model). Slots it chose anything else for
     (switches, setup, Protect, Fake Out, charge/recharge, unmodelled moves) are
     left exactly as vanilla chose them.
  3. Any exception, forced switch, or no-gain result falls back to the vanilla order.

Optional `use_turn_sim` (env DOUBLES_TURN_SIM=1) scores the pairs with src.turn_sim instead:
move order (speed_model), foe retaliation and retargeting. Off by default.

Mega evolution is not used here: poke_env's heuristic never mega-evolves (VGCPilot adds it).
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Dict, List, Optional

from poke_env.battle import DoubleBattle, Field, Move, Pokemon, SideCondition
from poke_env.battle.status import Status
from poke_env.player import SimpleHeuristicsPlayer
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder

from src import damage, opp_model, speed_model, turn_sim
from src import doubles_eval as DE
from src.mega_model import conditional_q
from src.smart_player import _boosts_dict, _terrain_name, _type_to_db, _weather_name

logger = logging.getLogger(__name__)

# Moves whose value is not "damage now": leave vanilla's choice alone.
LOCKED_MOVES = {
    "fakeout", "firstimpression", "suckerpunch", "upperhand", "focuspunch",
    "explosion", "selfdestruct", "mistyexplosion", "finalgambit", "mindblown",
}
# Damage depends on stats the evaluator doesn't feed the formula: treat as unmodelled.
UNMODELLED_MOVES = {
    "foulplay", "bodypress", "psyshock", "psystrike", "secretsword",
    "photongeyser", "shellsidearm", "terablast", "hiddenpower",
}
ITEM_ATK_MULT = {"choiceband": ("atk", 1.5), "choicespecs": ("spa", 1.5)}
ABILITY_ATK_MULT = {"hugepower": ("atk", 2.0), "purepower": ("atk", 2.0)}
ITEM_FINAL_MULT = {"lifeorb": 1.3}


@lru_cache(maxsize=1)
def _move_types():
    return frozenset(m["type"] for m in damage._raw_db()["moves"].values() if m.get("type"))


def _is_attack_candidate(move: Move) -> bool:
    mid = move.id
    if mid in LOCKED_MOVES or mid in UNMODELLED_MOVES:
        return False
    mv = damage.DB.get_move(mid)
    if not mv or mv.get("category") == "Status" or (mv.get("basePower") or 0) <= 0:
        return False
    flags = mv.get("flags") or {}
    if flags.get("charge") or flags.get("recharge"):
        return False
    return (mv.get("target") or "") in ("normal", "any", "allAdjacentFoes", "allAdjacent")


class DoublesPilot(SimpleHeuristicsPlayer):
    def __init__(self, *args, ko_bonus: Optional[float] = None, min_gain: Optional[float] = None,
                 use_turn_sim: Optional[bool] = None, **kwargs):
        super().__init__(*args, **kwargs)
        # env overrides let eval sweeps tune without code edits
        self.ko_bonus = ko_bonus if ko_bonus is not None else float(
            os.environ.get("DOUBLES_KO_BONUS", DE.KO_BONUS))
        self.min_gain = min_gain if min_gain is not None else float(
            os.environ.get("DOUBLES_MIN_GAIN", DE.MIN_GAIN))
        self.use_turn_sim = use_turn_sim if use_turn_sim is not None else (
            os.environ.get("DOUBLES_TURN_SIM", "0") == "1")
        self.stats_counter = {"turns": 0, "overrides": 0, "errors": 0, "sim_turns": 0,
                              "sim_protect": 0, "sim_switch": 0, "sim_fakeout": 0}

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

    def _attacker(self, mon: Pokemon) -> Optional[DE.Attacker]:
        stats = dict(mon.stats or {})
        if not stats or stats.get("atk") is None:
            return None
        stats = {k: int(v) for k, v in stats.items() if v is not None}
        item = opp_model.to_id(mon.item) if mon.item else ""
        ability = opp_model.to_id(mon.ability) if mon.ability else ""
        for table, key in ((ITEM_ATK_MULT, item), (ABILITY_ATK_MULT, ability)):
            if key in table:
                stat, mult = table[key]
                stats[stat] = int(stats[stat] * mult)
        return DE.Attacker(
            stats=stats,
            types=[_type_to_db(t) for t in mon.types if t is not None],
            boosts=_boosts_dict(mon),
            burn=mon.status == Status.BRN,
            ability="Guts" if ability == "guts" else None,
            final_mult=ITEM_FINAL_MULT.get(item, 1.0),
        )

    def _mega_prob(self, mon: Pokemon) -> float:
        """P(this foe Mega Evolves this turn); the base pilot never models it."""
        return 0.0

    def _foe(self, mon: Pokemon, battle: Optional[DoubleBattle] = None) -> Optional[DE.Combatant]:
        """Damage hypotheses for a foe; with `battle`, each also carries its own Speed list."""
        builds = opp_model.opponent_builds(mon.species, item=mon.item, moves_seen=list(mon.moves),
                                           ability=mon.ability)
        if not builds:
            return None
        mods = self._speed_mods(mon, battle, False) if battle is not None else None
        abilities = (opp_model.ability_distribution(mon.species, mon.ability) or {None: 1.0}) if mods else {}

        def speeds(stat: int, b) -> Optional[list]:
            if mods is None:
                return None
            scarf = opp_model.to_id(b.item or "") == "choicescarf"
            return [(pa, speed_model.effective_speed(stat, mods, a, scarf)) for a, pa in abilities.items()]
        frac = mon.current_hp_fraction
        q = conditional_q(self._mega_prob(mon), sum(b.weight for b in builds if b.form_stats))
        hyps, post = [], {}                 # post: Mega form -> P(this foe is that form this turn)
        for b in builds:
            cur = max(1, round(frac * b.max_hp))
            if b.form_stats and q > 0:
                hyps.append(DE.Hypothesis(b.weight * q, b.form_stats, b.form_stats["hp"],
                                          max(1, round(frac * b.form_stats["hp"])),
                                          types=list(damage.DB.get_species(b.form)["types"]),
                                          speeds=speeds(b.form_stats["spe"], b)))
                post[b.form] = post.get(b.form, 0.0) + b.weight * q
                if q < 1:
                    hyps.append(DE.Hypothesis(b.weight * (1 - q), b.stats, b.max_hp, cur,
                                              speeds=speeds(b.stats["spe"], b)))
            else:
                hyps.append(DE.Hypothesis(b.weight, b.stats, b.max_hp, cur, speeds=speeds(b.stats["spe"], b)))
        types = [_type_to_db(t) for t in mon.types if t is not None]
        pm = sum(post.values())
        immune = {t: (1 - pm) * opp_model.immunity_prob(mon.species, t, mon.ability)
                  + sum(w * opp_model.immunity_prob(f, t) for f, w in post.items())
                  for t in _move_types()}
        return DE.Combatant(hyps, types, _boosts_dict(mon), False,
                            {t: p for t, p in immune.items() if p > 0})

    # ---- turn_sim inputs ----------------------------------------------------------------

    @staticmethod
    def _speed_mods(mon: Pokemon, battle: DoubleBattle, own: bool, scarf: bool = False) -> speed_model.SpeedMods:
        conds = battle.side_conditions if own else battle.opponent_side_conditions
        return speed_model.SpeedMods(
            stage=int(mon.boosts.get("spe", 0)), paralyzed=mon.status == Status.PAR,
            tailwind=SideCondition.TAILWIND in conds, scarf=scarf,
            weather=_weather_name(battle), terrain=_terrain_name(battle))

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
        moves = [m.id for m in mon.moves.values() if _is_attack_candidate(m)]
        if not moves:      # nothing revealed: assume a neutral move off its better attacking stat
            st = comb.hyps[0].stats
            moves = ["bodyslam" if st["atk"] >= st["spa"] else "hypervoice"]
        fakeout, protect, protect_ok = self._foe_action_probs(mon, battle)
        return turn_sim.FoeInfo(moves, speeds, fakeout, protect, protect_ok)

    def _foe_action_probs(self, mon: Pokemon, battle: DoubleBattle) -> tuple:
        """(P(Fake Out), P(Protect-family), P(that Protect works)) for a foe this turn; the base
        pilot has no action model (VGCPilot fits one from replays)."""
        return 0.0, 0.0, 1.0

    def _ally(self, mon: Pokemon) -> Optional[DE.Combatant]:
        stats = {k: int(v) for k, v in (mon.stats or {}).items() if v is not None}
        if not stats or not mon.max_hp:
            return None
        stats["hp"] = int(mon.max_hp)
        ab = mon.ability
        immune = {t: 1.0 for t in _move_types()
                  if ab and opp_model.IMMUNITY_ABILITIES.get(opp_model.to_id(ab)) == t}
        return DE.Combatant([DE.Hypothesis(1.0, stats, int(mon.max_hp), max(1, int(mon.current_hp)))],
                            [_type_to_db(t) for t in mon.types if t is not None],
                            _boosts_dict(mon), True, immune)

    # ---- order <-> action ---------------------------------------------------

    @staticmethod
    def _action(slot: int, order: SingleBattleOrder, world: Dict[str, DE.Combatant]) -> Optional[DE.Action]:
        move = getattr(order, "order", None)
        if not isinstance(move, Move) or not _is_attack_candidate(move):
            return None
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
                    and _is_attack_candidate(bo.order))
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
                          ko_bonus=self.ko_bonus)
        ia, ib, _, _ = DE.choose_pair(ev, cand_actions[0], cand_actions[1], self.min_gain)
        if (ia, ib) == (0, 0):
            return base
        return DoubleBattleOrder(cand_orders[0][ia], cand_orders[1][ib])

    # ---- turn_sim decision: attacks plus Fake Out / Protect / switch --------------------------

    @staticmethod
    def _sim_kind(order: SingleBattleOrder) -> Optional[str]:
        o = getattr(order, "order", None)
        if isinstance(o, Pokemon):
            return "switch"
        if isinstance(o, Move):
            if _is_attack_candidate(o):
                return "attack"
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
        if kind == "switch":
            bid = bench.get(o.species)
            return DE.Action(slot, turn_sim.SWITCH, (bid,)) if bid else None
        if kind == "fakeout" and mon.first_turn and order.move_target in (1, 2) \
                and f"o{order.move_target - 1}" in world:
            return DE.Action(slot, turn_sim.FAKE_OUT, (f"o{order.move_target - 1}",))
        return None

    def _improve_sim(self, battle: DoubleBattle, base, world: Dict[str, DE.Combatant],
                     attackers: Dict[int, DE.Attacker]):
        bench: Dict[str, str] = {}
        for slot_switches in battle.available_switches or []:
            for m in slot_switches:
                c = self._ally(m) if m.species not in bench else None
                if c is not None:
                    bench[m.species] = f"b{len(bench)}"
                    world[bench[m.species]] = c

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
        fine = turn_sim.TurnSim(*args, ko_bonus=self.ko_bonus)
        coarse = turn_sim.TurnSim(*args, ko_bonus=self.ko_bonus, max_hyps=turn_sim.COARSE_HYPS,
                                  min_outcome_p=turn_sim.COARSE_OUTCOME_P)
        for ev in (fine, coarse):
            ev.set_candidates({0: cand_actions[0], 1: cand_actions[1]})
        for slot in (0, 1):
            keep = fine.shortlist(cand_actions[slot], turn_sim.SHORTLIST)
            cand_orders[slot] = [cand_orders[slot][i] for i in keep]
            cand_actions[slot] = [cand_actions[slot][i] for i in keep]
        self.stats_counter["sim_turns"] += 1
        ia, ib, _, _ = turn_sim.choose_pair_refined(coarse, fine, cand_actions[0], cand_actions[1],
                                                    self.min_gain, turn_sim.TOP_K)
        if (ia, ib) == (0, 0):
            return base
        for slot, i in ((0, ia), (1, ib)):
            if i:
                key = {"switch": "sim_switch", "fakeout": "sim_fakeout", "protect": "sim_protect"}.get(
                    self._sim_kind(cand_orders[slot][i]))
                if key:
                    self.stats_counter[key] = self.stats_counter.get(key, 0) + 1
        return DoubleBattleOrder(cand_orders[0][ia], cand_orders[1][ib])
