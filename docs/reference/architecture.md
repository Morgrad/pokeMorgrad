# Architecture

How pokeMorgrad fits together: the data pipeline (replays and teams -> priors, DB, BC), the GA
that searches teams with battle pilots on local Showdown servers, the processes that run
during a GA, the directory layout, the `src/` modules by subsystem and their import map. Read
it first when a task crosses subsystems or you need to know which module owns what.

Last verified against code: 2026-11-18

Format facts: `gen9championsvgc2026regmc` (Reg M-C, Champions mod), doubles, Mega legal,
Terastallization NOT legal, EVs 0-32 per stat, 66 total, stat term `max(2*pts-1, 0)`.

## 1. Pipeline overview

Goal: find the best Reg M-C team (with Umbreon in slot 0 on islands A and B) by evolving
teams with a genetic algorithm whose fitness is the result of real Showdown battles played by
a scripted doubles pilot against real tournament teams.

```
Showdown dex --tools/build_regmc_db.js--> data/regmc_db.json  (format truth: species, moves,
                                                              items, abilities, natures, types)
Ladder replays (tools/scrape_replays.py -> data/showdown_replays/, local only)
  |-- tools/build_training_data.py (Tracker in tools/replay_tracker.py)
  |       -> data/training_data.jsonl -> src/bc_train.py -> output/models/bc_best.pt
  |                                     -> src/bc_player.py (pilot "bc", parked track)
  |-- tools/build_species_priors.py   -> data/species_move_priors.json (GA moves + BC mask)
  |-- tools/build_meta_weights.py     -> data/species_ladder_usage.json (fitness weights)
  |-- tools/build_opp_actions.py      -> data/opp_actions.json (foe Protect/Fake Out/TR odds)
  `-- tools/build_mega_rates.py       -> data/mega_rates.json (foe Mega odds)
Tournament teams (tools/scrape_tournament.py -> data/regional_teams/;
                  tools/scrape_vgcpastes.py -> data/scraped/vgcpastes/, local only)
  |-- tools/swap_pool.py, tools/regenerate_split.py -> data/pool_split.json (train / holdout)
  |-- tools/build_ev_priors.py + tools/scrape_metavgc.py + tools/blend_priors.py
  |       -> data/species_build_priors.json, species_ability_priors.json (opponent model)
  `-- tools/build_archetypes.py -> data/species_archetypes.json (opponent sets)

GA (src/ga/, launched by run/ga_parallel.sh or run/ga_run.py)
  islands A/B/C -> genomes (src/ga/genome.py, operators.py; legality.py via Node validator)
    -> battles: our side VGCPilot ("vgc") vs opponent LadderOpponent ("ladder"),
       opponents = train pool minus a 30-team validation slice (118 teams)
    -> fitness = meta-weighted win rate (src/ga/fitness.py)
  -> checkpoints output/checkpoints/v6/<run>/gen_NNNN.json
  -> champions output/champions/ga_<run>_island_<X>.txt (train-best) + _train.txt
Held-out eval: python -m src.eval <team.txt> --pilot vgc --opp ladder  (100 holdout teams,
  prints plain win rate + Wilson CI + the GA's meta-weighted rate)
Paired comparisons: tools/paired_eval.py / tools/paired_run.sh (same matchups, two arms)
```

Pilots used for fitness (defaults in `src/ga/config.py::GAConfig`, env `GA_PILOT` /
`GA_OPP`):
- Our side: `vgc` = `src/vgc_pilot.py::VGCPilot`, wrapped by
  `src/player_factory.py::TimeoutPlayer` (forfeits after turn 50). VGCPilot = vanilla
  heuristic order improved by `src/turn_sim.py` + `turn_sim_resolve.py` (move order, KO odds, Protect, Fake Out,
  switch, support moves) + battle memory + Mega choice + foe action odds.
- Opponent: `ladder` = `src/ladder_opp.py::LadderOpponent` (vanilla heuristic that uses
  Protect / Fake Out at replay-fitted rates).
- `GA_PILOT=heuristic GA_OPP=heuristic` restores the pre-2026-10-16 environment (scores not
  comparable).

Fitness = sum(w_i * win_i) / sum(w_i) over battles with a result (`None` = timeout, desync,
< 3 turns or > 50 turns, dropped), `w_i` = mean ladder usage of opponent i's six species
(`src/meta_weights.py`, unseen species 0.02). `GA_META_WEIGHTS=0` = plain win rate.

## 2. Process model

A parallel GA run (`bash run/ga_parallel.sh <hours> <run_id>`) has:

