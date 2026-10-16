# run/, tests/, ops/ reference

Verified by reading the scripts. "Unclear" = not established from the code alone. Nothing here was executed.

## Contents
- [Launching a GA run](#launching-a-ga-run)
- [Port / island mapping and env vars](#port--island-mapping-and-env-vars)
- [run/ scripts](#run-scripts)
- [tests/](#tests)
- [ops/](#ops)
- [Inconsistencies noted](#inconsistencies-noted)

## Launching a GA run
Normal 3-island parallel run (3 processes, 3 Showdown servers):
```
bash run/ga_parallel.sh [hours=4.0] [run_id=p1]
```
What happens (`run/ga_parallel.sh`):
1. `cd ~/pokeMorgrad` (hard-coded, `:15`), activates `~/venv-pokemorgad`, `PYTHONUNBUFFERED=1`, `pkill -9 -f "run.ga_island"`.
2. For ports 8000/8001/8002: if `curl` fails, starts `node pokemon-showdown start <port> --no-security` from `~/pokemon-showdown` (log `/tmp/showdown_<port>.log`); sleeps 8s; aborts if any port is still down.
3. `run_island` per island loops until the time budget is spent: runs `SHOWDOWN_PORT=$port ISLAND_NAME=$name GA_CONCURRENCY=8 python -m run.ga_island $RUN_ID $remaining_h` (`:60`), log `/tmp/ga_${RUN_ID}_${name}.log`; respawns on non-zero exit.
4. Watchdog `tools/watch_islands.py <run_id> <name> <pid> 300` kills a process whose log mtime stalls > 300s (checks every 30s; `watch_islands.py` header) so the loop respawns it.
5. On finish it renames `output/champions/ga_${RUN_ID}_${name}_island_${name}.txt` to `ga_${RUN_ID}_island_${name}.txt` and touches `/tmp/ga_${RUN_ID}_done`. The `_train.txt` file is not renamed.

Single island by hand: `SHOWDOWN_PORT=8000 ISLAND_NAME=A python -m run.ga_island <run_id> <hours>` (server must already be up).

## Port / island mapping and env vars
| Island | Port | Locked slot / seed | RNG seed | Checkpoint dir |
|---|---|---|---|---|
| A | 8000 | slot 0 Umbreon + baseline-team seed | 42 | `output/checkpoints/v6/<run_id>_A` |
| B | 8001 | slot 0 Umbreon, no seed | 137 | `.../<run_id>_B` |
| C | 8002 | free (no lock) | 999 | `.../<run_id>_C` |

(`run/ga_island.py` SPECS and seeds; run_id passed to `run_islands` is `f"{RUN_ID}_{NAME}"`.)
- Parallel mode has NO cross-process migration: `migration_every=999` in `ga_island.py`, one island per process.
- Port is routed through `SHOWDOWN_PORT`, read at import by `src/battle.py:59` (battle sockets) and `src/ga_core.py:1072` (`restart_showdown`). `ga_island.py:37` reads it only to print it.

| Env var | Set by | Read by | Value |
|---|---|---|---|
| `SHOWDOWN_PORT` | ga_parallel.sh (per island) | battle.py, ga_core.py, ga_island.py | 8000/8001/8002 |
| `ISLAND_NAME` | ga_parallel.sh | ga_island.py:36 | A/B/C (default A) |
| `GA_CONCURRENCY` | ga_parallel.sh sets 8 | ga_island.py:38 (default 8), ga_run.py:60 (default "3"), ga_core.py:1398, eval.py:27 (default "3") | simultaneous battles per process |
| `PYTHONUNBUFFERED` | ga_parallel.sh | python | 1 |
| `SHOWDOWN_DIR` | optional | ga_overnight.sh, ops/*.sh (default `$HOME/pokemon-showdown`) | note: ga_core ignores it |
| `GA_TRAIN_SAMPLE` | optional | ga_core.py:75 | default 250 |

## run/ scripts
### run/ga_island.py (78 lines)
One island per process. argv: `run_id` (default `p1`), `hours` (default 4.0). Calls `run_islands` with a single island, pop 10, battles 800, `migration_every=999`. Env: `ISLAND_NAME`, `SHOWDOWN_PORT`, `GA_CONCURRENCY` (default 8).

### run/ga_run.py (68 lines)
Single-process, all three islands together (ring migration every 5 gens): `python -m run.ga_run <run_id> [hours]` (defaults `run1`, 5.0).
- Seeds `{run1: 42, run2: 137, run3: 999}`. When `RUN_ID != "run1"`, warm-starts from `output/champions/ga_run1_island_{A,B,C}.txt` if present.
- Islands: A = Umbreon + baseline seed, B = Umbreon, C = free. `concurrency=int(env GA_CONCURRENCY, "3")` (`:60`), `migration_every=5`.
- Needs the repo root on the import path, so use `-m` (no `sys.path` insertion in the file).
- Talks to one server (port from `SHOWDOWN_PORT`, default 8000).

### run/ga_overnight.sh (74 lines)
Sequential chain on one server (port 8000): `python -m run.ga_run run1 2.5`, then `run2 2.5`, then `python -m src.eval` on the baseline and the six champions.
- Starts Showdown on 8000 if needed plus a 30s watchdog loop; kills processes matching `ga_run.py` / `ga_core`.
- DESTRUCTIVE: `rm -rf` of the run1 and run2 checkpoint directories before starting (so no resume).
- Does not set `GA_CONCURRENCY` (falls to ga_run's default 3). Logs in `/tmp`; marker `/tmp/ga_overnight_done_$STAMP`.

## tests/
Run directly (pytest is NOT installed):
```
source ~/venv-pokemorgad/bin/activate
python tests/test_damage.py
python tests/test_doubles_eval.py
python tests/test_speed_model.py
python tests/test_blend_priors.py
python tests/test_archetypes.py
python tests/test_mega_z_lines.py
python tests/test_battle_memory.py
```
Each file inserts the repo root into `sys.path`, so it works from any cwd with the venv active. The `__main__` runner iterates `test_*` functions in sorted order, prints results, exits 1 on failure. It catches only `AssertionError`, so any other exception crashes the runner with a traceback instead of a per-test fail.

### tests/test_damage.py (96 lines)
Pins `src/damage.py` outputs. Pins were captured from the implementation, not an independent Showdown oracle.
- `test_db_path_is_repo_relative`: DB path resolves under the repo.
- `test_spread_move_base`: Garchomp Earthquake vs Incineroar rolls span 134..162.
- `test_spread_penalty_removed_when_single_target`: `include_spread=False` removes x0.75.
- `test_crit_and_burn`: pinned values 204 (crit) and 67 (burn).
- `test_status_move_has_no_damage`; `test_rain_boosts_water` (53).
- `test_stats_variant_matches_pin`: `damage_rolls_from_stats` gives 188..224.
- `test_type_immunities_deal_zero`: regression for the immune-code-3 fix (commit f9c354c).
- `test_rolls_are_sorted_and_16_long`; `test_range_and_ko_chance` ((134,147,162), 0.0).

### tests/test_blend_priors.py (4 tests)
Pure helpers of `tools/blend_priors.py`: nature canonicalization, misspelled mega stones, corpus-vs-metavgc weighting, Mega/regional ability legality.

### tests/test_archetypes.py (6 tests) and tests/test_mega_z_lines.py (10 tests)
Synthetic posterior tests (count weighting, item/move reveal, Mega-form filter) and real-data golden tests for Garchomp / Lucario / Absol Mega-Z lines (set given item + moves, post-Mega Speed 203, unrevealed Scarf, Levitate vs Sand Force).

### tests/test_battle_memory.py (22 tests)
Synthetic edge cases (Z-line Mega, copied moves, flinch, pivot/replacement/drag switches, speed-pair taint, weather/terrain/Trick Room/Tailwind turns left, Protect chain, Slow Start) and four checks on the first 600-2000 logs in `data/showdown_replays` (skipped if absent): Mega exact and once per side, condition durations, Protect 2/3 fail, first mover.

### tests/test_speed_model.py (9 tests)
Covers `effective_speed` modifiers, ability/weather/terrain conditions, `p_faster` (certain, tie, Trick Room, weighted mixture, opponent mods, empty belief), `belief_for` on real species and `opp_model.ability_distribution`. Run: `python tests/test_speed_model.py`.

### tests/test_doubles_eval.py (135 lines)
10 tests over `src/opp_model.py` and `src/doubles_eval.py`, using helper builders `attacker/foe/ally/one_hit_rolls`. They read the real `data/species_build_priors.json` and `data/regmc_db.json`.
- opp_model: `test_opp_builds_weights_and_stats`, `test_opp_mega_form_resolves_and_falls_back_to_generic`, `test_immunity_prob`.
- Evaluator/choose_pair: `test_focus_fire_beats_split_when_only_the_pair_kills`, `test_overkill_redirects_second_attacker`, `test_choose_pair_prefers_baseline_on_tie_and_finds_focus_fire`, `test_spread_move_hurts_fragile_ally`, `test_ally_immune_to_spread_is_not_penalised`, `test_ability_immunity_zeroes_value`, `test_status_and_none_actions_are_free`.
- Not covered by either file: ga_core, battle, eval, bc_*, DoublesPilot (poke_env integration). `tools/test_pilots.py` and `tools/pilot_probe.py` exist but were not read (unclear what they cover).

## ops/
Four shell helpers for the Showdown server (none run here).
- `ops/start_server.sh [port]`: kills only `pokemon-showdown start <port>` (default 8000), restarts it with `--no-security` from `$SHOWDOWN_DIR`, log `/tmp/showdown_<port>.log`, curl check.
- `ops/watch_server.sh`: 30s loop that restarts via `start_server.sh` if :8000 is down. Also contains a training-stall killer targeting `~/vgc-bench` (TB dir `~/vgc-bench/results/logs_sp`, 300s stall); only the server-health half applies to this repo.
- `start_server.sh` is port-scoped (it used to pkill every Showdown process, which could take down 8001/8002 mid-run). `ga_parallel.sh` starts its own servers and does not use ops/. `ops/watch_server.sh` still watches 8000 only.

## Inconsistencies noted
- `GA_CONCURRENCY` default differs: 8 (ga_island.py, ga_parallel.sh) vs "3" (ga_core, ga_run, eval). docs/STATE.md §5.9 is reported to say battle.py reads it; it does not (battle.py reads only `SHOWDOWN_PORT`).
- `ga_run.py` docstring says "B = free, C = free" but the code locks Umbreon on B; its docstring also suggests `python ga_run.py`, which would fail without `-m`.
- `ga_overnight.sh` labels now say 2.5h per run, matching the code.
- `ga_parallel.sh` `_train.txt` champion files keep the doubled name after the rename step; `REPO_ROOT` is defined at `:93` but referenced inside a function defined earlier (`:65`), fine only because the function is called afterwards.
