"""Neural models + checkpoint I/O for the BC pilot.

Two architectures:
  BCModel    (v2) — flat MLP trunk. The production model; bc_best.pt was
                    trained with this. OUTPUTS=6.
  BCModelV3  (v3) — transformer over 12 slot tokens + 1 field token.
                    Adds a per-slot target head. OUTPUTS=8.

Callers should check `model.OUTPUTS` to know whether to unpack 6 or 8 tensors.
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
N_TARGETS = 5   # 0=our right, 1=our left, 2=none, 3=opp left, 4=opp right


# ────────────────────────── v2 (production) ──────────────────────────

class BCModel(nn.Module):
    OUTPUTS = 6

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


# ────────────────────────── v3 (transformer) ──────────────────────────

class _TransformerBlock(nn.Module):
    def __init__(self, d_model, n_heads, ff_dim, dropout=0.1):
        super().__init__()
        self.attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout,
                                          batch_first=True)
        self.ln1 = nn.LayerNorm(d_model)
        self.ln2 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, ff_dim), nn.GELU(),
            nn.Linear(ff_dim, d_model),
        )
        self.drop = nn.Dropout(dropout)

    def forward(self, x):
        h = self.ln1(x)
        a, _ = self.attn(h, h, h, need_weights=False)
        x = x + self.drop(a)
        x = x + self.drop(self.ff(self.ln2(x)))
        return x


class BCModelV3(nn.Module):
    """Transformer over slot tokens + field token.

    Token stream:
      [slot_0, slot_1, ..., slot_11, field]   (13 tokens total)
    Each slot token gets:
      sp_emb + flat(mv_emb) + it_emb + ab_emb + cont  →  Linear → d_model
    Plus a per-position embedding so the model knows which slot it's looking at.

    Heads A read the hidden state of token 0 (our left).
    Heads B read the hidden state of token 1 (our right).
    """
    OUTPUTS = 8
    N_TOKENS = N_SLOTS + 1   # 12 slots + 1 field

    def __init__(self, n_species, n_moves, n_items, n_abilities,
                 d_model=384, n_heads=6, n_layers=4, ff_dim=768, dropout=0.1):
        super().__init__()
        self.sp_emb = nn.Embedding(n_species, EMB_SPECIES, padding_idx=0)
        self.mv_emb = nn.Embedding(n_moves, EMB_MOVE, padding_idx=0)
        self.it_emb = nn.Embedding(n_items, EMB_ITEM, padding_idx=0)
        self.ab_emb = nn.Embedding(n_abilities, EMB_ABILITY, padding_idx=0)

        per_mon = EMB_SPECIES + EMB_MOVE * N_MOVES_PER + EMB_ITEM + EMB_ABILITY + CONT_DIM
        self.mon_proj = nn.Linear(per_mon, d_model)
        self.field_proj = nn.Linear(17, d_model)
        self.pos_emb = nn.Embedding(self.N_TOKENS, d_model)

        self.blocks = nn.ModuleList([
            _TransformerBlock(d_model, n_heads, ff_dim, dropout)
            for _ in range(n_layers)
        ])
        self.ln_out = nn.LayerNorm(d_model)

        head_dim = d_model
        self.type_head_a   = nn.Linear(head_dim, 3)
        self.move_head_a   = nn.Linear(head_dim, n_moves)
        self.switch_head_a = nn.Linear(head_dim, n_species)
        self.target_head_a = nn.Linear(head_dim, N_TARGETS)
        self.type_head_b   = nn.Linear(head_dim, 3)
        self.move_head_b   = nn.Linear(head_dim, n_moves)
        self.switch_head_b = nn.Linear(head_dim, n_species)
        self.target_head_b = nn.Linear(head_dim, N_TARGETS)

    def forward(self, sp, mv, it, ab, cont, field):
        B = sp.size(0)
        sp_e = self.sp_emb(sp)
        mv_e = self.mv_emb(mv).view(B, N_SLOTS, N_MOVES_PER * EMB_MOVE)
        it_e = self.it_emb(it)
        ab_e = self.ab_emb(ab)
        per = torch.cat([sp_e, mv_e, it_e, ab_e, cont], dim=-1)   # (B, 12, per_mon)
        slot_tok = self.mon_proj(per)                             # (B, 12, d)
        field_tok = self.field_proj(field).unsqueeze(1)           # (B, 1, d)
        x = torch.cat([slot_tok, field_tok], dim=1)               # (B, 13, d)

        pos = torch.arange(self.N_TOKENS, device=x.device)
        x = x + self.pos_emb(pos).unsqueeze(0)

        for blk in self.blocks:
            x = blk(x)
        x = self.ln_out(x)

        h_a = x[:, 0]   # slot 0 (our left)
        h_b = x[:, 1]   # slot 1 (our right)

        return (
            self.type_head_a(h_a), self.move_head_a(h_a),
            self.switch_head_a(h_a), self.target_head_a(h_a),
            self.type_head_b(h_b), self.move_head_b(h_b),
            self.switch_head_b(h_b), self.target_head_b(h_b),
        )


# ────────────────────────── masks + checkpoint ──────────────────────────

def build_move_mask(priors, encoder, verbose=True):
    """(species × move) 0/1 mask from real usage priors. Struggle + pad zeroed."""
    mask = np.zeros((encoder.n_species, encoder.n_moves), dtype=np.float32)
    matched = 0
    for sp_name, entries in priors.items():
        sid = encoder.species_idx.get(sp_name)
        if not sid:
            continue
        matched += 1
        for e in entries:
            mid = encoder.move_idx.get(e["move"])
            if mid:
                mask[sid, mid] = 1.0
    struggle_mid = encoder.move_idx.get("Struggle")
    if struggle_mid:
        mask[:, struggle_mid] = 0.0
    mask[:, 0] = 0.0
    if verbose:
        covered = mask[1:].sum(1)
        covered = covered[covered > 0]
        if covered.size:
            print(f"Move mask: {matched} species, avg={covered.mean():.1f} moves/species")
    return torch.from_numpy(mask)


def save_checkpoint(path, model, *, epoch, val_loss, val_acc,
                    val_move_acc, val_switch_acc, encoder_v=2,
                    arch=None, val_target_acc=None):
    """Save a training checkpoint. `arch` lets loaders pick the right class."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if arch is None:
        arch = "v3" if getattr(model, "OUTPUTS", 6) == 8 else "v2"
    payload = {
        "model_state": model.state_dict(),
        "epoch": epoch,
        "val_loss": val_loss,
        "val_acc": val_acc,
        "val_move_acc": val_move_acc,
        "val_switch_acc": val_switch_acc,
        "encoder_v": encoder_v,
        "arch": arch,
    }
    if val_target_acc is not None:
        payload["val_target_acc"] = val_target_acc
    torch.save(payload, path)


def load_checkpoint(path, model, device="cpu"):
    """Load state dict into `model` and set eval mode. Returns the raw ckpt dict."""
    ckpt = torch.load(path, map_location=device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    return ckpt
