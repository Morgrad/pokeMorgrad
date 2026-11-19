"""
Full pre-flight audit before launching the counter-meta GA.
Checks every layer of the data + generation pipeline.

Exits 1 if any hard check fails (illegal items/stones/natures, invalid regional or
baseline team, fuzz / mutation / crossover failures, broken lock). Species with fewer
than 4 moves are reported as a warning only (Ditto legitimately has just Transform).

One function per numbered report section (check_*); each prints its section and returns
its hard failures. main() runs them in order: the random draws (seed 0, then 42 for the
mutation test, 1 for the crossover test) and so the whole report are deterministic.
"""
import random
import sys

from src import regmc_db as DB
from src.ga.genome import (
    _BASE_SPECIES,
    _ITEMS,
    _NATURES,
    _legal_items_for,
    build_random_genome,
    genome_to_text,
)
from src.ga.operators import crossover, mutate
from src.ga.pools import regional_pool
from src.paths import data_path

LOCKED = {0: "Umbreon"}          # the lock used by the fuzz / mutation / crossover tests


def _section(title, first=False):
    if not first:
        print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def check_db():
    """1. DB INTEGRITY: counts only, never fails."""
    _section("1. DB INTEGRITY", first=True)
    db = DB.load_db()
    print(f"  format: {db['meta']['formatName']}")
    print(f"  mod:    {db['meta']['mod']}")
    print(f"  built:  {db['meta']['built']}")
    print(f"  species (all/base): {len(db['species'])}/{len(_BASE_SPECIES)}")
    print(f"  items:    {len(db['items'])}")
    print(f"  moves:    {len(db['moves'])}")
    print(f"  abilities:{len(db['abilities'])}")
    print(f"  natures:  {len(db['natures'])}")
    return []


def check_names():
    """2. NAME SANITY: species issues are warnings; items without name/id and empty natures fail."""
    _section("2. NAME SANITY")
    problems = []
    # Every species must have: name, baseSpecies, abilities (non-empty), moves (>=4)
    bad_species = []
    for s in _BASE_SPECIES:
        if not s.get("name"):
            bad_species.append((s.get("name"), "no name"))
        elif not s.get("baseSpecies"):
            bad_species.append((s["name"], "no baseSpecies"))
        elif not s.get("abilities"):
            bad_species.append((s["name"], "no abilities"))
        elif len(s.get("moves", [])) < 4:
            bad_species.append((s["name"], f"only {len(s['moves'])} moves"))
    print(f"  Species with issues (warning only): {len(bad_species)}")
    for n, why in bad_species[:10]:
        print(f"    {n}: {why}")

    # Every item must have: name, id
    bad_items = []
    for it in _ITEMS:
        if not it.get("name") or not it.get("id"):
            bad_items.append(it.get("name", "?"))
    print(f"  Items with issues: {len(bad_items)}")
    if bad_items:
        problems.append(f"{len(bad_items)} items without name/id")

    # Every nature must have: name, plus, minus (some neutral natures have both as "")
    bad_natures = [n for n in _NATURES if not n]
    print(f"  Bad natures: {len(bad_natures)}")
    if bad_natures:
        problems.append(f"{len(bad_natures)} bad natures")
    print(f"  Total natures: {len(_NATURES)}")
    print(f"  Sample: {_NATURES[:8]}")
    return problems


def check_mega_stones():
    """3. MEGA STONE INTEGRITY: every stone is a legal item; _legal_items_for returns only legal items."""
    _section("3. MEGA STONE INTEGRITY")
    problems = []
    mega_species = [s for s in _BASE_SPECIES if s["megaStones"]]
    print(f"  Base species with mega stones: {len(mega_species)}")
    bad_stones = []
    for s in mega_species:
        for stone in s["megaStones"]:
            if not DB.is_legal_item(stone):
                bad_stones.append((s["name"], stone))
    print(f"  Species with illegal stone ref: {len(bad_stones)}")
    for n, st in bad_stones[:5]:
        print(f"    {n}: {st}")
    if bad_stones:
        problems.append(f"{len(bad_stones)} illegal mega stone refs")

    print()
    print("  Sampling _legal_items_for:")
    for sp_name in ["Umbreon", "Salamence", "Garchomp", "Incineroar", "Rillaboom"]:
        items = _legal_items_for(sp_name)
        illegal = [i for i in items if not DB.is_legal_item(i)]
        print(f"    {sp_name}: {len(items)} items, {len(illegal)} illegal")
        if illegal:
            print(f"      ILLEGAL: {illegal[:3]}")
            problems.append(f"_legal_items_for({sp_name}) returned illegal items")
    return problems


