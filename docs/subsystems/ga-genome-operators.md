# GA genome operators: mutate, crossover, locks, composition, legality gate (src/ga/operators.py, src/ga/legality.py)

The genetic operators and repair steps: mutation ops and crossover
(`src/ga/operators.py`, 205 lines), and in `src/ga/legality.py` (182 lines)
`enforce_constraints` (locked slots such as Umbreon in slot 0), the Protect and Fake Out
composition rule and `filter_legal_genomes` (the real Showdown validator gate). Read this
before changing how teams are bred or repaired. Representation, priors, random builds
(`src/ga/genome.py`) and pools (`src/ga/pools.py`): `ga-genome.md`. Both modules were part
of `src/ga/genome.py` until 2026-11-18 (moved verbatim).

| module | names |
|---|---|
| `src/ga/operators.py` | `EV_BUDGET`, `EV_STAT_CAP`, `_used_bases`, `_used_items`, `mutate_species`, `mutate_item`, `mutate_ability`, `mutate_nature`, `mutate_evs`, `mutate_move`, `mutate`, `crossover` |
| `src/ga/legality.py` | `MAX_REBUILD_TRIES`, `PROTECT_MOVES`, `FAKEOUT_MOVES`, `_force_move_on_slot`, `_enforce_composition`, `filter_legal_genomes`, `enforce_constraints` |

Both import their building blocks (`_fresh_mon`, `_random_mon`, `_pick_item_for`,
`_legal_items_for`, `build_random_genome`, `genome_to_text`, roster caches) from
`src/ga/genome.py`.

Last verified against code: 2026-11-18

## Key facts (repeated from ga-genome.md)

- Genome = list of 6 mon dicts `{species, item, ability, nature, evs, moves}`; EVs omit
  zero stats; generated spreads total 66 with at most 32 per stat.
- constraints = `{slot: species}`, e.g. `{0: "Umbreon"}`; locked slots never mutate.
- Species clause = no two mons with the same base species (compared with `DB.norm` of
  `baseSpecies`); item clause = no duplicate items.
- `_fresh_mon(species, used_items)` builds one mon (priors / role moves, role spread,
  `_pick_item_for` item that avoids `used_items`).
- All randomness uses the global `random` module; order is pinned by
  `tests/test_ga_golden.py`.

## 1. Where operators are called

- `Island.init_population`: seed -> `enforce_constraints`; random top-up
  (`build_random_genome`); `filter_legal_genomes`; top-up again (not gated).
- `Island.breed`: elites `enforce_constraints(deepcopy)`; children
  `mutate(crossover(p1, p2, c), c)`; immigrants `build_random_genome`; then
  `filter_legal_genomes` on the whole new population; top-up (not gated).
- `Island.inject_fresh` (stagnation restart / diversity rescue, right after breed):
  `build_random_genome` into the children's slots (not gated). `Island.replace_worst`
  (golden harness only): same, into the lowest-fitness slots.
- `ring_migrate`: `enforce_constraints` + `_strip_species` (not gated).
- `Evaluator.evaluate`: `DB.validate_team` (local DB check); an invalid genome scores 0.0.

## 2. Mutation

`mutate(mons, constraints, n=None)` -> new genome (deep copy; parent untouched).
`free_slots` = slots not in constraints (none -> return the copy unchanged).
`n = n or random.randint(1, 4)` ops; each op = `random.choice` of the six below, applied to
`random.choice(free_slots)`.

| op | effect | respects |
|---|---|---|
| `mutate_species(mons, slot, constraints)` | new species not already on the team (base species), >= 4 moves; fresh `_random_mon`, item via `_pick_item_for` | species + item clause; `constraints` arg unused |
| `mutate_item(mons, slot)` | uniform random legal item not used elsewhere | item clause; NOT meta-weighted |
| `mutate_ability(mons, slot)` | another ability of the species (no-op if only one) | - |
| `mutate_nature(mons, slot)` | any other of the 25 natures | ignores role |
| `mutate_evs(mons, slot)` | re-roll: random stats get 32-point chunks until 66 spent | always ends as two stats at 32 and one at 2 |
| `mutate_move(mons, slot)` | replace one of the 4 moves (random index) with a random learnable move not already known, excluding `randomNormal` | ignores priors and role; may overwrite Protect |

