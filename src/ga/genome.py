import copy
import glob
import json
import os
import random
from functools import lru_cache

from src import regmc_db as DB
from src import showdown_validator as SV
from src.paths import data_path

# Extracted from ga_core.py

# --- Set generation ---
EV_BUDGET = 66          # Total EVs handed out per mutated spread. Deliberately low: these are

EV_STAT_CAP = 32        # search seeds, not tournament sets; 66 in 32-point chunks ≈ 2 invested stats.

# --- Legality gate ---
MAX_REBUILD_TRIES = 20  # Illegal genome: rebuild from scratch up to N times before dropping it.

# --- Champion selection ---
# Reserve a slice of the training pool that the GA never samples for fitness.
# Champion files are saved from the best genome by validation score, not by
# training fitness. Island B (2026-10-13) was 68% on the training pool but
# 58.7% held-out — the training-best overfit. A validation slice catches that.
VAL_POOL_SIZE = 30

VAL_SPLIT_SEED = 42

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

PROTECT_MOVES = (
    "Protect", "Detect", "Spiky Shield", "King's Shield",
    "Baneful Bunker", "Silk Trap", "Burning Bulwark",
)

FAKEOUT_MOVES = ("Fake Out", "Follow Me", "Rage Powder")

# =============================================================================
# CACHED ROSTER
# =============================================================================
# Loaded once at import and reused for every genome built this run. Filtering to
# species that actually have moves avoids ever building a mon we can't legalize.
_BASE_SPECIES = [s for s in DB.all_species_base() if s["moves"]]

_SPECIES_BY_NAME = {s["name"]: s for s in _BASE_SPECIES}

_ITEMS = list(DB.all_items())

_NATURES = [n["name"] for n in DB.all_natures()]

_REGIONAL_DIR = data_path("regional_teams")

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

def _load_teams(files, label):
    """Load team strings from a list of paths.

    pool_split.json historically stored absolute paths from another host, so
    each entry is resolved by basename against the local regional_teams dir.
    Loud on failure: a silently-empty pool used to look like a 0% eval.
    """
    teams, missing = [], 0
    for f in files:
        path = os.path.join(_REGIONAL_DIR, os.path.basename(f))
        try:
            text = open(path).read().strip()
            if text:
                teams.append(text)
            else:
                missing += 1
        except OSError:
            missing += 1
    if missing:
        print(f"WARNING: {label} pool: {missing}/{len(files)} teams failed to load "
              f"from {_REGIONAL_DIR}")
    if files and not teams:
        raise RuntimeError(
            f"{label} pool is empty: none of {len(files)} team files could be "
            f"read from {_REGIONAL_DIR}. Check data/regional_teams/ exists."
        )
    return teams

_REGIONAL = None

def regional_pool():
    """Training pool of team strings."""
    global _REGIONAL
    if _REGIONAL is None:
        split_path = data_path("pool_split.json")
        if os.path.exists(split_path):
            split = json.load(open(split_path))
            _REGIONAL = _load_teams(split.get("train", []), "training")
        else:
            files = sorted(glob.glob(os.path.join(_REGIONAL_DIR, "*.txt")))
            _REGIONAL = _load_teams(files, "training")
    return _REGIONAL

_HELDOUT = None

def _split_train_val(pool, val_size=VAL_POOL_SIZE, seed=VAL_SPLIT_SEED):
    """Deterministically split the training pool into (train, val) by index.

    Index-based, not string-based, because regional teams can duplicate.
    Union of train and val equals the original pool.
    """
    rng = random.Random(seed)
    idxs = list(range(len(pool)))
    rng.shuffle(idxs)
    val_idxs = set(idxs[:val_size])
    train = [pool[i] for i in range(len(pool)) if i not in val_idxs]
    val = [pool[i] for i in sorted(val_idxs)]
    return train, val

def heldout_pool():
    """Held-out pool (100 teams). Used for final eval only."""
    global _HELDOUT
    if _HELDOUT is None:
        split_path = data_path("pool_split.json")
        if os.path.exists(split_path):
            split = json.load(open(split_path))
            _HELDOUT = _load_teams(split.get("holdout", []), "held-out")
        else:
            _HELDOUT = regional_pool()
    return _HELDOUT

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

# =============================================================================
# TEAM REALISM CONSTRAINTS
# =============================================================================
def _force_move_on_slot(genome, slot, candidate_moves):
    """Try to replace one of slot's moves with the first learnable candidate.

    Returns True if the swap succeeded, False if no candidate is learnable by
    that species. Preserves species identity; item/EV/nature untouched.
    """
    mon = genome[slot]
    sp = _SPECIES_BY_NAME.get(mon["species"])
    if not sp:
        return False
    learnable = [mv for mv in candidate_moves if mv in sp["moves"]]
    if not learnable:
        return False
    pick = learnable[0]
    if pick in mon["moves"]:
        return False  # already has it, nothing to do
    # Replace a move that isn't Protect-family and isn't the candidate
    for i, mv in enumerate(mon["moves"]):
        if mv not in PROTECT_MOVES and mv not in FAKEOUT_MOVES:
            mon["moves"][i] = pick
            return True
    # All 4 moves are Protect/FakeOut family — replace slot 0 anyway
    mon["moves"][0] = pick
    return True

