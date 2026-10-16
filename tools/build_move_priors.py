"""Build move priors from VGCPastes scraped teams (tournament source).

Mirrors build_ev_priors.py. Outputs data/species_move_priors.json,
overwriting the previous ladder-sourced version. Keeps a backup of
the ladder version as species_move_priors.ladder.bak.json.

Aggregates move frequency per species, top MAX_MOVES entries each.
"""
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path.home() / "project"
sys.path.insert(0, str(REPO))
from src import regmc_db as DB

SCRAPED = Path("/tmp/vgc_scraped")
OUT = REPO / "data" / "species_move_priors.json"
BAK = REPO / "data" / "species_move_priors.ladder.bak.json"

MAX_MOVES = 20


def main():
    # Backup old file before overwriting
    if OUT.exists() and not BAK.exists():
        shutil.copy(OUT, BAK)
        print(f"backed up old -> {BAK.name}")

    files = sorted(SCRAPED.glob("*.txt"))
    print(f"reading {len(files)} teams...")

    counts = defaultdict(Counter)  # species -> Counter[move_name]
    unresolved = Counter()  # raw species strings we couldn't canonicalize
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
            raw_sp = (m.get("species") or "").strip()
            sp = DB.normalize_species_name(raw_sp)
            if not sp or not DB.get_species(sp):
                if raw_sp:
                    unresolved[raw_sp] += 1
                continue
            for mv in (m.get("moves") or []):
                mv = (mv or "").strip()
                if mv:
                    counts[sp][mv] += 1
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}  parsed={parsed} skipped={skipped}")

    print(f"\nparsed: {parsed}  skipped: {skipped}")
    if unresolved:
        print(f"unresolved species names: {len(unresolved)} unique, "
              f"{sum(unresolved.values())} occurrences")
        for name, c in unresolved.most_common(10):
            print(f"  {c:>4}  {name}")
    print(f"species with moves: {len(counts)}")

    out = {}
    for sp, counter in sorted(counts.items()):
        entries = [{"move": mv, "count": c}
                   for mv, c in counter.most_common(MAX_MOVES)]
        out[sp] = entries

    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {OUT} ({len(out)} species)")

    # --- sanity samples ---
    print("\n=== sanity ===")
    for name in ["Garchomp", "Incineroar", "Rillaboom", "Umbreon", "Gholdengo"]:
        if name in out:
            top = [(e["move"], e["count"]) for e in out[name][:6]]
            print(f"  {name:15} {top}")

    # --- coverage delta ---
    old = json.loads(BAK.read_text()) if BAK.exists() else {}
    print(f"\n=== coverage delta ===")
    print(f"  ladder source:      {len(old)} species")
    print(f"  tournament source:  {len(out)} species")
    new_only = set(out.keys()) - set(old.keys())
    old_only = set(old.keys()) - set(out.keys())
    print(f"  new species added:  {len(new_only)}")
    print(f"  species dropped:    {len(old_only)}")
    if new_only:
        print(f"  examples added: {sorted(new_only)[:10]}")
    if old_only:
        print(f"  examples dropped: {sorted(old_only)[:10]}")


if __name__ == "__main__":
    main()