Why `mutate_move` excludes `randomNormal`: 2026-10-15, run p2 island A, Outrage orders
without a target were rejected by Showdown, cascading into socket death and an infinite
retry loop.

Consequence: mutation can reintroduce what the build step avoids (off-meta items, a mega
species losing its stone, natures that contradict the spread). Composition (Protect /
Fake Out) is restored at the legality gate, items are not.

## 3. Crossover

`crossover(p1, p2, constraints)` -> child:
1. Locked slot: copy from whichever parent holds the mandated species (p1 first); if
   neither, `_fresh_mon(want, set())` (`ValueError` if it cannot be built).
2. Free slot: deep copy of `random.choice([p1[i], p2[i]])`.
3. Species clause repair: base species of locked slots are reserved first; any free slot
   whose base species was already seen is re-rolled with `mutate_species`.
4. Item clause repair: walking slots in order, a duplicate item is replaced with
   `_pick_item_for(species, seen_items)` (the earlier slot keeps it).

## 4. Locks: enforce_constraints and _strip_species

`enforce_constraints(genome, constraints)` -> new genome (input returned as-is if no
constraints or empty genome). For each locked slot whose species differs, the slot is
rebuilt with `_fresh_mon(want, used_items)` (`used_items` includes every current item,
also the one being replaced). Then `repair_clauses(g, constraints)` (below) fixes the
species and item clauses, e.g. a free slot that already held the locked species is
re-rolled. Fixed 2026-11-18: without that repair the genome had the locked species twice;
`init_population` / `breed` caught it at the legality gate, but `ring_migrate` did not and
the evaluator scored it 0.0 as INVALID.

`operators.repair_clauses(mons, constraints)` (the one shared clause repair, used by
`crossover` and `enforce_constraints`): base species of locked slots are reserved; free
slots in order, a repeated base species is re-rolled with `mutate_species`; then all slots
in order, a repeated item is re-picked with `_pick_item_for` (the earlier slot keeps it).
Edits in place and draws from `random` only when it repairs something.

Island locks in the launchers (2026-11-18): A = `{0: "Umbreon"}` + baseline seed,
B = `{0: "Umbreon"}`, C = `{}` (both `run/ga_run.py` and `run/ga_island.py`). Umbreon is
in slot 0 of `data/baseline_team.txt`.

`src/ga/population.py::_strip_species(genome, species_set, constraints)`: used by
`ring_migrate` to replace any free-slot mon whose species is in `species_set` (locked on
the source island, not on the destination) with a fresh mon of a species that is not in
the set, not a base species already on the team, and has >= 4 moves. Fix for the
2026-10-12 leak where Umbreon from a locked island spread into free islands and diversity
collapsed.

## 5. Composition rule: Protect and Fake Out (`_enforce_composition`)

Applied in place to every genome that LEAVES `filter_legal_genomes` (single choke point
shared by init and breed). Soft and idempotent:
- If no mon has a `PROTECT_MOVES` move: shuffle slot order, and on the first slot whose
  species learns one, `_force_move_on_slot` puts the first learnable Protect-family move
  over the first move that is neither Protect-family nor Fake Out-family (slot 0 move if
  all four are).
- Same for `FAKEOUT_MOVES` (Fake Out, Follow Me, Rage Powder).
- If no mon can learn one, the genome passes unchanged. Locked slots are eligible (species
  is preserved).
