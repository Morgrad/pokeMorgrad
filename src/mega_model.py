"""Foe Mega prediction: P(an opposing mon Mega Evolves THIS turn), from real ladder replays.

Mega happens before move order is decided, so the pilot must score the foe's post-Mega stats
with this probability. Rates come from data/mega_rates.json (tools/build_mega_rates.py): a table
over (candidates on the foe's field, turns the mon has already had the chance, lead vs back)
times a per-species factor (does this species usually hold its stone). One Mega per side, so the
probabilities of a side's candidates are renormalised to sum to at most 1.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from src import battle_memory as BM
from src import damage
from src.paths import data_path

RATES_PATH = Path(data_path("mega_rates.json"))
CONSUMED_P = 0.02          # item already used up (measured 1.6%): it was not the stone
MAX_P = 0.98


@lru_cache(maxsize=1)
def capable_species() -> frozenset:
    return frozenset(n for n, e in damage._raw_db()["species"].items() if e.get("megaStones"))


@lru_cache(maxsize=1)
def stone_ids() -> frozenset:
    return frozenset(BM._id(s) for e in damage._raw_db()["species"].values()
                     for s in (e.get("megaStones") or []))


@lru_cache(maxsize=1)
def _rates() -> dict:
    return json.loads(RATES_PATH.read_text())


def cell_key(k: int, ncand: int, lead: bool) -> str:
    kb = ("k0_lead" if lead else "k0_back") if k <= 0 else f"k{min(k, 3)}"
    return f"{kb}|{min(max(ncand, 1), 2)}"


def p_mega_now(species: str, k: int, ncand: int, lead: bool, item: Optional[str] = None,
               consumed: bool = False, rates: Optional[dict] = None) -> float:
    """P(this candidate Mega Evolves this turn). k = turns it already had the chance (0 = first)."""
    r = rates or _rates()
    if consumed:
        return CONSUMED_P
    if item:
        if BM._id(item) not in stone_ids():
            return 0.0
    base = r["cells"].get(cell_key(k, ncand, lead), r["cells"].get(cell_key(k, ncand, False), 0.1))
    rel = r["species_rel"].get(species, 1.0)
    p = base * rel
    if item:            # the stone is revealed: it holds, so the species factor no longer applies
        p = min(base / r["hold_floor"], MAX_P)
    return min(max(p, 0.0), MAX_P)


def candidates(mem: BM.BattleMemory, side: str, turn: Optional[int] = None) -> List[dict]:
    """Active, not-yet-Mega'd mons of Mega-capable species on `side`, while its Mega is unused."""
    if mem.mega_used.get(side) is not None:
        return []
    t = mem.turn if turn is None else turn
    cs = [r for r in mem.active_mons(side)
          if not r.fainted and not r.mega_form and r.species in capable_species()]
    return [dict(name=r.name, species=r.species, k=t - max(r.switch_in_turn + 1, 1),
                 ncand=len(cs), lead=r.switch_in_turn == 0, item=r.item,
                 consumed=r.item_consumed) for r in cs]


def foe_mega_probs(mem: BM.BattleMemory, side: str, rates: Optional[dict] = None) -> Dict[str, float]:
    """{mon name: P(it Megas this turn)} for `side`'s candidates; sums to at most 1."""
    cs = candidates(mem, side)
    ps = {c["name"]: p_mega_now(c["species"], c["k"], c["ncand"], c["lead"], c["item"],
                                c["consumed"], rates) for c in cs}
    total = sum(ps.values())
    if total > 1.0:
        ps = {n: p / total for n, p in ps.items()}
    return ps


def conditional_q(p_now: float, form_mass: float) -> float:
    """Convert P(this mon Megas now) into P(Megas now | the hypothesis carries a Mega form).

    `form_mass` is the belief weight of hypotheses that hold the stone; only those can Evolve."""
    return min(1.0, p_now / form_mass) if form_mass > 0 else 0.0


@lru_cache(maxsize=1)
def _stone_forms() -> dict:
    return {BM._id(n): it["megaStone"] for n, it in damage._raw_db()["items"].items() if it.get("megaStone")}


def mega_gain(species: str, stone: str) -> Optional[tuple]:
    """(offence gain, Speed gain) in base stats if `species` holding `stone` Mega Evolves.

    Humans Mega the larger offence gain 74% of the time when two candidates share the field
    (499 real turn-1 pairs); Speed gain as tie-break only."""
    form = _stone_forms().get(BM._id(stone), {}).get(species)
    sp = damage._raw_db()["species"]
    if form is None or form not in sp or species not in sp:
        return None
    b, m = sp[species]["baseStats"], sp[form]["baseStats"]
    return (max(m["atk"], m["spa"]) - max(b["atk"], b["spa"]), m["spe"] - b["spe"])
