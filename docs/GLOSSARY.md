> ℹ️ Paths in this file are **repo-relative** (resolved at runtime via
> `src/paths.py`). For current project status see [`STATE.md`](STATE.md) and the
> root [README](../README.md).

# Pokémon AI Project — Glossary

Last updated: 2026-10-13

A single reference for every acronym, term, and piece of jargon used in this
project. Grouped by category. If you see a term in a log, file name, or
conversation that isn't here, add it.

---

## 1. Game / VGC (Pokémon Video Game Championships)

| Term | Meaning | Notes |
|---|---|---|
| **VGC** | Video Game Championships | Official Pokémon competitive format |
| **Reg** | Regulation | A ruleset cycle, e.g. Reg M-C |
| **M-C** | Regulation M-C | Our target format (2026) |
| **M-B** | Regulation M-B | Previous regulation |
| **OTS** | Open Team Sheets | Opponent sees your full 6 at preview |
| **CTS** | Closed Team Sheets | Opponent sees only species (opposite of OTS) |
| **Bo1** | Best of 1 | One game decides the match |
| **Bo3** | Best of 3 | Up to three games; first to 2 wins |
| **BSS** | Battle Stadium Singles | Singles ladder (not our format) |
| **BST** | Base Stat Total | Sum of a species' 6 base stats |
| **EV** | Effort Value | Stat investment; 32 per stat, 66 total in our format |
| **IV** | Individual Value | Innate stat range; always 31 in VGC |
| **HP** | Hit Points | Health stat |
| **Atk** | Attack | Physical damage stat |
| **Def** | Defense | Physical defense stat |
| **SpA** | Special Attack | Special damage stat |
| **SpD** | Special Defense | Special defense stat |
| **Spe** | Speed | Turn order stat |
| **KO** | Knock Out | Faint |
| **OHKO** | One-Hit KO | Faint in one hit |
| **2HKO** | Two-Hit KO | Faint in two hits |
| **STAB** | Same Type Attack Bonus | +50% damage when move type matches user |
| **TR** | Trick Room | Speed-inverting field effect |
| **TW** | Tailwind | Doubles team speed for 4 turns |
| **Mega** | Mega Evolution | Mid-battle transformation via held stone |
| **Tera** | Terastallization | Gen 9 mechanic (may appear in future formats) |
| **Preview** | Team Preview | 30 seconds to pick 4 of 6 mons |

---

## 2. Machine Learning / AI

| Term | Meaning | Notes |
|---|---|---|
| **AI** | Artificial Intelligence | Umbrella term |
| **ML** | Machine Learning | Learning from data |
| **DL** | Deep Learning | ML with neural nets |
| **NN** | Neural Network | The model type |
| **RL** | Reinforcement Learning | Learn by reward |
| **BC** | Behavior Cloning | Imitate human play |
| **GA** | Genetic Algorithm | Evolution-based search |
| **MCTS** | Monte Carlo Tree Search | Game-tree search |
| **IL** | Imitation Learning | Same as BC |
| **PPO** | Proximal Policy Optimization | RL algorithm (used by vgc-bench) |
| **DQN** | Deep Q-Network | Classic RL algorithm |
| **SOTA** | State Of The Art | Best available result |
| **MDP** | Markov Decision Process | RL formalism |
| **POMDP** | Partially Observable MDP | RL with hidden state (our case) |
| **CNN** | Convolutional Neural Network | Image-oriented net |
| **RNN** | Recurrent Neural Network | Sequence-oriented net |
| **LSTM** | Long Short-Term Memory | RNN variant |
| **Transformer** | Attention-based net | Modern default |
| **LLM** | Large Language Model | GPT-style text model |
| **GPT** | Generative Pre-trained Transformer | LLM family |
| **BERT** | Bidirectional Encoder Representations from Transformers | Encoder LLM |
| **SGD** | Stochastic Gradient Descent | Optimizer |
| **Adam** | Adaptive Moment Estimation | Optimizer (common default) |
| **LR** | Learning Rate | How big each update is |
| **BCE** | Binary Cross Entropy | Loss for binary classification |
| **CE** | Cross Entropy | Loss for multi-class classification |
| **MSE** | Mean Squared Error | Loss for regression |

