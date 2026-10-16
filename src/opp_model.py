"""Opponent build estimation (hidden stats / abilities) for battle-time damage math.

poke_env never fills `Pokemon.stats` for opposing mons, so anything that wants a
damage estimate must guess the hidden spread. We guess from the scraped build
priors (data/species_build_priors.json): the top-K most common (EVs, nature)
builds per species, weighted by how often they appear. Callers treat the result
as a mixture, so one wrong guess costs probability mass, not a crash.

Torch-free and poke_env-free on purpose: pure data in, pure data out.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

from src import damage
from src.paths import data_path

LEVEL = 50
TOP_K = 3
STATS = ("hp", "atk", "def", "spa", "spd", "spe")

# ability id -> the move type it nullifies (hit probability, not damage, is what changes)
IMMUNITY_ABILITIES = {
    "levitate": "Ground", "eartheater": "Ground",
    "flashfire": "Fire", "wellbakedbody": "Fire",
    "waterabsorb": "Water", "stormdrain": "Water", "dryskin": "Water",
    "voltabsorb": "Electric", "lightningrod": "Electric", "motordrive": "Electric",
    "sapsipper": "Grass",
}


def to_id(name) -> str:
    return "".join(c for c in str(name).lower() if c.isalnum())


@dataclass(frozen=True)
class Build:
    weight: float
    nature: str
    evs: Dict[str, int]
    stats: Dict[str, int]      # final level-50 stats, includes "hp"

    @property
    def max_hp(self) -> int:
        return self.stats["hp"]


@lru_cache(maxsize=1)
def _species_index() -> Dict[str, str]:
    """to_id(name or id) -> DB species name."""
    out = {}
    for name, entry in damage._raw_db()["species"].items():
        out[to_id(name)] = name
        out[to_id(entry.get("id", name))] = name
    return out


@lru_cache(maxsize=1)
def _build_priors() -> dict:
    with open(data_path("species_build_priors.json")) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _ability_priors() -> dict:
    with open(data_path("species_ability_priors.json")) as f:
        return json.load(f)


def resolve_species(species) -> Optional[str]:
    """poke_env species id/name -> DB species name, or None if unknown."""
    if species is None:
        return None
    return _species_index().get(to_id(species))


def _prior_key(db_name: str, table: dict) -> Optional[str]:
    """Exact name, else the base species (priors are keyed by the paste's species
    name, which for mega forms may be the base)."""
    if db_name in table:
        return db_name
    base = db_name.split("-Mega")[0]
    return base if base in table else None


def stats_for(db_name: str, evs: Dict[str, int], nature: Optional[str]) -> Dict[str, int]:
    return {s: damage.stat_at_level(db_name, s, evs.get(s, 0), 31, nature, LEVEL)
            for s in STATS}


def _generic_spread(db_name: str):
    """Fallback when a species has no priors: bulky attacker on its better offense stat."""
    base = damage.DB.get_species(db_name)["baseStats"]
    if base["atk"] >= base["spa"]:
        return "Adamant", {"hp": 32, "atk": 32, "spe": 2}
    return "Modest", {"hp": 32, "spa": 32, "spe": 2}


def opponent_builds(species, k: int = TOP_K) -> List[Build]:
    """Top-k plausible builds for `species`, weights sum to 1. Empty if species unknown."""
    db_name = resolve_species(species)
    if db_name is None:
        return []
    table = _build_priors()
    key = _prior_key(db_name, table)
    raw = sorted(table[key], key=lambda e: -e.get("count", 1))[:k] if key else []
    if not raw:
        nature, evs = _generic_spread(db_name)
        return [Build(1.0, nature, evs, stats_for(db_name, evs, nature))]
    total = float(sum(e.get("count", 1) for e in raw))
    return [Build(e.get("count", 1) / total, e.get("nature"), dict(e["evs"]),
                  stats_for(db_name, e["evs"], e.get("nature")))
            for e in raw]


def ability_distribution(species, known_ability: Optional[str] = None) -> Dict[str, float]:
    """{ability id: probability} for `species`. A revealed ability is certain; otherwise the
    ability priors, falling back to a uniform guess over the species' DB abilities."""
    if known_ability:
        return {to_id(known_ability): 1.0}
    db_name = resolve_species(species)
    if db_name is None:
        return {}
    table = _ability_priors()
    key = _prior_key(db_name, table)
    if key:
        entries = {e["ability"]: e.get("count", 1) for e in table[key]}
    else:
        entries = {a: 1 for a in damage.DB.get_species(db_name).get("abilities", [])}
    total = float(sum(entries.values()))
    if total <= 0:
        return {}
    out: Dict[str, float] = {}
    for a, c in entries.items():
        out[to_id(a)] = out.get(to_id(a), 0.0) + c / total
    return out


def immunity_prob(species, move_type: str, known_ability: Optional[str] = None) -> float:
    """P(target's ability nullifies a `move_type` attack)."""
    return sum(p for a, p in ability_distribution(species, known_ability).items()
               if IMMUNITY_ABILITIES.get(a) == move_type)
