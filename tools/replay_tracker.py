"""
Replay log → decision-point states with move + switch options.

For each turn and each side, emits:
  {
    "replay_id": "...",
    "rating": N,
    "turn": N,
    "side": "p1",
    "state": {
      "my_active": [mon, mon],       # 2 slots
      "my_bench": [mon, mon],        # up to 4, only brought ones
      "opp_active": [mon, mon],
      "opp_seen": [mon, ...],        # anything revealed on opp side
      "field": {...},
    },
    "legal_actions": {
      "slot_a": [action, ...],       # moves + switches
      "slot_b": [action, ...],
    },
    "chosen": {
      "slot_a": action,
      "slot_b": action,
    },
  }

Action shapes:
  {"type": "move",   "move": "Fake Out", "target": "p2b"}
  {"type": "switch", "to": "Garchomp"}
"""
import json
import sys
from pathlib import Path

# --- Format constants (gen 9 VGC) ---
# These mirror in-game durations; we only flag the window, we don't tick it down
# turn by turn (the training signal is "is it active now", not "how many left").
MOVES_PER_MON = 4        # a mon reveals at most 4 distinct moves — cap every move list here
TRICK_ROOM_TURNS = 5     # Trick Room lasts 5 turns for the side that sets it
TAILWIND_TURNS = 4       # Tailwind lasts 4 turns for the side that sets it


def blank_mon():
    return {
        "species": None,
        "gender": None,
        "hp_now": None,
        "hp_max": None,
        "status": None,
        "boosts": {},
        "revealed_moves": [],
        "item": None,
        "ability": None,
        "is_mega": False,
        "is_active": False,
        "brought": False,
        "fainted": False,
    }


class Side:
    """One player's roster, tracked as the replay is replayed line by line.

    `mons` is the 6-mon preview order (what |poke| / |showteam| reveal up front);
    `active` maps the two live slots ("a"/"b") to indices into `mons`. We mutate
    these dicts in place as damage/boosts/switches come in.
    """

    def __init__(self, side_id):
        self.side_id = side_id  # "p1" or "p2"
        self.mons = [blank_mon() for _ in range(6)]  # preview order
        self.active = {"a": None, "b": None}  # index into mons

    def find_by_species(self, species):
        """Find a mon by species name (first non-fainted match)."""
        for i, m in enumerate(self.mons):
            if m["species"] == species and not m["fainted"]:
                return i
        return None

    def find_active(self, slot):
        idx = self.active.get(slot)
        return self.mons[idx] if idx is not None else None


def update_boosts(mon, stat, delta):
    if stat not in mon["boosts"]:
        mon["boosts"][stat] = 0
    mon["boosts"][stat] = max(-6, min(6, mon["boosts"][stat] + delta))


def parse_hp(s):
    """'100/100' → (100, 100). '0 fnt' → (0, max). '16/100' → (16, 100)."""
    if not s:
        return None, None
    s = s.strip()

    # Explicit faint marker
    if s.endswith("fnt") or s == "0 fnt":
        # Try to extract max from "0 fnt" (no max present) or "0/100 fnt"
        if "/" in s:
            try:
                max_hp = int(s.split("/")[1].split()[0])
                return 0, max_hp
            except (ValueError, IndexError):
                pass
        return 0, None

    # Standard "current/max" form
    token = s.split()[0]  # in case of trailing flags
    if "/" in token:
        parts = token.split("/")
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                return None, None
    return None, None