---

## 3. Statistics

| Term | Meaning | Notes |
|---|---|---|
| **SE** | Standard Error | Noise measure: `sqrt(p(1-p)/N)` |
| **CI** | Confidence Interval | Range containing true value with X% probability |
| **N** | Sample size | Number of battles |
| **σ** | Sigma (standard deviation) | Spread of a distribution |
| **μ** | Mu (mean) | Average value |
| **p-value** | Probability under null hypothesis | Small = unlikely by chance |
| **p̂** | Sample proportion | Observed win rate |

---

## 4. Our Project — Core Concepts

| Term | Meaning | Notes |
|---|---|---|
| **Genome** | A candidate team | Represented as 6 mons with moves/items/etc. |
| **Population** | Set of genomes | Current generation's candidates |
| **Generation** | One evolution cycle | Evaluate → sort → breed |
| **Elite** | Top-ranked genome | Kept unchanged into next gen |
| **Crossover** | Combine two parents | Mix 6 slots from each |
| **Mutation** | Random change | Swap species, move, item, etc. |
| **Island** | Independent sub-population | 3 islands in v6 |
| **Migration** | Copy genomes between islands | Ring topology, every 5 gens |
| **Stagnation** | No improvement for N gens | Triggers restart |
| **Diversity floor** | Min species count in pop | Below → inject randoms |
| **Immigrant** | Freshly random genome | Injected to break convergence |
| **Fitness** | Win rate vs opponent pool | Single number per genome |
| **Pool** | Opponent team set | 400 regional top-cuts, split 300/100 |
| **Held-out** | Test set never seen in training | 100 teams for final eval |
| **Train pool** | Fitness evaluation set | 300 teams sampled randomly |
| **Pilot** | Who plays the battles | Heuristic (working baseline) or BC pilot (functional but weak) |
| **Team preview** | Pick 4 of your 6 | Strategic phase before battle |
| **Meta** | The dominant strategy set | What most top players run |
| **Archetype** | A team style | Rain, Sand, Trick Room, etc. |
| **Species clause** | No duplicate species | Format rule |
| **Item clause** | No duplicate items | Format rule |

---

## 5. Our Project — Code & Files

| File | Purpose |
|---|---|
| `src/paths.py` | Repo-relative path resolution — single source of truth for file locations |
| `src/regmc_db.py` | Canonical data access + team validator |
| `data/regmc_db.json` | Canonical DB (species, items, moves, abilities) |
| `src/ga_core.py` | GA engine — base (species-level) + island model + checkpointing |
| `src/state_encoder.py` | Battle state → tensors for the BC model |
| `src/bc_model.py` | Neural net definition + checkpoint I/O |
| `src/bc_train.py` | BC training loop |
| `src/bc_player.py` | poke_env Player wrapping the BC model |
| `src/eval.py` | Unified evaluation CLI |
| `src/audit_before_launch.py` | Pre-flight sanity checks |
| `src/showdown_validator.py` | Showdown legality gate |
| `src/showdown_validate.js` | Node.js validator bridge |
| `run/ga_run.py` | 5-hour GA launcher |
| `run/ga_overnight.sh` | 10-hour chain (run1 + run2 + eval) |
| `tools/build_regmc_db.js` | Rebuild canonical DB from Showdown |
| `tools/scrape_replays.py` | Replay scraper |
| `tools/replay_tracker.py` | Replay parser (Tracker class) |
| `tools/build_training_data.py` | THE training-data driver: replays → `training_data.jsonl` (tags `side_won`/`target_a`/`target_b`) |
| `tools/batch_parse.py` | Legacy driver (pre-`side_won` schema) — archived, do not regenerate with it |
| `tools/build_species_priors.py` | Build `species_move_priors.json` |
| `data/pool_split.json` | Train/held-out split (300/100), basenames |
| `data/meta_items.json` | Item frequency per species from real teams |
| `data/showdown_replays/` | Scraped replays (training data) |
| `data/regional_teams/` | 400 top-cut teams (opponent pool) |
| `output/champions/` | GA-produced team files |
| `output/checkpoints/v6/` | Per-gen checkpoints |
| `docs/STATE.md` | Current project state (short) |
| `docs/STATE_history.md` | Full chronological log |
| `docs/GLOSSARY.md` | This file |

