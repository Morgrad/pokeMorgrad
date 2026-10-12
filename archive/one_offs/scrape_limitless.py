"""
Scrape real Reg M-C team lists from the Limitless API.
Docs: https://docs.limitlesstcg.com/developer.html  (no key required)
"""
import json, os, sys, time, urllib.request

API = "https://play.limitlesstcg.com/api"
REG = "M-C"
MAX_TOURNAMENTS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
OUT_DIR = os.path.expanduser("~/project/real_teams")
os.makedirs(OUT_DIR, exist_ok=True)

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

url = f"{API}/tournaments?game=VGC&format={REG}&limit={MAX_TOURNAMENTS}"
tournaments = fetch(url)
print(f"Found {len(tournaments)} tournaments")

saved = 0
seen = set()
for t in tournaments:
    tid = t["id"]
    try:
        standings = fetch(f"{API}/tournaments/{tid}/standings")
    except Exception as e:
        print(f"  skip {tid}: {e}")
        continue

    for p in standings:
        dl = p.get("decklist")
        if not dl or len(dl) != 6:
            continue
        key = json.dumps(
            [[m["name"], m.get("item"), tuple(m.get("attacks", []))] for m in dl],
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)

        lines = []
        for m in dl:
            lines.append(f"{m['name']} @ {m.get('item', 'Leftovers')}")
            lines.append(f"Ability: {m.get('ability', 'Pressure')}")
            lines.append("Level: 50")
            moves = m.get("attacks", [])
            # Limitless doesn't publish EVs, so we use sensible defaults
            if any(mv in ("Make It Rain","Shadow Ball","Hyper Voice","Heat Wave",
                          "Dazzling Gleam","Moonblast","Thunderbolt","Ice Beam",
                          "Flamethrower","Psychic","Draco Meteor","Snarl") for mv in moves):
                lines.append("EVs: 2 HP / 32 SpA / 32 Spe")
                lines.append("Modest Nature")
            elif (any(mv in ("Fake Out","Follow Me","Protect","Trick Room",
                             "Tailwind","Helping Hand","Wide Guard","Icy Wind")
                      for mv in moves) and len(moves) <= 2):
                lines.append("EVs: 32 HP / 20 Def / 14 SpD")
                lines.append("Calm Nature")
            else:
                lines.append("EVs: 2 HP / 32 Atk / 32 Spe")
                lines.append("Jolly Nature")
            for mv in moves:
                lines.append(f"- {mv}")
            lines.append("")

        safe = "".join(c if c.isalnum() else "_" for c in p.get("player", "anon"))[:20]
        fname = f"{tid[:8]}_{safe}.txt"
        with open(os.path.join(OUT_DIR, fname), "w") as f:
            f.write("\n".join(lines))
        saved += 1

    print(f"  {t['name'][:40]:40s} → total {saved} teams")
    time.sleep(0.3)

print(f"\nSaved {saved} unique teams to {OUT_DIR}")
