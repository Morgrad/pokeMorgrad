> Paths in this file are repo-relative (resolved at runtime via
> `src/paths.py`). For current project status see `STATE.md` and the root
> `README.md`.

# Pokémon AI Project — Glossary

Last updated: 2026-10-14

Reference for every acronym, term, and piece of jargon used in this project.
Grouped by category. If a term appears in a log, file name, or conversation
and is not here, add it.

---

## 1. Game / VGC

| Term | Meaning |
|---|---|
| VGC | Video Game Championships — official Pokémon competitive format |
| Reg | Regulation — a ruleset cycle |
| M-C | Regulation M-C — our target format (2026) |
| M-B | Regulation M-B — previous regulation |
| OTS | Open Team Sheets — opponent sees your full 6 at preview |
| CTS | Closed Team Sheets — opponent sees only species |
| Bo1 / Bo3 | Best of 1 / Best of 3 |
| BST | Base Stat Total — sum of a species' 6 base stats |
| EV | Effort Value — stat investment; 66 total, 32 per stat cap in our format |
| IV | Individual Value — innate stat range; always 31 in VGC |
| HP / Atk / Def / SpA / SpD / Spe | The six stats |
| KO / OHKO / 2HKO | Knock Out / one hit / two hits |
| STAB | Same Type Attack Bonus — +50% damage when move type matches user |
| TR | Trick Room — speed-inverting field effect |
| TW | Tailwind — doubles team speed for 4 turns |
| Mega | Mega Evolution — mid-battle transformation via held stone |
| Tera | Terastallization — Gen 9 mechanic, not in our format |
| Preview | Team Preview — pick 4 of 6 before battle |
| Meta | The dominant strategy set at a given time |
| Archetype | A team style: rain, sand, Trick Room, Psyspam, etc. |
| Species clause | No duplicate species on a team |
| Item clause | No duplicate items on a team |

---

## 2. Machine Learning

| Term | Meaning |
|---|---|
| ML / DL | Machine Learning / Deep Learning |
| NN | Neural Network |
| RL | Reinforcement Learning |
| BC | Behavior Cloning — imitate human play |
| IL | Imitation Learning — same as BC |
| GA | Genetic Algorithm — evolution-based search |
| MCTS | Monte Carlo Tree Search |
| PPO | Proximal Policy Optimization — RL algorithm |
| SOTA | State Of The Art |
| MDP / POMDP | Markov Decision Process / Partially Observable |
| CNN / RNN / LSTM / Transformer | Network architectures |
| LLM | Large Language Model |
| SGD / Adam | Optimizers |
| LR | Learning Rate |
| CE | Cross Entropy — multi-class loss |
| NLL | Negative Log Likelihood |
| Dropout | Regularization technique |

---

## 3. Statistics

| Term | Meaning |
|---|---|
| SE | Standard Error — noise measure, sqrt(p(1-p)/N) |
| CI | Confidence Interval |
| N | Sample size (battles) |
| sigma / mu | Standard deviation / mean |
| p-value | Probability under the null hypothesis |
| Wilson CI | Binomial confidence interval that stays inside [0,1] at small N |
| Binomial noise | The intrinsic variance in a win-rate measurement |
| Noise floor | The smallest change in win rate that is distinguishable from noise |

---

## 4. GA concepts

