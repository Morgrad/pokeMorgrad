# Tests and the verify gate

Every file under `tests/` (including `tests/golden/`): what it covers, how to run it, whether
`tools/verify.sh` runs it, which data it needs, how long it takes, and how to regenerate the
GA golden master. Read this before adding or changing a test, or when `verify.sh` fails.

Last verified against code: 2026-11-18

## How tests run

- Tests are plain scripts: `python tests/<file>.py` from the repo root with the venv active.
  Each file puts the repo root on `sys.path` itself (except `tests/test_vgc_pilot.py`, which
  inserts `"."`, so it only works from the repo root).
- The gate is `bash tools/verify.sh`, which must end with `ALL PASS`. pytest is present in the
  repo `.venv` (9.2.0, dev extra) but is NOT the gate and the agent rules say never use it.
- Output convention: one line per test, `PASS <test_name>` or `FAIL <test_name>: <message>`,
  exit code 1 if anything failed.
- Rules from `.clinerules/00-core-rules.md`: copy the `__main__` runner from
  `tests/test_damage.py`; unit tests must run in under 5 seconds and must not need a live
  Showdown server or the network; if a test fails, fix the test first and never change core
  logic just to make a test pass.

The canonical runner (copy this verbatim into new test files):

```
if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
```

It only catches `AssertionError`: any other exception aborts the file with a traceback (still
exit code 1). Several older files use variants; see the "Runner" column below.

## tools/verify.sh step by step

```
bash tools/verify.sh
```

It runs `set -euo pipefail`, does `cd ~/pokeMorgrad` (hard-coded), activates `.venv` if
`.venv/bin/activate` exists else `~/venv-pokemorgad`, then:

| Step | Command | Catches |
|---|---|---|
| `ruff` | `ruff check src run tools tests` | Lint (E, F, W, I). Run `ruff check --fix <files>` first. |
| `imports` | `import src.ga.engine, src.ga.legality, src.ga.operators, src.eval, src.bc_train, src.bc_player, src.bc_model` | Import errors; needs torch installed (CPU torch is fine). |
| `imports2` | `import src.paths, src.regmc_db, src.state_encoder, src.audit_before_launch` | Same. |
| `paths` | prints `data_path('regmc_db.json')` | Path layer resolves. |
| `pools` | prints `len(regional_pool()), len(heldout_pool())` (from `src.ga.pools`) | Prints `148 100` on 2026-11-18. Fails if `data/pool_split.json` is missing / broken (`heldout_pool` raises). Sizes are asserted by `tests/test_pools.py`. |
| `tests` | loop over the `TESTS=( ... )` array, 33 files, one at a time (list below) | Unit tests. The first failing file prints `FAILED: tests/<file>.py` and the script exits 1. Each file is preceded by a `--- tests/<file>.py` line. |
| `audit` | `python -m src.audit_before_launch` | DB integrity, name sanity, Mega stones, regional teams, 500+500 genome fuzz, 2000 mutations, 500 crossovers, Umbreon lock, baseline validity. Exits 1 with `AUDIT FAILED: N problem(s)` plus `FAIL <msg>` lines on any hard failure, else prints `AUDIT COMPLETE`. Takes about 27 s. |

then prints `ALL PASS`. On 2026-11-18: 33 test files, 223 `PASS` lines, `ALL PASS`
(`pytest -q tests` also reports 223 passed, but pytest is not the gate). Total about
1.5-2 minutes on the 2026-11-18 laptop checkout.

Fixed 2026-11-18: the `tests` step used to be one `a && b && c ...` chain under `set -e`;
bash ignores failures inside `&&` lists (except the last command), so a failing file
silently skipped the rest and the script still printed `ALL PASS`. Also
`src/audit_before_launch.py` used to exit 0 even with failures. Both now fail the gate.
Quick count check:

```
bash tools/verify.sh 2>&1 | tee /tmp/verify.log | tail -1     # ALL PASS
grep -c "^PASS" /tmp/verify.log                               # 223 on 2026-11-18
```

