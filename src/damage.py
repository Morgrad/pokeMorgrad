"""Champions-format stat + base damage estimator.

Mirrors Showdown's data/mods/champions/scripts.ts statModify + damage math.
Critical: EV points (0-32) map to stat term via max(2*points - 1, 0).

Ignores: crits, weather, terrain, stat stages, abilities, items, screens,
status. Extend via explicit modifier params — do not fork the module.
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


# typeChart[defender_type].damageTaken[move_type] is a code:
#   0 -> 1.0x   (neutral)
#   1 -> 2.0x   (weak)
#   2 -> 0.5x   (resist)
#   4 -> 0.0x   (immune)
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
    """Champions points (0-32) -> stat EV term. See scripts.ts."""
    return max(2 * int(points) - 1, 0)


def stat_at_level(species_name, stat, ev=0, iv=31, nature=None, level=50):
    """Final stat. `ev` is Champions points (0-32). Returns 0 if species unknown."""
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
    """Return type multiplier. move_type and defender_types are DB-cased."""
    chart = _raw_db()["typeChart"]
    mult = 1.0
    for dt in defender_types:
        entry = chart.get(dt.lower(), {}).get("damageTaken", {})
        code = entry.get(move_type, 0)
        mult *= _CODE_TO_MULT.get(code, 1.0)
    return mult


def _is_spread(move, is_doubles):
    """True if the move hits multiple targets in doubles."""
    if not is_doubles:
        return False
    target = (move.get("target") or "").lower()
    return target in ("alladjacent", "alladjacentfoes")


def damage_rolls(attacker_species, attacker_evs, attacker_nature,
                 move_name, defender_species, defender_evs, defender_nature,
                 attacker_level=50, defender_level=50, is_doubles=True,
                 crit=False, burn=False, include_spread=True):
    """Return 16 damage values (0.85x - 1.00x rolls), or [] if invalid."""
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

    if category == "physical":
        a = stat_at_level(attacker_species, "atk",
                          ev=attacker_evs.get("atk", 0),
                          nature=attacker_nature, level=attacker_level)
        d = stat_at_level(defender_species, "def",
                          ev=defender_evs.get("def", 0),
                          nature=defender_nature, level=defender_level)
    else:
        a = stat_at_level(attacker_species, "spa",
                          ev=attacker_evs.get("spa", 0),
                          nature=attacker_nature, level=attacker_level)
        d = stat_at_level(defender_species, "spd",
                          ev=defender_evs.get("spd", 0),
                          nature=defender_nature, level=defender_level)
    if a == 0 or d == 0:
        return []

    # Showdown base formula: ((2 * level / 5 + 2) * power * A / D) / 50 + 2
    base = ((2 * attacker_level) // 5 + 2) * power * a // d
    base = base // 50 + 2

    if include_spread and _is_spread(mv, is_doubles):
        base = int(base * 0.75)
    if crit:
        base = int(base * 1.5)

    rolls = [int(base * (85 + i) / 100) for i in range(16)]

    # STAB (order matches Showdown: randomizer, STAB, type, burn)
    stab = 1.5 if mv["type"] in atk.get("types", []) else 1.0
    eff = _effectiveness(mv["type"], dfd.get("types", []))
    burn_m = 0.5 if (burn and category == "physical") else 1.0

    out = []
    for r in rolls:
        r = int(r * stab)
        r = int(r * eff)
        r = int(r * burn_m)
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
    """P(single hit KOs). Returns 0..1."""
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