---

## 6. Our Project — Paths (Roadmap Labels)

| Path | Meaning | Status |
|---|---|---|
| **Path 2** | Hand-coded doubles-aware pilot | Fallback if Path 3 fails |
| **Path 3** | BC + RL pilot from replays | **Current plan** |

Older/deprecated Path labels from earlier discussions:
- Path A / B / C — superseded by Path 2/3 naming

---

## 7. Tools & Infrastructure

| Term | Meaning | Notes |
|---|---|---|
| **Showdown** | Pokémon Showdown | Battle simulator, runs on localhost:8000 |
| **Node** | Node.js | JavaScript runtime (runs Showdown) |
| **poke_env** | Python library | Battle interface used by all our pilots |
| **ROCm** | Radeon Open Compute | AMD GPU compute stack |
| **WSL** | Windows Subsystem for Linux | How we run Linux on Windows |
| **GPU** | Graphics Processing Unit | 7900 XTX in our case |
| **CPU** | Central Processing Unit | |
| **API** | Application Programming Interface | |
| **CLI** | Command Line Interface | |
| **PID** | Process ID | Unix process identifier |
| **HTTP(S)** | HyperText Transfer Protocol (Secure) | Web protocol |
| **URL** | Uniform Resource Locator | Web address |
| **UA** | User Agent | HTTP header identifying the client |
| **RNG** | Random Number Generator | |
| **ETA** | Estimated Time of Arrival | Used in progress logs |
| **JSON** | JavaScript Object Notation | Data format |
| **JSONL** | JSON Lines | One JSON object per line |

---

## 8. Common Log Terms

| Term | Meaning |
|---|---|
| **TB** | TensorBoard | Training visualization (used by vgc-bench, not our GA) |
| **fps** | Frames per second | Training throughput (steps/sec in our context) |
| **log_level=40** | Python logging level | 40 = ERROR only (silent training) |
| **popup** | Showdown server rejection message | "Your team was rejected..." |
| **forfeit** | Battle conceded early | Counted separately in fitness |
| **ALL-TIME** | Best genome seen so far | Persisted to champion file |
| **NEW ALL-TIME** | Log message | When an island sets a new best |

---

## 9. Hosts / URLs

| URL | Purpose |
|---|---|
| `play.pokemonshowdown.com` | Main Showdown server |
| `replay.pokemonshowdown.com` | Public replay database |
| `replay.pokemonshowdown.com/search.json` | Replay search API |
| `replay.pokemonshowdown.com/<id>.json` | Individual replay |
| `limitlessvgc.com` | Regional tournament data |
| `play.limitlesstcg.com` | Online tournament data (older scrape) |
| `localhost:8000` | Our training Showdown server |
| `localhost:8001` | Our eval / probe Showdown server |
| `localhost:6006` | TensorBoard (vgc-bench only) |

---

## 10. Things That Sound Alike But Aren't

