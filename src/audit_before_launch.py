"""
Full pre-flight audit before launching the counter-meta GA.
Checks every layer of the data + generation pipeline.
"""
import os, sys, glob, random, json, traceback
sys.path.insert(0, os.path.expanduser("~/project/src"))
import regmc_db as DB
import ga_core as G

random.seed(0)

print("=" * 60)
print("1. DB INTEGRITY")
print("=" * 60)
db = DB.load_db()
print(f"  format: {db['meta']['formatName']}")
print(f"  mod:    {db['meta']['mod']}")
print(f"  built:  {db['meta']['built']}")
print(f"  species (all/base): {len(db['species'])}/{len(G._BASE_SPECIES)}")
print(f"  items:    {len(db['items'])}")
print(f"  moves:    {len(db['moves'])}")
print(f"  abilities:{len(db['abilities'])}")
print(f"  natures:  {len(db['natures'])}")

print()
print("=" * 60)
print("2. NAME SANITY")
print("=" * 60)

# Every species must have: name, baseSpecies, abilities (non-empty), moves (>=4)
bad_species = []
for s in G._BASE_SPECIES:
    if not s.get("name"): bad_species.append((s.get("name"), "no name"))
    elif not s.get("baseSpecies"): bad_species.append((s["name"], "no baseSpecies"))
    elif not s.get("abilities"): bad_species.append((s["name"], "no abilities"))
    elif len(s.get("moves", [])) < 4: bad_species.append((s["name"], f"only {len(s['moves'])} moves"))
print(f"  Species with issues: {len(bad_species)}")
for n, why in bad_species[:10]: print(f"    {n}: {why}")

# Every item must have: name, id
bad_items = []
for it in G._ITEMS:
    if not it.get("name") or not it.get("id"):
        bad_items.append(it.get("name", "?"))
print(f"  Items with issues: {len(bad_items)}")

# Every nature must have: name, plus, minus (some neutral natures have both as "")
bad_natures = [n for n in G._NATURES if not n]
print(f"  Bad natures: {len(bad_natures)}")
print(f"  Total natures: {len(G._NATURES)}")
print(f"  Sample: {G._NATURES[:8]}")

print()
print("=" * 60)
print("3. MEGA STONE INTEGRITY")
print("=" * 60)
# Every mega stone must be legal item
mega_species = [s for s in G._BASE_SPECIES if s["megaStones"]]
print(f"  Base species with mega stones: {len(mega_species)}")
bad_stones = []
for s in mega_species:
    for stone in s["megaStones"]:
        if not DB.is_legal_item(stone):
            bad_stones.append((s["name"], stone))
print(f"  Species with illegal stone ref: {len(bad_stones)}")
for n, st in bad_stones[:5]: print(f"    {n}: {st}")

# Check _legal_items_for returns only legal items
print()
print("  Sampling _legal_items_for:")
for sp_name in ["Umbreon", "Salamence", "Garchomp", "Incineroar", "Rillaboom"]:
    items = G._legal_items_for(sp_name)
    illegal = [i for i in items if not DB.is_legal_item(i)]
    print(f"    {sp_name}: {len(items)} items, {len(illegal)} illegal")
    if illegal:
        print(f"      ILLEGAL: {illegal[:3]}")

print()
print("=" * 60)
print("4. REGIONAL TEAMS")
print("=" * 60)
regional = G.regional_pool()
print(f"  Loaded: {len(regional)} teams")
bad_regional = 0
for i, text in enumerate(regional):
    ok, errs = DB.validate_team(text)
    if not ok:
        bad_regional += 1
        if bad_regional <= 3:
            print(f"    INVALID #{i}: {errs[:2]}")
print(f"  Invalid regional teams: {bad_regional}")

print()
print("=" * 60)
print("5. FUZZ TEST — 500 random Umbreon-locked genomes")
print("=" * 60)
locked = {0: "Umbreon"}
fails = []
for i in range(500):
    g = G.build_random_genome(locked)
    if g is None:
        fails.append((i, "build returned None"))
        continue
    text = G.genome_to_text(g)
    ok, errs = DB.validate_team(text)
    if not ok:
        fails.append((i, errs[:2]))
    # Lock check
    if g[0]["species"] != "Umbreon":
        fails.append((i, f"lock violated: {g[0]['species']}"))
print(f"  Failures: {len(fails)}/500")
for idx, err in fails[:5]: print(f"    #{idx}: {err}")

print()
print("=" * 60)
print("6. FUZZ TEST — 500 random free genomes")
print("=" * 60)
fails = []
for i in range(500):
    g = G.build_random_genome({})
    if g is None:
        fails.append((i, "build returned None"))
        continue
    text = G.genome_to_text(g)
    ok, errs = DB.validate_team(text)
    if not ok:
        fails.append((i, errs[:2]))
print(f"  Failures: {len(fails)}/500")
for idx, err in fails[:5]: print(f"    #{idx}: {err}")

print()
print("=" * 60)
print("7. MUTATION STRESS TEST — 2000 mutations on locked genome")
print("=" * 60)
random.seed(42)
g = G.build_random_genome(locked)
ok, errs = DB.validate_team(G.genome_to_text(g))
if not ok:
    print(f"  Seed genome invalid: {errs[:2]}")
else:
    for i in range(2000):
        g = G.mutate(g, locked)
        if g[0]["species"] != "Umbreon":
            print(f"  LOCK BROKEN at mutation {i}: {g[0]['species']}")
            break
        if i % 500 == 0:
            ok, errs = DB.validate_team(G.genome_to_text(g))
            if not ok:
                print(f"  Invalid after {i} mutations: {errs[:2]}")
                break
    else:
        print(f"  After 2000 mutations: lock held, checking final validity...")
        ok, errs = DB.validate_team(G.genome_to_text(g))
        print(f"  Final: {'VALID' if ok else 'INVALID: ' + str(errs[:2])}")

print()
print("=" * 60)
print("8. CROSSOVER STRESS TEST — 500 crossovers")
print("=" * 60)
random.seed(1)
fails = []
for i in range(500):
    p1 = G.build_random_genome(locked)
    p2 = G.build_random_genome(locked)
    if not p1 or not p2:
        continue
    child = G.crossover(p1, p2, locked)
    ok, errs = DB.validate_team(G.genome_to_text(child))
    if not ok:
        fails.append((i, errs[:2]))
    if child[0]["species"] != "Umbreon":
        fails.append((i, f"lock broken: {child[0]['species']}"))
print(f"  Failures: {len(fails)}/500")
for idx, err in fails[:5]: print(f"    #{idx}: {err}")

print()
print("=" * 60)
print("9. BASELINE TEAM")
print("=" * 60)
baseline = os.path.expanduser("~/project/data/baseline_team.txt")
ok, errs = DB.validate_team(open(baseline).read())
print(f"  {baseline}: {'VALID' if ok else 'INVALID ' + str(errs[:3])}")

print()
print("=" * 60)
print("AUDIT COMPLETE")
print("=" * 60)