On a host without `data/showdown_replays/` (gitignored, for example the 2026-11-18 laptop
checkout) the 5 real-replay tests of `tests/test_battle_memory.py` return early and still
count as PASS. Fixed 2026-11-18: the fifth one
(`test_real_replays_ots_item_matches_the_stone_that_later_megas`) had no skip guard and
failed, which (with the old `&&` chain) skipped 12 later files.

## Test files

Times measured 2026-11-18 on the laptop checkout (8 cores, CPU torch), wall clock per file. All 33 files are run by `tools/verify.sh`, in this order: damage,
doubles_eval, speed_model, blend_priors, archetypes, mega_z_lines, battle_memory,
vgc_pilot, mega_model, turn_sim, turn_sim_paths, support, opp_actions, ladder_opp, meta_weights,
battle_hook, battle_runner, poke_env_fixes, player_factory, pilot_support, replay_filters,
replay_log, bc_state, showdown_validator, pools, genome_clauses, extract_champions, ga_robust,
ga_config, ga_eval_order, ga_injection, island_wiring, ga_golden.

| File | Tests | verify | Time | Runner | Covers |
|---|---|---|---|---|---|
| `test_damage.py` | 10 | yes | 0.2 s | canonical | `src/damage.py` pins (captured from the implementation, not an independent Showdown oracle): Garchomp Earthquake vs Incineroar rolls 134..162, spread penalty, crit 204 / burn 67, rain Water 53, stats variant 188..224, type immunities deal 0, 16 sorted rolls, `(134,147,162)` range. |
| `test_doubles_eval.py` | 10 | yes | 0.6 s | canonical | `src/opp_model.py` builds/Mega fallback/immunity and `src/doubles_eval.py` pair choice: focus fire, overkill redirect, ties prefer baseline, spread hurting ally, ability immunity. Reads tracked `data/species_build_priors.json`, `data/regmc_db.json`. |
| `test_speed_model.py` | 9 | yes | 1.0 s | canonical | `src/speed_model.py::effective_speed`, `p_faster` (tie, Trick Room, mixtures, empty belief), `belief_for`, `opp_model.ability_distribution`. |
| `test_blend_priors.py` | 4 | yes | 0.2 s | canonical | Pure helpers of `tools/blend_priors.py`: nature canonicalization, misspelled Mega stones, corpus vs metavgc weighting, Mega / regional ability legality. Writes nothing. |
| `test_archetypes.py` | 6 | yes | 0.3 s | canonical | `src/archetypes.py` posterior on a synthetic table (count weighting, item / move reveal, Mega-form filter, unknown move). No data files. |
| `test_mega_z_lines.py` | 10 | yes | 1.1 s | canonical | Golden tests on real tracked priors: Garchomp / Lucario / Absol Mega-Z sets, post-Mega Speed 203, unrevealed Scarf. |
| `test_battle_memory.py` | 25 | yes | 2.3 s | canonical | `src/battle_memory*.py`: 20 synthetic protocol cases (Mega Z-line, copied moves, flinch, switch kinds, speed pairs, weather / terrain / Trick Room / Tailwind turns, Protect chain, Wide Guard, Open Team Sheets, Slow Start, Taunt / Yawn, volatiles) plus 5 `test_real_replays_*` on `data/showdown_replays/` (gitignored). Without that data all 5 return early (one prints `(no replay data, skipped)`) and count as PASS. Fixed 2026-11-18: `test_real_replays_ots_item_matches_the_stone_that_later_megas` had no skip guard and failed with `AssertionError((0, 0))`. |
| `test_vgc_pilot.py` | 6 | yes | 1.8 s | list order | `src/vgc_pilot.py` Mega step on synthetic orders; reads Taunt / Trick Room turns from memory. Run from repo root. |
| `test_mega_model.py` | 9 | yes | 3.2 s | no catch | `src/mega_model.py`: candidates, k growth, probability shape, speed mixture, Mega types / ability immunity in hypotheses. |
| `test_turn_sim.py` | 26 | yes | 5.6 s | list order | `src/turn_sim*.py` behaviour: speed order, Trick Room, priority, retargeting, mirror foes, Fake Out, Protect, switch, pilot end-to-end, timing of `choose_pair`. |
| `test_turn_sim_paths.py` | 3 | yes | 1.5 s | list order | Exact values (recorded before the 2026-11-18 split of `TurnSim._run` into `src/turn_sim_resolve.py`) for the rarely hit branches: drop into Protect / onto a foe without `FoeInfo`, Charm on a foe without `FoeInfo`, foe single-target retarget onto our partner (and blocked by its Protect). A changed number = changed simulator behavior. |
| `test_support.py` | 28 | yes | 5.1 s | list order | `src/support_value.py` and its use in `doubles_eval` / `turn_sim` / pilot: Foul Play, Snarl, Charm, Helping Hand, Taunt vs Trick Room, heals, lookahead (6 tests incl. timing). |
| `test_opp_actions.py` | 11 | yes | 0.3 s | list order | `src/opp_actions.py`: foe Protect / Fake Out / Trick Room probabilities, fallbacks, both `foe_ctx` call conventions; `test_real_rates_file_if_present` uses tracked `data/opp_actions.json`. |
| `test_ladder_opp.py` | 5 | yes | 1.8 s | no catch | `src/ladder_opp.py` with real poke_env objects, no server: Protect / Fake Out substitution and rates. |
| `test_meta_weights.py` | 6 | yes | 2.1 s | list order | `src/meta_weights.py` species keys, team weights with floor, weighted rate dropping `None`, and the GA fitness matching it. |
| `test_ga_robust.py` | 6 | yes | 2.5 s | list order | `src/showdown_server.py` restart waits past 15 s, retries once, `ensure` raises when dead; `run_islands` fails fast without the usage file; eval reports the GA fitness. Fakes subprocess / sleep / probe. |
| `test_ga_config.py` | 6 | yes | 2.9 s | list order | `GAConfig.from_env` defaults and overrides; `DEFAULT == from_env(os.environ)` and `src.eval` uses `config.FORMAT` / `UID_MAX`; `test_invalid_values_fail_fast` (unknown `GA_PILOT` / `GA_OPP`, `GA_TRAIN_SAMPLE=0`, `early_stop_win_rate=1.5` raise `ValueError`); `test_pilot_names_match_player_factory` (`PILOT_NAMES == PILOTS`, `make_player("nope", ...)` raises); `test_showdown_port_has_one_parser` (`src/paths.py::showdown_port` is the only `SHOWDOWN_PORT` parser). |
| `test_ga_eval_order.py` | 3 | yes | 2.5 s | list order | Regression for the 2026-11-18 fix: each outcome is weighted by ITS opponent (full run, early-abort path, threshold boundary). Battles finish in reverse order. |
| `test_island_wiring.py` | 2 | yes | 2.4 s | canonical | `run/ga_island.py::SPECS` and `run/ga_run.py::ISLANDS` (serial launcher, run_id `run1`): A = Umbreon slot 0 + `baseline_team.txt` seed, B = Umbreon slot 0 and no seed, C = no lock and no seed. |
| `test_ga_injection.py` | 4 | yes | 1.1 s | canonical | `src/ga/engine.py::_evolve_island` + `src/ga/population.py` with a fake evaluator and identity legality gate: stagnation restart and diversity rescue genomes land in the children's slots and reach the next generation, elites survive, restart wins over rescue, the last generation injects nothing, `ring_migrate` targets the worst slots and spares elites after breed. |
| `test_ga_golden.py` | 1 | yes | 5.2 s | single call | Golden master of the whole GA engine (below). |
| `test_bc_state.py` | 2 | yes | 3.8 s | canonical | Live battle -> encoder state dict via `src/bc_player.py::BCPlayer._state_to_dict` and `tools/generate_heuristic_dataset.py::state_from_battle` on a stub battle. Regression for the `mon_view(m, True)` `TypeError` (fixed 2026-11-18). Needs torch (CPU is fine), no model file, no Showdown. |
| `test_showdown_validator.py` | 3 | yes | 0.1 s | canonical | `src/showdown_validator.py::check_teams` with a faked `subprocess.run`: verdicts parsed in order and cached; node failure raises `ValidatorError` and caches nothing; a per-team `ERR:` verdict is returned but not cached. |
| `test_pools.py` | 3 | yes | 0.2 s | canonical | `src/ga/pools.py` (patches `PL.data_path`, resets `PL._HELDOUT` / `_REGIONAL`). Real `data/pool_split.json`: train / holdout disjoint and `regional_pool` / `heldout_pool` sized like the split; `heldout_pool` raises `RuntimeError` on a missing split file (no fallback to train), an empty holdout list or an overlap. |
| `test_genome_clauses.py` | 4 | yes | 1.1 s | list order | Clause fuzz (refactor B2): species clause, item clause and locks hold after `build_random_genome`, crossover + mutate chains, `enforce_constraints` on genomes from other islands (incl. the locked species already in a free slot) and `ring_migrate`. Failed on the pre-B2 code (58 + 4 violations). |
| `test_extract_champions.py` | 1 | yes | 0.2 s | canonical | `tools/extract_champions.py::extract` on a temp checkpoint: primary file = train best, `_train` = train best, `_val` = `best_val_ever`. Writes only to a temp dir. |
| `test_battle_hook.py` | 4 | yes | 1.1 s | canonical | `run_battle(log_sink=None)` signature (no `save_filter` / `save_callback`); `battle_log_lines` joins poke_env `_replay_data` into protocol lines; `log_sink` gets the last attempt's result and log; sink errors are swallowed. |
| `test_battle_runner.py` | 5 | yes | 1.8 s | list order | Imports from `src.battle_runner` and `src.battle`; with fake players: a pilot exception returns `(None, [])`, is logged (ERROR + traceback) and counted (`battle_error_counts`); only the first 3 per type get a traceback, then every 100th; a timeout is not an error; `KeyError: 'round'` warns, other `KeyError`s propagate. |
| `test_poke_env_fixes.py` | 4 | yes | 1.5 s | list order | `src/poke_env_fixes.py` on a bare poke_env `DoubleBattle`: a Round after its partner's Round no longer raises `KeyError: 'round'`, is revealed and costs one PP like the partner's, and `_replay_data` keeps the original message; the unpatched poke_env still raises (flags a poke_env upgrade that fixes it); only that message shape is touched; `player_factory` installs the patch once (checked in a fresh process). |
| `test_replay_log.py` | 4 | yes | 1.5 s | canonical | `src/replay_log.py::ReplayLogger`: rows carry real fitness / outcome / gen, cap per (island, gen) in (genome, opponent) order, private deterministic RNG (global stream untouched); `Evaluator.evaluate(on_battles=...)` reports aligned outcomes / logs (head only on early abort) with identical fitness; engine wiring gives the same population and RNG state with logging on or off. |
| `test_pilot_support.py` | 1 | yes | 1.5 s | single call | Import smoke for `src/pilot_support.py::_resolve_support_move`. |
| `test_player_factory.py` | 1 | yes | 2.1 s | single call | `make_player("heuristic", ...)` returns an object (no server needed). Unknown names are covered by `test_ga_config.py`. |
| `test_replay_filters.py` | 1 | yes | 0.1 s | returns bool | `src/replay_filters.py::default_ga_filter`: fitness thresholds, Tailwind / Trick Room triggers, random sampling. |

