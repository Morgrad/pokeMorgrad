# GA genome: representation, priors, random teams, pools (src/ga/genome.py, src/ga/pools.py)

How a team is encoded for the GA, how random legal-looking teams are built from priors,
text <-> genome conversion, and where the opponent pools and the train/validation split
come from. Read this before touching team generation or pools. Mutation, crossover,
locks, Protect / Fake Out enforcement and the Showdown legality gate
(`src/ga/operators.py`, `src/ga/legality.py`) are in `ga-genome-operators.md`.

Last verified against code: 2026-11-18

## 1. Purpose

`src/ga/genome.py` and its three sibling modules are the GA's "team factory": every genome
that enters a population is built (`genome.py`), bred (`operators.py`) or repaired
(`legality.py`) there, and every opponent team comes from `pools.py`.
It also carries the team-realism layer added 2026-10-14 (meta items, role-committed
movesets, move priors, Protect and Fake Out coverage) that stops the GA from exploiting
pilot blind spots (dead items, no Protect, nonsense natures). Format facts it encodes:
`gen9championsvgc2026regmc`, Level 50, EVs 0-32 per stat, 66 total, no Tera.

## 2. Files

| path | lines | role |
|---|---|---|
| `src/ga/genome.py` | 398 | roster caches, `CANONICAL_ITEMS`, priors, `_legal_items_for`, `_species_role`, `_random_mon`, `_pick_item_for`, `_fresh_mon`, `build_random_genome`, `genome_to_text`, `text_to_genome` (sections 3-7) |
| `src/ga/pools.py` | 112 | `VAL_POOL_SIZE`, `VAL_SPLIT_SEED`, `_REGIONAL_DIR`, `_load_teams`, `regional_pool`, `_split_train_val`, `heldout_pool` (section 8) |
| `src/ga/legality.py` | 192 | legality gate, composition, locks (`ga-genome-operators.md`) |
| `src/ga/operators.py` | 220 | mutation and crossover (`ga-genome-operators.md`) |
| `src/regmc_db.py` | (see foundation.md) | species/items/moves/natures DB, `parse_team`, `validate_team`, `norm` |
| `src/showdown_validator.py` | 79 | `check_teams(texts)` -> `[(ok, msg)]` via `node src/showdown_validate.js`, md5 cache; raises `ValidatorError` if node fails as a whole |
| `data/species_move_priors.json` | - | move usage per species (191 species) |
| `data/meta_items.json` | - | item usage per species (94 species) |
| `data/pool_split.json` | - | `{"train": [148 file names], "holdout": [100 file names]}` |
| `data/regional_teams/*.txt` | 349 files | team pastes the split points to |

Until 2026-11-18 all four were one file, `src/ga/genome.py` (834 lines); the split moved
the code verbatim (golden master and a seeded snapshot of every function unchanged).
Dependencies: `legality` and `operators` import from `genome`; `pools` imports only
`src.paths`; nothing imports back (no cycles). Importers: `genome` <- `population`,
`evaluator`, `checkpoint`, `legality`, `operators`, `src/audit_before_launch.py`, tools;
`pools` <- `engine`, `src/eval.py`, `src/audit_before_launch.py`, tools; `legality` /
`operators` <- `population` (and the audit / dataset tool).

## 3. Representation

```
genome = [mon0, mon1, mon2, mon3, mon4, mon5]      # exactly 6, slot order matters for locks
mon = {"species": "Salamence", "item": "Salamencite", "ability": "Intimidate",
       "nature": "Jolly", "evs": {"hp": 2, "atk": 32, "spe": 32},
       "moves": ["Dragon Claw", "Double-Edge", "Protect", "Tailwind"]}
```

- `evs` keys are lowercase stat ids; zero stats are omitted. Totals are 66 for generated
  spreads; parsed seeds keep whatever the paste had.
- No gender, Tera, level or shiny fields; level is always written as 50.
- Genomes are plain JSON-serializable lists (stored as-is in checkpoints).

## 4. Module-level caches and constants

| name | module | value | meaning |
|---|---|---|---|
| `_BASE_SPECIES` | genome | 230 dicts | `DB.all_species_base()` (forme is None) that have moves |
| `_SPECIES_BY_NAME` | genome | dict | name -> species dict (keys `name`, `baseSpecies`, `moves`, `abilities`, `megaStones`, `baseStats`) |
| `_ITEMS` | genome | 166 | all DB items |
| `_NATURES` | genome | 25 | nature names |
| `CANONICAL_ITEMS` | genome | Leftovers, Sitrus Berry, Focus Sash, Life Orb, Choice Scarf, Choice Specs, Assault Vest, Rocky Helmet | item fallback |
| `_REGIONAL_DIR` | pools | `data/regional_teams` | where pool files are resolved |
| `VAL_POOL_SIZE` / `VAL_SPLIT_SEED` | pools | 30 / 42 | validation slice |
| `EV_BUDGET` / `EV_STAT_CAP` | operators | 66 / 32 | EV total and per-stat cap for `mutate_evs` |
| `MAX_REBUILD_TRIES` | legality | 20 | legality-gate rebuild attempts per genome |
| `PROTECT_MOVES` | legality | Protect, Detect, Spiky Shield, King's Shield, Baneful Bunker, Silk Trap, Burning Bulwark | Protect family |
| `FAKEOUT_MOVES` | legality | Fake Out, Follow Me, Rage Powder | turn-1 disruption / redirection |

