"""
ga_core.py — GA engine for counter-meta VGC team search.

Evolves 6-mon teams against a pool of real top-cut teams, using a poke_env
pilot (heuristic by default) to play out battles for the fitness signal.

Entry points:
  run_ga(...)        single-population generational GA — legacy/debug only.
  run_islands(...)   multi-island GA with ring migration, stagnation restart,
                     and JSON checkpointing — THIS is the production path.

Vocabulary used throughout:
  genome       = list of 6 mon dicts {species, item, ability, nature, evs, moves}
  constraints  = {slot_idx: species_name} — "locked" slots that must hold a
                 given species and are never mutated/crossed away.
  fitness      = win rate of a genome vs a sampled slice of the opponent pool.

Everything here is CPU/async orchestration; the only heavy dependency is
poke_env driving a local Showdown server (see restart_showdown / SHOWDOWN_PORT).
"""
from __future__ import annotations

import asyncio
import copy
import glob
import json
import os
import random
import subprocess
import time
import urllib.request
from functools import lru_cache

from src import battle as B
from src import regmc_db as DB
from src import showdown_validator as SV

FORMAT = "gen9championsvgc2026regmc"  # canonical format registry; battle.py callers pass this in

# Repo root = parent of this file's directory (src/)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p(*parts):
    """Path relative to repo root."""
    return os.path.join(_REPO_ROOT, *parts)


# -----------------------------------------------------------------------------
# Tuning knobs — every value here was hand-tuned against the Reg M-C pool.
# Grouped up top so a reviewer can find and adjust them without spelunking
# through the engine body. Changing one changes GA *behavior*, not correctness.
# -----------------------------------------------------------------------------

# --- Set generation ---
META_ITEM_BIAS = 0.70   # P(draw the item from real tournament usage) vs any legal item.
                        # 0.70 keeps teams meta-plausible while still exploring off-meta tech.
EV_BUDGET = 66          # Total EVs handed out per mutated spread. Deliberately low: these are
EV_STAT_CAP = 32        # search seeds, not tournament sets; 66 in 32-point chunks ≈ 2 invested stats.

# --- Legality gate ---
MAX_REBUILD_TRIES = 20  # Illegal genome: rebuild from scratch up to N times before dropping it.

# --- Battle harness ---
BATTLE_TIMEOUT = 20     # seconds before a battle is abandoned as hung (returns None, not a loss).
MIN_TURNS = 3           # Battles ending < 3 turns are almost always a Showdown desync/forfeit,
                        # not a real game — discard so they don't poison the fitness signal.
# (The retry-uid stride lives in src/battle.py now — RETRY_STRIDE there.)
SEED_POOL = 30          # When seeding a population from real teams, draw from the first N teams.

# --- Champion selection ---
# Reserve a slice of the training pool that the GA never samples for fitness.
# Champion files are saved from the best genome by validation score, not by
# training fitness. Island B (2026-10-13) was 68% on the training pool but
# 58.7% held-out — the training-best overfit. A validation slice catches that.
VAL_POOL_SIZE = 30
VAL_SPLIT_SEED = 42

# --- Early-stop ---
# A genome plays EARLY_STOP_MIN_BATTLES first; if that head score is below
# EARLY_STOP_WIN_RATE we skip the tail. Statistically: at 50 battles the Wilson
# 95% CI is ~±10 pts, so a genome truly at 30%+ has <1% chance of showing <15%.
# The abort catches the bottom third of a generation at negligible false-positive
# risk and saves ~85% of the wall time for those genomes.
EARLY_STOP_MIN_BATTLES = 50     # only meaningful when the pool is larger than this.
EARLY_STOP_WIN_RATE = 0.15      # abort when head score < this.

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
# Species with no meta_items.json entry pick from CANONICAL_ITEMS ∩ legal.
# Species WITH an entry pick only from that entry (usage-weighted).

