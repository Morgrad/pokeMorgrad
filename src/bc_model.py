"""Neural model + checkpoint I/O for the BC pilot.

Extracted from the original bc_train.py so that bc_player.py can import
the model without pulling in the training pipeline (DataLoader, Dataset, ...).
"""
import os

import numpy as np
import torch
import torch.nn as nn

from src.state_encoder import N_SLOTS, N_MOVES_PER, CONT_DIM

# Architecture constants
EMB_SPECIES = 32
EMB_MOVE = 16
EMB_ITEM = 16
EMB_ABILITY = 16

NEG_INF = -1e4
TYPE_MOVE, TYPE_SWITCH, TYPE_NONE = 0, 1, 2


class BCModel(nn.Module):
    def __init__(self, n_species, n_moves, n_items, n_abilities):
        super().__init__()
        self.sp_emb = nn.Embedding(n_species, EMB_SPECIES, padding_idx=0)
        self.mv_emb = nn.Embedding(n_moves, EMB_MOVE, padding_idx=0)
        self.it_emb = nn.Embedding(n_items, EMB_ITEM, padding_idx=0)
        self.ab_emb = nn.Embedding(n_abilities, EMB_ABILITY, padding_idx=0)

        per_mon = EMB_SPECIES + EMB_MOVE * N_MOVES_PER + EMB_ITEM + EMB_ABILITY + CONT_DIM
        flat = per_mon * N_SLOTS + 17

        self.trunk = nn.Sequential(
            nn.Linear(flat, 512), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(512, 256), nn.ReLU(), nn.Dropout(0.3),
        )
        self.type_head_a   = nn.Linear(256, 3)
        self.move_head_a   = nn.Linear(256, n_moves)
        self.switch_head_a = nn.Linear(256, n_species)
        self.type_head_b   = nn.Linear(256, 3)
        self.move_head_b   = nn.Linear(256, n_moves)
        self.switch_head_b = nn.Linear(256, n_species)

    def forward(self, sp, mv, it, ab, cont, field):
        B = sp.size(0)
        sp_e = self.sp_emb(sp)
        mv_e = self.mv_emb(mv).view(B, N_SLOTS, N_MOVES_PER * EMB_MOVE)
        it_e = self.it_emb(it)
        ab_e = self.ab_emb(ab)
        per = torch.cat([sp_e, mv_e, it_e, ab_e, cont], dim=-1)
        flat = torch.cat([per.view(B, -1), field], dim=-1)
        h = self.trunk(flat)
        return (self.type_head_a(h), self.move_head_a(h), self.switch_head_a(h),
                self.type_head_b(h), self.move_head_b(h), self.switch_head_b(h))


def build_move_mask(priors, encoder, verbose=True):
    """Build (species × move) 0/1 mask from real usage priors. Returns CPU tensor."""
    mask = np.ones((encoder.n_species, encoder.n_moves), dtype=np.float32)
    matched = 0
    for sp_name, entries in priors.items():
        sid = encoder.species_idx.get(sp_name)
        if not sid:
            continue
        matched += 1
        mask[sid, :] = 0.0
        for e in entries:
            mid = encoder.move_idx.get(e["move"])
            if mid:
                mask[sid, mid] = 1.0
    if verbose:
        covered = mask[1:].sum(1)
        covered = covered[covered > 0]
        if covered.size:
            print(f"Move mask: {matched} species, avg={covered.mean():.1f} moves/species")
    return torch.from_numpy(mask)


def save_checkpoint(path, model, *, epoch, val_loss, val_acc,
                    val_move_acc, val_switch_acc, encoder_v=2):
    """Save a training checkpoint. Schema is compatible with bc_best.pt."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save({
        "model_state": model.state_dict(),
        "epoch": epoch,
        "val_loss": val_loss,
        "val_acc": val_acc,
        "val_move_acc": val_move_acc,
        "val_switch_acc": val_switch_acc,
        "encoder_v": encoder_v,
    }, path)


def load_checkpoint(path, model, device="cpu"):
    """Load state dict into `model` and put it in eval mode. Returns the raw ckpt dict."""
    ckpt = torch.load(path, map_location=device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return ckpt
