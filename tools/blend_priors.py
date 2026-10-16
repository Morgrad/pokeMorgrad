"""Blend our tournament-corpus priors with metavgc usage tables.

Usage:
    python tools/scrape_metavgc.py fetch && python tools/scrape_metavgc.py parse
    python tools/blend_priors.py            # writes the files below
    python tools/blend_priors.py --dry-run  # report only

Inputs:  data/species_{build,ability}_priors.corpus.json  (tools/build_ev_priors.py)
         data/scraped/metavgc/species.json                (tools/scrape_metavgc.py)
Outputs: data/species_build_priors.json     blended spreads  (read by src/opp_model.py)
         data/species_ability_priors.json   blended abilities (read by src/opp_model.py)
         data/species_item_priors.json      metavgc item shares, DB-legal only
         data/species_move_usage.json       metavgc move shares, DB-legal only
(species_move_priors.json is the BC pilot's ladder-count mask and is NOT touched.)

Blend rule: count = corpus_count + N0 * metavgc_share, so metavgc acts as a prior worth
N0 teams and our corpus dominates only where it has more than ~N0 teams of evidence.
Rollback: `git checkout pre-blended-priors -- data/` or re-run this script.
"""
import argparse
import difflib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src import regmc_db as DB  # noqa: E402

DATA = REPO / "data"
N0 = 10.0                 # metavgc counts as this many teams of evidence
MAX_SPREADS = 10
ABILITY_TRUST = 0.9       # use a metavgc ability table only if >= this share is DB-legal
STATS = ("hp", "atk", "def", "spa", "spd", "spe")
norm = DB.norm


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def canon_nature(raw: str, natures: set):
    """metavgc nature -> DB nature name (casing, accents, typos like 'Adament'), else None."""
    plain = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode().capitalize()
    if plain in natures:
        return plain
    hit = difflib.get_close_matches(plain, natures, n=1, cutoff=0.75)
    return hit[0] if hit else None


def canon_item(raw: str, sp: dict):
    """metavgc item -> DB item dict. Misspelled mega stones (Excadrillite) resolve to the
    species' own stone (Excadrite)."""
    it = DB.get_item(raw)
    if it or not raw.lower().endswith("ite"):
        return it
    stones = sp.get("megaStones") or (DB.get_species(sp["baseSpecies"]) or {}).get("megaStones", [])
    hit = difflib.get_close_matches(raw, stones, n=1, cutoff=0.8)
    return DB.get_item(hit[0]) if hit else None


def legal_abilities(sp: dict) -> set:
    """Own abilities; a Mega form also accepts its base species' (the paste carries the pre-Mega one)."""
    names = list(sp["abilities"])
    if (sp.get("forme") or "").startswith("Mega"):
        base = DB.get_species(sp["baseSpecies"])
        names += base["abilities"] if base else []
    return {norm(a) for a in names}


def movepool(sp: dict) -> set:
    moves = sp["moves"] or (DB.get_species(sp["baseSpecies"]) or {}).get("moves", [])
    return {norm(m) for m in moves}


def blend_builds(ours: list, mv_builds: list, natures: set, log: dict) -> list:
    counts = defaultdict(float)
    evs_of = {}
    for e in ours:
        key = (e["nature"], tuple(sorted((k, v) for k, v in e["evs"].items() if v > 0)))
        counts[key] += e["count"]
        evs_of[key] = dict(e["evs"])
    valid = []
    for e in mv_builds:
        if "spread" not in e:
            continue                      # the "Other" bucket
        nature = canon_nature(e["name"].split()[0], natures)
        vals = [int(x) for x in e["spread"].split("/")]
        if nature is None or max(vals) > 32 or sum(vals) > 66:
            log["bad_spread"] += 1
            continue
        evs = {s: v for s, v in zip(STATS, vals) if v > 0}
        valid.append(((nature, tuple(sorted(evs.items()))), evs, e["pct"]))
    total = sum(p for _, _, p in valid)
    for key, evs, p in valid:
        counts[key] += N0 * p / total if total > 0 else 0.0
        evs_of.setdefault(key, evs)
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:MAX_SPREADS]
    return [{"evs": evs_of[k], "nature": k[0], "count": round(c, 3)} for k, c in top if c > 0]


