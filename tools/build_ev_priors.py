"""Build (species, item)-keyed build priors from VGCPastes scraped teams.

Usage:
    python3 tools/build_ev_priors.py

Outputs:
    data/species_build_priors.json     keyed by "Species @ Item" AND "Species"
    data/species_ability_priors.json   keyed by species only

Item-keyed entries are stored only when they have >= MIN_ITEM_COUNT teams.
Species-only entries aggregate across all items and serve as fallback.
Sampling logic (in ga_core._random_mon) should prefer item-keyed, fall
back to species-only.

Format per entry (list, most-common-first):
    {"evs": {"hp": 2, "atk": 32, "spe": 32}, "nature": "Jolly", "count": 47}
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path.home() / "project"
sys.path.insert(0, str(REPO))
from src import regmc_db as DB

SCRAPED = Path("/tmp/vgc_scraped")
OUT_BUILD = REPO / "data" / "species_build_priors.json"
OUT_ABILITY = REPO / "data" / "species_ability_priors.json"

MIN_COUNT_SPECIES = 2    # species-level entries need >= 2 occurrences
MIN_COUNT_ITEM = 3       # (species, item) entries need >= 3 occurrences
MAX_SPREADS = 25
MAX_ABILITIES = 5


def normalize_item(item):
    """Normalize item name to what appears after '@'. Handles empty/None."""
    if not item:
        return ""
    return item.strip()


def ev_tuple(evs):
    """Convert evs dict to hashable tuple of (stat, value), zeros dropped."""
    if not evs:
        return ()
    return tuple(sorted((k, int(v)) for k, v in evs.items() if int(v) > 0))


def main():
    files = sorted(SCRAPED.glob("*.txt"))
    print(f"reading {len(files)} teams...")

    # Counters keyed by species and by (species, item)
    species_build = defaultdict(Counter)      # species -> Counter[(evs_tuple, nature)]
    item_build = defaultdict(Counter)         # (species, item) -> Counter[...]
    species_ability = defaultdict(Counter)    # species -> Counter[ability]

    parsed = skipped = 0
    for i, f in enumerate(files):
        text = f.read_text()
        try:
            mons = DB.parse_team(text)
        except Exception:
            skipped += 1
            continue
        if not mons or len(mons) != 6:
            skipped += 1
            continue
        parsed += 1

        for m in mons:
            sp = (m.get("species") or "").strip()
            if not sp:
                continue
            item = normalize_item(m.get("item"))
            evs = m.get("evs") or {}
            nat = (m.get("nature") or "").strip() or "Neutral"
            abil = (m.get("ability") or "").strip()

            key = (ev_tuple(evs), nat)
            species_build[sp][key] += 1
            if item:
                item_build[(sp, item)][key] += 1
            if abil:
                species_ability[sp][abil] += 1

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}  parsed={parsed} skipped={skipped}")

    print(f"\nparsed: {parsed}  skipped: {skipped}")
    print(f"species with builds:    {len(species_build)}")
    print(f"species+item with builds: {len(item_build)}")
    print(f"species with abilities: {len(species_ability)}")

    # --- build output dict ---
    build_out = {}

    # species-only entries
    for sp, counter in sorted(species_build.items()):
        entries = []
        for (ev_tup, nat), count in counter.most_common(MAX_SPREADS):
            if count < MIN_COUNT_SPECIES and entries:
                break
            entries.append({
                "evs": dict(ev_tup),
                "nature": nat,
                "count": count,
            })
        if entries:
            build_out[sp] = entries

    # item-keyed entries — only when well-populated
    item_keys_added = 0
    for (sp, item), counter in sorted(item_build.items()):
        total = sum(counter.values())
        if total < MIN_COUNT_ITEM:
            continue
        entries = []
        for (ev_tup, nat), count in counter.most_common(MAX_SPREADS):
            if count < MIN_COUNT_SPECIES and entries:
                break
            entries.append({
                "evs": dict(ev_tup),
                "nature": nat,
                "count": count,
            })
        if entries:
            key = f"{sp} @ {item}"
            build_out[key] = entries
            item_keys_added += 1

    # ability priors (species-only)
    ability_out = {}
    for sp, counter in sorted(species_ability.items()):
        entries = [{"ability": a, "count": c}
                   for a, c in counter.most_common(MAX_ABILITIES)]
        if entries:
            ability_out[sp] = entries

    OUT_BUILD.write_text(json.dumps(build_out, indent=2))
    OUT_ABILITY.write_text(json.dumps(ability_out, indent=2))

    print(f"\nwrote {OUT_BUILD}")
    print(f"  species-only keys: {len(species_build)}")
    print(f"  (species, item) keys added: {item_keys_added}")
    print(f"  total keys: {len(build_out)}")
    print(f"wrote {OUT_ABILITY} ({len(ability_out)} species)")

    # --- sanity samples ---
    def show(key):
        if key in build_out:
            print(f"\n{key}:")
            for e in build_out[key][:5]:
                evs = e["evs"]
                ev_str = " / ".join(f"{v} {k.upper()}" for k, v in evs.items()) or "(no EVs)"
                print(f"  {ev_str:40}  {e['nature']:10}  (n={e['count']})")
        else:
            print(f"\n{key}: NOT FOUND")

    print("\n=== sanity ===")
    show("Garchomp")
    show("Garchomp @ Garchompite Z")
    show("Garchomp @ Rocky Helmet")
    show("Garchomp @ Choice Scarf")
    show("Incineroar @ Sitrus Berry")
    show("Umbreon @ Leftovers")

    if "Garchomp" in ability_out:
        print(f"\nGarchomp abilities: {ability_out['Garchomp']}")


if __name__ == "__main__":
    main()
