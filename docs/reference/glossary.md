# Glossary

Terms, acronyms and jargon used in pokeMorgrad code, logs and docs, grouped by area, with the
current meaning checked against the code. Read it when a word in a log, file or doc is
unclear. Constants, file tables and log-line formats are in `glossary-constants.md`.

Last verified against code: 2026-11-18

Format facts (always true here): `gen9championsvgc2026regmc` (Reg M-C, Champions mod),
doubles, Mega Evolution legal, Terastallization NOT legal, EVs 0-32 per stat, total 66,
stat term `max(2*pts-1, 0)`.

## 1. Game / VGC

| Term | Meaning |
|---|---|
| VGC | Video Game Championships, the official doubles format |
| Reg M-C | Regulation M-C, our target ruleset (2026). M-B is the previous one |
| Champions EV / points | 0-32 per stat, 66 total; stat term `max(2*p-1, 0)`, not mainline EVs/4 |
| IV | Individual value, always 31 here |
| BST | Base stat total |
| STAB | Same-type attack bonus (x1.5) |
| KO / OHKO / 2HKO | Knock out / in one hit / in two hits |
| TR / TW | Trick Room (speed order inverted) / Tailwind (side speed x2 for 4 turns) |
| Mega | Mega Evolution via a held stone, once per side. Z-line Megas (Absol-Mega-Z, Garchomp-Mega-Z, Lucario-Mega-Z) are separate forms from the plain Mega |
| Tera | Terastallization: NOT legal in this format, never modelled |
| OTS / CTS | Open / Closed Team Sheets. OTS shows items, abilities, moves, natures at preview; opt-in on ladder (~1.5% of games), forced in Bo3 |
| Bo1 / Bo3 | Best of 1 / 3. Current goal is ladder (Bo1), Bo3 later |
| Preview | Team preview: bring 4 of 6 |
| Species clause / Item clause | No duplicate base species / no duplicate items on a team |
| Protect family | Protect, Detect, Spiky Shield, King's Shield, Baneful Bunker, Silk Trap, Burning Bulwark (and others in `PROTECT_FAMILY`) |
| Stall chain | Consecutive successful Protects; next success chance 1/3^chain (Wide Guard, Quick Guard, Mat Block excluded) |
| Pivot | Move that switches the user out (`Move.self_switch`) |
| Meta | What the ladder / top cuts actually play |
| Archetype (team) | A team style: rain, sand, Trick Room, Psyspam... |
| Archetype (set) | In `data/species_archetypes.json`: real sets of one species grouped by (item, nature), with spreads, move and ability counts |

## 2. GA

| Term | Meaning |
|---|---|
| Genome | One candidate team: list of 6 mon dicts `{species, item, ability, nature, evs, moves}` |
| Population / Island | Genomes of one generation / one independent sub-population (`src/ga/population.py::Island`) |
| Island spec | `{"name", "constraints", "seed_paths"}` for one island |
| Islands A / B / C | Today (`run/ga_island.py`, `run/ga_run.py`): A = Umbreon locked slot 0 + baseline seed, B = Umbreon locked, no seed, C = free |
| Constraint / lock | Slot pinned to a species, e.g. `{0: "Umbreon"}` |
| Foreign lock | A species locked on another island arriving in a migrant; `_strip_species` replaces it |
| Generation | Evaluate every genome, record bests, rescue diversity or restart, breed |
| Elite / Crossover / Mutation | Unchanged top genome / mix of two parents / random change of species, item, ability, nature, EVs or a move |
| Immigrant | Fresh random genome injected (immigration rate 0.20) |
| Diversity floor | Below 15 unique species, right after breeding, 3 bred children are replaced by fresh random genomes (`Island.inject_fresh`; skipped if a stagnation restart happens that generation) |
| Stagnation restart | After 5 generations without a new `best_ever`, right after breeding, half the population (children only, never the elites) is replaced by fresh random genomes and the counter resets (`Island.restart_stagnant`) |
| Ring migration | Top 2 genomes copied around the ring every 5 gens; serial `run/ga_run.py` only (parallel islands use `migration_every=999`) |
| Parallel GA | 3 processes, one island each, each on its own Showdown server (8000/8001/8002) |
| Fitness | Meta-weighted win rate of a genome over the battles that returned a result (`src/ga/fitness.py::weighted_fitness`) |
| Meta weight | Weight of one opponent team = mean ladder usage of its 6 species (`src/meta_weights.py`), unseen species 0.02 |
| Fitness pilot / opponent pilot | Who plays the battles: `vgc` (VGCPilot) vs `ladder` (LadderOpponent) by default (env `GA_PILOT` / `GA_OPP`) |
| Pool | Opponent teams in `data/regional_teams/` |
| Train pool | `pool_split.json["train"]` (148 teams); 30 of them are held back as the validation slice, the other 118 are the fitness pool |
| Validation slice | 30 train teams (`VAL_POOL_SIZE`, seed 42) never used for fitness; scores `best_val_ever` |
| Held-out pool / holdout | `pool_split.json["holdout"]` (100 teams); never seen by the GA; final eval only |
| Early stop / early-abort | Play 50 battles first; below 15% skip the rest (only when a genome has more than 50 opponents) |
| best_ever / best_val_ever | Island's all-time best by training fitness / by validation-slice score |
| Champion | Team file written at the end: primary `ga_<run>_island_<X>.txt` = `best_ever` (train-selected since 2026-10-15); `..._train.txt` = same genome |
| Train champion / Val champion | Selected by training fitness (current default) / by validation slice (legacy fallback) |
| Checkpoint | `output/checkpoints/v6/<run_id>/gen_NNNN.json`; newest always kept, older ones only every 5th gen |
| Run id | Name of a run (`run1`, `p3`, `q5`, ...); parallel islands use `<run_id>_<X>` internally |
| Realism constraint stack | Soft build rules from 2026-10-14: meta items, forced Protect, forced Fake Out/redirection, role-committed moves, priors |
| Role | physical / special / support from base stats (`_species_role`): support if max(Atk, SpA) < 80, else the higher side, coin flip when both >= 80 |
| Preferred / fallback pool | Role-matching moves + Status / off-role moves (used only when short) |
| Canonical items | Fallback item list for species without `meta_items.json` data |
| Golden test | `tests/test_ga_golden.py`: pins run_islands stdout, checkpoint JSON, champions and RNG use |
| Facade | `src/ga_core.py` re-exported `src/ga/` names for old imports; removed 2026-11-18 (old -> new names: `docs/reference/ga-old-names.md`) |

