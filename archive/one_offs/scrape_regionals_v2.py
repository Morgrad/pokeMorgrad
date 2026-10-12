"""
Scrape Limitless VGC regional teams.

Source: https://limitlessvgc.com/tournaments/<id>/teams
Each page has N teams; each team = 6 <div class="pkmn"> inside <div class="teamlist-pokemon">.

Output: ~/project/regional_teams/<tournament>_teamNN.txt in Showdown format.
EVs are inferred (Limitless doesn't publish them).
"""
import os, re, sys, time, urllib.request
from bs4 import BeautifulSoup

TOURNAMENTS = {
    "441": "baltimore",
    "442": "brisbane",
    "443": "frankfurt",
    "444": "recife",
}
OUT_DIR = os.path.expanduser("~/project/regional_teams")
os.makedirs(OUT_DIR, exist_ok=True)

# Move category lookup (from regmc_db) — used for EV heuristic
sys.path.insert(0, os.path.expanduser("~/project"))
import regmc_db as DB

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', errors='replace')

def clean(s):
    if s is None:
        return ""
    return re.sub(r'^(Ability:\s*|.*?Nature$)', '', s).strip() if False else s.strip()

def parse_ability(text):
    return text.replace("Ability:", "").strip() if text else ""

def parse_nature(text):
    return text.replace("Nature", "").strip() if text else ""

def evs_for_moves(moves):
    """Infer EV spread from move categories."""
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
    """Parse a .teamlist-pokemon container into a team string."""
    mons = container.find_all("div", class_="pkmn")
    if len(mons) != 6:
        return None
    lines = []
    for p in mons:
        name_el = p.find("div", class_="name")
        item_el = p.find("div", class_="item")
        abil_el = p.find("div", class_="ability")
        nat_el = p.find("div", class_="nature")
        moves_el = p.find("ul", class_="moves")

        species = name_el.get_text(strip=True) if name_el else ""
        item = item_el.get_text(strip=True) if item_el else "Leftovers"
        ability = parse_ability(abil_el.get_text(strip=True)) if abil_el else "Pressure"
        nature_listed = parse_nature(nat_el.get_text(strip=True)) if nat_el else None
        moves = [li.get_text(strip=True) for li in moves_el.find_all("li")] if moves_el else []

        if not species or not moves:
            return None

        # EVs inferred from move categories; ignore Limitless-published nature
        # (they list a nature but we don't trust it since EVs aren't shown;
        #  using our own heuristic keeps the team internally consistent)
        ev_str, nat_infer = evs_for_moves(moves)

        lines.append(f"{species} @ {item}")
        lines.append(f"Ability: {ability}")
        lines.append("Level: 50")
        lines.append(f"{nat_infer} Nature")
        lines.append(f"EVs: {ev_str}")
        for mv in moves:
            lines.append(f"- {mv}")
        lines.append("")

    return "\n".join(lines)

def main():
    total_saved = 0
    total_skipped = 0

    for tid, shortname in TOURNAMENTS.items():
        url = f"https://limitlessvgc.com/tournaments/{tid}/teams"
        print(f"Fetching {shortname} ({tid})...")
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        containers = soup.find_all("div", class_="teamlist-pokemon")
        print(f"  Found {len(containers)} team containers")

        saved_here = 0
        for i, c in enumerate(containers):
            team_str = parse_team(c)
            if not team_str:
                total_skipped += 1
                continue
            fname = f"{shortname}_{i+1:02d}.txt"
            with open(os.path.join(OUT_DIR, fname), "w") as f:
                f.write(team_str)
            saved_here += 1
            total_saved += 1
        print(f"  Saved {saved_here}")
        time.sleep(0.3)

    print(f"\nTotal saved: {total_saved}, skipped: {total_skipped}")
    print(f"Output: {OUT_DIR}")

if __name__ == "__main__":
    main()
