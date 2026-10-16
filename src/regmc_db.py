"""
Canonical data layer for the Reg M-C format.

Loads regmc_db.json (built from the Showdown format dex) and provides:
- Raw data access (species, moves, abilities, items, natures, types)
- validate_team(text) -> (ok, errors)
- Helpers for team generation

This is THE source of truth. Nothing else parses format data.
"""
import json
import os
import re
from functools import lru_cache

from src.paths import data_path

DB_PATH = data_path("regmc_db.json")


def norm(s):
    """Normalize a name to Showdown id format."""
    if s is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ============================================================
# Core loading
# ============================================================

@lru_cache(maxsize=1)
def load_db():
    with open(DB_PATH) as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _indexes():
    """Build name/id lookup indexes for fast access."""
    db = load_db()

    species_by_name = {s["name"]: s for s in db["species"].values()}
    species_by_id = {s["id"]: s for s in db["species"].values()}

    # Items stored as dict already, but expose by name and id
    items_by_name = db["items"]
    items_by_id = {norm(i["name"]): i for i in items_by_name.values()}

    moves_by_name = db["moves"]
    moves_by_id = {norm(m["name"]): m for m in moves_by_name.values()}

    abilities_by_name = db["abilities"]
    abilities_by_id = {norm(a["name"]): a for a in abilities_by_name.values()}

    return {
        "species_by_name": species_by_name,
        "species_by_id": species_by_id,
        "items_by_name": items_by_name,
        "items_by_id": items_by_id,
        "moves_by_name": moves_by_name,
        "moves_by_id": moves_by_id,
        "abilities_by_name": abilities_by_name,
        "abilities_by_id": abilities_by_id,
    }


# ============================================================
# Raw accessors
# ============================================================

def all_species():
    """All legal species as list of dicts (includes formes)."""
    return list(load_db()["species"].values())


def all_species_base():
    """Base species only (forme is null). Use for team building."""
    return [s for s in all_species() if s["forme"] is None]


def all_items():
    return list(load_db()["items"].values())


def all_moves():
    return list(load_db()["moves"].values())


def all_abilities():
    return list(load_db()["abilities"].values())


def all_natures():
    return list(load_db()["natures"].values())


def get_species(name):
    """Return species dict by name or id. None if not found."""
    if name is None:
        return None
    idx = _indexes()
    if name in idx["species_by_name"]:
        return idx["species_by_name"][name]
    nid = norm(name)
    if nid in idx["species_by_id"]:
        return idx["species_by_id"][nid]
    return None


def normalize_species_name(raw):
    """
    Canonicalize a species string from a Showdown team paste.

    Handles three artifacts common in tournament-sourced pastes:
      1. Trailing gender marker on a cosmetic species:
             "Hatterene (F)"     -> "Hatterene"
      2. Gender marker on a form-suffixed species (marker redundant):
             "Indeedee-F (F)"    -> "Indeedee-F"
             "Basculegion (M)"   -> "Basculegion"
      3. Nickname prefix:
             "Aang (Staraptor)"  -> "Staraptor"

    Returns the raw string unchanged if nothing resolves; callers should
    log unresolved names and skip.
    """
    if not raw:
        return raw
    s = raw.strip()
    if not s:
        return s

    sp = get_species(s)
    if sp:
        return sp["name"]

    # Trailing "(M)"/"(F)".
    m = re.match(r"^(.*?)\s*\((M|F)\)\s*$", s)
    if m:
        base, g = m.group(1).strip(), m.group(2)
        sp = get_species(f"{base}-{g}") or get_species(base)
        if sp:
            return sp["name"]
        s = base  # fall through: "Nickname (Species) (M)"

    # Nickname: "<nick> (<species>)".
    m = re.match(r"^.*?\(([^()]+)\)\s*$", s)
    if m:
        sp = get_species(m.group(1).strip())
        if sp:
            return sp["name"]

    return raw


def get_item(name):
    if name is None:
        return None
    idx = _indexes()
    if name in idx["items_by_name"]:
        return idx["items_by_name"][name]
    return idx["items_by_id"].get(norm(name))


def get_move(name):
    if name is None:
        return None
    idx = _indexes()
    if name in idx["moves_by_name"]:
        return idx["moves_by_name"][name]
    return idx["moves_by_id"].get(norm(name))


def get_ability(name):
    if name is None:
        return None
    idx = _indexes()
    if name in idx["abilities_by_name"]:
        return idx["abilities_by_name"][name]
    return idx["abilities_by_id"].get(norm(name))


def is_legal_item(name):
    return get_item(name) is not None


def is_legal_move(name):
    return get_move(name) is not None


def is_legal_ability(name):
    return get_ability(name) is not None


def mega_stones_for(species):
    """Return list of mega stone item names for a species (by name or dict)."""
    if isinstance(species, str):
        sp = get_species(species)
    else:
        sp = species
    return sp["megaStones"] if sp else []


def species_can_learn(species, move):
    """True if species can learn move (normalized comparison)."""
    sp = get_species(species) if isinstance(species, str) else species
    if not sp:
        return False
    target = norm(move)
    return any(norm(m) == target for m in sp["moves"])