| Term | Meaning |
|---|---|
| Genome | A candidate team — 6 mons with moves/items/natures/EVs |
| Population | Set of genomes in one generation |
| Generation | One evolve cycle: evaluate, sort, breed |
| Elite | Top-ranked genome, copied unchanged into next gen |
| Crossover | Combine two parent genomes |
| Mutation | Random change to one genome (species, item, move, etc.) |
| Island | Independent sub-population; the v6 model runs 3 |
| Migration | Copy top genomes between islands (ring topology) |
| Stagnation | N generations with no improvement; triggers restart |
| Diversity floor | Minimum unique-species count in an island |
| Immigrant | Freshly random genome, injected to break convergence |
| Fitness | Win rate against a sampled opponent pool |
| Pool | Opponent team set (the 545 top-cut teams) |
| Train pool | 270 teams sampled for fitness (of the 300-team split) |
| Validation slice | 30 teams held back from fitness; used for champion selection |
| Held-out pool | 100 teams never seen during GA; final eval only |
| Foreign lock | A species locked on island X but not Y, present in an immigrant |
| Constraint | A locked slot, e.g. `{0: "Umbreon"}` |
| Island spec | The full config for one island: name, constraints, seed paths |
| Early stop | Aborting a genome's evaluation after a head batch if clearly bad |
| Champion | Best genome from an island, selected by validation score |

---

## 5. BC / encoder

| Term | Meaning |
|---|---|
| Encoder | Battle state to tensors |
| cont[] | 17-dim continuous vector per mon (HP, boosts, status, etc.) |
| field[] | 17-dim field vector (weather, terrain, TR, tailwind) |
| Slot | One of 12 mon positions: my-2-active, my-4-bench, opp-2-active, opp-4-seen |
| Move mask | Per-species allowed-moves mask from usage priors |
| Live moveset mask | Inference-time mask built from the acting mon's current 4 moves |
| Move priors | Top-N moves by tournament usage per species |
| Meta items | Item frequency per species from real top-cut teams |
| Canonical items | Fallback item list for species without meta entries |
| Role | physical / special / support — determined from base stats |
| Preferred pool | Moves matching the role + Status moves |
| Fallback pool | Off-role moves, used only if preferred pool is short |
| side_won | Boolean per training row: did this side win? Used for oversampling |
| Checkpoint contract | Frozen names and dimensions that must not change (arch, N_TARGETS, etc.) |
| arch | Checkpoint field: "v2" (MLP) or "v3" (transformer) |

---

## 6. Model constants (frozen by checkpoint)

| Name | Value | Meaning |
|---|---|---|
| N_SLOTS | 12 | Slots in the state encoder (2+4+2+4) |
| N_MOVES_PER | 4 | Moves per mon |
| CONT_DIM | 17 | Continuous feature width per mon |
| N_TARGETS | 5 | Target classes: our left, our right, none, opp left, opp right |
| EMB_SPECIES / EMB_MOVE / EMB_ITEM / EMB_ABILITY | 32 / 16 / 16 / 16 | Embedding sizes |
| NEG_INF | -1e4 | Mask sentinel; -inf produces NaN in the loss |

---

## 7. GA tuning constants (in src/ga_core.py)

| Name | Default | Meaning |
|---|---|---|
| META_ITEM_BIAS | 0.70 | Probability of drawing an item from meta prior |
| EV_BUDGET / EV_STAT_CAP | 66 / 32 | EVs handed out per mutated spread |
| MAX_REBUILD_TRIES | 20 | Rebuild attempts before dropping an illegal genome |
| BATTLE_TIMEOUT | 20 | Seconds before a battle is abandoned |
| MIN_TURNS | 3 | Battles shorter than this are dropped as desyncs |
| SEED_POOL | 30 | First N regional teams used to seed a random population |
| VAL_POOL_SIZE / VAL_SPLIT_SEED | 30 / 42 | Validation-slice size and split seed |
| EARLY_STOP_MIN_BATTLES | 50 | Head batch size before early-abort decision |
| EARLY_STOP_WIN_RATE | 0.15 | Below this head rate, the tail is skipped |
| PROTECT_MOVES / FAKEOUT_MOVES | tuple | Required-coverage move sets |
| CANONICAL_ITEMS | tuple | Fallback item pool |

---

## 8. Code and files

