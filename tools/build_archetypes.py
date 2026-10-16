"""Build per-species set archetypes from every real team paste we have.

Usage:
    python tools/build_archetypes.py            # writes data/species_archetypes.json
    python tools/build_archetypes.py --dry-run

Sources (deduplicated by team content): data/regional_teams/*.txt and
data/scraped/vgcpastes/teams/*.txt (tools/scrape_vgcpastes.py).

An archetype is an (item, nature) group of real sets for one species. Keeping item and nature
together is what lets the opponent model tell Garchomp-Z (Garchompite Z, Modest, special moves)
from Garchomp-physical (Life Orb/Choice Scarf, Jolly/Adamant, physical moves). Each group keeps
its spreads, moves and abilities as counts. A Mega form is stored under its base species, with the
form derived from the item (`form`), because pastes carry the base species plus the stone.

Output: {species: {"n": sets, "archetypes": [{item, nature, form, count,
         spreads: [{evs, count}], moves: {name: count}, abilities: {name: count}}]}}
"""
import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src import regmc_db as DB  # noqa: E402

SOURCES = [REPO / "data" / "regional_teams", REPO / "data" / "scraped" / "vgcpastes" / "teams"]
OUT = REPO / "data" / "species_archetypes.json"
MAX_SPREADS = 8


def set_key(mon: dict) -> tuple:
    return (mon["species"], mon["item"], mon["nature"], tuple(sorted(mon["evs"].items())),
            tuple(sorted(mon["moves"])))


def canon_species(raw: str):
    """Paste species -> storage key. A Mega form is stored under its base species."""
    name = DB.normalize_species_name(raw)
    sp = DB.get_species(name) if name else None
    if not sp:
        return None
    return sp["baseSpecies"] if (sp.get("forme") or "").startswith("Mega") else sp["name"]


def load_teams() -> list:
    teams, seen, dup = [], set(), 0
    for src in SOURCES:
        for f in sorted(src.glob("*.txt")):
            try:
                mons = DB.parse_team(f.read_text())
            except Exception:
                continue
            if len(mons) != 6:
                continue
            sig = hashlib.sha1(repr(sorted(set_key(m) for m in mons)).encode()).hexdigest()
            if sig in seen:
                dup += 1
                continue
            seen.add(sig)
            teams.append(mons)
    print(f"{len(teams)} unique teams ({dup} duplicates skipped)")
    return teams


def mega_form(item_name: str, species: str):
    it = DB.get_item(item_name) if item_name else None
    return ((it or {}).get("megaStone") or {}).get(species)


def build(teams: list) -> dict:
    groups = defaultdict(lambda: {"count": 0, "spreads": Counter(), "moves": Counter(), "abilities": Counter()})
    totals = Counter()
    skipped = Counter()
    for mons in teams:
        for m in mons:
            sp = canon_species(m["species"])
            if sp is None:
                skipped[m["species"]] += 1
                continue
            item = (DB.get_item(m["item"]) or {}).get("name", m["item"])
            nature = m["nature"] or "Serious"
            g = groups[(sp, item, nature)]
            g["count"] += 1
            g["spreads"][tuple(sorted((k, v) for k, v in m["evs"].items() if v > 0))] += 1
            g["moves"].update(DB.get_move(x)["name"] if DB.get_move(x) else x for x in m["moves"])
            if m["ability"]:
                g["abilities"][m["ability"]] += 1
            totals[sp] += 1
    out = defaultdict(lambda: {"n": 0, "archetypes": []})
    for (sp, item, nature), g in groups.items():
        out[sp]["archetypes"].append({
            "item": item, "nature": nature, "form": mega_form(item, sp), "count": g["count"],
            "spreads": [{"evs": dict(k), "count": c} for k, c in g["spreads"].most_common(MAX_SPREADS)],
            "moves": dict(g["moves"].most_common()),
            "abilities": dict(g["abilities"].most_common()),
        })
    for sp, d in out.items():
        d["n"] = totals[sp]
        d["archetypes"].sort(key=lambda a: -a["count"])
    if skipped:
        print(f"unresolved species skipped: {dict(skipped)}")
    return dict(sorted(out.items()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    dry = ap.parse_args().dry_run
    data = build(load_teams())
    print(f"{len(data)} species, {sum(len(d['archetypes']) for d in data.values())} archetypes, "
          f"{sum(d['n'] for d in data.values())} sets")
    for sp in ("Garchomp", "Lucario", "Absol"):
        d = data.get(sp)
        if d:
            print(sp, d["n"], [(a["item"], a["nature"], a["count"]) for a in d["archetypes"][:6]])
    if not dry:
        OUT.write_text(json.dumps(data, indent=1))
        print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
