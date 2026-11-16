from __future__ import annotations

import logging
from functools import lru_cache
from typing import FrozenSet, Optional

from poke_env.battle import DoubleBattle, Move, Pokemon, SideCondition
from poke_env.battle.status import Status

from src import damage, opp_model, speed_model
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
# (Foul Play joins them unless the "foulplay" support effect is on.)
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


def _is_attack_candidate(move: Move, effects: FrozenSet[str] = frozenset()) -> bool:
    mid = move.id
    if mid in LOCKED_MOVES or (mid in UNMODELLED_MOVES and not (mid == "foulplay" and "foulplay" in effects)):
        return False
    mv = damage.DB.get_move(mid)
    if not mv or mv.get("category") == "Status" or (mv.get("basePower") or 0) <= 0:
        return False
    flags = mv.get("flags") or {}
    if flags.get("charge") or flags.get("recharge"):
        return False
    return (mv.get("target") or "") in ("normal", "any", "allAdjacentFoes", "allAdjacent")




class PilotWorldMixin:
    effects: FrozenSet[str]
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
    def _speed_mods(mon: Pokemon, battle: DoubleBattle, own: bool, scarf: bool = False) -> speed_model.SpeedMods:
        conds = battle.side_conditions if own else battle.opponent_side_conditions
        return speed_model.SpeedMods(
            stage=int(mon.boosts.get("spe", 0)), paralyzed=mon.status == Status.PAR,
            tailwind=SideCondition.TAILWIND in conds, scarf=scarf,
            weather=_weather_name(battle), terrain=_terrain_name(battle))

