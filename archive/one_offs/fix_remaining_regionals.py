"""
Fix 6 remaining regional team failures:
- 'Held Item:' scraper artifact
- Illegal abilities (typos/errors in Limitless data)
- Drop files that can't be fixed cleanly
"""
import os, glob, re, sys
sys.path.insert(0, os.path.expanduser("~/project"))
import regmc_db as DB

TEAM_DIR = os.path.expanduser("~/project/regional_teams")

def fix_team(text):
    """Return fixed text or None if unfixable."""
    mons = DB.parse_team(text)
    if not mons:
        return None

    lines = []
    for m in mons:
        species = m["species"].strip()
        sp = DB.get_species(species)
        if not sp:
            return None

        # Fix "Held Item:" artifact
        item = (m["item"] or "").strip()
        item = re.sub(r'^Held Item:\s*', '', item, flags=re.I)
        if not DB.is_legal_item(item):
            item = "Leftovers"
            # try to find a legal mega stone first
            if sp["megaStones"]:
                item = sp["megaStones"][0]

        # Fix illegal ability → fall back to first legal
        ability = (m["ability"] or "").strip()
        if not DB.species_has_ability(sp, ability):
            ability = sp["abilities"][0] if sp["abilities"] else "Pressure"

        # Nature
        nature = (m["nature"] or "Jolly").strip()
        # Verify nature exists
        db_natures = DB.load_db()["natures"]
        if nature not in db_natures:
            nature = "Jolly"

        # EVs
        evs = m["evs"] or {"hp": 2, "atk": 32, "spe": 32}
        ev_str = " / ".join(f"{v} {k.upper()}" for k, v in evs.items() if v > 0)
        if not ev_str:
            ev_str = "2 HP / 32 Atk / 32 Spe"

        # Moves — must be exactly 4 legal
        real_moves = [mv.strip() for mv in m["moves"] if mv.strip() and mv.strip() != "-"]
        legal_moves = []
        for mv in real_moves:
            if DB.species_can_learn(sp, mv) and DB.is_legal_move(mv):
                legal_moves.append(mv)
        if len(legal_moves) < 4:
            return None  # unfixable
        legal_moves = legal_moves[:4]

        lines.append(f"{species} @ {item}")
        lines.append(f"Ability: {ability}")
        lines.append("Level: 50")
        lines.append(f"{nature} Nature")
        lines.append(f"EVs: {ev_str}")
        for mv in legal_moves:
            lines.append(f"- {mv}")
        lines.append("")

    return "\n".join(lines)


def main():
    files = sorted(glob.glob(os.path.join(TEAM_DIR, "*.txt")))
    fixed = 0
    dropped = 0

    for f in files:
        src = open(f).read()
        # Skip if already valid
        ok, _ = DB.validate_team(src)
        if ok:
            continue

        result = fix_team(src)
        if result is None:
            os.remove(f)
            dropped += 1
            print(f"  dropped: {os.path.basename(f)}")
            continue

        ok2, errs2 = DB.validate_team(result)
        if ok2:
            open(f, "w").write(result)
            fixed += 1
            print(f"  fixed: {os.path.basename(f)}")
        else:
            os.remove(f)
            dropped += 1
            print(f"  dropped (still invalid): {os.path.basename(f)}: {errs2[:2]}")

    print(f"\nFixed: {fixed}")
    print(f"Dropped: {dropped}")
    print(f"Remaining: {len(glob.glob(os.path.join(TEAM_DIR, '*.txt')))}")


if __name__ == "__main__":
    main()
