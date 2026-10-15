"""Scrape a Limitless VGC tournament's team lists into data/regional_teams/.

Usage:
    python3 tools/scrape_tournament.py <tournament_id> <shortname>
    python3 tools/scrape_tournament.py 445 louisville

Writes <shortname>_NN.txt files in Showdown format. Does NOT touch
pool_split.json — run tools/extend_train_pool.py afterward to add the new
files to the training pool.

Source format: https://limitlessvgc.com/tournaments/<id>/teams
Each page has N teams; each team = 6 <div class="pkmn"> inside
<div class="teamlist-pokemon">.
"""
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

REPO = Path.home() / "project"
sys.path.insert(0, str(REPO))
from src import regmc_db as DB

OUT_DIR = REPO / "data" / "regional_teams"
OUT_DIR.mkdir(parents=True, exist_ok=True)

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

TOURNAMENT_ID = sys.argv[1]
SHORTNAME = sys.argv[2]
URL = f"https://limitlessvgc.com/tournaments/{TOURNAMENT_ID}/teams"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_ability(text):
    return text.replace("Ability:", "").strip() if text else ""


def parse_nature(text):
    return text.replace("Nature", "").strip() if text else ""


def evs_for_moves(moves):
    cats = []
    for mv in moves:
        info = DB.get_move(mv)
        if info:
            cats.append(info["category"])
    n_phys = cats.count("Physical")
    n_spec = cats.count("Special")
    if n_phys == 0 and n_spec == 0:
        return "32 HP / 20 Def / 14 SpD", "Calm"
    if n_phys > n_spec:
        return "2 HP / 32 Atk / 32 Spe", "Jolly"
    if n_spec > n_phys:
        return "2 HP / 32 SpA / 32 Spe", "Modest"
    return "32 HP / 20 Def / 14 SpD", "Calm"


def parse_team(container):
    """Parse one .teamlist-pokemon container into a Showdown team string."""
    mons = container.select(".pkmn")
    if len(mons) != 6:
        return None
    lines = []
    for mon in mons:
        # Species + item
        name_el = mon.select_one(".pkmn-name")
        item_el = mon.select_one(".pkmn-item")
        if not name_el:
            return None
        species = name_el.get_text(strip=True)
        item = item_el.get_text(strip=True) if item_el else "Leftovers"
        item = re.sub(r"^@\s*", "", item).strip() or "Leftovers"

        ability_el = mon.select_one(".pkmn-ability")
        ability = parse_ability(ability_el.get_text(strip=True)) if ability_el else ""

        nature_el = mon.select_one(".pkmn-nature")
        nature = parse_nature(nature_el.get_text(strip=True)) if nature_el else ""

        moves = [m.get_text(strip=True) for m in mon.select(".pkmn-move")]
        if not moves:
            return None

        evs, default_nature = evs_for_moves(moves)

        lines.append(f"{species} @ {item}")
        lines.append(f"Ability: {ability or 'Pressure'}")
        lines.append("Level: 50")
        lines.append(f"{nature or default_nature} Nature")
        lines.append(f"EVs: {evs}")
        for mv in moves[:4]:
            lines.append(f"- {mv}")
        lines.append("")
    return "\n".join(lines)


def main():
    print(f"Fetching {SHORTNAME} ({TOURNAMENT_ID})...")
    html = fetch(URL)
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select(".teamlist-pokemon")
    print(f"  Found {len(containers)} team containers")

    saved = 0
    skipped = 0
    for i, c in enumerate(containers):
        team_str = parse_team(c)
        if not team_str:
            skipped += 1
            continue
        fname = f"{SHORTNAME}_{i + 1:02d}.txt"
        with open(OUT_DIR / fname, "w") as f:
            f.write(team_str)
        saved += 1
    print(f"  Saved {saved}")
    print(f"\nTotal saved: {saved}, skipped: {skipped}")
    print(f"Output: {OUT_DIR}")
    print(f"\nNext: python3 tools/normalize_tournament.py {SHORTNAME}")


if __name__ == "__main__":
    main()
