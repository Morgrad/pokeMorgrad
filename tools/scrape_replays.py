"""Scrape Pokemon Showdown replays for our format."""
import urllib.request, urllib.error, json, os, sys, time, random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.paths import data_path

UA = "Mozilla/5.0 (compatible; research-scraper/1.0)"
FORMAT = "gen9championsvgc2026regmc"
RATING_FLOOR = int(sys.argv[1]) if len(sys.argv) > 1 else 1600
MAX_PAGES = int(sys.argv[2]) if len(sys.argv) > 2 else 200
SLEEP = 0.25

META_DIR = data_path("showdown_replays_meta")
REPLAY_DIR = data_path("showdown_replays")
os.makedirs(META_DIR, exist_ok=True)
os.makedirs(REPLAY_DIR, exist_ok=True)


def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


meta_path = os.path.join(META_DIR, "index.json")

if os.path.exists(meta_path):
    all_meta = json.load(open(meta_path))
    seen_ids = {m["id"] for m in all_meta}
    start_page = (len(all_meta) // 51) + 1
    print(f"Resumed: {len(all_meta)} entries, starting page {start_page}")
else:
    all_meta = []
    seen_ids = set()
    start_page = 1

print(f"PHASE 1: metadata (format={FORMAT}, max_pages={MAX_PAGES})")
empty_pages = 0

for page in range(start_page, start_page + MAX_PAGES):
    url = f"https://replay.pokemonshowdown.com/search.json?format={FORMAT}&sort=rating&page={page}"
    try:
        entries = fetch_json(url)
    except Exception as e:
        print(f"  page {page}: error {e}")
        time.sleep(2)
        continue

    if not isinstance(entries, list):
        print(f"  page {page}: unexpected response")
        break

    if not entries:
        empty_pages += 1
        if empty_pages >= 3:
            print(f"  page {page}: 3 empty pages, stopping")
            break
        continue

    empty_pages = 0
    new = 0
    for e in entries:
        rid = e.get("id")
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        all_meta.append({
            "id": rid,
            "rating": e.get("rating"),
            "uploadtime": e.get("uploadtime"),
            "players": e.get("players"),
        })
        new += 1

    if page % 5 == 0 or new < 50:
        print(f"  page {page}: +{new} new, total {len(all_meta)}")

    if page % 10 == 0:
        json.dump(all_meta, open(meta_path, "w"), indent=1)

    if len(entries) < 51:
        print(f"  page {page}: last page ({len(entries)} entries)")
        break

    time.sleep(SLEEP)

json.dump(all_meta, open(meta_path, "w"), indent=1)
print(f"Metadata total: {len(all_meta)}")

ratings = [m["rating"] for m in all_meta if isinstance(m["rating"], (int, float))]
print(f"With rating: {len(ratings)}")
if ratings:
    print(f"  min={min(ratings)} max={max(ratings)} median={sorted(ratings)[len(ratings)//2]}")
    print(f"  above {RATING_FLOOR}: {sum(1 for r in ratings if r >= RATING_FLOOR)}")

qualified = [m for m in all_meta
             if isinstance(m["rating"], (int, float)) and m["rating"] >= RATING_FLOOR]
unrated = [m for m in all_meta if m["rating"] is None]
qualified += unrated[:500]

print(f"\nPHASE 2: fetch {len(qualified)} replays (rating >= {RATING_FLOOR})")

fetched = 0
skipped = 0
failed = 0
t0 = time.time()

for i, m in enumerate(qualified, 1):
    rid = m["id"]
    out_path = os.path.join(REPLAY_DIR, f"{rid}.json")
    if os.path.exists(out_path):
        skipped += 1
        continue
    url = f"https://replay.pokemonshowdown.com/{rid}.json"
    try:
        data = fetch_json(url)
        with open(out_path, "w") as f:
            json.dump(data, f)
        with open(os.path.join(REPLAY_DIR, f"{rid}.meta.json"), "w") as f:
            json.dump({"rating": m["rating"], "uploadtime": m["uploadtime"]}, f)
        fetched += 1
    except Exception:
        failed += 1

    if i % 25 == 0 or i == len(qualified):
        elapsed = time.time() - t0
        rate = i / elapsed if elapsed > 0 else 0
        eta = (len(qualified) - i) / rate if rate > 0 else 0
        print(f"  {i}/{len(qualified)}  fetched={fetched} skipped={skipped} failed={failed}  "
              f"{rate:.1f}/s  eta={eta/60:.1f}min")

    time.sleep(SLEEP + random.uniform(0, 0.1))

print(f"\nDONE: fetched={fetched} skipped={skipped} failed={failed}")
print(f"Files in: {REPLAY_DIR}")
