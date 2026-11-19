# GA old names (removed src/ga_core.py facade)

Where every name of the removed `src/ga_core.py` facade lives now. Use it when reading old
history entries, old branches or old notes that say `from src.ga_core import X` or `G.X`.

Last verified against code: 2026-11-18

`src/ga_core.py` re-exported the GA names after the package split and was deleted on
2026-11-18; every caller now imports the defining `src.ga.*` module. Nothing in `src/`,
`run/`, `tools/` or `tests/` imports `ga_core` any more.

| old `ga_core` name | now |
|---|---|
| `run_islands` | `src.ga.engine.run_islands` |
| `FORMAT`, `UID_MAX`, `CHECKPOINT_DIR`, `CHAMPION_DIR` | `src.ga.config.<same name>` |
| `BATTLE_TIMEOUT`, `MIN_TURNS`, `FITNESS_PILOT`, `FITNESS_OPP`, `META_WEIGHTS`, `TRAIN_SAMPLE_SIZE`, `EARLY_STOP_MIN_BATTLES`, `EARLY_STOP_WIN_RATE`, `SHOWDOWN_PORT`, `SHOWDOWN_DIR` | `src.ga.config.DEFAULT.<lowercase field>` (e.g. `DEFAULT.early_stop_win_rate`) |
| `_fitness(outcomes, opponents)` | `src.ga.fitness.weighted_fitness(outcomes, opponents, DEFAULT.meta_weights)` |
| `_opp_weight(opp_text)` | `src.ga.fitness.opp_weight(opp_text, DEFAULT.meta_weights)` |
| `regional_pool`, `heldout_pool`, `_split_train_val`, `_REGIONAL_DIR` | `src.ga.pools.<same name>` |
| `genome_to_text`, `text_to_genome`, `build_random_genome`, `_fresh_mon`, `_legal_items_for`, `_BASE_SPECIES`, `_SPECIES_BY_NAME`, `_ITEMS`, `_NATURES` | `src.ga.genome.<same name>` |
| `filter_legal_genomes`, `enforce_constraints` | `src.ga.legality.<same name>` |
| `mutate`, `crossover` | `src.ga.operators.<same name>` |
| `Island`, `ring_migrate`, `_strip_species` | `src.ga.population.<same name>` |
| `breed(island, rate)`, `inject_immigrants(island, n)`, `count_unique_species(island)` | `island.breed(rate)`, `island.replace_worst(n)`, `island.unique_species()` |
| `save_checkpoint`, `load_latest_checkpoint` | `src.ga.checkpoint.<same name>` |
| `restart_showdown(wait_s, tries)`, `ensure_showdown()`, `_showdown_up()` | `src.showdown_server.restart(DEFAULT.showdown_port, DEFAULT.showdown_dir, wait_s=, tries=)`, `.ensure(port, dir)`, `.is_up(port)` |

Code that did `from src import ga_core as G` usually needs three imports now, e.g.
`from src.ga import fitness as F`, `from src.ga.config import DEFAULT`,
`from src.ga.pools import regional_pool`.

## Related docs

- [../subsystems/ga.md](../subsystems/ga.md) - GA package: files, API, invariants
- [../subsystems/ga-genome.md](../subsystems/ga-genome.md) - genome.py and pools.py
- [../subsystems/ga-genome-operators.md](../subsystems/ga-genome-operators.md) - legality.py and operators.py
- [../history/README.md](../history/README.md) - dated history (old code paths)
