"""
GA v5 — DB-backed team search.

Data layer: regmc_db.py (authoritative, extracted from Showdown).
Strategy layer: role definitions + move scoring (this file).

Genome = 6 base species names. Sets are built from the DB, legal by construction.
No string-matching heuristics. No hardcoded item/move/ability lists.
"""
import asyncio
import json
import os
import random
import sys
import time
from functools import lru_cache

sys.path.insert(0, os.path.expanduser("~/project"))

from poke_env.player import SimpleHeuristicsPlayer
from poke_env import AccountConfiguration
from real_team_loader import load_real_teams
import regmc_db as DB

# ============================================================
# CONFIG
# ============================================================

FORMAT = "gen9championsvgc2026regmc"
POP_SIZE = 6
GENERATIONS = 5
ELITES = 2
OPPONENTS_PER_TEAM = 105
BATTLES_PER_OPPONENT = 2
CONCURRENCY = 3
TIMEOUT = 20
MIN_VALID_BATTLES = 180
HISTORY = "ga_v5_history.json"
CHECKPOINT = "ga_v5_checkpoint.json"

SEED_TEAM_PATH = os.path.expanduser("~/pokemon-ai/baseline_team.txt")

random.seed(42)

# ============================================================
# LOAD FROM DB
# ============================================================

# Base species only (no formes)
BASE_SPECIES = [s for s in DB.all_species_base() if s["moves"]]
SPECIES_BY_NAME = {s["name"]: s for s in BASE_SPECIES}
ALL_ITEMS = DB.all_items()
OPP_POOL = load_real_teams()

# VGC staples: these are community-consensus "always include if learnable".
# Small, stable, not format data — strategy knowledge.
VGC_STAPLES = {
    "Protect":    1000,
    "Fake Out":    900,
    "Follow Me":   850,
    "Tailwind":    800,
    "Trick Room":  800,
    "Parting Shot": 750,
    "U-turn":      700,
    "Volt Switch": 700,
}

# ============================================================
# ROLE DEFINITIONS
# ============================================================

ROLE_FOR_SLOT = {
    1: "physical_mega",
    2: "intimidate_fakeout",
    3: "special_attacker",
    4: "physical_attacker",
    5: "physical_sweeper",
}

def _stat(sp, key):
    return sp["baseStats"].get(key, 0)

def _is_physical(sp):
    return _stat(sp, "atk") > _stat(sp, "spa") + 15

def _is_special(sp):
    return _stat(sp, "spa") > _stat(sp, "atk") + 15

@lru_cache(maxsize=None)
def _role_pool(role):
    """Return an immutable tuple of species dicts eligible for a role."""
    out = []
    for sp in BASE_SPECIES:
        name = sp["name"]
        if name == "Umbreon":
            continue
        if role == "physical_mega":
            if sp["megaStones"] and _is_physical(sp):
                out.append(name)
        elif role == "intimidate_fakeout":
            if DB.species_has_ability(sp, "Intimidate") and DB.species_can_learn(sp, "Fake Out"):
                out.append(name)
        elif role == "special_attacker":
            if _is_special(sp) and _stat(sp, "spa") >= 100:
                out.append(name)
        elif role == "physical_attacker":
            if _is_physical(sp) and _stat(sp, "atk") >= 100 and DB.species_can_learn(sp, "Fake Out"):
                out.append(name)
        elif role == "physical_sweeper":
            if _is_physical(sp) and _stat(sp, "spe") >= 95 and _stat(sp, "atk") >= 110:
                out.append(name)
    return tuple(out)

def role_candidates(role, exclude_names=None):
    exclude_names = exclude_names or set()
    return [SPECIES_BY_NAME[n] for n in _role_pool(role) if n not in exclude_names]

# ============================================================
# SET GENERATION (all data from DB)
# ============================================================

def _kind_for_role(role):
    if role == "special_attacker":
        return "special"
    if role == "intimidate_fakeout":
        return "support"
    return "physical"

