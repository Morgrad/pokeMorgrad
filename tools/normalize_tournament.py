"""Normalize species names and clean artifacts in freshly-scraped teams.

Usage:
    python3 tools/normalize_tournament.py <prefix>
    python3 tools/normalize_tournament.py louisville

Rewrites <prefix>_*.txt in data/regional_teams/ in place:
  - Converts prefix-form names ("Female Indeedee") to suffix-form
    ("Indeedee-F"), which poke_env and Showdown expect
  - Strips "Held Item:" artifacts, substitutes a legal item
  - Rejects files that can't be fixed cleanly (moves to _rejected/)

Idempotent: rerunning produces no changes.
"""
import re
import sys
from pathlib import Path

REPO = Path.home() / "project"
sys.path.insert(0, str(REPO))
from src import regmc_db as DB

TEAM_DIR = REPO / "data" / "regional_teams"
REJECT_DIR = TEAM_DIR / "_rejected"
REJECT_DIR.mkdir(exist_ok=True)

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)
PREFIX = sys.argv[1]
GLOB = f"{PREFIX}_*.txt"

SPECIES_MAP = {
    "Hisuian Arcanine": "Arcanine-Hisui",
    "Hisuian Typhlosion": "Typhlosion-Hisui",
    "Hisuian Zoroark": "Zoroark-Hisui",
    "Hisuian Goodra": "Goodra-Hisui",
    "Hisuian Samurott": "Samurott-Hisui",
    "Hisuian Decidueye": "Decidueye-Hisui",
    "Hisuian Sneasel": "Sneasel-Hisui",
    "Hisuian Growlithe": "Growlithe-Hisui",
    "Eternal Flower Floette": "Floette-Eternal",
    "Female Indeedee": "Indeedee-F",
    "Male Indeedee": "Indeedee-M",
    "Female Meowstic": "Meowstic-F",
    "Male Meowstic": "Meowstic-M",
    "Female Basculegion": "Basculegion-F",
    "Male Basculegion": "Basculegion-M",
    "Female Oinkologne": "Oinkologne-F",
    "Male Oinkologne": "Oinkologne-M",
    "Alolan Ninetales": "Ninetales-Alola",
    "Alolan Persian": "Persian-Alola",
    "Alolan Sandslash": "Sandslash-Alola",
    "Alolan Raichu": "Raichu-Alola",
    "Alolan Marowak": "Marowak-Alola",
    "Alolan Exeggutor": "Exeggutor-Alola",
    "Galarian Slowking": "Slowking-Galar",
    "Galarian Slowbro": "Slowbro-Galar",
    "Galarian Zapdos": "Zapdos-Galar",
    "Galarian Moltres": "Moltres-Galar",
    "Galarian Articuno": "Articuno-Galar",
    "Galarian Weezing": "Weezing-Galar",
    "Galarian Darmanitan": "Darmanitan-Galar",
    "Paldean Tauros Aqua Breed": "Tauros-Paldea-Aqua",
    "Paldean Tauros Blaze Breed": "Tauros-Paldea-Blaze",
    "Paldean Tauros Combat Breed": "Tauros-Paldea-Combat",
    "Paldean Wooper": "Wooper-Paldea",
    "Heat Rotom": "Rotom-Heat",
    "Wash Rotom": "Rotom-Wash",
    "Frost Rotom": "Rotom-Frost",
    "Fan Rotom": "Rotom-Fan",
    "Mow Rotom": "Rotom-Mow",
    "Basculin White-Striped": "Basculin-White-Striped",
}
FALLBACK_ITEMS = ["Sitrus Berry", "Mystic Water", "Sharp Beak", "Damp Rock"]


def normalize_species(name):
    name = name.strip()
    if name in SPECIES_MAP:
        return SPECIES_MAP[name]
    sp = DB.get_species(name)
    if sp:
        return sp["name"]
    return name


def rewrite_file(path):
    text = path.read_text()

    # Fix "Held Item:" artifacts before parsing
    text = re.sub(r"@ Held Item:\s*\n", "@ Leftovers\n", text)

    mons = DB.parse_team(text)
    if not mons:
        return None, "unfixable"

    lines = []
    used_items = set()
    for m in mons:
        species = normalize_species(m["species"])
        if not DB.get_species(species):
            return None, "unfixable"

        item = (m["item"] or "Leftovers").strip()
        if item in used_items or item.lower() in ("helditem", "held item", ""):
            for fb in FALLBACK_ITEMS:
                if fb not in used_items:
                    item = fb
                    break
        used_items.add(item)

        ability = (m["ability"] or "Pressure").strip()
        nature = (m["nature"] or "Jolly").strip()
        evs = m.get("evs") or {}
        ev_str = " / ".join(f"{v} {k.upper()}" for k, v in evs.items() if v > 0)
        if not ev_str:
            ev_str = "2 HP / 32 Atk / 32 Spe"

        real_moves = [mv.strip() for mv in m["moves"]
                      if mv and mv.strip() and mv.strip() != "-"]
        if len(real_moves) < 4:
            return None, "unfixable"

        lines.append(f"{species} @ {item}")
        lines.append(f"Ability: {ability}")
        lines.append("Level: 50")
        lines.append(f"{nature} Nature")
        lines.append(f"EVs: {ev_str}")
        for mv in real_moves[:4]:
            lines.append(f"- {mv}")
        lines.append("")

    new_text = "\n".join(lines)
    return new_text, ("ok" if new_text != path.read_text() else "unchanged")


def main():
    files = sorted(TEAM_DIR.glob(GLOB))
    print(f"Normalizing {len(files)} files matching {GLOB}")
    ok = unchanged = rejected = 0

    for f in files:
        new_text, status = rewrite_file(f)
        if status == "unfixable":
            f.rename(REJECT_DIR / f.name)
            rejected += 1
            print(f"  reject {f.name}")
            continue
        if status == "unchanged":
            unchanged += 1
            continue
        f.write_text(new_text)
        ok += 1

    print(f"\nRewritten: {ok}")
    print(f"Unchanged: {unchanged}")
    print(f"Rejected (moved to {REJECT_DIR}): {rejected}")
    if ok or rejected:
        print(f"\nNext: python3 tools/extend_train_pool.py {PREFIX}")


if __name__ == "__main__":
    main()
