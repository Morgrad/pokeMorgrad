"""Genome encoding and random team building for the GA.

A genome is a list of 6 mon dicts {species, item, ability, nature, evs, moves}. This module
holds the legal roster, the usage priors, the random set builder (role-consistent moves, EVs,
nature; meta-weighted items) and the conversion to / from Showdown team text.

Split on 2026-11-18 (code moved unchanged):
  src/ga/pools.py      opponent team pools (train / validation / held-out)
  src/ga/legality.py   Showdown legality gate, Protect / Fake Out composition, locked slots
  src/ga/operators.py  mutation and crossover
"""
import json
import os
import random
from functools import lru_cache

from src import regmc_db as DB
from src.paths import data_path

# --- Team realism constraints ---
# The GA optimizes for the heuristic pilot, which ignores items, Protect
# timing, and Fake Out priority. Left unconstrained, it produces champions
# full of dead items and no tactical moves — real VGC players laugh at them.
# These constraints make champions look like top-cut teams without touching
# the model or the pilot.
CANONICAL_ITEMS = (
    "Leftovers", "Sitrus Berry", "Focus Sash", "Life Orb",
    "Choice Scarf", "Choice Specs", "Assault Vest", "Rocky Helmet",
)

# =============================================================================
# CACHED ROSTER
# =============================================================================
# Loaded once at import and reused for every genome built this run. Filtering to
# species that actually have moves avoids ever building a mon we can't legalize.
_BASE_SPECIES = [s for s in DB.all_species_base() if s["moves"]]

_SPECIES_BY_NAME = {s["name"]: s for s in _BASE_SPECIES}

_ITEMS = list(DB.all_items())

_NATURES = [n["name"] for n in DB.all_natures()]

_MOVE_PRIORS = None

def move_priors_for(species_name, top_n=8):
    """Top-N moves by tournament usage count for a species, or None.

    Returns a list of (move_name, count) pairs. Caller decides how to
    filter/weight. Lazily loads the file once.
    """
    global _MOVE_PRIORS
    if _MOVE_PRIORS is None:
        path = data_path("species_move_priors.json")
        _MOVE_PRIORS = json.load(open(path)) if os.path.exists(path) else {}
    entries = _MOVE_PRIORS.get(species_name, [])
    if not entries:
        return None
    ranked = sorted(entries, key=lambda e: -e.get("count", 0))[:top_n]
    out = [(e["move"], e.get("count", 1)) for e in ranked]
    return out or None

_META_ITEMS = None

def meta_items_for(species_name):
    """List of (item_name, count) for a species, from real tournament usage.

    `count` is a raw frequency weight (consumed by random.choices in
    _pick_item_for), not a normalized probability. Lazily loads meta_items.json
    on first call; returns None when we have no usage data for the species.
    """
    global _META_ITEMS
    if _META_ITEMS is None:
        path = data_path("meta_items.json")
        _META_ITEMS = json.load(open(path)) if os.path.exists(path) else {}
    entries = _META_ITEMS.get(species_name, [])
    return [(e["item"], e["count"]) for e in entries] if entries else None

# =============================================================================
# SET GENERATION
# =============================================================================
@lru_cache(maxsize=None)
def _legal_items_for(species_name):
    """Items this species may legally hold.

    Mega stones are species-locked (only the matching mon may hold its stone;
    every other stone is filtered out), and `itemUser` items (e.g. signature
    berries) are restricted to their listed users. Everything else is fair game.
    Falls back to ("Leftovers",) so a caller always has something to choose.

    Cached: the legal set for a species never changes within a run (it's a pure
    function of the static item/species tables), and this sits on the set-build
    hot path. Returns a *tuple* so the cached value can't be mutated by a caller —
    every call site either iterates it, wraps it in set(), or random.choice()s it,
    all of which accept a tuple unchanged.
    """
    sp = _SPECIES_BY_NAME.get(species_name)
    if not sp:
        return ("Leftovers",)
    stones = set(sp["megaStones"])
    out = []
    for it in _ITEMS:
        name = it["name"]
        if name in stones:
            out.append(name)
            continue
        if it.get("megaStone"):
            continue  # a different species's stone
        users = it.get("itemUser")
        if users:
            target = DB.norm(species_name)
            if not any(DB.norm(u) == target for u in users):
                continue
        out.append(name)
    return tuple(out) or ("Leftovers",)

def _species_role(sp):
    """Classify a species into a single offensive role for this genome.

    Returns one of: 'physical', 'special', 'support'.

    Design: no 'mixed' role. Real teams commit to one EV spread; the
    population explores the other build by generating a different genome with
    the opposite coin flip. This matches how tournament teams are built and
    keeps EV/nature/moveset internally consistent.

    Thresholds:
      peak < 80  -> support   (Umbreon 65/60; can't carry either offense)
      low  < 80  -> commit    (Gengar 65/130; 65 Atk is unusable)
      else       -> coin flip (Salamence 135/110, Dragapult 120/100,
                               Arcanine 110/100, Archaludon 105/125)
    """
    stats = sp.get("baseStats") or {}
    atk = stats.get("atk", 0)
    spa = stats.get("spa", 0)
    if atk == 0 and spa == 0:
        return "physical"        # no data — arbitrary but deterministic
    peak = max(atk, spa)
    low = min(atk, spa)
    if peak < 80:
        return "support"
    if low < 80:
        return "physical" if atk > spa else "special"
    # Both viable — commit to one side at random.
    return random.choice(("physical", "special"))