def _score_move(mv, kind):
    """Score a move from DB metadata for a role kind."""
    if mv is None:
        return -1
    name = mv["name"]
    if name in VGC_STAPLES:
        return VGC_STAPLES[name]
    cat = mv["category"]
    bp = mv["basePower"] or 0
    prio = mv["priority"] or 0

    if kind == "special":
        if cat == "Special":
            return 100 + bp + 10 * prio
        if cat == "Status":
            return 40
        return bp * 0.3
    if kind == "physical":
        if cat == "Physical":
            return 100 + bp + 10 * prio
        if cat == "Status":
            return 40
        return bp * 0.3
    # support
    if cat == "Status":
        return 100
    if prio > 0:
        return 80 + bp
    return bp * 0.5

def _pick_moves(sp, kind, n=4):
    """Pick top-scored n moves for a species, from DB learnset."""
    scored = []
    seen = set()
    for mname in sp["moves"]:
        key = DB.norm(mname)
        if key in seen:
            continue
        seen.add(key)
        mv = DB.get_move(mname)
        scored.append((_score_move(mv, kind), mname))
    scored.sort(reverse=True)
    top = [name for _, name in scored[:n]]
    # Light stochasticity: sometimes swap slot 3/4 for a lower-ranked move
    if len(scored) > n and random.random() < 0.3:
        pool = [name for _, name in scored[n:n + 8]]
        if pool:
            top[-1] = random.choice(pool)
    return top

def _evs_for_kind(kind):
    if kind == "special":
        return {"hp": 2, "spa": 32, "spe": 32}
    if kind == "support":
        return {"hp": 32, "def": 20, "spd": 14}
    return {"hp": 2, "atk": 32, "spe": 32}

def _nature_for_kind(kind):
    if kind == "special":
        return random.choice(["Modest", "Timid"])
    if kind == "support":
        return random.choice(["Bold", "Calm", "Impish", "Careful"])
    return random.choice(["Adamant", "Jolly"])

def _item_usable_by(item, species_name):
    users = item.get("itemUser")
    if not users:
        return True
    target = DB.norm(species_name)
    return any(DB.norm(u) == target for u in users)

def _pick_item(sp, used_items):
    """Pick an item for a species, respecting itemUser restrictions + item clause."""
    # Prefer mega stone if species has one and it's unused
    for stone in sp["megaStones"]:
        if stone not in used_items:
            return stone
    # Otherwise random unused legal item that this species can hold
    pool = [
        it["name"] for it in ALL_ITEMS
        if it["name"] not in used_items and _item_usable_by(it, sp["name"])
    ]
    if not pool:
        return "Leftovers"
    return random.choice(pool)

def build_set(sp, kind, used_items):
    """Build a legal set for a species. Returns dict."""
    abilities = sp["abilities"]
    item = _pick_item(sp, used_items)
    used_items.add(item)
    return {
        "item": item,
        "ability": random.choice(abilities),
        "nature": _nature_for_kind(kind),
        "evs": _evs_for_kind(kind),
        "moves": _pick_moves(sp, kind, 4),
    }

def build_team(species_names):
    """Given 6 species names, build legal sets for all of them."""
    used_items = set()
    sets = {}
    # Slot 0: always Umbreon, support-flavored
    sp0 = SPECIES_BY_NAME[species_names[0]]
    sets[species_names[0]] = build_set(sp0, "support", used_items)
    # Slots 1-5: role-driven
    for slot in range(1, 6):
        name = species_names[slot]
        sp = SPECIES_BY_NAME[name]
        role = ROLE_FOR_SLOT[slot]
        kind = _kind_for_role(role)
        sets[name] = build_set(sp, kind, used_items)
    return (list(species_names), sets)

# ============================================================
# POPULATION INIT
# ============================================================

def load_seed_team():
    """Load baseline team from file, return (species_names, sets)."""
    text = open(SEED_TEAM_PATH).read()
    mons = DB.parse_team(text)
    species_names = [m["species"] for m in mons]
    sets = {}
    for m in mons:
        sets[m["species"]] = {
            "item": m["item"],
            "ability": m["ability"],
            "nature": m["nature"],
            "evs": m["evs"],
            "moves": m["moves"],
        }
    return (species_names, sets)