PROTECT_MOVES = (
    "Protect", "Detect", "Spiky Shield", "King's Shield",
    "Baneful Bunker", "Silk Trap", "Burning Bulwark",
)
# Priority-ordered: the first one in the list that a species learns gets used.

FAKEOUT_MOVES = ("Fake Out", "Follow Me", "Rage Powder")
# Turn-1 disruption / redirection; first learnable wins.


# =============================================================================
# CACHED ROSTER
# =============================================================================
# Loaded once at import and reused for every genome built this run. Filtering to
# species that actually have moves avoids ever building a mon we can't legalize.
_BASE_SPECIES = [s for s in DB.all_species_base() if s["moves"]]
_SPECIES_BY_NAME = {s["name"]: s for s in _BASE_SPECIES}
_ITEMS = list(DB.all_items())
_NATURES = [n["name"] for n in DB.all_natures()]
_REGIONAL_DIR = _p("data", "regional_teams")


_MOVE_PRIORS = None
def move_priors_for(species_name, top_n=8):
    """Top-N moves by tournament usage count for a species, or None.

    Returns a list of (move_name, count) pairs. Caller decides how to
    filter/weight. Lazily loads the file once.
    """
    global _MOVE_PRIORS
    if _MOVE_PRIORS is None:
        path = _p("data", "species_move_priors.json")
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
        path = _p("data", "meta_items.json")
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
        split_path = _p("data", "pool_split.json")
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
        split_path = _p("data", "pool_split.json")
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
    """Swap one of the 4 moves for a random legal one not already known."""
    sp = _SPECIES_BY_NAME.get(mons[slot]["species"])
    if not sp:
        return mons
    alts = [m for m in sp["moves"] if m not in mons[slot]["moves"]]
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


# =============================================================================
# BATTLE
# =============================================================================
# The battle harness itself (player construction, timeout, retry, websocket
# cleanup) lives in src/battle.py, shared with eval. The GA passes this module
# semaphore, FORMAT, and its own knobs (BATTLE_TIMEOUT, MIN_TURNS) into it.
_SEM = None   # module-global concurrency gate; set by run_ga / run_islands.


def _log_score(idx, total, fit, wins, valid_n, mons, tag=""):
    """One-line progress print. `tag` is an optional suffix like 'early-abort'."""
    ts = time.strftime("%H:%M:%S")
    species = ' / '.join(m['species'] for m in mons)
    suffix = f"  {tag}" if tag else ""
    print(f"  [{ts}] {idx+1:>2}/{total}  {fit*100:5.1f}%  ({wins}W/{valid_n}){suffix}  {species}",
          flush=True)


async def evaluate(mons, opponents, idx, total):
    """Fitness = win rate of one genome across all `opponents`, run concurrently.

    Two-phase: play EARLY_STOP_MIN_BATTLES first; if that head score is below
    EARLY_STOP_WIN_RATE, skip the tail and return the partial score. Partial (not
    0.0) so the genome still ranks correctly against other bad genomes — useful
    in early generations when the whole population is weak.

    Invalid genomes score 0.0 immediately. Battles returning None (timeout /
    desync) are dropped from the denominator, not counted as losses.

    Small pools (<= EARLY_STOP_MIN_BATTLES, e.g. smoke tests) skip the split and
    play everything in one batch.
    """
    text = genome_to_text(mons)
    ok, errs = DB.validate_team(text)
    if not ok:
        print(f"  [{idx+1}/{total}] INVALID: {errs[:2]}")
        return 0.0

    def _battle(opp):
        return B.run_battle(text, opp, random.randint(1, 10**9), _SEM, FORMAT,
                            pilot="heuristic", timeout=BATTLE_TIMEOUT,
                            min_turns=MIN_TURNS)

    # Small pools: no early-stop possible, one batch.
    if len(opponents) <= EARLY_STOP_MIN_BATTLES:
        outcomes = await asyncio.gather(*[_battle(o) for o in opponents])
        valid = [o for o in outcomes if o is not None]
        if not valid:
            return 0.0
        fit = sum(valid) / len(valid)
        _log_score(idx, total, fit, sum(valid), len(valid), mons)
        return fit

    # Phase 1 — head batch.
    head, tail = opponents[:EARLY_STOP_MIN_BATTLES], opponents[EARLY_STOP_MIN_BATTLES:]
    head_outs = await asyncio.gather(*[_battle(o) for o in head])
    head_valid = [o for o in head_outs if o is not None]
    if not head_valid:
        return 0.0
    head_fit = sum(head_valid) / len(head_valid)

    # Early-abort: hopeless genome, skip the tail entirely.
    if head_fit < EARLY_STOP_WIN_RATE:
        _log_score(idx, total, head_fit, sum(head_valid), len(head_valid), mons,
                   tag="early-abort")
        return head_fit

    # Phase 2 — tail batch.
    tail_outs = await asyncio.gather(*[_battle(o) for o in tail])
    tail_valid = [o for o in tail_outs if o is not None]

    all_valid = head_valid + tail_valid
    if not all_valid:
        return 0.0
    fit = sum(all_valid) / len(all_valid)
    _log_score(idx, total, fit, sum(all_valid), len(all_valid), mons)
    return fit