def check_regional_teams():
    """4. REGIONAL TEAMS: every training-pool team passes the local DB validator."""
    _section("4. REGIONAL TEAMS")
    regional = regional_pool()
    print(f"  Loaded: {len(regional)} teams")
    bad_regional = 0
    for i, text in enumerate(regional):
        ok, errs = DB.validate_team(text)
        if not ok:
            bad_regional += 1
            if bad_regional <= 3:
                print(f"    INVALID #{i}: {errs[:2]}")
    print(f"  Invalid regional teams: {bad_regional}")
    return [f"{bad_regional} invalid regional teams"] if bad_regional else []


def _fuzz(constraints, check_lock):
    """Build 500 random genomes; return [(index, error)] for None builds, invalid teams, broken locks."""
    fails = []
    for i in range(500):
        g = build_random_genome(constraints)
        if g is None:
            fails.append((i, "build returned None"))
            continue
        text = genome_to_text(g)
        ok, errs = DB.validate_team(text)
        if not ok:
            fails.append((i, errs[:2]))
        # Lock check
        if check_lock and g[0]["species"] != "Umbreon":
            fails.append((i, f"lock violated: {g[0]['species']}"))
    print(f"  Failures: {len(fails)}/500")
    for idx, err in fails[:5]:
        print(f"    #{idx}: {err}")
    return fails


def check_locked_fuzz():
    """5. 500 random Umbreon-locked genomes are valid and keep the lock."""
    _section("5. FUZZ TEST — 500 random Umbreon-locked genomes")
    fails = _fuzz(LOCKED, check_lock=True)
    return [f"locked fuzz: {len(fails)} failures"] if fails else []


def check_free_fuzz():
    """6. 500 random unconstrained genomes are valid."""
    _section("6. FUZZ TEST — 500 random free genomes")
    fails = _fuzz({}, check_lock=False)
    return [f"free fuzz: {len(fails)} failures"] if fails else []


def check_mutation():
    """7. 2000 chained mutations (seed 42) keep the lock and stay valid."""
    _section("7. MUTATION STRESS TEST — 2000 mutations on locked genome")
    problems = []
    random.seed(42)
    g = build_random_genome(LOCKED)
    ok, errs = DB.validate_team(genome_to_text(g))
    if not ok:
        print(f"  Seed genome invalid: {errs[:2]}")
        problems.append("mutation stress: seed genome invalid")
        return problems
    for i in range(2000):
        g = mutate(g, LOCKED)
        if g[0]["species"] != "Umbreon":
            print(f"  LOCK BROKEN at mutation {i}: {g[0]['species']}")
            problems.append("mutation stress: lock broken")
            return problems
        if i % 500 == 0:
            ok, errs = DB.validate_team(genome_to_text(g))
            if not ok:
                print(f"  Invalid after {i} mutations: {errs[:2]}")
                problems.append("mutation stress: invalid genome")
                return problems
    print("  After 2000 mutations: lock held, checking final validity...")
    ok, errs = DB.validate_team(genome_to_text(g))
    print(f"  Final: {'VALID' if ok else 'INVALID: ' + str(errs[:2])}")
    if not ok:
        problems.append("mutation stress: final genome invalid")
    return problems


def check_crossover():
    """8. 500 crossovers of locked parents (seed 1) are valid and keep the lock."""
    _section("8. CROSSOVER STRESS TEST — 500 crossovers")
    random.seed(1)
    fails = []
    for i in range(500):
        p1 = build_random_genome(LOCKED)
        p2 = build_random_genome(LOCKED)
        if not p1 or not p2:
            continue
        child = crossover(p1, p2, LOCKED)
        ok, errs = DB.validate_team(genome_to_text(child))
        if not ok:
            fails.append((i, errs[:2]))
        if child[0]["species"] != "Umbreon":
            fails.append((i, f"lock broken: {child[0]['species']}"))
    print(f"  Failures: {len(fails)}/500")
    for idx, err in fails[:5]:
        print(f"    #{idx}: {err}")
    return [f"crossover stress: {len(fails)} failures"] if fails else []


def check_baseline():
    """9. BASELINE TEAM: data/baseline_team.txt is valid."""
    _section("9. BASELINE TEAM")
    baseline = data_path("baseline_team.txt")
    ok, errs = DB.validate_team(open(baseline).read())
    print(f"  {baseline}: {'VALID' if ok else 'INVALID ' + str(errs[:3])}")
    return [] if ok else ["baseline team invalid"]


CHECKS = (check_db, check_names, check_mega_stones, check_regional_teams, check_locked_fuzz,
          check_free_fuzz, check_mutation, check_crossover, check_baseline)


def main():
    """Run every check, print the report, return the list of hard failures."""
    problems = []
    random.seed(0)
    for check in CHECKS:
        problems += check()

    _section("AUDIT COMPLETE" if not problems else f"AUDIT FAILED: {len(problems)} problem(s)")
    for msg in problems:
        print(f"  FAIL {msg}")
    return problems


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