| Process | Count | Started by | Notes |
|---|---|---|---|
| Showdown server `node pokemon-showdown start <port> --no-security` | 3 (ports 8000, 8001, 8002) | `run/ga_parallel.sh` if not answering; `src/showdown_server.py::restart` every 10 generations | runs in `~/pokemon-showdown` (`SHOWDOWN_DIR`); log `/tmp/showdown_<port>.log` |
| Island process `python -m run.ga_island <run_id> <hours>` | 3 (A on 8000, B on 8001, C on 8002) | `run/ga_parallel.sh` respawn loop | env `ISLAND_NAME`, `SHOWDOWN_PORT`, `GA_CONCURRENCY=8`; one asyncio loop each; log `/tmp/ga_<run_id>_<X>.log`; respawned from the last checkpoint on non-zero exit until the time budget ends |
| Watchdog `tools/watch_islands.py` | 1 per island | `run/ga_parallel.sh` | SIGKILLs an island whose log is older than 300 s |
| Node validator `node src/showdown_validate.js` | short-lived, 1 per validation batch | `src/showdown_validator.py::check_teams` (`subprocess.run`) | validates base64 team texts against Showdown's TeamValidator; results cached by md5 |

Inside an island process: `run_islands` -> `Evaluator.evaluate` runs up to `GA_CONCURRENCY`
battles at once (one `asyncio.Semaphore`); each battle creates two poke_env players with
fresh account names on that island's server and retries once on `None`
(`src/battle_runner.py::run_battle`). Islands never talk to each other (`migration_every=999`).
Serial `python -m run.ga_run <run_id> <hours>` runs all three islands in one process on
`SHOWDOWN_PORT` (default 8000) with ring migration every 5 generations.

Settings are read from env at import (`GAConfig`), so set env vars before launching. Long runs
need the user's approval.

## 3. Directory layout

| Path | Contents |
|---|---|
| `src/` | the Python package (`from src.x import y`); GA engine in `src/ga/` |
| `run/` | GA entry points: `ga_parallel.sh`, `ga_island.py`, `ga_run.py`, `ga_overnight.sh` |
| `tools/` | data pipeline (scrapers, prior/DB builders), eval helpers (`paired_eval.py`, `paired_run.sh`), `verify.sh` gate, `preflight.py`, watchdog |
| `ops/` | Showdown server scripts (`start_server.sh`, `watch_server.sh`) |
| `tests/` | `python tests/<file>.py` test scripts; `tests/golden/` GA golden-master fixture |
| `data/` | inputs: `regmc_db.json`, team pools, priors, fitted rates (mostly gitignored with a whitelist) |
| `output/` | generated: `checkpoints/v6/`, `champions/`, `models/`, `archive/` (gitignored; about 30 champion/archive files are force-added) |
| `docs/` | this documentation (`history/` = dated log) |
| `archive/` | frozen old scripts, pools and tools; do not edit |
| `~/pokemon-showdown/` | separate git repo with the simulator (outside this repo); never edit |

## 4. src/ modules by subsystem

- Foundation: `paths` (repo-relative paths), `regmc_db` (DB access, `validate_team`),
  `showdown_validator` + `showdown_validate.js` (Node validation), `meta_weights` (ladder
  usage weights), `archetypes` (opponent set posterior).
- GA (`src/ga/`): `config` (GAConfig, FORMAT), `genome` (encoding, priors, random
  build, text <-> genome), `pools` (train / validation / held-out pools), `legality`
  (Showdown gate, composition, locks), `operators` (mutate, crossover), `fitness`
  (weighted win rate), `evaluator` (Evaluator), `population` (Island, ring migration),
  `checkpoint` (checkpoint/champion files), `engine` (`run_islands`); `showdown_server`
  (probe/restart). No facade: import from the defining module.
- Battle harness: `battle` (re-export), `battle_runner` (run one battle), `player_factory`
  (`make_player`, `TimeoutPlayer`), `poke_env_fixes` (patches a poke_env parser bug),
  `replay_log` + `replay_filters` (GA replay logging).
- Damage and opponent knowledge: `damage`, `opp_model`, `speed_model`, `mega_model`,
  `opp_actions`.
- Battle memory: `battle_memory`, `battle_memory_parser`, `battle_memory_types`.
- Turn simulation: `doubles_eval` (pair scoring), `turn_sim` (scenario enumeration, foe
  model), `turn_sim_resolve` (one scenario in move order), `turn_sim_types`,
  `turn_sim_lookahead`, `support_value` (support-move effects).
- Pilots: `doubles_pilot` + mixins `pilot_world`, `pilot_actions`, `pilot_sim_input`;
  `vgc_pilot`, `ladder_opp`, `smart_player` (old, helpers still used); `pilot_support`
  (imported only by `tests/test_pilot_support.py`).
- Evaluation: `eval` (CLI), `audit_before_launch` (pre-flight checks).
- BC (torch): `state_encoder`, `bc_model`, `bc_train`, `bc_player`.

## 5. Dependency map