# =============================================================================
# SIMPLE GA (single population) — LEGACY / debug only
# =============================================================================
# run_islands (below) is the production path. run_ga is kept for quick local
# debugging of the evolve loop without the island/migration machinery; it has no
# live callers in run/ and is not checkpointed.
async def run_ga(locked, pop_size, generations, battles_per_genome, concurrency,
                 seed_path=None, label="latest"):
    """Single-population generational GA. Legacy/debug — see run_islands for prod."""
    global _SEM
    _SEM = asyncio.Semaphore(concurrency)
    random.seed(42)
    opponents = regional_pool()
    if not opponents:
        print("ERROR: no regional teams loaded")
        return
    print(f"=== GA (locked: {locked or 'none'}) ===")
    print(f"Pop {pop_size}, Gens {generations}, Battles/genome {battles_per_genome}")
    print(f"Opponents: {len(opponents)} regional teams")

    population = []
    if seed_path and os.path.exists(seed_path):
        g = text_to_genome(open(seed_path).read())
        if g:
            population.append(g)
            print(f"Seeded with {os.path.basename(seed_path)}")
    for _ in range(min(3, pop_size - len(population))):
        text = random.choice(opponents[:SEED_POOL])
        g = text_to_genome(text)
        if not g:
            continue
        for slot, want in locked.items():
            sp = _SPECIES_BY_NAME.get(g[slot]["species"]) if g[slot] else None
            if not sp or sp["baseSpecies"] != _SPECIES_BY_NAME[want]["baseSpecies"]:
                mon = _fresh_mon(want, {m["item"] for m in g if m})
                if mon is None:
                    continue
                g[slot] = mon
        population.append(g)
    while len(population) < pop_size:
        g = build_random_genome(locked)
        if g:
            population.append(g)

    population = filter_legal_genomes(population, locked)
    print(f"After legality gate: {len(population)} valid genomes")

    history = []
    all_time_best = {"fit": -1, "genome": None, "gen": None}
    t0 = time.time()
    for gen in range(generations):
        print(f"\n[{time.strftime('%H:%M:%S')}] === GEN {gen+1}/{generations}  "
              f"({(time.time()-t0)/60:.1f} min) ===")
        gen_opps = random.sample(opponents, min(len(opponents), battles_per_genome))
        fits = await asyncio.gather(*[evaluate(g, gen_opps, i, len(population))
                                       for i, g in enumerate(population)])
        ranked = sorted(zip(fits, population), key=lambda x: -x[0])
        print(f"  -> Best: {ranked[0][0]*100:.1f}%  Avg: {sum(fits)/len(fits)*100:.1f}%")
        if ranked[0][0] > all_time_best["fit"]:
            all_time_best = {"fit": ranked[0][0], "genome": ranked[0][1], "gen": gen+1}
            print(f"     NEW ALL-TIME BEST: {ranked[0][0]*100:.1f}% (gen {gen+1})")

        history.append({
            "gen": gen+1, "best": ranked[0][0],
            "avg": sum(fits)/len(fits),
            "species": [m["species"] for m in ranked[0][1]],
        })
        champ = _p("output", "champions", f"ga_{label}.txt")
        os.makedirs(os.path.dirname(champ), exist_ok=True)
        open(champ, "w").write(genome_to_text(all_time_best["genome"]))
        json.dump(history, open(_p("output", "ga_history.json"), "w"), indent=2)

        if gen == generations - 1:
            break
        # Elitism: keep the top fifth (≥2) verbatim, fill the rest by breeding
        # crossovers of the elite pool. run_islands.breed uses a larger top-third
        # — single-pop can afford a tighter elite since there's no migration to
        # reseed diversity.
        n_elites = max(2, pop_size // 5)
        elites = [g for _, g in ranked[:n_elites]]
        new_pop = [copy.deepcopy(g) for g in elites]
        while len(new_pop) < pop_size:
            p1, p2 = random.sample(elites, 2)
            new_pop.append(mutate(crossover(p1, p2, locked), locked))
        population = filter_legal_genomes(new_pop, locked)

    print(f"\n=== DONE ===")
    print(f"All-time best: {all_time_best['fit']*100:.1f}% (gen {all_time_best['gen']})")
    print(genome_to_text(all_time_best["genome"]))


# =============================================================================
# ISLAND MODEL
# =============================================================================
# The production GA: N semi-isolated populations ("islands"), each optionally
# locking a different species, evolving in parallel. Top genomes migrate around a
# ring every few generations; stagnant islands restart their worst half. State is
# JSON-checkpointed every generation so a multi-hour run survives a crash/restart.
CHECKPOINT_DIR = _p("output", "checkpoints", "v6")
CHAMPION_DIR = _p("output", "champions")
SHOWDOWN_DIR = os.path.expanduser("~/pokemon-showdown")
SHOWDOWN_PORT = 8000


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


class Island:
    """One GA sub-population plus its evolve/checkpoint bookkeeping.

    constraints  = {slot: species} locked for this island (may be empty).
    best_ever    = all-time best genome seen here (survives stagnation restarts).
    stagnation   = generations since best_ever improved (drives the restart).
    to_dict/from_dict are the on-disk checkpoint shape (see save_checkpoint).
    """

    def __init__(self, name, constraints=None, seed_paths=None):
        self.name = name
        self.constraints = constraints or {}
        self.population = []
        self.fitness = []
        self.best_ever = {"fit": -1, "genome": None, "gen": None}
        # best_val_ever = best genome by validation-slice score (champion source)
        self.best_val_ever = {"fit": -1, "genome": None, "gen": None}
        self.stagnation = 0
        self.history = []
        self.seed_paths = seed_paths or []

    def init_population(self, size):
        """Fill the population to `size`: seed files first, then random genomes.

        Runs the legality gate once, then tops up again (the gate can drop
        genomes it couldn't legalize). The final list may still be short if the
        roster can't produce `size` legal genomes, which is acceptable.
        """
        self.population = []
        for path in self.seed_paths:
            if os.path.exists(path):
                try:
                    g = text_to_genome(open(path).read())
                    if g:
                        g = enforce_constraints(g, self.constraints)
                        self.population.append(g)
                        print(f"  [{self.name}] seeded with {os.path.basename(path)}")
                except Exception:
                    pass
        while len(self.population) < size:
            g = build_random_genome(self.constraints)
            if g:
                self.population.append(g)
        self.population = filter_legal_genomes(self.population, self.constraints)
        while len(self.population) < size:
            g = build_random_genome(self.constraints)
            if g:
                self.population.append(g)
        self.fitness = [0.0] * len(self.population)

    def to_dict(self):
        """Serialize to the JSON checkpoint shape (constraint keys → str for JSON)."""
        return {
            "name": self.name,
            "constraints": {str(k): v for k, v in self.constraints.items()},
            "population": self.population,
            "fitness": self.fitness,
            "best_ever": self.best_ever,
            "best_val_ever": self.best_val_ever,
            "stagnation": self.stagnation,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, d):
        """Rebuild an Island from a checkpoint dict (constraint keys → int again)."""
        isl = cls(d["name"], {int(k): v for k, v in d.get("constraints", {}).items()})
        isl.population = d["population"]
        isl.fitness = d.get("fitness", [0.0] * len(isl.population))
        isl.best_ever = d["best_ever"]
        isl.best_val_ever = d.get("best_val_ever",
                                   {"fit": -1, "genome": None, "gen": None})
        isl.stagnation = d.get("stagnation", 0)
        isl.history = d.get("history", [])
        return isl


def count_unique_species(island):
    """Count distinct base species across the island — the diversity metric."""
    seen = set()
    for g in island.population:
        if not g:
            continue
        for m in g:
            sp = _SPECIES_BY_NAME.get(m["species"])
            if sp:
                seen.add(DB.norm(sp["baseSpecies"]))
    return len(seen)


def inject_immigrants(island, n):
    """Replace the `n` worst genomes with fresh random ones. Returns count added.

    Diversity rescue: called when an island's unique-species count falls below
    the floor. Targets the lowest-fitness slots so we never evict a contender.
    """
    if not island.fitness:
        return 0
    ranked = sorted(range(len(island.population)), key=lambda i: island.fitness[i])
    added = 0
    for idx in ranked[:n]:
        fresh = build_random_genome(island.constraints)
        if fresh:
            island.population[idx] = fresh
            island.fitness[idx] = 0.0
            added += 1
    return added


def _strip_species(genome, species_set, constraints):
    """Replace any mon whose species is in species_set with a fresh random mon.
    Preserves species + item clauses. Never touches constrained slots.
    """
    if not genome:
        return genome
    stripped = copy.deepcopy(genome)

    # Build the set of base species we must avoid duplicating (excluding
    # the slots we're about to replace).
    def _bases(exclude_slots=()):
        s = set()
        for i, m in enumerate(stripped):
            if i in exclude_slots or m is None:
                continue
            sp = _SPECIES_BY_NAME.get(m.get("species"))
            if sp:
                s.add(DB.norm(sp["baseSpecies"]))
        return s

    for slot, mon in enumerate(stripped):
        if slot in constraints:
            continue
        if mon and mon.get("species") in species_set:
            used_items = {m["item"] for m in stripped
                          if m and m.get("item") and m is not mon}
            used_bases = _bases(exclude_slots=(slot,))
            cands = [s["name"] for s in _BASE_SPECIES
                     if s["name"] not in species_set
                     and DB.norm(s["baseSpecies"]) not in used_bases
                     and len(s["moves"]) >= 4]
            if not cands:
                continue
            new_sp = random.choice(cands)
            fresh = _fresh_mon(new_sp, used_items)
            if fresh:
                stripped[slot] = fresh
    return stripped


def ring_migrate(islands, n=2):
    """Copy each island's top `n` genomes into the next island's worst `n` slots.

    Migration runs around a ring (island i receives from island i-1). Incoming
    genomes are constraint-enforced for the destination, and any species that is
    locked on the SOURCE but not here is stripped — see the inline note below for
    the diversity-collapse bug that motivated it.
    """
    tops = []
    for isl in islands:
        if not isl.fitness:
            tops.append([])
            continue
        ranked = sorted(range(len(isl.population)), key=lambda i: -isl.fitness[i])
        tops.append([copy.deepcopy(isl.population[i]) for i in ranked[:n]])
    for i, isl in enumerate(islands):
        incoming = tops[(i - 1) % len(islands)]
        if not incoming:
            continue
        ranked = sorted(range(len(isl.population)), key=lambda j: isl.fitness[j])
        for j, genome in enumerate(incoming):
            if j >= len(ranked):
                break
            fixed = enforce_constraints(genome, isl.constraints)
            # Strip any species that is a lock on the SOURCE island but
            # not locked here. Without this, Umbreon leaks from island A
            # into B/C and diversity collapses over generations.
            src_constraints = islands[(i - 1) % len(islands)].constraints
            foreign_locks = set(src_constraints.values()) - set(isl.constraints.values())
            if foreign_locks:
                fixed = _strip_species(fixed, foreign_locks, isl.constraints)
            isl.population[ranked[-1 - j]] = fixed
            isl.fitness[ranked[-1 - j]] = 0.0


def restart_showdown():
    """Kill and relaunch the local Showdown server, waiting for it to come back.

    Called periodically mid-run because the Node server leaks memory/sockets over
    thousands of battles. Hard-kills any process on the port, relaunches detached
    with --no-security (local-only, trusted), then polls the HTTP port for up to
    15s. Returns True once it answers, False if it never came up.
    """
    print(f"  [showdown] restarting on :{SHOWDOWN_PORT}...")
    subprocess.run(["pkill", "-9", "-f", f"pokemon-showdown start {SHOWDOWN_PORT}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    subprocess.Popen(
        ["node", "pokemon-showdown", "start", str(SHOWDOWN_PORT), "--no-security"],
        cwd=SHOWDOWN_DIR,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(15):   # poll up to ~15s for the server to accept connections
        try:
            urllib.request.urlopen(f"http://localhost:{SHOWDOWN_PORT}", timeout=2)
            print(f"  [showdown] back up")
            return True
        except Exception:
            time.sleep(1)
    print(f"  [showdown] FAILED")
    return False


def save_checkpoint(generation, islands, run_id="run1"):
    """Write a full-run checkpoint and prune old ones, keeping every 5th gen.

    Retention: the latest checkpoint is always kept; older ones survive only if
    their generation is a multiple of 5. This bounds disk use over a long run
    while still leaving periodic restore points. Returns the path written.
    """
    base = os.path.join(CHECKPOINT_DIR, run_id)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"gen_{generation:04d}.json")
    state = {
        "generation": generation,
        "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
        "islands": [isl.to_dict() for isl in islands],
    }
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    all_ckpts = sorted(f for f in os.listdir(base) if f.startswith("gen_"))
    for f in all_ckpts[:-1]:   # never prune the newest
        try:
            gen = int(f.split("_")[1].split(".")[0])
            if gen % 5 != 0:   # keep multiples of 5 as periodic restore points
                os.remove(os.path.join(base, f))
        except Exception:
            pass
    return path


def load_latest_checkpoint(run_id="run1"):
    """Path of the highest-numbered checkpoint for a run, or None if none exist."""
    base = os.path.join(CHECKPOINT_DIR, run_id)
    if not os.path.isdir(base):
        return None
    files = sorted(f for f in os.listdir(base) if f.startswith("gen_"))
    if not files:
        return None
    return os.path.join(base, files[-1])


def breed(island, immigration_rate=0.20):
    """Produce the next generation of one island: elites + crossovers + immigrants.

    Keeps the top third (≥2) as elites, then fills the rest by either injecting a
    fresh random genome (probability immigration_rate, for ongoing diversity) or
    breeding a mutated crossover of two elites. The new population is legality-
    gated and topped back up to the original size. Fitness resets to zero.
    """
    n = len(island.population)
    if n < 4:
        return
    ranked = sorted(range(n), key=lambda i: -island.fitness[i])
    n_elites = max(2, n // 3)
    elites = [enforce_constraints(copy.deepcopy(island.population[i]), island.constraints)
              for i in ranked[:n_elites]]
    new_pop = list(elites)
    while len(new_pop) < n:
        if random.random() < immigration_rate:
            fresh = build_random_genome(island.constraints)
            if fresh:
                new_pop.append(fresh)
            continue
        p1, p2 = random.sample(elites, 2)
        child = mutate(crossover(p1, p2, island.constraints), island.constraints)
        new_pop.append(child)
    new_pop = filter_legal_genomes(new_pop, island.constraints)
    while len(new_pop) < n:
        fresh = build_random_genome(island.constraints)
        if fresh:
            new_pop.append(fresh)
    island.population = new_pop[:n]
    island.fitness = [0.0] * len(island.population)


async def _eval_on_subset(genome, opponents, verbose=False):
    """One-shot fitness on a specific opponent list. No early-stop, no retry."""
    text = genome_to_text(genome)
    ok, errs = DB.validate_team(text)
    if not ok:
        return 0.0
    tasks = [B.run_battle(text, o, random.randint(1, 10**9), _SEM, FORMAT,
                          pilot="heuristic", timeout=BATTLE_TIMEOUT,
                          min_turns=MIN_TURNS)
             for o in opponents]
    outcomes = await asyncio.gather(*tasks)
    valid = [o for o in outcomes if o is not None]
    if not valid:
        return 0.0
    return sum(valid) / len(valid)


async def run_islands(
    island_specs,
    pop_per_island=10,
    generations=999,
    battles_per_genome=800,
    concurrency=int(os.environ.get("GA_CONCURRENCY", "3")),
    immigration_rate=0.20,
    stagnation_limit=5,
    diversity_floor=15,
    migration_every=5,
    showdown_restart_every=10,
    max_hours=None,
    run_id="run1",
):
    """Production GA driver: evolve N islands with migration, restart, checkpoints.

    Resumes from the latest checkpoint for `run_id` if one exists, else builds
    islands from island_specs. Each generation, per island: evaluate fitness,
    track the all-time best, rescue diversity (inject_immigrants) or escape local
    optima (stagnation restart), then breed. Every `migration_every` gens the ring
    migrates; every `showdown_restart_every` gens the server is bounced. Stops at
    `generations` or when `max_hours` elapses. Writes a champion file per island.
    """
    global _SEM
    _SEM = asyncio.Semaphore(concurrency)

    islands = []
    start_gen = 0
    ckpt = load_latest_checkpoint(run_id)
    if ckpt:
        try:
            state = json.load(open(ckpt))
            islands = [Island.from_dict(d) for d in state["islands"]]
            start_gen = state["generation"]
            print(f"RESUMED from {ckpt} at gen {start_gen}")
        except Exception as e:
            print(f"checkpoint load failed ({e}); fresh start")
            islands = []

    if not islands:
        print("Initializing islands...")
        for spec in island_specs:
            isl = Island(
                spec["name"],
                constraints=spec.get("constraints", {}),
                seed_paths=spec.get("seed_paths", []),
            )
            isl.init_population(pop_per_island)
            islands.append(isl)
            print(f"  [{isl.name}] {len(isl.population)} genomes, "
                  f"constraints={isl.constraints}")

    print(f"=== GA: {len(islands)} islands × {pop_per_island} ===")
    print(f"Gens {start_gen}..{generations}, {battles_per_genome} battles/genome")

    opp_pool = regional_pool()
    train_pool, val_pool = _split_train_val(opp_pool)
    print(f"Fitness pool: {len(train_pool)} teams   "
          f"Validation slice: {len(val_pool)} teams")
    t0 = time.time()
    time_budget_seconds = (max_hours * 3600) if max_hours else None

    for gen in range(start_gen, generations):
        if time_budget_seconds and (time.time() - t0) > time_budget_seconds:
            print(f"\n=== TIME BUDGET REACHED ({max_hours}h) at gen {gen} ===")
            break
        if gen > start_gen and (gen - start_gen) % showdown_restart_every == 0 and gen > 0:
            restart_showdown()

        print(f"\n[{time.strftime('%H:%M:%S')}] === GEN {gen+1}/{generations}  "
              f"({(time.time()-t0)/60:.1f} min) ===")

        for isl in islands:
            gen_opps = random.sample(train_pool, min(battles_per_genome, len(train_pool)))
            fits = await asyncio.gather(*[
                evaluate(g, gen_opps, i, len(isl.population))
                for i, g in enumerate(isl.population)
            ])
            isl.fitness = list(fits)
            best_idx = max(range(len(fits)), key=lambda i: fits[i])
            gen_best = fits[best_idx]

            if gen_best > isl.best_ever["fit"]:
                isl.best_ever = {
                    "fit": gen_best,
                    "genome": copy.deepcopy(isl.population[best_idx]),
                    "gen": gen + 1,
                }
                isl.stagnation = 0
                print(f"  [{isl.name}] NEW ALL-TIME (train): {gen_best*100:.1f}%")
            else:
                isl.stagnation += 1

            # Champion selection: evaluate this generation's training-best on
            # the held-back validation slice. Champions come from
            # best_val_ever, not best_ever — Island B (2026-10-13) showed
            # the training best overfits by ~10 points on held-out.
            val_fit = await _eval_on_subset(isl.population[best_idx], val_pool)
            if val_fit > isl.best_val_ever["fit"]:
                isl.best_val_ever = {
                    "fit": val_fit,
                    "genome": copy.deepcopy(isl.population[best_idx]),
                    "gen": gen + 1,
                }
                print(f"  [{isl.name}] NEW VAL BEST: {val_fit*100:.1f}% "
                      f"(train {gen_best*100:.1f}%)")

            isl.history.append({
                "gen": gen + 1,
                "best": gen_best,
                "avg": sum(fits) / len(fits) if fits else 0,
                "all_time": isl.best_ever["fit"],
                "stag": isl.stagnation,
            })

            uniq = count_unique_species(isl)
            if uniq < diversity_floor:
                added = inject_immigrants(isl, 3)
                print(f"  [{isl.name}] diversity low ({uniq}): injected {added}")

            if isl.stagnation >= stagnation_limit:
                n_restart = len(isl.population) // 2
                ranked = sorted(range(len(isl.fitness)), key=lambda i: isl.fitness[i])
                for j in ranked[:n_restart]:
                    fresh = build_random_genome(isl.constraints)
                    if fresh:
                        isl.population[j] = fresh
                        isl.fitness[j] = 0.0
                print(f"  [{isl.name}] STAGNATION: restarted {n_restart}")
                isl.stagnation = 0

            if gen < generations - 1:
                breed(isl, immigration_rate=immigration_rate)

            print(f"  [{isl.name}] gen {gen+1}: best={gen_best*100:5.1f}%  "
                  f"all-time={isl.best_ever['fit']*100:5.1f}%  stag={isl.stagnation}  "
                  f"uniq={uniq}")

        if (gen + 1) % migration_every == 0 and gen < generations - 1:
            ring_migrate(islands, n=2)
            print(f"  >> migration done at gen {gen+1}")

        ckpt_path = save_checkpoint(gen + 1, islands, run_id)
        print(f"  >> checkpoint: {os.path.basename(ckpt_path)}")

    os.makedirs(CHAMPION_DIR, exist_ok=True)
    print(f"\n=== DONE ===")
    for isl in islands:
        # Champion by validation score, not training score. Fall back to
        # training best if we never got a val evaluation (short runs).
        best = isl.best_val_ever if isl.best_val_ever["genome"] else isl.best_ever
        label = "val" if isl.best_val_ever["genome"] else "train"
        if best["genome"]:
            path = os.path.join(CHAMPION_DIR, f"ga_{run_id}_island_{isl.name}.txt")
            open(path, "w").write(genome_to_text(best["genome"]))
            print(f"  [{isl.name}] champion ({label}): {best['fit']*100:.1f}% "
                  f"(train best {isl.best_ever['fit']*100:.1f}%) -> {path}")