Runner variants: "list order" = `list(globals())` (definition order) with the canonical
try/except; "no catch" = no try/except, so the first failure is a traceback and later tests do
not run; "single call" / "returns bool" = calls one function. Over 5 s on this laptop:
`test_turn_sim.py`, `test_support.py`, `test_ga_golden.py` (rule is under 5 s).

Every `tests/test_*.py` file is in `verify.sh` (33 files on 2026-11-18). To run all of them
without stopping at the first failure:

```
for f in tests/test_*.py; do python "$f" > /tmp/t.out 2>&1 || { echo "FAIL $f"; tail -5 /tmp/t.out; }; done
```

## Golden master: tests/test_ga_golden.py + tests/golden/

Files: `tests/test_ga_golden.py` (48 lines), `tests/golden/ga_harness.py` (218 lines; imports `src.ga.engine` and `src.ga.population`),
`tests/golden/ga_golden.json` (12404 lines, the fixture).

What it pins (byte-for-byte JSON compare, unified diff on failure):
- Population operators with `random.seed(7)`: `Island.init_population`, `Island.breed`,
  `Island.replace_worst`, `ring_migrate`, `Island.unique_species`, `Island.to_dict`/`from_dict`
  round trip, RNG state afterwards, captured stdout.
- Three `run_islands` calls on islands A (Umbreon lock + baseline seed) and B (free),
  pop 6, `run_id="golden"`: fresh run (3 gens, 20 battles/genome), resume to gen 5, resume to
  gen 7 with 60 battles/genome (head/tail early-abort path). For each: normalized stdout
  (times replaced), every checkpoint and champion file under `output/`, battle count, a hash
  of sorted uids, RNG state, and the kwargs passed to `run_battle`.