| File | Purpose |
|---|---|
| src/paths.py | Repo-relative path resolution, single source of truth |
| src/regmc_db.py | Canonical data access + team validator |
| src/state_encoder.py | Battle state to tensors |
| src/bc_model.py | BCModel (v2) and BCModelV3 definitions + checkpoint I/O |
| src/bc_train.py | BC training loop |
| src/bc_player.py | poke_env Player wrapping the BC model |
| src/ga_core.py | GA engine: genome build, mutate, crossover, islands |
| src/battle.py | Shared battle runner (make_player, run_battle) |
| src/eval.py | Unified evaluation CLI |
| src/audit_before_launch.py | Pre-flight data-integrity checks |
| src/showdown_validator.py | Python wrapper around the Node validator |
| src/showdown_validate.js | Node bridge |
| run/ga_run.py | 5.5-hour GA launcher |
| run/ga_overnight.sh | 11-hour chain: run1 + run2 + eval |
| tools/preflight.py | Pre-launch sanity checks |
| tools/bc_diagnostic.py | BC vs heuristic decision comparison |
| tools/encode_snapshot.py | Capture/compare encoder output for bit-exactness |
| tools/build_regmc_db.js | Rebuild canonical DB from Showdown |
| tools/scrape_replays.py | Replay scraper |
| tools/replay_tracker.py | Replay parser (Tracker class) |
| tools/build_training_data.py | Training-data driver: replays to training_data.jsonl |
| tools/generate_heuristic_dataset.py | Heuristic-imitation dataset generator |
| tools/build_species_priors.py | Build species_move_priors.json |

---

## 9. Data files

| File | Purpose |
|---|---|
| data/regmc_db.json | Canonical format data (species, moves, items, abilities) |
| data/baseline_team.txt | Reference team, GA seed for island A |
| data/pool_split.json | Train/holdout split (300/100), basenames |
| data/meta_items.json | Item frequency per species from tournament usage |
| data/species_move_priors.json | Top moves by usage per species |
| data/regional_teams/ | 150 VGCPastes teams (real EVs); 100 holdout; 445 archived under `_archive_2026-10-15/` |
| data/showdown_replays/ | Scraped replays (gitignored, regenerable) |
| data/training_data.jsonl | Parsed decisions (gitignored, regenerable) |
| data/training_data_heuristic.jsonl | Heuristic-imitation rows (gitignored) |
| output/models/ | Trained checkpoints |
| output/champions/ | GA-produced team files |
| output/checkpoints/v6/run{1,2}/ | Per-generation GA snapshots |

---

## 10. Tools and infrastructure

| Term | Meaning |
|---|---|
| Showdown | Pokémon Showdown — the battle simulator |
| Node | Node.js runtime; Showdown is written in it |
| poke_env | Python library we use to talk to Showdown |
| ROCm | AMD GPU compute stack |
| WSL | Windows Subsystem for Linux |
| GPU / CPU | Graphics / Central Processing Unit |
| HTTP / URL / UA | Web protocol, address, user agent |
| RNG | Random Number Generator |
| PID | Process ID |
| JSON / JSONL | Data formats |
| venv | Python virtual environment (~/llm-env) |
| preflight | The pre-launch check script |

---

## 11. Log fields

BC training epoch line:

    Epoch NN/30  trl=X tra=X trm=X trs=X  vll=X vla=X vlm=X vls=X  (Ns) *

| Code | Meaning |
|---|---|
| trl / vll | Train / val loss |
| tra / vla | Train / val overall action accuracy |
| trm / vlm | Train / val move-head accuracy (masked) |
| trs / vls | Train / val switch-head accuracy |
| (Ns) | Wall-clock seconds for the epoch |
| * | New best val_move_acc; checkpoint saved |

GA line:

    [HH:MM:SS]  3/10  47.0%  (141W/300)  Umbreon / Salamence / ...

| Field | Meaning |
|---|---|
| HH:MM:SS | Wall clock at print time |
| 3/10 | Third genome of ten this generation |
| 47.0% | Fitness (win rate) |
| 141W/300 | Wins out of valid battles played |
| early-abort | Genome was aborted after the head batch |
| species list | The genome's species in slot order |

