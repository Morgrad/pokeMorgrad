"""BC trainer — per-turn, two-headed (slot A + slot B)."""
import json
import os
import random
import time

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

from src.state_encoder import StateEncoder
from src.bc_model import (
    BCModel, build_move_mask, save_checkpoint,
    NEG_INF, TYPE_MOVE, TYPE_SWITCH, TYPE_NONE,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p(*parts):
    return os.path.join(_REPO_ROOT, *parts)


DATA = _p("data", "training_data.jsonl")
PRIORS_PATH = _p("data", "species_move_priors.json")
MODEL_DIR = _p("output", "models")
BEST_MODEL_PATH = os.path.join(MODEL_DIR, os.environ.get("BC_OUT", "bc_best.pt"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BATCH = 256
EPOCHS = int(os.environ.get("BC_EPOCHS", "30"))
LR = 1e-3
WEIGHT_DECAY = 1e-5
VAL_FRAC = 0.1
SEED = 42
NUM_WORKERS = 0
PATIENCE = int(os.environ.get("BC_PATIENCE", "3"))


class BCDataset(Dataset):
    def __init__(self, decisions, encoder, priors):
        self.encoder = encoder
        self.samples = []
        allowed = {sp: {e["move"] for e in entries} for sp, entries in priors.items()}
        self.allowed_moves = allowed

        for o in decisions:
            side = o["side"]
            acts = o.get("chosen", {}).get(side, {})
            if not acts:
                continue
            state = o["state"]
            my_active = state.get("my_active", [])
            if len(my_active) < 2:
                my_active = (my_active + [None, None])[:2]

            slot_data = []
            for slot_name, slot_idx in [("a", 0), ("b", 1)]:
                action = acts.get(slot_name)
                mon = my_active[slot_idx] if slot_idx < len(my_active) else None
                if not isinstance(action, dict) or mon is None:
                    slot_data.append((TYPE_NONE, 0, 0, mon))
                    continue
                t = action.get("type")
                sp_name = mon.get("species")
                if t == "move":
                    mv = action.get("move")
                    if self.allowed_moves and sp_name in self.allowed_moves \
                            and mv not in self.allowed_moves[sp_name]:
                        slot_data.append((TYPE_NONE, 0, 0, mon))
                        continue
                    mid = encoder.move_idx.get(mv, 0)
                    slot_data.append((TYPE_MOVE, mid, 0, mon))
                elif t == "switch":
                    target_id = encoder.species_idx.get(action.get("to"), 0)
                    slot_data.append((TYPE_SWITCH, 0, target_id, mon))
                else:
                    slot_data.append((TYPE_NONE, 0, 0, mon))

            # Outcome-weighted sampling: duplicate decisions from winning
            # sides so they contribute ~2x their share of the gradient.
            # Cheap alternative to sample-weighted loss (no cross_entropy
            # reduction='none' plumbing). side_won defaults to True when
            # the field is missing (e.g. legacy data without winner info).
            weight = 2 if o.get("side_won", True) else 1
            for _ in range(weight):
                self.samples.append((state, slot_data))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        state, slot_data = self.samples[i]
        enc = self.encoder.encode(state)

        bench = state.get("my_bench", [])
        bench_mask = np.zeros(self.encoder.n_species, dtype=np.float32)
        for m in bench:
            if not m:
                continue
            sid = self.encoder.species_idx.get(m.get("species"), 0)
            if sid:
                bench_mask[sid] = 1.0

        out = [
            enc["species_ids"], enc["move_ids"], enc["item_ids"],
            enc["ability_ids"], enc["continuous"], enc["field"],
            torch.from_numpy(bench_mask),
        ]
        for (t, mv, sw, mon) in slot_data:
            acting_sid = self.encoder.species_idx.get(mon.get("species"), 0) if mon else 0
            out.append(torch.tensor([t, mv, sw, acting_sid], dtype=torch.long))
        return tuple(out)


def slot_loss(type_logits, move_logits, switch_logits, targets, move_mask, bench_mask):
    t = targets[:, 0]; mv = targets[:, 1]; sw = targets[:, 2]; sid = targets[:, 3]
    loss = F.cross_entropy(type_logits, t)
    mm = t == TYPE_MOVE
    if mm.any():
        per_species = move_mask[sid[mm]]
        masked = move_logits[mm] + (1 - per_species) * NEG_INF
        loss = loss + F.cross_entropy(masked, mv[mm])
    sm = t == TYPE_SWITCH
    if sm.any():
        bmask = bench_mask[sm]
        masked = switch_logits[sm] + (1 - bmask) * NEG_INF
        loss = loss + F.cross_entropy(masked, sw[sm])
    return loss


def run_epoch(model, loader, opt, train, move_mask):
    model.train() if train else model.eval()
    torch.set_grad_enabled(train)
    total_loss = 0.0
    total = 0
    correct = 0
    move_correct = 0
    move_total = 0
    switch_correct = 0
    switch_total = 0

    for batch in loader:
        (sp, mv, it, ab, cont, field, bench_mask,
         slot_a, slot_b) = [b.to(DEVICE) for b in batch]
        if train:
            opt.zero_grad()

        ta, ma, sa, tb, mb, sb = model(sp, mv, it, ab, cont, field)
        loss = slot_loss(ta, ma, sa, slot_a, move_mask, bench_mask) + \
               slot_loss(tb, mb, sb, slot_b, move_mask, bench_mask)

        if train:
            loss.backward()
            opt.step()

        bs = sp.size(0)
        total_loss += loss.item() * bs

        for t_logits, m_logits, s_logits, targets in [(ta, ma, sa, slot_a),
                                                       (tb, mb, sb, slot_b)]:
            t_t = targets[:, 0]; mv_t = targets[:, 1]
            sw_t = targets[:, 2]; sid_t = targets[:, 3]

            pred_t = t_logits.argmax(1)
            per_species = move_mask[sid_t]
            m_masked = m_logits + (1 - per_species) * NEG_INF
            pred_m = m_masked.argmax(1)
            m_valid = t_t == TYPE_MOVE
            move_correct += (m_valid & (pred_m == mv_t)).sum().item()
            move_total += m_valid.sum().item()

            s_masked = s_logits + (1 - bench_mask) * NEG_INF
            pred_s = s_masked.argmax(1)
            s_valid = t_t == TYPE_SWITCH
            switch_correct += (s_valid & (pred_s == sw_t)).sum().item()
            switch_total += s_valid.sum().item()

            ok = (pred_t == t_t) & (
                (m_valid & (pred_m == mv_t)) |
                (s_valid & (pred_s == sw_t)) |
                (t_t == TYPE_NONE)
            )
            correct += ok.sum().item()
            total += bs

    return (total_loss / max(total, 1), correct / max(total, 1),
            move_correct / max(move_total, 1), switch_correct / max(switch_total, 1))


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    print(f"Device: {DEVICE}")
    enc = StateEncoder()
    print(f"Vocab: species={enc.n_species}, moves={enc.n_moves}")

    print("Loading priors...")
    priors = json.load(open(PRIORS_PATH))
    move_mask = build_move_mask(priors, enc).to(DEVICE)

    print("Loading decisions...")
    decisions = []
    with open(DATA) as f:
        for line in f:
            decisions.append(json.loads(line))
    print(f"  {len(decisions)} turn rows")

    random.shuffle(decisions)
    n_val = int(len(decisions) * VAL_FRAC)
    train_d, val_d = decisions[n_val:], decisions[:n_val]

    print("Building datasets...")
    train_ds = BCDataset(train_d, enc, priors)
    val_ds = BCDataset(val_d, enc, priors)
    print(f"  train={len(train_ds):,}  val={len(val_ds):,}")

    tl = DataLoader(train_ds, batch_size=BATCH, shuffle=True, num_workers=NUM_WORKERS)
    vl = DataLoader(val_ds, batch_size=BATCH, shuffle=False, num_workers=NUM_WORKERS)

    model = BCModel(enc.n_species, enc.n_moves, enc.n_items, enc.n_abilities).to(DEVICE)
    print(f"Params: {sum(p.numel() for p in model.parameters()):,}")

    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)

    best_val_loss = float("inf")
    best_val_acc = 0.0
    noimp = 0

    for epoch in range(1, EPOCHS + 1):
        t0 = time.time()
        trl, tra, trm, trs = run_epoch(model, tl, opt, True, move_mask)
        vll, vla, vlm, vls = run_epoch(model, vl, opt, False, move_mask)
        sched.step()
        dt = time.time() - t0

        marker = ""
        if vll < best_val_loss:
            best_val_loss = vll
            best_val_acc = vla
            noimp = 0
            save_checkpoint(
                BEST_MODEL_PATH, model,
                epoch=epoch, val_loss=vll, val_acc=vla,
                val_move_acc=vlm, val_switch_acc=vls,
            )
            marker = " *"
        else:
            noimp += 1

        print(f"Epoch {epoch:2d}/{EPOCHS}  "
              f"trl={trl:.3f} tra={tra:.3f} trm={trm:.3f} trs={trs:.3f}  "
              f"vll={vll:.3f} vla={vla:.3f} vlm={vlm:.3f} vls={vls:.3f}  "
              f"({dt:.1f}s){marker}", flush=True)

        if noimp >= PATIENCE:
            print(f"Early stop at epoch {epoch}")
            break

    print(f"\nBest val_loss={best_val_loss:.4f}  val_acc={best_val_acc:.3f}")
    print(f"Saved: {BEST_MODEL_PATH}")


if __name__ == "__main__":
    main()