def random_team_species():
    """Generate 6 base species with role constraints and species clause."""
    species = ["Umbreon"]
    seen_bases = {"umbreon"}
    for slot in range(1, 6):
        role = ROLE_FOR_SLOT[slot]
        cands = role_candidates(role, exclude_names=set(species))
        cands = [c for c in cands if DB.norm(c["baseSpecies"]) not in seen_bases]
        if not cands:
            cands = [s for s in BASE_SPECIES
                     if s["name"] not in species and DB.norm(s["baseSpecies"]) not in seen_bases]
        pick = random.choice(cands)
        species.append(pick["name"])
        seen_bases.add(DB.norm(pick["baseSpecies"]))
    return species

def random_team():
    return build_team(random_team_species())

# ============================================================
# MUTATION
# ============================================================

def mutate_species(species, rate=0.3):
    if random.random() > rate:
        return species
    slot = random.randint(1, 5)
    role = ROLE_FOR_SLOT[slot]
    cands = role_candidates(role, exclude_names=set(species))
    if not cands:
        return species
    pick = random.choice(cands)["name"]
    species = list(species)
    species[slot] = pick
    return species

# ============================================================
# TEAM -> TEXT
# ============================================================

def team_to_str(species_list, sets):
    lines = []
    for sp_name in species_list:
        st = sets[sp_name]
        ev_str = " / ".join(f"{v} {k.upper()}" for k, v in st["evs"].items() if v > 0)
        lines.append(f"{sp_name} @ {st['item']}")
        lines.append(f"Ability: {st['ability']}")
        lines.append("Level: 50")
        lines.append(f"{st['nature']} Nature")
        lines.append(f"EVs: {ev_str}" if ev_str else "EVs: 0 HP")
        for m in st["moves"]:
            lines.append(f"- {m}")
        lines.append("")
    return "\n".join(lines)

# ============================================================
# BATTLE
# ============================================================

SEM = None

async def run_battle(team_str, opp_str, uid):
    async with SEM:
        bot = opp = None
        try:
            bot = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=team_str,
                max_concurrent_battles=1,
                account_configuration=AccountConfiguration.generate(f"B{uid}", rand=True))
            opp = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=opp_str,
                max_concurrent_battles=1,
                account_configuration=AccountConfiguration.generate(f"O{uid}", rand=True))
            await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout=TIMEOUT)
            if bot.n_finished_battles == 0:
                return None
            try:
                last = list(bot.battles.values())[-1]
                turns = getattr(last, "turn", 0)
            except Exception:
                turns = 0
            if turns < 3:
                return None
            return 1 if bot.n_won_battles > 0 else 0
        except Exception:
            return None
        finally:
            for p in (bot, opp):
                try:
                    if p:
                        await p.ps_client.stop_listening()
                except Exception:
                    pass

# ============================================================
# EVAL + MAIN LOOP
# ============================================================

async def eval_team(species_list, idx, total, shared_opps=None):
    genome = build_team(species_list)
    team_str = team_to_str(*genome)

    ok, errs = DB.validate_team(team_str)
    if not ok:
        print(f"  WARN: genome {idx+1} illegal: {errs[:2]}")

    opps = shared_opps or random.sample(OPP_POOL, min(OPPONENTS_PER_TEAM, len(OPP_POOL)))
    tasks = [run_battle(team_str, o, random.randint(1, 10**9))
             for o in opps for _ in range(BATTLES_PER_OPPONENT)]
    outcomes = await asyncio.gather(*tasks)
    valid = [o for o in outcomes if o is not None]
    if len(valid) < MIN_VALID_BATTLES:
        fit, wins, games = 0.0, 0, len(valid)
    else:
        wins, games = sum(valid), len(valid)
        fit = wins / games
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}]  [{idx+1:>2}/{total}] {fit*100:5.1f}%  ({wins:>2}W/{games}  forfeits={len(outcomes)-len(valid)})  {' / '.join(species_list)}")
    return fit, wins, games, genome