def blend_abilities(ours: list, mv_abilities: list, sp: dict, log: dict) -> list:
    legal = legal_abilities(sp)
    display = {norm(a): a for a in sp["abilities"] + ((DB.get_species(sp["baseSpecies"]) or {}).get("abilities", [])
                                                      if (sp.get("forme") or "").startswith("Mega") else [])}
    counts = defaultdict(float)
    for e in ours:
        if norm(e["ability"]) in legal:
            counts[norm(e["ability"])] += e["count"]
        else:
            log["corpus_ability_illegal"] += 1
    listed = [e for e in mv_abilities if e["name"] != "Other" and e["pct"] > 0]
    mass = sum(e["pct"] for e in listed)
    good = [e for e in listed if norm(e["name"]) in legal]
    good_mass = sum(e["pct"] for e in good)
    if mass > 0 and good_mass / mass >= ABILITY_TRUST:
        for e in good:
            counts[norm(e["name"])] += N0 * e["pct"] / good_mass
    elif mass > 0:
        log["ability_distrusted"].append((sp["name"], [(e["name"], e["pct"]) for e in listed[:3]]))
    return [{"ability": display[a], "count": round(c, 3)}
            for a, c in sorted(counts.items(), key=lambda kv: -kv[1]) if c > 0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    dry = ap.parse_args().dry_run

    mv = json.loads((DATA / "scraped" / "metavgc" / "species.json").read_text())
    corpus_b = json.loads((DATA / "species_build_priors.corpus.json").read_text())
    corpus_a = json.loads((DATA / "species_ability_priors.corpus.json").read_text())
    by_slug = {slug(s["name"]): s for s in DB.all_species()}
    natures = {n["name"] for n in DB.all_natures()}
    move_name = {m["id"]: m["name"] for m in DB.all_moves()}
    log = defaultdict(int)
    log["ability_distrusted"] = []
    log["moves_dropped"] = []
    log["items_dropped"] = defaultdict(float)

    builds, abilities, items, moves = {}, {}, {}, {}
    # species-only keys keep their corpus data; "Species @ Item" keys pass through unchanged
    builds.update({k: v for k, v in corpus_b.items() if "@" in k})
    for name in sorted({k for k in corpus_b if "@" not in k} | set(corpus_a)
                       | {s["name"] for slg, s in by_slug.items() if slg in mv and "-tera" not in slg}):
        sp = DB.get_species(name)
        if not sp:
            continue
        v = mv.get(slug(sp["name"]), {})
        b = blend_builds(corpus_b.get(name, []), v.get("builds", []), natures, log)
        if b:
            builds[name] = b
        a = blend_abilities(corpus_a.get(name, []), v.get("abilities", []), sp, log)
        if a:
            abilities[name] = a
        legal_items = []
        for e in v.get("items", []):
            it = canon_item(e["name"], sp)
            if e["name"] == "Other" or e["pct"] <= 0:
                continue
            if it:
                legal_items.append({"item": it["name"], "pct": e["pct"]})
            else:
                log["items_dropped"][e["name"]] += e["pct"]
        if legal_items:
            items[name] = legal_items + [{"item": "__other__", "pct": round(max(0.0, 100 - sum(i["pct"] for i in legal_items)), 2)}]
        pool, kept, dropped = movepool(sp), [], []
        for e in v.get("moves", []):
            if e["name"] == "Other" or e["pct"] <= 0:
                continue
            (kept if norm(e["name"]) in pool else dropped).append(e)
        if kept:
            moves[name] = [{"move": move_name.get(norm(e["name"]), e["name"]), "pct": e["pct"]} for e in kept]
            moves[name].append({"move": "__other__", "pct": round(max(0.0, 100 - sum(e["pct"] for e in kept)), 2)})
        log["moves_dropped"] += [(name, e["name"], e["pct"]) for e in dropped]

    print(f"builds: {len(builds)} keys ({sum('@' not in k for k in builds)} species, was "
          f"{sum('@' not in k for k in corpus_b)}) | abilities: {len(abilities)} (was {len(corpus_a)})")
    print(f"items: {len(items)} species | moves: {len(moves)} species")
    print(f"invalid metavgc spreads dropped: {log['bad_spread']}; illegal corpus abilities dropped: {log['corpus_ability_illegal']}")
    print(f"metavgc ability tables distrusted (<{ABILITY_TRUST:.0%} DB-legal): {len(log['ability_distrusted'])}")
    for n, top in log["ability_distrusted"]:
        print(f"   {n}: {top}")
    print(f"illegal items dropped: {dict(log['items_dropped'])}")
    print(f"moves not in DB movepool dropped: {len(log['moves_dropped'])}")
    for t in log["moves_dropped"][:30]:
        print("   ", t)
    if dry:
        return
    (DATA / "species_build_priors.json").write_text(json.dumps(builds, indent=2))
    (DATA / "species_ability_priors.json").write_text(json.dumps(abilities, indent=2))
    (DATA / "species_item_priors.json").write_text(json.dumps(items, indent=1))
    (DATA / "species_move_usage.json").write_text(json.dumps(moves, indent=1))
    print("written")


if __name__ == "__main__":
    main()
