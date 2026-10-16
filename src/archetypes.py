"""Opponent set posterior from real-team archetypes (data/species_archetypes.json).

An archetype is an (item, nature) group of real sets for one species (tools/build_archetypes.py).
Given what we have seen of an opposing mon (its item, moves used, ability, Mega form) this returns
a weighted list of archetypes: weight = (#sets in the group) x P(evidence | group). It is what lets
a Garchomp that used Power Gem be recognised as the Garchompite Z special set and one holding a
Choice Scarf as a physical set, instead of mixing both.

Evidence model (soft, because pastes are not exhaustive):
  - revealed item: matches the group's item or is down-weighted to MISMATCH.
  - Mega form seen (e.g. Garchomp-Mega-Z): only groups whose stone yields that form.
  - each revealed move m: P(m | group) = (c_group(m) + K * f_species(m)) / (n_group + K), floored.
  - revealed ability: same smoothed form over the group's ability counts.

Torch-free and poke_env-free: pure data in, pure data out.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

from src.paths import data_path

MISMATCH = 0.02      # likelihood floor for a contradicted observation
K = 2.0              # smoothing toward the species-level frequency
MIN_SETS = 5         # below this a species falls back to the marginal priors


def _id(name) -> str:
    return "".join(c for c in str(name).lower() if c.isalnum())


@lru_cache(maxsize=1)
def load_table() -> dict:
    try:
        with open(data_path("species_archetypes.json")) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _smoothed(count: float, n: float, species_freq: float) -> float:
    return max(MISMATCH, (count + K * species_freq) / (n + K))


def posterior(entry: dict, item: Optional[str] = None, moves_seen: Sequence[str] = (),
              ability: Optional[str] = None, form: Optional[str] = None) -> List[Tuple[float, dict]]:
    """[(weight, archetype)] sorted by weight, weights sum to 1. `entry` is one species' table row."""
    archs = entry["archetypes"]
    if form:
        same_form = [a for a in archs if a.get("form") == form]
        archs = same_form or archs        # unseen form combo: don't throw the evidence away
    n_species = float(entry["n"]) or 1.0
    species_moves: Dict[str, float] = {}
    species_abilities: Dict[str, float] = {}
    for a in entry["archetypes"]:
        for m, c in a["moves"].items():
            species_moves[_id(m)] = species_moves.get(_id(m), 0.0) + c
        for ab, c in a["abilities"].items():
            species_abilities[_id(ab)] = species_abilities.get(_id(ab), 0.0) + c

    item_id = _id(item) if item and _id(item) not in ("", "unknownitem", "none") else None
    seen = [_id(m) for m in moves_seen]
    out = []
    for a in archs:
        w = float(a["count"])
        n = w
        if item_id is not None and _id(a["item"]) != item_id:
            w *= MISMATCH
        a_moves = {_id(m): c for m, c in a["moves"].items()}
        for m in seen:
            w *= _smoothed(a_moves.get(m, 0.0), n, species_moves.get(m, 0.0) / n_species)
        if ability:
            a_ab = {_id(x): c for x, c in a["abilities"].items()}
            w *= _smoothed(a_ab.get(_id(ability), 0.0), n, species_abilities.get(_id(ability), 0.0) / n_species)
        out.append((w, a))
    total = sum(w for w, _ in out)
    if total <= 0:
        return []
    return sorted(((w / total, a) for w, a in out), key=lambda t: -t[0])


def item_distribution(post: List[Tuple[float, dict]]) -> Dict[str, float]:
    """P(item) marginalised over a posterior."""
    out: Dict[str, float] = {}
    for w, a in post:
        out[a["item"]] = out.get(a["item"], 0.0) + w
    return out


def move_distribution(post: List[Tuple[float, dict]]) -> Dict[str, float]:
    """P(species carries move m) marginalised over a posterior (each group's move share)."""
    out: Dict[str, float] = {}
    for w, a in post:
        n = float(a["count"]) or 1.0
        for m, c in a["moves"].items():
            out[m] = out.get(m, 0.0) + w * min(1.0, c / n)
    return out