## 3. Pilots and simulation

| Term | Meaning |
|---|---|
| Pilot / player | The bot that plays a team (`src/player_factory.py::make_player` names: `heuristic`, `doubles`, `vgc`, `ladder`, `bc`) |
| SimpleHeuristicsPlayer / vanilla | poke_env's built-in heuristic (`heuristic`). Never Megas, never Protects/Fake Outs in doubles |
| DoublesPilot | `src/doubles_pilot.py`: vanilla decides, then attacks of both slots are re-allocated jointly; with `use_turn_sim` (default on) turn_sim picks the pair |
| VGCPilot | `src/vgc_pilot.py`: DoublesPilot + BattleMemory + Mega choice + foe action odds; our fitness pilot |
| TimeoutPlayer | `src/player_factory.py`: VGCPilot that forfeits after turn 50 (used for our side when pilot is `vgc`) |
| LadderOpponent | `src/ladder_opp.py`: heuristic that swaps in Protect / Fake Out at replay-fitted rates; GA opponent |
| SmartPlayer | `src/smart_player.py`: old KO-aware heuristic (lost 42.5% to vanilla); kept for helper functions |
| BCPlayer | `src/bc_player.py`: behavior-cloning pilot (`bc`) |
| turn_sim / TurnSim | `src/turn_sim.py` (+ `turn_sim_resolve.py::Resolution` for one scenario): expected-value simulation of one turn in move order with HP distributions, foe outcomes (attack / Protect / Fake Out / nothing), our Protect / Fake Out / switch candidates |
| Coarse / fine stage | turn_sim screens all pairs with 2 hypotheses, then re-scores the top 6 pairs with the full sim |
| Mirror foe | In turn_sim each foe picks its attack the way our pilot would, from its side |
| Hypothesis | One possible foe build (spread, item, ability, Mega form) with a probability |
| PASSIVE_COST | Value charged for a Protect / switch in turn_sim (0.30; env `DOUBLES_PASSIVE_COST`) |
| Support layer | Valuing support moves from move data (`src/support_value.py`): foulplay, snarl, charm, helpinghand, taunt, heal. On by default (`DEFAULT_SUPPORT = "all"`) |
| LookAhead | Multi-turn continuation term in turn_sim (`src/turn_sim_lookahead.py`); off by default (`DOUBLES_LOOKAHEAD`) |
| KO bonus | doubles_eval score bonus for P(KO): 1.0 (`src/doubles_eval.py::KO_BONUS`). SmartPlayer's separate `KO_BONUS` is 8.0 |
| Opponent model | `src/opp_model.py`: hidden foe builds from archetypes (>= 5 real sets) or blended priors |
| Speed model | `src/speed_model.py`: `p_faster` from the foe build mixture (Scarf share, Mega Speed); stage 2 (observed order) not built |
| Mega model | `src/mega_model.py`: P(foe Megas this turn) from replay-fitted rates; `mega_gain` picks which of our mons Megas |
| Opponent actions | `src/opp_actions.py`: P(Protect / Fake Out / Trick Room) per foe context, fitted on 5006 replays |
| BattleMemory | `src/battle_memory.py`: per-battle state poke_env lacks (Mega form/stone, conditions with turns, move order, Protect chain, volatiles, OTS), fed raw protocol lines |
| BattleMemoryMixin | Mixin before the poke_env Player that feeds every message line to BattleMemory first |
| Condition / turns_left | Timed field/side effect with start turn and setter / `(min, max)` turns it still lasts |
| Taint / speed_pairs | A turn whose order is not pure Speed (After You, Quick Claw...) / same-priority move pairs on untainted turns (valid Speed observations) |
| repair_mega_forms | Re-applies the exact Mega form from `detailschange`, because poke_env maps Z stones wrongly |
| Decision point (Mega) | Turn start where a side still has its Mega and a Mega-capable mon is active |

