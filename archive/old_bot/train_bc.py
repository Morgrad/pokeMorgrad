import json
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from collections import Counter
import numpy as np

# ---------- Build vocabularies from the data ----------
print("Loading parsed replays...")
with open("parsed_replays.jsonl") as f:
    replays = [json.loads(l) for l in f]
print(f"  Loaded {len(replays)} replays")

species_counter = Counter()
move_counter = Counter()
for r in replays:
    species_counter.update(r["p1_team"])
    species_counter.update(r["p2_team"])
    for t in r["turns"]:
        for a in t["p1_actions"] + t["p2_actions"]:
            if a["type"] == "move":
                move_counter[a["move"]] += 1

# Keep only moves with >= 5 uses to reduce noise
move_vocab = {m: i for i, (m, c) in enumerate(move_counter.most_common()) if c >= 5}
species_vocab = {s: i for i, (s, c) in enumerate(species_counter.most_common())}

N_SPECIES = len(species_vocab)
N_MOVES = len(move_vocab)
print(f"  Species vocab: {N_SPECIES}")
print(f"  Move vocab:    {N_MOVES}")

# ---------- Build (state, action) pairs ----------
# State = (active species, opponent active species, turn number)
# Action = move chosen (we ignore switches for now)

print("\nBuilding training pairs...")
pairs = []
for r in replays:
    # Track active Pokémon per side
    p1_active = None
    p2_active = None
    for t in r["turns"]:
        for a in t["p1_actions"]:
            if a["type"] == "switch":
                p1_active = a["to"]
            elif a["type"] == "move" and p1_active and p2_active:
                if a["move"] in move_vocab:
                    pairs.append((p1_active, p2_active, t["turn"], a["move"]))
        for a in t["p2_actions"]:
            if a["type"] == "switch":
                p2_active = a["to"]
            elif a["type"] == "move" and p1_active and p2_active:
                if a["move"] in move_vocab:
                    pairs.append((p2_active, p1_active, t["turn"], a["move"]))

print(f"  Training pairs: {len(pairs)}")

# ---------- Dataset ----------
class BattleDataset(Dataset):
    def __init__(self, pairs, species_vocab, move_vocab):
        self.data = []
        for my_s, opp_s, turn, move in pairs:
            if my_s not in species_vocab or opp_s not in species_vocab:
                continue
            my_idx = species_vocab[my_s]
            opp_idx = species_vocab[opp_s]
            move_idx = move_vocab[move]
            self.data.append((my_idx, opp_idx, min(turn, 20), move_idx))
    def __len__(self): return len(self.data)
    def __getitem__(self, i):
        my, opp, turn, move = self.data[i]
        return torch.tensor([my, opp, turn], dtype=torch.long), torch.tensor(move, dtype=torch.long)

ds = BattleDataset(pairs, species_vocab, move_vocab)
dl = DataLoader(ds, batch_size=256, shuffle=True)
print(f"  Dataset size: {len(ds)}")

# ---------- Model ----------
class MovePredictor(nn.Module):
    def __init__(self, n_species, n_moves, embed_dim=32):
        super().__init__()
        self.species_emb = nn.Embedding(n_species, embed_dim)
        self.opp_emb = nn.Embedding(n_species, embed_dim)
        self.turn_emb = nn.Embedding(21, 8)
        self.net = nn.Sequential(
            nn.Linear(embed_dim * 2 + 8, 256),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(256, 256),
            nn.ReLU(),
            nn.Linear(256, n_moves),
        )
    def forward(self, x):
        my = self.species_emb(x[:, 0])
        opp = self.opp_emb(x[:, 1])
        turn = self.turn_emb(x[:, 2])
        h = torch.cat([my, opp, turn], dim=-1)
        return self.net(h)

# ---------- Train on GPU ----------
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"\nTraining on: {device}")
if device.type == "cuda":
    print(f"  GPU: {torch.cuda.get_device_name(0)}")

model = MovePredictor(N_SPECIES, N_MOVES).to(device)
optimizer = optim.Adam(model.parameters(), lr=1e-3)
loss_fn = nn.CrossEntropyLoss()

EPOCHS = 10
for epoch in range(EPOCHS):
    model.train()
    total_loss, correct, total = 0, 0, 0
    for x, y in dl:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        logits = model(x)
        loss = loss_fn(logits, y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        correct += (logits.argmax(dim=-1) == y).sum().item()
        total += y.size(0)
    acc = 100 * correct / total
    print(f"Epoch {epoch+1:>2}/{EPOCHS}  loss={total_loss/len(dl):.4f}  acc={acc:.1f}%")

torch.save(model.state_dict(), "bc_model.pt")
print("\n✅ Saved model to bc_model.pt")

# Save vocabularies so we can reload them later
with open("vocab.json", "w") as f:
    json.dump({"species": species_vocab, "moves": move_vocab}, f)
print("✅ Saved vocab to vocab.json")
