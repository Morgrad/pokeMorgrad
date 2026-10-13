"""
state_encoder.py — Battle state (dict) -> tensors for the embedding BC model.

Usage:
    from src.state_encoder import StateEncoder
    enc = StateEncoder()                 # loads vocab from data/regmc_db.json
    tensors = enc.encode(state_dict)     # dict of torch tensors, fed to BCModel

    python -m src.state_encoder          # self-test: prints vocab + throughput

Inputs:
    - data/regmc_db.json — canonical species/moves/items/abilities. Vocab size
      and ordering come from here; they are baked into the trained checkpoint.
    - state_dict — one decision point: my_active/my_bench/opp_active/opp_seen
      (each a list of mon dicts) plus an optional `field` dict.

What it produces (per encode()):
    species_ids [12], move_ids [12,4], item_ids [12], ability_ids [12] — long
    indices into the embedding tables; continuous [12,17] and field [17] floats.
    The 12 slots are a FIXED order: my 2 active, my 4 bench, opp 2 active, opp 4
    seen (see encode()).

CHECKPOINT CONTRACT (read the banner by the constants below before editing):
    the vocab sizes, the 12/4/17 dimensions and every index in the cont[] and
    field layouts are frozen — the trained model's first Linear depends on them.
    Comment freely; do NOT renumber or resize.
"""
import json
import numpy as np
import torch

from src.paths import data_path

REGM_DB = data_path("regmc_db.json")

# =============================================================================
# CHECKPOINT CONTRACT — DO NOT RENAME OR RESIZE
# =============================================================================
# These lists define BOTH the one-hot offsets inside cont[]/field AND their
# widths. Appending to STATUSES/WEATHERS/TERRAINS shifts every later index and
# silently invalidates output/models/bc_best.pt. The *order* is the contract,
# not just the membership. "none" MUST stay at index 0 — it is the fallback bin
# for any value we don't recognize (see the `x in X else 0` guards below).
STATUSES = ["none", "brn", "par", "slp", "psn", "tox", "frz"]          # 7-wide
WEATHERS = ["none", "SunnyDay", "RainDance", "Sandstorm", "Snow", "Hail",
            "DesolateLand", "PrimordialSea", "DeltaStream"]            # 9-wide
TERRAINS = ["none", "Electric", "Grassy", "Psychic", "Misty"]         # 5-wide
BOOST_STATS = ["atk", "def", "spa", "spd", "spe"]                     # 5-wide

N_SLOTS = 12       # mons per state: 2 active + 4 bench, our side then theirs
N_MOVES_PER = 4    # move slots per mon
CONT_DIM = 17      # width of the per-mon continuous vector (cont[] layout below)

# Bulk/HP normalizers. 200 HP is a practical ceiling for VGC (a max-invest
# Blissey-class wall); dividing by it maps hp_max into ~[0,1] as a cheap bulk
# proxy. 6 is the stat-stage cap (+6/-6), so boost/6 lands in [-1,1].
HP_MAX_NORM = 200.0
BOOST_STAGE_MAX = 6.0