How the run is faked (no Showdown, no battles):
- `POKEMORGRAD_ROOT` -> a temp dir from `tempfile.mkdtemp(prefix="ga_golden_")` with `data/`
  symlinked to the real `data/`, so outputs go to the temp dir. The harness deletes the dir
  after the run (`shutil.rmtree`). Fixed 2026-11-18: it used to leave one `/tmp/ga_golden_*`
  dir per run; old leftovers can be removed with `rm -rf /tmp/ga_golden_*`.
- `SHOWDOWN_PORT` -> a tiny local HTTP server so `showdown_server.ensure` passes.
- `src.battle.run_battle` -> deterministic hash-based fake; `src.showdown_validator.check_teams`
  -> `regmc_db.validate_team` (no node).
- `PYTHONHASHSEED=0` is required (the genome code iterates sets); the harness exits without it.
- It depends on tracked data files (`data/pool_split.json`, `data/regional_teams/`, priors,
  `data/species_ladder_usage.json`, `data/regmc_db.json`). Changing those changes the fixture.

When it fails: something changed GA output. If the change was NOT intended, fix the code.
Last deliberate regeneration: 2026-11-18, for the post-breed stagnation restart / diversity
rescue (`Island.inject_fresh`) and `ring_migrate` targeting the lowest-fitness slots.
Regenerate ONLY for an intended behavior change, and say so in the commit message:

```
PYTHONHASHSEED=0 python tests/golden/ga_harness.py --write
python tests/test_ga_golden.py
git diff --stat tests/golden/ga_golden.json
```

## Adding a test (checklist)

1. New file `tests/test_<topic>.py`; first lines put the repo root on `sys.path`:
   `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`.
2. Functions named `test_*`, plain `assert`; synthetic inputs; no Showdown, no network,
   under 5 s; write only under `/tmp` or a temp dir.
3. Copy the canonical runner above.
4. Add `test_<topic>` (no `tests/` prefix, no `.py`) to the `TESTS=( ... )` array in
   `tools/verify.sh` (edit only with approval; it is shared infrastructure).
5. `ruff check --fix tests/test_<topic>.py`, then `bash tools/verify.sh` must end with
   `ALL PASS`, and the `PASS` count must grow by the number of new tests.

## Related docs

- [../runbooks/health-check.md](../runbooks/health-check.md) - verify gate and preflight before runs
- [config-and-env.md](config-and-env.md) - `PYTHONHASHSEED`, `POKEMORGRAD_ROOT`
- [../subsystems/ga.md](../subsystems/ga.md) - what the golden test protects
- [../design/policy.md](../design/policy.md) - test-gated workflow rules
- [../runbooks/failure-modes.md](../runbooks/failure-modes.md)
