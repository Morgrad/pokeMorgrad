"""Meta weights: how much each opponent team should count, from ladder-replay species usage.

usage[species] = share of ladder teams (replay sides) that carry the species. A team's weight is the
mean usage of its six species (unseen species count as FLOOR), so teams built from what the ladder
actually plays count more. The GA's fitness is the weighted win rate over the opponent pool; rebuild
data/species_ladder_usage.json with tools/build_meta_weights.py when new replays arrive.

Species are keyed by one function for team pastes and replay `|poke|` lines: nicknames and gender tags
are dropped (src.regmc_db.normalize_species_name) and every forme folds into its base species (Mega,
gender, Rotom-Wash, Floette-Eternal -> Floette), so a Mega in a paste matches its unmegaed form in a replay.
"""
from __future__ import annotations

import glob
import json
import os
import re
from functools import lru_cache
from typing import Optional

from src import regmc_db as DB
from src.paths import data_path

USAGE_PATH = data_path("species_ladder_usage.json")
FLOOR = 0.02
_POKE_LINE = re.compile(r"\|poke\|(p[12])\|([^|]+)\|")


def species_key(raw: str) -> str:
    sp = DB.get_species(DB.normalize_species_name(raw))
    if not sp:
        return DB.norm(raw.split(",")[0])
    return DB.norm(sp["baseSpecies"])


def team_keys(text: str) -> list[str]:
    return [species_key(m["species"]) for m in DB.parse_team(text)]


def usage_from_replays(replay_dir: str) -> tuple[dict, int]:
    """(usage rate per species key, number of team sides counted) over data/showdown_replays/*.json."""
    count: dict[str, int] = {}
    sides = 0
    for path in glob.glob(os.path.join(replay_dir, "*.json")):
        if path.endswith(".meta.json"):
            continue
        try:
            log = json.load(open(path)).get("log", "")
        except (OSError, ValueError):
            continue
        per_side: dict[str, set] = {"p1": set(), "p2": set()}
        for side, name in _POKE_LINE.findall(log):
            per_side[side].add(species_key(name.split(",")[0]))
        for keys in per_side.values():
            if keys:
                sides += 1
                for k in keys:
                    count[k] = count.get(k, 0) + 1
    return {k: v / sides for k, v in count.items()} if sides else {}, sides


def save_usage(usage: dict, sides: int, path: str = USAGE_PATH) -> None:
    with open(path, "w") as f:
        json.dump({"n_sides": sides, "floor": FLOOR, "usage": dict(sorted(usage.items(), key=lambda kv: -kv[1]))},
                  f, indent=1)


@lru_cache(maxsize=1)
def load_usage(path: str = USAGE_PATH) -> dict:
    return json.load(open(path))["usage"]


def team_weight(text: str, usage: Optional[dict] = None, floor: float = FLOOR) -> float:
    usage = load_usage() if usage is None else usage
    keys = team_keys(text)
    if not keys:
        return floor
    return sum(max(usage.get(k, 0.0), floor) for k in keys) / len(keys)


def weights_by_text(teams, usage: Optional[dict] = None) -> dict:
    return {t: team_weight(t, usage) for t in teams}


def weighted_rate(outcomes, weights) -> float:
    """Weighted win rate; outcomes of None (no usable result) are dropped. 0.0 if nothing is usable."""
    pairs = [(o, w) for o, w in zip(outcomes, weights) if o is not None]
    total = sum(w for _, w in pairs)
    return sum(o * w for o, w in pairs) / total if total else 0.0


def effective_n(weights) -> float:
    """Kish effective sample size of a weight vector (n when uniform)."""
    s, s2 = sum(weights), sum(w * w for w in weights)
    return s * s / s2 if s2 else 0.0