---

## 12. Path labels (roadmap)

| Label | Meaning | Status |
|---|---|---|
| Path 2 | Hand-coded doubles-aware pilot | Fallback |
| Path 3 | BC + RL pilot from replays | Current plan |

Older/deprecated: Path A / B / C.

---

## 13. Things that sound alike

| A | B | Difference |
|---|---|---|
| SimpleHeuristics / MaxBasePowerPlayer | Built-in poke_env bots; SH is stronger | |
| Reg M-C / Reg M-B | Different regulations | |
| Bo1 / OTS | Best-of format vs team-sheet visibility, independent axes | |
| Genome / Champion | Candidate vs best-found | |
| Fitness / Win rate | Fitness is what GA optimizes; usually equal to win rate | |
| Population / Pool | GA's genomes vs opponent teams | |
| Pool / Held-out | Training pool vs test set | |
| Train / Eval | 270 teams for GA, 100 held out | |
| Pilot / Player | Same thing; "pilot" emphasizes it plays a fixed team | |
| Row-level / Battle-level split | The second avoids leakage; use battle-level | |
| Role / Category | Role is a species classification; Category is a move property | |

---

## 14. Project history highlights

Terms and names from earlier iterations, kept here so older logs remain
readable.

| Term | Meaning | Superseded by |
|---|---|---|
| v1 / v2 / v3 encoder | Earlier embedding models | v4 (currently v2/v3 in BCModel/BCModelV3) |
| bc_train_v4.py | Original BC trainer filename | bc_train.py |
| ga_core_v6.py | Island-model extension | Merged into ga_core.py |
| state_encoder_v2.py | Original encoder filename | state_encoder.py |
| batch_parse.py | Legacy data driver (pre-side_won) | build_training_data.py |
| opponent_gen.py | Old team generator | Archived, unused |
| Path 3 | BC+RL plan label | Still current |
| NeuralPlayer | Original v1 pilot | Archived |

---

## 15. How to extend this file

Add an entry when:
- A new acronym is introduced
- A new file enters the pipeline
- A new constant becomes important
- An ambiguity keeps causing confusion

Keep entries terse. One line each where possible.

---

## 17. Pool sources and swap (2026-10-15)

| Term | Meaning |
|---|---|
| VGCPastes | Community repo of tournament team pastes; source of real EVs |
| Pokepaste | pastebin for teams; `/raw` returns Showdown text |
| Real EVs | EV spreads extracted from tournament pastes (not inferred) |
| Inferred EVs | Canonical role spreads (2/32/32 etc); pre-swap default |
| Golden holdout | `pool_split_golden.json`; frozen 100-team eval set |
| Train champion | Genome by best training fitness (default 2026-10-15) |
| Val champion | Genome by best 30-team validation score (legacy) |
| Signature dedup | `sorted([(species, item) for mon in team])` |
| HYPERLINK formula | Sheets cell type that CSV export loses |
| Watchdog | `tools/watch_islands.py`; SIGKILLs stalled islands |
| WSL sleep mask | `systemctl mask sleep.target ...`; no overnight suspend |



---

## 16. Parallel architecture (2026-10-14)

| Term | Meaning |
|---|---|
| Parallel GA | Three processes, three islands, three Showdown instances |
| Island process | One `python -m run.ga_island` invocation, drives one island |
| SHOWDOWN_PORT | Env var; routes a process to its own Showdown instance |
| Val champion | Genome picked by val-slice score; `ga_<run>_island_<X>.txt` |
| Train champion | Genome picked by training fitness; `..._train.txt` suffix |
| Ring migration | Cross-island genome exchange (serial mode only) |
| Louisville | 5th tournament added to the pool 2026-10-14 (145 teams) |
| Bridge eval | Re-evaluating old champions on the new holdout after a pool change |