| Term A | Term B | Difference |
|---|---|---|
| SimpleHeuristics | MaxBasePowerPlayer | Both built-in bots; SH is slightly smarter |
| Reg M-C | Reg M-B | Different regulations (M-C is current) |
| Bo1 / Bo3 | OTS / CTS | Best-of format vs team sheet visibility — independent axes |
| Genome | Champion | Genome is any candidate; champion is the best found |
| Fitness | Win rate | Fitness is what GA optimizes (usually = win rate) |
| Population | Pool | Population = GA's genomes; Pool = opponents |
| Pool | Held-out | Pool = training data; held-out = test set |
| Train | Eval | Train uses 300 teams; eval uses 100 different ones |
| Pilot | Player | Same thing; "pilot" emphasizes that it plays a fixed team |

---

---

## 11. BC Training Metrics (Log Fields)

Printed once per epoch by `src/bc_train.py`. Format:

    Epoch NN/30  trl=X tra=X trm=X  vll=X vla=X vlt3=X vlm=X  (Ns) *

| Code | Meaning | Notes |
|---|---|---|
| **trl** | train loss | Sum of 3 heads (type + move + switch) |
| **tra** | train accuracy | Overall action accuracy (move OR switch correct) |
| **trm** | train move accuracy | Move-head top-1 accuracy among masked moves |
| **trt3** | train top-3 | Move-head top-3 accuracy (is correct move in top 3?) |
| **vll** | val loss | Validation loss — used for early stopping |
| **vla** | val accuracy | Overall action accuracy on held-out examples |
| **vlm** | val move accuracy | **Primary metric** — val move-head top-1 with mask |
| **vlt3** | val top-3 | Val move-head top-3 accuracy |

### Reference values (May 2026 Reg M-C, ~100k examples)

| Metric | Random | Always-most-common | Bad model | Good model |
|---|---|---|---|---|
| vlm (masked) | ~5% (1 of 20) | ~15% | <25% | **>40%** |
| vlt3 | ~15% | — | <50% | **>70%** |
| vla | 0.1% | ~10% | <25% | **>35%** |

### Version history

| Model | Encoder | Model size | val_acc | val_move_acc |
|---|---|---|---|---|
| v1 | one-hot, 16.9k dims | 18M params | 21% | n/a |
| v2 | embeddings, dict | 1.3M params | 19% | n/a |
| v3 | v2 + species move masking | 1.3M params | (running) | (running) |

### Metric abbreviations, short form

- `tr*` = train
- `vl*` = val
- `*l` = loss
- `*a` = overall accuracy
- `*m` = move accuracy
- `*t3` = top-3 accuracy
- Suffix ` *` after epoch line = new best val_loss (checkpoint saved)
- `noimp=N` = N epochs without improvement (early stops at 3)

## 12. How to Extend This File

Add entries here when:
- A new acronym is introduced
- A new file enters the pipeline
- A new path label is created
- An ambiguity keeps causing confusion

Keep entries terse. One line each when possible.

## Project-specific terms

| Term | Meaning |
|---|---|
| **side_won** | Boolean per training row: did the side that made this decision ultimately win the replay? Used by `bc_train.py` for outcome-weighted oversampling (winner decisions contribute 2× gradient weight). |
| **live moveset mask** | At inference time, mask any move the acting Pokémon doesn't actually know (from its current 4-move set). More accurate than `species_move_priors.json`, which only covers species that appear in the priors file. |
| **move target** | In Showdown doubles, single-target moves must be sent with a slot number (1 = opp left, 2 = opp right, -1 = our left ally, -2 = our right ally). Self/field/side/spread moves must NOT have one — `regmc_db.get_move(name)["target"]` decides which. |
| **island** | A population in the island-model GA. Each island has its own constraints (e.g. island A locks Umbreon in slot 0). Migration every N generations carries top genomes to the next island. |
| **foreign lock** | A species locked on island X but not island Y, appearing in an immigrant genome on island Y. `_strip_species` replaces these on migration. |
| **held-out pool** | The 100 teams in `pool_split.json["holdout"]` never seen during GA. Used for honest final eval. |
| **train pool** | The 300 teams in `pool_split.json["train"]` used for GA fitness. |