def _score_move_for_role(move_name, role):
    """Bias weight for a move given the genome's committed role.

    3 = strongly preferred (correct offensive category)
    2 = neutral (Status, or any offensive move on support role)
    1 = mild dislike (off-role offensive move — rare coverage slot)
    """
    data = DB.get_move(move_name)
    if not data:
        return 2
    cat = data.get("category", "Status")
    if cat == "Status":
        return 2
    if role == "support":
        return 2
    if role == "physical":
        return 3 if cat == "Physical" else 1
    if role == "special":
        return 3 if cat == "Special" else 1
    return 2

def _weighted_sample_no_replace(items, weights, k):
    """Sample k distinct items with weights. Weights must be > 0."""
    pool = list(items)
    w = list(weights)
    out = []
    for _ in range(min(k, len(pool))):
        idx = random.choices(range(len(pool)), weights=w, k=1)[0]
        out.append(pool.pop(idx))
        w.pop(idx)
    return out

def _preferred_pool(legal_moves, role):
    """Split a move pool into (preferred, fallback) by role.

    Preferred = moves whose category matches the role, plus any Status move.
    Fallback = off-role offensive moves.

    Returns (preferred, fallback) lists.
    """
    preferred, fallback = [], []
    for mv in legal_moves:
        data = DB.get_move(mv)
        cat = data.get("category", "Status") if data else "Status"
        if cat == "Status":
            preferred.append(mv)
            continue
        if role == "support":
            fallback.append(mv)
            continue
        if role == "physical":
            (preferred if cat == "Physical" else fallback).append(mv)
        elif role == "special":
            (preferred if cat == "Special" else fallback).append(mv)
        else:
            preferred.append(mv)
    return preferred, fallback

def _random_mon(species_name):
    """Build a random legal set for a species, or None if it can't field 4 moves.

    The EV spread + nature are picked to match the moveset's damage class:
    mostly-physical → offensive Jolly, mostly-special → Modest, mixed/none →
    a bulky Calm spread. Item is a placeholder here; callers overwrite it with
    _pick_item_for to apply the meta bias and dedupe within a team.

    Moves with target="randomNormal" (Outrage, Thrash, Uproar, ...) are EXCLUDED.
    poke_env's SimpleHeuristicsPlayer doesn't attach a move_target for these in
    doubles, so Showdown rejects the order with "[Invalid choice] Can't move: X
    needs a target" — the battle is dropped as a None result and the fitness
    denominator shrinks. Cheap to avoid: just don't generate those moves.
    """
    sp = _SPECIES_BY_NAME.get(species_name)
    if not sp or len(sp["moves"]) < 4:
        return None

    legal = []
    for mv in sp["moves"]:
        data = DB.get_move(mv)
        if not data:
            continue
        if data.get("target") == "randomNormal":
            continue    # heuristic can't target these correctly in doubles
        legal.append(mv)

    if len(legal) < 4:
        return None

    role = _species_role(sp)
    moves = None

    # Preferred path: tournament usage priors. Real teams use 6-10 of a
    # species' 40-80 legal moves; sampling from the full pool produces
    # Copycat-Rest nonsense. Priors give us the real set.
    priors = move_priors_for(species_name)
    if priors:
        priors_legal = [(mv, w) for mv, w in priors if mv in legal]
        if len(priors_legal) >= 4:
            # Restrict to role-matching categories when we have 4+ such moves
            role_matched = [(mv, w) for mv, w in priors_legal
                            if _score_move_for_role(mv, role) >= 2]
            if len(role_matched) >= 4:
                priors_legal = role_matched
            items = [mv for mv, _ in priors_legal]
            weights = [w for _, w in priors_legal]
            moves = _weighted_sample_no_replace(items, weights, 4)

    # Fallback: role-weighted random over the full legal pool.
    if moves is None:
        preferred, fallback = _preferred_pool(legal, role)
        if len(preferred) >= 4:
            weights = [2 ** _score_move_for_role(mv, role) for mv in preferred]
            moves = _weighted_sample_no_replace(preferred, weights, 4)
        else:
            combined = preferred + fallback
            weights = [2 ** _score_move_for_role(mv, role) for mv in combined]
            moves = _weighted_sample_no_replace(combined, weights, 4)

    # EVs + nature follow the committed role, NOT the sampled move count.
    # Role was already coin-flipped above; this makes the whole genome
    # internally consistent (moves, EVs, nature all align to one offense).
    if role == "physical":
        evs, nature = {"hp": 2, "atk": 32, "spe": 32}, "Jolly"
    elif role == "special":
        evs, nature = {"hp": 2, "spa": 32, "spe": 32}, "Modest"
    else:  # support
        evs, nature = {"hp": 32, "def": 20, "spd": 14}, "Calm"
    return {
        "species": species_name,
        "item": random.choice(_legal_items_for(species_name)),
        "ability": random.choice(sp["abilities"] or ["Pressure"]),
        "nature": nature,
        "evs": evs,
        "moves": moves,
    }

