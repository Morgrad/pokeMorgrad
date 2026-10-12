import json
from collections import Counter

def parse_replay(replay):
    log = replay.get("log", "")
    if not log:
        return None

    lines = log.split("\n")
    parsed = {
        "id": replay.get("id"),
        "format": replay.get("formatid"),
        "rating": replay.get("rating"),
        "p1_name": None, "p2_name": None,
        "p1_rating": None, "p2_rating": None,
        "winner": None,
        "p1_team": [], "p2_team": [],
        "turns": [],
    }

    current_turn = None

    for line in lines:
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        tag = parts[1] if len(parts) > 1 else ""

        if tag == "player" and len(parts) >= 6:
            side, name = parts[2], parts[3]
            try:
                rating = int(parts[5]) if parts[5] else None
            except ValueError:
                rating = None
            if side == "p1":
                parsed["p1_name"], parsed["p1_rating"] = name, rating
            elif side == "p2":
                parsed["p2_name"], parsed["p2_rating"] = name, rating

        elif tag == "poke" and len(parts) >= 4:
            side = parts[2]
            species = parts[3].split(",")[0].strip()
            if side == "p1":
                parsed["p1_team"].append(species)
            elif side == "p2":
                parsed["p2_team"].append(species)

        elif tag == "turn" and len(parts) >= 3:
            try:
                current_turn = {"turn": int(parts[2]), "p1_actions": [], "p2_actions": []}
                parsed["turns"].append(current_turn)
            except ValueError:
                pass

        elif tag in ("switch", "drag") and current_turn and len(parts) >= 4:
            slot = parts[2].split(":")[0].strip()
            species = parts[3].split(",")[0].strip()
            action = {"type": "switch", "slot": slot, "to": species}
            (current_turn["p1_actions"] if slot.startswith("p1") else current_turn["p2_actions"]).append(action)

        elif tag == "move" and current_turn and len(parts) >= 5:
            slot = parts[2].split(":")[0].strip()
            action = {"type": "move", "slot": slot, "move": parts[3], "target": parts[4]}
            (current_turn["p1_actions"] if slot.startswith("p1") else current_turn["p2_actions"]).append(action)

        elif tag == "-mega" and current_turn and len(parts) >= 4:
            slot = parts[2].split(":")[0].strip()
            action = {"type": "mega", "slot": slot}
            (current_turn["p1_actions"] if slot.startswith("p1") else current_turn["p2_actions"]).append(action)

        elif tag == "win" and len(parts) >= 3:
            parsed["winner"] = parts[2]

    if not parsed["winner"] or len(parsed["turns"]) < 2:
        return None
    return parsed


def main():
    print("Loading raw replays...")
    replays = []
    with open("regmc_replays.jsonl") as f:
        for line in f:
            try:
                replays.append(json.loads(line))
            except Exception:
                pass
    print(f"  Loaded {len(replays)} raw replays")

    print("\nParsing...")
    parsed, skipped = [], 0
    for r in replays:
        p = parse_replay(r)
        if p is None:
            skipped += 1
        else:
            parsed.append(p)

    print(f"  Parsed:  {len(parsed)}")
    print(f"  Skipped: {skipped}")

    print("\nSaving to parsed_replays.jsonl...")
    with open("parsed_replays.jsonl", "w") as f:
        for p in parsed:
            f.write(json.dumps(p) + "\n")

    # -------- Summary --------
    total_turns = sum(len(p["turns"]) for p in parsed)
    total_actions = sum(len(t["p1_actions"]) + len(t["p2_actions"]) for p in parsed for t in p["turns"])

    print("\n" + "=" * 50)
    print("DATASET SUMMARY")
    print("=" * 50)
    print(f"Replays:                 {len(parsed)}")
    print(f"Total turns:             {total_turns}")
    print(f"Total actions:           {total_actions}")
    print(f"Avg turns per replay:    {total_turns/len(parsed):.1f}")
    print(f"Avg actions per turn:    {total_actions/total_turns:.2f}")

    all_species = Counter()
    for p in parsed:
        all_species.update(p["p1_team"])
        all_species.update(p["p2_team"])

    print("\nTop 20 most-used Pokémon:")
    for s, c in all_species.most_common(20):
        print(f"  {s:<22} {c}")

    all_moves = Counter()
    for p in parsed:
        for t in p["turns"]:
            for a in t["p1_actions"] + t["p2_actions"]:
                if a["type"] == "move":
                    all_moves[a["move"]] += 1

    print("\nTop 20 most-used moves:")
    for m, c in all_moves.most_common(20):
        print(f"  {m:<22} {c}")


if __name__ == "__main__":
    main()
