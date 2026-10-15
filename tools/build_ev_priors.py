"""Build joint (evs, nature) priors from VGCPastes scraped teams.

Usage:
    python3 tools/build_ev_priors.py

Reads /tmp/vgc_scraped/*.txt (Pokepaste format), aggregates per-species
(evs, nature) tuples by frequency, writes data/species_build_priors.json.

Also builds data/species_ability_priors.json from the same teams.

Only includes (evs, nature) tuples that appear >= 2 times per species, to
avoid a long tail of one-off noise. Species with only one unique build get
that build as the sole prior.
"""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path.home() / "project"
sys.path.insert(0, str(REPO))
from src import regmc_db as DB

SCRAPED = Path("/tmp/vgc_scraped")
OUT_BUILD = REPO / "data" / "species_build_priors.json"
OUT_ABILITY = REPO / "data" / "species_ability_priors.json"

MIN_COUNT = 2
MAX_SPREADS = 20


def ev_tuple(evs):
    """Convert evs dict to a sorted hashable tuple of (stat, value)."""
    if not evs:
        return ()
    return tuple(sorted((k, int(v)) for k, v in evs.items() if int(v) > 0))


def main():
    files = sorted(SCRAPED.glob("*.txt"))
    print(f"reading {len(files)} teams...")

    build_counts = {}   # species -> Counter of (evs_tuple, nature)
    ability_counts = {} # species -> Counter of ability
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
            sp = m.get("species", "").strip()
            if not sp:
                continue
            evs = m.get("evs") or {}
            nat = (m.get("nature") or "").strip() or "Neutral"
            abil = (m.get("ability") or "").strip()
            key = (ev_tuple(evs), nat)
            build_counts.setdefault(sp, Counter())[key] += 1
            if abil:
                ability_counts.setdefault(sp, Counter())[abil] += 1
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}  parsed={parsed} skipped={skipped}")

    print(f"\nparsed: {parsed}  skipped: {skipped}")
    print(f"species with builds: {len(build_counts)}")
    print(f"species with abilities: {len(ability_counts)}")

    # --- build priors ---
    build_out = {}
    for sp, counter in sorted(build_counts.items()):
        entries = []
        for (ev_tup, nat), count in counter.most_common(MAX_SPREADS):
            if count < MIN_COUNT and entries:
                break
            evs = dict(ev_tup)
            entries.append({
                "evs": evs,
                "nature": nat,
                "count": count,
            })
        if entries:
            build_out[sp] = entries

    ability_out = {}
    for sp, counter in sorted(ability_counts.items()):
        entries = [{"ability": a, "count": c} for a, c in counter.most_common(10)]
        if entries:
            ability_out[sp] = entries

    OUT_BUILD.write_text(json.dumps(build_out, indent=2))
    OUT_ABILITY.write_text(json.dumps(ability_out, indent=2))

    print(f"\nwrote {OUT_BUILD} ({len(build_out)} species)")
    print(f"wrote {OUT_ABILITY} ({len(ability_out)} species)")

    # --- sanity samples ---
    for name in ["Garchomp", "Umbreon", "Incineroar", "Rillaboom", "Gholdengo"]:
        if name in build_out:
            print(f"\n{name}:")
            for e in build_out[name][:3]:
                evs = e["evs"]
                ev_str = " / ".join(f"{v} {k.upper()}" for k, v in evs.items())
                print(f"  {ev_str}  {e['nature']}  (n={e['count']})")
        if name in ability_out:
            print(f"  abilities: {[(e['ability'], e['count']) for e in ability_out[name][:3]]}")


if __name__ == "__main__":
    main()