class Tracker:
    def __init__(self, replay_data):
        self.data = replay_data
        self.log = replay_data["log"].split("\n")
        self.sides = {"p1": Side("p1"), "p2": Side("p2")}
        self.field = {
            "weather": None,
            "weather_turns": 0,
            "terrain": None,
            "terrain_turns": 0,
            "trick_room": False,
            "trick_room_turns": 0,
            "tailwind": {"p1": 0, "p2": 0},
        }
        self.turn = 0
        self.pending_actions = {"p1": {}, "p2": {}}  # slot → action
        self.outputs = []
        # turn number -> list of emitted output dicts still awaiting `chosen`.
        # Lets _backfill_chosen fill the just-ended turn in O(1) instead of
        # rescanning all of self.outputs every turn (the old O(turns²) loop).
        self._awaiting_by_turn = {}
        self.full_moves = {"p1": {}, "p2": {}}  # set by run()

    def emit_decision(self):
        """At the start of each turn, emit state + choices for both sides."""
        for side_id, side in self.sides.items():
            # Build state snapshot
            my_active = [side.find_active("a"), side.find_active("b")]
            my_bench = [m for m in side.mons
                        if m["brought"] and not m["is_active"] and not m["fainted"]]
            opp_id = "p2" if side_id == "p1" else "p1"
            opp = self.sides[opp_id]
            opp_active = [opp.find_active("a"), opp.find_active("b")]
            opp_seen = [m for m in opp.mons if m["species"] and (m["brought"] or m["is_active"])]

            # Legal actions (approximate — we know moves from reveal + bench from reveals)
            legal = self.compute_legal_actions(side)

            entry = {
                "replay_id": self.data.get("id"),
                "rating": self.data.get("rating"),
                "turn": self.turn,
                "side": side_id,
                "state": {
                    "my_active": [self._shallow_mon_full_moves(m, side_id) if m else None for m in my_active],
                    "my_bench": [self._shallow_mon_full_moves(m, side_id) for m in my_bench],
                    "opp_active": [self._shallow_mon(m) if m else None for m in opp_active],
                    "opp_seen": [self._shallow_mon(m) for m in opp_seen],
                    "field": dict(self.field),
                },
                "legal_actions": legal,
                "chosen": {},  # filled as we process the turn's actions
            }
            self.outputs.append(entry)
            self._awaiting_by_turn.setdefault(self.turn, []).append(entry)

    def _backfill_chosen(self):
        """Snapshot pending_actions into the outputs of the turn that just ended.

        Equivalent to the old "scan every output where turn == self.turn and
        chosen == {}" pass: the per-turn index holds exactly those still-unfilled
        entries (added on emit, dropped here on fill), so this is O(entries-this-
        turn) rather than O(all-outputs). Each entry still receives *both* sides'
        pending actions, matching the original behavior.
        """
        awaiting = self._awaiting_by_turn.pop(self.turn, None)
        if not awaiting:
            return
        for entry in awaiting:
            for side_id in ("p1", "p2"):
                entry["chosen"][side_id] = dict(self.pending_actions[side_id])

    def _shallow_mon_full_moves(self, m, side_id):
        """Like _shallow_mon but with the full moveset the player had."""
        out = self._shallow_mon(m)
        full = self.full_moves.get(side_id, {}).get(m["species"], [])
        if full:
            out["revealed_moves"] = list(full[:MOVES_PER_MON])
        return out

    def _shallow_mon(self, m):
        return {
            "species": m["species"],
            "gender": m["gender"],
            "hp_now": m["hp_now"],
            "hp_max": m["hp_max"],
            "status": m["status"],
            "boosts": dict(m["boosts"]),
            "revealed_moves": list(m["revealed_moves"]),
            "item": m["item"],
            "ability": m["ability"],
            "is_mega": m["is_mega"],
        }

    def compute_legal_actions(self, side):
        """Best-effort: moves revealed + bench slots."""
        slots = {}
        for slot in ("a", "b"):
            mon = side.find_active(slot)
            if not mon:
                slots[slot] = []
                continue
            actions = []
            # Revealed moves become legal "candidates" (we don't know full moveset)
            full_moves = self.full_moves.get(side.side_id, {}).get(mon["species"], mon["revealed_moves"])
            for mv in full_moves[:MOVES_PER_MON]:
                actions.append({"type": "move", "move": mv, "target": None})
            # Any brought, non-active bench mon is a switch target
            for i, m in enumerate(side.mons):
                if m["brought"] and not m["is_active"] and not m["fainted"]:
                    actions.append({"type": "switch", "to": m["species"]})
            slots[slot] = actions
        return slots

    # ============ EVENT HANDLERS ============

    def handle_poke(self, parts):
        # |poke|p1|Species, L50, F|
        side_id = parts[2]
        info = parts[3].split(",")
        species = info[0].strip()
        gender = info[2].strip() if len(info) > 2 else None
        # Filter out markers that aren't actually gender
        if gender and gender.lower() in ("shiny", "l50", "m", "f"):
            if gender.lower() == "shiny":
                gender = None
        if gender and gender.lower() not in ("m", "f"):
            gender = None
        side = self.sides.get(side_id)
        if not side:
            return
        for m in side.mons:
            if m["species"] is None:
                m["species"] = species
                m["gender"] = gender or None
                return

    def handle_showteam(self, parts):
        # |showteam|p1|Golisopod||Golisopite|EmergencyExit|LeechLife,CloseCombat,IronHead,Protect|Brave||F|||50|
        side_id = parts[2]
        side = self.sides.get(side_id)
        if not side:
            return
        entries = parts[3].split("]")
        for i, entry in enumerate(entries):
            if i >= 6:
                break
            fields = entry.split("|")
            if len(fields) < 4:
                continue
            # fields: species, ?, item, ability, moves_csv, nature, ?, gender, ...
            mon = side.mons[i]
            mon["species"] = fields[0].strip() or mon["species"]
            mon["item"] = fields[2].strip() or None
            mon["ability"] = fields[3].strip() or None
            if len(fields) > 4 and fields[4]:
                mon["revealed_moves"] = [mv.strip() for mv in fields[4].split(",") if mv.strip()]
            if len(fields) > 7 and fields[7].strip():
                mon["gender"] = fields[7].strip()

    def handle_switch(self, parts):
        # |switch|p1a: Incineroar|Incineroar, L50, F|100/100
        ident = parts[2]
        species_full = parts[3]
        hp_str = parts[4] if len(parts) > 4 else ""
        side_id = ident.split(":")[0][:2]
        slot = ident.split(":")[0][2:3]  # "a" or "b"
        species = species_full.split(",")[0].strip()
        hp_now, hp_max = parse_hp(hp_str)
        side = self.sides.get(side_id)
        if not side:
            return
        # Find mon in preview roster
        idx = side.find_by_species(species)
        if idx is None:
            return
        mon = side.mons[idx]
        mon["hp_now"] = hp_now
        mon["hp_max"] = hp_max or mon["hp_max"]
        mon["is_active"] = True
        mon["brought"] = True
        side.active[slot] = idx
        # If this is mid-turn, record action
        if self.turn > 0:
            self.pending_actions[side_id][slot] = {"type": "switch", "to": species}

    def handle_move(self, parts):
        # |move|p1b: Charizard|Protect|p1b: Charizard
        ident = parts[2]
        move = parts[3]
        target = parts[4] if len(parts) > 4 else None
        side_id = ident.split(":")[0][:2]
        slot = ident.split(":")[0][2:3]
        species = ident.split(":", 1)[1].strip()
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is None:
            return
        mon = side.mons[idx]
        if move not in mon["revealed_moves"]:
            mon["revealed_moves"].append(move)
        if self.turn > 0:
            self.pending_actions[side_id][slot] = {
                "type": "move", "move": move, "target": target
            }

    def handle_ability(self, parts):
        # |-ability|p1a: Incineroar|Intimidate|boost
        if len(parts) < 4:
            return
        ident = parts[2]
        ability = parts[3]
        side_id = ident.split(":")[0][:2]
        species = ident.split(":", 1)[1].strip() if ":" in ident else ""
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is not None:
            side.mons[idx]["ability"] = ability

    def handle_item_reveal(self, parts):
        # |-item|p1a: Incineroar|Sitrus Berry
        if len(parts) < 4:
            return
        ident = parts[2]
        item = parts[3]
        side_id = ident.split(":")[0][:2]
        species = ident.split(":", 1)[1].strip() if ":" in ident else ""
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is not None:
            side.mons[idx]["item"] = item

    def handle_enditem(self, parts):
        # |-enditem|p1a: Incineroar|Sitrus Berry|[eat]
        if len(parts) < 4:
            return
        ident = parts[2]
        item = parts[3]
        side_id = ident.split(":")[0][:2]
        species = ident.split(":", 1)[1].strip() if ":" in ident else ""
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is not None:
            side.mons[idx]["item"] = item + " (consumed)"

    def handle_hp_change(self, parts, delta=False):
        # |-damage|p1a: Incineroar|16/100|[from] ...
        # |-heal|p1a: Incineroar|41/100|[from] item: Sitrus Berry
        if len(parts) < 4:
            return
        ident = parts[2]
        hp_str = parts[3]
        side_id = ident.split(":")[0][:2]
        species = ident.split(":", 1)[1].strip() if ":" in ident else ""
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is None:
            return
        mon = side.mons[idx]
        hp_now, hp_max = parse_hp(hp_str)
        mon["hp_now"] = hp_now
        if hp_max is not None:
            mon["hp_max"] = hp_max
        if "fnt" in hp_str or hp_now == 0:
            mon["fainted"] = True
            mon["is_active"] = False
            for slot, i in list(side.active.items()):
                if i == idx:
                    side.active[slot] = None

    def handle_status(self, parts, cure=False):
        # |-status|p1a: X|brn  or  |-curestatus|p1a: X|brn
        if len(parts) < 4:
            return
        ident = parts[2]
        status = parts[3]
        side_id = ident.split(":")[0][:2]
        species = ident.split(":", 1)[1].strip() if ":" in ident else ""
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is not None:
            side.mons[idx]["status"] = None if cure else status

    def handle_boost(self, parts, unboost=False):
        # |-boost|p1a: X|atk|2
        if len(parts) < 5:
            return
        ident = parts[2]
        stat = parts[3]
        try:
            delta = int(parts[4])
        except ValueError:
            return
        if unboost:
            delta = -delta
        side_id = ident.split(":")[0][:2]
        species = ident.split(":", 1)[1].strip() if ":" in ident else ""
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is not None:
            update_boosts(side.mons[idx], stat, delta)

    def handle_weather(self, parts):
        # |-weather|SunnyDay|[upkeep]  or  |-weather|none
        weather = parts[2] if len(parts) > 2 else "none"
        if weather == "none":
            self.field["weather"] = None
        else:
            self.field["weather"] = weather

    def handle_field(self, parts, end=False):
        # |-fieldstart|move: Trick Room|[of] p1b: X
        if len(parts) < 3:
            return
        field = parts[2]
        if "Trick Room" in field:
            self.field["trick_room"] = not end
            self.field["trick_room_turns"] = 0 if end else TRICK_ROOM_TURNS

    def handle_sidestart(self, parts, end=False):
        # |-sidestart|p1: Team|move: Tailwind
        if len(parts) < 3:
            return
        team = parts[2]
        cond = parts[3] if len(parts) > 3 else ""
        side_id = team.split(":")[0].strip()
        if "Tailwind" in cond:
            self.field["tailwind"][side_id] = 0 if end else TAILWIND_TURNS

    def handle_detailschange(self, parts):
        # |detailschange|p1a: Charizard|Charizard-Mega-Y, L50, F
        ident = parts[2]
        details = parts[3]
        side_id = ident.split(":")[0][:2]
        species = ident.split(":", 1)[1].strip()
        new_species = details.split(",")[0].strip()
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is not None:
            mon = side.mons[idx]
            if "-Mega" in new_species:
                mon["is_mega"] = True

    def handle_mega(self, parts):
        # |-mega|p1a: Charizard|Charizard|Charizardite Y
        if len(parts) < 4:
            return
        ident = parts[2]
        item = parts[4] if len(parts) > 4 else None
        side_id = ident.split(":")[0][:2]
        species = ident.split(":", 1)[1].strip()
        side = self.sides.get(side_id)
        if not side:
            return
        idx = side.find_by_species(species)
        if idx is not None:
            mon = side.mons[idx]
            mon["is_mega"] = True
            if item:
                mon["item"] = item

    # ============ MAIN LOOP ============

    def run(self):
        # Prescan: collect all moves each mon used during the whole battle
        # (a player knows their own 4 moves from turn 1)
        self.full_moves = {"p1": {}, "p2": {}}
        for line in self.log:
            if not line.startswith("|move|"):
                continue
            parts = line.split("|")
            if len(parts) < 4:
                continue
            ident = parts[2]
            move = parts[3]
            side_id = ident.split(":")[0][:2]
            species = ident.split(":", 1)[1].strip() if ":" in ident else ""
            if side_id not in self.full_moves:
                continue
            self.full_moves[side_id].setdefault(species, [])
            if move not in self.full_moves[side_id][species]:
                self.full_moves[side_id][species].append(move)

        for line in self.log:
            if not line or not line.startswith("|"):
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            tag = parts[1]

            if tag == "poke":
                self.handle_poke(parts)
            elif tag == "showteam":
                self.handle_showteam(parts)
            elif tag == "turn":
                # Fill in the previous turn's choices, then open the new turn.
                self._backfill_chosen()
                self.pending_actions = {"p1": {}, "p2": {}}
                try:
                    self.turn = int(parts[2])
                except ValueError:
                    self.turn = 0
                self.emit_decision()
            elif tag == "switch":
                self.handle_switch(parts)
            elif tag == "drag":
                self.handle_switch(parts)
            elif tag == "move":
                self.handle_move(parts)
            elif tag == "-ability":
                self.handle_ability(parts)
            elif tag == "-item":
                self.handle_item_reveal(parts)
            elif tag == "-enditem":
                self.handle_enditem(parts)
            elif tag == "-damage":
                self.handle_hp_change(parts)
            elif tag == "-heal":
                self.handle_hp_change(parts)
            elif tag == "-sethp":
                self.handle_hp_change(parts)
            elif tag == "-status":
                self.handle_status(parts)
            elif tag == "-curestatus":
                self.handle_status(parts, cure=True)
            elif tag == "-boost":
                self.handle_boost(parts)
            elif tag == "-unboost":
                self.handle_boost(parts, unboost=True)
            elif tag == "-clearallboost":
                for side in self.sides.values():
                    for m in side.mons:
                        m["boosts"] = {}
            elif tag == "-weather":
                self.handle_weather(parts)
            elif tag == "-fieldstart":
                self.handle_field(parts)
            elif tag == "-fieldend":
                self.handle_field(parts, end=True)
            elif tag == "-sidestart":
                self.handle_sidestart(parts)
            elif tag == "-sideend":
                self.handle_sidestart(parts, end=True)
            elif tag == "detailschange":
                self.handle_detailschange(parts)
            elif tag == "-mega":
                self.handle_mega(parts)
            elif tag == "faint":
                if len(parts) > 2:
                    ident = parts[2]
                    side_id = ident.split(":")[0][:2]
                    species = ident.split(":", 1)[1].strip() if ":" in ident else ""
                    side = self.sides.get(side_id)
                    if side:
                        idx = side.find_by_species(species)
                        if idx is not None:
                            side.mons[idx]["fainted"] = True
                            side.mons[idx]["hp_now"] = 0
                            for slot, i in list(side.active.items()):
                                if i == idx:
                                    side.active[slot] = None
                            side.mons[idx]["is_active"] = False

        # Final snapshot: fill chosen for the last turn (both side-outputs)
        self._backfill_chosen()

        return self.outputs


def main(replay_path):
    d = json.load(open(replay_path))
    t = Tracker(d)
    outputs = t.run()
    print(f"Extracted {len(outputs)} decision points")
    if outputs:
        print()
        print("=== Sample decision point (turn 2) ===")
        for o in outputs:
            if o["turn"] == 2:
                print(json.dumps(o, indent=2, default=str)[:2000])
                break


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python replay_tracker.py <replay.json>")
        sys.exit(1)
    main(sys.argv[1])

