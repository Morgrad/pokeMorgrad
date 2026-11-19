"""GA variation operators: mutation and crossover of genomes.

mutate() applies 1-4 random ops (species / item / ability / nature / EVs / move) to free
slots of a copy; crossover() mixes two parents slot by slot and repairs the species and
item clauses. Locked slots (constraints) are never mutated away.

Split out of src/ga/genome.py on 2026-11-18 (code unchanged).
"""
import copy
import random

from src import regmc_db as DB
from src.ga.genome import (
    _BASE_SPECIES,
    _NATURES,
    _SPECIES_BY_NAME,
    _fresh_mon,
    _legal_items_for,
    _pick_item_for,
    _random_mon,
)

# --- Set generation ---
EV_BUDGET = 66          # Total EVs handed out per mutated spread. Deliberately low: these are

EV_STAT_CAP = 32        # search seeds, not tournament sets; 66 in 32-point chunks ≈ 2 invested stats.

# =============================================================================
# MUTATION
# =============================================================================
def _used_bases(mons, exclude_slot=None):
    """Set of base-species norms currently on the team (for the species clause)."""
    s = set()
    for i, m in enumerate(mons):
        if i == exclude_slot or m is None:
            continue
        sp = _SPECIES_BY_NAME.get(m["species"])
        if sp:
            s.add(DB.norm(sp["baseSpecies"]))
    return s

def _used_items(mons, exclude_slot=None):
    """Set of items currently on the team (for the item clause)."""
    return {m["item"] for i, m in enumerate(mons)
            if i != exclude_slot and m and m.get("item")}

def mutate_species(mons, slot, constraints):
    """Swap one slot's species for a random legal one not already on the team.

    `constraints` is accepted for a uniform mutate() dispatch signature but is
    unused here — locked slots are filtered out by the caller before we're called.
    """
    used = _used_bases(mons, exclude_slot=slot)
    cands = [s["name"] for s in _BASE_SPECIES
             if DB.norm(s["baseSpecies"]) not in used and len(s["moves"]) >= 4]
    if not cands:
        return mons
    new_sp = random.choice(cands)
    mon = _random_mon(new_sp)
    if mon is None:
        return mons
    mon["item"] = _pick_item_for(new_sp, _used_items(mons, exclude_slot=slot))
    mons[slot] = mon
    return mons

def mutate_item(mons, slot):
    """Swap one slot's item for a random legal unused one (item clause preserved)."""
    sp = _SPECIES_BY_NAME.get(mons[slot]["species"])
    if not sp:
        return mons
    used = _used_items(mons, exclude_slot=slot)
    cands = [i for i in _legal_items_for(mons[slot]["species"]) if i not in used]
    if cands:
        mons[slot]["item"] = random.choice(cands)
    return mons

def mutate_ability(mons, slot):
    """Swap to an alternate ability (no-op if the species has only one)."""
    sp = _SPECIES_BY_NAME.get(mons[slot]["species"])
    if not sp or len(sp["abilities"]) < 2:
        return mons
    alts = [a for a in sp["abilities"] if a != mons[slot]["ability"]]
    if alts:
        mons[slot]["ability"] = random.choice(alts)
    return mons

def mutate_nature(mons, slot):
    """Swap to a different nature."""
    alts = [n for n in _NATURES if n != mons[slot]["nature"]]
    mons[slot]["nature"] = random.choice(alts)
    return mons

def mutate_evs(mons, slot):
    """Re-roll the EV spread: hand out EV_BUDGET in EV_STAT_CAP-sized chunks.

    Randomly dumps the budget into stats, each capped at EV_STAT_CAP, until it's
    spent. Zero-valued stats are dropped from the dict (Showdown omits them).
    """
    stats = ["hp", "atk", "def", "spa", "spd", "spe"]
    budget, evs = EV_BUDGET, {s: 0 for s in stats}
    while budget > 0:
        s = random.choice(stats)
        if evs[s] < EV_STAT_CAP:
            add = min(budget, EV_STAT_CAP - evs[s])
            evs[s] += add
            budget -= add
    mons[slot]["evs"] = {s: v for s, v in evs.items() if v > 0}
    return mons

