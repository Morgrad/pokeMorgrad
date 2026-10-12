# Reg M-C safe defaults — alphabetized, using only items/moves confirmed
# from the user's validated team and parsed replay usage data.

DEFAULT_SETS = {
    "Aerodactyl":       ("Unnerve",       "Focus Sash",    "Jolly",   {"hp": 2,  "atk": 32, "spe": 32}, ["Rock Slide", "Dual Wingbeat", "Tailwind", "Protect"]),
    "Arcanine-Hisui":   ("Rock Head",     "Charcoal",      "Adamant", {"hp": 2,  "atk": 32, "spe": 32}, ["Flare Blitz", "Head Smash", "Rock Slide", "Extreme Speed"]),
    "Archaludon":       ("Stamina",       "Leftovers",     "Modest",  {"hp": 32, "spa": 32, "spd": 2},  ["Electro Shot", "Flash Cannon", "Dragon Pulse", "Protect"]),
    "Basculegion":      ("Adaptability",  "Mystic Water",  "Adamant", {"hp": 2,  "atk": 32, "spe": 32}, ["Wave Crash", "Last Respects", "Aqua Jet", "Protect"]),
    "Blastoise":        ("Torrent",       "Blastoisinite", "Modest",  {"hp": 32, "spa": 32, "spd": 2},  ["Water Pulse", "Aura Sphere", "Dark Pulse", "Protect"]),
    "Charizard":        ("Blaze",         "Charizardite Y","Timid",   {"hp": 2,  "spa": 32, "spe": 32}, ["Heat Wave", "Weather Ball", "Solar Beam", "Protect"]),
    "Corviknight":      ("Mirror Armor",  "Leftovers",     "Impish",  {"hp": 32, "def": 20, "spd": 14}, ["Body Press", "Iron Head", "Tailwind", "Protect"]),
    "Delphox":          ("Blaze",         "Focus Sash",    "Timid",   {"hp": 2,  "spa": 32, "spe": 32}, ["Heat Wave", "Psychic", "Shadow Ball", "Protect"]),
    "Dragonite":        ("Multiscale",    "Lum Berry",     "Adamant", {"hp": 2,  "atk": 32, "spe": 32}, ["Extreme Speed", "Dragon Claw", "Ice Spinner", "Protect"]),
    "Excadrill":        ("Sand Rush",     "Focus Sash",    "Jolly",   {"hp": 2,  "atk": 32, "spe": 32}, ["Iron Head", "Earthquake", "Rock Slide", "Protect"]),
    "Farigiraf":        ("Armor Tail",    "Sitrus Berry",  "Relaxed", {"hp": 32, "def": 20, "spd": 14}, ["Trick Room", "Psychic", "Foul Play", "Helping Hand"]),
    "Floette-Eternal":  ("Flower Veil",   "Leftovers",     "Calm",    {"hp": 32, "spd": 20, "def": 14}, ["Moonblast", "Dazzling Gleam", "Calm Mind", "Protect"]),
    "Froslass":         ("Cursed Body",   "Focus Sash",    "Timid",   {"hp": 2,  "spa": 32, "spe": 32}, ["Blizzard", "Shadow Ball", "Icy Wind", "Protect"]),
    "Garchomp":         ("Rough Skin",    "Rocky Helmet",  "Jolly",   {"hp": 2,  "atk": 32, "spe": 32}, ["Stomping Tantrum", "Dragon Claw", "Rock Slide", "Protect"]),
    "Gholdengo":        ("Good as Gold",  "Life Orb",      "Modest",  {"hp": 2,  "spa": 32, "spe": 32}, ["Make It Rain", "Shadow Ball", "Nasty Plot", "Protect"]),
    "Glimmora":         ("Toxic Debris",  "Focus Sash",    "Timid",   {"hp": 2,  "spa": 32, "spe": 32}, ["Power Gem", "Sludge Wave", "Earth Power", "Spiky Shield"]),
    "Golisopod":        ("Emergency Exit","Leftovers",     "Adamant", {"hp": 32, "atk": 32, "def": 2},  ["First Impression", "Liquidation", "Leech Life", "Sucker Punch"]),
    "Golurk":           ("Iron Fist",     "Leftovers",     "Adamant", {"hp": 32, "atk": 32, "spd": 2},  ["Earthquake", "Poltergeist", "Close Combat", "Heavy Slam"]),
    "Grimmsnarl":       ("Prankster",     "Light Clay",    "Careful", {"hp": 32, "spd": 20, "def": 14}, ["Spirit Break", "Light Screen", "Reflect", "Protect"]),
    "Indeedee":         ("Psychic Surge", "Sitrus Berry",  "Calm",    {"hp": 32, "spd": 20, "def": 14}, ["Protect", "Helping Hand", "Psychic", "Trick Room"]),
    "Indeedee-F":       ("Psychic Surge", "Sitrus Berry",  "Calm",    {"hp": 32, "spd": 20, "def": 14}, ["Protect", "Helping Hand", "Psychic", "Trick Room"]),
    "Incineroar":       ("Intimidate",    "Sitrus Berry",  "Impish",  {"hp": 32, "def": 23, "spd": 11}, ["Fake Out", "Flare Blitz", "Throat Chop", "Parting Shot"]),
    "Kingambit":        ("Defiant",       "Black Glasses", "Adamant", {"hp": 32, "atk": 32, "spe": 2},  ["Kowtow Cleave", "Sucker Punch", "Iron Head", "Protect"]),
    "Kommo-o":          ("Soundproof",    "Leftovers",     "Modest",  {"hp": 2,  "spa": 32, "spe": 32}, ["Clanging Scales", "Aura Sphere", "Clangorous Soul", "Protect"]),
    "Meowstic-F":       ("Competitive",   "Focus Sash",    "Timid",   {"hp": 32, "spa": 20, "spe": 14}, ["Psychic", "Fake Out", "Helping Hand", "Protect"]),
    "Milotic":          ("Competitive",   "Leftovers",     "Bold",    {"hp": 32, "def": 20, "spd": 14}, ["Scald", "Icy Wind", "Recover", "Protect"]),
    "Ninetales-Alola":  ("Snow Warning",  "Light Clay",    "Timid",   {"hp": 32, "spa": 20, "spe": 14}, ["Blizzard", "Moonblast", "Aurora Veil", "Freeze-Dry"]),
    "Pelipper":         ("Drizzle",       "Focus Sash",    "Modest",  {"hp": 2,  "spa": 32, "spe": 32}, ["Hurricane", "Weather Ball", "Tailwind", "Protect"]),
    "Politoed":         ("Drizzle",       "Sitrus Berry",  "Calm",    {"hp": 32, "spd": 20, "def": 14}, ["Muddy Water", "Icy Wind", "Helping Hand", "Protect"]),
    "Raichu":           ("Lightning Rod", "Raichunite Y",  "Timid",   {"hp": 2,  "spa": 32, "spe": 32}, ["Zap Cannon", "Focus Blast", "Fake Out", "Protect"]),
    "Rillaboom":        ("Grassy Surge",  "Miracle Seed",  "Adamant", {"hp": 2,  "atk": 32, "spe": 32}, ["Grassy Glide", "Wood Hammer", "Fake Out", "High Horsepower"]),
    "Salamence":        ("Intimidate",    "Salamencite",   "Naive",   {"hp": 1,  "atk": 21, "spa": 15, "spe": 29}, ["Double-Edge", "Dragon Claw", "Tailwind", "Protect"]),
    "Sinistcha":        ("Hospitality",   "Sitrus Berry",  "Calm",    {"hp": 32, "spd": 20, "def": 14}, ["Matcha Gotcha", "Shadow Ball", "Trick Room", "Protect"]),
    "Sneasler":         ("Poison Touch",  "Focus Sash",    "Jolly",   {"hp": 2,  "atk": 32, "spe": 32}, ["Close Combat", "Dire Claw", "Fake Out", "Throat Chop"]),
    "Staraptor":        ("Intimidate",    "Choice Scarf",  "Jolly",   {"hp": 2,  "atk": 32, "spe": 32}, ["Brave Bird", "Close Combat", "U-turn", "Double-Edge"]),
    "Sylveon":          ("Pixilate",      "Fairy Feather", "Modest",  {"hp": 32, "spa": 32, "spd": 2},  ["Hyper Voice", "Moonblast", "Quick Attack", "Protect"]),
    "Torkoal":          ("Drought",       "Charcoal",      "Quiet",   {"hp": 32, "spa": 32, "spd": 2},  ["Eruption", "Heat Wave", "Solar Beam", "Protect"]),
    "Typhlosion-Hisui": ("Frisk",         "Life Orb",      "Timid",   {"hp": 2,  "spa": 32, "spe": 32}, ["Eruption", "Shadow Ball", "Heat Wave", "Focus Blast"]),
    "Tyranitar":        ("Sand Stream",   "Leftovers",     "Adamant", {"hp": 32, "atk": 32, "def": 2},  ["Rock Slide", "Crunch", "Low Kick", "Protect"]),
    "Umbreon":          ("Inner Focus",   "Leftovers",     "Bold",    {"hp": 32, "def": 20, "spd": 14}, ["Foul Play", "Snarl", "Yawn", "Taunt"]),
    "Venusaur":         ("Chlorophyll",   "Focus Sash",    "Modest",  {"hp": 2,  "spa": 32, "spe": 32}, ["Sludge Bomb", "Earth Power", "Sleep Powder", "Protect"]),
    "Volcarona":        ("Flame Body",    "Sitrus Berry",  "Timid",   {"hp": 2,  "spa": 32, "spe": 32}, ["Heat Wave", "Bug Buzz", "Quiver Dance", "Protect"]),
    "Whimsicott":       ("Prankster",     "Focus Sash",    "Timid",   {"hp": 2,  "spa": 32, "spe": 32}, ["Moonblast", "Tailwind", "Encore", "Protect"]),
}