def _enforce_composition(genome):
    """Ensure team has Protect coverage and turn-1 disruption.

    Soft constraints: if no mon on the team can learn the required move, the
    genome passes through unchanged. Idempotent: a genome that already has
    the coverage gets no edits.
    """
    if not genome or len(genome) != 6:
        return genome

    # --- Protect coverage ---
    has_protect = any(
        any(mv in PROTECT_MOVES for mv in (m.get("moves") or []))
        for m in genome if m
    )
    if not has_protect:
        # Try slots in a shuffled order so different genomes get different
        # Protect users — avoids every champion looking identical.
        slots = list(range(6))
        random.shuffle(slots)
        for slot in slots:
            if _force_move_on_slot(genome, slot, PROTECT_MOVES):
                break

    # --- Fake Out / redirection coverage ---
    has_fakeout = any(
        any(mv in FAKEOUT_MOVES for mv in (m.get("moves") or []))
        for m in genome if m
    )
    if not has_fakeout:
        slots = list(range(6))
        random.shuffle(slots)
        for slot in slots:
            if _force_move_on_slot(genome, slot, FAKEOUT_MOVES):
                break

    return genome

# =============================================================================
# SHOWDOWN LEGALITY GATE
# =============================================================================
def filter_legal_genomes(genomes, constraints):
    """Return only Showdown-legal genomes, rebuilding invalid ones in place.

    Each genome is validated by the real Showdown team validator (via SV). An
    invalid genome is replaced by a freshly built one, retried up to
    MAX_REBUILD_TRIES times; if none of the rebuilds pass, that slot is simply
    dropped (the population is topped back up by the caller). Output length may
    therefore be < len(genomes), and survivors keep their input order.

    Batched to cut subprocess spawns: SV.check_teams validates a whole list in a
    single Showdown process, so instead of one validator call per rebuild attempt
    (worst case n + MAX_REBUILD_TRIES·bad spawns per generation) we validate by
    *attempt index* — one batched call for the initial population, then one per
    rebuild round over only the still-failing slots, worst case
    MAX_REBUILD_TRIES+1 calls total.

    Equivalence note: initially-legal genomes pass through byte-identical and in
    order. Rebuilt genomes are random either way; batching consumes the RNG
    round-major instead of per-genome, so a specific replacement's identity can
    differ from the old path — but the per-genome pass/fail, the input ordering,
    and the MAX_REBUILD_TRIES-per-genome cap (a None build still burns a try) are
    preserved exactly.
    """
    # result[i] holds the legal genome for input slot i (original or a rebuild),
    # or None if that slot was dropped. Reassembled in input order at the end.
    result = [None] * len(genomes)
    verdicts = SV.check_teams([genome_to_text(g) for g in genomes])

    # Slots still needing a legal replacement, each with its remaining try budget.
    pending = {}
    for i, (g, (ok, _msg)) in enumerate(zip(genomes, verdicts)):
        if ok:
            result[i] = g
        else:
            pending[i] = MAX_REBUILD_TRIES

    while pending:
        # One attempt for every still-failing slot. Building consumes a try even
        # when build_random_genome returns None (mirrors the original loop, where
        # a None fresh still burned one of the MAX_REBUILD_TRIES iterations).
        fresh_by_idx = {}
        for i in list(pending):
            pending[i] -= 1
            fresh = build_random_genome(constraints)
            if fresh is not None:
                fresh_by_idx[i] = fresh

        # Validate this round's successfully-built candidates in one batched call.
        if fresh_by_idx:
            idxs = list(fresh_by_idx)
            round_verdicts = SV.check_teams([genome_to_text(fresh_by_idx[i]) for i in idxs])
            for i, (ok2, _msg) in zip(idxs, round_verdicts):
                if ok2:
                    result[i] = fresh_by_idx[i]
                    del pending[i]

        # Drop any slot that has exhausted its attempts without a legal rebuild.
        for i in list(pending):
            if pending[i] <= 0:
                del pending[i]

    legal = [g for g in result if g is not None]
    # Apply team-realism constraints once, on every genome that leaves the
    # gate. This is the single choke point shared by init_population and breed,
    # so nothing enters the population unconstrained.
    for g in legal:
        _enforce_composition(g)
    return legal

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

def crossover(p1, p2, constraints):
    """Breed two parents slot-by-slot, then repair the species and item clauses.

    Each free slot inherits from a random parent; locked slots take the parent
    that actually holds the mandated species (rebuilding if neither does). The
    naive per-slot mix can duplicate a base species or item, so two repair passes
    follow: re-roll species-clause violators via mutate_species, then re-pick any
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
    # Species clause
    seen = set()
    for i, m in enumerate(child):
        if i in constraints:
            sp = _SPECIES_BY_NAME.get(m["species"])
            if sp:
                seen.add(DB.norm(sp["baseSpecies"]))
    for i, m in enumerate(child):
        if i in constraints:
            continue
        sp = _SPECIES_BY_NAME.get(m["species"])
        if not sp:
            continue
        base = DB.norm(sp["baseSpecies"])
        if base in seen:
            child = mutate_species(child, i, constraints)
            sp2 = _SPECIES_BY_NAME.get(child[i]["species"])
            if sp2:
                seen.add(DB.norm(sp2["baseSpecies"]))
        else:
            seen.add(base)
    # Item clause
    seen_items = set()
    for m in child:
        if m["item"] in seen_items:
            m["item"] = _pick_item_for(m["species"], seen_items)
        seen_items.add(m["item"])
    return child

def enforce_constraints(genome, constraints):
    """Rebuild any locked slot whose species doesn't match. Returns a new genome."""
    if not constraints or not genome:
        return genome
    g = copy.deepcopy(genome)
    used_items = {m["item"] for m in g if m and m.get("item")}
    for slot, want in constraints.items():
        current = g[slot].get("species") if slot < len(g) else None
        if current != want:
            mon = _fresh_mon(want, used_items)
            if mon and slot < len(g):
                g[slot] = mon
                used_items.add(mon["item"])
    return g
