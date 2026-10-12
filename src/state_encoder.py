"""Encoder v2: dict of tensors for embedding-based model."""
import json
import os
import numpy as np
import torch

REGM_DB = os.path.expanduser("~/project/data/regmc_db.json")

STATUSES = ["none", "brn", "par", "slp", "psn", "tox", "frz"]
WEATHERS = ["none", "SunnyDay", "RainDance", "Sandstorm", "Snow", "Hail",
            "DesolateLand", "PrimordialSea", "DeltaStream"]
TERRAINS = ["none", "Electric", "Grassy", "Psychic", "Misty"]
BOOST_STATS = ["atk", "def", "spa", "spd", "spe"]

N_SLOTS = 12
N_MOVES_PER = 4
CONT_DIM = 17


class StateEncoder:
    def __init__(self):
        db = json.load(open(REGM_DB))
        self.species_list = sorted(db["species"].keys())
        self.move_list = sorted(db["moves"].keys())
        self.item_list = sorted(db["items"].keys())
        self.ability_list = sorted(db["abilities"].keys())
        self.species_idx = {s: i + 1 for i, s in enumerate(self.species_list)}
        self.move_idx = {m: i + 1 for i, m in enumerate(self.move_list)}
        self.item_idx = {i: k + 1 for k, i in enumerate(self.item_list)}
        self.ability_idx = {a: i + 1 for i, a in enumerate(self.ability_list)}
        self.n_species = len(self.species_list) + 1
        self.n_moves = len(self.move_list) + 1
        self.n_items = len(self.item_list) + 1
        self.n_abilities = len(self.ability_list) + 1

    def encode_mon(self, mon):
        species_id = 0
        move_ids = [0, 0, 0, 0]
        item_id = 0
        ability_id = 0
        cont = np.zeros(CONT_DIM, dtype=np.float32)
        if mon is not None:
            sid = self.species_idx.get(mon.get("species"))
            if sid:
                species_id = sid
            for i, mv in enumerate((mon.get("revealed_moves") or [])[:4]):
                mid = self.move_idx.get(mv)
                if mid:
                    move_ids[i] = mid
            item = mon.get("item")
            if item:
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
                cont[1] = min(1.0, hp_max / 200.0)
            boosts = mon.get("boosts") or {}
            for i, stat in enumerate(BOOST_STATS):
                b = boosts.get(stat, 0)
                cont[2 + i] = max(-1.0, min(1.0, b / 6.0))
            status = mon.get("status") or "none"
            si = STATUSES.index(status) if status in STATUSES else 0
            cont[7 + si] = 1.0
            cont[14] = 1.0 if mon.get("is_mega") else 0.0
            cont[15] = 1.0 if hp_now == 0 else 0.0
        return species_id, move_ids, item_id, ability_id, cont

    def encode_field(self, field):
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
    import sys, time
    enc = StateEncoder()
    print(f"Vocab: species={enc.n_species}, moves={enc.n_moves}, "
          f"items={enc.n_items}, abilities={enc.n_abilities}")
    path = os.path.expanduser("~/project/data/training_data.jsonl")
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
