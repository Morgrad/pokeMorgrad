"""Generate fully legal Showdown teams for any species using regmc_learnsets.json."""
import json, random

LEARNSETS = json.load(open("regmc_learnsets.json"))
MOVE_INFO = json.load(open("regmc_moves.json"))
try:
    REAL_MOVES = json.load(open("species_real_moves.json"))
except FileNotFoundError:
    REAL_MOVES = {}
ITEMS = json.load(open("regmc_items.json"))
MEGA_STONES = ITEMS["mega_stones"]
GENERIC_ITEMS = ITEMS["generic_items"]

# Preferred items by role (fallbacks in case species can't hold Mega)
DEFAULT_ITEMS = ["Leftovers","Sitrus Berry","Focus Sash","Life Orb","Rocky Helmet",
                 "Lum Berry","Miracle Seed","Charcoal","Mystic Water","Black Glasses"]

# Essential moves that should be prioritized if legal
ESSENTIAL = {"Protect","Fake Out","Trick Room","Tailwind","Wide Guard","Quick Guard",
             "Helping Hand","Follow Me","Rage Powder","Spiky Shield","King's Shield",
             "Baneful Bunker","Detect","Yawn","Taunt","Encore","Swords Dance",
             "Nasty Plot","Calm Mind","Bulk Up","Dragon Dance","Will-O-Wisp","Thunder Wave"}

NATURES = ["Adamant","Modest","Jolly","Timid","Bold","Calm","Impish","Careful",
           "Naive","Hasty","Relaxed","Quiet","Brave","Sassy","Rash","Mild","Lonely","Gentle"]

def _lookup_learnset(species):
    """Try exact name, then try stripping form suffixes."""
    if species in LEARNSETS: return LEARNSETS[species]
    for suffix in ["-Blue","-Yellow","-White","-Green","-Alola","-Hisui","-Galar",
                   "-Paldea","-Blaze","-Aqua","-Combat","-Combat-Breed","-Family-of-Three",
                   "-Female","-Male","-Small","-Large","-Super","-Dusk","-Midnight","-Midday"]:
        if species.endswith(suffix):
            base = species[:-len(suffix)]
            if base in LEARNSETS: return LEARNSETS[base]
    # Last resort: strip anything after last dash
    if "-" in species:
        base = species.rsplit("-", 1)[0]
        if base in LEARNSETS: return LEARNSETS[base]
    return None

def pick_moves(species):
    ls = _lookup_learnset(species)
    valid = set(ls["moves"]) if ls and ls.get("moves") else set()
    # Prefer real competitive moves, filtered to legal
    if species in REAL_MOVES and valid:
        real = REAL_MOVES[species]
        moves = [m for m in real["moves"] if m in valid]
        alts = [m for m in real.get("alt_moves", []) if m in valid]
        # Pad with any legal move if we have fewer than 4
        for m in ls["moves"]:
            if len(moves) >= 4: break
            if m not in moves: moves.append(m)
        # Occasionally swap an alt
        if len(moves) == 4 and alts and random.random() < 0.4:
            idx = random.randint(0, 3)
            alt = random.choice(alts)
            if alt not in moves: moves[idx] = alt
        return moves[:4]
    # Fallback: learnset-based
    if not ls:
        return []
    pool = ls["moves"]
    # Prioritize essential utility moves, then attacks
    utility = [m for m in pool if m in ESSENTIAL]
    attacks = [m for m in pool if MOVE_INFO.get(m, {}).get("basePower", 0) >= 50]
    random.shuffle(utility); random.shuffle(attacks)
    chosen = utility[:2] + attacks[:2]
    # If fewer than 4, fill from remaining pool
    for m in pool:
        if len(chosen) >= 4: break
        if m not in chosen: chosen.append(m)
    return chosen[:4]

def pick_ability(species):
    ls = _lookup_learnset(species)
    valid = set(ls["abilities"]) if ls and ls.get("abilities") else set()
    # Only use replay abilities if they're actually legal for this species
    if species in REAL_MOVES and valid:
        real = REAL_MOVES[species].get("top_abilities", [])
        filtered = [a for a in real if a in valid]
        if filtered:
            return random.choice(filtered)
    if valid:
        return random.choice(list(valid))
    return None