GENERIC_FALLBACK = ("Pressure", "Leftovers", "Adamant",
                    {"hp": 32, "atk": 20, "spe": 14},
                    ["Protect", "Rock Slide", "Crunch", "Iron Head"])

# Alternative items to rotate in when a team has duplicate items (Item Clause).
# Only items we've confirmed exist in Reg M-C (Safety Goggles was rejected).
ITEM_ALTERNATIVES = ["Leftovers", "Sitrus Berry", "Focus Sash", "Life Orb",
                     "Rocky Helmet", "Miracle Seed", "Lum Berry", "Charcoal",
                     "Black Glasses", "Mystic Water", "Fairy Feather", "Light Clay"]


def species_to_team_string(species_list):
    """Convert a species list to a valid Showdown team string.
    Ensures no duplicate items (Item Clause)."""
    used_items = set()
    lines = []
    for species in species_list:
        ability, item, nature, evs, moves = DEFAULT_SETS.get(species, GENERIC_FALLBACK)

        # Item Clause: if item already used, rotate to an available one
        if item in used_items:
            for alt in ITEM_ALTERNATIVES:
                if alt not in used_items:
                    item = alt
                    break
        used_items.add(item)

        lines.append(f"{species} @ {item}")
        lines.append(f"Ability: {ability}")
        lines.append(f"Level: 50")
        lines.append(f"{nature} Nature")
        ev_parts = [f"{v} {k.upper()}" for k, v in evs.items() if v > 0]
        lines.append(f"EVs: {' / '.join(ev_parts)}")
        for m in moves:
            lines.append(f"- {m}")
        lines.append("")
    return "\n".join(lines)