def species_has_ability(species, ability):
    sp = get_species(species) if isinstance(species, str) else species
    if not sp:
        return False
    target = norm(ability)
    return any(norm(a) == target for a in sp["abilities"])


def moves_by_category(species, category):
    """Return legal moves for species filtered by category (Physical/Special/Status)."""
    sp = get_species(species) if isinstance(species, str) else species
    if not sp:
        return []
    out = []
    for mname in sp["moves"]:
        mv = get_move(mname)
        if mv and mv["category"] == category:
            out.append(mname)
    return out


# ============================================================
# Team parsing and validation
# ============================================================

def parse_team(text):
    """
    Parse a Showdown team string into a list of mon dicts:
      {species, item, ability, nature, evs, moves}
    """
    if not text or not text.strip():
        return []
    blocks = re.split(r"\n\s*\n", text.strip())
    mons = []
    for b in blocks:
        lines = [ln.rstrip() for ln in b.split("\n") if ln.strip()]
        if not lines or "@" not in lines[0]:
            continue
        head = lines[0]
        species, item = head.split("@", 1)
        mon = {
            "species": species.strip(),
            "item": item.strip(),
            "ability": None,
            "nature": None,
            "evs": {},
            "moves": [],
        }
        for ln in lines[1:]:
            ln = ln.strip()
            if ln.startswith("Ability:"):
                mon["ability"] = ln.split(":", 1)[1].strip()
            elif ln.endswith("Nature"):
                mon["nature"] = ln.replace("Nature", "").strip()
            elif ln.startswith("EVs:"):
                for part in ln[4:].split("/"):
                    part = part.strip()
                    m = re.match(r"(\d+)\s+(\w+)", part)
                    if m:
                        mon["evs"][m.group(2).lower()] = int(m.group(1))
            elif ln.startswith("- "):
                mon["moves"].append(ln[2:].strip())
        mons.append(mon)
    return mons


def validate_team(text):
    """
    Validate a team string against the DB.
    Returns (ok: bool, errors: list[str]).
    """
    errors = []
    mons = parse_team(text)
    if len(mons) != 6:
        return False, [f"expected 6 mons, got {len(mons)}"]

    # Species Clause: 6 unique base species
    base_species = []
    for m in mons:
        sp = get_species(m["species"])
        if sp is None:
            errors.append(f"unknown species: {m['species']}")
            continue
        base_species.append(sp["baseSpecies"])
    if len(set(base_species)) != len(base_species):
        errors.append("species clause violated (duplicate base species)")

    # Item Clause: 6 unique items
    items = [m["item"] for m in mons if m["item"]]
    if len(set(items)) != len(items):
        dups = [i for i in set(items) if items.count(i) > 1]
        errors.append(f"item clause violated (duplicate: {dups})")

    # Per-mon checks
    for m in mons:
        sp = get_species(m["species"])
        if sp is None:
            continue

        # Item legal
        if m["item"] and not is_legal_item(m["item"]):
            errors.append(f"{m['species']}: illegal item '{m['item']}'")

        # Ability legal for this species (normalized)
        if m["ability"] and not species_has_ability(sp, m["ability"]):
            errors.append(f"{m['species']}: illegal ability '{m['ability']}'")

        # 4 moves exactly
        if len(m["moves"]) != 4:
            errors.append(f"{m['species']}: expected 4 moves, got {len(m['moves'])}")

        # Duplicate moves
        if len(set(norm(x) for x in m["moves"])) != len(m["moves"]):
            errors.append(f"{m['species']}: duplicate moves")

        # Moves learnable
        for mv in m["moves"]:
            if not species_can_learn(sp, mv):
                errors.append(f"{m['species']}: cannot learn '{mv}'")

        # EVs: max 32 per stat, max 66 total
        total_evs = sum(m["evs"].values())
        if total_evs > 66:
            errors.append(f"{m['species']}: EVs total {total_evs} > 66")
        for stat, val in m["evs"].items():
            if val > 32:
                errors.append(f"{m['species']}: {stat} {val} > 32")

    return len(errors) == 0, errors


# ============================================================
# Smoke test
# ============================================================

if __name__ == "__main__":
    db = load_db()
    print(f"DB: {db['meta']['formatName']}")
    print(f"  mod: {db['meta']['mod']}")
    print(f"  built: {db['meta']['built']}")
    print()
    print(f"  species (all): {len(db['species'])}")
    print(f"  species (base): {len(all_species_base())}")
    print(f"  items: {len(db['items'])}")
    print(f"  moves: {len(db['moves'])}")
    print(f"  abilities: {len(db['abilities'])}")
    print(f"  natures: {len(db['natures'])}")
    print(f"  types: {len(db['types'])}")
    print()

    # Mega stone coverage
    base = all_species_base()
    with_mega = [s for s in base if s["megaStones"]]
    print(f"Base species with mega stones: {len(with_mega)}")
    print(f"  sample: {[(s['name'], s['megaStones'][0]) for s in with_mega[:5]]}")
    print()

    # Baseline team validation
    baseline_path = data_path("baseline_team.txt")
    if os.path.exists(baseline_path):
        text = open(baseline_path).read()
        ok, errs = validate_team(text)
        print(f"Baseline team: {'PASS' if ok else 'FAIL'}")
        for e in errs:
            print(f"  - {e}")