def pick_item(species, used_items):
    # Real item from replays first — but only if it's a known legal item
    ALL_LEGAL_ITEMS = set(GENERIC_ITEMS) | {m["stone"] for m in MEGA_STONES.values()}
    if species in REAL_MOVES and REAL_MOVES[species].get("top_items"):
        for item in REAL_MOVES[species]["top_items"]:
            if item in ALL_LEGAL_ITEMS and item not in used_items:
                return item
    # Then Mega Stone
    if species in MEGA_STONES and random.random() < 0.25:
        stone = MEGA_STONES[species]["stone"]
        if stone not in used_items:
            return stone
    # Otherwise generic
    for item in DEFAULT_ITEMS:
        if item not in used_items: return item
    for item in GENERIC_ITEMS:
        if item not in used_items: return item
    return "Leftovers"

def pick_evs(species=None):
    """Competitive EV spread based on species base stats, not random."""
    stats = ["hp","atk","def","spa","spd","spe"]
    budget = 66
    evs = {s: 0 for s in stats}

    # Look up base stats if we have them
    base = {}
    if species:
        ls = _lookup_learnset(species)
        if ls:
            base = ls.get("baseStats", {})

    atk = base.get("atk", 100)
    spa = base.get("spa", 100)
    spe = base.get("spe", 100)
    hp = base.get("hp", 100)
    dfn = base.get("def", 100)
    spd = base.get("spd", 100)

    # Determine role
    physical = atk > spa + 15
    special = spa > atk + 15
    fast = spe >= 90
    bulky = hp + dfn + spd >= 300

    # Standard comp EV distribution — every branch sums to exactly 66
    if fast and (physical or special):
        # Fast attacker: 32 offense, 32 speed, 2 HP
        evs["spe"] = 32
        evs["atk" if physical else "spa"] = 32
        evs["hp"] = 2
    elif bulky and not fast:
        # Bulky wall: HP + defenses
        evs["hp"] = 32
        evs["def"] = 20
        evs["spd"] = 14
    elif bulky and fast:
        # Bulky attacker
        evs["hp"] = 12
        evs["spe"] = 22
        evs["atk" if physical else "spa"] = 32
    elif physical:
        # Physical, not fast, not bulky
        evs["hp"] = 22
        evs["atk"] = 30
        evs["spe"] = 14
    elif special:
        # Special, not fast, not bulky
        evs["hp"] = 22
        evs["spa"] = 30
        evs["spe"] = 14
    else:
        # Support / mixed — HP + defenses + speed
        evs["hp"] = 22
        evs["def"] = 15
        evs["spd"] = 15
        evs["spe"] = 14

    # Safety clamp
    for k in evs:
        evs[k] = min(evs[k], 32)

    return {s: v for s, v in evs.items() if v > 0}

def pick_nature(species):
    ls = _lookup_learnset(species) or {}
    stats = ls.get("baseStats", {})
    if stats.get("spa", 100) > stats.get("atk", 100): return random.choice(["Modest","Timid","Calm","Bold"])
    if stats.get("atk", 100) > stats.get("spa", 100): return random.choice(["Adamant","Jolly","Impish","Careful"])
    return random.choice(NATURES)

def _normalize_mega(species):
    """Convert 'X-Mega' / 'X-Mega-Y' / 'X-Mega-Z' back to base species."""
    for suffix in ["-Mega-Y", "-Mega-X", "-Mega-Z", "-Mega"]:
        if species.endswith(suffix):
            return species[: -len(suffix)]
    return species

def team_to_showdown(species_list):
    # Track which species were Mega forms and normalize them
    was_mega = {}
    normalized = []
    for sp in species_list:
        base = _normalize_mega(sp)
        if base != sp:
            was_mega[base] = True
        normalized.append(base)
    species_list = normalized
    # Verify every species is buildable
    for sp in species_list:
        if _lookup_learnset(sp) is None:
            return None
    used_items = set()
    lines = []
    for sp in species_list:
        if was_mega.get(sp) and sp in MEGA_STONES:
            item = MEGA_STONES[sp]["stone"]
        else:
            item = pick_item(sp, used_items)
        used_items.add(item)
        ability = pick_ability(sp)
        if ability is None: return None
        nature = pick_nature(sp)
        evs = pick_evs(sp)
        moves = pick_moves(sp)
        if len(moves) < 4: return None
        ev_str = " / ".join(f"{v} {k.upper()}" for k, v in evs.items() if v > 0)
        lines.append(f"{sp} @ {item}")
        lines.append(f"Ability: {ability}")
        lines.append("Level: 50")
        lines.append(f"{nature} Nature")
        lines.append(f"EVs: {ev_str}")
        for m in moves: lines.append(f"- {m}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    # Smoke test on 5 random species
    species = random.sample(list(LEARNSETS.keys()), 6)
    print("Test team:")
    print(team_to_showdown(species))
