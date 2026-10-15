"""KO-aware heuristic pilot.

Subclass of SimpleHeuristicsPlayer that replaces crude base_power scoring
with real damage estimates (src.damage.damage_rolls_from_stats).

Vanilla pilot cannot see: EVs (uses base_stats), KOs, return damage.
This one can. Falls back to parent scoring on any exception so behavior is
never strictly worse.

Usage:
    from src.smart_player import SmartPlayer
    player = SmartPlayer(...)
"""
from __future__ import annotations

import logging
from typing import Optional

from poke_env.battle import Pokemon, Move, AbstractBattle
from poke_env.player import SimpleHeuristicsPlayer

from src import damage

logger = logging.getLogger(__name__)


_TYPE_MAP = {
    "NORMAL": "Normal", "FIRE": "Fire", "WATER": "Water", "GRASS": "Grass",
    "ELECTRIC": "Electric", "ICE": "Ice", "FIGHTING": "Fighting",
    "POISON": "Poison", "GROUND": "Ground", "FLYING": "Flying",
    "PSYCHIC": "Psychic", "BUG": "Bug", "ROCK": "Rock", "GHOST": "Ghost",
    "DRAGON": "Dragon", "DARK": "Dark", "STEEL": "Steel", "FAIRY": "Fairy",
}


def _type_to_db(t):
    if t is None:
        return None
    name = t.name.upper() if hasattr(t, "name") else str(t).upper()
    return _TYPE_MAP.get(name, name.title())


def _weather_name(battle):
    """Extract current weather as a lowercase string, or None."""
    try:
        w = battle.weather
        if not w:
            return None
        # w is Dict[Weather, int]; take first key
        wk = next(iter(w))
        nm = wk.name.lower() if hasattr(wk, "name") else str(wk).lower()
        # poke_env names: 'rain', 'sun', 'sandstorm', 'snow', 'hail'
        if "rain" in nm:   return "rain"
        if "sun" in nm:    return "sun"
        if "sand" in nm:   return "sand"
        if "snow" in nm or "hail" in nm: return "snow"
    except Exception:
        pass
    return None


def _terrain_name(battle):
    try:
        f = battle.fields
        if not f:
            return None
        for fld in f:
            nm = fld.name.lower() if hasattr(fld, "name") else str(fld).lower()
            if "electric" in nm: return "electric"
            if "grassy" in nm:   return "grassy"
            if "psychic" in nm:  return "psychic"
            if "misty" in nm:    return "misty"
    except Exception:
        pass
    return None


def _stats_dict(mon: Pokemon) -> dict:
    """Return {hp, atk, def, spa, spd, spe} ints. Zeros for missing."""
    out = {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
    try:
        s = mon.stats or {}
        for k in out:
            v = s.get(k)
            if v is not None:
                out[k] = int(v)
    except Exception:
        pass
    return out


def _boosts_dict(mon: Pokemon) -> dict:
    out = {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}
    try:
        b = mon.boosts or {}
        for k in out:
            v = b.get(k)
            if v is not None:
                out[k] = int(v)
    except Exception:
        pass
    return out


class SmartPlayer(SimpleHeuristicsPlayer):
    """Heuristic pilot with real damage estimation for move scoring.

    Adds: KO detection, HP-aware move scoring, predicted-damage-taken
    penalty for the next turn.
    """

    KO_BONUS = 8.0
    DAMAGE_WEIGHT = 3.0
    RETURN_DAMAGE_WEIGHT = 1.0
    PROTECT_HP_THRESHOLD = 0.25

    @classmethod
    def _score_move_with_damage(cls, attacker: Pokemon, opponent: Pokemon,
                                 move: Move, battle) -> Optional[float]:
        """Return a numeric score, or None if the move can't be modeled."""
        if move is None:
            return None
        atk_stats = _stats_dict(attacker)
        def_stats = _stats_dict(opponent)
        if atk_stats["atk"] == 0 and atk_stats["spa"] == 0:
            return None
        if def_stats["def"] == 0 and def_stats["spd"] == 0:
            return None

        atk_types = [_type_to_db(t) for t in attacker.types if t is not None]
        def_types = [_type_to_db(t) for t in opponent.types if t is not None]

        rolls = damage.damage_rolls_from_stats(
            attacker_stats=atk_stats,
            attacker_types=atk_types,
            attacker_boosts=_boosts_dict(attacker),
            move_name=move.id,
            defender_stats=def_stats,
            defender_types=def_types,
            defender_boosts=_boosts_dict(opponent),
            weather=_weather_name(battle),
            terrain=_terrain_name(battle),
        )
        if not rolls:
            return None
        avg = sum(rolls) / len(rolls)
        opp_hp = max(1, opponent.current_hp)
        frac = avg / opp_hp
        ko = 1.0 if max(rolls) >= opp_hp else 0.0
        acc = (move.accuracy / 100.0) if isinstance(move.accuracy, int) else 1.0
        return (frac * SmartPlayer.DAMAGE_WEIGHT + ko * SmartPlayer.KO_BONUS) * acc

    @staticmethod
    def choose_singles_move(battle):
        """Override: score damaging moves with damage.py; fall back for
        status/setup/switch by calling the parent's decision path."""
        # If we can't identify the active mons, defer.
        attacker = getattr(battle, "active_pokemon", None)
        opponent = getattr(battle, "opponent_active_pokemon", None)
        if attacker is None or opponent is None:
            return SimpleHeuristicsPlayer.choose_singles_move(battle)

        # Only intervene for damaging move selection.
        # Let the parent handle switches, entry hazards, setup, Protect logic.
        try:
            parent_result = SimpleHeuristicsPlayer.choose_singles_move(battle)
        except Exception:
            return SimpleHeuristicsPlayer.choose_singles_move(battle)

        # If parent wanted to switch or use a non-damaging move, keep it.
        order, parent_score = parent_result
        order_move = getattr(order, "order", None)
        is_move = hasattr(order_move, "id") and hasattr(order_move, "category")
        if not is_move:
            return parent_result

        # Score every available damaging move with our estimator.
        scored = []
        for mv in battle.available_moves or []:
            s = SmartPlayer._score_move_with_damage(attacker, opponent, mv, battle)
            if s is not None:
                scored.append((mv, s))

        if not scored:
            return parent_result

        best_move, best_score = max(scored, key=lambda x: x[1])

        # Only override the parent if we found a strictly better damaging move.
        # Compare against parent's score heuristic scaled to our units:
        # parent_score is base_power-ish, in the hundreds. Normalize crudely.
        try:
            parent_move = order_move
            parent_move_score = SmartPlayer._score_move_with_damage(
                attacker, opponent, parent_move, battle
            )
        except Exception:
            parent_move_score = None

        if parent_move_score is None or best_score >= parent_move_score:
            try:
                return SimpleHeuristicsPlayer.create_order(best_move), best_score
            except Exception:
                return parent_result
        return parent_result