def _pick_item_for(species_name, used_items):
    """Pick an item a real team would plausibly run, avoiding item-clause dupes.

    Priority:
      1. Mega stone not yet used on this team (only choice for mega species).
      2. Meta items from real tournament usage, weighted by frequency, if the
         species has an entry — restricted to items this species can legally
         hold and that aren't already on the team.
      3. Canonical competitive items (CANONICAL_ITEMS ∩ legal ∩ unused).
      4. Last resort: any legal unused item.

    Realism: dead items (Binding Band on a mon with no binding moves, Heat Rock
    with no sun setter) are eliminated by construction because real tournament
    data never contains them for these species, and the canonical fallback is
    competitive staples. The pilot is blind to items; the GA exploited that.
    """
    sp = _SPECIES_BY_NAME.get(species_name)
    if not sp:
        return "Leftovers"
    for stone in sp["megaStones"]:
        if stone not in used_items:
            return stone

    legal_set = set(_legal_items_for(species_name)) - used_items

    # 2. Meta items, weighted
    meta = meta_items_for(species_name)
    if meta:
        candidates = [(i, w) for i, w in meta if i in legal_set]
        if candidates:
            items, weights = zip(*candidates)
            return random.choices(items, weights=weights, k=1)[0]

    # 3. Canonical fallback
    canonical = [i for i in CANONICAL_ITEMS if i in legal_set]
    if canonical:
        return random.choice(canonical)

    # 4. Last resort
    legal = [i for i in _legal_items_for(species_name) if i not in used_items]
    return random.choice(legal) if legal else "Leftovers"

def _fresh_mon(species_name, used_items):
    """Build one mon with a proper item. Used for locked slots."""
    mon = _random_mon(species_name)
    if mon is None:
        return None
    mon["item"] = _pick_item_for(species_name, used_items)
    return mon

def build_random_genome(constraints):
    """Build a full 6-mon genome honoring locks, the species clause, and item dupes.

    Locked slots (constraints) are filled first with their mandated species; the
    rest are filled from a shuffled roster, skipping any base species already on
    the team (species clause) and any mon we can't build. Returns None if a slot
    can't be filled — the caller is expected to retry or drop the genome.
    """
    mons = [None] * 6
    used_bases, used_items = set(), set()
    for slot, sp_name in constraints.items():
        if sp_name not in _SPECIES_BY_NAME:
            raise ValueError(f"unknown species for lock: {sp_name}")
        mon = _fresh_mon(sp_name, used_items)
        if mon is None:
            raise ValueError(f"cannot build locked slot {slot}: {sp_name}")
        mons[slot] = mon
        used_items.add(mon["item"])
        used_bases.add(DB.norm(_SPECIES_BY_NAME[sp_name]["baseSpecies"]))
    pool = [s["name"] for s in _BASE_SPECIES]
    for slot in range(6):
        if mons[slot] is not None:
            continue
        random.shuffle(pool)
        for cand in pool:
            sp = _SPECIES_BY_NAME[cand]
            if DB.norm(sp["baseSpecies"]) in used_bases:
                continue
            mon = _fresh_mon(cand, used_items)
            if mon is None:
                continue
            mons[slot] = mon
            used_items.add(mon["item"])
            used_bases.add(DB.norm(sp["baseSpecies"]))
            break
    if any(m is None for m in mons):
        return None
    return mons

# =============================================================================
# SERIALIZE
# =============================================================================
def genome_to_text(mons):
    """Render a genome as a Showdown team paste (the format every tool consumes)."""
    lines = []
    for m in mons:
        lines.append(f"{m['species']} @ {m['item']}")
        lines.append(f"Ability: {m['ability']}")
        lines.append("Level: 50")
        lines.append(f"{m['nature']} Nature")
        ev = " / ".join(f"{v} {k.upper()}" for k, v in m["evs"].items() if v > 0)
        lines.append(f"EVs: {ev}" if ev else "EVs: 0 HP")
        for mv in m["moves"]:
            lines.append(f"- {mv}")
        lines.append("")
    return "\n".join(lines)

def text_to_genome(text):
    """Parse a Showdown team paste back into a genome. None unless it's exactly 6 mons."""
    mons = DB.parse_team(text)
    if len(mons) != 6:
        return None
    return [{
        "species": m["species"], "item": m["item"], "ability": m["ability"],
        "nature": m["nature"], "evs": m["evs"], "moves": m["moves"],
    } for m in mons]
