"""
GA core engine for counter-meta team search.

Genome = 6 mons, each {species, item, ability, nature, evs, moves}.
Constraints = {slot_idx: species_name} — locked slots don't mutate.
"""
import asyncio, copy, glob, json, os, random, sys, time
sys.path.insert(0, os.path.expanduser("~/project/src"))
from poke_env.player import SimpleHeuristicsPlayer
from poke_env import AccountConfiguration
import regmc_db as DB
import showdown_validator as SV

FORMAT = "gen9championsvgc2026regmc"

# ============= CACHED ROSTER =============
_BASE_SPECIES = [s for s in DB.all_species_base() if s["moves"]]
_SPECIES_BY_NAME = {s["name"]: s for s in _BASE_SPECIES}
_ITEMS = list(DB.all_items())
_NATURES = [n["name"] for n in DB.all_natures()]
_REGIONAL_DIR = os.path.expanduser("~/project/data/regional_teams")

_META_ITEMS = None
def meta_items_for(species_name):
    """Return list of (item_name, weight) for a species, or None if unknown."""
    global _META_ITEMS
    if _META_ITEMS is None:
        path = os.path.expanduser("~/project/data/meta_items.json")
        _META_ITEMS = json.load(open(path)) if os.path.exists(path) else {}
    entries = _META_ITEMS.get(species_name, [])
    return [(e["item"], e["count"]) for e in entries] if entries else None


_REGIONAL = None
def regional_pool():
    """Training pool (300 teams)."""
    global _REGIONAL
    if _REGIONAL is None:
        split_path = os.path.expanduser("~/project/data/pool_split.json")
        if os.path.exists(split_path):
            split = json.load(open(split_path))
            files = split.get("train", [])
        else:
            files = sorted(glob.glob(os.path.join(_REGIONAL_DIR, "*.txt")))
        _REGIONAL = [open(f).read().strip() for f in files if open(f).read().strip()]
    return _REGIONAL


_HELDOUT = None
def heldout_pool():
    """Held-out pool (100 teams). Used for final eval only."""
    global _HELDOUT
    if _HELDOUT is None:
        split_path = os.path.expanduser("~/project/data/pool_split.json")
        if os.path.exists(split_path):
            split = json.load(open(split_path))
            files = split.get("holdout", [])
            _HELDOUT = [open(f).read().strip() for f in files if open(f).read().strip()]
        else:
            _HELDOUT = regional_pool()  # fallback
    return _HELDOUT


_META_ITEMS = None
def meta_items_for(species_name):
    """List of (item_name, weight) for a species, from real tournament data."""
    global _META_ITEMS
    if _META_ITEMS is None:
        path = os.path.expanduser("~/project/data/meta_items.json")
        _META_ITEMS = json.load(open(path)) if os.path.exists(path) else {}
    entries = _META_ITEMS.get(species_name, [])
    return [(e["item"], e["count"]) for e in entries] if entries else None


# ============= SET GENERATION =============
def _legal_items_for(species_name):
    sp = _SPECIES_BY_NAME.get(species_name)
    if not sp:
        return ["Leftovers"]
    stones = set(sp["megaStones"])
    out = []
    for it in _ITEMS:
        name = it["name"]
        if name in stones:
            out.append(name); continue
        if it.get("megaStone"):
            continue  # wrong species's stone
        users = it.get("itemUser")
        if users:
            target = DB.norm(species_name)
            if not any(DB.norm(u) == target for u in users):
                continue
        out.append(name)
    return out or ["Leftovers"]


def _random_mon(species_name):
    sp = _SPECIES_BY_NAME.get(species_name)
    if not sp or len(sp["moves"]) < 4:
        return None
    moves = random.sample(sp["moves"], 4)
    cats = [DB.get_move(m)["category"] for m in moves if DB.get_move(m)]
    n_p, n_s = cats.count("Physical"), cats.count("Special")
    if n_p > n_s:
        evs, nature = {"hp": 2, "atk": 32, "spe": 32}, "Jolly"
    elif n_s > n_p:
        evs, nature = {"hp": 2, "spa": 32, "spe": 32}, "Modest"
    else:
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
    """Pick an item with a bias toward what the meta actually uses."""
    sp = _SPECIES_BY_NAME.get(species_name)
    if not sp:
        return "Leftovers"
    # Mega stones always take priority if species can mega
    for stone in sp["megaStones"]:
        if stone not in used_items:
            return stone
    # Meta prior: 70% chance to pull from empirical item distribution
    meta = meta_items_for(species_name)
    if meta and random.random() < 0.70:
        legal_set = set(_legal_items_for(species_name)) - used_items
        candidates = [(i, w) for i, w in meta if i in legal_set]
        if candidates:
            items, weights = zip(*candidates)
            return random.choices(items, weights=weights, k=1)[0]
    # Fallback: uniform random from legal pool
    legal = [i for i in _legal_items_for(species_name) if i not in used_items]
    return random.choice(legal) if legal else "Leftovers"