Lazy globals loaded on first call and kept for the process: `_MOVE_PRIORS`, `_META_ITEMS`
(in `genome.py`), `_REGIONAL`, `_HELDOUT` (in `pools.py`; `tests/test_pools.py` resets
them). Consolidating them is open item B5 in `docs/design/refactor-roadmap.md`. Changing a
data file needs a new process.

## 5. Priors

- `move_priors_for(species, top_n=8)` -> `[(move, count), ...]` top 8 by tournament count
  from `species_move_priors.json`, or None. Example (2026-11-18): Umbreon ->
  `[("Snarl", 4), ("Foul Play", 3), ("Taunt", 3), ("Yawn", 1), ("Psychic", 1)]`.
- `meta_items_for(species)` -> `[(item, count), ...]` from `meta_items.json`, or None.
  Counts are raw weights for `random.choices`. Umbreon has no entry (falls to
  `CANONICAL_ITEMS`).
- There are no EV or nature priors in the GA: EVs and nature come from the role (below).
  `data/species_build_priors.json` is used by the opponent model, not by genome.py.
- History: 2026-10-15 notes found move priors came from about 5000 ladder replays while
  build/ability priors came from 560 tournament teams; 145 species had builds but no move
  priors and fall back to role-random moves.

## 6. Building a random mon / genome

`_legal_items_for(species)` -> tuple (lru_cached): all items except other species' mega
stones and `itemUser`-restricted items for other users; own mega stones included;
`("Leftovers",)` fallback.

`_species_role(sp)` -> `physical` | `special` | `support` from base Atk / SpA:
peak < 80 -> support (Umbreon 65/60); low < 80 -> the higher side (Gengar 65/130 ->
special); both >= 80 -> coin flip per genome (Salamence, Dragapult, Arcanine,
Archaludon). No `mixed` role by design. Consumes RNG only on the coin-flip branch.

`_random_mon(species)` -> mon or None:
1. Legal move list = species moves minus moves with `target == "randomNormal"` (Outrage,
   Thrash, Uproar...). Reason: the heuristic pilot sent those without a target in doubles,
   Showdown rejected the order (`Can't move: X needs a target`) and battles were lost to
   None. Needs >= 4 moves left, else None.
2. Role from `_species_role`.
3. Priors path: priors that are legal; if >= 4, keep only role-matching ones (on-role
   offensive or Status) when >= 4 remain; sample 4 without replacement weighted by count.
4. Fallback: `_preferred_pool` splits legal moves into preferred (on-role + Status) and
   fallback (off-role); sample 4 weighted `2 ** score` (score 3 on-role, 2 status, 1 off).
5. Spread by role (all total 66): physical `{"hp": 2, "atk": 32, "spe": 32}` Jolly; special
   `{"hp": 2, "spa": 32, "spe": 32}` Modest; support `{"hp": 32, "def": 20, "spd": 14}` Calm.
6. Item = random legal item (placeholder), ability = random species ability.
Measured 2026-10-14: with priors Umbreon got Snarl/Taunt/Foul Play/Psychic instead of
Copycat/Rest/Baby-Doll Eyes/Reflect.

`_pick_item_for(species, used_items)` -> item, in priority order: (1) an unused own mega
stone (always, for a mega species); (2) meta items legal and unused, weighted by count;
(3) `CANONICAL_ITEMS` legal and unused; (4) any legal unused item; else `Leftovers`.

`_fresh_mon(species, used_items)` = `_random_mon` + `_pick_item_for`.

`build_random_genome(constraints)` -> genome or None: fill locked slots first
(`ValueError` if the species is unknown or cannot be built), then each free slot from a
reshuffled roster skipping base species already used (species clause) and passing
`used_items` (item clause). Returns None if any slot stays empty.

## 7. Text <-> genome

- `genome_to_text(mons)` -> Showdown paste: `Species @ Item`, `Ability: X`, `Level: 50`,
  `<Nature> Nature`, `EVs: 32 HP / 32 ATK / 2 SPE` (`EVs: 0 HP` if empty), `- Move` x4,
  blank line per mon. This is the format every tool, eval and the validator consume.
- `text_to_genome(text)` -> genome via `DB.parse_team`; None unless exactly 6 mons. Keeps
  species, item, ability, nature, evs, moves only.

## 8. Pools and the train / validation / held-out split (src/ga/pools.py)

- `regional_pool()` -> list of team strings (cached): if `data/pool_split.json` exists,
  its `train` list, else every `data/regional_teams/*.txt` sorted.