- The edit happens AFTER validation, so the modified genome is not re-validated (moves come
  from the species' learnset, so it should stay legal).
Why (2026-10-13/14): champions scoring 66-71% vs the old heuristic pilot had no Protect,
no Fake Out, dead items (`Umbreon @ Binding Band`, `Garchomp @ Heat Rock`) - they
exploited pilot blind spots. Expected effect: lower but more meaningful scores.

## 6. Legality gate: filter_legal_genomes

`filter_legal_genomes(genomes, constraints)` -> list of legal genomes (input order kept;
may be shorter):
1. One batched `SV.check_teams` call (Node `src/showdown_validate.js`, real Showdown
   TeamValidator, results cached by md5 of the text).
2. Each failing slot gets up to `MAX_REBUILD_TRIES` = 20 rebuilds with
   `build_random_genome(constraints)` (a None build still burns a try). Rebuilds are
   validated per ROUND in one batched call (worst case 21 validator spawns per call).
3. Slots that never pass are dropped; the caller tops up (without the gate).
4. `_enforce_composition` on every survivor.
An illegal child is replaced by a brand-new random genome, not repaired. The gate caught,
historically: Greninja-Bond / Battle Bond, Meowstic/Competitive, Covert Cloak, Assault Vest
legality, duplicate moves, unknown species. Measured 2026-10-13: 0 invalid in 3500 fuzz
genomes.

## 7. Gotchas

- If `node` cannot run (`OSError`, 60 s `TimeoutExpired`), exits non-zero, or returns a
  different number of verdicts than teams, `check_teams` raises `ValidatorError`
  (a `RuntimeError`, message includes node's stderr) and caches nothing; the GA island /
  `filter_legal_genomes` crashes loudly. So a host without a built Showdown checkout
  (`$SHOWDOWN_DIR/dist/`) cannot build populations. Per-team `ERR:` verdicts are returned as
  failures but not cached. Fixed 2026-11-18: a node failure became a cached "illegal"
  verdict, every genome was rebuilt 20 times, dropped, and the population was refilled with
  unvalidated random genomes (`tests/test_showdown_validator.py`).
- Clause REPAIR lives in one place, `operators.repair_clauses` (refactor B2, 2026-11-18).
  Clause-aware CONSTRUCTION is separate on purpose: `genome.build_random_genome`,
  `operators.mutate_species` and `population._strip_species` pick species / items not
  already used (`operators._used_bases` / `_used_items`). `tests/test_genome_clauses.py`
  asserts the clauses and locks after every one of these paths. Known gap:
  `_pick_item_for` returns `Leftovers` as a last resort even if taken (never hit in the fuzz).
- `mutate_species` draws from all 230 base species, not from meta species.

## 8. How to change safely

1. Run the clause fuzz first: `python tests/test_genome_clauses.py` (asserts species /
   item clauses and locks after build, crossover + mutate, `enforce_constraints`,
   `ring_migrate`), then `python -m src.audit_before_launch` (Showdown-rule validity via
   `DB.validate_team`; exits 1 with `AUDIT FAILED: N problem(s)`).
2. Keep `filter_legal_genomes` as the single place where `_enforce_composition` runs.
   `filter_legal_genomes` calls the validator as `SV.check_teams` (module attribute, the
   golden harness patches it) and `build_random_genome` from `src.ga.genome`; tests that
   want a different gate patch `src.ga.population.filter_legal_genomes` instead.
3. Keep the per-slot try budget semantics (None build burns a try) and input ordering;
   the golden test pins the resulting populations.
4. Any change in RNG consumption changes golden output: regenerate only on purpose with
   `PYTHONHASHSEED=0 python tests/golden/ga_harness.py --write`.
5. Run `python tests/test_ga_golden.py` and `bash tools/verify.sh` (`ALL PASS`).

## Related docs

- [ga-genome.md](ga-genome.md) - representation, priors, random builds, pools
- [ga.md](ga.md) - GA package overview, invariants, known bugs
- [ga-loop.md](ga-loop.md) - generation loop that calls these operators
- [battle-harness.md](battle-harness.md) - showdown_validator and showdown_validate.js
- [foundation.md](foundation.md) - regmc_db (validate_team, norm, species data)
- [../design/refactor-roadmap.md](../design/refactor-roadmap.md) - B2 (done) / B5 refactors