def build_random_genome(constraints):
    mons = [None] * 6
    used_bases, used_items = set(), set()
    # Locked slots first
    for slot, sp_name in constraints.items():
        if sp_name not in _SPECIES_BY_NAME:
            raise ValueError(f"unknown species for lock: {sp_name}")
        mon = _random_mon(sp_name)
        if mon is None:
            raise ValueError(f"cannot build locked slot {slot}: {sp_name}")
        mon["item"] = _pick_item_for(sp_name, used_items)
        mons[slot] = mon
        used_items.add(mon["item"])
        used_bases.add(DB.norm(_SPECIES_BY_NAME[sp_name]["baseSpecies"]))
    # Free slots
    pool = [s["name"] for s in _BASE_SPECIES]
    for slot in range(6):
        if mons[slot] is not None:
            continue
        random.shuffle(pool)
        for cand in pool:
            sp = _SPECIES_BY_NAME[cand]
            if DB.norm(sp["baseSpecies"]) in used_bases:
                continue
            mon = _random_mon(cand)
            if mon is None:
                continue
            mon["item"] = _pick_item_for(cand, used_items)
            mons[slot] = mon
            used_items.add(mon["item"])
            used_bases.add(DB.norm(sp["baseSpecies"]))
            break
    if any(m is None for m in mons):
        return None
    return mons


# ============= SERIALIZE =============
def genome_to_text(mons):
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
    mons = DB.parse_team(text)
    if len(mons) != 6:
        return None
    return [{
        "species": m["species"], "item": m["item"], "ability": m["ability"],
        "nature": m["nature"], "evs": m["evs"], "moves": m["moves"],
    } for m in mons]


# ============= SHOWDOWN LEGALITY GATE =============
def filter_legal_genomes(genomes, constraints):
    """Take a list of genomes; return only those Showdown accepts. Rebuild invalid ones."""
    texts = [genome_to_text(g) for g in genomes]
    verdicts = SV.check_teams(texts)
    out = []
    for g, (ok, msg) in zip(genomes, verdicts):
        if ok:
            out.append(g)
            continue
        # Try to rebuild; up to 20 attempts
        for _ in range(20):
            fresh = build_random_genome(constraints)
            if fresh is None:
                continue
            ok2, _ = SV.check_teams([genome_to_text(fresh)])[0]
            if ok2:
                out.append(fresh)
                break
    return out


# ============= MUTATION =============
def _used_bases(mons, exclude_slot=None):
    s = set()
    for i, m in enumerate(mons):
        if i == exclude_slot or m is None:
            continue
        sp = _SPECIES_BY_NAME.get(m["species"])
        if sp:
            s.add(DB.norm(sp["baseSpecies"]))
    return s


def _used_items(mons, exclude_slot=None):
    return {m["item"] for i, m in enumerate(mons) if i != exclude_slot and m}


def mutate_species(mons, slot, constraints):
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
    sp = _SPECIES_BY_NAME.get(mons[slot]["species"])
    if not sp:
        return mons
    used = _used_items(mons, exclude_slot=slot)
    cands = [i for i in _legal_items_for(mons[slot]["species"]) if i not in used]
    if cands:
        mons[slot]["item"] = random.choice(cands)
    return mons


def mutate_ability(mons, slot):
    sp = _SPECIES_BY_NAME.get(mons[slot]["species"])
    if not sp or len(sp["abilities"]) < 2:
        return mons
    alts = [a for a in sp["abilities"] if a != mons[slot]["ability"]]
    if alts:
        mons[slot]["ability"] = random.choice(alts)
    return mons


def mutate_nature(mons, slot):
    alts = [n for n in _NATURES if n != mons[slot]["nature"]]
    mons[slot]["nature"] = random.choice(alts)
    return mons


def mutate_evs(mons, slot):
    stats = ["hp", "atk", "def", "spa", "spd", "spe"]
    budget, evs = 66, {s: 0 for s in stats}
    while budget > 0:
        s = random.choice(stats)
        if evs[s] < 32:
            add = min(budget, 32 - evs[s])
            evs[s] += add; budget -= add
    mons[slot]["evs"] = {s: v for s, v in evs.items() if v > 0}
    return mons


def mutate_move(mons, slot):
    sp = _SPECIES_BY_NAME.get(mons[slot]["species"])
    if not sp:
        return mons
    alts = [m for m in sp["moves"] if m not in mons[slot]["moves"]]
    if alts:
        mons[slot]["moves"][random.randint(0, 3)] = random.choice(alts)
    return mons


def mutate(mons, constraints, n=None):
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
    child = []
    for i in range(6):
        if i in constraints:
            want = constraints[i]
            # Force the constrained species, even if parent was wrong
            if p1[i] and p1[i].get("species") == want:
                child.append(copy.deepcopy(p1[i]))
            elif p2[i] and p2[i].get("species") == want:
                child.append(copy.deepcopy(p2[i]))
            else:
                # Neither parent has the locked species — rebuild it
                mon = _random_mon(want)
                if mon is None:
                    raise ValueError(f"cannot build locked slot {i}: {want}")
                child.append(mon)
        else:
            child.append(copy.deepcopy(random.choice([p1[i], p2[i]])))
    # Fix species clause
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
    # Fix item clause
    seen_items = set()
    for m in child:
        if m["item"] in seen_items:
            m["item"] = _pick_item_for(m["species"], seen_items)
        seen_items.add(m["item"])
    return child