- `heldout_pool()` -> 100 team strings from `holdout` (cached). Raises `RuntimeError` if
  `pool_split.json` is missing, its `holdout` list is empty, or a file is in both `train`
  and `holdout` (compared by basename). Fixed 2026-11-18: a missing split file silently
  returned the TRAINING pool, so a "held-out" score could be a training score.
  `tests/test_pools.py` pins this.
- `_load_teams(files, label)`: resolves each entry by BASENAME under
  `data/regional_teams/` (old split files held absolute paths from another host). Prints
  `WARNING: <label> pool: k/n teams failed to load` for missing/empty files; raises
  `RuntimeError` if none load (a silently empty pool once looked like a 0% eval).
- `_split_train_val(pool, val_size=30, seed=42)` -> `(train, val)`: shuffles indices with
  `random.Random(42)`, by index not by string (pool teams can repeat), union = pool. On
  2026-11-18: 118 train, 30 val. Deterministic, so resumes see the same split.
- Current pool (swapped 2026-10-15): 148 VGCPastes teams with real EV spreads
  (`vgc_MC*.txt`) for training, 100 `real_ev_*.txt` held out. Pool tooling (swap, extend,
  regenerate split) is in `../runbooks/data-pipeline.md`.

## 9. Tests

- `tests/test_ga_golden.py`: pins `Island.init_population`, `breed`, `replace_worst`,
  `ring_migrate`, checkpoint round trip and RNG state for seeded runs; all genome code is
  covered indirectly. Needs `PYTHONHASHSEED=0` (handled by the test).
- `python -m src.audit_before_launch` (last step of `tools/verify.sh`; one `check_*`
  function per report section, see `../runbooks/health-check.md`): DB and name
  sanity, mega-stone integrity, `_legal_items_for` samples, pool validity, then fuzz:
  500 Umbreon-locked + 500 free `build_random_genome`, 2000 chained `mutate` on a locked
  genome (lock must hold), 500 `crossover`, each checked with `DB.validate_team` (species
  and item clause, EV caps, learnable moves). Any hard failure (fuzz / mutation /
  crossover failures, broken lock, illegal items / stones / natures, invalid regional or
  baseline team) makes it print `AUDIT FAILED: N problem(s)` and exit 1, which fails the
  gate. Fixed 2026-11-18: it used to exit 0 regardless. Species with fewer than 4 moves are a
  warning only (Ditto has only Transform).
- `tools/verify.sh` step `pools` prints `len(regional_pool()), len(heldout_pool())` (`148 100`).
- `tests/test_pools.py` (3 tests): real split disjoint and sized; `heldout_pool` raises on a
  missing, empty or overlapping split.
- `tests/test_ga_injection.py` (4 tests) covers `Island.inject_fresh` / `ring_migrate` slots.
- `tests/test_genome_clauses.py` (4 tests, about 1 s): species clause, item clause and locks
  hold after `build_random_genome`, crossover + mutate chains, `enforce_constraints` on
  genomes from other islands, and `ring_migrate` (refactor B2, 2026-11-18).

## 10. Gotchas

- `_random_mon` and `mutate_move` exclude `randomNormal` moves, but opponent pool teams can
  still contain Outrage. The old STATE.md (2026-10-15) proposed stripping it in `_load_teams`; the
  current code does not.
- Roles only approximate natures; there is no nature data source.
- Known gaps (2026-10-14, still open): no offensive type-coverage constraint, no meta
  species bias (any of 230 base species), no team-synergy check (e.g. Psychic Seed off a
  Psychic Terrain team).
- The code iterates sets in places, so exact genomes depend on `PYTHONHASHSEED`.

## 11. How to change safely

1. Any change to RNG use (an extra `random` call, a different order) changes every seeded
   population and the golden fixture; regenerate deliberately
   (`PYTHONHASHSEED=0 python tests/golden/ga_harness.py --write`) and say so in the commit.
2. Keep `_legal_items_for` returning a tuple (it is cached; a list could be mutated).
3. Keep the `randomNormal` filter in both `_random_mon` and `mutate_move`.
4. `tools/preflight.py` greps `src/ga/` for `_species_role`, `_preferred_pool`,
   `_enforce_composition`, `move_priors_for`, `CANONICAL_ITEMS`, `VAL_POOL_SIZE`,
   `early_stop_min_battles`; renaming them fails preflight.
5. Changing pools: edit `data/pool_split.json` via the pool tools, not by hand; the GA
   resolves by basename.
6. Run `python tests/test_ga_golden.py` and `bash tools/verify.sh`.

## Related docs

- [ga-genome-operators.md](ga-genome-operators.md) - mutate, crossover, locks, Protect/Fake Out, legality gate
- [ga.md](ga.md) - GA package overview and invariants
- [ga-loop.md](ga-loop.md) - where these functions are called each generation
- [foundation.md](foundation.md) - regmc_db (species, items, validate_team)
- [battle-harness.md](battle-harness.md) - showdown_validator / showdown_validate.js
- [../reference/data-files.md](../reference/data-files.md) - priors and pool files
- [../runbooks/data-pipeline.md](../runbooks/data-pipeline.md) - priors, pool swap, split
