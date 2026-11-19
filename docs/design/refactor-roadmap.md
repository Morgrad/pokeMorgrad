# Refactor roadmap

Open and finished refactor work items from the 2026-10-14 code audit, re-checked against the
code on 2026-11-18, plus debt found since. Read this before a cleanup or restructuring task:
it says what is still open, what is done, the safety net for each item and how to verify it.

Last verified against code: 2026-11-18

Rules that still apply:
- Do one tier per session; never mix a mechanical rename with a structural change.
- GA changes are guarded by `tests/test_ga_golden.py` (pins `run_islands` stdout, checkpoint
  JSON, champion files and RNG consumption). If it fails, you changed GA behavior. Regenerate
  the fixture only for an intended change: `PYTHONHASHSEED=0 python tests/golden/ga_harness.py --write`.
- Gate after every item: `bash tools/verify.sh` must end with `ALL PASS`.
- There is no GA facade any more (`src/ga_core.py` removed 2026-11-18): import each name
  from its defining `src.ga.*` module.
- A pure refactor is proven identical with the golden master PLUS a characterization
  snapshot taken before the change (see D1 / D9 below for how it was done on 2026-11-18).

## Status summary

| Item | Tier | What | Status 2026-11-18 |
|---|---|---|---|
| C2 | 0 | duplicated battle-split block in `bc_train.py` | done 2026-10-14 (`7dba410`) |
| A1 | 1 | private path helpers in 4 modules | done 2026-10-15 |
| A2 | 1 | EV caps declared twice | stale: no duplicate (only `src/ga/operators.py::EV_BUDGET`, `EV_STAT_CAP`) |
| A3 | 1 | duplicated battle constants | partly done (see below) |
| C1 | 2 | delete `BCModelV3` and v3 branches | open |
| C3 | 2 | drop unread `encoder_v` checkpoint field | open |
| C4 | 2 | delete `load_checkpoint` tombstone comment | open |
| C5 | 2 | item/ability/gender residue in BC inference | open |
| C6 | 2 | repeated CHECKPOINT CONTRACT banners | mostly done (3 mentions in `bc_model.py`, 2 in `state_encoder.py`) |
| B1 | 3 | delete legacy `run_ga` | done 2026-10-16 |
| B2 | 3 | consolidate genome-repair passes | done 2026-11-18 (fuzz test first, then `repair_clauses`) |
| B3 | 3 | collapse `evaluate` / `_eval_on_subset` | partly done 2026-11-18, rest kept on purpose |
| B4 | 3 | one "top up population" helper | done 2026-11-18 |
| B5 | 3 | lazy-global singletons | open |
| D1-D8 | - | debt found after the split | open (section "New debt") |

## Tier 0 - real defects

**C2 (done).** The battle-level split ran twice in `src/bc_train.py`. Check:
`grep -c "battle-level split" src/bc_train.py` returns 1 (true today).

## Tier 1 - mechanical duplication

**A1 (done 2026-10-15).** `src/eval.py`, `src/bc_train.py`, `src/bc_player.py` and the GA
import `data_path` / `output_path` from `src/paths.py`; no local `_REPO_ROOT` / `_p()` left.

**A2 (stale).** The EV caps exist once, in `src/ga/operators.py` (`EV_BUDGET = 66`,
`EV_STAT_CAP = 32`). Nothing to do; re-grep before reviving.

**A3 (partly done).** Done: `FORMAT` and `UID_MAX` live in `src/ga/config.py`; `src/eval.py`
reuses them (`FORMAT = C.FORMAT`, `UID_MAX = C.UID_MAX`, `C` = `src.ga.config`). Still duplicated:
- battle timeout: `src/eval.py::TIMEOUT = 20` vs `GAConfig.battle_timeout = 20`;
- `GA_CONCURRENCY` is read in four places with two defaults: `src/eval.py` (3),
  `src/ga/engine.py::run_islands` default arg (3), `run/ga_run.py` (3), `run/ga_island.py`
  (8; `run/ga_parallel.sh` also sets 8).
Fix: read the timeout from `src.ga.config.DEFAULT.battle_timeout` in eval; decide one
concurrency default. Verify: `python -c "from src.eval import FORMAT as F1; from src.ga.config import FORMAT as F2; assert F1 == F2"`.

