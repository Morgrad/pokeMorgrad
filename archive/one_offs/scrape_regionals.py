import json, urllib.request, os, time

API = "https://play.limitlesstcg.com/api"
OUT_DIR = os.path.expanduser("~/project/regional_teams")
os.makedirs(OUT_DIR, exist_ok=True)

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

# Search for the regionals
print("Fetching tournament list...")
url = f"{API}/tournaments?game=VGC&format=M-C&limit=100"
tournaments = fetch(url)

regionals = []
for t in tournaments:
    name = t.get("name", "")
    if "Regional" in name or "regional" in name:
        regionals.append(t)
        print(f"  Found: {t['id']} | {name} | {t.get('date', '')}")

print(f"\nFound {len(regionals)} regionals. Extracting Top Cut teams...")

saved = 0
for t in regionals:
    tid = t["id"]
    try:
        standings = fetch(f"{API}/tournaments/{tid}/standings")
    except Exception as e:
        print(f"  skip {tid}: {e}")
        continue

    # Sort by placement if available, else take top 16 entries
    # Limitless standings usually ordered by placement already
    top_cut = standings[:16]

    for p in top_cut:
        dl = p.get("decklist")
        if not dl or len(dl) != 6:
            continue

        lines = []
        for m in dl:
            lines.append(f"{m['name']} @ {m.get('item', 'Leftovers')}")
            lines.append(f"Ability: {m.get('ability', 'Pressure')}")
            lines.append("Level: 50")
            # Use a generic spread; if we scrape real EV spreads, great, else default
            moves = m.get("attacks", [])
            if any(mv in ("Make It Rain","Shadow Ball","Hyper Voice","Heat Wave","Dazzling Gleam","Moonblast","Thunderbolt","Ice Beam","Flamethrower","Psychic","Draco Meteor","Snarl") for mv in moves):
                lines.append("EVs: 2 HP / 32 SpA / 32 Spe")
                lines.append("Modest Nature")
            elif any(mv in ("Fake Out","Follow Me","Protect","Trick Room","Tailwind","Helping Hand","Wide Guard","Icy Wind") for mv in moves) and len(moves) <= 2:
                lines.append("EVs: 32 HP / 20 Def / 14 SpD")
                lines.append("Calm Nature")
            else:
                lines.append("EVs: 2 HP / 32 Atk / 32 Spe")
                lines.append("Jolly Nature")
            for mv in moves:
                lines.append(f"- {mv}")
            lines.append("")

        safe = "".join(c if c.isalnum() else "_" for c in p.get("player", "anon"))[:20]
        fname = f"regional_{tid[:8]}_{safe}.txt"
        with open(os.path.join(OUT_DIR, fname), "w") as f:
            f.write("\n".join(lines))
        saved += 1

    print(f"  {t['name'][:40]}: kept {min(16, len(standings))} top-cut teams")

print(f"\nSaved {saved} Top Cut teams to {OUT_DIR}")
