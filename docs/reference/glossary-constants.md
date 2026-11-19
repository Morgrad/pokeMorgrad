# Glossary, part 2: constants, files and log fields

Named constants and their current values, the file-to-purpose tables (with the `src/ga/`
package layout of 2026-11-18) and how to read GA / BC log lines. Read it when a log line, a
constant name or a file name needs decoding. Terms are in `glossary.md`; every env var is in
`config-and-env.md`.

Last verified against code: 2026-11-18

Format facts: `gen9championsvgc2026regmc`, doubles, Mega legal, Tera NOT legal, EVs 0-32 per
stat, 66 total, stat term `max(2*pts-1, 0)`.

## 1. GA constants

Genome constants are module constants in `src/ga/genome.py`, `pools.py`, `legality.py`, `operators.py`. Fitness-environment settings
are fields of the frozen `GAConfig` (`src/ga/config.py`), read from env ONCE at import into
`DEFAULT` (set env vars before the process starts). The uppercase aliases (`BATTLE_TIMEOUT`,
`MIN_TURNS`, `FITNESS_PILOT`, ...) of the removed `src/ga_core.py` facade are gone: use
`DEFAULT.battle_timeout` etc.

| Name | Where | Value | Meaning |
|---|---|---|---|
| `FORMAT` | `ga/config.py` | `gen9championsvgc2026regmc` | Showdown format id |
| `UID_MAX` | `ga/config.py` | `10**9` | random per-battle account id range |
| `CHECKPOINT_DIR` / `CHAMPION_DIR` | `ga/config.py` | `output/checkpoints/v6`, `output/champions` | output dirs |
| `battle_timeout` | `GAConfig` | 20 s | battle abandoned -> `None` (not a loss) |
| `min_turns` | `GAConfig` | 3 | shorter battles dropped as desyncs |
| `fitness_pilot` / `fitness_opp` | `GAConfig` | `vgc` / `ladder` | env `GA_PILOT` / `GA_OPP` |
| `meta_weights` | `GAConfig` | True | env `GA_META_WEIGHTS` (`1` = on) |
| `train_sample_size` | `GAConfig` | 250 | cap on opponents per generation (env `GA_TRAIN_SAMPLE`) |
| `early_stop_min_battles` / `early_stop_win_rate` | `GAConfig` | 50 / 0.15 | head batch and abort threshold |
| `showdown_port` / `showdown_dir` | `GAConfig` | 8000 / `~/pokemon-showdown` | env `SHOWDOWN_PORT` / `SHOWDOWN_DIR` |
| `EV_BUDGET` / `EV_STAT_CAP` | `ga/operators.py` | 66 / 32 | EVs handed out by `mutate_evs` |
| `MAX_REBUILD_TRIES` | `ga/legality.py` | 20 | rebuilds before an illegal genome is dropped |
| `VAL_POOL_SIZE` / `VAL_SPLIT_SEED` | `ga/pools.py` | 30 / 42 | validation slice size and seed |
| `CANONICAL_ITEMS` | `ga/genome.py` | Leftovers, Sitrus Berry, Focus Sash, Life Orb, Choice Scarf, Choice Specs, Assault Vest, Rocky Helmet | fallback items |
| `PROTECT_MOVES` / `FAKEOUT_MOVES` | `ga/legality.py` | 7 Protect-family moves / Fake Out, Follow Me, Rage Powder | forced coverage sets |
| `FLOOR` | `meta_weights.py` | 0.02 | usage of a species never seen on ladder |

`run_islands` keyword arguments (per run, not in `GAConfig`), with the values each launcher
passes:

| kwarg | default | `run/ga_island.py` (parallel) | `run/ga_run.py` (serial) |
|---|---|---|---|
| `pop_per_island` | 10 | 10 | 10 |
| `generations` | 999 | env `GA_GENERATIONS` (999) | 999 |
| `battles_per_genome` | 800 | 50 | 800 (capped by the 118-team fitness pool) |
| `concurrency` | env `GA_CONCURRENCY` or 3 | env or 8 | env or 3 |
| `immigration_rate` / `stagnation_limit` / `diversity_floor` | 0.20 / 5 / 15 | same | same |
| `migration_every` / `showdown_restart_every` | 5 / 10 | 999 / 10 | 5 / 10 |
| `max_hours` | None | argv[2] (4.0) | argv[2] (5.0) |

Opponents per genome per generation = `min(battles_per_genome, train_sample_size, len(fitness pool))`.

## 2. Pilot and simulation constants