Generated from the `src.*` imports with an AST scan on 2026-11-18. Read `X --> a, b` as "X imports a and b".
`(lazy)` marks imports done inside a function.
```
paths                --> -
regmc_db             --> paths
showdown_validator   --> paths
archetypes           --> paths
damage               --> paths, regmc_db
smart_player         --> damage
support_value        --> damage
doubles_eval         --> damage, support_value
opp_model            --> archetypes, damage, paths
mega_model           --> battle_memory, damage, paths
speed_model          --> damage, mega_model, opp_model
battle_memory_types  --> -
battle_memory_parser --> battle_memory_types, regmc_db
battle_memory        --> battle_memory_parser, battle_memory_types
opp_actions          --> battle_memory, paths
ladder_opp           --> battle_memory, opp_actions
meta_weights         --> paths, regmc_db
turn_sim_types       --> battle_memory, damage, doubles_eval, support_value
turn_sim_lookahead   --> doubles_eval, support_value, turn_sim_types ; (lazy) turn_sim
turn_sim_resolve     --> doubles_eval, support_value, turn_sim_types
turn_sim             --> damage, doubles_eval, support_value, turn_sim_lookahead, turn_sim_resolve, turn_sim_types
pilot_world          --> damage, doubles_eval, mega_model, opp_model, smart_player, speed_model
pilot_actions        --> damage, doubles_eval, pilot_world, support_value, turn_sim
pilot_sim_input      --> doubles_eval, opp_model, pilot_world, speed_model, turn_sim
pilot_support        --> -        (used by tests/test_pilot_support.py only)
doubles_pilot        --> doubles_eval, pilot_actions, pilot_sim_input, pilot_world, smart_player, support_value, turn_sim
vgc_pilot            --> battle_memory, doubles_pilot, mega_model, opp_actions, opp_model
poke_env_fixes       --> -
player_factory       --> paths, poke_env_fixes, vgc_pilot ; (lazy) bc_player, doubles_pilot, ladder_opp
battle_runner        --> player_factory
battle               --> battle_runner, player_factory
showdown_server      --> -
ga.config            --> paths
ga.genome            --> paths, regmc_db
ga.pools             --> paths
ga.legality          --> ga.genome, ga.operators, showdown_validator
ga.operators         --> ga.genome, regmc_db
ga.fitness           --> meta_weights
ga.population        --> ga.genome, ga.legality, ga.operators, regmc_db
ga.evaluator         --> battle, ga.config, ga.fitness, ga.genome, regmc_db
ga.checkpoint        --> ga.config, ga.genome, ga.population
ga.engine            --> ga.checkpoint, ga.config, ga.evaluator, ga.pools, ga.population, meta_weights, showdown_server
eval                 --> battle, ga.config, ga.fitness, ga.pools, paths
audit_before_launch  --> ga.genome, ga.operators, ga.pools, paths, regmc_db
replay_filters       --> -
replay_log           --> replay_filters   (used by run/ga_island.py; engine gets it as an argument)
state_encoder        --> paths
bc_model             --> state_encoder
bc_player            --> bc_model, paths, state_encoder
bc_train             --> bc_model, paths, state_encoder
```
- Torch-importing modules: `state_encoder`, `bc_model`, `bc_player`, `bc_train`. Everything
  else is torch-free; `battle` / `player_factory` reach torch only through the lazy
  `BCPlayer` import (pilot `bc`).
- `run/`, `tools/`, `src/eval.py` and `src/audit_before_launch.py` import the defining
  `src.ga.*` module directly (the `ga_core` facade was removed on 2026-11-18).
- `turn_sim_lookahead -> turn_sim` is a lazy import.

## 6. Where to change what

| Task | Start in |
|---|---|
| GA loop, islands, checkpoints | `src/ga/engine.py`, `src/ga/population.py`, `src/ga/checkpoint.py` (golden test pins output) |
| How teams are built or mutated | `src/ga/genome.py` (build), `src/ga/operators.py` (mutate / crossover), `src/ga/legality.py` (gate, locks), `src/ga/pools.py` (opponent pools) |
| Fitness formula / weights | `src/ga/fitness.py`, `src/meta_weights.py` |
| Fitness pilots or their settings | `src/ga/config.py`, `src/player_factory.py` |
| Pilot decisions | `src/doubles_pilot.py`, `src/turn_sim.py`, `src/turn_sim_resolve.py`, `src/support_value.py`, `src/vgc_pilot.py` |
| Opponent behavior in fitness | `src/ladder_opp.py`, `src/opp_actions.py` |
| Battle running, retries, ports | `src/battle_runner.py`, `src/player_factory.py`, `src/showdown_server.py` |

## Related docs

- [GA subsystem](../subsystems/ga.md) and [GA genome](../subsystems/ga-genome.md)
- [Battle harness](../subsystems/battle-harness.md), [Pilots](../subsystems/pilots.md), [Turn sim](../subsystems/turn-sim.md)
- [Foundation](../subsystems/foundation.md), [Damage](../subsystems/damage.md), [Battle memory](../subsystems/battle-memory.md), [BC](../subsystems/bc.md), [Eval](../subsystems/eval.md)
- [Run scripts](run-scripts.md), [Tools](tools.md), [Data files](data-files.md), [Config and env](config-and-env.md)
- [Design decisions](../design/decisions.md), [Glossary](glossary.md)