async def main():
    global SEM
    SEM = asyncio.Semaphore(CONCURRENCY)
    print("=== GA v5 (DB-backed) ===")
    print(f"Base species: {len(BASE_SPECIES)}, items: {len(ALL_ITEMS)}, real teams: {len(OPP_POOL)}")
    print(f"Pop {POP_SIZE}, Gens {GENERATIONS}, "
          f"Opps {OPPONENTS_PER_TEAM}x{BATTLES_PER_OPPONENT}={OPPONENTS_PER_TEAM*BATTLES_PER_OPPONENT}/genome")

    start_gen = 0
    if os.path.exists(CHECKPOINT):
        cp = json.load(open(CHECKPOINT))
        population = cp["population"]   # list of (species_list, sets) tuples
        start_gen = cp["generation"]
        history = cp.get("history", [])
        print(f"RESUMING from generation {start_gen}")
    else:
        # Seed with baseline + random
        population = [load_seed_team()]
        for _ in range(POP_SIZE - 1):
            if random.random() < 0.3:
                population.append(load_seed_team())
            else:
                population.append(random_team())
        history = []

    t0 = time.time()
    for g in range(start_gen, GENERATIONS):
        print(f"\n[{time.strftime('%H:%M:%S')}] === GEN {g+1}/{GENERATIONS}  ({(time.time()-t0)/60:.1f} min) ===")
        gen_opps = random.sample(OPP_POOL, min(OPPONENTS_PER_TEAM, len(OPP_POOL)))
        results = await asyncio.gather(
            *[eval_team(x[0], i, len(population), shared_opps=gen_opps)
              for i, x in enumerate(population)]
        )
        results.sort(key=lambda r: r[0], reverse=True)
        print(f"[{time.strftime('%H:%M:%S')}]  -> Best: {results[0][0]*100:.1f}%")

        history.append({
            "gen": g+1, "best_fitness": results[0][0],
            "rankings": [{
                "fitness": r[0], "wins": r[1], "games": r[2],
                "species": r[3][0], "sets": r[3][1],
            } for r in results],
        })
        json.dump(history, open(HISTORY, "w"), indent=2, default=str)
        # Save population as plain species lists (rebuildable)
        json.dump({
            "generation": g+1,
            "population": [(list(r[3][0]), r[3][1]) for r in results],
            "history": history,
        }, open(CHECKPOINT, "w"), default=str)

        if g == GENERATIONS - 1:
            break

        # Breed
        elites_species = [list(r[3][0]) for r in results[:ELITES]]
        new_pop_species = list(elites_species)
        while len(new_pop_species) < POP_SIZE:
            if random.random() < 0.15:
                new_pop_species.append(random_team_species())
                continue
            p1, p2 = random.sample(elites_species, 2)
            child = ["Umbreon"]
            seen = {"umbreon"}
            for i in range(1, 6):
                pick = random.choice([p1[i], p2[i]])
                sp = SPECIES_BY_NAME.get(pick)
                if sp and DB.norm(sp["baseSpecies"]) in seen:
                    role = ROLE_FOR_SLOT[i]
                    alts = [c["name"] for c in role_candidates(role, exclude_names=seen)]
                    pick = random.choice(alts) if alts else pick
                child.append(pick)
                sp = SPECIES_BY_NAME.get(pick)
                if sp:
                    seen.add(DB.norm(sp["baseSpecies"]))
            child = mutate_species(child, rate=0.35)
            new_pop_species.append(child)

        # Rebuild full genomes from species lists
        population = [build_team(sp) for sp in new_pop_species]

    # Save champion
    all_best = max(history, key=lambda g: g["best_fitness"])
    best = all_best["rankings"][0]
    print(f"\n=== GA v5 COMPLETE ===")
    print(f"Best (Gen {all_best['gen']}): {best['fitness']*100:.1f}%")
    print(f"Species: {' / '.join(best['species'])}")
    os.makedirs("champions", exist_ok=True)
    fname = f"champions/ga_v5_winner_{int(time.time())}.txt"
    open(fname, "w").write(team_to_str(best["species"], best["sets"]))
    print(f"Champion: {fname}")

if __name__ == "__main__":
    asyncio.run(main())
