"""
Fix species name mismatches in regional teams and drop malformed ones.
Limitless uses "Hisuian Arcanine"; Showdown uses "Arcanine-Hisui".
"""
import os, glob, re, sys
sys.path.insert(0, os.path.expanduser("~/project"))
import regmc_db as DB

TEAM_DIR = os.path.expanduser("~/project/regional_teams")

# Name mapping: Limitless → Showdown
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
    "Basculegion Female": "Basculegion-F",
    "Basculegion Male": "Basculegion-M",
    "Oinkologne Female": "Oinkologne-F",
    "Oinkologne Male": "Oinkologne-M",
}

def normalize_species(name):
    name = name.strip()
    if name in SPECIES_MAP:
        return SPECIES_MAP[name]
    # If DB already knows it, use it
    sp = DB.get_species(name)
    if sp:
        return sp["name"]
    return name

def normalize_team_text(text):
    """Rewrite species names and return normalized text, or None if malformed."""
    mons = DB.parse_team(text)
    if not mons:
        return None

    lines = []
    for m in mons:
        species = normalize_species(m["species"])
        if not DB.get_species(species):
            return None  # unknown species even after mapping

        # Reject malformed moves: '-' placeholder or fewer than 4 real moves
        real_moves = [mv for mv in m["moves"] if mv and mv.strip() and mv.strip() != "-"]
        if len(real_moves) < 4:
            return None
        real_moves = real_moves[:4]

        item = m["item"] or "Leftovers"
        ability = m["ability"] or "Pressure"
        nature = m["nature"] or "Jolly"
        evs = m["evs"] or {}
        ev_str = " / ".join(f"{v} {k.upper()}" for k, v in evs.items() if v > 0) or "2 HP / 32 Atk / 32 Spe"

        lines.append(f"{species} @ {item}")
        lines.append(f"Ability: {ability}")
        lines.append("Level: 50")
        lines.append(f"{nature} Nature")
        lines.append(f"EVs: {ev_str}")
        for mv in real_moves:
            lines.append(f"- {mv}")
        lines.append("")

    return "\n".join(lines)

def main():
    files = sorted(glob.glob(os.path.join(TEAM_DIR, "*.txt")))
    fixed = 0
    dropped = 0
    unchanged = 0

    for f in files:
        src = open(f).read()
        normalized = normalize_team_text(src)
        if normalized is None:
            os.remove(f)
            dropped += 1
            continue
        if normalized.strip() != src.strip():
            open(f, "w").write(normalized)
            fixed += 1
        else:
            unchanged += 1

    print(f"Fixed: {fixed}")
    print(f"Dropped (malformed/unknown): {dropped}")
    print(f"Unchanged: {unchanged}")
    print(f"Remaining: {len(glob.glob(os.path.join(TEAM_DIR, '*.txt')))}")

if __name__ == "__main__":
    main()