| Name | Where | Value | Env override |
|---|---|---|---|
| `KO_BONUS` / `MIN_GAIN` / `ALLY_WEIGHT` | `doubles_eval.py` | 1.0 / 0.01 / 1.0 | `DOUBLES_KO_BONUS`, `DOUBLES_MIN_GAIN` (read in `DoublesPilot.__init__`) |
| `PASSIVE_COST` | `turn_sim_types.py` | 0.30 (0.15 before 2026-11-14) | `DOUBLES_PASSIVE_COST` |
| `MAX_HYPS` / `COARSE_HYPS` | `turn_sim_types.py` | 4 / 2 | - |
| `SHORTLIST` / `TOP_K` | `turn_sim_types.py` | 3 attacks per slot / 6 pairs re-scored | - |
| `MIN_OUTCOME_P` / `COARSE_OUTCOME_P` | `turn_sim_types.py` | 0.005 / 0.05 | - |
| `EFFECTS` | `support_value.py` | foulplay, snarl, charm, helpinghand, taunt, heal | - |
| `DEFAULT_SUPPORT` | `support_value.py` | `"all"` (since 2026-11-12) | `DOUBLES_SUPPORT` (comma list, `all`, or empty = off) |
| `SUPPORT_COST` / `SUPPORT_HORIZON` / `FOE_STAY` / `TR_HORIZON` | `support_value.py` | 0.15 / 2.0 / 0.7 / 2.0 | `DOUBLES_SUPPORT_COST`, `_HORIZON`, `_STAY`, `DOUBLES_TR_HORIZON` |
| `DEFAULT_LOOKAHEAD` / `LOOKAHEAD_GAMMA` | `support_value.py` | False / 0.7 | `DOUBLES_LOOKAHEAD`, `DOUBLES_LOOKAHEAD_GAMMA` |
| `use_turn_sim` | `doubles_pilot.py` | on | `DOUBLES_TURN_SIM=0` turns off |
| foe action odds | `vgc_pilot.py` | on | `DOUBLES_FOE_ACTIONS=0` turns off |
| `TOP_K` / `ARCHETYPE_K` | `opp_model.py` | 3 / 6 builds per foe | - |
| `MIN_SETS` / `K` / `MISMATCH` | `archetypes.py` | 5 / 2.0 / 0.02 | - |
| turn limit | `player_factory.py::TimeoutPlayer`, `battle_runner.py::run_battle_once` | forfeit / drop after turn 50 | - |
| `RETRY_STRIDE` | `player_factory.py` | 999983 | - |
| SmartPlayer `KO_BONUS` / `DAMAGE_WEIGHT` | `smart_player.py` | 8.0 / 3.0 | - |

## 3. BC model constants (frozen by the checkpoint contract)

| Name | Where | Value | Meaning |
|---|---|---|---|
| `N_SLOTS` | `state_encoder.py` | 12 | 2 active + 4 bench per side |
| `N_MOVES_PER` | `state_encoder.py` | 4 | moves per mon |
| `CONT_DIM` / `FIELD_DIM` | `state_encoder.py` / `bc_model.py` | 17 / 17 | per-mon continuous width / field width |
| `EMB_SPECIES` / `EMB_MOVE` / `EMB_ITEM` / `EMB_ABILITY` | `bc_model.py` | 32 / 16 / 16 / 16 | embedding sizes |
| `N_TARGETS` | `bc_model.py` | 5 | 0 = our right, 1 = our left, 2 = none, 3 = opp left, 4 = opp right (v3 only) |
| `NEG_INF` | `bc_model.py` | -1e4 | mask value (-inf gives NaN loss) |
| `OUTPUTS` | `bc_model.py` | 6 (v2) / 8 (v3) | tensors returned by forward |

BC training env (`src/bc_train.py`): `BC_MODEL` (v2), `BC_OUT` (bc_candidate.pt), `BC_EPOCHS` (30),
`BC_PATIENCE` (3), `BC_BATCH` (256), `BC_DATA` (`data/training_data.jsonl`).

## 4. Files: src/ by subsystem