# ============= BATTLE =============
_SEM = None

async def _run_battle(team_str, opp_str, uid):
    async with _SEM:
        bot = opp = None
        try:
            bot = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=team_str, max_concurrent_battles=1,
                account_configuration=AccountConfiguration.generate(f"B{uid}", rand=True))
            opp = SimpleHeuristicsPlayer(
                battle_format=FORMAT, team=opp_str, max_concurrent_battles=1,
                account_configuration=AccountConfiguration.generate(f"O{uid}", rand=True))
            await asyncio.wait_for(bot.battle_against(opp, n_battles=1), timeout=20)
            if bot.n_finished_battles == 0:
                return None
            try:
                turns = getattr(list(bot.battles.values())[-1], "turn", 0)
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
                    if p: await p.ps_client.stop_listening()
                except Exception: pass


async def evaluate(mons, opponents, idx, total):
    text = genome_to_text(mons)
    ok, errs = DB.validate_team(text)
    if not ok:
        print(f"  [{idx+1}/{total}] INVALID: {errs[:2]}")
        return 0.0
    tasks = [_run_battle(text, o, random.randint(1, 10**9)) for o in opponents]
    outcomes = await asyncio.gather(*tasks)
    valid = [o for o in outcomes if o is not None]
    if not valid:
        return 0.0
    wins = sum(valid)
    fit = wins / len(valid)
    ts = time.strftime("%H:%M:%S")
    species = ' / '.join(m['species'] for m in mons)
    print(f"  [{ts}] {idx+1:>2}/{total}  {fit*100:5.1f}%  ({wins}W/{len(valid)})  {species}", flush=True)
    return fit


async def run_ga(locked, pop_size, generations, battles_per_genome, concurrency, seed_path=None, label="latest"):
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
        text = random.choice(opponents[:30])
        g = text_to_genome(text)
        if not g:
            continue
        # Enforce lock: if a locked slot's species doesn't match, rebuild it
        for slot, want in locked.items():
            sp = _SPECIES_BY_NAME.get(g[slot]["species"]) if g[slot] else None
            if not sp or sp["baseSpecies"] != _SPECIES_BY_NAME[want]["baseSpecies"]:
                mon = _random_mon(want)
                if mon is None:
                    continue
                mon["item"] = _pick_item_for(want, {m["item"] for m in g if m})
                g[slot] = mon
        population.append(g)
    while len(population) < pop_size:
        g = build_random_genome(locked)
        if g:
            population.append(g)

    # Gate initial population through Showdown
    population = filter_legal_genomes(population, locked)
    print(f"After legality gate: {len(population)} valid genomes")

    history = []
    all_time_best = {"fit": -1, "genome": None, "gen": None}
    t0 = time.time()
    ranked = []
    for gen in range(generations):
        print(f"\n[{time.strftime('%H:%M:%S')}] === GEN {gen+1}/{generations}  ({(time.time()-t0)/60:.1f} min) ===")
        gen_opps = random.sample(opponents, min(len(opponents), battles_per_genome))
        fits = await asyncio.gather(*[evaluate(g, gen_opps, i, len(population))
                                       for i, g in enumerate(population)])
        ranked = sorted(zip(fits, population), key=lambda x: -x[0])
        print(f"  -> Best: {ranked[0][0]*100:.1f}%  Avg: {sum(fits)/len(fits)*100:.1f}%")
        if ranked[0][0] > all_time_best["fit"]:
            all_time_best = {"fit": ranked[0][0], "genome": ranked[0][1], "gen": gen+1}
            print(f"     NEW ALL-TIME BEST: {ranked[0][0]*100:.1f}% (gen {gen+1})")
        if ranked[0][0] > all_time_best["fit"]:
            all_time_best = {"fit": ranked[0][0], "genome": ranked[0][1], "gen": gen+1}
            print(f"     NEW ALL-TIME BEST: {ranked[0][0]*100:.1f}% (gen {gen+1})")

        history.append({
            "gen": gen+1, "best": ranked[0][0],
            "avg": sum(fits)/len(fits),
            "species": [m["species"] for m in ranked[0][1]],
        })
        champ = os.path.expanduser(f"~/project/output/champions/ga_{label}.txt")
        os.makedirs(os.path.dirname(champ), exist_ok=True)
        # Save the all-time best, not this generation's best
        open(champ, "w").write(genome_to_text(all_time_best["genome"]))
        json.dump(history, open(os.path.expanduser("~/project/output/ga_history.json"), "w"), indent=2)

        if gen == generations - 1:
            break
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