class StateEncoder:
    """
    Turns a decision-point state dict into the tensor bundle BCModel expects.

    Construction loads the canonical vocab from regmc_db.json once and builds
    name -> index maps. Index 0 is reserved as the "unknown / empty slot"
    padding id for every embedding table (hence `i + 1`), so a missing species,
    move, item, or ability all collapse to the model's pad embedding instead of
    crashing or aliasing a real entry.

    Internal state:
      species_list/move_list/item_list/ability_list : sorted vocab (order frozen)
      *_idx   : name -> 1-based embedding index
      n_*     : embedding table sizes (= vocab + 1 for the pad slot)
    """

    def __init__(self):
        db = json.load(open(REGM_DB))
        # sorted() makes the index assignment deterministic across rebuilds —
        # the model was trained against this exact ordering.
        self.species_list = sorted(db["species"].keys())
        self.move_list = sorted(db["moves"].keys())
        self.item_list = sorted(db["items"].keys())
        self.ability_list = sorted(db["abilities"].keys())
        # 1-based: index 0 stays free as the pad / unknown id for each table.
        self.species_idx = {s: i + 1 for i, s in enumerate(self.species_list)}
        self.move_idx = {m: i + 1 for i, m in enumerate(self.move_list)}
        self.item_idx = {i: k + 1 for k, i in enumerate(self.item_list)}
        self.ability_idx = {a: i + 1 for i, a in enumerate(self.ability_list)}
        self.n_species = len(self.species_list) + 1
        self.n_moves = len(self.move_list) + 1
        self.n_items = len(self.item_list) + 1
        self.n_abilities = len(self.ability_list) + 1

    def encode_mon(self, mon):
        """
        Encode one mon into (species_id, move_ids[4], item_id, ability_id, cont).

        `mon` may be None (empty slot) -> all-zero / pad ids, cont stays zeros.
        Unknown names fall back to id 0 (pad). The active flag at cont[16] is
        NOT set here — encode() sets it per slot, because whether a mon is active
        is a property of its position, not the mon itself.

        cont[] layout (CONT_DIM = 17) — this is a checkpoint contract:
            [0]      current HP fraction      hp_now / hp_max, clamped [0,1]
            [1]      bulk proxy               min(1, hp_max / 200)
            [2:7]    stat boosts              BOOST_STATS order, each b/6 in [-1,1]
            [7:14]   status one-hot           STATUSES order (none..frz), 7 bins
            [14]     mega flag                1 if mid-battle mega-evolved
            [15]     fainted flag             1 if hp_now == 0
            [16]     active flag              set by encode(), 0 here
        NOTE: field[] (encode_field) is ALSO 17 wide but a completely different
        layout — the shared width is a coincidence, not a shared meaning.
        """
        species_id = 0
        move_ids = [0, 0, 0, 0]
        item_id = 0
        ability_id = 0
        cont = np.zeros(CONT_DIM, dtype=np.float32)
        if mon is not None:
            sid = self.species_idx.get(mon.get("species"))
            if sid:
                species_id = sid
            for i, mv in enumerate((mon.get("revealed_moves") or [])[:N_MOVES_PER]):
                mid = self.move_idx.get(mv)
                if mid:
                    move_ids[i] = mid
            item = mon.get("item")
            if item:
                # Items arrive as "Choice Band (...)" sometimes — strip the paren tail.
                base = item.split(" (")[0]
                iid = self.item_idx.get(base)
                if iid:
                    item_id = iid
            abil = mon.get("ability")
            if abil:
                aid = self.ability_idx.get(abil)
                if aid:
                    ability_id = aid
            hp_now = mon.get("hp_now")
            hp_max = mon.get("hp_max")
            if hp_now is not None and hp_max and hp_max > 0:
                cont[0] = max(0.0, min(1.0, hp_now / hp_max))
            if hp_max:
                cont[1] = min(1.0, hp_max / HP_MAX_NORM)
            boosts = mon.get("boosts") or {}
            for i, stat in enumerate(BOOST_STATS):
                b = boosts.get(stat, 0)
                cont[2 + i] = max(-1.0, min(1.0, b / BOOST_STAGE_MAX))
            # Status one-hot; unknown status -> index 0 ("none") via the guard.
            status = mon.get("status") or "none"
            si = STATUSES.index(status) if status in STATUSES else 0
            cont[7 + si] = 1.0
            cont[14] = 1.0 if mon.get("is_mega") else 0.0
            cont[15] = 1.0 if hp_now == 0 else 0.0
        return species_id, move_ids, item_id, ability_id, cont

    def encode_field(self, field):
        """
        Encode global field state into a 17-wide vector (distinct from cont[]):
            [0:9]    weather one-hot    WEATHERS order (none + 8), 9 bins
            [9:14]   terrain one-hot    TERRAINS order (none + 4), 5 bins
            [14]     trick room         1 if active
            [15]     tailwind p1        1 if our tailwind up
            [16]     tailwind p2        1 if their tailwind up
        9 + 5 + 1 + 2 = 17. `p` walks the offset so the blocks stay in sync with
        the vocab widths above — do not hand-hardcode the indices.
        """
        v = np.zeros(17, dtype=np.float32)
        if not field:
            return v
        p = 0
        w = field.get("weather") or "none"
        v[p + (WEATHERS.index(w) if w in WEATHERS else 0)] = 1.0
        p += len(WEATHERS)
        t = field.get("terrain") or "none"
        v[p + (TERRAINS.index(t) if t in TERRAINS else 0)] = 1.0
        p += len(TERRAINS)
        v[p] = 1.0 if field.get("trick_room") else 0.0
        p += 1
        tw = field.get("tailwind") or {}
        v[p] = 1.0 if tw.get("p1", 0) > 0 else 0.0
        v[p + 1] = 1.0 if tw.get("p2", 0) > 0 else 0.0
        return v

    def encode(self, state_dict):
        """
        Assemble the full 12-slot tensor bundle for one decision point.

        Slot order is FIXED and must match training: our 2 active, our 4 bench,
        their 2 active, their 4 seen. Short lists are padded with None; long ones
        truncated. `active_mask` marks which of the 12 slots are the on-field
        mons (slots 0,1 and 6,7) and is written into cont[16] per slot.
        """
        my_active = (list(state_dict.get("my_active", [])) + [None, None])[:2]
        my_bench = (list(state_dict.get("my_bench", [])) + [None]*4)[:4]
        opp_active = (list(state_dict.get("opp_active", [])) + [None, None])[:2]
        opp_seen = (list(state_dict.get("opp_seen", [])) + [None]*4)[:4]
        slots = my_active + my_bench + opp_active + opp_seen
        active_mask = [1, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0]
        sp_ids, mv_ids, it_ids, ab_ids, conts = [], [], [], [], []
        for i, m in enumerate(slots):
            sid, mvs, iid, aid, cont = self.encode_mon(m)
            cont[16] = float(active_mask[i])
            sp_ids.append(sid); mv_ids.append(mvs); it_ids.append(iid)
            ab_ids.append(aid); conts.append(cont)
        return {
            "species_ids": torch.tensor(sp_ids, dtype=torch.long),
            "move_ids": torch.tensor(mv_ids, dtype=torch.long),
            "item_ids": torch.tensor(it_ids, dtype=torch.long),
            "ability_ids": torch.tensor(ab_ids, dtype=torch.long),
            "continuous": torch.tensor(np.stack(conts), dtype=torch.float32),
            "field": torch.from_numpy(self.encode_field(state_dict.get("field"))),
        }


if __name__ == "__main__":
    import time
    enc = StateEncoder()
    print(f"Vocab: species={enc.n_species}, moves={enc.n_moves}, "
          f"items={enc.n_items}, abilities={enc.n_abilities}")
    path = data_path("training_data.jsonl")
    with open(path) as f:
        sample = json.loads(f.readline())
    out = enc.encode(sample["state"])
    for k, v in out.items():
        print(f"  {k}: shape={tuple(v.shape)}, dtype={v.dtype}")
    t0 = time.time()
    n = 0
    with open(path) as f:
        for line in f:
            enc.encode(json.loads(line)["state"])
            n += 1
            if n >= 500:
                break
    dt = time.time() - t0
    print(f"\n{n} states in {dt:.2f}s = {n/dt:.0f}/s")