| File | Purpose |
|---|---|
| `src/paths.py` | repo-relative paths (`data_path`, `output_path`, `src_path`, `showdown_dir`) |
| `src/regmc_db.py` | canonical DB access, `validate_team`, `normalize_species_name` |
| `src/showdown_validator.py` + `src/showdown_validate.js` | batch team validation through Node + Showdown |
| `src/meta_weights.py` | ladder species usage and team weights |
| `src/archetypes.py` | opponent set posterior from real-team archetypes |
| `src/ga/config.py` | `FORMAT`, `UID_MAX`, output dirs, frozen `GAConfig` |
| `src/ga/genome.py` | genome encoding, priors, random build, text <-> genome |
| `src/ga/pools.py` | train / validation / held-out opponent pools |
| `src/ga/legality.py` | Showdown legality gate, Protect / Fake Out composition, locked slots |
| `src/ga/operators.py` | mutation and crossover |
| `src/ga/fitness.py` | meta-weighted win rate (outcome i pairs with opponent i) |
| `src/ga/evaluator.py` | `Evaluator`: plays a genome's battles, early stop, validation slice |
| `src/ga/population.py` | `Island` (breed, replace, bookkeeping), `ring_migrate`, `_strip_species` |
| `src/ga/checkpoint.py` | checkpoint JSON and champion files |
| `src/ga/engine.py` | `run_islands`, the per-generation loop |
| `src/showdown_server.py` | probe / restart / ensure a local Showdown server |
| `src/battle.py` | re-exports `run_battle`, `run_battle_once`, `make_player`, `TimeoutPlayer` |
| `src/battle_runner.py` | play one battle (retry, min turns, 50-turn drop, save hooks) |
| `src/player_factory.py` | `make_player(pilot, ...)`, `TimeoutPlayer`, server config |
| `src/replay_log.py` / `src/replay_filters.py` | GA replay logging (`ReplayLogger`, JSONL per island and generation) / which battles to save |
| `src/eval.py` | evaluation CLI (`python -m src.eval`) |
| `src/audit_before_launch.py` | pre-flight data checks (`python -m src.audit_before_launch`) |
| `src/damage.py` | Champions stats and 16-roll damage |
| `src/opp_model.py`, `src/speed_model.py`, `src/mega_model.py`, `src/opp_actions.py` | foe builds, Speed odds, foe Mega odds, foe Protect/Fake Out/TR odds |
| `src/battle_memory.py` (+ `_parser`, `_types`) | per-battle memory fed from protocol lines |
| `src/doubles_eval.py` | joint attack-pair scoring |
| `src/turn_sim.py` (+ `_resolve`, `_types`, `_lookahead`) | one-turn expected-value simulation (`_resolve` plays one scenario) |
| `src/support_value.py` | support-move effects from move data |
| `src/doubles_pilot.py`, `src/pilot_world.py`, `src/pilot_actions.py`, `src/pilot_sim_input.py` | DoublesPilot and its mixins |
| `src/vgc_pilot.py`, `src/ladder_opp.py`, `src/smart_player.py` | VGCPilot, LadderOpponent, old SmartPlayer |
| `src/pilot_support.py` | support-move resolvers; imported only by `tests/test_pilot_support.py` |
| `src/state_encoder.py`, `src/bc_model.py`, `src/bc_train.py`, `src/bc_player.py` | BC stack (torch) |

## 5. Data files (main ones)

| File | Purpose |
|---|---|
| `data/regmc_db.json` | canonical format data (from Showdown's dex) |
| `data/baseline_team.txt` | reference team; seed of island A |
| `data/pool_split.json` | `train` (148) / `holdout` (100) team basenames |
| `data/regional_teams/` | opponent team pastes (348 files; old 445-team pool in `_archive_2026-10-15/`) |
| `data/meta_items.json` | item counts per species (GA items) |
| `data/species_move_priors.json` | top moves per species (GA move sampling + BC move mask; ladder-sourced) |
| `data/species_build_priors.json`, `species_ability_priors.json`, `species_archetypes.json` | opponent model inputs |
| `data/species_ladder_usage.json` | ladder usage for meta weights |
| `data/opp_actions.json`, `data/mega_rates.json` | fitted foe action and Mega rates |
| `data/paired_eval/` | paired-run logs (gitignored) and `teams/umb_*.txt` Umbreon builds |
| `output/checkpoints/v6/<run_id>/`, `output/champions/`, `output/models/` | GA checkpoints, champion teams, BC models |

## 6. Log fields

GA genome line (`src/ga/evaluator.py::_log_score`):

    [HH:MM:SS]  3/10   47.0%  (141W/300)  early-abort  Umbreon / Salamence / ...

`3/10` = genome 3 of 10 this generation; `47.0%` = fitness (meta-weighted); `141W/300` =
plain wins / valid battles; `early-abort` only when the head batch was below 15%; then the
species in slot order. Invalid genomes print `[i/n] INVALID: ...` and score 0.

GA generation lines (`src/ga/engine.py`): `[HH:MM:SS] === GEN 4/999  (31.2 min) ===` (the
watchdog plan in D8 of the refactor roadmap keys on this marker), then per island
`[A] gen 4: best= 61.0%  all-time= 63.5%  stag=1  uniq=38`; `>> migration done`,
`>> checkpoint: gen_0004.json`, `[A] diversity low (12): injected 3`,
`[A] STAGNATION: restarted 5`, and at the end `[A] champion (train): ...`.

BC epoch line (`src/bc_train.py`):

    Epoch  7/30  trl=X tra=X trm=X trs=X  vll=X vla=X vlm=X vls=X  (Ns) *

`trl`/`vll` loss, `tra`/`vla` overall action accuracy, `trm`/`vlm` move-head accuracy
(masked), `trs`/`vls` switch-head accuracy, `vltg` target accuracy (v3 only), `(Ns)` epoch
seconds, `*` = new best val_move_acc, checkpoint saved.

## Related docs

- [Glossary terms](glossary.md)
- [Config and env vars](config-and-env.md)
- [Architecture](architecture.md)
- [Data files](data-files.md)
- [Tests](tests.md)
