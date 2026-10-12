import requests
import time
import json
import os
from tqdm import tqdm

FORMAT = "gen9championsvgc2026regmc"
OUTPUT = "regmc_replays.jsonl"
MAX_PAGES = 200  # ~10,000 replays max; raise if you want more

def fetch_page(page):
    url = f"https://replay.pokemonshowdown.com/search.json?format={FORMAT}&page={page}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print(f"  page {page} error: {e}")
        return None

def fetch_replay(replay_id):
    url = f"https://replay.pokemonshowdown.com/{replay_id}.json"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

def main():
    print(f"Searching Showdown for format: {FORMAT}")
    all_ids = []
    page = 1
    empty_pages = 0

    while page <= MAX_PAGES and empty_pages < 2:
        data = fetch_page(page)
        if not data:
            empty_pages += 1
            page += 1
            time.sleep(1.0)
            continue

        # Showdown returns a list of replay objects
        if isinstance(data, list):
            replays = data
        else:
            replays = data.get("results", [])

        if not replays:
            empty_pages += 1
            page += 1
            time.sleep(1.0)
            continue

        for rep in replays:
            rid = rep.get("id") or rep.get("uploadtime", "")
            if rid:
                all_ids.append(rid)

        print(f"  page {page}: +{len(replays)} replays (total: {len(all_ids)})")
        page += 1
        time.sleep(1.0)  # be polite

    print(f"\nFound {len(all_ids)} replay IDs. Downloading full logs...")

    if not all_ids:
        print("\n⚠️  NO REPLAYS FOUND for this format.")
        print("This means the format is too new/custom for public replays.")
        print("We'll need to generate data via self-play instead.")
        return

    with open(OUTPUT, "w") as f:
        count = 0
        for rid in tqdm(all_ids):
            log = fetch_replay(rid)
            if log:
                f.write(json.dumps(log) + "\n")
                count += 1
            time.sleep(0.3)  # rate limit

    print(f"\n✅ Saved {count} replays to {OUTPUT}")

if __name__ == "__main__":
    main()