## Tier 2 - BC module cleanup (one PR; needs a retrain to fully verify)

Touches `src/bc_model.py`, `src/bc_train.py`, `src/bc_player.py`. Do not do it in the same
session as Tier 1 or right before a long GA run. The BC track is parked (BC is not used for
fitness), so this is low priority but safe line reduction. Checkpoint contract: no
state_dict key, `arch` value or dimension constant may be renamed or resized for v2.

**C1 - delete `BCModelV3` (open).** Still present: `src/bc_model.py::BCModelV3` and
`_TransformerBlock`; `src/bc_train.py` selects it with `BC_MODEL=v3` (`MODEL_ARCH`) and keeps
`is_v3` target accounting; `src/bc_player.py::_get_shared_model` instantiates it for
`arch == "v3"`. v3 was rejected 2026-10-13 (8.8% vs v2 19.4%). Verify: importing
`BCModelV3` fails, `BCModel` imports; `bc_best.pt` and `bc_heuristic_v1c.pt` (both v2) load;
a 5-battle BC smoke runs.

**C3 - drop `encoder_v` (open).** `src/bc_model.py::save_checkpoint` still writes it and no
loader reads it. Old checkpoints keep loading because nothing calls `.get("encoder_v")`.

**C4 - tombstone comment (open).** The `# NOTE: a generic load_checkpoint() lived here ...`
block at the end of `src/bc_model.py` documents a removed function. Delete it.

**C5 - inference residue (open).** `src/bc_player.py` `mon_view` always sends
`"item": None, "ability": None` (so the item/ability embeddings always see index 0) and
collects `"gender"`, which `encode_mon` never reads. Drop `gender` now; drop item/ability
embeddings only with a fresh (v4) retrain.

**C6 - banners (mostly done).** Optional final pass: one short contract note per file.

## Tier 3 - GA package (highest care, one item per session)

**B1 (done 2026-10-16).** `run_ga` deleted; `run_islands` is the only driver.