## 4. BC / encoder

| Term | Meaning |
|---|---|
| BC / IL | Behavior cloning / imitation learning: learn to copy recorded decisions |
| Encoder | `src/state_encoder.py`: battle state -> tensors (12 slots: our 2 active + 4 bench, their 2 active + 4 seen) |
| cont[] / field[] | 17-dim continuous vector per mon / 17-dim field vector |
| Move mask | Per-species allowed moves from `species_move_priors.json`; live moveset mask at inference |
| valid_orders | poke_env's per-slot list of legal orders; the BC pilot scores these (no hand filtering) |
| Ally-target penalty | 5.0 log-unit penalty on targets -1/-2 unless the move is ally-targeting (Helping Hand...) |
| side_won | Per training row: did this side win (used for outcome oversampling) |
| Checkpoint contract | Frozen names/dimensions in `bc_model.py` / `state_encoder.py`; changing them breaks `bc_best.pt` |
| arch | Checkpoint field: `v2` (MLP, production) or `v3` (transformer, rejected) |
| bc_best.pt | Production BC model; promotion needs +3 pts on a 5-seed held-out eval |

## 5. Statistics and evaluation

| Term | Meaning |
|---|---|
| SE / CI / Wilson CI | Standard error sqrt(p(1-p)/N) / confidence interval / binomial interval that stays in [0, 1] (`src/eval.py::wilson_ci`) |
| Noise floor | ~+/-5 pts on 500 battles (same baseline measured 54.8-60.6%); use >= 5 seeds and paired runs |
| Paired comparison | Same seeded matchups played by two arms (`tools/paired_eval.py`); report paired difference + McNemar p |
| McNemar p | Test on discordant pairs (one arm won, the other lost) |
| Real-EV holdout | Holdout teams with real tournament EV spreads (from VGCPastes) |
| Bridge eval | Re-evaluating old champions on a new holdout after a pool change |

## 6. Infrastructure and history names

| Term | Meaning |
|---|---|
| Showdown | Pokemon Showdown simulator (Node), local servers on ports 8000-8002; `~/pokemon-showdown` or `SHOWDOWN_DIR` |
| poke_env | Python client library for Showdown (0.17.0 in `.venv`) |
| Validator | `src/showdown_validator.py` + `src/showdown_validate.js`: Node subprocess running Showdown's team validator |
| regmc_db | `data/regmc_db.json`: canonical species, moves, items, abilities, natures, type chart from Showdown's dex |
| VGCPastes / Pokepaste | Community sheet of tournament teams / paste host (`/raw` gives Showdown text) |
| metavgc | metavgc.com per-species usage tables, blended into opponent priors |
| Watchdog | `tools/watch_islands.py`: kills an island whose log mtime is older than 300 s |
| WSL sleep mask | `systemctl mask sleep.target ...` so the host does not suspend overnight |
| log_milestone | `tools/log_milestone.py`: appends a dated entry to the old history log |
| Path A | Structural fitness design (not implemented) |
| Path 2 / Path 3 | Old roadmap labels: hand-coded doubles pilot (now VGCPilot) / BC + RL pilot (parked) |
| NeuralPlayer, vgc-bench | First-week pilot and RL framework, archived |
| ga_core_v6, bc_train_v4, state_encoder_v2, batch_parse | Old file names, merged or archived (`tools/batch_parse.py` is legacy) |
| p1..p4, q1, q5, smoke1 | Past run ids (see `docs/history/`) |

## 7. Things that sound alike

| A / B | Difference |
|---|---|
| Population / Pool | GA genomes / opponent teams |
| Train pool / Validation slice / Holdout | Fitness opponents / 30 held-back train teams / 100 never-seen eval teams |
| Fitness / Win rate | Fitness is meta-weighted; plain win rate with `GA_META_WEIGHTS=0` |
| Pilot `heuristic` / `doubles` / `vgc` | vanilla / + joint attack allocation (+ turn_sim) / + memory, Mega, foe odds |
| Role / Category | Species classification in the GA / move property (Physical, Special, Status) |
| Row-level / battle-level split | BC val split; battle-level avoids leakage and is the one used |
| Bo1 vs OTS | Independent axes: match length vs team-sheet visibility |

## Related docs

- [Glossary part 2: constants, files, log fields](glossary-constants.md)
- [Architecture](architecture.md)
- [Config and env vars](config-and-env.md)
- [Design decisions](../design/decisions.md)