def mutate_move(mons, slot):
    """Swap one of the 4 moves for a random legal one not already known.

    Excludes randomNormal moves (Outrage, Thrash, Uproar, ...) — the
    heuristic pilot can't target them in doubles and Showdown rejects the
    order, cascading into socket death and an infinite retry loop
    (2026-10-15, run p2 island A). Matches the same filter in _random_mon.
    """
    sp = _SPECIES_BY_NAME.get(mons[slot]["species"])
    if not sp:
        return mons
    alts = []
    for m in sp["moves"]:
        if m in mons[slot]["moves"]:
            continue
        data = DB.get_move(m)
        if data and data.get("target") == "randomNormal":
            continue
        alts.append(m)
    if alts:
        mons[slot]["moves"][random.randint(0, 3)] = random.choice(alts)
    return mons

def mutate(mons, constraints, n=None):
    """Apply 1–4 random mutation ops to free (unlocked) slots of a genome copy.

    Operates on a deep copy so the parent genome is never aliased. Locked slots
    (in constraints) are excluded from the target pool. mutate_species needs the
    constraints arg; the rest take only (mons, slot) — hence the dispatch branch.
    """
    mons = copy.deepcopy(mons)
    free_slots = [i for i in range(6) if i not in constraints]
    if not free_slots:
        return mons
    n = n or random.randint(1, 4)
    ops = [mutate_species, mutate_item, mutate_ability,
           mutate_nature, mutate_evs, mutate_move]
    for _ in range(n):
        op = random.choice(ops)
        slot = random.choice(free_slots)
        mons = op(mons, slot, constraints) if op == mutate_species else op(mons, slot)
    return mons

def repair_clauses(mons, constraints):
    """Make a 6-mon genome obey the species clause and the item clause; returns it.

    The one shared clause repair (refactor B2, 2026-11-18), used by crossover and
    legality.enforce_constraints. Edits in place (mutate_species writes into the list).
    1. Species clause: base species of the locked slots are reserved first; walking the
       free slots in order, a mon whose base species was already seen is re-rolled with
       mutate_species (locked slots are never touched).
    2. Item clause: walking all slots in order, a duplicate item is re-picked with
       _pick_item_for (the earlier slot keeps it).
    Draws from `random` only when something is repaired, so a valid genome passes through
    unchanged and without changing the random stream.
    """
    # Species clause
    seen = set()
    for i, m in enumerate(mons):
        if i in constraints:
            sp = _SPECIES_BY_NAME.get(m["species"])
            if sp:
                seen.add(DB.norm(sp["baseSpecies"]))
    for i, m in enumerate(mons):
        if i in constraints:
            continue
        sp = _SPECIES_BY_NAME.get(m["species"])
        if not sp:
            continue
        base = DB.norm(sp["baseSpecies"])
        if base in seen:
            mons = mutate_species(mons, i, constraints)
            sp2 = _SPECIES_BY_NAME.get(mons[i]["species"])
            if sp2:
                seen.add(DB.norm(sp2["baseSpecies"]))
        else:
            seen.add(base)
    # Item clause
    seen_items = set()
    for m in mons:
        if m["item"] in seen_items:
            m["item"] = _pick_item_for(m["species"], seen_items)
        seen_items.add(m["item"])
    return mons

def crossover(p1, p2, constraints):
    """Breed two parents slot-by-slot, then repair the species and item clauses.

    Each free slot inherits from a random parent; locked slots take the parent
    that actually holds the mandated species (rebuilding if neither does). The
    naive per-slot mix can duplicate a base species or item, so repair_clauses
    follows: re-roll species-clause violators via mutate_species, then re-pick any
    duplicate item via _pick_item_for.
    """
    child = []
    for i in range(6):
        if i in constraints:
            want = constraints[i]
            if p1[i] and p1[i].get("species") == want:
                child.append(copy.deepcopy(p1[i]))
            elif p2[i] and p2[i].get("species") == want:
                child.append(copy.deepcopy(p2[i]))
            else:
                # Neither parent has locked species — rebuild with proper item
                mon = _fresh_mon(want, set())
                if mon is None:
                    raise ValueError(f"cannot build locked slot {i}: {want}")
                child.append(mon)
        else:
            child.append(copy.deepcopy(random.choice([p1[i], p2[i]])))
    return repair_clauses(child, constraints)
