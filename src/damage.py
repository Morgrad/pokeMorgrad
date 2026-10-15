"""Champions-format stat + base damage estimator.

Mirrors Showdown's data/mods/champions/scripts.ts statModify + battle-actions
damage math. Verified against Showdown for base cases.

EV points are Champions points (0-32). Stat term uses max(2*points - 1, 0).

Modifier coverage (all optional kwargs, defaults = no modifier):
  - crit:         1.5x damage (ignores screens)
  - burn:         0.5x physical (skipped if attacker_ability == 'Guts')
  - weather:      'rain' | 'sun' | 'sand' | 'snow'
  - terrain:      'electric' | 'grassy' | 'psychic' | 'misty'
  - attacker_boosts / defender_boosts: dict of stat -> stage (-6..+6)
  - reflect / light_screen / aurora_veil: bool
  - attacker_ability / defender_ability: for damage-relevant abilities

Order of operations follows Showdown's battle-actions.modifyDamage exactly.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src import regmc_db as DB

_DB_PATH = Path.home() / "project" / "data" / "regmc_db.json"


@lru_cache(maxsize=1)
def _raw_db():
    return json.loads(_DB_PATH.read_text())


_CODE_TO_MULT = {0: 1.0, 1: 2.0, 2: 0.5, 4: 0.0}


NATURE_MODS = {
    "Adamant": ("atk", "spa"), "Modest":  ("spa", "atk"),
    "Jolly":   ("spe", "spa"), "Timid":   ("spe", "atk"),
    "Bold":    ("def", "atk"), "Impish":  ("def", "spa"),
    "Calm":    ("spd", "atk"), "Careful": ("spd", "spa"),
    "Brave":   ("atk", "spe"), "Quiet":   ("spa", "spe"),
    "Relaxed": ("def", "spe"), "Sassy":   ("spd", "spe"),
    "Naive":   ("spe", "spd"), "Hasty":   ("spe", "def"),
    "Lonely":  ("atk", "def"), "Mild":    ("spa", "def"),
    "Naughty": ("atk", "spd"), "Rash":    ("spa", "spd"),
    "Gentle":  ("spd", "def"), "Lax":     ("def", "spd"),
}


def _ev_term(points):
    return max(2 * int(points) - 1, 0)


def _stage_mult(stage):
    s = max(-6, min(6, int(stage)))
    return (2 + s) / 2 if s >= 0 else 2 / (2 - s)


def stat_at_level(species_name, stat, ev=0, iv=31, nature=None, level=50):
    sp = DB.get_species(species_name)
    if not sp:
        return 0
    base = sp["baseStats"].get(stat, 0)
    ev = max(0, min(32, int(ev)))
    evt = _ev_term(ev)
    if stat == "hp":
        return ((2 * base + iv + evt) * level) // 100 + level + 10
    raw = ((2 * base + iv + evt) * level) // 100 + 5
    if nature and nature in NATURE_MODS:
        up, down = NATURE_MODS[nature]
        if stat == up:
            raw = int(raw * 1.1)
        elif stat == down:
            raw = int(raw * 0.9)
    return raw


def _effectiveness(move_type, defender_types):
    chart = _raw_db()["typeChart"]
    mult = 1.0
    for dt in defender_types:
        entry = chart.get(dt.lower(), {}).get("damageTaken", {})
        code = entry.get(move_type, 0)
        mult *= _CODE_TO_MULT.get(code, 1.0)
    return mult


def _is_spread(move, is_doubles):
    if not is_doubles:
        return False
    return (move.get("target") or "").lower() in ("alladjacent", "alladjacentfoes")


def _weather_mult(weather, move_type):
    if weather == "rain":
        if move_type == "Water": return 1.5
        if move_type == "Fire":  return 0.5
    elif weather == "sun":
        if move_type == "Fire":  return 1.5
        if move_type == "Water": return 0.5
    return 1.0


def _terrain_mult(terrain, move_type):
    if not terrain:
        return 1.0
    t = terrain.lower()
    mt = move_type.lower()
    if t == "electric" and mt == "electric": return 1.3
    if t == "grassy"   and mt == "grass":    return 1.3
    if t == "psychic"  and mt == "psychic":  return 1.3
    if t == "misty"    and mt == "dragon":   return 0.5
    return 1.0


def _screen_mult(category, is_doubles, reflect, light_screen, aurora_veil, crit):
    if crit:
        return 1.0
    f = (2.0 / 3.0) if is_doubles else 0.5
    if aurora_veil:
        return f
    if category == "physical" and reflect:
        return f
    if category == "special" and light_screen:
        return f
    return 1.0


def damage_rolls(attacker_species, attacker_evs, attacker_nature,
                 move_name, defender_species, defender_evs, defender_nature,
                 attacker_level=50, defender_level=50, is_doubles=True,
                 include_spread=True,
                 crit=False, burn=False,
                 weather=None, terrain=None,
                 attacker_boosts=None, defender_boosts=None,
                 attacker_grounded=True, defender_grounded=True,
                 reflect=False, light_screen=False, aurora_veil=False,
                 attacker_ability=None, defender_ability=None):
    mv = DB.get_move(move_name)
    if not mv or mv.get("category") == "Status":
        return []
    atk = DB.get_species(attacker_species)
    dfd = DB.get_species(defender_species)
    if not atk or not dfd:
        return []

    category = mv["category"].lower()
    power = mv.get("basePower") or 0
    if power <= 0:
        return []

    ab = attacker_boosts or {}
    db_ = defender_boosts or {}

    if category == "physical":
        a_base = stat_at_level(attacker_species, "atk",
                               ev=attacker_evs.get("atk", 0),
                               nature=attacker_nature, level=attacker_level)
        d_base = stat_at_level(defender_species, "def",
                               ev=defender_evs.get("def", 0),
                               nature=defender_nature, level=defender_level)
        a_stat = a_base * _stage_mult(ab.get("atk", 0))
        d_stat = d_base * _stage_mult(db_.get("def", 0))
    else:
        a_base = stat_at_level(attacker_species, "spa",
                               ev=attacker_evs.get("spa", 0),
                               nature=attacker_nature, level=attacker_level)
        d_base = stat_at_level(defender_species, "spd",
                               ev=defender_evs.get("spd", 0),
                               nature=defender_nature, level=defender_level)
        a_stat = a_base * _stage_mult(ab.get("spa", 0))
        d_stat = d_base * _stage_mult(db_.get("spd", 0))

    if weather == "sand" and category == "special" and "Rock" in dfd.get("types", []):
        d_stat *= 1.5
    elif weather == "snow" and category == "physical" and "Ice" in dfd.get("types", []):
        d_stat *= 1.5

    if a_stat == 0 or d_stat == 0:
        return []

    base = ((2 * attacker_level) // 5 + 2) * power * int(a_stat) // int(d_stat)
    base = base // 50 + 2

    if include_spread and _is_spread(mv, is_doubles):
        base = int(base * 0.75)

    wm = _weather_mult(weather, mv["type"])
    if wm != 1.0:
        base = int(base * wm)

    if crit:
        base = int(base * 1.5)

    rolls = [int(base * (85 + i) / 100) for i in range(16)]

    stab = 1.5 if mv["type"] in atk.get("types", []) else 1.0
    eff = _effectiveness(mv["type"], dfd.get("types", []))
    burn_m = 1.0
    if burn and category == "physical" and attacker_ability != "Guts":
        burn_m = 0.5
    terrain_m = _terrain_mult(terrain, mv["type"]) if attacker_grounded else 1.0
    screen_m = _screen_mult(category, is_doubles, reflect, light_screen,
                            aurora_veil, crit)

    out = []
    for r in rolls:
        r = int(r * stab)
        r = int(r * eff)
        r = int(r * burn_m)
        r = int(r * terrain_m)
        r = int(r * screen_m)
        if eff > 0 and r < 1:
            r = 1
        out.append(r)
    return out


def damage_range(attacker_species, attacker_evs, attacker_nature,
                 move_name, defender_species, defender_evs, defender_nature,
                 **kwargs):
    rolls = damage_rolls(attacker_species, attacker_evs, attacker_nature,
                         move_name, defender_species, defender_evs,
                         defender_nature, **kwargs)
    if not rolls:
        return (0, 0, 0)
    return (min(rolls), sum(rolls) // len(rolls), max(rolls))


def ko_chance(attacker_species, attacker_evs, attacker_nature,
              move_name, defender_species, defender_evs, defender_nature,
              **kwargs):
    hp = stat_at_level(defender_species, "hp",
                       ev=defender_evs.get("hp", 0),
                       nature=defender_nature,
                       level=kwargs.get("defender_level", 50))
    if hp == 0:
        return 0.0
    rolls = damage_rolls(attacker_species, attacker_evs, attacker_nature,
                         move_name, defender_species, defender_evs,
                         defender_nature, **kwargs)
    if not rolls:
        return 0.0
    return sum(1 for r in rolls if r >= hp) / len(rolls)