**B2 - genome-repair passes (done 2026-11-18).** First `tests/test_genome_clauses.py` (4
seeded tests: builds, crossover + mutate chains, `enforce_constraints` on genomes from other
islands, `ring_migrate`; asserts species clause, item clause, locks). On the old code it
failed: 58 species-clause violations from `enforce_constraints` (a genome holding the locked
species in a free slot came out with it twice and scored 0.0 as INVALID) and 4 from
`ring_migrate`. Then: crossover's two repair passes became `src/ga/operators.py::repair_clauses`
(same code, so crossover's RNG use is identical), `src/ga/legality.py::enforce_constraints`
calls it after rebuilding locked slots (the fix; draws from `random` only when it repairs
something), and `src/ga/population.py::_strip_species` uses the shared `_used_bases` /
`_used_items` instead of its nested copy. Golden master unchanged (its runs never hit the
bug), audit byte-identical. Construction-time clause logic (`build_random_genome`,
`mutate_species` picking unused species / items) stays where it is: it builds, it does not
repair. Remaining gap: `_pick_item_for` falls back to `Leftovers` even if taken (never seen
in the fuzz).

**B3 (partly done 2026-11-18).** Now `src/ga/evaluator.py::Evaluator.evaluate` (logs,
early-stops, validates) and `Evaluator.eval_on_subset` (no log, no early stop), sharing
`_start_battle` and `src/ga/fitness.py::weighted_fitness`. Kept as two methods on purpose.

**B4 (done 2026-11-18).** One helper `src/ga/population.py::_top_up`, used by
`Island.init_population` and `Island.breed`. The second top-up in `init_population` refills
genomes that `filter_legal_genomes` dropped; it is intended.

**B5 - lazy globals (open).** Four `global X; if X is None: X = load()` caches remain:
`src/ga/genome.py` `_MOVE_PRIORS` (`move_priors_for`), `_META_ITEMS` (`meta_items_for`);
`src/ga/pools.py` `_REGIONAL` (`regional_pool`), `_HELDOUT` (`heldout_pool`;
`tests/test_pools.py` resets these two by assignment, keep that working). A `functools.lru_cache` loader or a `_cached(name, loader)` helper removes
the boilerplate. `tests/test_ga_golden.py` must still pass unchanged.

## New debt (found 2026-11-18, open)

- **D1** Done 2026-11-18: `src/ga/genome.py` (834 lines) split into `genome.py` (398),
  `pools.py` (110), `legality.py` (182), `operators.py` (205); code moved verbatim by line
  range. Proven by the golden master and a seeded snapshot of every moved function (same
  JSON byte for byte before and after).
- **D2** Done 2026-11-18: `src/paths.py::showdown_port(env=None)` is the only parser of
  `SHOWDOWN_PORT`; `src/player_factory.py` (`DEFAULT_SERVER`), `GAConfig.from_env` and
  `run/ga_island.py` (`PORT`) call it (`tests/test_ga_config.py::test_showdown_port_has_one_parser`).
  Edge cases that changed: a zero-padded value (`08001`) now gives port 8001 in the URL, and
  a non-numeric value fails at import instead of building a bad URL.
- **D3** `tools/paired_eval.py` / `tools/paired_run.sh` restart Showdown themselves instead of
  using `src/showdown_server.py`.
- **D4** Done 2026-11-18: `GAConfig.__post_init__` rejects unknown pilot names
  (`PILOT_NAMES`), `train_sample_size < 1` and `early_stop_win_rate` outside [0, 1];
  `src/player_factory.py::make_player` raises ValueError for unknown names (was: silent
  `SimpleHeuristicsPlayer`). Since 2026-11-18 `run_battle_once` also logs any exception
  that kills a battle (see D7).
- **D5** Done 2026-11-18: every caller imports `src.ga.*` directly and `src/ga_core.py` was
  deleted (old name -> new module table: `docs/reference/ga-old-names.md`). Tests that
  used the facade wrappers now call the real functions (`Island.replace_worst`,
  `showdown_server.restart`, `fitness.weighted_fitness(..., DEFAULT.meta_weights)`).
- **D6** Done 2026-11-18: the `src/ga/engine.py` module docstring (order of breed vs
  restart / rescue), the `VAL_POOL_SIZE` comment in `src/ga/pools.py` (champion = train
  best) and the `src/eval.py` docstring + `--opponents` help ("300 training teams" -> the
  training pool, 148). The `_evolve_island` comment was already right.
- **D7** Replay logging: done 2026-11-18 (`src/replay_log.py`, `run_battle(log_sink=...)`,
  `Evaluator.evaluate(on_battles=...)`, `run_islands(replay_logger=...)`). Also done
  2026-11-18: `run_battle_once` no longer hides exceptions. The result is still `None` (so
  runs keep going and GA results are unchanged) but each one is logged by
  `_report_battle_error` (traceback for the first 3 per exception type, then every 100th as
  one line) and counted in `battle_error_counts()`; timeouts stay silent
  (`tests/test_battle_runner.py`).
- **D9** Done 2026-11-18: `TurnSim._run` (173 lines, 10 closures over 8 shared locals)
  moved to `src/turn_sim_resolve.py::Resolution`. Proven by recording every `_run` /
  `pair_value` result and LookAhead leaf state of the turn_sim tests bit for bit before and
  after (2197 records identical); `tests/test_turn_sim_paths.py` added first so every
  reachable line is executed. About 3% slower per `_run` call.
- **D10** Done 2026-11-18: `src/audit_before_launch.py::main` (206 lines) split into one
  `check_*` function per report section (`CHECKS`); report text byte-identical.
- **D11** Open, small: `src/bc_train.py::main` (154 lines) - leave until BC is kept or
  dropped. `src/regmc_db.py` (354 lines, 17 small functions) is fine as is.
- **D8** `tools/watch_islands.py` still detects stalls by log mtime (the 2026-10-15 flaw: a
  traceback loop looks alive); the planned fix was to look for `=== GEN` progress markers.

## Related docs

- [Design decisions](decisions.md)
- [Architecture and dependency map](../reference/architecture.md)
- [GA subsystem](../subsystems/ga.md)
- [BC subsystem](../subsystems/bc.md)
- [Tests](../reference/tests.md)
- [History index](../history/README.md)
