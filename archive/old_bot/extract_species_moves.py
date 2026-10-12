import json, re
from collections import Counter, defaultdict

# Parse every |move| line from raw replays
# Format: |move|p1a: Charizard|Heat Wave|p2a: Incineroar
RE_MOVE = re.compile(r"^\|move\|p[12][ab]: ([^|]+)\|([^|]+)\|")

species_moves = defaultdict(Counter)
species_items = defaultdict(Counter)
species_abilities = defaultdict(Counter)

with open("regmc_replays.jsonl") as f:
    for i, line in enumerate(f):
        r = json.loads(line)
        log = r.get("log", "")
        for entry in log.split("\n"):
            m = RE_MOVE.match(entry)
            if m:
                species = m.group(1).strip()
                move = m.group(2).strip()
                # Skip non-move events
                if move.startswith("move:") or not move:
                    continue
                species_moves[species][move] += 1
            # Item reveals
            if entry.startswith("|-item|"):
                parts = entry.split("|")
                if len(parts) >= 4:
                    species = parts[2].split(":")[-1].strip()
                    item = parts[3].strip()
                    species_items[species][item] += 1
            # Ability reveals
            if entry.startswith("|-ability|"):
                parts = entry.split("|")
                if len(parts) >= 4:
                    species = parts[2].split(":")[-1].strip()
                    ability = parts[3].strip()
                    species_abilities[species][ability] += 1

# Build top-4 move sets per species
MIN_USES = 5
result = {}
for species, counter in species_moves.items():
    top = [m for m, c in counter.most_common(8) if c >= MIN_USES]
    if len(top) >= 4:
        result[species] = {
            "moves": top[:4],
            "alt_moves": top[4:8],  # alternatives for GA mutation
            "top_items": [i for i, _ in species_items[species].most_common(3)],
            "top_abilities": [a for a, _ in species_abilities[species].most_common(3)],
        }

with open("species_real_moves.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"Species with 4+ real moves: {len(result)}")
print("\nSample — top 10:")
for sp in list(result.keys())[:10]:
    moves = ", ".join(result[sp]["moves"])
    print(f"  {sp:<20} {moves}")

print(f"\n✅ Saved species_real_moves.json")
